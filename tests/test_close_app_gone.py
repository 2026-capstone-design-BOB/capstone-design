# -*- coding: utf-8 -*-
"""닫는 쪽도 **본 대로 말한다** — `force_close_app` 의 종료 확인 (감사 G-07 · G-19)

실행: python tests/test_close_app_gone.py

## 왜 이 테스트가 있나

[전수 감사](../docs/research/2026-09_안전에러_전수감사.md)의 **G-07**:

```python
proc.terminate()
killed.append(proc.info["name"])     # ← 요청을 «결과»로 적었다
…
if killed:
    return f"✓ {name}{eul_reul} 종료했습니다."
```

🚨 **`terminate()` 는 요청이지 결과가 아니다.** 프로세스가 안 죽어도 «종료했습니다»가
나갔다. 이 저장소가 **여덟 번** 고친 결함군(BL-12·15·19·21·23·26·35 + 감사 G-01)과
같은 모양이고, 하필 **여는 쪽은 이미 고쳐져 있었다** — 2026-09-09에 `_await_window()`
가 *«창이 떴는지 본다»* 를 만들었는데(BL-26) **그 대칭인 `_await_gone()` 은 없었다.**

> 🔑 **«확인하지 않고 의도를 보고한다»가 이 저장소의 재발 결함이다.**
> 매번 «그 도구 하나»를 고쳤고, 그래서 **다음 도구에서 또 났다.**

## 🚨 양방향으로 박는다

«안 닫혔으면 ✓ 를 안 쓴다»만 고정하면 **항상 ⚠️ 라고 말하는 수정이 통과한다.**
그래서 «정말 닫혔으면 여전히 ✓ 라고 한다»를 같이 못 박는다.
그리고 **«실행 중이지 않습니다»가 거짓이 되는 자리**도 본다 — 권한이 없어 종료를
요청조차 못 하면, 예전 코드는 «안 켜져 있다»고 답했다. **켜져 있는데도.**

## 🔄 2026-09-23 — **주소가 옮겨졌다.** 이 스위트의 대상은 `force_close_app` 이다

G-19를 닫으면서 `close_app` 이 **`terminate()` 를 더는 부르지 않는다.** 이제
`WM_CLOSE` 로 곱게 닫고, 강제 종료는 **이름이 다른 도구**(`force_close_app`)로 갈라져
승인을 지난다. → docs/design/G-05-19_승인의_경계.md §4-2

🔑 **그래서 아래 검사를 지우지 않고 `force_close_app` 으로 겨눈다.** G-07이 잡은 결함
(«요청을 결과로 적는다»)은 도구 이름이 바뀌었을 뿐 **그대로 살아 있고**, 지우면
새 도구에서 같은 결함이 처음부터 다시 난다 — 이 저장소가 «복사본 둘»로 반복해 데인 모양이다.

📌 **`close_app` 의 새 계약**(WM_CLOSE 를 보낸다 · 남았으면 ✓ 를 안 쓴다 · 창을 못 찾으면
강제로 끄지 않는다)은 `tests/test_approval_boundary.py` 계약 4가 잡는다.

## ✅ 고치지 않았던 절반 — 감사 G-19, 2026-09-23에 닫혔다

`terminate()` 는 Windows 에서 `TerminateProcess` 라 **저장 대화상자를 띄우지 않는다.**
저장 안 한 메모장 내용이 승인 한 번 없이 사라졌다. **«언제 강제로 꺼도 되나»는
값 판단**이라(G-05와 같은 성질) 결정이 먼저였고, ADR 이 그 결정을 했다 —
**저장 대화상자가 곧 승인이다.** 우리가 승인을 만든 게 아니라 `terminate()` 가
**OS 의 승인을 억누르고 있었다.** §6이 그 상태를 못 박는다.
"""
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeProc:
    """프로세스 하나. `deny` 면 종료 요청이 거부되고, `stubborn` 이면 안 죽는다."""

    def __init__(self, name="notepad.exe", pid=1, deny=False, stubborn=False):
        self.info = {"name": name, "pid": pid}
        self.pid = pid
        self.deny = deny
        self.stubborn = stubborn
        self.alive = True
        self.asked = False

    def terminate(self):
        self.asked = True
        if self.deny:
            raise PermissionError("액세스가 거부되었습니다")
        if not self.stubborn:
            self.alive = False

    def is_running(self):
        return self.alive


class FakePsutil:
    """`process_iter` / `wait_procs` 만 갖는 최소 psutil."""

    def __init__(self, procs, wait_boom=None):
        self._procs = procs
        self._wait_boom = wait_boom
        self.waited = []

    def process_iter(self, attrs=None):
        return list(self._procs)

    def wait_procs(self, procs, timeout=None):
        self.waited.append(timeout)
        if self._wait_boom:
            raise self._wait_boom
        gone = [p for p in procs if not p.alive]
        alive = [p for p in procs if p.alive]
        return gone, alive


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
        from tools import app_control
        has_mod = True
    except Exception as e:                                    # noqa: BLE001
        app_control = None
        has_mod = False
        _why = f"{type(e).__name__}: {e}"

    src = io.open(os.path.join(_ROOT, "tools", "app_control.py"),
                  encoding="utf-8").read()

    def close(*procs, wait_boom=None, app="메모장"):
        """가짜 psutil 로 갈아끼우고 `force_close_app` 을 돌린다. 원래 것은 되돌린다.

        🔄 2026-09-23 — 겨누는 도구가 `close_app` → `force_close_app` 으로 바뀌었다.
          `terminate()` 가 그쪽으로 옮겨 갔기 때문이다(머리말 참조).
        """
        fake = FakePsutil(list(procs), wait_boom=wait_boom)
        saved = app_control.psutil
        app_control.psutil = fake
        try:
            return app_control.force_close_app.invoke({"app": app}), fake
        finally:
            app_control.psutil = saved

    # ── §1 정말 닫혔을 때만 ✓ ──────────────────────────────────────
    print("\n§1 ✓ 는 «확인된 것»에만 쓴다")
    if not has_mod:
        cannot_judge(["정말 닫히면 ✓ 라고 한다",
                      "🚨 안 닫히면 ✓ 를 쓰지 않는다",
                      "안 닫혔을 때 «닫았다»는 말이 안 들어간다",
                      "안 닫혔으면 무엇을 하라고 알려 준다",
                      "종료를 실제로 요청했다"],
                     f"tools.app_control 를 못 불러왔다 ({_why}) — `pluiz` 환경이 필요하다")
    else:
        out, fake = close(FakeProc())
        check("정말 닫히면 ✓ 라고 한다", out.startswith("✓") and "종료했습니다" in out,
              f"→ {out!r}")
        check("종료를 실제로 요청했다", fake._procs[0].asked)

        stubborn = FakeProc(stubborn=True)
        out, _ = close(stubborn)
        check("🚨 안 닫히면 ✓ 를 쓰지 않는다", not out.startswith("✓"), f"→ {out!r}")
        check("안 닫혔을 때 «닫았다/종료했습니다»는 말이 안 들어간다",
              "종료했습니다" not in out and "닫았어요" not in out, f"→ {out!r}")
        check("안 닫혔으면 무엇을 하라고 알려 준다",
              "직접" in out or "확인" in out, f"→ {out!r}")

    # ── §2 계약 마커 ──────────────────────────────────────────────
    #
    # 🔑 마커는 장식이 아니라 **코드가 파싱하는 계약**이다(BL-29). ⚠️ 는
    #   «도구는 돌았지만 목적이 달성되지 않았다» = **실패 쪽**이다. 그래서
    #   캐시 학습도, T04 보정도, 이 문장을 제대로 읽는다.
    print("\n§2 결과 계약 — ⚠️ 로 말한다 (실패 쪽으로 읽혀야 한다)")
    if not has_mod:
        cannot_judge(["안 닫힌 결과가 `tool_failed()` 로 실패다",
                      "닫힌 결과는 실패가 아니다"],
                     "tools.app_control 를 못 불러왔다")
    else:
        from core.tool_result import tool_failed
        out, _ = close(FakeProc(stubborn=True))
        check("안 닫힌 결과가 `tool_failed()` 로 실패다", tool_failed(out), f"→ {out!r}")
        ok, _ = close(FakeProc())
        check("닫힌 결과는 실패가 아니다", not tool_failed(ok), f"→ {ok!r}")

    # ── §3 «실행 중이지 않습니다»가 거짓이 되는 자리 ───────────────
    print("\n§3 🚨 켜져 있는데 «실행 중이지 않습니다»라고 하지 않는다")
    if not has_mod:
        cannot_judge(["권한이 없어 못 껐을 때 «안 켜져 있다»고 하지 않는다",
                      "그 실패가 로그에 남는다 (`except: pass` 가 아니다)",
                      "정말 없을 때는 ✗ «실행 중이지 않습니다»"],
                     "tools.app_control 를 못 불러왔다")
    else:
        lg = logging.getLogger("pluiz.AppControl")
        h = Grab()
        lg.addHandler(h)
        try:
            out, _ = close(FakeProc(deny=True))
        finally:
            lg.removeHandler(h)
        check("권한이 없어 못 껐을 때 «안 켜져 있다»고 하지 않는다",
              "실행 중이지 않" not in out, f"→ {out!r}")
        check("그 실패가 로그에 남는다 (`except: pass` 가 아니다)",
              any(lv >= logging.ERROR for lv, _ in h.rec), f"→ {h.rec}")
        out2, _ = close()          # 아무것도 안 걸린다
        check("정말 없을 때는 ✗ «실행 중이지 않습니다»",
              out2.startswith("✗") and "실행 중이지 않" in out2, f"→ {out2!r}")

    # ── §4 일부만 닫혔을 때 ───────────────────────────────────────
    print("\n§4 일부만 닫혔을 때 — 양쪽 다 거짓말이 될 수 있다")
    if not has_mod:
        cannot_judge(["일부만 닫히면 ✓ 가 아니다",
                      "«완전히 닫지 못했다»고 말한다",
                      "🔑 개수를 말하지 않는다 (사용자가 보는 건 창, 우리가 센 건 프로세스)"],
                     "tools.app_control 를 못 불러왔다")
    else:
        out, _ = close(FakeProc(pid=1), FakeProc(pid=2, stubborn=True))
        check("일부만 닫히면 ✓ 가 아니다", not out.startswith("✓"), f"→ {out!r}")
        check("«완전히 닫지 못했다»고 말한다", "완전히" in out or "일부" in out, f"→ {out!r}")
        # 🔑 BL-55 와 같은 함정 — 크롬은 창 하나에 프로세스가 여럿이다.
        check("🔑 개수를 말하지 않는다 (창 ↔ 프로세스)",
              "1개" not in out and "2개" not in out, f"→ {out!r}")

    # ── §5 모르면 «닫혔다»고 하지 않는다 ──────────────────────────
    print("\n§5 확인에 실패하면 살아 있는 쪽으로 센다")
    if not has_mod:
        cannot_judge(["확인이 터져도 ✓ 라고 하지 않는다",
                      "확인이 터져도 실제로 죽은 것은 죽은 것으로 센다"],
                     "tools.app_control 를 못 불러왔다")
    else:
        out, _ = close(FakeProc(stubborn=True), wait_boom=RuntimeError("못 기다렸다"))
        check("확인이 터져도 ✓ 라고 하지 않는다", not out.startswith("✓"), f"→ {out!r}")
        ok, _ = close(FakeProc(), wait_boom=RuntimeError("못 기다렸다"))
        check("확인이 터져도 실제로 죽은 것은 죽은 것으로 센다 («안 닫혔다»도 거짓이다)",
              ok.startswith("✓"), f"→ {ok!r}")

    # ── §6 구조 — 요청을 결과라고 적지 않는다 ─────────────────────
    #
    # 🔑 §1~§5는 «오늘 그렇게 말한다»를 본다. 여기는 **그 말의 근거가 측정인지**를 본다.
    print("\n§6 구조 — `terminate()` 뒤에 반드시 확인이 있다")
    body = src[src.index("def force_close_app"):]
    # 🔑 주석은 떼고 본다 — 옛 이름(`killed`)이 **왜 결함이었는지**는 주석에 남아
    #   있어야 하고, 남아 있으면 안 되는 것은 **코드**다.
    code_only = chr(10).join(ln.split("#", 1)[0] for ln in body.splitlines())
    check("`force_close_app` 이 `_await_gone` 을 부른다", "_await_gone(" in code_only)
    check("🚨 `terminate()` 결과를 «닫힌 것»으로 세지 않는다 (`killed` 가 사라졌다)",
          "killed" not in code_only, "요청을 결과로 적는 이름이 코드에 남아 있다")
    check("여는 쪽의 대칭이라는 근거가 적혀 있다",
          "_await_window" in src and "G-07" in src)
    check("G-19 를 닫은 근거가 코드에 적혀 있다", "G-19" in src)
    # ── 🔑 G-19 가 실제로 닫혔는가 — **양방향으로** 본다.
    #   «close_app 이 terminate 를 안 부른다»만 보면 «아무도 못 끄는» 수정이 통과한다.
    close_body = src[src.index("def close_app("):src.index("def force_close_app(")]
    close_code = chr(10).join(ln.split("#", 1)[0] for ln in close_body.splitlines())
    check("🚨 `close_app` 이 `terminate()` 를 **안** 부른다 (G-19)",
          ".terminate()" not in close_code)
    check("🔑 그래도 끌 길은 남아 있다 — `force_close_app` 이 부른다",
          ".terminate()" in code_only)
    check("둘이 **다른 도구**다 (force 인자가 아니다 · 절대규칙 9)",
          "def close_app(app: str) -> str:" in src
          and "def force_close_app(app: str) -> str:" in src)

    # ── §7 탐색기는 예전 그대로 ───────────────────────────────────
    #
    # ⚠️ 여기를 건드리면 바탕화면·작업표시줄이 통째로 사라진다 (BUG-11).
    print("\n§7 탐색기 보호는 그대로다 (BUG-11)")
    if not has_mod:
        cannot_judge(["탐색기는 종료를 시도조차 하지 않는다"],
                     "tools.app_control 를 못 불러왔다")
    else:
        out, fake = close(FakeProc(name="explorer.exe"), app="탐색기")
        check("탐색기는 종료를 시도조차 하지 않는다",
              not fake._procs[0].asked and "시스템 프로세스" in out, f"→ {out!r}")

    if skipped:
        print(f"\n결과: {passed}/{total} · 🚨 판정 불가 {skipped}건 — 초록이 아니다")
        print("   종료 확인을 다 못 쟀다. `conda activate pluiz` 로 다시 돌릴 것")
    else:
        print(f"\n결과: {passed}/{total} 통과")
    return passed == total and skipped == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
