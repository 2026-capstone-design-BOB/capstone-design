"""
실행 중인 앱 목록(get_running_apps) 검증 — mock (실제 프로세스 목록 없음)
실행: python tests/test_running_apps.py

## 왜 이 테스트가 생겼나

2026-09-07 실기에서 **계산기를 열어 둔 채** 물었더니 *"계산기는 지금 실행 중인 앱
목록에 없네요"* 라고 답했다. `open_app("계산기")`는 되는데 `get_running_apps`는
계산기를 **모르고 있었다** — 이 함수가 `APP_PROCESS_MAP`을 두고 **자기만의 12개짜리
화이트리스트**를 따로 들고 있었기 때문이다(같은 사실이 두 곳에 있어 한쪽만 갱신된,
이 프로젝트가 반복해서 데인 모양이다). `wt.exe`도 실제 이름이 `WindowsTerminal.exe`라
못 잡고 있었다.

더 나빴던 건 **말투**다. 아는 앱만 보면서 *"…만 실행 중이에요"* 라고 단정했다.
TASKS가 *"응답 문구 말고 get_running_apps 상태로 판정하라"* 고 적어 둔 그 도구라서,
**판정의 근거 자체가 못 믿을 물건**이었다.

그래서 여기서 보는 것은 두 가지다.

  ① **열 수 있는 앱은 볼 수도 있어야 한다** — 세 지도(별칭·프로세스·표시이름)가
     어긋나면 바로 실패한다. 새 앱을 추가할 때 한 곳만 고치면 여기서 걸린다.
  ② **아는 만큼만 말한다** — 목록이 비었든 찼든 "아는 앱만 확인한다"는 고지가 붙는다.

⚠️ 실제 프로세스를 열거하지 않는다. psutil을 가짜로 바꿔 끼운다.
"""
import _testenv  # noqa: F401
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.app_control import APP_ALIASES, APP_PROCESS_MAP, APP_DISPLAY_NAMES
import tools.system as S

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


class _P:
    """psutil.Process 흉내 — info["name"]만 있으면 된다."""

    def __init__(self, name):
        self.info = {"name": name}


def run_with(procs):
    """가짜 프로세스 목록으로 get_running_apps를 돌린다."""
    real = S.psutil.process_iter
    S.psutil.process_iter = lambda attrs=None: [_P(n) for n in procs]
    try:
        return S.get_running_apps.invoke({})
    finally:
        S.psutil.process_iter = real


# ── 1. 세 지도가 어긋나지 않는다 (단일 출처) ──────────────────────
print("[1] 열 수 있는 앱은 볼 수도 있어야 한다")

alias_keys = set(APP_ALIASES.values())
missing_proc = sorted(alias_keys - set(APP_PROCESS_MAP))
missing_name = sorted(set(APP_PROCESS_MAP) - set(APP_DISPLAY_NAMES))
check("open_app이 아는 앱은 전부 APP_PROCESS_MAP에 있다",
      not missing_proc, f"빠진 키={missing_proc}")
check("APP_PROCESS_MAP의 앱은 전부 한국어 표시 이름이 있다",
      not missing_name, f"빠진 키={missing_name}")
check("계산기가 세 지도에 모두 있다",
      "calculator" in alias_keys and "calculator" in APP_PROCESS_MAP
      and "calculator" in APP_DISPLAY_NAMES)


# ── 2. 실기에서 틀렸던 두 앱 ──────────────────────────────────────
print("")
print("[2] 2026-09-07 실기에서 못 잡던 것들")

out = run_with(["CalculatorApp.exe"])
check("계산기(UWP, CalculatorApp.exe)를 잡는다", "계산기" in out, out)
check("Calculator.exe(구버전)도 잡는다", "계산기" in run_with(["Calculator.exe"]))
check("대소문자가 달라도 잡는다", "메모장" in run_with(["Notepad.exe"]))
# wt.exe는 실행 스텁이고 실제로 떠 있는 창은 WindowsTerminal.exe다(실기 확인).
# 이 줄이 처음엔 wt.exe만 봐서 **거짓 통과**했다 — 실기에서 못 잡던 바로 그 이름으로 본다.
check("터미널을 실제 프로세스명(WindowsTerminal.exe)으로 잡는다",
      "터미널" in run_with(["WindowsTerminal.exe"]))
check("실행 스텁(wt.exe)으로도 잡는다", "터미널" in run_with(["wt.exe"]))


# ── 3. 아는 만큼만 말한다 ─────────────────────────────────────────
print("")
print("[3] 확인하지 않은 것을 확인한 것처럼 말하지 않는다")

NOTICE = "Pluiz가 아는 앱만 확인할게요"  # 🔄 2026-09-23 — 말투를 해요체로 통일했다(2-2 ⓐ). **소스 문구를 그대로** 적는다.
check("앱을 찾았을 때도 고지가 붙는다", NOTICE in run_with(["notepad.exe"]))
check("아무것도 못 찾았을 때도 고지가 붙는다", NOTICE in run_with(["Idle.exe"]))
check("모르는 앱은 목록에 넣지 않는다",
      "Idle" not in run_with(["Idle.exe"]))
check("죽는 중이라 이름이 없는 프로세스에도 죽지 않는다",
      "메모장" in run_with([None, "notepad.exe"]))


print(f"\n{chr(61) * 60}")
print(f"결과: {passed}/{total} 통과")
print(chr(61) * 60)
sys.exit(0 if passed == total else 1)
