# collect-server — 녹음 페이지 배포 · 목소리 수집 (M7 1-1)

> 📍 상위: [`docs/planning/개발_계획.md`](../../docs/planning/개발_계획.md) §6 · 부탁 문구는
> [`docs/teamwork/녹음_부탁드립니다.md`](../../docs/teamwork/녹음_부탁드립니다.md)
>
> **왜 있나** — 파일을 메일로 주고받으면 20~30명이 안 모인다. URL 하나면 모인다.
> M7의 임계 경로가 «사람 모으기»라, **참여 마찰을 줄이는 것이 곧 데이터 양**이다.

## 페이지는 한 벌뿐이다

원본은 **`scripts/플루이즈_녹음.html`** 이고 여기엔 복사본이 없다.
`build.mjs` 가 그 파일에 `<script src="uploader.js">` 한 줄만 끼워 `public/` 으로 굽는다.

| 어떻게 여나 | 무엇이 되나 |
|---|---|
| 파일을 더블클릭 (오프라인) | `window.PLUIZ_SEND` 가 없다 → **파일 2개로 받기** |
| 배포된 URL | 업로더가 먼저 실린다 → **«보내기» 버튼** |

🔑 **두 벌로 나누면 반드시 한쪽만 갱신된다** — 이 저장소가 반복해서 데인 모양이다.

## 🚨 왜 그냥 POST 하지 않는가

**Vercel 함수 본문 한도가 4.5MB인데 WAV가 5.7MB다.** 그냥 올리면 413이다.
그래서 브라우저가 Blob 저장소로 **직접** 올리고 함수는 토큰만 발급한다.

```
브라우저 ──① 매니페스트(4KB) ──▶ /api/meta ──▶ Blob (private)
         ◀── 저장 경로(base) ───┘
         ──② 토큰 요청 ─────────▶ /api/upload  (파일은 안 지나간다)
         ──③ WAV(5.7MB) ────────────────────▶ Blob (private)  ← 직행
```

**①을 먼저 하는 이유**: ③이 실패해도 «누가 어디까지 했다»가 남는다. 다시 부탁할 수 있다.

## 🔒 사람 목소리다

- **`access: 'private'`** — URL을 알아도 못 듣는다. 동의 문구가 «공개하지 않는다» 이고 **그 약속을 코드가 지킨다**
- **목록 API를 안 만들었다** — 그게 곧 «누가 녹음했는지 공개»다. 목록은 `pull.mjs` 로 **내 컴퓨터에서만** 본다
- `/api/meta` 가 **`consent !== true` 면 거절**한다. 페이지가 이미 막지만 페이지는 우회할 수 있다
- `/api/upload` 토큰에 제약을 건다 — `audio/wav` 만 · 12MB 까지 · `pluiz_<이름>_<14자리>.wav` 꼴만.
  ⚠️ **이 주소는 모르는 사람에게 공개된다**(그게 목적이다). 제약이 없으면 남의 저장소에 아무거나 올리는 문이 된다

## 쓰는 법

```bash
cd scripts/collect-server
npm install
npm run deploy          # 로컬에서 굽고 → 배포

# 모인 것 내려받기
vercel env pull .env.local
npm run pull            # → data/wakeword_raw/
python ../ingest_wakeword.py --list
```

> ⚠️ **Vercel 에서 빌드하지 않는다.** 원본 페이지가 이 폴더 **바깥**에 있는데
> 배포에는 이 폴더만 올라가서 빌드가 원본을 못 찾는다(실제로 한 번 실패했다).
> `.vercelignore` 가 있어서 `.gitignore` 대신 그게 쓰이고, 그래서 `public/` 이 올라간다.

## 아직 남은 것

- ⏸️ **배포 보호(Vercel Authentication) 해제** — 켜져 있으면 모르는 사람이 열 때 302 로 막힌다.
  대시보드 → Settings → Deployment Protection → Vercel Authentication → Disable.
  **페이지를 인터넷에 공개하는 동작이라 사람이 해야 한다.**
- 해제한 뒤 **본인이 한 번 끝까지 해 볼 것.** 마이크 권한·업로드·`pull` 까지는 실기에서만 갈린다.
