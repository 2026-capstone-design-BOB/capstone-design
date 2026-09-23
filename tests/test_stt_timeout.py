"""STT 가 **안 돌아오는 일이 없다** — Google 호출 타임아웃 (BL-69 · 2026-09-23)

    python tests/test_stt_timeout.py

## 왜 이 스위트가 있나

2026-09-23 실기에서 **턴이 통째로 멈췄다.** 로그가 남긴 것은 이게 전부다:

    22:01:57 [STT] 인식 시작 | 40939 bytes | google
    (끝 — 성공도 실패도 없고 «턴 완료» 도 없다)

`speech_recognition` 의 `Recognizer.operation_timeout` 은 **기본값이 `None`** 이라
`urlopen(..., timeout=None)` 으로 나간다. 응답이 안 오면 **영원히 기다린다.**

🔑 **핵심은 «폴백이 있는데 폴백으로 못 간다»는 것이다.**
오프라인 대비로 Whisper 를 깔아 뒀는데, 그 길은 «망이 없을 때» 만 열리고
**«망이 느릴 때» 는 안 열린다.** 로컬 엔진이 있는데 쓰지 못하고 멈춰 있었다.

⚠️ 전시 부스는 공용 와이파이다. 여기서 멈추면 **«안 되는 물건»** 으로 보인다.

## 🚨 양방향으로 박는다

«타임아웃을 건다»만 고정하면 **0초로 만들어 항상 Whisper 로 보내는 수정**이 통과한다.
Google 은 온라인 품질의 기본 경로다 — 그래서 «정상 응답은 그대로 성공한다» 를
같이 못 박고, 값이 **터무니없이 작지 않은지** 도 본다.
"""
import _testenv  # noqa: F401
import io
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeRecognizer:
    """`recognize_google` 대역. **어떤 timeout 으로 불렸는지** 기억한다."""

    last = None

    def __init__(self):
        self.operation_timeout = None
        FakeRecognizer.last = self

    def recognize_google(self, audio, language=None):
        # 실제 구현은 operation_timeout 을 urlopen 에 그대로 넘긴다.
        self.seen_timeout = self.operation_timeout
        if getattr(FakeRecognizer, "boom", None):
            raise FakeRecognizer.boom
        return "소리 켜 줘"


def run():
    passed = total = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}"
              + ("" if cond or not detail else f"   → {detail}"))

    src = io.open(os.path.join(_ROOT, "services", "stt.py"), encoding="utf-8").read()

    # ═══ ① 상수 자체 ═════════════════════════════════════════════
    print("=== ① 타임아웃 값 ===")
    try:
        from services.stt import GOOGLE_STT_TIMEOUT, GOOGLE_STT_SLOW
        ok_import = True
    except Exception as e:                                    # noqa: BLE001
        GOOGLE_STT_TIMEOUT = GOOGLE_STT_SLOW = None
        ok_import = False
        print(f"  ⬜ 판정 불가 — services.stt 를 못 불러왔다 ({e})")

    if ok_import:
        check("타임아웃이 설정돼 있다", GOOGLE_STT_TIMEOUT is not None)
        # 🚨 반대 방향 — 0 으로 만들어 «항상 Whisper» 가 되는 수정을 막는다
        check("🚨 값이 터무니없이 작지 않다 (≥3초)", GOOGLE_STT_TIMEOUT >= 3.0,
              GOOGLE_STT_TIMEOUT)
        check("   무한정 기다리지도 않는다 (≤30초)", GOOGLE_STT_TIMEOUT <= 30.0,
              GOOGLE_STT_TIMEOUT)
        check("   «느리다» 기준은 타임아웃보다 짧다",
              GOOGLE_STT_SLOW < GOOGLE_STT_TIMEOUT,
              f"{GOOGLE_STT_SLOW} / {GOOGLE_STT_TIMEOUT}")

    # ═══ ② 실제로 recognizer 에 **걸리는가** ══════════════════════
    print("=== ② recognizer 에 실제로 걸린다 ===")
    check("🚨 `operation_timeout` 을 설정한다 (소스)",
          "operation_timeout = GOOGLE_STT_TIMEOUT" in src,
          "이 줄이 없으면 urlopen(timeout=None) 으로 나간다")
    # 설정만 하고 안 쓰는 일이 없도록, 호출 **전에** 오는지 본다
    i_set = src.find("operation_timeout = GOOGLE_STT_TIMEOUT")
    i_call = src.find("recognize_google(audio_data")
    check("   설정이 호출보다 **앞**에 온다", 0 < i_set < i_call, f"{i_set} / {i_call}")

    # ═══ ③ 폴백이 열려 있다 ══════════════════════════════════════
    #   🔑 이 결함의 본체는 «폴백이 있는데 못 간다» 였다.
    print("=== ③ 🔑 실패하면 Whisper 로 간다 ===")
    check("google 이 None 을 주면 whisper 를 부른다 (소스)",
          "_transcribe_whisper(webm_path)" in src)
    check("🚨 폴백 사유가 **로그**에 남는다 (print 만으로는 사라진다)",
          "whisper 폴백 | %s" in src or "whisper 폴백 | %s: %s" in src,
          "print 는 콘솔이 닫히면 없어진다 — 원인을 못 좁힌다")
    check("   느린데 성공한 것도 남긴다", "google 이 느리다" in src)

    # ═══ ④ 판정 경로를 **대역으로** 지나가 본다 ═══════════════════
    print("=== ④ 대역으로 한 바퀴 ===")
    fake_sr = types.ModuleType("speech_recognition")
    fake_sr.Recognizer = FakeRecognizer
    fake_sr.AudioData = lambda *a, **k: object()
    fake_sr.UnknownValueError = type("UnknownValueError", (Exception,), {})
    fake_sr.RequestError = type("RequestError", (Exception,), {})
    saved = sys.modules.get("speech_recognition")
    sys.modules["speech_recognition"] = fake_sr
    try:
        if not ok_import:
            print("  ⬜ 판정 불가 — 모듈을 못 불러왔다")
        else:
            import services.stt as S

            class _Fake(S.STTService):
                def __init__(self):
                    pass

            svc = _Fake()
            # PyAV 변환은 건너뛰고 recognizer 경로만 본다
            orig = S.av if hasattr(S, "av") else None
            FakeRecognizer.boom = None
            # `_transcribe_google` 은 내부에서 av 를 import 한다 — 대역을 끼운다
            fake_av = types.ModuleType("av")

            class _Res:
                def __init__(self, **k):
                    pass

                def resample(self, frame):
                    return [] if frame is None else [types.SimpleNamespace(
                        planes=[b"\x00\x01" * 100])]

            class _Container:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def decode(self, audio=0):
                    return [object()]

            fake_av.AudioResampler = _Res
            fake_av.open = lambda p: _Container()
            sys.modules["av"] = fake_av

            out = svc._transcribe_google("x.webm")
            check("정상 응답은 그대로 성공한다", out == "소리 켜 줘", f"→ {out!r}")
            check("🚨 그때 timeout 이 실제로 걸려 있었다",
                  getattr(FakeRecognizer.last, "seen_timeout", None)
                  == GOOGLE_STT_TIMEOUT,
                  getattr(FakeRecognizer.last, "seen_timeout", None))

            # 타임아웃이 나면 **None** 을 돌려 폴백을 연다
            FakeRecognizer.boom = TimeoutError("timed out")
            out = svc._transcribe_google("x.webm")
            check("🔑 타임아웃이면 None (→ whisper 폴백이 열린다)", out is None, f"→ {out!r}")
            FakeRecognizer.boom = None
            del sys.modules["av"]
            _ = orig
    finally:
        if saved is not None:
            sys.modules["speech_recognition"] = saved
        else:
            sys.modules.pop("speech_recognition", None)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
