#!/usr/bin/env python3
"""email_triggers.json 규칙 CRUD 스크립트.

set-email-triggers 스킬에서 에이전트가 `execute` 로 호출한다. LLM 이 JSON 을 직접
편집하다 깨뜨리는 것을 막고, 스키마 검증과 원자적 저장을 보장한다. 표준 라이브러리만 사용.

대상 파일 기본값: 이 스크립트 기준 workspace 루트의 email_triggers.json
(skills/set-email-triggers/manage_triggers.py → parents[2] = workspace).

사용:
  python3 manage_triggers.py list
  python3 manage_triggers.py add --name NAME --action "..." \
      [--from X] [--subject-contains A --subject-contains B] [--body-contains X]
  python3 manage_triggers.py update --name NAME [--rename NEW] [--action ...] \
      [--from ...] [--subject-contains ...] [--body-contains ...] \
      [--clear-from] [--clear-subject] [--clear-body]
  python3 manage_triggers.py remove --name NAME
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "email_triggers.json"


def _path(args) -> Path:
    return Path(args.file) if args.file else DEFAULT_FILE


def _load(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"오류: {path} 가 유효한 JSON 이 아닙니다: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, list):
        print("오류: 최상위는 규칙 배열([])이어야 합니다.", file=sys.stderr)
        sys.exit(1)
    return data


def _save(path: Path, rules: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 원자적 저장(임시파일 + os.replace)으로 중간 손상 방지.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _find(rules: list, name: str) -> int:
    for i, r in enumerate(rules):
        if r.get("name") == name:
            return i
    return -1


def _apply_match(match: dict, args) -> dict:
    if getattr(args, "clear_from", False):
        match.pop("from", None)
    if getattr(args, "clear_subject", False):
        match.pop("subject_contains", None)
    if getattr(args, "clear_body", False):
        match.pop("body_contains", None)
    if args.from_:
        match["from"] = args.from_
    if args.subject_contains:
        match["subject_contains"] = args.subject_contains
    if args.body_contains:
        match["body_contains"] = args.body_contains
    return match


def cmd_list(args) -> None:
    rules = _load(_path(args))
    if not rules:
        print("규칙이 없습니다.")
        return
    print(json.dumps(rules, ensure_ascii=False, indent=2))


def cmd_add(args) -> None:
    path = _path(args)
    rules = _load(path)
    if _find(rules, args.name) >= 0:
        print(f"오류: '{args.name}' 규칙이 이미 있습니다. update 를 사용하세요.", file=sys.stderr)
        sys.exit(1)
    match = _apply_match({}, args)
    if not match:
        print("경고: match 조건이 비어 모든 메일에 매칭됩니다.", file=sys.stderr)
    rules.append({"name": args.name, "match": match, "action": args.action})
    _save(path, rules)
    print(f"추가됨: '{args.name}' (총 {len(rules)}개)")


def cmd_update(args) -> None:
    path = _path(args)
    rules = _load(path)
    i = _find(rules, args.name)
    if i < 0:
        print(f"오류: '{args.name}' 규칙이 없습니다.", file=sys.stderr)
        sys.exit(1)
    rule = rules[i]
    if args.action is not None:
        rule["action"] = args.action
    rule["match"] = _apply_match(rule.get("match", {}), args)
    if args.rename:
        if args.rename != args.name and _find(rules, args.rename) >= 0:
            print(f"오류: '{args.rename}' 이름이 이미 있습니다.", file=sys.stderr)
            sys.exit(1)
        rule["name"] = args.rename
    _save(path, rules)
    print(f"수정됨: '{args.name}'" + (f" → '{args.rename}'" if args.rename else ""))


def cmd_remove(args) -> None:
    path = _path(args)
    rules = _load(path)
    i = _find(rules, args.name)
    if i < 0:
        print(f"오류: '{args.name}' 규칙이 없습니다.", file=sys.stderr)
        sys.exit(1)
    rules.pop(i)
    _save(path, rules)
    print(f"삭제됨: '{args.name}' (총 {len(rules)}개)")


def _add_match_args(sp) -> None:
    sp.add_argument("--from", dest="from_", help="발신자 부분일치")
    sp.add_argument("--subject-contains", action="append", help="제목 포함(여러 번 지정=OR)")
    sp.add_argument("--body-contains", action="append", help="본문 포함(여러 번 지정=OR)")


def main() -> None:
    p = argparse.ArgumentParser(description="email_triggers.json 규칙 CRUD")
    p.add_argument("--file", help=f"규칙 파일 경로(기본: {DEFAULT_FILE})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="규칙 전체 출력")

    sa = sub.add_parser("add", help="규칙 추가")
    sa.add_argument("--name", required=True)
    sa.add_argument("--action", required=True, help="매칭 시 수행할 자연어 지시")
    _add_match_args(sa)

    su = sub.add_parser("update", help="규칙 수정")
    su.add_argument("--name", required=True)
    su.add_argument("--rename", help="새 이름")
    su.add_argument("--action")
    _add_match_args(su)
    su.add_argument("--clear-from", action="store_true", help="from 조건 제거")
    su.add_argument("--clear-subject", action="store_true", help="subject_contains 조건 제거")
    su.add_argument("--clear-body", action="store_true", help="body_contains 조건 제거")

    sr = sub.add_parser("remove", help="규칙 삭제")
    sr.add_argument("--name", required=True)

    args = p.parse_args()
    {"list": cmd_list, "add": cmd_add, "update": cmd_update, "remove": cmd_remove}[
        args.cmd
    ](args)


if __name__ == "__main__":
    main()
