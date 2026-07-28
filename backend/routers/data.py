"""데이터 라우터 — CRUD 4개 + 요약 1개.

**라우터를 파일로 나눈 기준**: URL 접두사 하나가 파일 하나다(`/api/data`). 한 파일에
전부 넣으면 엔드포인트가 늘어날수록 어디를 고쳐야 할지 찾기 어렵고, 여러 사람이 동시에
작업할 때 충돌한다.

라우터는 **HTTP 를 다루고**, 계산은 `services/` 가 한다. 그래서 이 파일에는 통계 공식이
없고, `services/summary.py` 에는 HTTP 상태 코드가 없다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .. import db
from ..models import DataPointIn, DataPointOut, SummaryOut
from ..services import summary as summary_service

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/summary", response_model=SummaryOut, summary="데이터 요약(프롬프트 주입용)")
def get_summary() -> SummaryOut:
    """데이터 요약을 돌려준다. **이 응답이 AI 시스템 프롬프트에 들어간다.**

    ⚠ 경로 순서 주의: 이 라우트는 `/{data_id}` **보다 위에** 있어야 한다. 아래에 두면
    FastAPI 가 `summary` 를 id 로 읽어 `/api/data/summary` 요청이 상세 조회로 간다.
    """
    documents = db.get_repository().list(db.COLLECTION_DATA)
    return SummaryOut(**summary_service.compute_summary(documents))


@router.get("/statistics", summary="추가 통계(보너스)")
def get_statistics() -> dict:
    """중앙값·표준편차·변동계수·사분위 — 요약보다 자세한 지표(보너스)."""
    documents = db.get_repository().list(db.COLLECTION_DATA)
    return summary_service.extended_statistics(documents)


@router.get("", response_model=list[DataPointOut], summary="데이터 목록 조회")
def list_data(limit: int = 500) -> list[DataPointOut]:
    """등록된 데이터를 최신순으로 돌려준다.

    상한을 두는 이유: 데이터가 수천 개가 되면 응답이 커져 프론트가 느려진다.
    """
    documents = db.get_repository().list(db.COLLECTION_DATA)
    return [DataPointOut(**_normalize(d)) for d in documents[:limit]]


@router.post("", response_model=DataPointOut, status_code=status.HTTP_201_CREATED,
             summary="새 데이터 추가")
def create_data(payload: DataPointIn) -> DataPointOut:
    """데이터 1건을 추가한다. 검증은 Pydantic 이 이 함수에 들어오기 전에 끝낸다."""
    record = db.get_repository().add(db.COLLECTION_DATA, payload.model_dump())
    return DataPointOut(**_normalize(record))


@router.put("/{data_id}", response_model=DataPointOut, summary="데이터 수정")
def update_data(data_id: str, payload: DataPointIn) -> DataPointOut:
    """데이터 1건을 수정한다. 없으면 404."""
    record = db.get_repository().update(db.COLLECTION_DATA, data_id, payload.model_dump())
    if record is None:
        raise HTTPException(status_code=404, detail=f"데이터를 찾을 수 없습니다: {data_id}")
    return DataPointOut(**_normalize(record))


@router.delete("/{data_id}", status_code=status.HTTP_204_NO_CONTENT, summary="데이터 삭제")
def delete_data(data_id: str) -> None:
    """데이터 1건을 삭제한다. 없으면 404.

    204(No Content)를 쓰는 이유: 삭제 성공에는 돌려줄 내용이 없다. 200 에 빈 객체를
    넣는 것보다 의미가 분명하다.
    """
    if not db.get_repository().delete(db.COLLECTION_DATA, data_id):
        raise HTTPException(status_code=404, detail=f"데이터를 찾을 수 없습니다: {data_id}")


def _normalize(document: dict) -> dict:
    """저장소 문서 → 응답 모델이 받는 형태.

    저장소에 옛 형식 문서가 남아 있어도 응답이 깨지지 않게 기본값을 채운다.
    """
    return {
        "id": str(document.get("id", "")),
        "period": str(document.get("period", "")),
        "value": float(document.get("value", 0)),
        "note": document.get("note"),
        "created_at": str(document.get("created_at", "")),
    }
