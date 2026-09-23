"""
전용 KWS 백엔드 계약 검증 — mock (마이크·ONNX·모델 파일 불필요)
실행: python tests/test_wakeword_kws.py

2026-09-08에 웨이크워드 런타임이 Whisper에서 **전용 KWS 모델**로 바뀌었다(ADR 3단계).
여기서 보는 것은 «모델이 얼마나 잘 맞히나»가 아니다 — 그건 학습 스크립트가 임계값
표로 답하고, 최종 확인은 사람이 마이크에 대고 한다.

**여기서 보는 것은 «언제 모델을 쓰지 않는가»** 다. 그게 위험한 쪽이기 때문이다:
  - 호출어를 바꿨는데(BL-13) 모델이 옛 말에만 반응하면 → **조용한 무시**
  - 모델 파일이 없거나 깨졌는데 프로세스가 죽으면 → 창이 아예 안 뜬다
  - 설정으로 Whisper 복귀가 안 되면 → 되돌릴 방법이 없다 (ADR §6)

⚠️ `services/wakeword.py`는 최상위에서 sounddevice·faster-whisper를 import 한다.
   그래서 `tests/test_wakeword.py`와 **같은 방식**으로 소스에서 필요한 구간만 떼어내
   실행한다. CI(ubuntu, 오디오 패키지 없음)에서도 계약을 검증하기 위해서다.
"""
import sys, os, re, types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

passed = total = 0
def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond: passed += 1; print(f"  ✓ {name}")
    else:    print(f"  ✗ {name} {detail}")


# ── 오디오 의존성 없이 백엔드 선택 로직만 로드 ────────────────────
_src = open(os.path.join(_ROOT, "services", "wakeword.py"), encoding="utf-8").read()
_mod = types.ModuleType("kws_backend")
_mod.__dict__.update({"sys": sys, "os": os, "re": re, "np": None,
                      "__file__": os.path.join(_ROOT, "services", "wakeword.py"),
                      "log": types.SimpleNamespace(info=lambda *a, **k: None,
                                                   exception=lambda *a, **k: None),
                      "DEFAULT_WAKE_WORDS": ["플루이즈", "pluiz"]})
# model_covers (순수 판정) + KWS 백엔드 블록
_a = _src.index("def model_covers")
_b = _src.index("def rms(")
exec(compile(_src[_a:_src.index("WAKE_WORDS = _load_wake_words()")], "kws1", "exec"), _mod.__dict__)
exec(compile(_src[_src.index("MODEL_PATH = os.path.join"):_b], "kws2", "exec"), _mod.__dict__)


print("=== ① model_covers — 모델이 감당하는 호출어인가 ===")
COVERED = {"플루이즈", "pluiz", "헤이 플루이즈", "플루이즈야", "야 플루이즈"}
check("기본 설정(플루이즈·pluiz)은 감당한다",
      _mod.model_covers(["플루이즈", "pluiz"], COVERED))
check("로마자 표기 pluiz만 있어도 감당한다", _mod.model_covers(["pluiz"], COVERED))
check("«헤이 플루이즈»도 감당한다", _mod.model_covers(["헤이 플루이즈"], COVERED))
check("다른 말(자비스)은 감당 못 한다 → Whisper로 가야 한다",
      not _mod.model_covers(["자비스", "헤이 자비스"], COVERED))
check("하나라도 감당 못 하면 전체가 불가 (부분 감지는 더 나쁘다)",
      not _mod.model_covers(["플루이즈", "자비스"], COVERED))
check("빈 설정(감지 끔)은 여기서 막지 않는다 — 부르는 쪽이 거른다",
      _mod.model_covers([], COVERED))

print("=== ② 폴백 — 모델을 못 쓰면 조용히 Whisper로 (죽지 않는다) ===")
_mod.MODEL_PATH = os.path.join(_ROOT, "services", "__없는파일__.npz")
check("모델 파일이 없으면 None (예외 아님)", _mod.load_kws_model() is None)

_real = os.path.join(_ROOT, "services", "wakeword_model.npz")
if os.path.exists(_real):
    import io as _io
    _broken = os.path.join(_ROOT, "cache", "__broken_model__.npz")
    os.makedirs(os.path.dirname(_broken), exist_ok=True)
    with open(_broken, "wb") as f:
        f.write(b"not a real npz at all")
    _mod.MODEL_PATH = _broken
    check("모델 파일이 깨져 있어도 None (프로세스가 죽으면 창이 안 뜬다)",
          _mod.load_kws_model() is None)
    os.remove(_broken)
else:
    check("모델 파일이 깨져 있어도 None", True, "(모델 미생성 — 건너뜀)")

print("=== ③ 되돌리기 — 설정으로 Whisper 강제 (ADR §6) ===")
_mod.MODEL_PATH = _real
_prev = os.environ.get("WAKEWORD_BACKEND")
os.environ["WAKEWORD_BACKEND"] = "whisper"
check("WAKEWORD_BACKEND=whisper면 모델을 쓰지 않는다", _mod.load_kws_model() is None)
if _prev is None: os.environ.pop("WAKEWORD_BACKEND", None)
else: os.environ["WAKEWORD_BACKEND"] = _prev

print("=== ④ 임계값 설정 ===")
check("기본 임계는 0.8 (학습 검증: 감지 95.0% · 오탐 1.82%)",
      abs(_mod.kws_threshold() - 0.8) < 1e-9)
_prev_t = os.environ.get("WAKEWORD_THRESHOLD")
os.environ["WAKEWORD_THRESHOLD"] = "0.95"
check("설정으로 임계를 올릴 수 있다", abs(_mod.kws_threshold() - 0.95) < 1e-9)
if _prev_t is None: os.environ.pop("WAKEWORD_THRESHOLD", None)
else: os.environ["WAKEWORD_THRESHOLD"] = _prev_t

print("=== ④-2 에너지 관문 — 백엔드마다 다르다 (2026-09-08 실기에서 드러난 것) ===")
# 관문의 존재 이유는 «비싼 추론을 아무 소리에나 돌리지 않는 것»이었다. Whisper는
# 창 하나에 700ms라 타당했지만 전용 모델은 28.7ms다. 관문을 Whisper 값(0.008) 그대로
# 두면 **조용한 마이크에서 발화가 모델에 도달조차 못 한다** — 실제로 그랬다.
check("모델용 관문이 Whisper용(0.008)보다 훨씬 낮다",
      _mod.kws_energy_floor(0.008) < 0.008 / 2,
      f"실제={_mod.kws_energy_floor(0.008)}")
check("실측된 마이크 발화 대역(0.002~0.006)을 통과시킨다",
      _mod.kws_energy_floor(0.008) < 0.002,
      f"실제={_mod.kws_energy_floor(0.008)}")
check("순수 무음(≈0.0009)은 여전히 거른다", _mod.kws_energy_floor(0.008) > 0.0009)
_prev_e = os.environ.get("WAKEWORD_ENERGY_MODEL")
os.environ["WAKEWORD_ENERGY_MODEL"] = "0.004"
check("설정으로 관문을 올릴 수 있다 (오탐이 잦으면)",
      abs(_mod.kws_energy_floor(0.008) - 0.004) < 1e-9)
if _prev_e is None: os.environ.pop("WAKEWORD_ENERGY_MODEL", None)
else: os.environ["WAKEWORD_ENERGY_MODEL"] = _prev_e

print("=== ⑤ 학습 결과물 계약 (npz에 무엇이 들어 있어야 하나) ===")
# ⚠️ CI(ubuntu)는 lock에서 langgraph·langchain-core 두 줄만 설치한다 — **numpy가 없다.**
#   모델 파일은 커밋되므로 여기 들어오지만 읽을 수단이 없다. 그럴 땐 건너뛴다.
#   (건너뛰어도 **개수가 같아야** 한다 — README 상태표의 숫자가 환경마다 달라지면
#    "이 숫자의 출처는 표 하나다"라는 규칙이 깨진다.)
try:
    import numpy as _np
except ImportError:
    _np = None
if os.path.exists(_real) and _np is not None:
    z = _np.load(_real, allow_pickle=False)
    for k in ("W0", "b0", "n_layers", "wake_word", "win_sec", "sample_rate"):
        check(f"npz에 {k}", k in z)
    check("npz에 wake_phrases (없으면 호출어 대조를 못 한다)", "wake_phrases" in z)
    if "wake_phrases" in z:
        ph = {str(x) for x in z["wake_phrases"]}
        check("wake_phrases가 기본 호출어를 덮는다",
              {"플루이즈", "pluiz"} <= ph, f"실제={sorted(ph)}")
    check("창 길이가 런타임과 같다 (2.0초)", abs(float(z["win_sec"]) - 2.0) < 1e-9)
    check("샘플레이트가 런타임과 같다 (16000)", int(z["sample_rate"]) == 16000)
else:
    _why = "numpy 없음(CI)" if _np is None else "모델 미생성"
    for k in ("W0", "b0", "n_layers", "wake_word", "win_sec", "sample_rate",
              "wake_phrases", "기본 호출어 커버"):
        check(f"npz 계약 — {k}", True, f"({_why} — 건너뜀)")
    check("창 길이가 런타임과 같다 (2.0초)", True, f"({_why} — 건너뜀)")
    check("샘플레이트가 런타임과 같다 (16000)", True, f"({_why} — 건너뜀)")

print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
