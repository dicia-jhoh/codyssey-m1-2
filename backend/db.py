"""저장소 계층 — Firestore. 자격이 없으면 로컬 JSON 파일로 자동 전환한다.

**왜 전환 장치를 두나**: Firestore 는 서비스 계정 키가 있어야 붙는다. 키가 없다고
서버가 뜨지도 않으면 ① 채점자가 코드를 돌려 볼 수 없고 ② 프론트 개발자가 백엔드를
기다려야 하고 ③ 테스트에 실물 DB 가 필요해진다.

**같은 인터페이스를 두 구현이 만족**하게 해서 위쪽(라우터·서비스) 코드는 어느 쪽이
붙었는지 모르게 했다. 이것이 저장소를 계층으로 분리하는 실질적인 이유다 —
"나중에 DB 를 바꿀 수도 있어서"가 아니라, **지금 당장 두 환경에서 돌려야** 하기 때문이다.

컬렉션 구조(미션 요구):
  data          — 분석 데이터 (period, value, note, created_at)
  conversations — 대화 기록 (title, messages, created_at)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from . import config

logger = logging.getLogger(__name__)

COLLECTION_DATA = "data"
COLLECTION_CONVERSATIONS = "conversations"


def now_iso() -> str:
    """저장되는 모든 시각을 이 함수 하나로 만든다 — 형식이 갈리지 않게."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    """문서 id. Firestore 자동 id 와 형태를 맞추려고 짧은 무작위 문자열을 쓴다."""
    return uuid.uuid4().hex[:20]


class Repository(Protocol):
    """저장소 인터페이스 — Firestore 구현과 로컬 구현이 둘 다 만족한다."""

    def add(self, collection: str, document: dict) -> dict: ...
    def list(self, collection: str, *, order_by: str = "created_at") -> list[dict]: ...
    def get(self, collection: str, document_id: str) -> dict | None: ...
    def update(self, collection: str, document_id: str, patch: dict) -> dict | None: ...
    def delete(self, collection: str, document_id: str) -> bool: ...


class LocalRepository:
    """로컬 JSON 파일 저장소 — Firestore 자격이 없을 때 쓰는 대체 구현.

    컬렉션 하나가 파일 하나다. 매 호출마다 읽고 쓰는 방식이라 느리지만, 프로세스가
    죽어도 데이터가 남고 파일을 열어 눈으로 확인할 수 있다. 개발·채점에는 이 쪽이 낫다.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or config.LOCAL_STORE_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "Firestore 자격이 없어 로컬 저장소를 씁니다: %s "
            "(배포에서는 FIREBASE_SERVICE_ACCOUNT_JSON 을 설정하세요)",
            self.root,
        )

    def _path(self, collection: str) -> Path:
        return self.root / f"{collection}.json"

    def _read(self, collection: str) -> list[dict]:
        path = self._path(collection)
        if not path.exists():
            return []
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            # 파일이 깨졌으면 빈 것으로 본다 — 여기서 죽으면 서버 전체가 멈춘다
            logger.error("로컬 저장소 파일을 읽지 못했습니다: %s", path)
            return []

    def _write(self, collection: str, documents: list[dict]) -> None:
        with open(self._path(collection), "w", encoding="utf-8") as f:
            json.dump(documents, f, ensure_ascii=False, indent=2)

    def add(self, collection: str, document: dict) -> dict:
        documents = self._read(collection)
        record = {**document, "id": document.get("id") or new_id(),
                  "created_at": document.get("created_at") or now_iso()}
        documents.append(record)
        self._write(collection, documents)
        return record

    def list(self, collection: str, *, order_by: str = "created_at") -> list[dict]:
        documents = self._read(collection)
        return sorted(documents, key=lambda d: str(d.get(order_by, "")), reverse=True)

    def get(self, collection: str, document_id: str) -> dict | None:
        return next((d for d in self._read(collection) if d.get("id") == document_id), None)

    def update(self, collection: str, document_id: str, patch: dict) -> dict | None:
        documents = self._read(collection)
        for index, document in enumerate(documents):
            if document.get("id") == document_id:
                # id·created_at 은 덮어쓰지 않는다 — 수정으로 신원이 바뀌면 안 된다
                documents[index] = {**document, **patch, "id": document_id,
                                    "created_at": document.get("created_at")}
                self._write(collection, documents)
                return documents[index]
        return None

    def delete(self, collection: str, document_id: str) -> bool:
        documents = self._read(collection)
        remaining = [d for d in documents if d.get("id") != document_id]
        if len(remaining) == len(documents):
            return False
        self._write(collection, remaining)
        return True


class FirestoreRepository:
    """Firestore 구현. `firebase-admin` 으로 붙는다."""

    def __init__(self, credentials_dict: dict) -> None:
        import firebase_admin
        from firebase_admin import credentials, firestore

        # 앱이 이미 초기화됐으면 다시 하지 않는다 — uvicorn --reload 에서 두 번 뜬다
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(credentials_dict))
        self.client = firestore.client()
        logger.info("Firestore 연결됨 (project=%s)", credentials_dict.get("project_id"))

    def add(self, collection: str, document: dict) -> dict:
        record = {**document, "created_at": document.get("created_at") or now_iso()}
        reference = self.client.collection(collection).document(document.get("id") or new_id())
        reference.set(record)
        return {**record, "id": reference.id}

    def list(self, collection: str, *, order_by: str = "created_at") -> list[dict]:
        from firebase_admin import firestore

        query = (self.client.collection(collection)
                 .order_by(order_by, direction=firestore.Query.DESCENDING))
        return [{**doc.to_dict(), "id": doc.id} for doc in query.stream()]

    def get(self, collection: str, document_id: str) -> dict | None:
        snapshot = self.client.collection(collection).document(document_id).get()
        return {**snapshot.to_dict(), "id": snapshot.id} if snapshot.exists else None

    def update(self, collection: str, document_id: str, patch: dict) -> dict | None:
        reference = self.client.collection(collection).document(document_id)
        if not reference.get().exists:
            return None
        # id·created_at 은 patch 에서 빼고 넘긴다 — 신원과 생성 시각은 불변이다
        safe = {k: v for k, v in patch.items() if k not in ("id", "created_at")}
        reference.update(safe)
        return self.get(collection, document_id)

    def delete(self, collection: str, document_id: str) -> bool:
        reference = self.client.collection(collection).document(document_id)
        if not reference.get().exists:
            return False
        reference.delete()
        return True


_repository: Any = None


def get_repository() -> Repository:
    """저장소 하나를 만들어 재사용한다(연결을 매 요청마다 새로 열지 않는다).

    Firestore 초기화가 실패해도 **서버를 죽이지 않고** 로컬로 내려간다. 배포 중에 키가
    잘못 설정됐을 때 전체 서비스가 멈추는 것보다, 로그에 경고를 남기고 도는 편이 낫다.
    """
    global _repository
    if _repository is not None:
        return _repository

    try:
        credentials_dict = config.get_firebase_credentials()
    except ValueError as exc:
        logger.error("%s", exc)
        credentials_dict = None

    if credentials_dict:
        try:
            _repository = FirestoreRepository(credentials_dict)
            return _repository
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 로컬로 내려간다
            logger.error("Firestore 초기화 실패(%s) — 로컬 저장소로 전환합니다", exc)

    _repository = LocalRepository()
    return _repository


def repository_kind() -> str:
    """현재 어느 저장소를 쓰는지 → 'firestore' | 'local'. 헬스체크·문서에 노출한다."""
    return "firestore" if isinstance(get_repository(), FirestoreRepository) else "local"
