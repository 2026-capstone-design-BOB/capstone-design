"""
Vision(화면 이해) 도구 검증 — mock (LLM API 불필요)
실행: python tests/test_vision.py

실제 화면 캡처와 Gemini Vision 호출은 라이브 영역이라 여기서 하지 않는다.
여기서 보는 것은 **키 없이 확인 가능한 계약**이다:
  - 캡처 실패 시 성공처럼 답하지 않는가   ← 이 프로젝트가 반복해서 데인 지점
  - LLM 호출 실패가 예외로 새지 않고 [오류] 문자열로 돌아오는가
  - 임시파일을 남기지 않는가
  - 프롬프트가 할루시네이션을 막는 지시를 담고 있는가
  - 개인정보 주의(OWASP LLM02)가 문서에 남아 있는가

⚠️ CI(ubuntu)와 로컬(Windows)에서 커버 범위가 다르다.
`tools/system.py`·`app_control.py`가 psutil·ctypes.wintypes를 최상위에서 import하므로
Linux에서는 그 경로를 못 탄다. **없으면 PASS가 아니라 SKIP으로 표시한다** —
2026-09-01에 "의존성이 없는데 통과하던 테스트"로 크게 데였기 때문이다.
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
import sys, os, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0
skipped = []

def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")

def skip(name, reason):
    skipped.append(f"{name} ({reason})")
    print(f"  ⚠ SKIP {name} — {reason}")


def _have(mod: str) -> bool:
    try:
        __import__(mod); return True
    except Exception:
        return False


# Windows 전용 모듈에 의존하는 경로를 탈 수 있는가
_win_ok = True
_win_why = ""
try:
    import tools.system as S          # noqa: F401  (psutil + ctypes)
except Exception as _e:
    _win_ok = False
    _win_why = f"{type(_e).__name__}: {_e}"

_pil_ok = _have("PIL")

# ── tools/vision.py 를 패키지 __init__ 을 우회해 직접 로드 ─────────────
# `tools/__init__.py` 가 app_control(psutil·ctypes.wintypes)을 eager import 하므로
# 그냥 `import tools.vision` 하면 **Linux(CI)에서 vision과 무관한 이유로 깨진다.**
# core/__init__.py 처럼 lazy 하지 않기 때문이다.
# tests/test_p3_3.py 가 core 패키지에 쓰는 것과 같은 stub 패키지 기법을 쓴다.
import importlib.util, types

if "tools" not in sys.modules:
    _stub = types.ModuleType("tools")
    _stub.__path__ = [os.path.join(_ROOT, "tools")]
    sys.modules["tools"] = _stub

_spec = importlib.util.spec_from_file_location(
    "tools.vision", os.path.join(_ROOT, "tools", "vision.py"))
V = importlib.util.module_from_spec(_spec)
sys.modules["tools.vision"] = V
_spec.loader.exec_module(V)


print("=== ① 도구 등록 ===")
if _win_ok:
    from core.tool_registry import get_all_tools
    names = [t.name for t in get_all_tools()]
    check("describe_screen 등록됨", "describe_screen" in names)
    from core.graph import DANGEROUS_TOOLS
    check("describe_screen은 위험도구가 아님 (HITL 불필요)",
          "describe_screen" not in DANGEROUS_TOOLS)
else:
    skip("도구 등록 확인", f"tools.system import 불가 — {_win_why}")


print("\n=== ② 캡처 실패 시 성공처럼 답하지 않는다 ===")
if _win_ok:
    _orig_shot = S.take_screenshot

    class _FailShot:
        name = "take_screenshot"
        def invoke(self, args):       # 파일을 만들지 않고 실패 문자열만 반환
            return "✗ '없는앱' 창을 찾을 수 없습니다."

    S.take_screenshot = _FailShot()
    try:
        r = V.describe_screen.invoke({"window": "없는앱", "question": ""})
        check("캡처 실패 → ✗ 로 시작 (성공 위장 안 함)",
              r.startswith("✗"), f"→ {r[:60]}")
        check("실패 사유를 그대로 전달", "찾을 수 없" in r, f"→ {r[:60]}")
    finally:
        S.take_screenshot = _orig_shot
else:
    skip("캡처 실패 처리", "tools.system import 불가")


print("\n=== ③ LLM 호출 실패가 예외로 새지 않는다 ===")
if _win_ok and _pil_ok:
    from PIL import Image
    import core.llm as L

    class _OkShot:
        name = "take_screenshot"
        def invoke(self, args):
            Image.new("RGB", (40, 30), (10, 20, 30)).save(args["save_path"], "PNG")
            return "✓ 저장 완료"

    _orig_shot, _orig_llm = S.take_screenshot, L.build_llm
    S.take_screenshot = _OkShot()
    def _boom(*a, **k): raise RuntimeError("API 키 없음(테스트)")
    L.build_llm = _boom
    try:
        r = V.describe_screen.invoke({"window": "", "question": ""})
        check("LLM 실패 → [오류] 문자열 반환 (예외 전파 안 함)",
              "[오류]" in r, f"→ {r[:70]}")
        check("실패인데 화면 설명을 지어내지 않음",
              "보입니다" not in r and "열려" not in r, f"→ {r[:70]}")
    finally:
        S.take_screenshot, L.build_llm = _orig_shot, _orig_llm

    print("\n=== ④ 임시파일을 남기지 않는다 ===")
    leftovers = [f for f in os.listdir(tempfile.gettempdir())
                 if f.startswith("pluiz_vision_")]
    check("pluiz_vision_ 임시파일 잔여 없음", not leftovers, f"→ {leftovers[:3]}")
else:
    why = "tools.system import 불가" if not _win_ok else "Pillow 미설치"
    skip("LLM 실패 처리 + 임시파일 정리", why)


print("\n=== ⑤ 프롬프트가 할루시네이션을 막는다 ===")
p = V._BASE_PROMPT
check("'추측하지 말고' 지시 포함", "추측하지" in p)
check("안 보이면 안 보인다고 말하라는 지시", "보이지 않는다" in p)
check("한국어 응답 지시", "한국어" in p)


print("\n=== ⑥ 개인정보 주의가 문서에 남아 있다 (OWASP LLM02) ===")
src = open(os.path.join(_ROOT, "tools", "vision.py"), encoding="utf-8").read()
check("화면 내용 외부 전송 경고 명시", "외부 LLM" in src and "전송" in src)
check("도구 설명에 '물어볼 때만' 제한", "물어볼 때만" in V.describe_screen.description)


# ── Vision 응답 로그 — 미리보기는 옵트인이다 (2026-09-08) ──────────
#
# 화면에 떠 있던 내용이 로그 파일에 남는 일이라, **기본이 조용히 뒤집히면 안 된다.**
# 그래서 «기본은 길이만»을 테스트로 못박는다. 로그는 mask_sensitive_output()을
# 거치지 않는다 — 그건 사용자에게 나가는 응답에만 걸린다.
print("\n=== Vision 응답 로그 (미리보기는 옵트인) ===")


class _CapturingLog:
    def __init__(self): self.lines = []
    def info(self, fmt, *a): self.lines.append(fmt % a)
    def __getattr__(self, _): return lambda *a, **k: None


def _log_with(monkey_settings):
    """설정을 갈아끼우고 _log_response를 호출해 남은 로그 한 줄을 돌려준다."""
    cap = _CapturingLog()
    orig_log = V.log
    V.log = cap
    try:
        import config.settings as _cs
        orig_get = _cs.get_settings
        _cs.get_settings = monkey_settings
        try:
            V._log_response("Vision 응답", "비밀번호는 hunter2 입니다\n두 번째 줄")
        finally:
            _cs.get_settings = orig_get
    finally:
        V.log = orig_log
    return cap.lines[-1] if cap.lines else ""


class _S:
    def __init__(self, on, n=200):
        self.vision_log_response = on
        self.vision_log_preview_chars = n


_off = _log_with(lambda: _S(False))
check("기본(꺼짐)은 길이만 남긴다", "자" in _off and "hunter2" not in _off, _off)

_on = _log_with(lambda: _S(True))
check("켜면 미리보기가 남는다", "hunter2" in _on, _on)
check("미리보기는 줄바꿈을 펴서 한 줄로 남긴다", "\n" not in _on, repr(_on))


def _boom():
    raise RuntimeError("설정을 못 읽는 상황")


_broken = _log_with(_boom)
check("설정을 못 읽으면 **안 남기는 쪽**으로 간다 (안전 기본값)",
      "hunter2" not in _broken, _broken)

_zero = _log_with(lambda: _S(True, 0))
check("미리보기 길이가 0이면 남기지 않는다", "hunter2" not in _zero, _zero)


tail = f"  ({len(skipped)}건 SKIP: {'; '.join(skipped)})" if skipped else ""
print(f"\n결과: {passed}/{total} 통과{tail}")
sys.exit(0 if passed == total else 1)
