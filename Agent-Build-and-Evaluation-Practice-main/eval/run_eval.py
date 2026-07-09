#!/usr/bin/env python3
"""에이전트 평가 스크립트.

eval/dataset.json 의 각 케이스를 실제 에이전트(agent.invoke)에 태워, tool call
시퀀스와 최종 응답을 뽑아낸 뒤 세 가지 방식으로 채점한다.
  - rule       : 특정 tool 이 호출됐는지/안 됐는지 문자열 매칭으로 확인 (결정적, 무료)
  - llm_judge  : 최종 응답이 자연어 기준(criteria)을 만족하는지 LLM에게 True/False 로 판정
  - llm_judge_pairwise : 두 variant(baseline/variant)의 응답을 LLM에게 비교시켜 승자 판정
                 (meta-harness 의 baseline vs variant 비교 단계에서 사용)

사용:
  # baseline(현재 langchain-deepagents.py)로 rule + llm_judge 케이스 실행
  uv run python eval/run_eval.py --dataset eval/dataset.json

  # 두 개의 agent 모듈(baseline/variant)을 pairwise 로 비교 (meta-harness 3단계용)
  uv run python eval/run_eval.py --dataset eval/dataset.json \
      --pairwise --module-a langchain-deepagents --module-b variant.langchain-deepagents

주의:
  - 실제 모델 호출이 일어나므로 비용/시간이 든다(README 참고).
  - LLM 비결정성 때문에 접전인 케이스는 여러 번 돌려 다수결로 판단하는 걸 권장한다
    (--repeat 옵션).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mode

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 에이전트 실행 → tool call 시퀀스 / 최종 응답 추출
# ---------------------------------------------------------------------------
@dataclass
class RunResult:
    query: str
    final_text: str
    tool_calls: list[str] = field(default_factory=list)  # "tool_name(args...)" 문자열들
    error: str | None = None


def _extract_tool_calls(messages: list) -> list[str]:
    """LangGraph 메시지 리스트에서 tool call 을 "이름(args)" 문자열로 뽑는다."""
    calls = []
    for m in messages:
        tool_calls = getattr(m, "tool_calls", None) or (
            m.get("tool_calls") if isinstance(m, dict) else None
        )
        if not tool_calls:
            continue
        for tc in tool_calls:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            calls.append(f"{name}({json.dumps(args, ensure_ascii=False)})")
    return calls


def _extract_final_text(messages: list) -> str:
    for m in reversed(messages):
        content = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
        role = getattr(m, "type", None) if not isinstance(m, dict) else m.get("role")
        if content and role in ("ai", "assistant"):
            if isinstance(content, str):
                return content
            if isinstance(content, list):  # content block 형식
                return "\n".join(
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
    return ""


def run_agent(agent_module: str, query: str, timeout_s: int = 180) -> RunResult:
    """agent_module(예: 'langchain-deepagents')을 import 해서 query 를 한 번 실행한다."""
    mod_name = agent_module.replace(".py", "").replace("/", ".")
    # 파일명에 하이픈이 있어 일반 import 가 안 되므로 importlib 로 직접 로드한다.
    mod_path = REPO_ROOT / f"{mod_name.replace('.', '/')}.py"
    spec = importlib.util.spec_from_file_location(mod_name.replace(".", "_"), mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    try:
        result = module.agent.invoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"recursion_limit": 50},
        )
        messages = result.get("messages", [])
        return RunResult(
            query=query,
            final_text=_extract_final_text(messages),
            tool_calls=_extract_tool_calls(messages),
        )
    except Exception as e:  # noqa: BLE001 - 평가 중 하나 실패해도 나머지는 계속 진행
        return RunResult(query=query, final_text="", tool_calls=[], error=str(e))


# ---------------------------------------------------------------------------
# 채점기
# ---------------------------------------------------------------------------
def score_rule(case: dict, run: RunResult) -> dict:
    joined_calls = " | ".join(run.tool_calls)
    missing = [s for s in case.get("expected_tool_substr", []) if s not in joined_calls]
    present_forbidden = [s for s in case.get("forbidden_tool_substr", []) if s in joined_calls]
    passed = not missing and not present_forbidden
    return {
        "passed": passed,
        "detail": {
            "missing_expected": missing,
            "unexpected_forbidden": present_forbidden,
            "tool_calls": run.tool_calls,
        },
    }


_JUDGE_SYSTEM = (
    "당신은 AI 에이전트의 응답을 평가하는 엄격한 채점자입니다. "
    "주어진 기준(criteria)에 비추어 응답이 기준을 만족하는지 판단하세요. "
    "반드시 아래 JSON 형식으로만 답하세요, 다른 텍스트는 절대 추가하지 마세요:\n"
    '{"passed": true|false, "reasoning": "한두 문장 이유"}'
)


def _call_judge(model, prompt: str) -> dict:
    resp = model.invoke([{"role": "system", "content": _JUDGE_SYSTEM}, {"role": "user", "content": prompt}])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"passed": False, "reasoning": f"판정 파싱 실패, raw={text[:200]}"}


def score_llm_judge(case: dict, run: RunResult, judge_model) -> dict:
    if run.error:
        return {"passed": False, "detail": {"reasoning": f"에이전트 실행 오류: {run.error}"}}
    prompt = (
        f"[사용자 질문]\n{case['query']}\n\n"
        f"[에이전트 최종 응답]\n{run.final_text}\n\n"
        f"[평가 기준]\n{case['criteria']}\n\n"
        "이 응답이 평가 기준을 만족합니까?"
    )
    verdict = _call_judge(judge_model, prompt)
    return {"passed": bool(verdict.get("passed")), "detail": verdict}


def score_llm_judge_pairwise(case: dict, run_a: RunResult, run_b: RunResult, judge_model) -> dict:
    prompt = (
        f"[사용자 질문]\n{case['query']}\n\n"
        f"[응답 A]\n{run_a.final_text}\n\n"
        f"[응답 B]\n{run_b.final_text}\n\n"
        f"[평가 기준]\n{case['criteria']}\n\n"
        '어느 응답이 더 낫습니까? 다음 JSON 형식으로만 답하세요: '
        '{"winner": "A"|"B"|"tie", "reasoning": "..."}'
    )
    resp = judge_model.invoke([{"role": "system", "content": _JUDGE_SYSTEM}, {"role": "user", "content": prompt}])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    text = text.strip().strip("`")
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        verdict = {"winner": "tie", "reasoning": f"판정 파싱 실패, raw={text[:200]}"}
    return {"passed": None, "detail": verdict}


# ---------------------------------------------------------------------------
# 메인 루프
# ---------------------------------------------------------------------------
def run_single_module(dataset: list[dict], module_name: str, repeat: int) -> list[dict]:
    # judge 모델은 에이전트와 같은 모델 객체를 재사용(같은 파일에서 import).
    mod_path = REPO_ROOT / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name.replace(".", "_") + "_judge", mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    judge_model = module.model

    results = []
    for case in dataset:
        if case["eval_type"] == "llm_judge_pairwise":
            continue  # pairwise는 --pairwise 모드에서 별도 처리
        votes = []
        last_run = None
        for _ in range(repeat):
            run = run_agent(module_name, case["query"])
            last_run = run
            if case["eval_type"] == "rule":
                r = score_rule(case, run)
            else:
                r = score_llm_judge(case, run, judge_model)
            votes.append(r["passed"])
        passed = mode(votes) if len(votes) > 1 else votes[0]
        results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "eval_type": case["eval_type"],
                "passed": passed,
                "votes": votes,
                "final_text_sample": last_run.final_text[:300] if last_run else "",
                "tool_calls_sample": last_run.tool_calls if last_run else [],
            }
        )
        print(f"  [{case['id']}] {'PASS' if passed else 'FAIL'} — {case['category']}")
    return results


def run_pairwise(dataset: list[dict], module_a: str, module_b: str) -> list[dict]:
    mod_path = REPO_ROOT / f"{module_a}.py"
    spec = importlib.util.spec_from_file_location("judge_ref", mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    judge_model = module.model

    results = []
    for case in dataset:
        if case["eval_type"] != "llm_judge_pairwise":
            continue
        run_a = run_agent(module_a, case["query"])
        run_b = run_agent(module_b, case["query"])
        r = score_llm_judge_pairwise(case, run_a, run_b, judge_model)
        results.append({"id": case["id"], "category": case["category"], **r})
        print(f"  [{case['id']}] winner={r['detail'].get('winner')} — {case['category']}")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="에이전트 질문-평가기준 세트 실행기")
    p.add_argument("--dataset", default="eval/dataset.json")
    p.add_argument("--module", default="langchain-deepagents", help="단일 평가 대상 모듈(확장자 제외)")
    p.add_argument("--repeat", type=int, default=1, help="llm_judge/rule 케이스 반복 횟수(비결정성 대응)")
    p.add_argument("--pairwise", action="store_true", help="module-a/module-b 를 pairwise 로 비교")
    p.add_argument("--module-a", default="langchain-deepagents")
    p.add_argument("--module-b", default=None)
    p.add_argument("--output", default=None, help="결과 JSON 저장 경로(기본: eval/results/<timestamp>.json)")
    args = p.parse_args()

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))

    if args.pairwise:
        if not args.module_b:
            print("오류: --pairwise 에는 --module-b 가 필요합니다.", file=sys.stderr)
            sys.exit(1)
        print(f"Pairwise 평가: {args.module_a} vs {args.module_b}")
        results = run_pairwise(dataset, args.module_a, args.module_b)
    else:
        print(f"평가 대상: {args.module} (반복 {args.repeat}회)")
        results = run_single_module(dataset, args.module, args.repeat)

    out_path = Path(args.output) if args.output else Path(
        f"eval/results/{int(time.time())}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.pairwise:
        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        by_cat: dict[str, list[bool]] = {}
        for r in results:
            by_cat.setdefault(r["category"], []).append(r["passed"])
        print(f"\n=== 요약: {passed}/{total} 통과 ===")
        for cat, vals in by_cat.items():
            print(f"  {cat}: {sum(vals)}/{len(vals)}")
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
