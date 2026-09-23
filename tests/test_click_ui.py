"""
좌표 기반 클릭(click_ui_element) 검증 — mock (실제 클릭 없음)
실행: python tests/test_click_ui.py

## 이 도구가 위험한 이유

클릭은 **되돌릴 수 없고**, 좌표는 Vision의 **추정**이다. 둘이 겹치면
"틀린 좌표를 정확히 클릭하는" 도구가 된다 — BL-12(엉뚱한 창에 입력)의 더 나쁜 판본.

그래서 세 겹으로 막는다. 이 테스트는 세 겹이 다 살아 있는지 본다.

  ① **LLM이 좌표를 넘길 수 없다** — 인자가 (target, window)뿐이다.
     좌표를 받을 수 있으면 언젠가 지어낸다.
  ② **사람 승인** — `DANGEROUS_TOOLS`라 hitl 노드가 먼저 물어본다.
  ③ **실행 직전 검사** — 못 찾았거나, 화면 밖이거나, 창이 그 사이 움직였으면
     **누르지 않는다.**

⚠️ 실제 마우스는 절대 움직이지 않는다. pyautogui를 가짜로 바꿔 호출만 기록한다.
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
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


# tools/__init__ 우회 (Linux CI에서 무관한 이유로 깨지지 않게)
if "tools" not in sys.modules:
    _stub = types.ModuleType("tools")
    _stub.__path__ = [os.path.join(_ROOT, "tools")]
    sys.modules["tools"] = _stub

_spec = importlib.util.spec_from_file_location(
    "tools.input_control", os.path.join(_ROOT, "tools", "input_control.py"))
IC = importlib.util.module_from_spec(_spec)
sys.modules["tools.input_control"] = IC
_spec.loader.exec_module(IC)


# ── 가짜 마우스 (실제로는 절대 안 움직인다) ────────────────────────
clicks = []
moves = []

class _FakeGui:
    FAILSAFE = True
    PAUSE = 0.0
    def position(self): return (10, 20)
    def click(self, x, y): clicks.append((x, y))
    def moveTo(self, x, y): moves.append((x, y))

IC._get_pyautogui = lambda: _FakeGui()

# ── 가짜 화면 인식 ────────────────────────────────────────────────
WINDOW_RECT = (700, 150, 800, 600)          # 창: (700,150) 에서 800x600
FOUND = {"found": True, "center": (1000, 300), "rect": (980, 290, 1020, 310),
         "size": (40, 20), "label": "저장 버튼", "window_rect": WINDOW_RECT}

_vision = types.ModuleType("tools.vision")
_result = {"value": dict(FOUND)}
_vision.locate_ui_element = lambda target, window="": dict(_result["value"])
sys.modules["tools.vision"] = _vision

_moved = {"value": False}
_system = types.ModuleType("tools.system")
_system.resolve_window_hwnd = lambda w: ((0 if w == "없는앱" else 1), w)
_system.window_screen_rect = lambda h: ((900, 150, 800, 600) if _moved["value"]
                                        else WINDOW_RECT)
sys.modules["tools.system"] = _system


def click(target="저장 버튼", window="메모장"):
    clicks.clear(); moves.clear()
    return IC.click_ui_element.invoke({"target": target, "window": window})


# ══════════════════════════════════════════════════════════════════
print("=== ① LLM이 좌표를 넘길 수 없다 ===")
args = IC.click_ui_element.args
check("인자는 target·window 뿐", set(args) == {"target", "window"}, f"→ {set(args)}")
check("x 좌표 인자가 없다", "x" not in args)
check("y 좌표 인자가 없다", "y" not in args)
d = IC.click_ui_element.description
check("좌표를 인자로 안 받는다고 설명에 명시", "좌표를 인자로 받지 않습니다" in d, f"→ {d}")
check("못 찾으면 클릭 안 한다고 명시", "클릭하지 않습니다" in d, f"→ {d}")


print("\n=== ② 승인을 받는다 (되돌릴 수 없다) ===")
import core.graph as G
check("DANGEROUS_TOOLS 에 등록됨", "click_ui_element" in G.DANGEROUS_TOOLS)
q = G._confirm_question({"name": "click_ui_element",
                         "args": {"target": "저장 버튼", "window": "메모장"}})
check("무엇을 누를지 알린다", "저장 버튼" in q, f"→ {q}")
check("어디서 누를지 알린다", "메모장" in q, f"→ {q}")
check("되돌릴 수 없다고 알린다", "되돌릴 수 없" in q, f"→ {q}")
check("삭제 문구('휴지통')를 쓰지 않는다", "휴지통" not in q, f"→ {q}")
q2 = G._confirm_question({"name": "click_ui_element", "args": {"target": "확인"}})
check("창을 안 줘도 질문이 성립한다", "확인" in q2 and q2.endswith(")"), f"→ {q2}")
# 재질문 문구가 삭제 전용이 아니어야 한다 (클릭에도 쓰인다)
rq = G._reask_question({"name": "click_ui_element", "args": {"target": "확인"}})
check("재질문이 삭제 전용 문구가 아니다", "삭제하려면" not in rq, f"→ {rq}")


print("\n=== ③ 정상 경로 ===")
r = click()
check("클릭이 일어났다", clicks == [(1000, 300)], f"→ {clicks}")
check("✓ 로 답한다", r.startswith("✓"), f"→ {r}")
check("어디를 눌렀는지 밝힌다", "(1000, 300)" in r, f"→ {r}")
check("무엇을 눌렀는지 밝힌다", "저장 버튼" in r, f"→ {r}")
check("효과까지 됐다고 하지 않는다", "화면을 확인해" in r, f"→ {r}")
check("마우스를 원래 자리로 돌려놓는다", moves == [(10, 20)], f"→ {moves}")


print("\n=== ④ 못 찾으면 아무 데도 누르지 않는다 ===")
print("    ※ 여기서 '화면 중앙이라도 눌러보기' 같은 건 절대 하면 안 된다")
_result["value"] = {"found": False, "reason": "화면에 보이지 않습니다"}
r = click()
check("🚨 클릭 0회", clicks == [], f"→ {clicks}")
check("✗ 로 답한다", r.startswith("✗"), f"→ {r}")
check("클릭하지 않았다고 명시", "클릭하지 않았어요" in r, f"→ {r}")
check("사유를 전달한다", "보이지 않습니다" in r, f"→ {r}")
_result["value"] = dict(FOUND)


print("\n=== ⑤ 창이 그 사이 움직이면 누르지 않는다 ===")
# 좌표는 캡처 시점의 창 위치 기준이다. 창이 움직였으면 그 좌표는 더 이상
# 그 요소를 가리키지 않는다 — 그대로 누르면 엉뚱한 것을 누른다.
_moved["value"] = True
r = click()
check("🚨 클릭 0회", clicks == [], f"→ {clicks}")
check("창이 움직였다고 알린다", "움직여서" in r, f"→ {r}")
_moved["value"] = False

print("\n=== ⑥ 창이 사라지면 누르지 않는다 ===")
r = click(window="없는앱")
check("🚨 클릭 0회", clicks == [], f"→ {clicks}")
check("창이 사라졌다고 알린다", "사라졌습니다" in r, f"→ {r}")


print("\n=== ⑦ 좌표가 창 밖이면 누르지 않는다 ===")
# Vision이 엉뚱한 좌표를 줬을 때 걸리는 마지막 그물
_result["value"] = dict(FOUND, center=(50, 50))     # 창은 (700,150) 부터다
r = click()
check("🚨 클릭 0회", clicks == [], f"→ {clicks}")
check("창 밖이라고 알린다", "창 밖" in r, f"→ {r}")
_result["value"] = dict(FOUND)


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
