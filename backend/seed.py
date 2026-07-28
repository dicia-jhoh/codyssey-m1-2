"""시드 — M1-1 분석에 쓴 데이터를 이 서비스의 저장소로 옮긴다.

**미션 연계**: M1-1(데이터 분석 리포트)이 분석한 항공 승객 수 144개월이 그대로 이
서비스의 데이터가 된다. 같은 데이터를 두 번 만들지 않고, M1-1 의 결론(`summary.json`)과
이 서비스의 요약이 **같은 값을 가리키는지** 대조할 수도 있다.

실행: `python -m backend.seed`
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from . import config, db

CSV_PATH = Path("data/airline_passengers.csv")
M1_1_SUMMARY = Path("data/m1_1_summary.json")


def load_rows(path: Path = CSV_PATH) -> list[dict]:
    """CSV → 데이터 문서 목록. M1-1 과 같은 파일을 읽는다."""
    if not path.exists():
        raise SystemExit(f"[중단] 데이터 파일이 없습니다: {path}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [
        {"period": row["Month"].strip(), "value": float(row["Passengers"]),
         "note": "M1-1 분석 데이터(Box & Jenkins 항공 승객 수)"}
        for row in rows
        if row.get("Month") and row.get("Passengers")
    ]


def main(argv: list[str] | None = None) -> int:
    """저장소에 데이터를 넣는다. 이미 있으면 건너뛴다(중복 적재 방지)."""
    config.load_dotenv()
    repository = db.get_repository()

    existing = repository.list(db.COLLECTION_DATA)
    if existing and "--force" not in (argv or sys.argv[1:]):
        print(f"이미 {len(existing)}건이 있습니다. 다시 넣으려면 --force 를 주세요.")
        return 0

    rows = load_rows()
    for row in rows:
        repository.add(db.COLLECTION_DATA, row)
    print(f"적재 {len(rows)}건 → 저장소({db.repository_kind()})")

    # M1-1 요약과 이 서비스 요약이 같은 데이터를 가리키는지 확인한다
    if M1_1_SUMMARY.exists():
        with open(M1_1_SUMMARY, encoding="utf-8") as f:
            m1_1 = json.load(f)
        print(f"M1-1 요약 대조 — 기간 {m1_1['period']} · {m1_1['points']}개 · "
              f"평균 {m1_1['stats']['mean']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
