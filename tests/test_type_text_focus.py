"""
BL-12 — `type_text`가 **입력 전에 대상 창을 확인**하는지 검증
실행: python tests/test_type_text_focus.py

## 무슨 일이 있었나 (2026-09-03 실기)

```
👤 (메모장 열린 상태에서) 거기에 회의록이라고 적어줘
🤖 네, 메모장에 '회의록'이라고 적어드렸어요.
```
실제로는 **Pluiz 오버레이 입력창**에 "회의록"이 들어갔다. `pyautogui`는 지정한 창이
아니라 **그때 포커스된 창**에 키를 보내기 때문이다. 도구는 예외만 안 나면 무조건
`"✓ 텍스트 입력 완료"`를 반환했고, 어느 창에 들어갔는지는 아무도 몰랐다.

## 이 테스트가 지키는 계약

  - 대상 창을 못 찾으면 **입력하지 않는다** (잘못 들어간 글자는 되돌릴 수 없다)
  - 대상 창이 앞에 오지 않으면 **입력하지 않는다**
  - 거부할 때 **어디에 들어갈 뻔했는지** 알려준다
  - 성공해도 **어느 창에 넣었는지** 밝힌다 ← 이게 있었으면 실기에서 바로 보였다

⚠️ 실제 키 입력은 하지 않는다. `pyautogui`/`pyperclip`과 창 조회를 전부 가짜로 바꾼다.
   **자동화 스크립트에서 진짜 type_text를 돌리면 사용자가 보고 있던 창에 글자가 들어간다.**
"""
import sys, os, types, importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0

def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


# ── tools/input_control.py 를 패키지 __init__ 우회해 직접 로드 ──────
# `tools/__init__.py`가 app_control(psutil·ctypes.wintypes)을 eager import 하므로
# 그냥 import 하면 Linux(CI)에서 input_control과 무관한 이유로 깨진다.
# (tests/test_vision.py와 같은 기법)
if "tools" not in sys.modules:
    _stub = types.ModuleType("tools")
    _stub.__path__ = [os.path.join(_ROOT, "tools")]
    sys.modules["tools"] = _stub

_spec = importlib.util.spec_from_file_location(
    "tools.input_control", os.path.join(_ROOT, "tools", "input_control.py"))
IC = importlib.util.module_from_spec(_spec)
sys.modules["tools.input_control"] = IC
_spec.loader.exec_module(IC)


# ── 가짜 입력 장치 (실제 키는 절대 보내지 않는다) ──────────────────
pasted = []

class _FakeClip:
    def __init__(self): self._v = ""
    def copy(self, v): self._v = v
    def paste(self): return self._v

class _FakeGui:
    FAILSAFE = True
    PAUSE = 0.0
    def hotkey(self, *keys): pasted.append("+".join(keys))
    def press(self, k): pasted.append(k)

IC._get_pyperclip = lambda: _FakeClip()
IC._get_pyautogui = lambda: _FakeGui()


# ── 가짜 창 세계 ──────────────────────────────────────────────────
# hwnd 100 = 메모장 / hwnd 200 = Pluiz 오버레이(실기에서 글자가 잘못 들어간 그 창)
WORLD = {"foreground": 200, "focus_works": True}

def _fake_app_control():
    m = types.ModuleType("tools.app_control")
    def find_hwnd_for_app(app):
        return {"메모장": 100, "크롬": 300}.get(app, 0)
    def _focus_window(key):
        if WORLD["focus_works"]:
            WORLD["foreground"] = 100
            return True
        return False
    m.find_hwnd_for_app = find_hwnd_for_app
    m._focus_window = _focus_window
    m._normalize = lambda a: a
    return m

sys.modules["tools.app_control"] = _fake_app_control()

IC._foreground_window = lambda: (
    WORLD["foreground"],
    {100: "제목 없음 - 메모장", 200: "Pluiz", 300: "Chrome"}.get(WORLD["foreground"], ""),
)


def call(text, target=""):
    pasted.clear()
    return IC.type_text.invoke({"text": text, "target": target})


# ══════════════════════════════════════════════════════════════════
print("=== ① 대상 창이 앞에 오면 입력한다 ===")
WORLD.update(foreground=200, focus_works=True)
r = call("회의록", target="메모장")
check("✓로 시작", r.startswith("✓"), f"→ {r}")
check("실제로 붙여넣기가 일어났다", "ctrl+v" in pasted, f"→ {pasted}")
check("**어느 창에** 넣었는지 밝힌다", "메모장" in r, f"→ {r}")
check("입력 내용을 함께 보고", "회의록" in r, f"→ {r}")

print("\n=== ② 이미 대상 창이 앞이면 굳이 포커스를 옮기지 않는다 ===")
WORLD.update(foreground=100, focus_works=False)   # 포커스 이동이 실패해도 상관없어야 함
r = call("회의록", target="메모장")
check("✓ 입력 성공", r.startswith("✓"), f"→ {r}")
check("붙여넣기 발생", "ctrl+v" in pasted)


print("\n=== ③ 🚨 대상 창을 앞으로 못 가져오면 입력하지 않는다 ===")
print("    ※ 실기에서 Pluiz 오버레이에 '회의록'이 들어간 바로 그 상황")
WORLD.update(foreground=200, focus_works=False)
r = call("회의록", target="메모장")
check("✗로 시작 (성공 위장 안 함)", r.startswith("✗"), f"→ {r}")
check("🚨 **키를 보내지 않았다**", pasted == [], f"→ {pasted}")
check("어느 창에 들어갈 뻔했는지 알려준다", "Pluiz" in r, f"→ {r}")
check("입력하지 않았다고 명시", "입력하지 않았습니다" in r, f"→ {r}")


print("\n=== ④ 대상 창이 아예 없으면 입력하지 않는다 ===")
WORLD.update(foreground=200, focus_works=True)
r = call("회의록", target="한글")          # find_hwnd_for_app → 0
check("✗로 시작", r.startswith("✗"), f"→ {r}")
check("키를 보내지 않았다", pasted == [], f"→ {pasted}")
check("찾을 수 없다고 알린다", "찾을 수 없" in r, f"→ {r}")
check("무엇을 해야 하는지 알려준다", "열어주세요" in r, f"→ {r}")


print("\n=== ⑤ target을 안 주면 예전처럼 현재 창에 넣는다 ===")
# 막지는 않는다. 다만 **어느 창에 들어갔는지 밝혀서** 사용자가 알아챌 수 있게 한다.
# (실기의 오보는 이 정보가 없어서 아무도 몰랐던 것이다)
WORLD.update(foreground=200, focus_works=True)
r = call("회의록")
check("입력은 된다", r.startswith("✓"), f"→ {r}")
check("붙여넣기 발생", "ctrl+v" in pasted)
check("🔎 들어간 창을 밝힌다 — 'Pluiz'라고 나와야 사용자가 알아챈다",
      "Pluiz" in r, f"→ {r}")


print("\n=== ⑥ 도구 설명이 LLM에게 target을 요구한다 ===")
d = IC.type_text.description
check("target 인자 설명 존재", "target" in d, f"→ {d[:80]}")
check("지정하라고 못박음", "반드시 지정" in d, f"→ {d}")
check("확인 안 되면 입력 안 한다고 명시", "입력하지 않" in d, f"→ {d}")


print("\n=== ⑦ 창 확인 수단이 없어도 죽지 않는다 ===")
_saved = sys.modules.pop("tools.app_control")
sys.modules["tools.app_control"] = None      # import 시 ImportError 유발
try:
    WORLD.update(foreground=200)
    r = call("회의록", target="메모장")
    check("확인 불가 → 막지 않고 예전 동작", r.startswith("✓"), f"→ {r}")
finally:
    sys.modules["tools.app_control"] = _saved


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
