# -*- coding: utf-8 -*-
"""연결이 막히면 **열어 준다** — 부탁이 아니라 강제 (BL-90 · 2026-10-02 실기)

실행: python tests/test_connect_retry.py

## 왜 이 테스트가 있나

BL-84 로 `connect_google` 도구를 만들고, 시스템 프롬프트에도 «막히면 호출하세요»를
적었다. **둘 다 있는데 실기에서 모델이 안 불렀다.**

```
👤 오늘 일정 알려줘
🤖 구글 로그인이 아직 안 됐어요. 연결 창에서 한 번 로그인하면 그 뒤로는 안 물어봐요.
🙋 "구글 로그인 어떻게 하는지, 브라우저도 안 띄워주고 이상해.."
```

🔑 이 저장소가 반복해서 적어 둔 문장이 또 맞았다 —
*«프롬프트는 확률을 올릴 뿐이고 보장하는 건 구조다»*.

## 여기서 고정하는 것 넷

1. 🚨 **막혔으면 한 번 강제로 연다** — BL-19(감시)·BL-35(약속)와 **같은 기계**다.
2. 🔒 **이번 턴만 본다**(절대규칙 6). 지난 턴에 막혔던 것으로 지금 창을 띄우면,
   이미 로그인한 사용자에게 브라우저가 느닷없이 뜬다.
3. 🔒 **이미 열었으면 또 안 연다.** 창이 둘이면 어느 쪽을 봐야 할지 모르고,
   포트가 겹쳐 **둘 다 실패**할 수 있다.
4. 🚨 **못 열어도 고쳐 쓰지 않는다** — 원래 답(«로그인이 안 됐어요»)은 **사실**이다.

## ⚠️ 소스 대조가 아니라 **그래프를 돌린다**

가짜 LLM 을 끼우고 실제로 한 턴을 밟는다(BL-83 의 교훈).
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

import core.graph as G  # noqa: E402
import tools.google_auth as A  # noqa: E402
from langchain_core.messages import (  # noqa: E402
    AIMessage, HumanMessage, SystemMessage, ToolMessage,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name}" + (f"   → {detail}" if detail else ""))


# ═══ ① 🚨 두 곳에 적힌 사실이 **안 어긋난다** ═══════════════════════
#
# `core/graph.py` 는 `tools/` 를 import 하면 순환이 생겨서 문장 **조각**을 들고 있다.
# 그러면 한쪽만 고쳐질 수 있다 — 이 저장소가 **네 번 데인 모양**이다. 그래서 센다.
print(f"{NL}=== ① \U0001f6a8 조각이 실제 문장과 안 어긋난다 ===")
check("graph 가 든 조각이 **진짜 NEED_LOGIN 안에** 있다",
      G._NEED_LOGIN_MARK in A.NEED_LOGIN,
      f"{G._NEED_LOGIN_MARK!r} vs {A.NEED_LOGIN!r}")
from core.tool_registry import get_all_tools  # noqa: E402
check("강제할 도구 이름이 **실재한다**",
      G._CONNECT_TOOL in {t.name for t in get_all_tools()}, G._CONNECT_TOOL)


# ═══ ② 언제 끼어드나 ════════════════════════════════════════════════
print(f"{NL}=== ② 언제 끼어드나 ===")

BLOCKED = [
    HumanMessage(content="오늘 일정 알려줘"),
    AIMessage(content="", tool_calls=[
        {"name": "list_calendar_events", "args": {}, "id": "c1"}]),
    ToolMessage(content=A.NEED_LOGIN, tool_call_id="c1", name="list_calendar_events"),
]
SAID = AIMessage(content="구글 로그인이 아직 안 됐어요.")

check("🚨 막혔고 연결을 안 열었으면 **끼어든다**",
      G.needs_connect_retry(BLOCKED, SAID))
check("🔒 이미 뭔가 부르는 중이면 **안 끼어든다**",
      not G.needs_connect_retry(
          BLOCKED, AIMessage(content="", tool_calls=[
              {"name": "open_app", "args": {}, "id": "x"}])))
check("🔒 **이번 턴에 이미 열었으면** 또 안 연다",
      not G.needs_connect_retry(
          BLOCKED + [AIMessage(content="", tool_calls=[
              {"name": "connect_google", "args": {}, "id": "c2"}]),
              ToolMessage(content="✓ 창을 띄웠어요", tool_call_id="c2",
                          name="connect_google")], SAID))
check("막힌 적이 없으면 안 끼어든다",
      not G.needs_connect_retry(
          [HumanMessage(content="오늘 일정"),
           AIMessage(content="", tool_calls=[
               {"name": "list_calendar_events", "args": {}, "id": "c1"}]),
           ToolMessage(content="✓ 오늘 일정 2개예요", tool_call_id="c1",
                       name="list_calendar_events")], SAID))
# 🚨 **절대규칙 6** — 지난 턴에 막혔던 것으로 지금 창을 띄우면, 이미 로그인한
#   사용자에게 브라우저가 느닷없이 뜬다.
check("🚨 **지난 턴에 막혔던 것은 안 본다** (절대규칙 6)",
      not G.needs_connect_retry(
          BLOCKED + [AIMessage(content="로그인이 안 됐어요"),
                     HumanMessage(content="고마워")], SAID))


# ═══ ③ 지시가 **시스템 자리**에 들어간다 ═════════════════════════════
print(f"{NL}=== ③ 지시가 시스템 자리에 들어간다 ===")
_base = [SystemMessage(content="SYS"), HumanMessage(content="오늘 일정")]
_out = G.with_connect_directive(_base)
check("SystemMessage 가 **하나 그대로다**",
      sum(1 for m in _out if isinstance(m, SystemMessage)) == 1)
check("연결 도구를 부르라고 적는다", G._CONNECT_TOOL in _out[0].content)
check("🚨 **«터미널에서 직접»을 금지한다**",
      "터미널에서 직접 하라고 하지 마세요" in _out[0].content)
check("🚨 **«연결됐어요»를 금지한다** (창만 띄운 것이다)",
      "«연결됐어요»라고 하지 말고" in _out[0].content)


# ═══ ④ 🚨 그래프를 **실제로 돌린다** ════════════════════════════════
print(f"{NL}=== ④ \U0001f6a8 그래프를 실제로 돌린다 ===")


# 🚨 **진짜 `connect_google` 을 넘기지 않는다.** 그래프가 끝까지 돌면서
#   `ToolNode` 가 그걸 **실제로 실행해 브라우저를 띄운다.** 테스트가 창을 열면 안 된다.
#   그래서 **이름만 같은 가짜**를 끼운다 — 강제·라우팅은 이름으로 도니까 그대로 돈다.
from langchain_core.tools import tool as _tool  # noqa: E402

_opened = []


@_tool
def connect_google() -> str:
    """구글 계정 연결을 시작합니다(테스트용 — 아무것도 안 엽니다)."""
    _opened.append(1)
    return "✓ 구글 연결 창을 띄웠어요(가짜)."


class StubbornLLM:
    """🚨 **절대 연결 도구를 스스로 안 부르는 모델.** 실기에서 본 바로 그 모양."""

    def __init__(self, support_force=True):
        self.support_force = support_force
        self.forced = None
        self.calls = 0

    def bind_tools(self, tools, tool_choice=None):
        if tool_choice is None:
            return self
        if not self.support_force:
            raise ValueError("tool_choice 미지원")
        clone = StubbornLLM(self.support_force)
        clone.forced = tool_choice
        clone.parent = self
        return clone

    def invoke(self, messages):
        self.calls += 1
        if self.forced:
            return AIMessage(content="", tool_calls=[
                {"name": self.forced, "args": {}, "id": "forced-1"}])
        return AIMessage(content="구글 로그인이 아직 안 됐어요.")


def _no_security(text):
    return False, ""


def _fast_miss(text):
    return None


def drive(llm):
    g = G.build_pluiz_graph(llm=llm, tools=[], security_check=_no_security,
                            fast_resolve=_fast_miss)
    return g.invoke({"messages": list(BLOCKED)},
                    {"configurable": {"thread_id": "connect-" + str(id(llm))}})


# ⚠️ `tools=[]` 면 `_forced_llm` 이 묶을 것이 없어 None 을 돌려준다(설득 경로).
#   강제 경로를 보려면 도구를 하나 넘긴다.
def drive_with_tools(llm):
    g = G.build_pluiz_graph(llm=llm, tools=[connect_google],
                            security_check=_no_security, fast_resolve=_fast_miss)
    return g.invoke({"messages": list(BLOCKED)},
                    {"configurable": {"thread_id": "connect-t-" + str(id(llm))}})


llm1 = StubbornLLM(support_force=True)
_opened.clear()
st1 = drive_with_tools(llm1)
# 🔑 **마지막 메시지가 아니라 «열렸나»를 본다.** 강제 호출 뒤에 도구가 돌고 agent 가
#   한 번 더 돌아서, 마지막 메시지는 이미 그 다음 것이다.
check("🚨 **모델이 안 불러도 연결이 열린다** (강제)",
      len(_opened) == 1, f"열린 횟수 {len(_opened)}")
_names1 = [c.get("name")
           for m in st1["messages"] for c in (getattr(m, "tool_calls", None) or [])]
check("   그 호출이 **connect_google 이다**",
      _names1.count(G._CONNECT_TOOL) == 1, str(_names1))

# 🚨 `tool_choice` 를 못 묶는 provider 도 있다 — 그때는 **설득 재시도**로 내려가고,
#   그래도 안 부르면 **원래 답을 그대로 둔다.** 턴을 죽이지 않는다.
llm2 = StubbornLLM(support_force=False)
_opened.clear()
st2 = drive_with_tools(llm2)
_last2 = st2["messages"][-1]
check("🔒 강제를 못 묶으면 **설득으로 내려가고 턴은 산다**",
      bool(G.extract_response(st2)), repr(_last2)[:160])
check("   못 열었으면 **원래 답이 그대로 나간다** (고쳐 쓰지 않는다)",
      "로그인이 아직 안 됐어요" in G.extract_response(st2),
      G.extract_response(st2))
check("   그리고 **창은 안 열렸다** (억지로 열지 않는다)", _opened == [])


# ═══ ⑤ 일정 만들기가 **URL 로 도망가지 않는다** (같은 실기) ══════════
#
# 🙋 *"내가 직접 일정 만들라고 하질 않나"* — 토큰이 없을 때
#   *"내일모레 9시 미팅 만들어줘"* 가 **브라우저 창 + «저장 버튼을 눌러주세요»** 로
#   끝났고, 모델은 그 `✓` 를 보고 *"일정을 만들었어요!"* 라고 답했다.
print(f"{NL}=== ⑤ \U0001f6a8 일정 만들기가 URL 로 도망가지 않는다 ===")
import tools.calendar as C  # noqa: E402
from core.tool_result import tool_failed  # noqa: E402

_CAL_SRC = io.open(os.path.join(_ROOT, "tools", "calendar.py"),
                   encoding="utf-8").read()


def _raise_need_login(*a, **k):
    raise A.NeedLogin("토큰 없음")


_orig = C._create_via_api
C._create_via_api = _raise_need_login
try:
    out = C.create_calendar_event.invoke(
        {"title": "미팅", "date": "2026-10-04", "time": "09:00"})
finally:
    C._create_via_api = _orig

check("🚨 **로그인만 안 된 것이면 URL 을 안 연다**",
      out == A.NEED_LOGIN, out)
check("   그래서 BL-90 의 강제가 **여기에도 걸린다**",
      G._NEED_LOGIN_MARK in out)

# 자격증명 자체가 없으면 URL 말고 길이 없다 — 그때는 **✓ 가 아니라 ⚠️** 다.
check("🚨 URL 폴백은 **⚠️ 다** (일정은 아직 없다)",
      "⚠️ 아직 일정이 만들어지지 않았어요" in _CAL_SRC, )
check("   그래서 `tool_failed` 에 걸려 output_guard 의 그물을 지난다",
      tool_failed("⚠️ 아직 일정이 만들어지지 않았어요. …"))
check("🔒 **«만들었어요»라고 적힌 자리가 없다**",
      "일정이 캘린더에 추가됐어요" in _CAL_SRC          # API 성공 경로는 그대로
      and "추가 화면을 열었어요. 저장 버튼을 눌러주세요!" not in _CAL_SRC)


print(f"{NL}결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
