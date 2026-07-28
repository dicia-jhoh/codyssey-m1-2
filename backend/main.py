"""FastAPI 앱 — 라우터를 모으고 CORS 를 설정한다.

실행: `uvicorn backend.main:app --reload`
문서: http://localhost:8000/docs (Swagger UI)

**구조를 나눈 기준**:
  routers/   HTTP 를 다룬다 — 경로·상태 코드·요청 검증
  services/  계산을 한다 — 통계·프롬프트·AI 호출
  db.py      저장한다 — Firestore 또는 로컬
  models.py  주고받는 모양을 정한다

이렇게 나누면 **바뀌는 이유가 섞이지 않는다.** 통계 공식을 고칠 때 HTTP 를 건드리지
않고, 저장소를 바꿀 때 라우터를 건드리지 않는다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, db
from .routers import chat, conversations, data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("m1_2")

config.load_dotenv()

app = FastAPI(
    title="시계열 데이터 AI Agent API",
    version="1.0.0",
    description=(
        "시계열 데이터를 저장하고, 그 **요약을 시스템 프롬프트에 주입**해 GPT 와 "
        "대화하는 API 입니다.\n\n"
        "- 데이터 CRUD + 요약 (`/api/data`)\n"
        "- 대화 저장·조회·삭제 (`/api/conversations`)\n"
        "- AI 대화 (`/api/chat`) — 요약 주입 + 도구 호출\n\n"
        "⚠ 무료 티어(Render)는 일정 시간 요청이 없으면 잠들었다가 다음 요청에 깨어납니다. "
        "**첫 요청은 30초 이상 걸릴 수 있습니다.**"
    ),
)

# CORS — 프론트(Vercel)와 백엔드(Render)가 다른 도메인이라 반드시 필요하다.
# `*` 를 쓰지 않는 이유: 아무 사이트나 이 API 를 부를 수 있게 되고, 쿠키를 쓰는 순간
# 브라우저가 거부한다. 허용 도메인은 환경 변수로 준다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(data.router)
app.include_router(conversations.router)
app.include_router(chat.router)


@app.get("/", tags=["health"], summary="헬스체크")
def health() -> dict:
    """서버 상태와 **현재 어느 저장소를 쓰는지**를 알려 준다.

    저장소 종류를 노출하는 이유: 배포 후 "왜 데이터가 안 남지?" 를 여기서 바로 확인할 수
    있다. Firestore 키가 잘못 설정되면 `local` 이 뜬다.
    """
    return {
        "status": "ok",
        "storage": db.repository_kind(),
        "ai_ready": config.get_openai_key() is not None,
        "docs": "/docs",
    }


@app.on_event("startup")
def on_startup() -> None:
    """시작 시 저장소를 한 번 붙여 본다 — 문제가 있으면 첫 요청이 아니라 여기서 로그에 뜬다."""
    logger.info("저장소: %s", db.repository_kind())
    if config.get_openai_key() is None:
        logger.warning("%s", config.missing_key_message(config.OPENAI_KEY_NAME, "AI 대화"))
