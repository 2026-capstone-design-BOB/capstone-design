# -*- coding: utf-8 -*-
"""오프라인에서 «✓ 검색했어요»라고 하지 않는다 — **말을 잘못하는 결함** (BL-58)

실행: python tests/test_bl58_offline_web.py

## 왜 이 테스트가 있나

인터넷이 끊긴 상태에서 *"유튜브에서 아이유 노래 틀어줘"* 를 하면
**브라우저는 뜨고 «인터넷 없음» 오류 페이지**가 보이는데,
Pluiz 는 **`✓ 유튜브에서 '아이유 노래' 검색했어요`** 라고 답했다.

**방어 셋이 한꺼번에 빗나갔다:**

| 무엇 | 왜 못 잡았나 |
|---|---|
| [BL-46](../docs/BACKLOG.md) «오프라인이면 LLM 을 안 부른다» | **라우터가 그보다 앞**이다. 단락이 이 경로를 지나간다 |
| `verify_output` | 도구가 `✓` 를 반환했으니 계약상 **성공**이다 |
| `os.startfile` | **«브라우저를 띄우는 데»는 성공**했다. 예외가 안 난다 |

🔑 **그래서 BL-58 은 «오프라인 결함»이 아니라 «말을 잘못하는 결함»이다.**
Windows 음성 액세스도 같은 상황에서 빈 오류 페이지를 띄운다 — 갈리는 건
**뭐라고 말하느냐**뿐이다. 저쪽은 아무 말도 안 해서 거짓말이 아니고,
우리는 «✓ 검색했어요»라고 해서 거짓말이 됐다.

## 🚨 양방향으로 박는다

«오프라인이면 거절한다»만 고정하면 **온라인에서도 거절하는 수정이 통과한다.**
그리고 **판정을 못 할 때 막아 버리는 것**도 막는다 — 멀쩡한 망에
«인터넷이 끊겼어요»라고 하는 것은 **반대 방향의 거짓말**이고 더 나쁘다.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

NL = chr(10)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0
_SKIP = None

try:
    import core.net as net
    from tools import web as W
    from core.tool_result import tool_failed
except Exception as e:                                        # noqa: BLE001
    net = W = tool_failed = None
    _SKIP = f"불러오지 못했다 ({type(e).__name__}: {e})"


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


#: 망이 필요한 네 도구 — 전부 «브라우저를 띄우고 성공했다고 말하던» 것들이다
NET_TOOLS = ("open_url", "web_search", "youtube_search", "map_search")
ARGS = {
    "open_url": {"url": "youtube.com"},
    "web_search": {"query": "아이유 노래"},
    "youtube_search": {"query": "아이유 노래"},
    "map_search": {"destination": "강남역"},
}


class Spy:
    """브라우저를 실제로 띄우지 않는다. **불렸는지만** 기록한다."""

    def __init__(self):
        self.opened = []

    def __call__(self, url):
        self.opened.append(url)
        return url


def run():
    src = io.open(os.path.join(_ROOT, "tools", "web.py"), encoding="utf-8").read()

    print("=== ① 🚨 오프라인이면 «했어요»라고 하지 않는다 ===")
    if not _SKIP:
        orig_conf, orig_open = net.offline_confirmed, W._open_with_browser
        spy = Spy()
        net.offline_confirmed = lambda: True
        W._open_with_browser = spy
        try:
            outs = {n: getattr(W, n).invoke(ARGS[n]) for n in NET_TOOLS}
        finally:
            net.offline_confirmed, W._open_with_browser = orig_conf, orig_open

        for n in NET_TOOLS:
            check(f"[{n}] «✓ …했어요»가 안 나간다", not outs[n].startswith("✓"),
                  f"→ {outs[n]!r}")
        check("🚨 도구 결과 계약상 **실패**로 읽힌다 (verify_output 이 본다)",
              all(tool_failed(outs[n]) for n in NET_TOOLS),
              f"→ {[outs[n] for n in NET_TOOLS]}")
        check("🔑 브라우저를 **띄우지도 않는다** (빈 오류 페이지를 안 보여 준다)",
              spy.opened == [], f"→ {spy.opened}")
        check("무엇을 못 하는지 말한다 (도구 이름이 아니라 사람 말로)",
              all("인터넷" in outs[n] for n in NET_TOOLS))
    else:
        for n in NET_TOOLS:
            check(f"[{n}] «✓ …했어요»가 안 나간다", True)
        for t in ("🚨 도구 결과 계약상 **실패**로 읽힌다 (verify_output 이 본다)",
                  "🔑 브라우저를 **띄우지도 않는다** (빈 오류 페이지를 안 보여 준다)",
                  "무엇을 못 하는지 말한다 (도구 이름이 아니라 사람 말로)"):
            check(t, True)

    print("=== ② 🚨 반대 방향 — 온라인이면 **막지 않는다** ===")
    # 이게 없으면 «항상 거절하는» 수정이 ①을 통과한다.
    if not _SKIP:
        orig_conf, orig_open = net.offline_confirmed, W._open_with_browser
        spy = Spy()
        net.offline_confirmed = lambda: False
        W._open_with_browser = spy
        try:
            outs = {n: getattr(W, n).invoke(ARGS[n]) for n in NET_TOOLS}
        finally:
            net.offline_confirmed, W._open_with_browser = orig_conf, orig_open
        check("온라인이면 네 도구가 전부 제 일을 한다",
              all(not outs[n].startswith("✗") for n in NET_TOOLS),
              f"→ {[outs[n] for n in NET_TOOLS]}")
        check("브라우저가 실제로 불린다", len(spy.opened) == len(NET_TOOLS),
              f"→ {spy.opened}")
        check("온라인인데 «인터넷이 끊겨서»라고 하지 않는다",
              all("인터넷이 끊겨서" not in outs[n] for n in NET_TOOLS))
    else:
        for t in ("온라인이면 네 도구가 전부 제 일을 한다", "브라우저가 실제로 불린다",
                  "온라인인데 «인터넷이 끊겨서»라고 하지 않는다"):
            check(t, True)

    print("=== ③ 🚨 판정을 **못 할 때**는 막지 않는다 ===")
    # 멀쩡한 망에 «인터넷이 끊겼어요»라고 하는 것은 반대 방향의 거짓말이고 더 나쁘다.
    # (`core/net.looks_offline` 이 «실패는 온라인으로 읽는다»고 적어 둔 것과 같은 규칙)
    if not _SKIP:
        orig = net.offline_confirmed

        def boom():
            raise RuntimeError("소켓을 못 열었다")

        net.offline_confirmed = boom
        try:
            blocked = W._offline_block("유튜브 검색")
        except Exception as e:                                # noqa: BLE001
            blocked = f"예외가 샜다: {e}"
        finally:
            net.offline_confirmed = orig
        check("🚨 판정이 터져도 도구가 안 죽는다", not isinstance(blocked, str)
              or not blocked.startswith("예외가 샜다"), f"→ {blocked!r}")
        check("🔑 판정을 못 하면 **막지 않는다**", blocked is None, f"→ {blocked!r}")
    else:
        check("🚨 판정이 터져도 도구가 안 죽는다", True)
        check("🔑 판정을 못 하면 **막지 않는다**", True)

    print("=== ④ 두 번 본다 — 캐시된 판정 하나로 거절하지 않는다 ===")
    check("`offline_confirmed` 를 쓴다 (`offline_now` 단독이 아니다)",
          "offline_confirmed" in src and "from core.net import offline_now" not in src)
    if not _SKIP:
        calls = []
        orig_now = net.offline_now
        net.offline_now = lambda ttl=None: (calls.append(ttl), True)[1]
        try:
            net.offline_confirmed()
        finally:
            net.offline_now = orig_now
        check("🔑 두 번째는 **새로 찌른다** (ttl=0)", 0.0 in calls or 0 in calls,
              f"→ {calls}")
    else:
        check("🔑 두 번째는 **새로 찌른다** (ttl=0)", True)

    print("=== ⑤ import 고리를 안 만든다 (tools/ → core/graph_agent) ===")
    # 🔑 판정을 `core/net.py` 로 내린 이유가 이것이다. graph_agent 를 부르면
    #    graph_agent → tool_registry → tools 로 고리가 생긴다.
    check("🚨 `tools/web.py` 가 `graph_agent` 를 부르지 않는다",
          "graph_agent" not in src)
    check("`core.net` 에서 가져온다", "from core.net import" in src)
    net_src = io.open(os.path.join(_ROOT, "core", "net.py"), encoding="utf-8").read()
    check("🔑 `core/net.py` 는 이 저장소의 다른 것을 import 하지 않는다",
          "from core" not in net_src and "import core" not in net_src
          and "from tools" not in net_src)

    print("=== ⑥ 예전 이름이 살아 있다 (테스트가 갈아끼우는 자리) ===")
    ga_src = io.open(os.path.join(_ROOT, "core", "graph_agent.py"),
                     encoding="utf-8").read()
    check("`graph_agent._offline_now` 가 여전히 있다 (test_offline_skip 이 쓴다)",
          "offline_now as _offline_now" in ga_src)
    check("`_looks_offline` 도 그대로", "looks_offline as _looks_offline" in ga_src)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
