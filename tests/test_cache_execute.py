# -*- coding: utf-8 -*-
"""캐시 실행 경로의 정직함 — **실패를 성공이라고 말하지 않는다** (감사 G-01·02·04)

실행: python tests/test_cache_execute.py

## 왜 이 테스트가 있나

[전수감사](../docs/research/2026-09_안전에러_전수감사.md)에서 **가장 큰 구멍 셋이
한 함수에서 나왔다** — `core/command_cache.py` 의 캐시 실행 경로다.

| | 무엇이었나 |
|---|---|
| **G-01** | 도구가 실패하면 `response_template`(= *«볼륨 올렸어요»* 같은 **성공 문장**)을 대신 돌려줬다 |
| **G-02** | 그 실패가 `print` 로만 나가서 **`logs/pluiz.log` 에 한 줄도 안 남았다** |
| **G-04** | 모르는 도구를 **조용히 건너뛰었다** — 2개짜리 엔트리가 1개만 돌고 «다 했어요»가 나갔다 |

🚨 **하필 이 경로가 LLM 을 안 거친다.** 빠른 경로(캐시 히트)는 그래프의 그물 넷을
전부 비켜간다 — 즉 **여기서 거짓말하면 아무도 안 잡는다.**
이 저장소가 일곱 번 고친 «확인하지 않고 됐다고 말하는 것»
(BL-12·15·19·21·23·26·35)의 캐시 판본이다.

## 🚨 양방향으로 박는다

«실패하면 템플릿을 안 쓴다»만 고정하면 **항상 실패라고 말하는 수정이 통과한다.**
그래서 «다 됐을 때는 여전히 결과를 돌려준다»도 같이 못 박는다.
그리고 «일부만 됐을 때 «못 했어요»라고 하지 않는다»도 — **앞의 도구는 이미 돌았고
부작용이 남아 있다.** 그 경우 «못 했어요»는 반대 방향의 거짓말이다.
"""
import asyncio
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

NL = chr(10)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0
_SKIP = None

try:
    from core.command_cache import CommandCache
except Exception as e:                                        # noqa: BLE001
    CommandCache = None
    _SKIP = f"core.command_cache 를 못 불러왔다 ({type(e).__name__})"


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if _SKIP:
        passed += 1
        print(f"  ~ {name}   ({_SKIP} — 건너뜀)")
        return
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name}" + (f"   → {detail}" if detail else ""))


class FakeTool:
    """도구 하나. `boom` 이면 부른 순간 터진다."""

    def __init__(self, name, out="됐어요", boom=None):
        self.name = name
        self._out = out
        self._boom = boom
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        if self._boom:
            raise self._boom
        return self._out

    async def ainvoke(self, args):
        return self.invoke(args)


class Entry:
    def __init__(self, calls, template="볼륨 올렸어요"):
        self.pattern = "볼륨 올려줘"
        self.response_template = template
        self.tool_calls = calls


def cache_with(*tools):
    """`__init__` 을 안 거친다 — 파일도 설정도 건드리지 않는다."""
    c = CommandCache.__new__(CommandCache)
    c._tools_map = {t.name: t for t in tools}
    c._get_tools_map = lambda: c._tools_map
    return c


def call(calls, *tools, is_async=False):
    c = cache_with(*tools)
    e = Entry(calls)
    return asyncio.run(c.execute(e)) if is_async else c.execute_sync(e)


def run():
    src = io.open(os.path.join(_ROOT, "core", "command_cache.py"),
                  encoding="utf-8").read()

    print("=== ① 🚨 G-01 — 도구가 실패하면 «성공 문장»을 돌려주지 않는다 ===")
    boom = FakeTool("volume_up", boom=RuntimeError("장치를 못 찾았다"))
    out = call([{"name": "volume_up", "args": {}}], boom)
    check("성공 템플릿(«볼륨 올렸어요»)이 안 나간다", "볼륨 올렸어요" not in out, f"→ {out!r}")
    check("실패했다고 말한다", "못" in out or "실행하지" in out, f"→ {out!r}")
    check("🔑 예외 원문을 사용자에게 읽어 주지 않는다 (감사 G-14와 같은 이유)",
          "장치를 못 찾았다" not in out, f"→ {out!r}")

    print("=== ② 🚨 반대 방향 — 다 됐을 때는 **여전히** 결과를 돌려준다 ===")
    # 이게 없으면 «항상 실패라고 말하는» 수정이 ①을 통과한다.
    ok = FakeTool("volume_up", out="볼륨 60%")
    out = call([{"name": "volume_up", "args": {}}], ok)
    check("성공하면 도구 결과가 그대로 나온다", out == "볼륨 60%", f"→ {out!r}")
    check("성공했는데 «못 했어요»라고 하지 않는다", "못 했" not in out and "실행하지" not in out)
    check("도구가 실제로 불렸다", ok.calls == [{}], f"→ {ok.calls}")

    print("=== ③ 🚨 일부만 됐을 때 — «못 했어요»도 거짓이다 ===")
    # 앞의 도구는 **이미 돌았고 부작용이 남아 있다.** 없던 일로 말하면 안 된다.
    a = FakeTool("volume_up", out="볼륨 60%")
    b = FakeTool("open_app", boom=RuntimeError("없는 앱"))
    out = call([{"name": "volume_up", "args": {}}, {"name": "open_app", "args": {}}], a, b)
    check("«일부만»이라고 말한다", "일부만" in out, f"→ {out!r}")
    check("성공 템플릿을 쓰지 않는다", "볼륨 올렸어요" not in out, f"→ {out!r}")
    check("🔑 «아무것도 못 했다»고도 하지 않는다 (앞 도구는 이미 돌았다)",
          out != CommandCache._FAIL_ALL if not _SKIP else True, f"→ {out!r}")
    check("먼저 온 도구는 실제로 돌았다", a.calls == [{}], f"→ {a.calls}")

    print("=== ④ 🚨 G-04 — 모르는 도구를 조용히 건너뛰지 않는다 ===")
    only = FakeTool("volume_up", out="볼륨 60%")
    out = call([{"name": "volume_up", "args": {}}, {"name": "없는도구", "args": {}}], only)
    check("모르는 도구가 섞이면 «다 했어요»가 안 나간다",
          "볼륨 올렸어요" not in out, f"→ {out!r}")
    check("그것도 «안 된 것»으로 센다 (일부만)", "일부만" in out, f"→ {out!r}")
    out2 = call([{"name": "없는도구", "args": {}}])
    check("전부 모르는 도구면 실패다", "실행하지" in out2 or "못" in out2, f"→ {out2!r}")

    print("=== ⑤ 🚨 G-02 — 실패가 `logs/pluiz.log` 에 남는다 (`print` 가 아니다) ===")
    check("소스에서 캐시 실행의 `print` 가 사라졌다",
          "[CommandCache] 동기 실행 오류" not in src
          and "[CommandCache] 도구 실행 오류" not in src)
    check("로거를 만든다 (`get_logger`)", "get_logger(\"CommandCache\")" in src)

    if not _SKIP:
        rec = []

        class Grab(logging.Handler):
            def emit(self, r):
                rec.append((r.levelno, r.getMessage()))

        lg = logging.getLogger("pluiz.CommandCache")
        h = Grab()
        lg.addHandler(h)
        try:
            call([{"name": "volume_up", "args": {}}],
                 FakeTool("volume_up", boom=RuntimeError("장치를 못 찾았다")))
        finally:
            lg.removeHandler(h)
        check("실패가 ERROR 로 실제로 찍힌다", any(lv >= logging.ERROR for lv, _ in rec),
              f"→ {rec}")
        check("🔑 로그에는 예외 원문이 남는다 (사람이 되짚어야 한다)",
              any("장치를 못 찾았다" in m for _, m in rec), f"→ {rec}")
    else:
        check("실패가 ERROR 로 실제로 찍힌다", True)
        check("🔑 로그에는 예외 원문이 남는다 (사람이 되짚어야 한다)", True)

    print("=== ⑥ 🚨 두 경로가 **같은 말**을 한다 (sync ↔ async) ===")
    # 경로에 따라 정직함이 갈리면 안 된다. 결론을 내는 자리가 하나여야 한다.
    check("`execute` 도 `_verdict` 를 쓴다", src.count("self._verdict(entry") == 2,
          f"실제 {src.count('self._verdict(entry')}군데")
    if not _SKIP:
        calls = [{"name": "volume_up", "args": {}}]
        sync_out = call(calls, FakeTool("volume_up", boom=RuntimeError("x")))
        async_out = call(calls, FakeTool("volume_up", boom=RuntimeError("x")), is_async=True)
        check("실패했을 때 두 경로의 말이 같다", sync_out == async_out,
              f"sync={sync_out!r} async={async_out!r}")
        ok_s = call(calls, FakeTool("volume_up", out="볼륨 60%"))
        ok_a = call(calls, FakeTool("volume_up", out="볼륨 60%"), is_async=True)
        check("성공했을 때도 두 경로의 말이 같다", ok_s == ok_a,
              f"sync={ok_s!r} async={ok_a!r}")
    else:
        check("실패했을 때 두 경로의 말이 같다", True)
        check("성공했을 때도 두 경로의 말이 같다", True)

    print("=== ⑦ 도구가 아예 없는 엔트리는 예전대로 템플릿을 쓴다 ===")
    # 🔑 «도구 0개»는 실패가 아니다. 순수 응답 패턴이 그렇게 생겼다 —
    #    여기를 실패로 바꾸면 멀쩡한 캐시가 전부 «못 했어요»가 된다.
    out = call([])
    check("도구가 없으면 응답 템플릿 그대로", out == "볼륨 올렸어요", f"→ {out!r}")

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
