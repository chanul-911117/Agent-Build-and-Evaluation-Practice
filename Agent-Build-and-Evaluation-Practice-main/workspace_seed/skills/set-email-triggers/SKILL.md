---
name: set-email-triggers
description: 이메일 트리거 규칙(email_triggers.json)을 조회·추가·수정·삭제한다. 사용자가 "특정 조건의 메일이 오면 ~해줘"처럼 이메일 자동화 규칙을 만들거나 바꾸거나 지워달라고 할 때 사용한다.
---

# 이메일 트리거 규칙 관리

게이트웨이의 이메일 감시기(EmailTriggerAdapter)는 workspace 루트의 `email_triggers.json`
을 매 폴링마다 읽어, 새로 도착한 메일이 규칙 조건에 맞으면 그 규칙의 `action` 을 실행한다.
**파일을 바꾸면 다음 폴링(기본 30초)에 자동 반영**되므로 재시작이 필요 없다.

## 규칙 CRUD 는 스크립트로 한다 (중요)
JSON 을 직접 편집하지 말고, 이 스킬에 포함된 **`manage_triggers.py`** 를 `execute` 도구로
실행한다. 스크립트가 스키마 검증·원자적 저장을 해주므로 JSON 손상이 없다. 명령은
**workspace 디렉터리에서** 실행한다(경로는 workspace 기준 상대경로).

```bash
# 목록
python3 skills/set-email-triggers/manage_triggers.py list

# 추가
python3 skills/set-email-triggers/manage_triggers.py add \
  --name "규칙이름" --action "매칭 시 할 일(자연어)" \
  [--from "billing@"] [--subject-contains "invoice" --subject-contains "청구서"] [--body-contains "..."]

# 수정 (지정한 필드만 바뀜)
python3 skills/set-email-triggers/manage_triggers.py update \
  --name "규칙이름" [--rename "새이름"] [--action "..."] \
  [--from ...] [--subject-contains ...] [--body-contains ...] \
  [--clear-from] [--clear-subject] [--clear-body]

# 삭제
python3 skills/set-email-triggers/manage_triggers.py remove --name "규칙이름"
```

### match 조건 (지정한 것만 검사, 전부 만족해야 매칭 = AND)
- `--from`: 발신자에 이 문자열 포함(부분 일치, 대소문자 무시).
- `--subject-contains`: 제목 포함. **여러 번 지정하면 그중 하나라도(OR)**.
- `--body-contains`: 본문 포함. 여러 번 지정하면 OR.
- ⚠️ 조건을 하나도 안 주면 **모든** 새 메일에 매칭되니 특별한 경우가 아니면 피한다
  (스크립트가 경고를 출력한다).

### action
- 매칭된 메일(발신자/제목/본문)이 함께 주어진 상태로 실행되는 자연어 지시.
- 쓸 수 있는 도구 예: `telegram_send_message`, `slack_send_message`, `write_file`(파일 저장),
  `send_email`(메일 발송). 대상 채널 ID/주소 등을 구체적으로 적는다.

## 절차
1. 사용자 요청을 파악해 적절한 `manage_triggers.py` 명령을 `execute` 로 실행한다.
2. 스크립트 출력(성공/오류)을 확인한다. 필요하면 `list` 로 결과를 재확인한다.
3. 사용자에게 무엇을 바꿨는지(추가/수정/삭제한 규칙 이름) 한 줄로 요약한다.

## 예시
사용자: "billing@ 에서 invoice 메일 오면 슬랙 C012 에 요약 알림 보내줘"
→ `execute`:
```bash
python3 skills/set-email-triggers/manage_triggers.py add \
  --name "인보이스 알림" --from "billing@" --subject-contains "invoice" \
  --action "이 인보이스 메일의 금액과 마감일을 요약해서 Slack 채널 C012 로 보내줘."
```

사용자: "인보이스 알림 규칙 지워줘"
→ `python3 skills/set-email-triggers/manage_triggers.py remove --name "인보이스 알림"`

## 주의
- API 키·비밀번호 등 자격증명은 규칙에 넣지 않는다.
