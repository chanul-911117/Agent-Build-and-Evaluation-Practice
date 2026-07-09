# 이메일(Gmail) 연동 가이드

deep agent에 이메일을 붙이는 전체 과정 — **무엇을 발급받고, 어떻게 설정하고, 어떻게 쓰는지**,
그리고 흔한 네트워크 문제(포트 차단·연결 한도)와 대안까지.

Slack/Telegram과 달리 이메일은 **게이트웨이 자동 응답을 하지 않습니다**(개인 메일함에 자동
답장하는 위험 회피). 대신 두 가지로 동작합니다:

| 기능 | 설명 |
|---|---|
| **에이전트 도구** | `read_recent_emails`(읽기), `send_email`(발송) — 요청받을 때만 |
| **이메일 트리거** | 조건에 맞는 새 메일이 오면 규칙의 작업을 실행(옵트인, 규칙 CRUD는 스킬로) |

---

## 1. Gmail 앱 비밀번호 발급

Gmail은 일반 비밀번호로 외부 앱 로그인을 막으므로 **앱 비밀번호**가 필요합니다.

1. Google 계정 → **보안** → **2단계 인증** 켜기 (앱 비밀번호의 전제조건)
2. https://myaccount.google.com/apppasswords → 앱 이름(예: `cowork-agent`) → **만들기**
3. **16자리 비밀번호** 복사
4. (필요 시) Gmail 웹 → 설정 → **전달 및 POP/IMAP** → **IMAP 사용** (최근 계정은 기본 켜짐)

> ⚠️ **전용 봇 계정 권장**: 이메일 트리거/읽기를 안정적으로 쓰려면 **봇 전용 Gmail 계정**을
> 새로 만드는 걸 권합니다. 개인 메인 Gmail은 폰/PC 메일 앱이 IMAP으로 붙어 있어 아래 5-2의
> "연결 한도" 문제가 생기기 쉽습니다.

## 2. `.env` 설정

```dotenv
# 발신 (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-bot@gmail.com
SMTP_PASSWORD=앱비밀번호16자리
EMAIL_FROM=your-bot@gmail.com
# 수신 (IMAP) — USER/PASSWORD 생략 시 SMTP 값 재사용
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
```

## 3. 실행 & 무엇이 켜지나

```bash
uv run python langchain-deepagents.py
```

- **이메일 도구**가 붙습니다: `[connector] Email 활성화`
- **이메일 트리거 감시기**가 IMAP 연결되면 실행됩니다: `[gateway] email-trigger 연결 확인 → 실행`
  - 규칙이 없으면 조용히 대기만 합니다.
  - 감시 시작 시점 **이후 새 메일부터** 트리거합니다(과거 메일 제외).

## 4. 사용법

### 도구 (Studio / 텔레그램 / 슬랙에서 자연어로)
- 읽기: "새 메일 있어?"(→ `unread_only`), "최근 메일 10개 요약해줘"(→ `limit`)
- 발송: "kim@example.com 에게 '회의 확정' 제목으로 메일 보내줘"

### 이메일 트리거 (조건 → 작업)
"billing@ 에서 invoice 메일 오면 슬랙 C012에 요약 보내줘" 처럼 말하면, 에이전트가
`set-email-triggers` 스킬로 규칙을 등록합니다. 규칙은 workspace의 `email_triggers.json`에
저장되고, 감시기가 **매 폴링(기본 30초)마다 재로드**하므로 재시작이 필요 없습니다.

- 로그: `[email-trigger] 매칭 '규칙명' ← 발신자 / 제목` → `처리 완료 (N초)`
- 형식 예시: 프로젝트 루트의 `email_triggers.example.json`

---

## 5. 트러블슈팅

### 5-1. `[Errno 54] Connection reset by peer` (IMAP 연결 리셋)
**원인**: 일부 **사내망/기관 방화벽이 메일 수신 포트(IMAP 993, SMTPS 465)를 차단**합니다.
curl/OpenSSL로도 TLS가 리셋되면(파이썬만이 아니라) 네트워크 차단입니다.

**진단**:
```bash
nc -z -G 5 imap.gmail.com 993                 # TCP 도달?
openssl s_client -connect imap.gmail.com:993 -brief </dev/null   # TLS 되나? (write:errno=54 면 차단)
openssl s_client -connect smtp.gmail.com:587 -starttls smtp -brief </dev/null  # 발송(587)은 대개 열림
```

**대안**:
- **다른 네트워크**(집/핫스팟)에서 실행하면 IMAP이 됩니다. `send_email`(587)은 사내망에서도 대개 동작.
- 사내망에서도 읽기/트리거가 필요하면 → **Gmail API(HTTPS 443)** 로 전환(5-4 참고). 사내망은 보통
  443은 열어두므로 API는 통과합니다.

### 5-2. `[ALERT] Too many simultaneous connections`
**원인**: Gmail은 계정당 **동시 IMAP 연결 ~15개**로 제한합니다. 폰/PC 메일 앱이 이미 붙어 있거나
짧은 시간에 여러 번 연결하면 한도에 걸립니다. (TLS 리셋과 달리 이건 Gmail의 정상 응답 =
네트워크는 뚫렸다는 뜻)

**동작**: 감시기는 이 에러를 **일시적**으로 취급해 제외하지 않고, 폴링마다 **자동 재시도**합니다.
자리가 나면 스스로 붙습니다(로그의 `폴링 오류` 가 멈추면 정상 작동 중).

**해결**:
1. **봇 전용 Gmail 계정** 사용 (다른 앱이 안 붙어 항상 여유) — 가장 확실.
2. 또는 이 계정의 폰/PC 메일 앱에서 IMAP을 잠시 끄기.
3. 계속되면 계정에 로그인한 상태로 https://accounts.google.com/DisplayUnlockCaptcha 실행 후 재시도.

### 5-3. 발송은 되는데 읽기만 안 됨
정상적인 사내망 증상입니다. **SMTP 587(발송)은 열려 있고 IMAP 993(수신)만 차단**된 것.
`send_email`은 그대로 쓰고, 읽기/트리거는 5-1의 대안을 따르세요.

### 5-4. "최신 보안 표준"으로 가고 싶다 (앱 비밀번호 대신 OAuth)
Google이 앱 비밀번호를 "구형"이라고 경고하는데, 최신 방식은 **OAuth2 + Gmail API(HTTPS)** 입니다.

| | IMAP + 앱 비밀번호 | Gmail API + OAuth2 |
|---|---|---|
| 사내망(993 차단) | ❌ | ✅ (HTTPS 443) |
| 동시 연결 한도 | ❌ 15개 제한 | ✅ 무관(REST) |
| 재사용성 | ✅ **범용**(모든 IMAP 메일 동일 코드) | ❌ provider별(Gmail API ≠ MS Graph) |

- **재사용성 트레이드오프**: IMAP은 host/port만 바꾸면 어느 provider든 동작합니다. OAuth+API는
  provider마다 API가 달라 각각 구현이 필요하지만, 우리 구조(도구·트리거·매칭)는 그대로 두고
  **백엔드만 갈아끼우는** 설계로 하면 상위 코드는 재사용됩니다.
- 참고: IMAP에 OAuth 토큰을 쓰는 **XOAUTH2** 도 있지만, 여전히 IMAP이라 5-1/5-2 문제는 해결하지 못합니다.
- 결론: **사내망에서도 읽기/트리거가 필요하면** Gmail API가 실질적 해법입니다(Google Cloud
  프로젝트 + OAuth 동의 설정 필요). 지금은 IMAP으로 두고, 필요해지면 백엔드를 추가하면 됩니다.

---

## 6. 이메일 트리거 규칙 (상세)

규칙은 workspace의 `email_triggers.json`(JSON 배열)에 저장됩니다. 편집은 **스킬의 스크립트**로 합니다
(에이전트가 JSON을 직접 고치다 깨뜨리지 않도록).

### 규칙 구조
```json
{
  "name": "고유한 규칙 이름",
  "match": { "from": "billing@", "subject_contains": ["invoice", "청구서"], "body_contains": "..." },
  "action": "매칭된 메일에 대해 무엇을 할지 자연어로"
}
```
- `match`: 지정한 조건만 검사하며 **전부 만족해야 매칭**(AND). `subject_contains`/`body_contains`
  는 배열이면 그중 하나라도(OR). `match`가 비면 **모든** 메일에 매칭되니 주의.
- `action`: 매칭 메일(발신자/제목/본문)이 함께 주어진 상태로 실행. Slack/Telegram 전송,
  파일 저장(`write_file`), 메일 발송(`send_email`) 등.

### 스킬 스크립트 (직접 실행도 가능)
`workspace/skills/set-email-triggers/manage_triggers.py` — 스키마 검증 + 원자적 저장.
```bash
# workspace 디렉터리에서
python3 skills/set-email-triggers/manage_triggers.py list
python3 skills/set-email-triggers/manage_triggers.py add \
  --name "인보이스 알림" --from "billing@" --subject-contains "invoice" \
  --action "이 인보이스의 금액/마감일을 요약해 Slack C012 로 보내줘."
python3 skills/set-email-triggers/manage_triggers.py update --name "인보이스 알림" --rename "청구서 알림"
python3 skills/set-email-triggers/manage_triggers.py remove --name "청구서 알림"
```
> 이 스킬은 `workspace_seed/skills/set-email-triggers/` 를 소스로 하며, 실행 시 workspace/skills 로 동기화됩니다.

---

## 7. 참고 사항

- **읽음 처리 안 함**: 읽기·트리거 모두 IMAP `readonly` 로 조회하므로 메일함 안읽음 상태를 유지합니다.
  트리거는 마지막 처리 UID를 `workspace/.email_trigger_state.json` 에 기록해 중복 없이 폴링합니다.
- **폴링 주기**: `EMAIL_POLL_SECONDS`(기본 30초).
- **보안**: 앱 비밀번호/토큰은 절대 커밋하지 말고 `.env`(gitignore)에만 두세요. 규칙에 자격증명 금지.

관련 코드: `connectors.py`(EmailConnector), `gateway.py`(EmailTriggerAdapter), `.env.example`,
`workspace_seed/skills/set-email-triggers/`.
