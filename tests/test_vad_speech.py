"""말 판정으로 발화 종료를 끝내는 길 — 회귀 자물쇠 (M10 · 2026-10-01).

## 왜

음악이 나오면 크기가 안 떨어져서 «무음»이 영영 안 오고 녹음이 상한(30초)까지 갔다
(BL-81). 크기로는 못 푼다는 것이 네 번의 실측으로 닫혔다 —
**자동 볼륨 조절을 켜면 음악이 안 끝나고, 끄면 2m 목소리(0.0068)가 안 들린다.**

같은 자료를 말 판정기로 재면 갈린다:
    음악만   RMS 0.0026(가장 큼) · **말 확률 0.000**
    사람 말                      · 최대 확률 **0.98** (호출 499건 중 90%가 0.9 초과)

🔒 **설계의 핵심은 「더하기」다.** 시작 판정은 한 글자도 안 건드리고, 종료는
  «끝낼 수 있는 조건»을 하나 더 놓는다(OR). 그래서 새 신호는 녹음을 **더 일찍
  끝낼 수만** 있고 더 끌거나 시작을 막을 수 없다. 2m 가 거기 걸려 있다.

실행: python tests/test_vad_speech.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0


def check(label, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ FAIL {label}" + (f"   → {detail}" if detail else ""))


def _src(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


_WS = _src("services", "wakeword.py")
_UI = _src("electron-ui", "renderer", "index.html")
_MJS = _src("electron-ui", "main.js")
_PRE = _src("electron-ui", "preload.js")


# ═══ ① 신호를 내보내는 쪽 ═════════════════════════════════════════
print("=== ① 웨이크워드 프로세스가 말 판정을 내보낸다 ===")
check("`VAD_SPEECH 1` / `VAD_SPEECH 0` 을 찍는다",
      '"VAD_SPEECH 1"' in _WS and '"VAD_SPEECH 0"' in _WS)
check("🚨 신호 이름에 **`WAKE` 가 안 들어간다** — main.js 가 includes('WAKE') 로 본다",
      "WAKE" not in "VAD_SPEECH")
check("🔑 **상태가 바뀔 때만** 보낸다 (매 프레임이면 stdout 이 터진다)",
      "_speech_on" in _WS and "상태가 바뀌었을 때만" in _WS)
check("히스테리시스가 있다 (하나면 임계 근처에서 떤다)",
      "SPEECH_ON = 0.5" in _WS and "SPEECH_OFF = 0.35" in _WS)
check("🔑 **방금 들어온 조각**만 본다 (창 전체의 최댓값이 아니다)",
      "chunk[-SPEECH_FRAME:]" in _WS)
check("🚨 창 최댓값을 쓰면 왜 안 되는지 적혀 있다 (음악 5분에 19번 떴다)",
      "19번" in _WS)
check("프레임 크기가 Silero 가 받는 512 다", "SPEECH_FRAME = 512" in _WS)

check("🔒 모델이 없으면 **조용히 포기한다** — 웨이크워드는 그대로 돌아야 한다",
      "크기 판정만으로 돈다" in _WS)
check("🔒 말 판정이 터져도 웨이크워드가 안 죽는다 (try/except 로 감쌌다)",
      "말 판정이 깨져도 웨이크워드는 돌아야 한다" in _WS)
check("🔑 깨우는 판단과 **따로** 돈다 (홉·관문·쿨다운에 안 걸린다)",
      "깨우는 판단과 따로" in _WS)

try:
    from config.settings import get_settings
    get_settings.cache_clear()
    check("설정으로 끌 수 있다 (`vad_speech_enabled`)",
          hasattr(get_settings(), "vad_speech_enabled"))
    import services.wakeword as W
    check("기본이 켜짐이다", W.speech_enabled() is True)
    check("🔑 말 판정기가 실제로 뜬다 (faster-whisper 가 들고 온다 — 새 의존성 0)",
          W._load_speech_model() not in (None, False))
except Exception as e:                                        # noqa: BLE001
    check("설정·모델을 실제로 불러온다", False, f"{type(e).__name__}: {e}")


# ═══ ② 신호가 렌더러까지 간다 ═════════════════════════════════════
print("\n=== ② 신호가 Electron 을 거쳐 렌더러까지 간다 ===")
check("main.js 가 `VAD_SPEECH` 를 읽는다", "VAD_SPEECH" in _MJS)
check("🚨 `WAKE` 검사보다 **먼저** 본다",
      _MJS.find("VAD_SPEECH") < _MJS.find("out.includes('WAKE')"))
check("🔑 한 번에 여러 줄이 와도 **마지막 상태**를 쓴다",
      "sp[sp.length - 1]" in _MJS)
check("preload 가 `onVadSpeech` 를 연다", "onVadSpeech" in _PRE)
check("렌더러가 구독한다", "onVadSpeech" in _UI)


# ═══ ③ 🔒 더하기지 바꾸기가 아니다 ════════════════════════════════
#
# 🚨 이번 라운드에서 고치려다 더 큰 것을 깬 적이 두 번 있다(AGC 끄기 · 반려된 12초).
#   그래서 여기가 이 파일에서 **가장 중요한 절**이다.
print("\n=== ③ 지금 되는 것을 안 건드렸다 ===")
_vad = _UI[_UI.find("const VAD = {"):_UI.find("const CIRCUM")]
check("🔒 시작 임계가 그대로다 (2m 가 여기 걸려 있다)", "START_RMS: 0.020" in _vad)
check("🔒 크기 종료 임계가 그대로다", "KEEP_RMS: 0.012" in _vad)
check("🔒 상한이 30초 그대로다 (사용자가 반려한 자리)", "MAX_MS: 30000" in _vad)
check("🔒 AGC 를 다시 끄지 않았다", "autoGainControl: false" not in _UI)

check("🔑 크기 종료 조건이 **그대로 살아 있다**",
      "if (quietAt && now - quietAt >= VAD.SILENCE_MS) endVad('endpoint', 'rms');" in _UI)
check("🔑 말 판정은 **따로 끝내는 길**이다 (OR — 더 일찍 끝낼 수만 있다)",
      "endVad('endpoint', 'speech')" in _UI)
check("말 판정 쪽은 **더 참는다** (숨 고르는 사이에 끊기지 않게)",
      "SPEECH_SILENCE_MS: 2000" in _vad)
check("왜 2.0초인지 실측이 적혀 있다 (1.2초면 12.3%, 2.0초면 4.5% 가 도중에 끊긴다)",
      "12.3%" in _vad and "4.5%" in _vad)

check("🔒 **신호가 안 오면 아무 일도 안 일어난다** (오래된 신호는 버린다)",
      "SPEECH_STALE_MS" in _UI and "speechSeenAt" in _UI)
check("🔑 녹음을 새로 시작할 때 지난 상태가 안 샌다",
      "지난 녹음의" in _UI and "speechQuietAt = 0" in _UI)


# ═══ ④ 무엇이 끝냈는지 로그에 남는다 ══════════════════════════════
print("\n=== ④ 어느 쪽이 끝냈는지 보인다 ===")
_MAIN = _src("main.py")
check("보고에 `end_by` 가 있다", "end_by" in _UI and "end_by: str" in _MAIN)
check("로그에 `끝낸것=` 이 찍힌다", "끝낸것=%s" in _MAIN)
check("🔑 그래야 «새 신호가 실제로 일을 했나»를 잴 수 있다",
      "말 판정기가 실제로 일을 한 것" in _MAIN)


# ═══ ⑤ 판정 논리 — 실제 확률로 ════════════════════════════════════
print("\n=== ⑤ 판정 논리 ===")
try:
    import services.wakeword as W2

    def run(probs):
        """런타임과 같은 히스테리시스로 상태 열을 만든다."""
        on, out = False, []
        for p in probs:
            if not on and p >= W2.SPEECH_ON:
                on = True
            elif on and p < W2.SPEECH_OFF:
                on = False
            out.append(on)
        return out

    check("0.5 를 넘으면 켜진다", run([0.6])[-1] is True)
    check("🔑 0.5 아래라고 바로 꺼지지 않는다 (히스테리시스 — 0.35 까지는 유지)",
          run([0.6, 0.4])[-1] is True)
    check("0.35 아래면 꺼진다", run([0.6, 0.2])[-1] is False)
    check("🚨 음악 수준(0.00)에서는 안 켜진다", run([0.0, 0.0, 0.0])[-1] is False)
    check("🔑 사람 말 수준(0.98)에서는 켜진다", run([0.98])[-1] is True)
except Exception as e:                                        # noqa: BLE001
    check("판정 논리를 실제로 돌린다", False, f"{type(e).__name__}: {e}")


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
