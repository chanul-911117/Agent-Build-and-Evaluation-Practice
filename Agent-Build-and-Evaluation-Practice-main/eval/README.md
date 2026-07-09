# 에이전트 평가 (질문-평가기준 세트)

## 구성
- `dataset.json` — 10개 테스트 케이스 (rule 4개, llm_judge 5개, llm_judge_pairwise 1개)
- `run_eval.py` — 실제 에이전트(`agent.invoke`)를 돌려 채점하는 스크립트
- `fixtures/sample_io_list.csv` — 테스트용 샘플 I/O List (EStop 포함)
- `results/` — 실행 결과 JSON이 여기 쌓인다 (git에는 커밋하지 않는 걸 권장 — 매번 LLM 비결정성으로 값이 달라짐)

## 평가 유형
| eval_type | 설명 | 비용 |
|---|---|---|
| `rule` | tool call에 특정 문자열이 있는지/없는지 확인 (결정적) | 무료(에이전트 호출 1회) |
| `llm_judge` | 최종 응답이 자연어 기준을 만족하는지 LLM이 True/False 판정 | 에이전트 호출 + judge 호출 |
| `llm_judge_pairwise` | 두 variant의 응답 중 뭐가 더 나은지 LLM이 비교 판정 | 에이전트 호출 2회 + judge 호출 (meta-harness 3단계에서 사용) |

## 실행

```bash
# 기본: langchain-deepagents.py 를 10개 케이스로 평가, 각 1회
uv run python eval/run_eval.py --dataset eval/dataset.json --module langchain-deepagents

# 비결정성 대응: llm_judge 케이스를 3회씩 돌려 다수결로 판정
uv run python eval/run_eval.py --dataset eval/dataset.json --repeat 3

# meta-harness 3단계용: baseline vs variant pairwise 비교
uv run python eval/run_eval.py --dataset eval/dataset.json --pairwise \
    --module-a langchain-deepagents --module-b variant/langchain-deepagents
```

## 주의
- 실행할 때마다 **실제 모델 호출**이 일어난다 (에이전트 자체 + llm_judge 채점 모두). `.env`의 `OPENAI_API_KEY`(OpenRouter) 필요.
- 케이스마다 몇십 초~몇 분 걸릴 수 있다(에이전트가 실제로 `execute`, `write_todos` 등을 수행하므로).
- `R04`(grounding, 업로드 파일 없는데 요약해달라는 케이스)는 지금 스크립트에서 **자동 채점이 안 붙어 있다** — `requires_response_check` 필드로만 표시해뒀고, 사람이 `final_text_sample`을 직접 읽고 판단해야 한다. 필요하면 `run_eval.py`에 이 필드를 처리하는 llm_judge 분기를 추가할 수 있다.
- 새 케이스를 추가하려면 `dataset.json`에 항목을 append하면 된다. 스키마는 기존 항목을 참고.

## 새 케이스 만드는 기준 (슬라이드 Evaluation 파트 참고)
- **명확한 정답이 있는가?** → `rule` (tool 호출 여부, 파일 생성 여부 등 결정적으로 확인 가능한 것)
- **주관적 판단이 필요한가?**(친절함, 안전 원칙 준수, 정직함 등) → `llm_judge`
- **"어느 쪽이 더 나은가"를 비교해야 하는가?**(예: meta-harness로 프롬프트 수정 전후 비교) → `llm_judge_pairwise`
