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


def _configured_raw_wake_words() -> list:
    """사용자가 **적은 그대로**의 호출어. (`_expand` 변형을 붙이기 전)

    KWS 모델이 어떤 말로 학습됐는지와 대조하는 데 쓴다. 확장된 목록으로 대조하면
    오인식 변형(`플로이드` 등)까지 섞여 들어와 판단이 어긋난다.
    """
    try:
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        if not s.wake_word_enabled:
            return []
        return list(s.wake_word_list) or list(DEFAULT_WAKE_WORDS)
    except Exception:
        return list(DEFAULT_WAKE_WORDS)


def model_covers(configured: list, phrases) -> bool:
    """설정된 호출어를 이 모델이 감당할 수 있나. (순수 함수 — 테스트 가능)

    전용 KWS 모델은 **학습된 말 하나만** 안다. BL-13에서 사용자가 호출어를 바꿀 수
    있게 해 놨으므로, 감당 못 하는 말이 설정돼 있으면 **모델을 쓰면 안 된다** —
    쓰면 바꾼 호출어가 조용히 무시되고, 설정 화면에서 저장까지 한 사용자는
    아무 반응이 없는 이유를 알 수 없다. 그럴 땐 임의의 단어를 다루는 Whisper로 간다.

    빈 설정(감지 끔)은 여기서 판단하지 않는다 — 부르는 쪽이 이미 걸러낸다.
    """
    if not configured:
        return True
    return set(configured) <= set(phrases)


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


# ── 전용 KWS 모델 백엔드 (2026-09-08) ─────────────────────────────
# Whisper는 **문장을 받아적는** 모델이라 "플루이즈" 같은 조어에서 감지율 69%가
# 천장이었다(ADR §2). 여기서는 **음향에서 키워드만 찾는다** — openWakeWord의
# 사전학습 임베딩 위에 우리가 학습시킨 작은 MLP 하나다.
#
# ⚠️ **sklearn을 런타임 의존성으로 만들지 않는다.** 학습은 sklearn으로 하고
#   추론은 여기서 numpy 행렬곱으로 직접 한다(`relu(x@W+b)` 반복 + 시그모이드).
#   npz에는 가중치만 들어 있다. → scripts/train_wakeword.py의 `save()`
#
# 되돌리기: 모델 파일이 없거나 로드가 실패하면 **Whisper 경로로 자동 복귀**한다.
# `.env`에 `WAKEWORD_BACKEND=whisper`로 강제할 수도 있다. (ADR §6)
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wakeword_model.npz")


class KwsModel:
    """임베딩 → MLP → 확률. 창 하나를 받아 «웨이크워드인가»를 0~1로 답한다."""

    def __init__(self, path: str):
        z = np.load(path, allow_pickle=False)
        n = int(z["n_layers"])
        self.W = [z[f"W{i}"] for i in range(n)]
        self.b = [z[f"b{i}"] for i in range(n)]
        self.win_sec = float(z["win_sec"])
        self.sample_rate = int(z["sample_rate"])
        self.wake_word = str(z["wake_word"])       # 이 모델이 아는 말 — 딱 하나다
        # 이 모델이 커버하는 «사용자 표기» 목록. 옛 모델 파일에는 없을 수 있어 폴백을 둔다.
        try:
            self.wake_phrases = {str(x) for x in z["wake_phrases"]}
        except KeyError:
            self.wake_phrases = {self.wake_word}
        # 임베딩 추출기는 학습 때와 **같은 것**이어야 한다 (openWakeWord 사전학습 ONNX)
        from openwakeword.utils import AudioFeatures
        self._af = AudioFeatures()

    def probability(self, audio: "np.ndarray") -> float:
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        x = self._af._get_embeddings(pcm).flatten()[None, :].astype(np.float32)
        for W, b in zip(self.W[:-1], self.b[:-1]):
            x = np.maximum(0.0, x @ W + b)              # relu
        z = float((x @ self.W[-1] + self.b[-1]).ravel()[0])
        return 1.0 / (1.0 + np.exp(-z))                 # 시그모이드


def load_kws_model():
    """모델 백엔드를 준비한다. **실패는 예외가 아니라 None이다** — Whisper로 돌아간다.

    웨이크워드가 안 뜨는 것보다 나쁜 건 **웨이크워드 프로세스가 죽는 것**이다.
    그러면 Electron이 창을 못 띄우고 사용자는 이유를 알 수 없다.
    """
    backend = "auto"
    try:
        from config.settings import get_settings
        get_settings.cache_clear()
        backend = (get_settings().wakeword_backend or "auto").lower()
    except Exception:
        pass
    if backend == "whisper":
        print("[wakeword] backend=whisper (설정으로 강제)", file=sys.stderr, flush=True)
        return None
    if not os.path.exists(MODEL_PATH):
        if backend == "model":
            print(f"[wakeword] ⚠️ backend=model인데 {MODEL_PATH} 가 없다 → Whisper로 진행",
                  file=sys.stderr, flush=True)
        return None
    try:
        m = KwsModel(MODEL_PATH)

        # ⚠️ **모델은 학습된 말 하나만 안다.** BL-13에서 사용자가 호출어를 바꿀 수 있게
        #   해 놨으므로, 설정이 «플루이즈»가 아닌데 모델을 쓰면 **바꾼 호출어가 조용히
        #   무시된다** — 설정 화면에서 저장까지 했는데 아무 반응이 없는 최악의 모양이다.
        #   그런 경우엔 임의의 단어를 다루는 Whisper 경로로 간다.
        configured = _configured_raw_wake_words()
        if not model_covers(configured, m.wake_phrases):
            print(f"[wakeword] 호출어가 학습된 말({m.wake_word})과 다릅니다 "
                  f"{configured} → Whisper 경로로 갑니다 (전용 모델은 {m.wake_word} 전용)",
                  file=sys.stderr, flush=True)
            log.info("호출어 불일치 → whisper | 학습=%s | 설정=%s", m.wake_word, configured)
            return None

        m.probability(np.zeros(int(m.sample_rate * m.win_sec), dtype=np.float32))  # 예열
        return m
    except Exception as e:
        print(f"[wakeword] ⚠️ KWS 모델 로드 실패 → Whisper로 폴백: {e}",
              file=sys.stderr, flush=True)
        log.exception("KWS 모델 로드 실패")
        return None


def kws_energy_floor(default: float) -> float:
    """모델 백엔드용 에너지 관문. Whisper용보다 **훨씬 낮다.**

    관문의 존재 이유는 «비싼 추론을 아무 소리에나 돌리지 않는 것»이었다.
    Whisper는 창 하나에 700ms였으니 타당했다. 전용 모델은 **28.7ms**다 —
    0.6초마다 한 번 도니 점유율이 5%도 안 된다. **막을 이유가 사라졌다.**

    ⚠️ 관문을 Whisper 값(0.008) 그대로 두면 조용한 마이크에서 **발화가 모델에
      도달조차 못 한다.** 2026-09-08 실기에서 정확히 그랬다: 620번 «무음 스킵»이
      찍히는 동안 통과한 2번은 **둘 다 prob 1.000 · 0.893으로 성공**했다.
      모델이 못 알아들은 게 아니라 **들어볼 기회가 없었다.**
    """
    try:
        from config.settings import get_settings
        get_settings.cache_clear()
        return float(get_settings().wakeword_energy_model)
    except Exception:
        return min(default, 0.0015)


def kws_threshold() -> float:
    try:
        from config.settings import get_settings
        get_settings.cache_clear()
        return float(get_settings().wakeword_threshold)
    except Exception:
        return 0.8


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

    # 전용 KWS 모델이 있으면 그걸 쓴다. 없거나 실패하면 Whisper로 간다 (ADR §6).
    # ⚠️ Whisper는 **필요할 때만** 로드한다 — 둘 다 올리면 메모리와 시작 시간이 두 배다.
    kws = load_kws_model()
    if kws is not None:
        model = None
        energy_threshold = kws_energy_floor(energy_threshold)   # ← 관문을 백엔드에 맞춘다
        print(f"[wakeword] backend=model (KWS 전용 · 임계 {kws_threshold():.2f} · "
              f"에너지 {energy_threshold:.4f})", file=sys.stderr, flush=True)
        log.info("backend=model | 임계=%.2f | 에너지=%.4f | win=%.1fs",
                 kws_threshold(), energy_threshold, kws.win_sec)
    else:
        print(f"[wakeword] backend=whisper — Loading model ({model_size})...",
              file=sys.stderr, flush=True)
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        log.info("backend=whisper | model=%s", model_size)

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

    log.info("설정: backend=%s energy=%.4f window=%.1fs hop=%.1fs",
             "model" if kws is not None else f"whisper({model_size})",
             energy_threshold, WINDOW_SECONDS, HOP_SECONDS)
    print("[wakeword] 준비 완료. 감지 중...", file=sys.stderr, flush=True)

    last_wake = 0.0
    window = np.zeros(WINDOW_SAMPLES, dtype=np.float32)   # 최근 WINDOW_SECONDS 초
    since_hop = 0
    quiet_log_at = 0.0
    busy = threading.Lock()        # 인식은 한 번에 하나만 (창이 겹치므로 쌓이면 밀린다)

    def _fire(ts, why):
        """깨운다. 두 백엔드가 같은 출구를 쓰게 해서 동작이 갈리지 않게 한다."""
        nonlocal last_wake
        last_wake = ts
        print("WAKE", flush=True)
        print(f"[wakeword] *** WAKE WORD DETECTED *** ({why})",
              file=sys.stderr, flush=True)

    def _detect_model(chunk, ts):
        """전용 KWS 모델 경로. 창 하나 → 확률 하나.

        Whisper 경로와 달리 **텍스트가 없다.** 그래서 매칭 실패를 진단할 때 볼 것은
        `heard=...`가 아니라 **확률**이다 — 임계에 못 미친 값도 로그에 남긴다.
        안 그러면 "안 깨어났다"만 남고 아까웠는지 한참 멀었는지를 알 수 없다.
        """
        nonlocal last_wake
        try:
            if not WAKE_WORDS:          # 감시 끔(WAKE_WORD_ENABLED=false) — 재시작 불필요
                return
            pr = kws.probability(chunk)
            th = kws_threshold()
            if pr >= th:
                log.info("prob=%.3f ≥ %.2f → WAKE", pr, th)
                _fire(ts, f"prob={pr:.3f}")
            elif pr >= th * 0.5:          # 아깝게 놓친 것 — 임계만 낮추면 되는 경우다
                log.info("prob=%.3f < %.2f (놓침)", pr, th)
            else:
                # ⚠️ 낮은 확률도 **파일에는 남긴다.** 2026-09-08에 이걸 안 남겨서
                #   "왜 안 깨어나나"를 확률로 답할 수 없었다(다행히 «무음 스킵»이
                #   범인을 알려줬다). 콘솔은 INFO라 조용하고 파일만 DEBUG로 받는다.
                log.debug("prob=%.3f < %.2f", pr, th)
        except Exception as e:
            print(f"[wakeword] kws error: {e}", file=sys.stderr, flush=True)
            log.exception("KWS 추론 실패")
        finally:
            if busy.locked():
                busy.release()

    def _transcribe(chunk, ts):
        """창 하나를 인식해 웨이크워드가 있는지 본다. (Whisper 경로 — 폴백)"""
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
                _fire(ts, f"heard={text[:30]!r}")

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
            target=(_detect_model if kws is not None else _transcribe),
            args=(window.copy(), now), daemon=True,
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
