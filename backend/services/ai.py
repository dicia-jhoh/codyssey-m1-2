"""AI 대화 — 컨텍스트 주입 + 도구 호출(Function Calling).

**두 가지 방식이 공존한다**:
  ① 컨텍스트 주입 — 요약을 **미리** 시스템 프롬프트에 넣는다. 항상 필요한 정보에 맞다.
  ② 도구 호출     — 모델이 **필요할 때** 함수를 부른다. 요청마다 다른 정보에 맞다.

①만 쓰면 "3월 데이터 몇 개야?" 같은 질문에 답할 수 없다(요약에 없으니까). 그렇다고
데이터 전체를 프롬프트에 넣으면 매 요청 토큰이 커진다. **②가 그 사이를 메운다** —
모델이 판단해서 필요한 것만 가져온다.

`anthropic` 패키지로 코드시세이 공식 게이트웨이(copa)를 쓰되, 없거나 키가 없으면
**명확한 안내와 함께 실패**한다. 조용히 가짜 답을 만들지 않는다 — 사용자가 AI 답변인
줄 알면 안 된다.
"""

from __future__ import annotations

import json
import logging

from .. import config
from . import summary as summary_service

logger = logging.getLogger(__name__)

# 모델에게 알려 줄 도구 스키마(Anthropic 규격: parameters 가 아니라 input_schema).
TOOL_SCHEMAS = [
    {
        "name": "get_data_points",
        "description": (
            "등록된 데이터 포인트를 조회한다. 특정 기간의 실제 값이 필요하거나, "
            "요약만으로 답할 수 없는 질문일 때 사용한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period_prefix": {
                    "type": "string",
                    "description": "기간 접두사로 거른다. 예: '1960' (그 해 전체), '1960-07' (그 달)",
                },
                "limit": {
                    "type": "integer",
                    "description": "최대 개수(기본 20). 너무 크게 잡지 마라.",
                },
            },
        },
    },
    {
        "name": "get_statistics",
        "description": (
            "중앙값·표준편차·변동계수·사분위 같은 추가 통계를 조회한다. "
            "분포나 변동성에 대한 질문일 때 사용한다."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

# 도구 호출 왕복 상한. 모델이 계속 도구만 부르는 상태를 막는다.
MAX_TOOL_ROUNDS = 3
# 한 번에 돌려줄 데이터 상한 — 모델이 limit 을 크게 잡아도 여기서 자른다.
TOOL_RESULT_CAP = 40


class AIUnavailable(RuntimeError):
    """AI 를 쓸 수 없는 상태 — 키 없음, 패키지 없음, 호출 실패."""


def _client():
    """copa(Anthropic 호환) 클라이언트. 키·패키지가 없으면 AIUnavailable 를 올린다."""
    api_key = config.get_copa_key()
    if not api_key:
        raise AIUnavailable(config.missing_key_message(config.COPA_KEY_NAME, "AI 대화"))
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise AIUnavailable(
            "anthropic 패키지가 설치되지 않았습니다. `pip install -r requirements.txt`"
        ) from exc
    return Anthropic(api_key=api_key, base_url=config.COPA_BASE_URL, timeout=config.REQUEST_TIMEOUT)


def _run_tool(name: str, arguments: dict, documents: list[dict]) -> dict:
    """도구 실행 — 모델이 부른 함수를 실제로 수행한다.

    **모델이 부른다고 그대로 실행하지 않는다.** 이름을 허용 목록으로 확인하고, 인자도
    우리가 다시 검증한다. 모델 출력은 사용자 입력과 같은 등급으로 다뤄야 한다.
    """
    if name == "get_data_points":
        prefix = str(arguments.get("period_prefix") or "").strip()
        try:
            limit = int(arguments.get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(limit, TOOL_RESULT_CAP))  # 모델이 크게 잡아도 여기서 자른다

        selected = [d for d in documents if str(d.get("period", "")).startswith(prefix)]
        selected.sort(key=lambda d: str(d.get("period", "")))
        return {
            "matched": len(selected),
            "returned": min(len(selected), limit),
            "points": [
                {"period": d.get("period"), "value": d.get("value")}
                for d in selected[:limit]
            ],
        }

    if name == "get_statistics":
        return summary_service.extended_statistics(documents)

    # 허용 목록 밖 이름 — 모델이 없는 함수를 지어낸 경우
    return {"error": f"알 수 없는 도구: {name}"}


def chat(user_message: str, history: list[dict], documents: list[dict]) -> tuple[str, list[str]]:
    """AI 대화 → (답변, 호출한 도구 이름 목록).

    흐름:
      1) 데이터 요약을 계산해 시스템 프롬프트에 넣는다(컨텍스트 주입)
      2) 이전 대화 + 이번 질문을 붙여 호출한다
      3) 모델이 도구를 부르면 실행해 결과를 돌려주고 다시 호출한다(최대 3왕복)
      4) 최종 답변을 돌려준다
    """
    client = _client()

    data_summary = summary_service.compute_summary(documents)
    extended = summary_service.extended_statistics(documents)
    system_prompt = summary_service.build_system_prompt(data_summary, extended)

    # Anthropic 은 시스템 프롬프트를 messages 가 아니라 별도 system= 인자로 받는다.
    messages: list[dict] = []
    # 이전 대화는 최근 것만 넣는다 — 전부 넣으면 토큰이 무한정 커진다
    for entry in history[-10:]:
        if entry.get("role") in ("user", "assistant") and entry.get("content"):
            messages.append({"role": entry["role"], "content": entry["content"]})
    messages.append({"role": "user", "content": user_message})

    used_tools: list[str] = []

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = client.messages.create(
                model=config.DEFAULT_MODEL,
                system=system_prompt,
                messages=messages,
                tools=TOOL_SCHEMAS,
                max_tokens=config.MAX_TOKENS,
                # 설치된 anthropic SDK 버전엔 temperature 가 타입 인자로 없다 — extra_body 로
                # 우회해 넘긴다. 사실 기반 답변이라 낮게: 같은 데이터에 매번 다른 숫자가
                # 나오면 안 된다.
                extra_body={"temperature": 0.2},
            )
        except Exception as exc:  # noqa: BLE001 — SDK 예외 종류가 버전마다 다르다
            logger.error("copa 호출 실패: %s", exc)
            raise AIUnavailable(f"AI 호출에 실패했습니다: {exc}") from exc

        tool_uses = [block for block in response.content if block.type == "tool_use"]

        if not tool_uses:
            text = "".join(block.text for block in response.content if block.type == "text")
            return text.strip(), used_tools

        # 도구를 부른 경우 — 어시스턴트 턴(텍스트+tool_use 블록)을 그대로 이어 붙인다
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for call in tool_uses:
            used_tools.append(call.name)
            logger.info("도구 호출: %s(%s)", call.name, call.input)
            result = _run_tool(call.name, call.input, documents)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        messages.append({"role": "user", "content": tool_results})

    # 상한까지 도구만 부른 경우 — 여기서 멈추고 사실대로 알린다
    return (
        "도구를 여러 번 조회했지만 답을 정리하지 못했습니다. 질문을 조금 더 구체적으로 "
        "적어 주시겠어요?",
        used_tools,
    )
