# 사용 피드백 수신기 — Vercel

팀원이 Pluiz 답변 옆 🚩 로 보낸 신고를 모아 **변소윤이 한 페이지에서 보는** 곳입니다.

> 🚨 **여기가 원본이 아닙니다.** 원본은 각 PC 의 `logs/사용_피드백_보고.md` 입니다.
> 이 서비스가 죽어도 보고는 안 사라집니다 — Pluiz 가 **파일에 먼저 쓰고 나서** 보냅니다.
> 그래서 안 켜도 신고 기능은 그대로 동작합니다(파일로 전달하면 됩니다).

| | |
|---|---|
| 받는 곳 | `POST /api/report` — `x-pluiz-key` 헤더 필요 |
| 보는 곳 | `/` (보기 비밀번호) · 데이터는 `GET /api/list` |
| 저장 | Upstash Redis 리스트 (`pluiz:reports`, 최근 500건) |
| 비용 | Vercel Hobby + Upstash 무료 범위 |

## 🔒 비밀이 **둘**인 이유

| 환경변수 | 누가 갖나 | 할 수 있는 것 |
|---|---|---|
| `INGEST_KEY` | **팀원 PC 의 `.env`** | 보내기만 |
| `VIEW_PASSWORD` | **변소윤만** | 보기만 |

🚨 **하나로 합치지 마세요.** 합치면 팀원 PC 에 깔린 키 하나로 **남의 보고를 전부
읽을 수 있습니다.** 팀원 PC 는 관리 범위 밖이고, 키는 평문으로 `.env` 에 있습니다.

## 처음 올리는 법 (약 10분)

> 🚨 **한 줄씩 복사하세요.** 주석을 같이 붙여넣으면 다음 줄이 딸려 들어가
> `upstashpython ...` 처럼 명령이 뭉개집니다.

### 1. 로그인 (이미 했으면 건너뜀)

```bash
cd feedback-web
npx vercel login
```

### 2. 프로젝트 만들기

```bash
npx vercel link
```

물어보는 것과 답:

| 물어보는 것 | 답 |
|---|---|
| `Set up "…/feedback-web"?` | **Y** |
| `Which scope…?` | 본인 계정 (엔터) |
| `Link to existing project?` | **N** — 새로 만듭니다 |
| `What's your project's name?` | **`pluiz-feedback`** |
| `In which directory is your code located?` | **`./`** (엔터) |

📌 이름이 주소가 됩니다 → `https://pluiz-feedback.vercel.app`.
이미 쓰이는 이름이면 Vercel 이 뒤에 무언가를 붙여 줍니다. 그대로 쓰면 됩니다.
🔑 **주소를 몰라야 안전한 구조가 아닙니다** — 두 입구 모두 비밀을 요구합니다.

### 3. 저장소(Upstash Redis) 붙이기

```bash
npx vercel integration add upstash
```

브라우저가 열립니다. 무료(Free) 플랜으로 데이터베이스를 하나 만들고 이 프로젝트에
연결하면, `UPSTASH_REDIS_REST_URL` · `UPSTASH_REDIS_REST_TOKEN` 이 **자동으로** 꽂힙니다.

> 💡 CLI 가 막히면 대시보드에서 해도 됩니다 — 프로젝트 → **Storage** → Upstash Redis.

### 4. 비밀 두 개 만들기

**서로 다른 값**이어야 합니다. 값을 두 번 뽑아 메모장에 적어 두세요.

```bash
node -e "console.log(require('crypto').randomBytes(24).toString('base64url'))"
```

```bash
npx vercel env add INGEST_KEY production
```

```bash
npx vercel env add VIEW_PASSWORD production
```

각각 값을 물어봅니다(화면에 안 보입니다). 뽑아 둔 값을 하나씩 붙여넣으세요.

🚨 **`INGEST_KEY` 는 팀원에게 줄 것**, **`VIEW_PASSWORD` 는 혼자만 아는 것**입니다.
같은 값을 넣으면 팀원 PC 의 키로 **남의 보고를 전부 읽을 수 있게** 됩니다.

### 5. 올리기

```bash
npx vercel deploy --prod
```

> ⚠️ **순서가 중요합니다.** 환경변수를 넣고 **나서** 올려야 반영됩니다.
> 나중에 값을 바꿨다면 이 명령을 **다시** 돌리세요.

### 6. 팀원 `.env` 에 주소 넣기

```
PLUIZ_FEEDBACK_ENDPOINT=https://pluiz-feedback.vercel.app/api/report
PLUIZ_FEEDBACK_KEY=<INGEST_KEY 와 같은 값>
```

🚨 **키는 저장소가 아니라 직접 전달**하세요(카톡·대면). `.env` 는 커밋되지 않지만,
실수로 올리면 공개됩니다 — 이 저장소가 세 번 데인 자리입니다.

## 잘 되는지 확인 — **막히는 것까지** 봅니다

### ① 올바른 키로 넣어 본다 → `200`

```bash
curl -X POST https://pluiz-feedback.vercel.app/api/report -H "x-pluiz-key: <INGEST_KEY>" -H "Content-Type: application/json" -d "{\"markdown\":\"### 테스트\",\"kind\":\"good\",\"who\":\"개발자\"}"
```

`{"status":"ok","count":1}` 이면 성공입니다.

### ② 🔑 **틀린 키로도 해 본다** → `401`

```bash
curl -X POST https://pluiz-feedback.vercel.app/api/report -H "x-pluiz-key: 틀린키" -H "Content-Type: application/json" -d "{\"markdown\":\"### 테스트\"}"
```

`{"error":"unauthorized"}` 가 나와야 합니다.
🚨 **막히는 걸 확인 안 하면 막혔다고 믿을 수 없습니다.** ①만 보고 넘어가지 마세요.

### ③ 브라우저로 본다

`https://pluiz-feedback.vercel.app` 을 열고 **보기 비밀번호**를 넣습니다.
①에서 넣은 「테스트」가 보이면 끝입니다.

🔑 **보내기 키(`INGEST_KEY`)를 넣어 보세요. 안 열려야 맞습니다.**

---

## 안 될 때

| 증상 | 원인 · 할 것 |
|---|---|
| curl 에 **HTML 로그인 페이지**가 돌아온다 | Vercel 의 **Deployment Protection** 이 켜져 있습니다. 프로젝트 → Settings → Deployment Protection → **Vercel Authentication 을 Production 에서 끕니다.** (두 입구 모두 비밀을 요구하므로 이걸 꺼도 안전합니다) |
| `{"error":"store_failed"}` | Upstash 연결이 안 된 것입니다. 3번을 하고 **`vercel deploy --prod` 를 다시** 돌리세요 |
| 올바른 키인데 `401` | 환경변수를 넣고 **재배포를 안 한** 경우입니다. 5번을 다시 |
| Pluiz 가 *"수신기에 닿지 못했어요"* | `.env` 의 `PLUIZ_FEEDBACK_ENDPOINT` 주소 끝이 **`/api/report`** 인지 보세요 |
| Pluiz 가 *"보내기 키가 맞지 않아요"* | `.env` 의 `PLUIZ_FEEDBACK_KEY` 와 Vercel 의 `INGEST_KEY` 가 다릅니다 |

📌 **어느 경우든 보고는 안 사라집니다.** 로컬 `logs/사용_피드백_보고.md` 에 이미
쌓여 있고, 화면이 그렇게 말해 줍니다. 전송은 덤입니다.

---

## 선택 — GitHub 에 연결해 자동 배포

안 해도 됩니다(`vercel deploy --prod` 로 충분). 하려면 프로젝트 →
Settings → Git 에서 저장소를 연결하고, 🚨 **Root Directory 를 `feedback-web` 으로**
지정하세요. 안 하면 저장소 루트(파이썬 프로젝트)를 빌드하려다 실패합니다.

---

## 켜고 끄기

`.env` 의 `PLUIZ_FEEDBACK_ENDPOINT` 를 **지우면 즉시 안 나갑니다.** 신고는 그대로
되고 파일에만 쌓입니다. 기본값이 «안 보냄» 이라, 설정하지 않은 PC 에서는
아무것도 밖으로 나가지 않습니다.

## 무엇이 올라가는가

보고서 마크다운 한 덩어리입니다 — 말한 내용 · Pluiz 의 답 · 시각 · 기대한 것,
그리고 (팀원이 끄지 않았으면) **그때 로그 발췌**. 주민번호·카드번호·API 키는
보내기 전에 `core/security.mask_sensitive_output` 으로 가립니다.

🚨 그래도 **화면에서 읽은 창 제목 같은 것이 로그에 섞일 수 있습니다.** 그래서 UI 가
보낼 내용을 **그대로 보여 주고** 로그를 끌 수 있게 합니다. 켤지 말지는 팀원이 봅니다.
