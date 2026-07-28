"""대화 라우터 — 저장·목록·상세·삭제.

**목록과 상세를 나눈 이유**(미션 요구 (A)·(B) 둘 다 충족): 대화가 쌓이면 목록 응답에
모든 메시지를 담을 때 응답이 급격히 커진다. 목록은 제목·개수만, 전체 내용은 상세에서.
프론트의 "대화 불러오기"는 목록에서 고른 뒤 상세를 부르는 흐름이다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .. import db
from ..models import ConversationIn, ConversationOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut], summary="대화 목록 조회")
def list_conversations() -> list[ConversationOut]:
    """대화 목록. **messages 는 비워서 돌려준다**(응답 크기 관리 — 미션 (B) 방식).

    전체 메시지가 필요하면 `GET /api/conversations/{id}` 를 쓴다.
    """
    documents = db.get_repository().list(db.COLLECTION_CONVERSATIONS)
    return [_to_out(d, include_messages=False) for d in documents]


@router.get("/{conversation_id}", response_model=ConversationOut, summary="대화 상세 조회")
def get_conversation(conversation_id: str) -> ConversationOut:
    """대화 1건의 **전체 messages** 를 돌려준다(미션 (A) 방식 — 불러오기 UX)."""
    document = db.get_repository().get(db.COLLECTION_CONVERSATIONS, conversation_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"대화를 찾을 수 없습니다: {conversation_id}")
    return _to_out(document, include_messages=True)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED,
             summary="대화 저장")
def create_conversation(payload: ConversationIn) -> ConversationOut:
    """대화를 저장한다. `/api/chat` 이 자동으로 부르지만, 직접 부를 수도 있다."""
    record = db.get_repository().add(db.COLLECTION_CONVERSATIONS, {
        "title": payload.title,
        "messages": [m.model_dump() for m in payload.messages],
    })
    return _to_out(record, include_messages=True)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="대화 삭제")
def delete_conversation(conversation_id: str) -> None:
    """대화 1건을 삭제한다. 없으면 404."""
    if not db.get_repository().delete(db.COLLECTION_CONVERSATIONS, conversation_id):
        raise HTTPException(status_code=404, detail=f"대화를 찾을 수 없습니다: {conversation_id}")


def _to_out(document: dict, *, include_messages: bool) -> ConversationOut:
    """저장소 문서 → 응답 모델. message_count 는 항상 채운다."""
    messages = document.get("messages") or []
    return ConversationOut(
        id=str(document.get("id", "")),
        title=str(document.get("title", "(제목 없음)")),
        created_at=str(document.get("created_at", "")),
        message_count=len(messages),
        messages=messages if include_messages else [],
    )
