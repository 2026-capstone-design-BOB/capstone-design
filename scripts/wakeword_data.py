"""
웨이크워드 학습 데이터 생성
===========================
`scripts/train_wakeword.py`가 쓰는 데이터 생성기. 단독 실행도 된다.

## 왜 이게 필요한가
Whisper 기반 웨이크워드는 "플루이즈"에서 **감지율 69%가 천장**이었다(2026-09-02 실측).
한국어에 없는 조어라 ASR이 실제 단어(플로이드·하이퍼노이즈)로 끌어당기기 때문이다.
→ 문장을 받아적는 대신 **음향에서 키워드만 찾는** 전용 모델로 간다.
   → docs/DEVLOG.md · docs/ROADMAP.md

## 데이터를 어떻게 만드나
- **양성**: `edge-tts`(이미 프로젝트에 있다)로 웨이크워드를 목소리·속도·높이를 바꿔 합성
- **음성(negative)**: 같은 방식으로 **웨이크워드가 아닌 한국어**를 합성.
  특히 **헷갈리는 말**(플로이드·블루투스·루이비통·플레이리스트)을 많이 넣는다 —
  이게 없으면 모델이 "플" 소리만 나면 반응한다.
- **증강**: 잡음·게인·시간이동·속도로 부풀린다. 실제 방에서 녹음된 소리에 가깝게.

## 화자 수가 지렛대다 — «실제 녹음»이 아니라 (2026-09-08 실측)
목소리를 하나만 쓰면 **처음 듣는 목소리를 30.5%밖에 못 잡는다.** 그래서 원래는
`--user-audio`로 실제 녹음을 섞어야 한다고 적혀 있었는데, 측정해 보니 병목은
«합성이라서»가 아니라 **«목소리가 2개라서»** 였다.

| 학습 화자 수 | 처음 듣는 목소리 감지율 (임계 0.8) |
|---|---|
| 1개 | 30.5% |
| 2개 | 83.0% |
| **11개** | **98.1%** |

그래서 `VOICES`를 15개로 늘렸다. edge-tts의 한국어 목소리는 3개뿐이지만
**Multilingual 목소리 12개가 한국어를 발음한다**(실측 확인).
`--user-audio`는 그대로 남아 있고 있으면 여전히 도움이 된다 — 다만 **필수가 아니다.**
→ docs/design/M2_웨이크워드_전용모델.md §4
"""

import asyncio
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SR = 16000

# ── 합성 조건 ──────────────────────────────────────────────────
# ⚠️ **양성과 음성을 반드시 같은 목소리 집합으로 합성한다.**
#   양성만 다목소리이고 음성이 2목소리면, 분류기는 단어가 아니라 **목소리 정체성**을
#   학습한다("다국어 목소리면 양성"). 그러면 평가 숫자가 통째로 가짜가 된다.
#   `synthesize_set`이 둘 다 이 목록을 쓰므로 여기만 고치면 된다.
VOICES = [
    # 한국어 (edge-tts가 주는 전부 — 2026-09-08 기준 3개)
    "ko-KR-SunHiNeural", "ko-KR-InJoonNeural", "ko-KR-HyunsuMultilingualNeural",
    # 다국어 목소리 — 한국어를 발음한다. 화자 다양성을 이걸로 번다.
    "en-AU-WilliamMultilingualNeural", "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural", "en-US-BrianMultilingualNeural",
    "en-US-EmmaMultilingualNeural", "fr-FR-VivienneMultilingualNeural",
    "fr-FR-RemyMultilingualNeural", "de-DE-SeraphinaMultilingualNeural",
    "de-DE-FlorianMultilingualNeural", "it-IT-GiuseppeMultilingualNeural",
    "pt-BR-ThalitaMultilingualNeural",
]
RATES  = ["-20%", "-10%", "+0%", "+10%", "+20%"]
PITCHES = ["-30Hz", "-15Hz", "+0Hz", "+15Hz", "+30Hz"]

# 양성 — 웨이크워드를 부르는 여러 형태
POSITIVE_PHRASES = ["플루이즈", "헤이 플루이즈", "플루이즈야", "야 플루이즈"]

# 이 모델이 **커버하는 사용자 표기**. 학습 결과(npz)에 같이 저장해서, 런타임이
# "설정된 호출어를 이 모델이 감당할 수 있나"를 판단하는 데 쓴다.
#
# ⚠️ `pluiz`가 왜 여기 있나 — **같은 소리의 다른 철자**다. Whisper 경로에서는 받아적은
#   텍스트가 로마자로 나올 수 있어 필요했지만, KWS 모델은 음향을 보므로 철자가 무의미하다.
#   이걸 빼면 «기본 설정인데도 모델을 안 쓰는» 일이 생긴다(2026-09-08에 실제로 겪었다).
#   `services/wakeword.py`의 `DEFAULT_WAKE_WORDS`와 맞춰 둔다.
COVERED_WAKE_WORDS = ["플루이즈", "pluiz"] + POSITIVE_PHRASES

# 음성 — 절대 깨어나면 안 되는 말.
# **발음이 비슷한 것**을 앞쪽에 많이 둔다. 이게 모델의 정밀도를 만든다.
NEGATIVE_PHRASES = [
    # 헷갈리는 말 (Whisper가 실제로 오인식했던 것들)
    "플로이드", "핑크 플로이드", "하이퍼노이즈", "블루투스 켜줘", "루이비통 검색해줘",
    "플레이리스트 틀어줘", "플러그인 설치해줘", "프로그램 종료해", "클라우드 확인해",
    "블로그 열어줘", "풀스크린으로 바꿔", "플래시 꺼줘", "프린터 연결해",
    # 실제 명령 (평소에 하는 말)
    "메모장 열어줘", "계산기 켜줘", "크롬 열어줘", "볼륨 올려줘", "소리 좀 키워봐",
    "화면 캡처해줘", "오늘 날씨 어때", "지금 몇 시야", "유튜브 틀어줘",
    "파일 좀 찾아줘", "그거 꺼줘", "바탕화면 보여줘", "밝기 낮춰줘",
    "배터리 얼마나 남았어", "실행 중인 앱 알려줘", "폴더 만들어줘",
    # 일상 대화
    "안녕 반가워", "밥 먹었어?", "이거 어떻게 하는 거야", "잠깐만 기다려봐",
    "그래서 어떻게 됐어", "나 지금 바빠", "조금 이따가 하자", "재밌겠다",
]


async def _synthesize(text, voice, rate, pitch, out_path):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(out_path)


def _load(path):
    """mp3 → 16kHz float32 numpy (faster-whisper의 디코더 재사용)."""
    from faster_whisper.audio import decode_audio
    return decode_audio(path, sampling_rate=SR)


async def synthesize_set(phrases, out_dir, tag, limit_combos=None, concurrency=8):
    """문구 × 목소리 × 속도 × 높이 조합을 합성해 파일 경로 리스트를 반환.

    ⚠️ **파일명에 조합 자체를 적는다** (`pos_p00_v03_r2_h4.mp3`).
      예전에는 일련번호(`pos_00017.mp3`)였는데, 그러면 `VOICES`를 늘리는 순간
      **같은 번호가 다른 조합을 가리키게 되고** 캐시가 조용히 재사용된다.
      «어떤 목소리로 학습했는지»가 어긋나는데 **아무 오류도 안 난다** —
      목소리를 2 → 15개로 늘리던 2026-09-08에 드러난 함정이다.
      이름이 조합을 담고 있으면 조합이 바뀔 때 파일도 저절로 갈린다.

    합성은 네트워크 왕복이라 **동시에 보낸다**(기본 8). 목소리가 늘면서 조합이
    수백 개가 됐는데 하나씩 기다리면 학습 한 번에 수십 분이 날아간다.
    """
    os.makedirs(out_dir, exist_ok=True)
    combos = [(pi_, p, vi, v, ri, r, hi, h)
              for pi_, p in enumerate(phrases)
              for vi, v in enumerate(VOICES)
              for ri, r in enumerate(RATES)
              for hi, h in enumerate(PITCHES)]
    if limit_combos and limit_combos < len(combos):
        rng = np.random.default_rng(0)
        idx = sorted(rng.choice(len(combos), size=limit_combos, replace=False))
        combos = [combos[i] for i in idx]

    paths = [os.path.join(out_dir, f"{tag}_p{c[0]:02d}_v{c[2]:02d}_r{c[4]}_h{c[6]}.mp3")
             for c in combos]
    todo = [(c, fp) for c, fp in zip(combos, paths) if not os.path.exists(fp)]
    print(f"  {tag}: 조합 {len(combos)}개 · 새로 합성 {len(todo)}개")

    if todo:
        sem = asyncio.Semaphore(concurrency)
        done = [0]

        async def one(c, fp):
            async with sem:
                for attempt in range(3):        # 네트워크는 가끔 튄다 — 조용히 재시도
                    try:
                        await _synthesize(c[1], c[3], c[5], c[7], fp)
                        break
                    except Exception as e:
                        if attempt == 2:
                            print(f"  합성 실패({c[1]!r} {c[3]}): {e}")
                        else:
                            await asyncio.sleep(1.0)
                done[0] += 1
                if done[0] % 100 == 0:
                    print(f"    {tag}: {done[0]}/{len(todo)}")

        await asyncio.gather(*(one(c, fp) for c, fp in todo))

    return [fp for fp in paths if os.path.exists(fp)]


# ── 증강 ───────────────────────────────────────────────────────
def augment(audio, rng, n=8):
    """클립 하나 → 여러 변형. 실제 방/마이크 조건을 흉내낸다.

    실측에서 사용자 마이크의 최대 진폭이 0.126으로 **작았다.** 그래서 게인 축소를
    넉넉히 넣는다 — 작게 녹음되는 환경에서도 반응해야 한다.
    """
    out = []
    for _ in range(n):
        a = audio.copy()

        # 속도 (길이 변화) — 말 빠르기 차이
        speed = rng.uniform(0.9, 1.12)
        if abs(speed - 1.0) > 0.01:
            idx = np.arange(0, len(a), speed)
            a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)

        # 게인 — 마이크 입력 레벨 차이 (작게 녹음되는 경우 포함)
        a = a * rng.uniform(0.15, 1.4)

        # 잡음 — 방 소음
        snr_scale = rng.uniform(0.0005, 0.02)
        a = a + rng.normal(0, snr_scale, len(a)).astype(np.float32)

        # 간단한 잔향 (한 번 반사)
        if rng.random() < 0.4:
            delay = int(SR * rng.uniform(0.02, 0.08))
            echo = np.zeros_like(a)
            echo[delay:] = a[:-delay] * rng.uniform(0.1, 0.35)
            a = a + echo

        out.append(np.clip(a, -1.0, 1.0).astype(np.float32))
    return out


def to_window(audio, rng, win_sec=2.0):
    """오디오를 고정 길이 창에 무작위 위치로 배치한다.

    실서비스는 슬라이딩 윈도우라 웨이크워드가 창의 **어디에나** 올 수 있다.
    항상 가운데에 두고 학습하면 실전에서 놓친다.
    """
    n = int(SR * win_sec)
    w = np.zeros(n, dtype=np.float32)
    if len(audio) >= n:
        start = rng.integers(0, len(audio) - n + 1) if len(audio) > n else 0
        w[:] = audio[start:start + n]
    else:
        off = rng.integers(0, n - len(audio) + 1)
        w[off:off + len(audio)] = audio
    return w
