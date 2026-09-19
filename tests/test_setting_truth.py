# -*- coding: utf-8 -*-
"""설정 도구가 **되읽고 말한다** · 여는 도구가 **열렸는지 본다** (감사 G-11·G-17)

실행: python tests/test_setting_truth.py

## 왜 이 테스트가 있나

[전수 감사](../docs/research/2026-09_안전에러_전수감사.md)의 **G-11**과 **G-17**은
이 저장소가 아홉 번 고친 한 문장의 또 다른 판본이다 —
**«결과를 확인하지 않고 의도를 보고한다».**

| | 무엇이었나 |
|---|---|
| **G-11** | 볼륨·밝기가 실행 **전** 값만 읽고 `✓ 볼륨: 40% → 50%` 라고 했다. **뒤의 50%는 의도다.** 설정이 실패해도(pycaw 없음 · WMI 거부 · PowerShell 폴백 실패) 같은 문장이 나갔다 |
| **G-17** | 브라우저 열기 폴백이 `subprocess.Popen` 이라 **셸만 뜨면** 돌아왔다. 브라우저가 안 떠도 `✓ … 열었습니다` 였다 |

🔑 **볼륨·밝기는 «되읽기가 싼» 몇 안 되는 자리다.** [BL-47](../docs/BACKLOG.md)이 `wmi` 를
깔아 이 PC를 «읽을 수 있는 PC»로 만들어 놨다. 그런데도 안 읽고 있었다.

## 🚨 양방향으로 박는다 — 세 방향이다

1. «안 맞았으면 ✓ 를 안 쓴다»만 고정하면 **항상 ⚠️ 라고 말하는 수정**이 통과한다
   → §1이 «맞았으면 여전히 ✓ 와 읽은 값»을 못 박는다.
2. 🚨 **«못 읽는 PC»를 실패로 만들면 안 된다.** ⚠️/✗ 로 답하면 그 PC에서 볼륨 명령이
   통째로 실패가 되어 [캐시 학습](../core/command_cache.py)에서 빠지고 매번 LLM 을 탄다.
   **모르는 것은 실패가 아니다** → §1-③이 `tool_failed()` 로 그 방향을 막는다.
3. 되읽은 값과 설정값이 **조금 다른 것**(장치가 단계로 반올림)은 실패가 아니다
   → 허용 오차를 상수로 두고 §1-④가 그 경계를 본다.
"""
import io
import logging
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeCtypes:
    """`keybd_event` 를 **실제로 누르지 않는다.** 누르면 이 PC의 소리가 바뀐다."""

    def __init__(self):
        self.keys = []
        outer = self

        class _User32:
            def keybd_event(self, vk, a, b, c):
                outer.keys.append(vk)

        class _Windll:
            user32 = _User32()

        self.windll = _Windll()


class FakeRun:
    """`subprocess.run` 대역. 종료코드와 stderr 를 마음대로 준다."""

    def __init__(self, returncode=0, stderr=b"", boom=None):
        self.returncode = returncode
        self.stderr = stderr
        self.boom = boom
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        if self.boom:
            raise self.boom
        return types.SimpleNamespace(returncode=self.returncode, stderr=self.stderr,
                                     stdout=b"")


class Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rec = []

    def emit(self, r):
        self.rec.append((r.levelno, r.getMessage()))


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
        from tools import system as sysmod
        from tools import web as webmod
        from core.tool_result import tool_failed
        has_mod = True
    except Exception as e:                                    # noqa: BLE001
        sysmod = webmod = tool_failed = None
        has_mod = False
        _why = f"{type(e).__name__}: {e}"

    sys_src = io.open(os.path.join(_ROOT, "tools", "system.py"), encoding="utf-8").read()
    web_src = io.open(os.path.join(_ROOT, "tools", "web.py"), encoding="utf-8").read()

    def with_patch(**attrs):
        """모듈 전역을 잠깐 갈아끼운다. 끝나면 반드시 되돌린다."""
        class _Ctx:
            def __enter__(self):
                self.saved = {}
                for mod, kv in attrs.items():
                    m = sysmod if mod == "sys_" else webmod
                    for k, v in kv.items():
                        self.saved[(m, k)] = getattr(m, k, None)
                        setattr(m, k, v)
                return self

            def __exit__(self, *a):
                for (m, k), v in self.saved.items():
                    setattr(m, k, v)
        return _Ctx()

    # ── §1 볼륨 — 말하는 값이 **읽은 값**이다 ────────────────────────
    print("\n§1 볼륨 — ✓ 뒤의 숫자는 «의도»가 아니라 «읽은 값»이다")
    if not has_mod:
        cannot_judge(
            ["① 맞았으면 읽은 값으로 말한다",
             "② 🚨 안 맞았으면 ✓ 를 안 쓴다",
             "② 무엇이 어긋났는지 말한다",
             "③ 🚨 «못 읽는 PC»는 실패가 아니다",
             "③ 그래도 ✓ 를 유지한다 (캐시 학습에서 빠지지 않는다)",
             "④ 장치가 1~2% 반올림하는 것은 실패가 아니다"],
            f"tools 를 못 불러왔다 ({_why}) — `conda activate pluiz` 로 다시 돌릴 것")
    else:
        reads = iter([40, 50])
        with with_patch(sys_={"_get_volume": lambda: next(reads),
                              "_set_volume_level": lambda lv: True}):
            out = sysmod.volume_up.invoke({"amount": 10})
        check("① 맞았으면 읽은 값으로 말한다", out == "✓ 볼륨: 40% → 50%", f"→ {out!r}")

        reads = iter([40, 40])           # 설정이 안 먹었다
        with with_patch(sys_={"_get_volume": lambda: next(reads),
                              "_set_volume_level": lambda lv: True}):
            out = sysmod.volume_up.invoke({"amount": 10})
        check("② 🚨 안 맞았으면 ✓ 를 안 쓴다", not out.startswith("✓"), f"→ {out!r}")
        check("② 무엇이 어긋났는지 말한다", "50%" in out and "40%" in out, f"→ {out!r}")

        reads = iter([40, -1])           # 설정 뒤 읽기가 안 된다
        with with_patch(sys_={"_get_volume": lambda: next(reads),
                              "_set_volume_level": lambda lv: True}):
            out = sysmod.volume_up.invoke({"amount": 10})
        check("③ 🚨 «못 읽는 PC»는 실패가 아니다", not tool_failed(out), f"→ {out!r}")
        check("③ 그래도 ✓ 를 유지한다 (캐시 학습에서 빠지지 않는다)",
              out.startswith("✓") and "확인" in out, f"→ {out!r}")

        reads = iter([40, 49])           # 장치가 반올림했다
        with with_patch(sys_={"_get_volume": lambda: next(reads),
                              "_set_volume_level": lambda lv: True}):
            out = sysmod.volume_up.invoke({"amount": 10})
        check("④ 장치가 1~2% 반올림하는 것은 실패가 아니다",
              out.startswith("✓") and "49%" in out, f"→ {out!r}")

    # ── §2 `set_volume` — 예전엔 되읽기가 **아예 없었다** ───────────
    print("\n§2 볼륨 지정 — 여기는 되읽기가 아예 없었다")
    if not has_mod:
        cannot_judge(["설정이 안 먹으면 «설정했습니다»라고 하지 않는다",
                      "먹었으면 그대로 ✓"],
                     "tools 를 못 불러왔다")
    else:
        reads = iter([70, 70])
        with with_patch(sys_={"_get_volume": lambda: next(reads),
                              "_set_volume_level": lambda lv: True}):
            out = sysmod.set_volume.invoke({"level": 30})
        check("설정이 안 먹으면 «설정했습니다»라고 하지 않는다",
              not out.startswith("✓"), f"→ {out!r}")
        reads = iter([70, 30])
        with with_patch(sys_={"_get_volume": lambda: next(reads),
                              "_set_volume_level": lambda lv: True}):
            out = sysmod.set_volume.invoke({"level": 30})
        check("먹었으면 그대로 ✓", out.startswith("✓") and "30%" in out, f"→ {out!r}")

    # ── §3 음소거 — «전환했습니다»도 의도였다 ──────────────────────
    print("\n§3 음소거 — «켰다»와 «껐다»는 반대말이다")
    if not has_mod:
        cannot_judge(["껐다 켜지면 «음소거했어요»", "켰다 꺼지면 «해제했어요»",
                      "🚨 상태가 그대로면 그렇게 말한다", "못 읽으면 ✓ 를 유지한다",
                      "키를 실제로 눌렀다"],
                     "tools 를 못 불러왔다")
    else:
        fake_ct = FakeCtypes()
        states = iter([0, 1])
        with with_patch(sys_={"_get_mute": lambda: next(states), "ctypes": fake_ct}):
            out = sysmod.mute_toggle.invoke({})
        check("껐다 켜지면 «음소거했어요»", out == "✓ 음소거했어요.", f"→ {out!r}")
        check("키를 실제로 눌렀다", fake_ct.keys == [0xAD, 0xAD], f"→ {fake_ct.keys}")

        states = iter([1, 0])
        with with_patch(sys_={"_get_mute": lambda: next(states), "ctypes": FakeCtypes()}):
            out = sysmod.mute_toggle.invoke({})
        check("켰다 꺼지면 «해제했어요»", out == "✓ 음소거를 해제했어요.", f"→ {out!r}")

        states = iter([1, 1])
        with with_patch(sys_={"_get_mute": lambda: next(states), "ctypes": FakeCtypes()}):
            out = sysmod.mute_toggle.invoke({})
        check("🚨 상태가 그대로면 그렇게 말한다",
              not out.startswith("✓") and "그대로" in out, f"→ {out!r}")

        states = iter([-1, -1])
        with with_patch(sys_={"_get_mute": lambda: next(states), "ctypes": FakeCtypes()}):
            out = sysmod.mute_toggle.invoke({})
        check("못 읽으면 ✓ 를 유지한다 (모르는 것은 실패가 아니다)",
              out.startswith("✓") and not tool_failed(out), f"→ {out!r}")

    # ── §4 밝기 — PowerShell 폴백의 **종료코드**를 본다 ─────────────
    #
    # 🔑 종료코드만 보면 모자란다. PowerShell 은 **비종료 오류**(개체가 null 이라
    #   메서드를 못 부르는 경우)에도 0 으로 끝나는데, 그게 이 폴백의 흔한 실패 모양이다.
    print("\n§4 밝기 — 폴백이 정말 먹었는지 본다")
    if not has_mod:
        cannot_judge(["폴백이 실패하면 False", "🔑 종료코드 0이어도 stderr 가 있으면 실패",
                      "성공하면 True", "🚨 실패하면 «마지막 값»으로 기억하지 않는다",
                      "설정이 실패하면 «바꾸지 못했어요»", "되읽어서 맞으면 ✓"],
                     "tools 를 못 불러왔다")
    else:
        dead_wmi = types.ModuleType("wmi")

        def _boom(*a, **kw):
            raise RuntimeError("WMI 를 못 쓴다")
        dead_wmi.WMI = _boom
        saved_wmi = sys.modules.get("wmi")
        sys.modules["wmi"] = dead_wmi
        try:
            before = sysmod._last_brightness
            fail = FakeRun(returncode=1, stderr=b"no instance")
            with with_patch(sys_={"subprocess": types.SimpleNamespace(run=fail)}):
                ok = sysmod._set_brightness(60)
            check("폴백이 실패하면 False", ok is False, f"→ {ok!r}")
            check("🚨 실패하면 «마지막 값»으로 기억하지 않는다",
                  sysmod._last_brightness == before,
                  f"→ {before!r} → {sysmod._last_brightness!r}")

            soft = FakeRun(returncode=0, stderr=b"Get-WmiObject : ... null")
            with with_patch(sys_={"subprocess": types.SimpleNamespace(run=soft)}):
                ok = sysmod._set_brightness(60)
            check("🔑 종료코드 0이어도 stderr 가 있으면 실패다", ok is False, f"→ {ok!r}")

            good = FakeRun(returncode=0, stderr=b"")
            with with_patch(sys_={"subprocess": types.SimpleNamespace(run=good)}):
                ok = sysmod._set_brightness(60)
            check("성공하면 True", ok is True, f"→ {ok!r}")
        finally:
            if saved_wmi is None:
                sys.modules.pop("wmi", None)
            else:
                sys.modules["wmi"] = saved_wmi

        with with_patch(sys_={"_get_brightness": lambda: 40,
                              "_set_brightness": lambda lv: False}):
            out = sysmod.brightness_up.invoke({"amount": 10})
        check("설정이 실패하면 «바꾸지 못했어요»",
              not out.startswith("✓") and "못" in out, f"→ {out!r}")

        reads = iter([40, 50])
        with with_patch(sys_={"_get_brightness": lambda: next(reads),
                              "_set_brightness": lambda lv: True}):
            out = sysmod.brightness_up.invoke({"amount": 10})
        check("되읽어서 맞으면 ✓", out == "✓ 밝기: 40% → 50%", f"→ {out!r}")

    # ── §5 브라우저 — 셸만 떠도 «열었습니다»였다 (G-17) ─────────────
    print("\n§5 브라우저 열기 — 셸이 뜬 것과 브라우저가 뜬 것은 다르다")
    if not has_mod:
        cannot_judge(["폴백이 실패하면 열기가 실패로 나간다",
                      "폴백이 성공하면 ✓",
                      "🔑 첫 인자를 비운 `start \"\" \"url\"` 형태로 부른다",
                      "평소 경로(os.startfile)면 셸을 아예 안 부른다",
                      "그 실패가 로그에 남는다"],
                     "tools 를 못 불러왔다")
    else:
        def _startfile_boom(u):
            raise OSError("연결된 프로그램이 없습니다")

        lg = logging.getLogger("pluiz.Web")
        h = Grab()
        lg.addHandler(h)
        try:
            fail = FakeRun(returncode=1, stderr="'start' 실패".encode("utf-8"))
            with with_patch(web_={"os": types.SimpleNamespace(startfile=_startfile_boom),
                                  "subprocess": types.SimpleNamespace(run=fail)}):
                out = webmod.open_url.invoke({"url": "https://example.com"})
            check("폴백이 실패하면 열기가 실패로 나간다",
                  tool_failed(out) and "열었습니다" not in out, f"→ {out!r}")
            cmd = fail.calls[0][0][0] if fail.calls else ""
            check("🔑 첫 인자를 비운 `start \"\" \"url\"` 형태로 부른다",
                  cmd.startswith('start "" "https://example.com"'), f"→ {cmd!r}")
        finally:
            lg.removeHandler(h)
        check("그 실패가 로그에 남는다",
              any(lv >= logging.ERROR for lv, _ in h.rec), f"→ {h.rec}")

        good = FakeRun(returncode=0)
        with with_patch(web_={"os": types.SimpleNamespace(startfile=_startfile_boom),
                              "subprocess": types.SimpleNamespace(run=good)}):
            out = webmod.open_url.invoke({"url": "https://example.com"})
        check("폴백이 성공하면 ✓", out.startswith("✓"), f"→ {out!r}")

        opened = []
        never = FakeRun(returncode=0)
        with with_patch(web_={"os": types.SimpleNamespace(startfile=opened.append),
                              "subprocess": types.SimpleNamespace(run=never)}):
            out = webmod.open_url.invoke({"url": "https://example.com"})
        check("평소 경로(os.startfile)면 셸을 아예 안 부른다",
              opened == ["https://example.com"] and not never.calls,
              f"→ {opened} · 셸 {len(never.calls)}회")

    # ── §5-B 🚨 COM — **서버에서는 지금까지 한 번도 못 읽었다** ──────────
    #
    # 2026-09-19 라이브 점검에서 잡혔다. 로그가 원인을 **이름으로** 말해 줬다:
    #   `x_wmi_uninitialised_thread: … without first calling pythoncom.CoInitialize[Ex]`
    # 그래프는 도구를 `asyncio.to_thread` 로 **워커 스레드**에서 돌리는데, COM 은
    # **스레드마다** 켜야 한다. 그래서 진단 스크립트(메인 스레드)에서는 읽히고
    # 서버에서는 -1 이었다 — 🔑 **BL-47 의 안 착륙한 절반이다.**
    print(chr(10) + "§5-B COM — 워커 스레드에서도 읽혀야 한다 (BL-47의 나머지 절반)")
    if not has_mod:
        cannot_judge(["읽기 전에 COM 을 켠다", "스레드당 한 번만 켠다",
                      "🔑 초기화가 실패해도 죽지 않는다",
                      "세 자리가 전부 COM 을 켠다"],
                     "tools 를 못 불러왔다")
    else:
        calls = []

        class _Ole:
            def CoInitializeEx(self, a, b):
                calls.append(b)
                return 0

        fake_ct = FakeCtypes()
        fake_ct.windll.ole32 = _Ole()
        dead = types.ModuleType("wmi")
        dead.WMI = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no wmi"))
        saved = sys.modules.get("wmi")
        sys.modules["wmi"] = dead
        try:
            sysmod._com_ready = types.SimpleNamespace()       # 이 «스레드»를 새로 본다
            with with_patch(sys_={"ctypes": fake_ct}):
                sysmod._get_brightness()
                sysmod._get_brightness()
        finally:
            if saved is None:
                sys.modules.pop("wmi", None)
            else:
                sys.modules["wmi"] = saved
        check("읽기 전에 COM 을 켠다", len(calls) >= 1, f"→ {calls}")
        check("스레드당 한 번만 켠다 (두 번 불러도 한 번)", len(calls) == 1, f"→ {calls}")

        boom_ct = FakeCtypes()

        class _Boom:
            def CoInitializeEx(self, a, b):
                raise OSError("COM 없음")
        boom_ct.windll.ole32 = _Boom()
        sysmod._com_ready = types.SimpleNamespace()
        with with_patch(sys_={"ctypes": boom_ct}):
            got = sysmod._ensure_com()
        check("🔑 초기화가 실패해도 죽지 않는다 (읽기가 -1 이 될 뿐)", got is None)
        sysmod._com_ready = types.SimpleNamespace()           # 원래대로 돌려 둔다

    check("세 자리가 전부 COM 을 켠다 (볼륨 읽기·밝기 읽기·밝기 쓰기)",
          sys_src.count("_ensure_com()") >= 4, f"→ {sys_src.count('_ensure_com()')}군데")

    # ── §6 구조 — 고친 자리가 그대로 있는지 ────────────────────────
    print("\n§6 구조 — 다음 사람이 되돌리지 못하게")
    # 🔑 «왜 Popen 이면 안 되는지»는 docstring 에 남아 있어야 한다. 남으면 안 되는
    #   것은 **부르는 것**이라 호출 형태(`Popen(`)로 본다.
    check("🚨 브라우저 폴백이 `Popen` 을 부르지 않는다 (셸만 보고 돌아오던 자리)",
          "Popen(" not in web_src, "`Popen(` 호출이 다시 들어왔다")
    check("볼륨·밝기가 한 자리(`_readback`)에서 판정한다",
          sys_src.count("_readback(") >= 4)
    check("허용 오차가 상수로 있다 (숫자를 흩뿌리지 않는다)",
          "_SETTING_TOLERANCE" in sys_src)
    check("근거가 코드에 적혀 있다 (감사 G-11·G-17)",
          "G-11" in sys_src and "G-17" in web_src)

    if skipped:
        print(f"\n결과: {passed}/{total} · 🚨 판정 불가 {skipped}건 — 초록이 아니다")
        print("   설정 도구의 정직함을 다 못 쟀다. `conda activate pluiz` 로 다시 돌릴 것")
    else:
        print(f"\n결과: {passed}/{total} 통과")
    return passed == total and skipped == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
