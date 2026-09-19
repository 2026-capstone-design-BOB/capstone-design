# -*- coding: utf-8 -*-
"""**어느 창에 했는지** 보고 말한다 — 창 상태 · 키 입력 (감사 G-08·G-09)

실행: python tests/test_window_key_truth.py

## 왜 이 테스트가 있나

두 결함이 **같은 뿌리**다 — *«어느 창인지 확인하지 않고 «했다»고 말한다».*

| | 무엇이었나 |
|---|---|
| **G-08** | 최대화·최소화가 `IsWindowVisible` 만 봤다. **유령(cloaked) 창이 그 검사를 통과한다** — 정지된 UWP(설정·계산기)에 «최대화해줘» 하면 아무 일도 없이 `✓` 가 나갔다. `ShowWindow` 결과도 안 봤다 |
| **G-09** | `press_key` 에 **`target` 인자가 아예 없었다.** 어디로 가는지 모르고 눌렀고, 어느 창에 갔는지 **말하지도 않았다**(`type_text` 는 말한다) |

🚨 **둘 다 이미 고쳐 둔 수선을 못 받은 자리다.**
`is_window_cloaked()` 는 [BL-26](../docs/BACKLOG.md)에서 만들어 놓고 **두 함수에 안 붙였고**,
`_ensure_target_focused()` 는 [BL-12](../docs/BACKLOG.md)에서 `type_text` 에만 붙였다.
*«그 도구 하나»를 고치면 **다음 도구에서 또 난다**.*

> ⚠️ **`ShowWindow` 의 반환값은 «성공»이 아니다** — «이전에 보이는 창이었나»다.
> 감사는 *«반환값도 안 본다»* 라고 적었지만 반환값을 봐도 답이 안 나온다.
> 진짜 답은 **창에 되묻는 것**이다: `IsZoomed` · `IsIconic`.

## 🚨 양방향으로 박는다

- «안 됐으면 ✓ 를 안 쓴다»만 고정하면 **항상 ⚠️ 라고 말하는 수정**이 통과한다 → §1이 막는다.
- 🔴 **`target` 을 필수로 만들면 안 된다.** *"엔터 눌러줘"* 처럼 «지금 이 창»이 맞는
  경우가 실제로 많고, 필수로 하면 그 평범한 명령이 **전부 막힌다** → §5-③이 막는다.
"""
import io
import logging
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Holder:
    """`ctypes.c_void_p` · `wintypes.DWORD` 대역 — `.value` 만 있으면 된다."""

    def __init__(self, v=0):
        self.value = v


class FakeCtypes:
    """창 목록을 들고 있는 가짜 Windows API. **실제 창을 건드리지 않는다.**"""

    def __init__(self, windows=None, titles=None, zoomed=None, iconic=None,
                 foreground=0):
        self.windows = windows or {}          # {hwnd: pid}
        self.titles = titles or {}            # {hwnd: 제목}
        self.zoomed = zoomed or {}
        self.iconic = iconic or {}
        self.foreground = foreground
        self.shown = []                       # (hwnd, cmd) 기록
        outer = self

        class _User32:
            def EnumWindows(self, proc, lparam):
                for h in list(outer.windows) + [h for h in outer.titles
                                                if h not in outer.windows]:
                    if proc(h, 0) is False:
                        break
                return 1

            def GetWindowThreadProcessId(self, h, ref):
                ref.value = outer.windows.get(h, 0)
                return 1

            def ShowWindow(self, h, cmd):
                outer.shown.append((h, cmd))
                return 1

            def GetForegroundWindow(self):
                return outer.foreground

            def IsZoomed(self, h):
                return 1 if outer.zoomed.get(h) else 0

            def IsIconic(self, h):
                return 1 if outer.iconic.get(h) else 0

            def IsWindowVisible(self, h):
                return 1

            def GetWindowTextW(self, h, buf, n):
                buf.value = outer.titles.get(h, "")
                return len(buf.value)

        class _Windll:
            user32 = _User32()

        self.windll = _Windll()
        self.wintypes = types.SimpleNamespace(DWORD=_Holder, HWND=int, LPARAM=int)

    # ── ctypes 모듈 흉내 ──────────────────────────────────────
    c_void_p = _Holder
    c_int = _Holder
    c_bool = bool

    @staticmethod
    def byref(x):
        return x

    @staticmethod
    def WINFUNCTYPE(*a):
        return lambda cb: cb

    @staticmethod
    def create_unicode_buffer(n):
        return _Holder("")


class FakePsutil:
    def __init__(self, procs):
        self._procs = procs               # [(name, pid)]

    def process_iter(self, attrs=None):
        return [types.SimpleNamespace(info={"name": n, "pid": p})
                for n, p in self._procs]


class FakeAuto:
    """`pyautogui` 대역. **실제로 키를 누르지 않는다.**"""

    def __init__(self):
        self.hotkeys = []
        self.presses = []

    def hotkey(self, *parts):
        self.hotkeys.append(parts)

    def press(self, key):
        self.presses.append(key)


def run():
    passed = total = skipped = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}"
              + ("" if cond or not detail else f"   → {detail}"))

    def cannot_judge(names, why):
        """못 잰 것을 **세어서** 남긴다 — 건너뛴 것은 통과가 아니다 (BL-59)."""
        nonlocal skipped
        for n in names:
            skipped += 1
            print(f"  ⬜ 판정 불가 {n}")
        print(f"     └ {why}")

    try:
        from tools import app_control as ac
        from tools import input_control as ic
        from core.tool_result import tool_failed
        has_mod = True
    except Exception as e:                                    # noqa: BLE001
        ac = ic = tool_failed = None
        has_mod = False
        _why = f"{type(e).__name__}: {e}"

    ac_src = io.open(os.path.join(_ROOT, "tools", "app_control.py"),
                     encoding="utf-8").read()
    ic_src = io.open(os.path.join(_ROOT, "tools", "input_control.py"),
                     encoding="utf-8").read()

    def patch(mod, **kv):
        class _Ctx:
            def __enter__(self):
                self.saved = {k: getattr(mod, k, None) for k in kv}
                for k, v in kv.items():
                    setattr(mod, k, v)
                return self

            def __exit__(self, *a):
                for k, v in self.saved.items():
                    setattr(mod, k, v)
        return _Ctx()

    # ── §1 창 상태 — 바꾸고 **되묻는다** ───────────────────────────
    print("\n§1 최대화·최소화 — `ShowWindow` 를 부른 것과 «됐다»는 다른 말이다")
    if not has_mod:
        cannot_judge(["정말 최대화되면 ✓", "🚨 안 됐으면 ✓ 를 안 쓴다",
                      "안 됐을 때 무엇을 하라고 말한다", "최소화도 같은 자리를 쓴다",
                      "실제로 `ShowWindow` 를 불렀다"],
                     f"tools 를 못 불러왔다 ({_why}) — `conda activate pluiz` 로 다시 돌릴 것")
    else:
        fc = FakeCtypes(zoomed={101: True})
        with patch(ac, ctypes=fc, _find_app_window=lambda k, a: (101, True)):
            out = ac.maximize_window.invoke({"app": "메모장"})
        check("정말 최대화되면 ✓", out.startswith("✓") and "최대화" in out, f"→ {out!r}")
        check("실제로 `ShowWindow` 를 불렀다", fc.shown == [(101, ac._SW_MAXIMIZE)],
              f"→ {fc.shown}")

        fc = FakeCtypes()                       # 상태가 안 바뀐다 (유령 창 모양)
        with patch(ac, ctypes=fc, _find_app_window=lambda k, a: (101, True)):
            out = ac.maximize_window.invoke({"app": "설정"})
        check("🚨 안 됐으면 ✓ 를 안 쓴다", not out.startswith("✓"), f"→ {out!r}")
        check("안 됐을 때 무엇이 문제인지 말한다", "응답" in out or "못" in out, f"→ {out!r}")

        fc = FakeCtypes(iconic={202: True})
        with patch(ac, ctypes=fc, _find_app_window=lambda k, a: (202, True)):
            out = ac.minimize_window.invoke({"app": "크롬"})
        check("최소화도 같은 자리를 쓴다 (상태를 되묻는다)",
              out.startswith("✓") and fc.shown == [(202, ac._SW_MINIMIZE)], f"→ {out!r}")

    # ── §2 실행 중이 아닌 것과 «창이 없는 것»은 다르다 ─────────────
    print("\n§2 «안 켜져 있다»와 «창이 없다»는 다른 말이다 (P3-3 정직 보고)")
    if not has_mod:
        cannot_judge(["프로세스가 없으면 «실행 중이 아니다»",
                      "프로세스는 있는데 창이 없으면 그렇게 말한다",
                      "창이 없을 때 `ShowWindow` 를 부르지 않는다"],
                     "tools 를 못 불러왔다")
    else:
        fc = FakeCtypes()
        with patch(ac, ctypes=fc, _find_app_window=lambda k, a: (0, False)):
            out = ac.maximize_window.invoke({"app": "메모장"})
        check("프로세스가 없으면 «실행 중이 아니다»",
              "실행 중이지 않" in out, f"→ {out!r}")

        fc = FakeCtypes()
        with patch(ac, ctypes=fc, _find_app_window=lambda k, a: (0, True)):
            out = ac.maximize_window.invoke({"app": "크롬"})
        check("프로세스는 있는데 창이 없으면 그렇게 말한다",
              "열려 있는 창이 없" in out, f"→ {out!r}")
        check("창이 없을 때 `ShowWindow` 를 부르지 않는다", fc.shown == [], f"→ {fc.shown}")

    # ── §3 🚨 유령 창을 «창»으로 세지 않는다 (G-08 본체) ────────────
    print("\n§3 🚨 유령(cloaked) 창을 창으로 세지 않는다")
    if not has_mod:
        cannot_judge(["유령 창은 후보에서 빠진다",
                      "진짜 창은 그대로 찾는다",
                      "🔑 `IsWindowVisible` 이 아니라 `_is_real_window` 를 쓴다"],
                     "tools 를 못 불러왔다")
    else:
        # hwnd 301 = 유령 · 302 = 진짜. 둘 다 같은 프로세스(pid 9)다.
        fc = FakeCtypes(windows={301: 9, 302: 9})
        with patch(ac, ctypes=fc, psutil=FakePsutil([("notepad.exe", 9)]),
                   _is_real_window=lambda h: h != 301):
            hwnd, running = ac._find_app_window("notepad", "메모장")
        check("유령 창은 후보에서 빠진다", hwnd == 302, f"→ hwnd={hwnd}")
        check("진짜 창은 그대로 찾는다", running is True and hwnd != 0, f"→ {hwnd}")

        fc = FakeCtypes(windows={301: 9}, titles={301: "설정"})
        with patch(ac, ctypes=fc, psutil=FakePsutil([("notepad.exe", 9)]),
                   _is_real_window=lambda h: False,
                   _find_hwnd_by_title=lambda kws: 0):
            hwnd, running = ac._find_app_window("notepad", "메모장")
        check("🚨 전부 유령이면 «창이 없다»가 된다 (예전엔 유령을 집었다)",
              hwnd == 0 and running is True, f"→ hwnd={hwnd} running={running}")

    # ── §4 구조 — 복사본 둘을 한 자리로 모았다 ─────────────────────
    #
    # 🔑 예전엔 `maximize_window` 와 `minimize_window` 가 **같은 코드 두 벌**이었다.
    #   그래서 같은 구멍이 둘 다에 있었다. 한 벌로 만들어야 다음 수선이 **둘 다에** 닿는다.
    print("\n§4 구조 — 같은 결함이 두 벌로 있지 않게")
    body = ac_src[ac_src.index("def _change_window_state"):]
    check("창 상태 판정이 한 함수(`_change_window_state`)로 모였다",
          ac_src.count("def _change_window_state") == 1)
    check("두 도구가 그 함수만 부른다",
          ac_src.count("_change_window_state(app,") == 2, "복사본이 남아 있다")
    check("🔑 `ShowWindow` 뒤에 상태를 되묻는다 (`IsZoomed`/`IsIconic`)",
          "IsZoomed" in ac_src and "IsIconic" in ac_src)
    check("근거가 코드에 적혀 있다 (감사 G-08)", "G-08" in ac_src)

    # ── §5 키 입력 — 어디로 가는지 보고 말한다 (G-09) ──────────────
    print("\n§5 키 입력 — `type_text` 가 받은 수선을 `press_key` 도 받는다")
    if not has_mod:
        cannot_judge(["① 대상 창을 확인 못 하면 **누르지 않는다**",
                      "① 그때 «키를 누르지 않았다»고 말한다",
                      "② 확인되면 누른다",
                      "③ 🔴 target 없이도 평범한 명령은 그대로 된다",
                      "④ 어느 창에서 눌렸는지 말한다",
                      "⑤ 단축키와 단일 키가 갈린다"],
                     "tools 를 못 불러왔다")
    else:
        auto = FakeAuto()
        deny = (False, "✗ '메모장' 창을 앞으로 가져오지 못해 입력하지 않았습니다. "
                       "지금 앞에 있는 건 '크롬' 창이라서, 그대로 입력하면 거기에 "
                       "글자가 들어갔을 거예요.")
        with patch(ic, _get_pyautogui=lambda: auto,
                   _ensure_target_focused=lambda t: deny,
                   _foreground_window=lambda: (1, "크롬")):
            out = ic.press_key.invoke({"key": "ctrl+s", "target": "메모장"})
        check("① 대상 창을 확인 못 하면 **누르지 않는다**",
              auto.hotkeys == [] and auto.presses == [], f"→ {auto.hotkeys}{auto.presses}")
        check("① 그때 «키를 누르지 않았다»고 말한다",
              tool_failed(out) and "키를 누르지 않았습니다" in out, f"→ {out!r}")

        auto = FakeAuto()
        with patch(ic, _get_pyautogui=lambda: auto,
                   _ensure_target_focused=lambda t: (True, ""),
                   _foreground_window=lambda: (1, "메모장")):
            out = ic.press_key.invoke({"key": "ctrl+s", "target": "메모장"})
        check("② 확인되면 누른다", auto.hotkeys == [("ctrl", "s")], f"→ {auto.hotkeys}")
        check("④ 어느 창에서 눌렸는지 말한다",
              "메모장" in out and out.startswith("✓"), f"→ {out!r}")

        # 🔴 여기가 반대 방향이다 — target 을 필수로 만드는 수정을 막는다.
        auto = FakeAuto()
        called = []
        with patch(ic, _get_pyautogui=lambda: auto,
                   _ensure_target_focused=lambda t: called.append(t) or (True, ""),
                   _foreground_window=lambda: (1, "메모장")):
            out = ic.press_key.invoke({"key": "엔터"})
        check("③ 🔴 target 없이도 평범한 명령은 그대로 된다",
              out.startswith("✓") and auto.presses == ["enter"], f"→ {out!r}")
        check("③ target 이 없으면 창 확인을 **부르지도 않는다**", called == [], f"→ {called}")

        auto = FakeAuto()
        with patch(ic, _get_pyautogui=lambda: auto,
                   _foreground_window=lambda: (0, "")):
            ic.press_key.invoke({"key": "f5"})
        check("⑤ 단축키와 단일 키가 갈린다",
              auto.presses == ["f5"] and auto.hotkeys == [], f"→ {auto.presses}")

    # ── §6 구조 — 계약이 코드에 남아 있다 ──────────────────────────
    print("\n§6 구조 — 다음 사람이 되돌리지 못하게")
    sig = ic_src[ic_src.index("def press_key("):ic_src.index("def press_key(") + 80]
    check("`press_key` 가 `target` 을 받는다", "target" in sig, f"→ {sig!r}")
    # 🚨 절대규칙 9와 같은 자리 — 좌표를 받으면 LLM 이 언젠가 지어낸다.
    check("🚨 그래도 **좌표 인자는 없다** (절대규칙 9)",
          " x:" not in sig and " y:" not in sig, f"→ {sig!r}")
    check("포커스 확인이 두 도구에서 **같은 함수**를 쓴다",
          ic_src.count("_ensure_target_focused(") >= 3)
    check("포커스 실패가 `print` 가 아니라 로그로 간다",
          "[type_text] 포커스 시도 실패" not in ic_src and "get_logger(\"Input\")" in ic_src)
    check("근거가 코드에 적혀 있다 (감사 G-09)", "G-09" in ic_src)

    if skipped:
        print(f"\n결과: {passed}/{total} · 🚨 판정 불가 {skipped}건 — 초록이 아니다")
        print("   창·키의 정직함을 다 못 쟀다. `conda activate pluiz` 로 다시 돌릴 것")
    else:
        print(f"\n결과: {passed}/{total} 통과")
    return passed == total and skipped == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
