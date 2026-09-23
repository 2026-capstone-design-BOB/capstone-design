"""BL-26 — 창을 «열었다»고 말하기 전에 **실제로 떴는지 본다**

    python tests/test_window_truth.py

## 무엇을 막는 테스트인가 (2026-09-09 실기 사고)

```
🎤 설정 창 열어줘
🤖 ✓ 설정 창을 앞으로 가져왔습니다.      ← 설정은 뜨지 않았다
🎤 안 열려 있는데 설정창
🤖 어? 설정 앱이 열려있다고 나오는데…
```

사용자: *"설정 앱을 애초에 못 여는 것 같아. 그리고 안 열렸는데 열었다고 거짓말 하는 거."*

**뿌리는 «유령 창»이었다.** Windows는 정지된 UWP 앱(설정 등)의 창을 닫지 않고
**DWM cloak** 한다. 그 창은 이렇게 보인다:

    IsWindowVisible : True       ← «보인다»고 나온다
    IsIconic        : False      ← 최소화도 아니다
    GetWindowRect   : 1536x912   ← 크기까지 정상
    제목            : '설정'
    DWMWA_CLOAKED   : 2          ← 실제로는 **가려져 있다**

그래서 `IsWindowVisible`만 보던 코드가 **없는 창을 있다고 셌고**, 포커스는
«성공»했고, `open_app`은 «앞으로 가져왔습니다»라고 답했다.

⚠️ 이 스위트는 **Windows API를 실제로 부른다**(mock이 아니다). 유령 창은 mock으로
   만들 수 없고, 만들 수 있었다면 애초에 이 결함도 없었을 것이다.
"""
import _testenv  # noqa: F401
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    passed += bool(cond)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}{('  ' + detail) if detail and not cond else ''}")


from tools.app_control import (is_window_cloaked, _is_real_window, _await_window,
                               _launched_or_honest, find_hwnd_for_app,
                               _window_class, _SHELL_WINDOW_CLASSES)

# ── ① cloaked 판정이 안전한가 ──────────────────────────────────────
print("=== ① cloaked 판정 — 실패해도 죽지 않는다 ===")
# ⚠️ 판정에 실패하면 **False(가려지지 않음)** 로 봐야 한다. 판정 실패 때문에
#    멀쩡한 창을 «없다»고 하면 그게 더 나쁘다.
check("잘못된 hwnd(0)에도 예외를 내지 않는다", is_window_cloaked(0) in (True, False))
check("말도 안 되는 hwnd에도 예외를 내지 않는다",
      is_window_cloaked(0x7FFFFFFF) in (True, False))
check("hwnd 0은 «진짜 창»이 아니다", _is_real_window(0) is False)

# ── ② 없는 창을 기다리면 정직하게 실패한다 ─────────────────────────
print("=== ② 없는 창을 기다리면 0을 돌려준다 ===")
import time as _t
t0 = _t.monotonic()
h = _await_window("__존재하지않는앱__", timeout=0.8)
el = _t.monotonic() - t0
check("없는 앱 → 0", h == 0)
check("타임아웃을 지킨다(무한 대기 아님)", el < 3.0, f"→ {el:.1f}초")

print("=== ② 못 열었으면 «열었다»고 하지 않는다 ===")
msg = _launched_or_honest("__존재하지않는앱__", "가짜앱", "을(를)", timeout=0.3)
check("✓ 로 시작하지 않는다", not msg.startswith("✓"), f"→ {msg}")
check("무슨 일인지 말한다", "나타나지 않았어요" in msg, f"→ {msg}")  # 🔄 2026-09-23 — 말투를 해요체로 통일했다(2-2 ⓐ). **소스 문구를 그대로** 적는다.

# ── ③ 유령 창을 «있는 창»으로 세지 않는다 ──────────────────────────
# 🚨 이 검사가 이 파일의 존재 이유다.
print("=== ③ 유령(cloaked) 창을 창으로 세지 않는다 ===")
import ctypes
import ctypes.wintypes as w

u = ctypes.windll.user32
ghosts, reals, shells = [], [], []


def _scan(hwnd, _):
    if not u.IsWindowVisible(hwnd):
        return True
    n = u.GetWindowTextLengthW(hwnd)
    if not n:
        return True
    # 🆕 2026-09-19 — **셸 창을 따로 센다.** 예전엔 «cloaked 가 아니면 진짜 창»이었는데,
    #   그 기준으로는 **바탕화면(`Progman`)이 «진짜 탐색기 창»** 이 된다.
    #   실기에서 *"탐색기 최대화해줘"* 가 바탕화면을 집고 `✓` 라고 답했다.
    if _window_class(hwnd) in _SHELL_WINDOW_CLASSES:
        shells.append(hwnd)
    elif is_window_cloaked(hwnd):
        ghosts.append(hwnd)
    else:
        reals.append(hwnd)
    return True


P = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
u.EnumWindows(P(_scan), 0)
print(f"    (이 PC: IsWindowVisible=True인 제목 있는 창 "
      f"{len(ghosts) + len(reals) + len(shells)}개 — 유령 {len(ghosts)} · 셸 {len(shells)})")

check("유령 창은 _is_real_window가 False로 본다",
      all(not _is_real_window(h) for h in ghosts))
check("진짜 창은 _is_real_window가 True로 본다",
      all(_is_real_window(h) for h in reals))
# 🆕 2026-09-19 라이브 점검이 잡은 것 — 바탕화면·작업표시줄은 «앱 창»이 아니다.
#   `explorer.exe` 가 파일 탐색기와 **바탕화면을 같이** 띄우기 때문에,
#   이걸 안 거르면 «탐색기»를 찾을 때 바탕화면이 먼저 걸린다.
check("🆕 셸 창(바탕화면·작업표시줄)은 _is_real_window가 False로 본다",
      all(not _is_real_window(h) for h in shells),
      f"→ 셸 창 {len(shells)}개")
if not shells:
    print("    ⚠️ 셸 창을 하나도 못 봤다 — «확인 못 함»이다(보통 Progman이 하나는 있다).")
# ⚠️ 유령이 0개인 PC(설정을 한 번도 안 연 상태 등)에서도 스위트는 통과해야 한다 —
#   위 두 검사는 빈 목록이면 자동으로 참이다. 그건 «못 봤다»이지 «없다»가 아니다.
if not ghosts:
    print("    ⚠️ 지금 이 PC엔 유령 창이 없다 — ③은 «확인 못 함»이지 «통과»가 아니다.")
    print("       재현: 설정을 열었다 닫고 잠시 뒤 다시 돌린다.")

# ── ④ find_hwnd_for_app이 유령을 돌려주지 않는다 ───────────────────
print("=== ④ find_hwnd_for_app은 유령을 돌려주지 않는다 ===")
# 프로세스 매칭 경로와 **제목 폴백 경로** 둘 다 걸러야 한다 —
# 2026-09-09에는 폴백이 유령 `ApplicationFrameWindow`(제목 '설정')를 집었다.
for app in ["설정", "계산기", "메모장", "크롬"]:
    hh = find_hwnd_for_app(app)
    check(f"'{app}' → 유령이 아니다", hh == 0 or _is_real_window(hh),
          f"→ hwnd={hh}")

print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
