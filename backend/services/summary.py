"""데이터 요약 — 저장된 데이터에서 "AI 에게 줄 한 덩어리" 를 만든다.

**이 함수의 출력이 곧 시스템 프롬프트의 재료**다. 그래서 무엇을 넣을지가 설계 결정이다:
원본 100개 값을 통째로 넣으면 토큰만 커지고 모델이 요약을 다시 해야 한다.
**사람이 데이터를 한 문단으로 설명한다면 무엇을 말할까**를 기준으로 골랐다.

추세 판정을 규칙으로 하는 이유: AI 에게 "추세가 어때?"라고 물으면 매번 답이 달라진다.
숫자로 정한 규칙이면 같은 데이터에 항상 같은 답이 나오고, 그 근거를 사람이 검증할 수 있다.
"""

from __future__ import annotations

import statistics

# 추세 판정 임계값(%). 최근 구간이 이전 구간보다 이만큼 넘게 다르면 증가/감소로 본다.
# 5%를 고른 이유: 이보다 작은 변화는 계절·잡음으로도 흔히 생긴다.
TREND_THRESHOLD_PCT = 5.0
# 추세를 보려면 앞뒤 구간이 각각 최소 이만큼은 있어야 한다.
MIN_POINTS_FOR_TREND = 6


def compute_summary(documents: list[dict]) -> dict:
    """데이터 목록 → 요약 dict. 데이터가 없어도 형태가 같은 dict 를 돌려준다.

    빈 경우에 None 대신 형태를 유지하는 이유: 호출한 쪽이 `if summary is None` 분기를
    쓰지 않아도 되고, 프론트가 항상 같은 키를 기대할 수 있다.
    """
    points = []
    for document in documents:
        period = str(document.get("period") or "").strip()
        try:
            value = float(document.get("value"))
        except (TypeError, ValueError):
            continue  # 값이 숫자가 아니면 통계에서 뺀다(입력 검증을 통과했어도 방어)
        if period:
            points.append((period, value))

    if not points:
        return {
            "count": 0, "period_from": None, "period_to": None,
            "mean": None, "minimum": None, "maximum": None,
            "trend": "판단 불가", "trend_basis": "데이터가 없습니다",
            "latest_value": None, "change_pct": None,
        }

    points.sort(key=lambda item: item[0])  # 시점 순 — 추세는 순서 위에서만 뜻이 있다
    values = [value for _, value in points]

    trend, basis, change_pct = _judge_trend(values)
    return {
        "count": len(points),
        "period_from": points[0][0],
        "period_to": points[-1][0],
        "mean": round(statistics.fmean(values), 2),
        "minimum": min(values),
        "maximum": max(values),
        "trend": trend,
        "trend_basis": basis,
        "latest_value": values[-1],
        "change_pct": change_pct,
    }


def _judge_trend(values: list[float]) -> tuple[str, str, float | None]:
    """최근 추세 → (판정, 근거 문장, 변화율).

    **앞뒤 절반의 평균을 비교**한다. 마지막 값 하나만 보면 그 달이 유난히 높거나 낮았을 때
    추세를 잘못 읽는다. 평균끼리 비교하면 한 점의 영향이 줄어든다.
    """
    if len(values) < MIN_POINTS_FOR_TREND * 2:
        return "판단 불가", f"추세 판정에는 최소 {MIN_POINTS_FOR_TREND * 2}개가 필요합니다", None

    half = len(values) // 2
    earlier = statistics.fmean(values[:half])
    recent = statistics.fmean(values[half:])
    if not earlier:
        return "판단 불가", "이전 구간 평균이 0입니다", None

    change_pct = round((recent - earlier) / earlier * 100, 2)
    basis = (f"앞 구간 평균 {earlier:.1f} → 최근 구간 평균 {recent:.1f} "
             f"({change_pct:+.1f}%, 기준 ±{TREND_THRESHOLD_PCT}%)")

    if change_pct > TREND_THRESHOLD_PCT:
        return "증가", basis, change_pct
    if change_pct < -TREND_THRESHOLD_PCT:
        return "감소", basis, change_pct
    return "유지", basis, change_pct


def extended_statistics(documents: list[dict]) -> dict:
    """보너스 — 요약을 넘어선 추가 지표.

    표준편차·변동계수·중앙값을 더한다. **변동계수를 넣은 이유**(M1-1 에서 배운 것):
    표준편차만으로는 규모가 다른 데이터끼리 흔들림을 비교할 수 없다.
    """
    values = []
    for document in documents:
        try:
            values.append(float(document.get("value")))
        except (TypeError, ValueError):
            continue

    if len(values) < 2:
        return {"available": False, "reason": "지표 계산에는 2개 이상이 필요합니다"}

    mean = statistics.fmean(values)
    stdev = statistics.stdev(values)
    return {
        "available": True,
        "median": round(statistics.median(values), 2),
        "stdev": round(stdev, 2),
        # 변동계수 — 규모 대비 흔들림. 규모가 다른 데이터끼리 비교할 때 쓴다
        "coefficient_of_variation": round(stdev / mean * 100, 2) if mean else None,
        "range": round(max(values) - min(values), 2),
        "quartiles": [round(q, 2) for q in statistics.quantiles(values, n=4)],
    }


def build_system_prompt(summary: dict, extended: dict | None = None) -> str:
    """요약 → 시스템 프롬프트(컨텍스트 주입).

    **컨텍스트 주입의 원리**: GPT 는 우리 데이터베이스를 볼 수 없다. 대화 시작 전에
    "너는 이런 데이터를 알고 있다"고 **글로 적어 주는 것**이 유일한 통로다. 그래서
    요약의 품질이 곧 답변의 품질이 된다.

    금지 규칙을 함께 넣는 이유: 요약에 없는 값을 물으면 모델은 **그럴듯하게 지어낸다.**
    "모른다고 답하라"를 명시해야 그 자리에서 멈춘다.
    """
    if summary["count"] == 0:
        return (
            "너는 데이터 분석 도우미다. 현재 등록된 데이터가 없다.\n"
            "사용자가 데이터에 대해 물으면 '아직 등록된 데이터가 없습니다. "
            "데이터 관리 화면에서 먼저 추가해 주세요.' 라고 답하라."
        )

    lines = [
        "너는 시계열 데이터 분석 도우미다. 아래는 사용자가 등록한 데이터의 요약이다.",
        "",
        "[데이터 요약]",
        f"- 기간: {summary['period_from']} ~ {summary['period_to']}",
        f"- 개수: {summary['count']}개",
        f"- 평균: {summary['mean']} / 최소: {summary['minimum']} / 최대: {summary['maximum']}",
        f"- 최근 값: {summary['latest_value']}",
        f"- 추세: {summary['trend']} ({summary['trend_basis']})",
    ]

    if extended and extended.get("available"):
        lines += [
            f"- 중앙값: {extended['median']} / 표준편차: {extended['stdev']}",
            f"- 변동계수: {extended['coefficient_of_variation']}% (규모 대비 흔들림)",
        ]

    lines += [
        "",
        "[답변 규칙]",
        "- 위 요약에 있는 숫자만 사용한다. **요약에 없는 값은 지어내지 마라.**",
        "- 요약으로 답할 수 없는 질문에는 '주어진 요약으로는 알 수 없습니다' 라고 말하고,",
        "  무엇이 더 있으면 답할 수 있는지 알려 준다.",
        "- 추세를 말할 때는 위 근거(앞뒤 구간 평균 비교)를 함께 언급한다.",
        "- 한국어로, 3~5문장으로 간결하게 답한다.",
    ]
    return "\n".join(lines)
