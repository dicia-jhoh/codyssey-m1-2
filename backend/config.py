"""설정 — 환경 변수 한 곳에서 읽는다.

**키는 코드에 절대 두지 않는다.** 이름만 알고 값은 환경에서 받는다. 배포(Render)에서는
대시보드의 Environment 에, 로컬에서는 `.env` 파일에 넣는다.

Firestore 서비스 계정은 **JSON 문자열 자체**를 환경 변수로 받는 방식을 기본으로 한다.
파일 경로 방식은 배포 환경에 파일을 올려야 해서 번거롭고, 실수로 저장소에 커밋될 위험이
있다. 문자열이면 그런 파일이 아예 없다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# 값이 아니라 **이름만** 코드에 둔다.
COPA_KEY_NAME = "COPA_API_KEY"
FIREBASE_JSON_NAME = "FIREBASE_SERVICE_ACCOUNT_JSON"
FIREBASE_PATH_NAME = "FIREBASE_SERVICE_ACCOUNT_PATH"  # 대안: 파일 경로
ALLOWED_ORIGINS_NAME = "ALLOWED_ORIGINS"

# 코드시세이 공식 게이트웨이(copa) — 기관 키로 정산되는 Anthropic 호환 엔드포인트.
# ⚠ 끝에 /v1 을 붙이지 않는다 — anthropic SDK가 자체적으로 /v1/messages 를 이어 붙여서,
# base_url에 /v1 이 있으면 /v1/v1/messages 로 겹쳐 403(public_api_scope_denied)이 난다.
COPA_BASE_URL = "https://copa.codyssey.kr"
DEFAULT_MODEL = "claude-haiku-4"
# 응답 길이를 묶어 요금과 대기시간을 예측 가능하게 만든다(미션 요구: 토큰 제한).
MAX_TOKENS = 600
REQUEST_TIMEOUT = 60

# Firestore 를 못 쓸 때 쓰는 로컬 저장소. 개발·채점 재현용이며 배포에서는 Firestore 를 쓴다.
LOCAL_STORE_DIR = Path(os.environ.get("LOCAL_STORE_DIR", "data/local_store"))


def load_dotenv(path: str = ".env") -> None:
    """`.env` 를 환경 변수로 올린다. 이미 있는 값은 덮어쓰지 않는다(플랫폼 설정이 우선)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def get_copa_key() -> str | None:
    """copa(코드시세이 공식 게이트웨이) 키. 없으면 None — 호출한 쪽이 안내한다."""
    return os.environ.get(COPA_KEY_NAME, "").strip() or None


def get_firebase_credentials() -> dict | None:
    """서비스 계정 자격 → dict(없으면 None).

    두 경로를 지원한다: JSON 문자열(권장) 또는 파일 경로. 어느 쪽도 없으면 None 을
    돌려주고, 저장소 계층이 로컬 파일 저장소로 **자동 전환**한다.
    """
    raw = os.environ.get(FIREBASE_JSON_NAME, "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 잘못된 JSON 을 조용히 무시하면 "왜 Firestore 가 안 붙지" 를 찾기 어렵다
            raise ValueError(
                f"{FIREBASE_JSON_NAME} 가 올바른 JSON 이 아닙니다. "
                "서비스 계정 키 파일 내용을 그대로 한 줄로 넣었는지 확인하세요."
            ) from None

    path = os.environ.get(FIREBASE_PATH_NAME, "").strip()
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def get_allowed_origins() -> list[str]:
    """CORS 허용 출처 목록.

    **왜 필요한가**: 프론트(Vercel)와 백엔드(Render)가 다른 도메인에 있다. 브라우저는
    기본적으로 다른 출처로의 요청을 막으므로(동일 출처 정책), 서버가 "이 출처는 허용한다"고
    응답 헤더로 알려 줘야 한다.

    기본값에 로컬 개발 주소를 넣어 두는 이유: 설정을 깜빡해도 로컬에서는 돌아가야 한다.
    운영 도메인은 반드시 환경 변수로 준다 — **`*` 를 쓰지 않는다.**
    """
    raw = os.environ.get(ALLOWED_ORIGINS_NAME, "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
    ]


def missing_key_message(name: str, what: str) -> str:
    """키가 없을 때의 안내문. ⚠ 실제 키 값은 어디에도 출력하지 않는다."""
    return (
        f"환경 변수 {name} 가 없어 {what} 를 사용할 수 없습니다. "
        f"로컬은 .env 파일에, 배포는 플랫폼 환경 변수에 설정하세요(값은 YOUR_KEY 자리)."
    )
