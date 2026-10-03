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

```bash
cd feedback-web
npx vercel login          # 이미 했으면 건너뜁니다
npx vercel link           # 새 프로젝트로 만듭니다
npx vercel integration add upstash    # Redis 환경변수가 자동으로 꽂힙니다
```

비밀 두 개를 넣습니다. **아무도 못 맞출 긴 문자열**로 만드세요.

```bash
# 값 만들기 (둘을 서로 다르게)
python -c "import secrets; print(secrets.token_urlsafe(32))"

npx vercel env add INGEST_KEY production
npx vercel env add VIEW_PASSWORD production
npx vercel deploy --prod
```

배포가 끝나면 나오는 주소를 팀원 `.env` 에 넣습니다.

```
PLUIZ_FEEDBACK_ENDPOINT=https://<프로젝트>.vercel.app/api/report
PLUIZ_FEEDBACK_KEY=<INGEST_KEY 와 같은 값>
```

> ⚠️ `.env` 는 저장소에 안 올라갑니다. **키는 저장소가 아니라 직접 전달**하세요.
> 저장소에 올리면 공개됩니다 — 이 저장소가 세 번 데인 자리입니다.

## 잘 되는지 확인

```bash
curl -X POST https://<프로젝트>.vercel.app/api/report \
  -H "x-pluiz-key: <INGEST_KEY>" -H "Content-Type: application/json" \
  -d '{"markdown":"### 테스트","kind":"good","who":"개발자"}'
# → {"status":"ok","count":1}
```

그 다음 브라우저로 `https://<프로젝트>.vercel.app` 을 열고 보기 비밀번호를 넣습니다.

🔑 키를 **틀리게** 한 번 넣어 401 이 나는 것도 같이 보세요. 막히는 걸 확인 안 하면
막혔다고 믿을 수 없습니다.

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
