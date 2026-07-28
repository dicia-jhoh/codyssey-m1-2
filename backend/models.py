"""Pydantic 모델 — 요청·응답 스키마.

**왜 Pydantic 인가**: FastAPI 는 이 모델로 ① 요청 본문을 자동 검증하고 ② 잘못된 요청에
422 와 **어느 필드가 왜 틀렸는지**를 돌려주며 ③ Swagger 문서를 자동 생성한다.
직접 `if not body.get("value")` 를 쓰면 셋 다 손으로 해야 한다.

검증을 **입구에서** 하는 이유: 잘못된 값이 저장소까지 흘러가면 나중에 통계가 틀리고,
그때는 원인이 입력에 있다는 게 보이지 않는다.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DataPointIn(BaseModel):
    """데이터 1건 입력 — POST /api/data · PUT /api/data/{id}"""

    period: str = Field(..., description="관측 시점 YYYY-MM 또는 YYYY-MM-DD", examples=["1961-01"])
    value: float = Field(..., gt=0, description="관측값(양수)", examples=[450.0])
    note: str | None = Field(None, max_length=200, description="메모(선택)")

    @field_validator("period")
    @classmethod
    def validate_period(cls, value: str) -> str:
        """YYYY-MM 또는 YYYY-MM-DD 만 받는다.

        정규식 대신 `date.fromisoformat` 로 검사하는 이유: 형식이 맞아도 존재하지 않는
        날짜(2026-02-30)를 걸러야 한다. YYYY-MM 은 1일을 붙여 확인한다.
        """
        text = value.strip()
        try:
            date.fromisoformat(text if len(text) == 10 else f"{text}-01")
        except ValueError:
            raise ValueError("period 는 YYYY-MM 또는 YYYY-MM-DD 형식이어야 합니다") from None
        return text


class DataPointOut(DataPointIn):
    """데이터 1건 출력 — 저장소가 매긴 id 와 생성 시각이 붙는다."""

    id: str
    created_at: str


class MessageIn(BaseModel):
    """대화 메시지 한 줄."""

    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1, max_length=4000)


class ConversationIn(BaseModel):
    """대화 저장 — POST /api/conversations"""

    title: str = Field(..., min_length=1, max_length=100)
    messages: list[MessageIn] = Field(..., min_length=1)


class ConversationOut(BaseModel):
    """대화 출력.

    ⚠ **목록 조회에서는 `messages` 를 비운다**(미션 요구 (B) 방식). 대화가 쌓이면 목록
    응답이 급격히 커지기 때문이다. 전체 내용은 `GET /api/conversations/{id}` 로 받는다
    — (A) 방식도 함께 구현했으므로 "불러오기" UX 가 가능하다.
    """

    id: str
    title: str
    created_at: str
    message_count: int
    messages: list[MessageIn] = Field(default_factory=list)


class ChatIn(BaseModel):
    """AI 대화 요청 — POST /api/chat"""

    message: str = Field(..., min_length=1, max_length=1000, description="사용자 질문")
    conversation_id: str | None = Field(None, description="이어 갈 대화 id(없으면 새로 만든다)")


class ChatOut(BaseModel):
    """AI 대화 응답."""

    reply: str
    conversation_id: str
    used_summary: bool = Field(..., description="시스템 프롬프트에 데이터 요약이 들어갔는지")
    tool_calls: list[str] = Field(default_factory=list, description="AI 가 호출한 도구 이름")


class SummaryOut(BaseModel):
    """데이터 요약 — GET /api/data/summary. 이 값이 시스템 프롬프트에 들어간다."""

    count: int
    period_from: str | None
    period_to: str | None
    mean: float | None
    minimum: float | None
    maximum: float | None
    trend: Literal["증가", "감소", "유지", "판단 불가"]
    trend_basis: str = Field(..., description="추세를 그렇게 판단한 근거")
    latest_value: float | None
    change_pct: float | None = Field(None, description="최근 구간 변화율(%)")
