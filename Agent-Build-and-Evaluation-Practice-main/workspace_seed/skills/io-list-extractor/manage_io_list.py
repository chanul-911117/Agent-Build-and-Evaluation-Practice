#!/usr/bin/env python3
"""I/O List(XLSX/CSV) → IR(JSON) 변환 및 관리 스크립트.

io-list-extractor 스킬에서 에이전트가 `execute` 로 호출한다. 엑셀/CSV 헤더를
자동 인식해 태그(주소/자료형/모듈/디바이스 등)를 추출하고, 확신할 수 없는 행은
needs_review 로 표시해 사람이 검토하게 한다. 표준 라이브러리 + openpyxl(xlsx용)만 사용.

IR(중간표현) 스키마 (schema_version 1.0)
{
  "schema_version": "1.0",
  "project": {"name": str, "source_file": str, "extracted_at": ISO8601},
  "devices": [{"id": str, "name": str}],
  "tags": [
    {
      "tag_name": str,
      "io_type": "DI"|"DO"|"AI"|"AO"|"UNKNOWN",
      "data_type": "BOOL"|"INT"|"REAL"|"UNKNOWN",
      "address": str,
      "module": str,
      "device": str,
      "description": str,
      "needs_review": bool,
      "review_reason": str | null
    }
  ],
  "summary": {
    "total_rows": int, "mapped": int, "needs_review": int,
    "duplicate_tags": [str], "duplicate_addresses": [str]
  }
}

대상 파일 기본 저장 위치: workspace 루트의 io_ir/<입력파일이름>.json
(skills/io-list-extractor/manage_io_list.py → parents[2] = workspace).

사용:
  python3 manage_io_list.py extract --input <path.xlsx|path.csv> \
      [--sheet SHEET_NAME] [--output io_ir/foo.json] [--project-name NAME]
  python3 manage_io_list.py list
  python3 manage_io_list.py show --file io_ir/foo.json [--needs-review-only]
  python3 manage_io_list.py validate --file io_ir/foo.json
"""

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = WORKSPACE_ROOT / "io_ir"

# ---------------------------------------------------------------------------
# 헤더 자동 인식
# ---------------------------------------------------------------------------
ALIASES: dict[str, list[str]] = {
    "tag_name": ["tag", "tagname", "tag name", "태그명", "태그", "심볼", "symbol", "변수명"],
    "address": ["address", "addr", "주소", "번지"],
    "io_type": ["io type", "i/o type", "iotype", "io", "구분", "유형", "입출력"],
    "data_type": ["data type", "datatype", "자료형", "데이터타입", "형식", "타입"],
    "module": ["module", "모듈", "슬롯", "slot"],
    "device": ["device", "장치", "디바이스", "설비", "장비"],
    "description": ["description", "설명", "comment", "비고", "note", "용도"],
}

# Siemens 스타일 주소 → IO 타입 추론 (I/E=입력, Q/A=출력, 뒤에 W면 워드=아날로그)
_ADDR_PATTERNS = [
    (re.compile(r"^(I|E)\d+\.\d+$", re.I), "DI"),
    (re.compile(r"^(Q|A)\d+\.\d+$", re.I), "DO"),
    (re.compile(r"^(IW|EW)\d+$", re.I), "AI"),
    (re.compile(r"^(QW|AW)\d+$", re.I), "AO"),
]

_IO_TYPE_NORMALIZE = {
    "di": "DI", "digital input": "DI", "디지털입력": "DI", "입력": "DI",
    "do": "DO", "digital output": "DO", "디지털출력": "DO", "출력": "DO",
    "ai": "AI", "analog input": "AI", "아날로그입력": "AI",
    "ao": "AO", "analog output": "AO", "아날로그출력": "AO",
}

_DATA_TYPE_NORMALIZE = {
    "bool": "BOOL", "boolean": "BOOL", "비트": "BOOL", "bit": "BOOL",
    "int": "INT", "integer": "INT", "정수": "INT",
    "real": "REAL", "float": "REAL", "실수": "REAL",
}


def _norm_header(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s_\-/]+", " ", s)
    return s.strip()


def _detect_columns(header_row: list[str]) -> dict[str, int]:
    """헤더 셀 목록에서 필드→열 인덱스 매핑을 만든다."""
    normed = [_norm_header(h) for h in header_row]
    col_map: dict[str, int] = {}
    for field, aliases in ALIASES.items():
        for idx, h in enumerate(normed):
            if h in aliases or any(a in h for a in aliases if len(a) > 2):
                col_map[field] = idx
                break
    return col_map


def _infer_io_type(raw: str, address: str) -> tuple[str, bool]:
    """(io_type, ok) — raw 값이 있으면 정규화, 없으면 주소 패턴에서 추론."""
    key = _norm_header(raw)
    if key in _IO_TYPE_NORMALIZE:
        return _IO_TYPE_NORMALIZE[key], True
    for pattern, io_type in _ADDR_PATTERNS:
        if address and pattern.match(address.strip()):
            return io_type, True
    return "UNKNOWN", False


def _infer_data_type(raw: str, io_type: str) -> tuple[str, bool]:
    key = _norm_header(raw)
    if key in _DATA_TYPE_NORMALIZE:
        return _DATA_TYPE_NORMALIZE[key], True
    if io_type in ("DI", "DO"):
        return "BOOL", True  # 디지털은 자료형이 안 적혀 있어도 BOOL로 확신 가능
    return "UNKNOWN", False


# ---------------------------------------------------------------------------
# 파일 읽기 (xlsx / csv)
# ---------------------------------------------------------------------------
def _read_rows(path: Path, sheet: str | None) -> list[list[str]]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            print(
                "오류: openpyxl 이 설치되어 있지 않습니다. "
                "'uv add openpyxl' 로 프로젝트에 추가하세요.",
                file=sys.stderr,
            )
            sys.exit(1)
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb[sheet] if sheet else wb.worksheets[0]
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(["" if c is None else str(c) for c in row])
        return rows
    if ext == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            return [row for row in csv.reader(f)]
    print(f"오류: 지원하지 않는 확장자입니다: {ext} (xlsx/xlsm/csv만 지원)", file=sys.stderr)
    sys.exit(1)


def _find_header_row(rows: list[list[str]]) -> int:
    """tag_name 에 해당하는 헤더가 있는 첫 행을 찾는다(빈 행 스킵)."""
    for i, row in enumerate(rows):
        if not any(str(c).strip() for c in row):
            continue
        col_map = _detect_columns(row)
        if "tag_name" in col_map:
            return i
        # 헤더 후보인데 tag_name 을 못 찾으면 다음 비어있지 않은 행을 계속 탐색
    return -1


# ---------------------------------------------------------------------------
# IR 빌드
# ---------------------------------------------------------------------------
def _build_ir(rows: list[list[str]], source_file: str, project_name: str) -> dict:
    header_idx = _find_header_row(rows)
    if header_idx < 0:
        print(
            "오류: 헤더 행을 찾을 수 없습니다 (태그명/Tag Name 열이 필요합니다). "
            "ALIASES 목록에 헤더 표현을 추가하거나 파일을 확인하세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    col_map = _detect_columns(rows[header_idx])
    data_rows = rows[header_idx + 1 :]

    tags = []
    devices_seen: dict[str, None] = {}
    seen_tag_names: dict[str, int] = {}
    seen_addresses: dict[str, int] = {}
    dup_tags: set[str] = set()
    dup_addrs: set[str] = set()

    def _cell(row: list[str], field: str) -> str:
        idx = col_map.get(field)
        if idx is None or idx >= len(row):
            return ""
        return (row[idx] or "").strip()

    for row in data_rows:
        if not any(str(c).strip() for c in row):
            continue
        tag_name = _cell(row, "tag_name")
        if not tag_name:
            continue  # 태그명 없는 행은 노이즈로 간주하고 건너뜀
        address = _cell(row, "address")
        device = _cell(row, "device")
        module = _cell(row, "module")
        description = _cell(row, "description")

        io_type, io_ok = _infer_io_type(_cell(row, "io_type"), address)
        data_type, dt_ok = _infer_data_type(_cell(row, "data_type"), io_type)

        needs_review = not (io_ok and dt_ok)
        reasons = []
        if not io_ok:
            reasons.append("io_type 을 판단할 수 없음(열 값도 없고 주소 패턴도 안 맞음)")
        if not dt_ok:
            reasons.append("data_type 을 판단할 수 없음(아날로그 신호는 폭/스케일 확인 필요)")

        if tag_name in seen_tag_names:
            dup_tags.add(tag_name)
            needs_review = True
            reasons.append("태그명 중복")
        seen_tag_names[tag_name] = seen_tag_names.get(tag_name, 0) + 1

        if address:
            if address in seen_addresses:
                dup_addrs.add(address)
                needs_review = True
                reasons.append("주소 중복")
            seen_addresses[address] = seen_addresses.get(address, 0) + 1

        if device:
            devices_seen[device] = None

        tags.append(
            {
                "tag_name": tag_name,
                "io_type": io_type,
                "data_type": data_type,
                "address": address,
                "module": module,
                "device": device,
                "description": description,
                "needs_review": needs_review,
                "review_reason": "; ".join(reasons) if reasons else None,
            }
        )

    review_count = sum(1 for t in tags if t["needs_review"])

    return {
        "schema_version": "1.0",
        "project": {
            "name": project_name,
            "source_file": source_file,
            "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "devices": [{"id": d, "name": d} for d in devices_seen],
        "tags": tags,
        "summary": {
            "total_rows": len(tags),
            "mapped": len(tags) - review_count,
            "needs_review": review_count,
            "duplicate_tags": sorted(dup_tags),
            "duplicate_addresses": sorted(dup_addrs),
        },
    }


# ---------------------------------------------------------------------------
# 저장/로드 (원자적 저장)
# ---------------------------------------------------------------------------
def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load(path: Path) -> dict:
    if not path.exists():
        print(f"오류: {path} 가 없습니다.", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"오류: {path} 가 유효한 JSON 이 아닙니다: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# 커맨드
# ---------------------------------------------------------------------------
def cmd_extract(args) -> None:
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"오류: 입력 파일이 없습니다: {input_path}", file=sys.stderr)
        sys.exit(1)

    rows = _read_rows(input_path, args.sheet)
    project_name = args.project_name or input_path.stem
    ir = _build_ir(rows, source_file=str(input_path), project_name=project_name)

    out_path = (
        Path(args.output) if args.output else DEFAULT_OUT_DIR / f"{input_path.stem}.json"
    )
    _save(out_path, ir)

    s = ir["summary"]
    print(f"저장됨: {out_path}")
    print(f"총 {s['total_rows']}개 태그 — 매핑완료 {s['mapped']}개 / 검토필요 {s['needs_review']}개")
    if s["duplicate_tags"]:
        print(f"⚠️ 태그명 중복: {', '.join(s['duplicate_tags'])}")
    if s["duplicate_addresses"]:
        print(f"⚠️ 주소 중복: {', '.join(s['duplicate_addresses'])}")
    if s["needs_review"]:
        review_names = [t["tag_name"] for t in ir["tags"] if t["needs_review"]][:10]
        more = "" if s["needs_review"] <= 10 else f" 외 {s['needs_review'] - 10}개"
        print(f"검토 필요 태그(상위 10개): {', '.join(review_names)}{more}")


def cmd_list(args) -> None:
    if not DEFAULT_OUT_DIR.exists():
        print("생성된 IR 파일이 없습니다.")
        return
    files = sorted(DEFAULT_OUT_DIR.glob("*.json"))
    if not files:
        print("생성된 IR 파일이 없습니다.")
        return
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            s = data.get("summary", {})
            print(
                f"{f.relative_to(WORKSPACE_ROOT)} — "
                f"{s.get('total_rows', '?')}개 태그, 검토필요 {s.get('needs_review', '?')}개"
            )
        except Exception:
            print(f"{f.relative_to(WORKSPACE_ROOT)} — (읽기 실패)")


def cmd_show(args) -> None:
    data = _load(Path(args.file))
    tags = data.get("tags", [])
    if args.needs_review_only:
        tags = [t for t in tags if t.get("needs_review")]
    print(json.dumps({**data, "tags": tags}, ensure_ascii=False, indent=2))


def cmd_validate(args) -> None:
    path = Path(args.file)
    data = _load(path)
    tags = data.get("tags", [])
    names, addrs = {}, {}
    for t in tags:
        names[t["tag_name"]] = names.get(t["tag_name"], 0) + 1
        if t.get("address"):
            addrs[t["address"]] = addrs.get(t["address"], 0) + 1
    dup_tags = sorted(n for n, c in names.items() if c > 1)
    dup_addrs = sorted(a for a, c in addrs.items() if c > 1)
    review = [t["tag_name"] for t in tags if t.get("needs_review")]

    print(f"파일: {path}")
    print(f"총 태그: {len(tags)}개")
    print(f"태그명 중복: {dup_tags or '없음'}")
    print(f"주소 중복: {dup_addrs or '없음'}")
    print(f"검토 필요: {len(review)}개" + (f" — {review}" if review else ""))
    if dup_tags or dup_addrs or review:
        sys.exit(1)  # 검증 실패를 종료코드로도 알림(자동화 파이프라인 연동 대비)


def main() -> None:
    p = argparse.ArgumentParser(description="I/O List → IR(JSON) 추출/관리")
    sub = p.add_subparsers(dest="cmd", required=True)

    se = sub.add_parser("extract", help="I/O List 파일을 IR JSON 으로 변환")
    se.add_argument("--input", required=True, help="입력 파일 경로(xlsx/xlsm/csv)")
    se.add_argument("--sheet", help="엑셀 시트 이름(생략 시 첫 시트)")
    se.add_argument("--output", help=f"출력 경로(기본: {DEFAULT_OUT_DIR}/<입력파일이름>.json)")
    se.add_argument("--project-name", help="IR 에 기록할 프로젝트 이름(기본: 입력파일 이름)")

    sub.add_parser("list", help="생성된 IR 파일 목록과 요약 출력")

    ss = sub.add_parser("show", help="IR 파일 내용 출력")
    ss.add_argument("--file", required=True)
    ss.add_argument("--needs-review-only", action="store_true", help="검토 필요 태그만 출력")

    sv = sub.add_parser("validate", help="IR 파일 무결성 재검증(중복/미판별 항목)")
    sv.add_argument("--file", required=True)

    args = p.parse_args()
    {
        "extract": cmd_extract,
        "list": cmd_list,
        "show": cmd_show,
        "validate": cmd_validate,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
