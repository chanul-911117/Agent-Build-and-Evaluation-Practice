# Telegram 연동 가이드

deep agent에 Telegram을 붙이는 전체 과정 — **무엇을 발급받고, 어떻게 설정하고, 어떻게 테스트하는지**.

Telegram은 셋(Slack/Telegram/Email) 중 **가장 간단**합니다. 봇 토큰 하나면 되고, Slack처럼 스코프·이벤트·App 토큰 설정이 없습니다.

---

## 0. 두 가지 사용 방향

| 방향 | 설명 | 필요한 것 |
|---|---|---|
| **A. 에이전트 → Telegram** | Studio/게이트웨이에서 에이전트가 텔레그램으로 **메시지 전송** | `TELEGRAM_BOT_TOKEN` (+ 선택 `TELEGRAM_CHAT_ID`) |
| **B. Telegram → 에이전트 → Telegram** | 봇에게 **메시지/DM** 보내면 에이전트가 실행돼 텔레그램으로 답변 | `TELEGRAM_BOT_TOKEN` (동일) |

Slack과 달리 **B(대화형 봇)도 추가 토큰이 없습니다.** 봇 토큰 하나로 getUpdates 롱폴링 수신까지 됩니다.

---

## 1. 봇 생성 (@BotFather)

1. Telegram 앱에서 **@BotFather** 검색 → 대화 시작
2. `/newbot` 전송
3. **봇 표시 이름** 입력 (예: `Cowork Agent`)
4. **봇 username** 입력 — 반드시 `bot`으로 끝나야 함 (예: `my_cowork_bot`)
5. BotFather가 **토큰**을 줍니다 → `123456789:ABCdef...` 복사

---

## 2. `.env` 설정

프로젝트 루트 `.env` 에 입력 (`.env.example` 참고):

```dotenv
TELEGRAM_BOT_TOKEN=123456789:ABCdef...복사한-토큰
# (선택) 에이전트가 도구로 '먼저' 보낼 때의 기본 대상 chat_id.
# 게이트웨이 수신·답장에는 불필요(받은 chat 으로 답장함).
TELEGRAM_CHAT_ID=
```

> `.env` 는 gitignore 되어 커밋되지 않습니다.

---

## 3. 실행

```bash
uv run python langchain-deepagents.py
```

이 한 번의 실행이 Studio UI를 띄우고, Telegram 연결이 **실제로 확인되면** 게이트웨이도 함께 실행합니다.

정상 기동 로그:
```
[connector] Telegram 활성화                          ← 에이전트 도구로 Telegram 붙음(방향 A)
[gateway] telegram 연결 확인 → 실행 (@my_cowork_bot)  ← getMe 로 라이브 연결 확인(방향 B)
게이트웨이 실행 중 → telegram
```

> `게이트웨이`는 **토큰이 있고 + 실제 연결(getMe)이 성공**한 채널만 실행합니다.
>
> 게이트웨이만 따로 돌리려면 `uv run python gateway.py`. 단, 통합 실행과 **동시에** 띄우지 마세요 — 봇당 `getUpdates` 는 하나만 가능해서 충돌(409)합니다.

---

## 4. 테스트

1. Telegram에서 방금 만든 봇 **@username** 검색 → **Start** 또는 아무 메시지 전송
2. `안녕, 자기소개 해줘` 보내기
3. 봇이 답장하면 성공 — 메모리·파일·다른 커넥터까지 붙은 그 deep agent가 응답합니다

실행 중인 터미널에 처리 로그가 찍힙니다:
```
[telegram] 수신(12345678): 안녕 자기소개 해줘
[telegram] 답장 전송 → 12345678 (3.2s)
```
- `수신` = 메시지 받음, `답장 전송` = 처리+전송 완료(괄호 안은 소요시간).

### 대화 초기화
봇에게 `/new` (또는 `new`)를 보내면 **그 대화만** 문맥이 초기화됩니다.

---

## 5. 트러블슈팅

### 5-1. `[Errno 54] Connection reset by peer` (연결 리셋)
**증상**: 시작 시 `telegram 연결 실패로 제외` 또는 폴링 중 리셋.

**원인**: 일부 사내망/기관 DPI가 `api.telegram.org` 로 가는 **파이썬 TLS 핸드셰이크를 지문으로 리셋**합니다. `curl` 은 통과하는데 `httpx`/`urllib` 는 막히는 게 특징입니다. (Telegram이 흔한 차단 표적)

**해결(이미 적용됨)**: 이 프로젝트는 브라우저 TLS를 위장하는 **`curl_cffi`**(libcurl 기반)로 텔레그램 요청을 보냅니다 — `connectors.py` 의 `_tg_get`/`_tg_post`. curl이 되는 환경이면 이걸로 통과합니다.

**그래도 리셋되면**:
- 먼저 `curl -k "https://api.telegram.org/bot<토큰>/getMe"` 로 도달 여부 확인(http=200이어야 함).
- curl조차 안 되면 네트워크가 Telegram 자체를 차단하는 것 → 다른 네트워크(핫스팟) 또는 VPN 필요.

### 5-2. 봇이 무반응
| 원인 | 확인 |
|---|---|
| 게이트웨이가 안 떴음 | 로그에 `게이트웨이 실행 중 → telegram` 있는지 |
| 통합 실행과 `gateway.py` **동시 실행** | 하나만 실행 (getUpdates 충돌) |
| 봇에 webhook 설정됨 | getUpdates 와 배타적. 새 봇은 해당 없음 |
| 그룹 채팅에서 멘션 필요 | 기본 privacy mode. @BotFather `/setprivacy` 로 조정(1:1 DM은 무관) |

### 5-3. 답변이 너무 느림
`gpt-5` 계열은 추론 모델이라 사소한 질문도 수십 초 걸릴 수 있습니다. 시스템 문제가 아니라 **모델의 호출당 추론 시간**입니다.

**해결(이미 적용됨)**: `langchain-deepagents.py` 의 `init_chat_model(...)` 에 `reasoning_effort="low"` 를 설정해 호출당 지연을 크게 줄였습니다(예: 80s → 3s). 복잡한 추론이 필요하면 `"medium"`/`"high"` 로 올릴 수 있습니다.

---

## 6. 참고 사항

- **큐 보관**: 게이트웨이가 꺼져 있는 동안 봇에게 보낸 메시지는 Telegram이 잠시 큐에 보관합니다. 다시 켜면 **밀린 메시지부터** 처리·답장합니다(정상 동작).
- **대화 문맥**: 게이트웨이는 대화(chat)별로 문맥을 유지하지만 프로세스 메모리(InMemorySaver)라 재시작 시 초기화됩니다. 장기 메모리(`workspace/AGENTS.md`)와 작업 파일은 디스크에 남습니다.
- **보안**: 봇 토큰은 절대 커밋하지 말고 `.env`(gitignore)에만 두세요.

관련 코드: `connectors.py`(TelegramConnector, `_tg_get`/`_tg_post`), `gateway.py`(TelegramAdapter), `.env.example`.
