# Slack 연동 가이드

deep agent에 Slack을 붙이는 전체 과정 — **무엇을 발급받고, 어떻게 설정하고, 어떻게 테스트하는지**.

---

## 0. 두 가지 사용 방향

Slack 연동은 방향에 따라 필요한 토큰과 설정이 다릅니다.

| 방향 | 설명 | 필요한 토큰 |
|---|---|---|
| **A. 에이전트 → Slack** | Studio/게이트웨이에서 에이전트가 Slack에 **메시지 전송·채널 읽기** | `SLACK_BOT_TOKEN` (+ 선택 `SLACK_USER_TOKEN`) |
| **B. Slack → 에이전트 → Slack** | Slack에서 봇을 **멘션·DM** 하면 에이전트가 실행돼 Slack으로 답변 | 위 + `SLACK_APP_TOKEN` (Socket Mode) |

- A만 필요하면 **1~3단계 + 7~8단계**.
- B(대화형 봇)까지 원하면 **전체**.

## 토큰 3종 요약

| 토큰 | 접두사 | 정체성 | 용도 | .env 변수 |
|---|---|---|---|---|
| Bot Token | `xoxb-` | 봇(별도 사용자) | 메시지 전송, 공개 채널 읽기 | `SLACK_BOT_TOKEN` |
| User Token | `xoxp-` | 나(권한 위임) | **초대 없이** 내 비공개 채널 읽기 | `SLACK_USER_TOKEN` |
| App-Level Token | `xapp-` | 앱 | Socket Mode 수신(멘션/DM) | `SLACK_APP_TOKEN` |

---

## 1. Slack 앱 생성

1. https://api.slack.com/apps → **Create New App** → **From scratch**
2. 앱 이름(예: `cowork-agent`) 입력 → 사용할 워크스페이스 선택 → **Create App**

---

## 2. Bot Token Scopes (필수 — 전송/읽기)

왼쪽 메뉴 **OAuth & Permissions** → **Scopes → Bot Token Scopes** 에 추가:

| Scope | 용도 |
|---|---|
| `chat:write` | 메시지 **전송** (`slack_send_message`, 봇 답장) |
| `channels:history` | **공개** 채널 메시지 읽기 (`slack_read_channel`) |
| `channels:read` | 채널 정보 조회 |
| `groups:history`, `groups:read` | **비공개** 채널 읽기(봇이 초대된 경우) |
| `app_mentions:read` | (방향 B) 채널 멘션 이벤트 수신 |
| `im:history`, `im:read` | (방향 B) 봇 DM 수신 |

---

## 3. User Token Scopes (선택 — 초대 없이 비공개 채널 읽기)

봇을 채널에 초대하지 않고 **내가 이미 속한** (비)공개 채널을 읽으려면 사용자 토큰을 씁니다.
같은 **OAuth & Permissions** 페이지 아래쪽 **User Token Scopes** 에 추가:

| Scope | 용도 |
|---|---|
| `channels:history` | 공개 채널 읽기 |
| `groups:history` | **비공개** 채널 읽기 (초대 불필요) |
| `channels:read`, `groups:read` | 채널 목록/정보 조회 |
| `im:history`, `mpim:history` | (선택) DM·그룹 DM 읽기 |

> 참고: 읽기=사용자 토큰, 쓰기=봇 토큰으로 분리돼 있습니다. 둘 중 하나만 넣어도 그 토큰으로 읽기·쓰기를 모두 처리합니다.

---

## 4. App-Level Token + Socket Mode + 이벤트 (방향 B — 대화형 봇)

Slack에서 봇을 멘션/DM 해서 에이전트를 호출하려면 이 단계가 필요합니다.

### 4-1. App-Level Token 발급
1. 왼쪽 메뉴 **Basic Information** → 아래 **App-Level Tokens** → **Generate Token and Scopes**
2. 이름(예: `socket`) → **Add Scope** → `connections:write` → **Generate**
3. `xapp-` 로 시작하는 토큰 복사

### 4-2. Socket Mode 켜기
왼쪽 메뉴 **Socket Mode** → **Enable Socket Mode** 토글 **ON**

### 4-3. 이벤트 구독
왼쪽 메뉴 **Event Subscriptions** → **Enable Events** ON (Socket Mode라 Request URL 불필요)
→ **Subscribe to bot events** 에 추가:
- `app_mention` — 채널 멘션 수신
- `message.im` — 봇 DM 수신

---

## 5. App Home — DM 허용 (방향 B에서 DM 쓰려면)

봇에게 DM을 보내려면 메시지 탭을 열어야 합니다. (안 열면 "이 앱으로 메시지를 보내는 기능이 꺼져 있습니다" 표시)

1. 왼쪽 메뉴 **App Home** → **Show Tabs** 섹션
2. **Messages Tab** 토글 **ON**
3. **"Allow users to send Slash commands and messages from the messages tab"** 체크박스 **체크**

---

## 6. 워크스페이스에 설치 / 재설치

- 왼쪽 **OAuth & Permissions** → **Install to Workspace** (스코프·이벤트를 바꿀 때마다 **Reinstall** 필요) → 승인
- 발급되는 토큰 복사:
  - **Bot User OAuth Token** (`xoxb-`)
  - **User OAuth Token** (`xoxp-`, User Scopes를 넣었다면)

---

## 7. `.env` 설정

프로젝트 루트 `.env` 에 입력 (`.env.example` 참고):

```dotenv
# 전송용 (봇 명의)
SLACK_BOT_TOKEN=xoxb-...
# 읽기용 (초대 없이 내 채널 열람, 선택)
SLACK_USER_TOKEN=xoxp-...
# 수신용 Socket Mode (방향 B, 선택)
SLACK_APP_TOKEN=xapp-...
```

> `.env` 는 gitignore 되어 커밋되지 않습니다. 필요한 키 목록은 `.env.example` 에 있습니다.

---

## 8. 실행

```bash
uv run python langchain-deepagents.py
```

이 한 번의 실행이:
1. **Studio UI**(langgraph dev)를 띄우고
2. Slack 수신이 **실제로 연결되면** 게이트웨이도 자동으로 함께 실행합니다.

정상 기동 로그 예시:
```
[connector] Slack 활성화                         ← 에이전트 도구로 Slack 붙음(방향 A)
[gateway] slack 연결 확인 → 실행 (팀명/봇이름)   ← 라이브 연결 확인(방향 B)
게이트웨이 실행 중 → slack (메신저에서 에이전트 사용 가능)
⚡️ Bolt app is running!                          ← Socket Mode 웹소켓 연결 성공
- 🎨 Studio UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

> `게이트웨이`는 **env가 채워졌고 + 실제 연결까지 성공**한 채널만 실행합니다. `xapp-` 토큰이 없으면 방향 B는 건너뜁니다(방향 A 도구는 그대로 동작).
>
> 게이트웨이만 따로 돌리려면 `uv run python gateway.py`. 단, 통합 실행과 **동시에** 띄우지 마세요(수신 중복).

---

## 9. 테스트

### 9-1. 방향 A — 에이전트 → Slack (Studio에서)
브라우저 Studio UI에서 `deepagent` 선택 후 자연어로:
- 전송: `슬랙 #general 에 '테스트 메시지' 보내줘`
- 읽기: `슬랙 C0123ABCD 채널 최근 20개 읽고 요약해줘`
  - 채널 ID 찾기: Slack에서 채널명 클릭 → 세부정보 맨 아래 `채널 ID`(`C…`)

### 9-2. 방향 B — Slack → 에이전트 → Slack

**DM 테스트**
1. Slack에서 봇(예: `cowork-agent`) 검색 → 1:1 메시지
2. `안녕, 자기소개 해줘` 전송
3. 잠시 후 봇이 답장하면 성공

**멘션 테스트**
1. 아무 채널에서 `/invite @봇이름`
2. `@봇이름 이번 주 할 일 정리해줘`
3. 봇이 **같은 스레드**에 답글

> 첫 답변은 몇 초 걸립니다(에이전트가 계획·모델 호출). 실행 중인 **터미널**에 에러(traceback)가 찍히는지 함께 확인하세요.

---

## 10. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| "이 앱으로 메시지를 보내는 기능이 꺼져 있습니다" | **5단계** App Home → Messages Tab ON + 체크박스 |
| DM 무반응 | `message.im` 이벤트 구독 + `im:history`/`im:read` 스코프 확인, 재설치 |
| 멘션 무반응 | 봇이 그 채널에 있는지(`/invite`), `app_mentions:read` 스코프 확인 |
| `게이트웨이 slack 연결 실패로 제외` | 봇 토큰 오류 — `auth.test` 실패. 토큰/재설치 확인 |
| `⚡️ Bolt app is running!` 안 뜸 | `SLACK_APP_TOKEN`(xapp-) 누락 또는 Socket Mode 미활성. 프록시가 웹소켓을 막는 경우도 있음 |
| 같은 답이 2~3번 옴 | 에이전트 처리가 3초를 넘겨 Slack이 이벤트 재전송. "즉시 ack + 백그라운드 처리"로 수정 필요 |
| `token will be unused` 경고 | 무해함(코드가 `client`를 직접 넘겨서 나는 안내). |

---

## 11. 참고 사항

- **TLS 검사 프록시**: 이 프로젝트는 사내 프록시 환경을 가정해 인증서 검증을 끕니다(`verify=False`). Socket Mode는 웹소켓(wss)이라, 프록시가 웹소켓을 차단하면 방향 B가 안 될 수 있습니다. 그때도 Telegram/Email/방향 A는 영향받지 않습니다.
- **대화 문맥**: 게이트웨이는 대화(채널/스레드/사용자)별로 문맥을 유지하지만 프로세스 메모리(InMemorySaver)라 재시작 시 초기화됩니다. 장기 메모리(`workspace/AGENTS.md`)와 작업 파일은 디스크에 계속 남습니다.
- **보안**: 봇 토큰은 초대된 채널만, 사용자 토큰은 내 권한 전체로 동작합니다. 토큰은 절대 커밋하지 말고 `.env`(gitignore)에만 두세요.

관련 코드: `connectors.py`(SlackConnector), `gateway.py`(SlackAdapter), `.env.example`.
