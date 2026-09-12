"""BL-46 — 오프라인이면 **LLM을 아예 부르지 않는다**.

배경: docs/design/BL-46_오프라인_LLM_생략.md

3차 실기에서 오프라인 실패 턴이 **8.0초**였다. 인터넷이 끊긴 걸 턴 시작에
이미 알면서도 LLM을 부르고 상한까지 기다렸기 때문이다.

🚨 **이 테스트는 양방향이다.** «안 부른다»만 고정하면 **오프라인에서 되던
캐시 명령까지 죽이는 수정**이 통과해 버린다. 이 기능의 전부를 잃는 방향이
바로 그쪽이라, 아래 ②가 ①보다 중요하다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

from core.graph import OfflineSkip, build_pluiz_graph  # noqa: E402

passed = total = 0


def check(name, cond, extra=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {extra}")


class CountingLLM:
    """몇 번 불렸는지 세는 LLM. **0이어야 한다**가 이 테스트의 요지다."""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        return AIMessage(content="LLM이 답했다")


@tool
def noop_tool(x: str = "") -> str:
    """테스트용 도구."""
    return "✓ 했다"


def make(is_offline, fast_resolve=None):
    llm = CountingLLM()
    g = build_pluiz_graph(
        llm=llm,
        tools=[noop_tool],
        security_check=lambda t: (False, ""),
        fast_resolve=fast_resolve,
        is_offline=is_offline,
    )
    return llm, g


def run(g, text, thread="t1"):
    return g.invoke({"messages": [HumanMessage(content=text)]},
                    {"configurable": {"thread_id": thread}})


# ── ① 오프라인 + 캐시 미스 → LLM을 한 번도 안 부른다 ──────────────────
print("=== ① 오프라인 · 캐시 미스 → LLM 0회 ===")
llm, g = make(is_offline=lambda: True, fast_resolve=lambda t: None)
raised = False
try:
    run(g, "오늘 저녁 뭐 먹지")
except OfflineSkip:
    raised = True
except Exception as e:                      # LangGraph가 감쌌을 수도 있다
    raised = isinstance(getattr(e, "__cause__", None), OfflineSkip) or \
        "OfflineSkip" in f"{type(e).__name__}{e}"
check("OfflineSkip이 올라온다", raised)
check("LLM 호출 0회", llm.calls == 0, f"실제 {llm.calls}회")


# ── ② 🚨 오프라인이어도 **캐시 히트는 그대로 돈다** ────────────────────
#    이 방향이 더 중요하다 — 여길 깨면 «오프라인 실행»이라는 기능 자체가 사라진다.
print("=== ② 오프라인 · 캐시 히트 → 평소대로 (단락이 캐시를 안 먹는다) ===")
llm, g = make(is_offline=lambda: True,
              fast_resolve=lambda t: "✓ 메모장을 실행했습니다." if "메모장" in t else None)
ok = True
try:
    out = run(g, "메모장 열어줘", thread="t2")
except Exception as e:
    ok = False
    out = f"예외: {type(e).__name__}"
check("예외 없이 끝난다", ok, str(out))
check("캐시 응답이 나온다",
      ok and any("메모장을 실행" in getattr(m, "content", "") for m in out["messages"]),
      str(out)[:120] if ok else "")
check("캐시 히트에는 LLM을 안 부른다", llm.calls == 0, f"실제 {llm.calls}회")


# ── ③ 온라인이면 단락이 안 걸린다 ──────────────────────────────────────
print("=== ③ 온라인 → LLM을 정상 호출 ===")
llm, g = make(is_offline=lambda: False, fast_resolve=lambda t: None)
out = run(g, "오늘 저녁 뭐 먹지", thread="t3")
check("LLM 호출 1회 이상", llm.calls >= 1, f"실제 {llm.calls}회")


# ── ④ is_offline을 안 주면 **오늘과 똑같다** (mock 기본값 호환) ────────
print("=== ④ is_offline 미주입 → 기존 동작 그대로 ===")
llm, g = make(is_offline=None, fast_resolve=lambda t: None)
out = run(g, "오늘 저녁 뭐 먹지", thread="t4")
check("LLM 호출 1회 이상", llm.calls >= 1, f"실제 {llm.calls}회")


# ── ⑤ 거짓 «오프라인»이 턴을 죽이지 않는다 (BL-46 §3-1) ────────────────
#
# `_offline_confirmed()`는 **두 번** 묻는다: TTL 캐시가 «오프라인»이라고 해도
# 캐시 없는 재확인이 «온라인»이면 **LLM을 부른다.** 10초 전에 끊겼다가 방금
# 복구된 네트워크에 대고 "인터넷이 없어요"라고 답하지 않기 위한 장치다.
print("=== ⑤ 재확인이 «온라인»이면 단락하지 않는다 ===")
import core.graph_agent as ga  # noqa: E402

calls = []


def fake_offline_now(ttl=ga._OFFLINE_TTL):
    calls.append(ttl)
    return len(calls) == 1          # 1번째(캐시)=오프라인, 2번째(재확인)=온라인


_orig = ga._offline_now
ga._offline_now = fake_offline_now
try:
    check("캐시가 «오프라인»이어도 재확인이 «온라인»이면 False",
          ga.PluizGraphAgent._offline_confirmed() is False)
    check("재확인은 ttl=0으로 부른다 (캐시를 안 쓴다)",
          len(calls) == 2 and calls[1] == 0.0, str(calls))
finally:
    ga._offline_now = _orig

calls.clear()


def both_offline(ttl=ga._OFFLINE_TTL):
    calls.append(ttl)
    return True


ga._offline_now = both_offline
try:
    check("둘 다 «오프라인»이면 True", ga.PluizGraphAgent._offline_confirmed() is True)
finally:
    ga._offline_now = _orig

calls.clear()


def never_offline(ttl=ga._OFFLINE_TTL):
    calls.append(ttl)
    return False


ga._offline_now = never_offline
try:
    check("온라인이면 재확인조차 안 한다 (소켓을 두 번 열지 않는다)",
          ga.PluizGraphAgent._offline_confirmed() is False and len(calls) == 1,
          str(calls))
finally:
    ga._offline_now = _orig


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
