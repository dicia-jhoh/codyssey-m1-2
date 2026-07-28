"""대화 라우터 — POST /api/chat.

**미션이 정한 흐름을 그대로 구현한다**:
  ① 데이터 요약 조회 → ② 시스템 프롬프트에 삽입 → ③ GPT 호출 → ④ 대화 자동 저장

자동 저장이 이 엔드포인트에 있는 이유: 사용자가 "저장" 버튼을 누르기를 기다리면 대부분
저장되지 않는다. 대화는 **일어난 사실**이므로 그 자리에서 남기는 편이 맞다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from .. import db
from ..models import ChatIn, ChatOut
from ..services import ai as ai_service
from ..services import summary as summary_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

TITLE_MAX = 40


@router.post("", response_model=ChatOut, summary="AI 대화")
def chat(payload: ChatIn) -> ChatOut:
    """질문을 받아 데이터 요약을 넣고 GPT 에 묻는다. 대화는 자동 저장된다."""
    repository = db.get_repository()
    documents = repository.list(db.COLLECTION_DATA)

    # ① 이어 갈 대화가 있으면 이전 메시지를 불러온다(맥락 유지)
    history: list[dict] = []
    conversation = None
    if payload.conversation_id:
        conversation = repository.get(db.COLLECTION_CONVERSATIONS, payload.conversation_id)
        if conversation is None:
            raise HTTPException(
                status_code=404,
                detail=f"대화를 찾을 수 없습니다: {payload.conversation_id}",
            )
        history = conversation.get("messages") or []

    # ②③ 요약 주입 + GPT 호출
    try:
        reply, used_tools = ai_service.chat(payload.message, history, documents)
    except ai_service.AIUnavailable as exc:
        # 503 — 서버는 살아 있지만 외부 의존(AI)을 쓸 수 없다는 뜻
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # ④ 대화 저장 — 이어 가는 중이면 갱신, 새 대화면 생성
    messages = [*history,
                {"role": "user", "content": payload.message},
                {"role": "assistant", "content": reply}]

    if conversation:
        repository.update(db.COLLECTION_CONVERSATIONS, conversation["id"],
                          {"messages": messages})
        conversation_id = conversation["id"]
    else:
        # 제목은 첫 질문에서 딴다 — 사용자가 목록에서 알아볼 수 있어야 한다
        title = payload.message.strip().replace("\n", " ")[:TITLE_MAX]
        record = repository.add(db.COLLECTION_CONVERSATIONS,
                                {"title": title or "새 대화", "messages": messages})
        conversation_id = record["id"]

    data_summary = summary_service.compute_summary(documents)
    return ChatOut(
        reply=reply,
        conversation_id=conversation_id,
        used_summary=data_summary["count"] > 0,
        tool_calls=used_tools,
    )
