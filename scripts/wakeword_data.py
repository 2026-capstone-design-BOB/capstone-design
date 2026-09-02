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

## ⚠️ 합성음만으로는 부족하다
edge-tts의 한국어 목소리는 **2개뿐**(SunHi·InJoon)이라 그 둘에 과적합된다.
`--user-audio`로 실제 녹음을 섞어야 한다. 수십 개만 있어도 크게 개선된다.
"""

import asyncio
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SR = 16000

# ── 합성 조건 ──────────────────────────────────────────────────
VOICES = ["ko-KR-SunHiNeural", "ko-KR-InJoonNeural"]
RATES  = ["-20%", "-10%", "+0%", "+10%", "+20%"]
PITCHES = ["-30Hz", "-15Hz", "+0Hz", "+15Hz", "+30Hz"]

# 양성 — 웨이크워드를 부르는 여러 형태
POSITIVE_PHRASES = ["플루이즈", "헤이 플루이즈", "플루이즈야", "야 플루이즈"]

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


async def synthesize_set(phrases, out_dir, tag, limit_combos=None):
    """문구 × 목소리 × 속도 × 높이 조합을 합성해 파일 경로 리스트를 반환."""
    os.makedirs(out_dir, exist_ok=True)
    combos = [(p, v, r, pi)
              for p in phrases for v in VOICES for r in RATES for pi in PITCHES]
    if limit_combos:
        rng = np.random.default_rng(0)
        idx = rng.choice(len(combos), size=min(limit_combos, len(combos)), replace=False)
        combos = [combos[i] for i in idx]

    paths = []
    for i, (p, v, r, pi) in enumerate(combos):
        fn = os.path.join(out_dir, f"{tag}_{i:05d}.mp3")
        if not os.path.exists(fn):
            try:
                await _synthesize(p, v, r, pi, fn)
            except Exception as e:
                print(f"  합성 실패({p!r} {v} {r} {pi}): {e}")
                continue
        paths.append(fn)
        if (i + 1) % 50 == 0:
            print(f"  {tag}: {i+1}/{len(combos)}")
    return paths


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
