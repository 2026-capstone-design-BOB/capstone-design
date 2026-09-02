"""
웨이크워드 서비스 — "플루이즈"
==============================
마이크를 계속 듣다가 웨이크워드가 들리면 stdout에 `WAKE`를 찍는다.
Electron(`electron-ui/main.js`)이 그걸 읽고 창을 띄운다.

## 사용자가 웨이크워드를 바꿀 수 있다
`.env`의 `WAKE_WORDS`(쉼표 구분) 또는 UI 설정에서 지정한다. 비워두면 아래 기본값을 쓴다.

    WAKE_WORDS=플루이즈,헤이 플루이즈

**재시작 없이 반영된다** — `_RELOAD_SEC`마다 설정을 다시 읽는다.
(이 스크립트는 Electron이 별도 프로세스로 띄우므로 서버 재시작과 무관하다.)

## 인식률을 위해 변형을 자동 생성한다
Whisper tiny는 "플루이즈" 같은 고유명사를 자주 흘려 듣는다("플루이스", "블루이즈"…).
그래서 사용자가 단어 하나만 적어도 `_expand()`가 흔한 오인식 변형을 만들어 붙인다.
사용자가 직접 적은 변형이 있으면 그것도 함께 쓴다.

## ⚠️ 이 스크립트는 의존성이 없으면 아무 일도 못 한다
`sounddevice` · `faster-whisper`가 필요하다. **Electron이 어떤 python으로 띄우는지가
중요하다** — `python`(anaconda base)에는 이것들이 없어서, 2026-09-02 이전까지
이 서비스는 뜨자마자 죽고 5초마다 재시도되기만 했다. (아무도 몰랐다)
→ `electron-ui/main.js`의 인터프리터 탐색 로직 참조.
"""

import sys
import os
import io
import threading
import time
import re

# Windows 콘솔 인코딩 고정 (cp949에서 한글 깨짐/예외 방지)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _die(msg: str, hint: str = "") -> None:
    """의존성 문제로 시작할 수 없을 때, **무엇이 없는지 분명히 말하고** 죽는다.

    예전엔 "sounddevice not installed" 한 줄만 stdout에 찍고 exit(1) 했다.
    Electron은 그 메시지를 로그에만 남기고 5초 뒤 재시도했기 때문에,
    **아무 일도 안 일어나는데 아무도 이유를 몰랐다.**
    """
    print(f"[wakeword] FATAL: {msg}", file=sys.stderr, flush=True)
    if hint:
        print(f"[wakeword] HINT: {hint}", file=sys.stderr, flush=True)
    print(f"[wakeword] python={sys.executable}", file=sys.stderr, flush=True)
    # Electron이 UI에 띄울 수 있도록 stdout으로도 한 줄 (WAKE와 구분되는 접두사)
    print(f"WAKEWORD_ERROR {msg}", flush=True)
    sys.exit(1)


try:
    import sounddevice as sd
    import numpy as np
except ImportError as e:
    _die(f"sounddevice/numpy 없음 ({e})",
         "pip install sounddevice numpy  ※ Pluiz 서버와 같은 python 환경에 설치할 것")

try:
    from faster_whisper import WhisperModel
except ImportError as e:
    _die(f"faster-whisper 없음 ({e})",
         "pip install faster-whisper  ※ Pluiz 서버와 같은 python 환경에 설치할 것")

# ── Config ─────────────────────────────────────────────────────
SAMPLE_RATE     = 16000
CHUNK_SECONDS   = 1.0           # 1초 청크
CHUNK_SAMPLES   = int(SAMPLE_RATE * CHUNK_SECONDS)
ENERGY_THRESHOLD = 0.015        # 무음 스킵 임계값 (높일수록 조용한 환경에서만 반응)
COOLDOWN_SEC    = 2.5           # 연속 감지 방지 딜레이

# ── 웨이크워드 ─────────────────────────────────────────────────
_RELOAD_SEC = 10.0        # 설정 재확인 주기 — 재시작 없이 변경 반영

# 사용자가 아무것도 설정하지 않았을 때의 기본값.
# "헤이 플루이즈"처럼 앞에 호출어를 붙여 불러도 걸리도록 부분매칭을 쓴다.
DEFAULT_WAKE_WORDS = ["플루이즈", "pluiz"]

# Whisper tiny가 고유명사를 흘려 들을 때 나오는 흔한 변형.
# 사용자가 단어 하나만 적어도 이 규칙으로 자동 확장한다.
# (오탐이 늘면 여기를 줄이는 게 첫 번째 조치다)
_CONFUSIONS = {
    "플": ["플", "픟", "블", "프", "풀"],
    "루": ["루", "르", "라"],
    "이": ["이", "위", "의"],
    "즈": ["즈", "스", "지", "주", "즘"],
}


def _expand(word: str) -> set:
    """웨이크워드 하나 → 흔한 오인식 변형 집합.

    글자 단위로 치환 후보를 조합한다. 조합 폭발을 막기 위해 **한 번에 한 글자만**
    바꾼 변형까지만 만든다 (거리 1). 전수 조합은 오탐을 급격히 늘린다.
    """
    w = word.strip()
    if not w:
        return set()

    out = {w}
    chars = list(w)
    for i, ch in enumerate(chars):
        for alt in _CONFUSIONS.get(ch, []):
            if alt == ch:
                continue
            variant = chars.copy()
            variant[i] = alt
            out.add("".join(variant))
    return out


def _load_wake_words() -> list:
    """설정에서 웨이크워드를 읽는다. 실패하면 기본값.

    설정 로딩이 깨져도 웨이크워드는 계속 동작해야 한다 — 그래서 예외를 삼킨다.
    """
    words = []
    try:
        from config.settings import get_settings
        get_settings.cache_clear()          # .env 변경을 반영 (@lru_cache)
        s = get_settings()
        if not s.wake_word_enabled:
            return []                        # 빈 리스트 = 감지 중지
        words = s.wake_word_list
    except Exception as e:
        print(f"[wakeword] 설정 로드 실패 → 기본값 사용: {e}", file=sys.stderr, flush=True)

    if not words:
        words = list(DEFAULT_WAKE_WORDS)

    expanded = set()
    for w in words:
        expanded |= _expand(w)
    return sorted(expanded)


WAKE_WORDS = _load_wake_words()

# 쉼표만 있거나 너무 짧은 결과 무시
NOISE_PATTERNS = re.compile(r'^[,.\s\-_]+$')


def normalize(text: str) -> str:
    return text.lower().strip().replace(' ', '')


def is_wake(text: str) -> bool:
    if not text or NOISE_PATTERNS.match(text):
        return False
    if not WAKE_WORDS:          # 사용자가 웨이크워드를 껐다
        return False
    norm = normalize(text)
    for w in WAKE_WORDS:
        if normalize(w) in norm:
            return True
    return False


def _reload_loop():
    """주기적으로 설정을 다시 읽어 WAKE_WORDS를 갱신한다 (재시작 불필요)."""
    global WAKE_WORDS
    while True:
        time.sleep(_RELOAD_SEC)
        try:
            new = _load_wake_words()
            if new != WAKE_WORDS:
                WAKE_WORDS = new
                shown = ", ".join(new[:6]) + (" …" if len(new) > 6 else "")
                print(f"[wakeword] 웨이크워드 갱신: {shown or '(꺼짐)'}",
                      file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[wakeword] 설정 재로드 실패(무시): {e}", file=sys.stderr, flush=True)


def rms(audio: "np.ndarray") -> float:
    return float(np.sqrt(np.mean(audio ** 2)))


def main():
    print("[wakeword] Loading model...", file=sys.stderr, flush=True)

    model = WhisperModel("tiny", device="cpu", compute_type="int8")

    # 설정 변경을 재시작 없이 반영
    threading.Thread(target=_reload_loop, daemon=True).start()

    if not WAKE_WORDS:
        print("[wakeword] ⚠️ 웨이크워드가 꺼져 있습니다 (WAKE_WORD_ENABLED=false). "
              "설정을 켜면 재시작 없이 반영됩니다.", file=sys.stderr, flush=True)
    else:
        shown = ", ".join(WAKE_WORDS[:8]) + (" …" if len(WAKE_WORDS) > 8 else "")
        print(f"[wakeword] 감지 대상 {len(WAKE_WORDS)}개: {shown}",
              file=sys.stderr, flush=True)

    print("[wakeword] 준비 완료. 감지 중...", file=sys.stderr, flush=True)

    last_wake = 0.0
    buf = np.zeros(CHUNK_SAMPLES, dtype=np.float32)
    buf_pos = 0

    def on_audio(indata, frames, time_info, status):
        nonlocal buf_pos, last_wake

        audio = indata[:, 0].astype(np.float32) if indata.ndim > 1 else indata.flatten().astype(np.float32)
        space = CHUNK_SAMPLES - buf_pos

        if len(audio) >= space:
            buf[buf_pos:] = audio[:space]
            chunk = buf.copy()
            # BUG-12: 버퍼를 채우고 남은 잔여 샘플을 다음 버퍼 시작으로 이월
            remainder = audio[space:]
            buf_pos = 0
            if len(remainder) > 0:
                buf[:len(remainder)] = remainder
                buf_pos = len(remainder)

            energy = rms(chunk)
            if energy < ENERGY_THRESHOLD:
                return  # 무음 스킵

            now = time.time()
            if now - last_wake < COOLDOWN_SEC:
                return  # 쿨다운 중

            threading.Thread(
                target=_transcribe,
                args=(model, chunk.copy(), now),
                daemon=True,
            ).start()
        else:
            buf[buf_pos:buf_pos + len(audio)] = audio
            buf_pos += len(audio)

    def _transcribe(model, chunk, ts):
        nonlocal last_wake
        try:
            segments, _ = model.transcribe(
                chunk,
                language="ko",
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 200},
                condition_on_previous_text=False,
            )
            text = " ".join(s.text for s in segments).strip()

            if not text or NOISE_PATTERNS.match(text):
                return

            print(f"[wakeword] heard: {text!r}", file=sys.stderr, flush=True)

            if is_wake(text):
                last_wake = ts
                print("WAKE", flush=True)
                print("[wakeword] *** WAKE WORD DETECTED ***", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[wakeword] transcribe error: {e}", file=sys.stderr, flush=True)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=512,
            callback=on_audio,
        ):
            print("[wakeword] Microphone stream started.", file=sys.stderr, flush=True)
            while True:
                time.sleep(0.1)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[wakeword] Stream error: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
