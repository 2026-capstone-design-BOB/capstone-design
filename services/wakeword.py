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
from itertools import combinations, product

# Windows 콘솔 인코딩 고정 (cp949에서 한글 깨짐/예외 방지)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 로그 파일 ──────────────────────────────────────────────────
# Windows 콘솔(cp949)에서는 Whisper가 들은 한국어가 깨져 보여서 **진단이 불가능하다.**
# ("heard: '??'" 처럼 나온다) 그래서 콘솔과 별개로 UTF-8 파일에도 남긴다.
# → logs/pluiz.log  (core/logger.py 재사용)
try:
    from core.logger import get_logger
    log = get_logger("wakeword")
except Exception:                      # 로깅이 없다고 웨이크워드가 죽으면 안 된다
    class _NullLog:
        def __getattr__(self, _): return lambda *a, **k: None
    log = _NullLog()


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

# ── 오디오 설정 ────────────────────────────────────────────────
SAMPLE_RATE     = 16000

# ⚠️ 예전에는 **1초 청크를 오버랩 없이** 잘라 넘겼다. 그런데 "헤이 플루이즈"는
#    1.2~1.5초라 창 경계에서 잘리기 일쑤였다. 2026-09-02 실측 로그에 그 증거가 남아 있다:
#      heard=', 풀로.'      ← "플루"만 들어간 조각
#      heard='뭐, 이제야.'   ← 뒤쪽 조각
#    온전한 발화가 한 창에 들어갈 확률 자체가 낮았다. → **슬라이딩 윈도우**로 바꿨다.
WINDOW_SECONDS  = 2.0           # 한 번에 인식할 구간 (발화 전체가 들어갈 만큼)
WINDOW_SAMPLES  = int(SAMPLE_RATE * WINDOW_SECONDS)
HOP_SECONDS     = 0.6           # 이만큼마다 다시 인식 → 창이 겹쳐서 경계 문제가 사라진다
HOP_SAMPLES     = int(SAMPLE_RATE * HOP_SECONDS)

COOLDOWN_SEC    = 2.5           # 연속 감지 방지 딜레이

# ── 웨이크워드 ─────────────────────────────────────────────────
_RELOAD_SEC = 10.0        # 설정 재확인 주기 — 재시작 없이 변경 반영

# 사용자가 아무것도 설정하지 않았을 때의 기본값.
# "헤이 플루이즈"처럼 앞에 호출어를 붙여 불러도 걸리도록 부분매칭을 쓴다.
DEFAULT_WAKE_WORDS = ["플루이즈", "pluiz"]

# Whisper tiny가 고유명사를 흘려 들을 때 나오는 흔한 변형.
# 사용자가 단어 하나만 적어도 이 규칙으로 자동 확장한다.
# (오탐이 늘면 여기를 줄이는 게 첫 번째 조치다)
# 2026-09-02 실측: edge-tts로 "플루이즈"를 24개(2목소리×3속도×4문형) 합성해
# Whisper에 넣어 실제 출력을 수집했다. 압도적으로 많았던 것 →  플로이즈 · 플로이드 · 플로이지
# 그래서 루→로, 즈→드 를 추가했다. (추측이 아니라 관측값이다)
_CONFUSIONS = {
    "플": ["플", "픟", "블", "프", "풀"],
    "루": ["루", "로", "르", "라"],
    "이": ["이", "위", "의"],
    "즈": ["즈", "드", "스", "지", "주", "즘"],
}


_MAX_DISTANCE = 2      # 동시에 몇 글자까지 바뀐 변형을 만들 것인가
_MAX_VARIANTS = 300    # 안전장치 — 사용자가 긴 단어를 넣으면 조합이 폭발한다


def _expand(word: str) -> set:
    """웨이크워드 하나 → 흔한 오인식 변형 집합.

    **거리 2까지 만든다.** 2026-09-02 실측으로 정한 값이다 —
    edge-tts로 합성한 "플루이즈" 24건을 Whisper에 넣어 나온 출력에 대해:

    | 거리 | 변형 수 | 감지율 | 오탐 |
    |---|---|---|---|
    | 1 | 15 | 38% | 0/20 |
    | **2** | **86** | **69%** | **0/20** |
    | 3 | 240 | 69% | 0/20 |

    거리 3은 이득 없이 변형만 3배가 된다. 거리 1은 `플로이드`(두 글자가 바뀐 형태)를
    놓친다 — 그게 Whisper가 가장 자주 뱉는 형태 중 하나다.

    ⚠️ 변형이 `_MAX_VARIANTS`를 넘으면 거리 1로 낮춘다. 사용자가 긴 웨이크워드를
    지정했을 때 조합이 폭발해 오탐이 늘어나는 걸 막는다.
    """
    w = word.strip()
    if not w:
        return set()

    chars = list(w)
    positions = [i for i, ch in enumerate(chars)
                 if [a for a in _CONFUSIONS.get(ch, []) if a != ch]]

    def build(max_dist):
        out = {w}
        for d in range(1, max_dist + 1):
            for pos in combinations(positions, d):
                opts = [[a for a in _CONFUSIONS[chars[i]] if a != chars[i]] for i in pos]
                for combo in product(*opts):
                    v = chars.copy()
                    for i, c in zip(pos, combo):
                        v[i] = c
                    out.add("".join(v))
        return out

    result = build(_MAX_DISTANCE)
    if len(result) > _MAX_VARIANTS:
        result = build(1)
    return result


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

# hotwords 사용 여부 (기본 꺼짐 — 위 _transcribe 주석 참조)
USE_HOTWORDS = os.getenv("WAKEWORD_HOTWORDS", "false").strip().lower() in ("1", "true", "yes")

# 쉼표만 있거나 너무 짧은 결과 무시
NOISE_PATTERNS = re.compile(r'^[,.\s\-_]+$')


# ── 환각 걸러내기 ──────────────────────────────────────────────
# Whisper는 짧고 조용한 구간에서 **반복 환각**을 뱉는다. 2026-09-02 실측 예:
#   ',Z.3 스트레이트 dre,Z.5.4, Z.3.4,Z.3.5.5.6,Z.3,Z.4.6,Z,9,Z,3,Z,Z,4,Z,col…'
#   '그냥 블루이즈,erm Frue, amateur,Os,no,만, toda…뜩,뜩,뜩,뜩…'
# 이건 설정 문제가 아니라 Whisper의 알려진 실패 모드다.
#
# ⚠️ 이걸 안 거르면 **오탐이 난다.** 수백 자짜리 난수 텍스트 안에 웨이크워드 변형
#    하나가 우연히 섞이면 그대로 깨어나기 때문이다. 실제로 그렇게 깨어났다.
_MAX_CHARS = 60          # 2초 발화로 60자를 넘길 수 없다
_MIN_LEN_FOR_REPEAT = 12  # 짧은 텍스트에 반복률을 적용하면 정상 발화까지 걸린다


def looks_hallucinated(text: str) -> bool:
    """Whisper 환각으로 보이면 True. 그러면 매칭 대상에서 제외한다."""
    t = (text or "").strip()
    if not t:
        return True
    if len(t) > _MAX_CHARS:
        return True
    if len(t) >= _MIN_LEN_FOR_REPEAT:
        # 같은 문자가 지나치게 반복되면(",,,,,," · "뜩뜩뜩") 환각이다
        most = max(t.count(c) for c in set(t))
        if most / len(t) > 0.35:
            return True
    return False


def normalize(text: str) -> str:
    return text.lower().strip().replace(' ', '')


def is_wake(text: str) -> bool:
    if not text or NOISE_PATTERNS.match(text):
        return False
    if not WAKE_WORDS:          # 사용자가 웨이크워드를 껐다
        return False
    if looks_hallucinated(text):
        return False            # 환각 안에서 우연히 걸리는 오탐 차단
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


def _tune():
    """마이크·환경에 따라 달라지는 값을 설정에서 읽는다. 실패해도 기본값으로 돈다."""
    model_size, energy = "base", 0.008
    try:
        from config.settings import get_settings
        get_settings.cache_clear()
        st = get_settings()
        model_size = st.wakeword_model or model_size
        energy = float(st.wakeword_energy)
    except Exception as e:
        print(f"[wakeword] 튜닝 설정 로드 실패 → 기본값: {e}", file=sys.stderr, flush=True)
    return model_size, energy


def main():
    model_size, energy_threshold = _tune()
    print(f"[wakeword] Loading model ({model_size})...", file=sys.stderr, flush=True)

    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    # 설정 변경을 재시작 없이 반영
    threading.Thread(target=_reload_loop, daemon=True).start()

    if not WAKE_WORDS:
        print("[wakeword] ⚠️ 웨이크워드가 꺼져 있습니다 (WAKE_WORD_ENABLED=false). "
              "설정을 켜면 재시작 없이 반영됩니다.", file=sys.stderr, flush=True)
    else:
        shown = ", ".join(WAKE_WORDS[:8]) + (" …" if len(WAKE_WORDS) > 8 else "")
        print(f"[wakeword] 감지 대상 {len(WAKE_WORDS)}개: {shown}",
              file=sys.stderr, flush=True)
        log.info("감지 대상 %d개: %s", len(WAKE_WORDS), ", ".join(WAKE_WORDS))

    log.info("설정: model=%s energy=%.4f window=%.1fs hop=%.1fs",
             model_size, energy_threshold, WINDOW_SECONDS, HOP_SECONDS)
    print("[wakeword] 준비 완료. 감지 중...", file=sys.stderr, flush=True)

    last_wake = 0.0
    window = np.zeros(WINDOW_SAMPLES, dtype=np.float32)   # 최근 WINDOW_SECONDS 초
    since_hop = 0
    quiet_log_at = 0.0
    busy = threading.Lock()        # 인식은 한 번에 하나만 (창이 겹치므로 쌓이면 밀린다)

    def _transcribe(chunk, ts):
        """창 하나를 인식해 웨이크워드가 있는지 본다."""
        nonlocal last_wake
        try:
            segments, _ = model.transcribe(
                chunk,
                language="ko",
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 200},
                condition_on_previous_text=False,
                # 고유명사 편향(hotwords): 켜면 "플루이즈" 쪽으로 디코딩이 기운다.
                # ⚠️ 그런데 모델이 힌트를 **그대로 뱉는** 부작용이 있다 — 2026-09-02 실측에서
                #    hotwords를 켠 뒤 환각이 급증했다. 기본값은 끔.
                #    WAKEWORD_HOTWORDS=true 로 켤 수 있다.
                hotwords=(" ".join(WAKE_WORDS[:8]) if (WAKE_WORDS and USE_HOTWORDS) else None),
            )
            text = " ".join(seg.text for seg in segments).strip()

            if not text or NOISE_PATTERNS.match(text):
                return

            print(f"[wakeword] heard: {text!r}", file=sys.stderr, flush=True)

            # 콘솔(cp949)이 깨져도 여기엔 정확히 남는다 — 매칭 실패 원인을 이걸로 판단한다
            matched = is_wake(text)
            if looks_hallucinated(text):
                log.info("heard=%r match=False (환각으로 판단, %d자)", text[:80], len(text))
            else:
                log.info("heard=%r match=%s", text, matched)

            if matched:
                last_wake = ts
                print("WAKE", flush=True)
                print("[wakeword] *** WAKE WORD DETECTED ***", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[wakeword] transcribe error: {e}", file=sys.stderr, flush=True)
            log.exception("transcribe 실패")
        finally:
            if busy.locked():
                busy.release()

    def on_audio(indata, frames, time_info, status):
        nonlocal since_hop, quiet_log_at

        audio = (indata[:, 0] if indata.ndim > 1 else indata.flatten()).astype(np.float32)
        n = len(audio)
        if n == 0:
            return

        # ── 슬라이딩 윈도우: 오래된 샘플을 밀어내고 뒤에 붙인다 ──────────
        if n >= WINDOW_SAMPLES:
            window[:] = audio[-WINDOW_SAMPLES:]
        else:
            window[:-n] = window[n:]
            window[-n:] = audio

        since_hop += n
        if since_hop < HOP_SAMPLES:
            return                      # 아직 다음 인식 시점이 아니다
        since_hop = 0

        e = rms(window)
        if e < energy_threshold:
            # 말했는데 아무 반응이 없다면 여기서 걸리는 것이다 (임계값이 높으면).
            # 로그 폭주를 막으려고 5초에 한 번만 남긴다.
            now_q = time.time()
            if now_q - quiet_log_at > 5.0:
                quiet_log_at = now_q
                log.debug("무음 스킵 energy=%.4f (임계 %.4f)", e, energy_threshold)
            return

        now = time.time()
        if now - last_wake < COOLDOWN_SEC:
            return                      # 방금 깨웠다

        # 앞선 인식이 아직 안 끝났으면 이번 창은 건너뛴다 (밀림 방지).
        # 창이 겹치므로 하나 건너뛰어도 다음 창에 같은 발화가 들어 있다.
        if not busy.acquire(blocking=False):
            return

        threading.Thread(
            target=_transcribe, args=(window.copy(), now), daemon=True,
        ).start()

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
        log.exception("마이크 스트림 오류")
        sys.exit(1)


if __name__ == "__main__":
    main()
