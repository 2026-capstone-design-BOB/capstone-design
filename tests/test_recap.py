# -*- coding: utf-8 -*-
"""「지금까지 뭐 했지?」 — **근거에서 만든다** (BL-56 · 2026-10-02)

실행: python tests/test_recap.py

## 왜 이 테스트가 있나

*"지금까지 한 거 뭐 했는지 정리해 줄래"* 는 **누구나 물어볼 법한 질문**인데
2026-09-14 2차 리허설에서 `사유=못함` 으로 끝났다. 조사해 보니 막은 장치가 있는 게
아니라 **모델이 그냥 «못 한다»고 답한 것**이었고, 시스템 프롬프트에 «대화를 요약해도
된다»가 한 줄도 없었다.

🚨 **그래서 프롬프트 한 줄을 넣는 것이 제일 싼 길이었다 — 안 넣었다.**
이 저장소가 반복해서 적어 둔 것이 *«프롬프트는 확률을 올릴 뿐이고 보장하는 건
구조다»* 이고, 여기서 틀리면 **«안 한 일을 했다고 말하는 것»** 이라
BL-12·19·21·26 이 **«요약»이라는 새 입구로** 들어온다.

## 여기서 고정하는 것 다섯

1. 🔒 **범위와 대상이 둘 다 있어야** 요약 요청이다 — *"지금까지 받은 파일 정리해줘"*
   가 걸리면 **파일을 안 건드리고 말만 하는** 턴이 된다.
2. 🚨 **기록은 코드가 만든다.** 모델이 ✗ 를 ✓ 로 바꿔 말할 **재료가 없다.**
3. 🚨 **지금 묻고 있는 턴은 기록에서 뺀다.** 안 그러면 모델이 그것도 «한 일»로 센다.
4. 🚨 **잘랐으면 잘랐다고 말한다** — 조용히 자르면 «그게 전부»로 요약된다.
5. 🚨 **턴을 넘겨 새지 않는다**(절대규칙 11) — 지난 턴 기록이 남으면 이번 턴 답에
   지난 대화가 섞인다. `plan` 이 정확히 그 모양으로 데인 자리다.

## ⚠️ 소스 대조가 아니라 **그래프를 실제로 돌린다**

2026-10-02 에 UI 결함 셋이 **mock 3,000건이 초록인 채로** 살아 있었다(BL-83).
«그렇게 적혀 있나»는 «그래서 그렇게 도나»를 못 본다. 그래서 여기서는 가짜 LLM 을
끼우고 **그래프를 한 바퀴 돌려 시스템 메시지에 무엇이 들어갔는지** 본다.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

import core.graph as G  # noqa: E402
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


# ═══ ① 무엇이 요약 요청인가 ════════════════════════════════════════
#
# 🔒 **놓치는 쪽이 안전하다.** 놓치면 오늘과 똑같이 돌 뿐이고, 잘못 걸리면
#   **명령이 수다로 바뀐다.** 그래서 범위(언제까지)와 대상(무엇을)을 둘 다 요구한다.
print(f"{NL}=== ① \U0001f512 범위와 대상이 둘 다 있어야 한다 ===")

_YES = [
    "지금까지 한 거 뭐 했는지 정리해 줄래",     # 2026-09-14 리허설 원문
    "오늘 한 일 뭐야",
    "우리 대화 정리해줘",
    "여태 뭐 했지",
    "그동안 무슨 일 했는지 알려줘",
]
_NO = [
    "지금까지 받은 파일 정리해줘",   # 🚨 범위는 있지만 대상이 «파일»이다 — 명령이다
    "바탕화면 정리해줘",
    "오늘 날씨 알려줘",
    "메모장에 뭐라고 써 있어",       # Vision 질문이다
    "그거 꺼줘",
    "a.txt 지워줘",
    "",
]
check("리허설에서 실패한 그 문장이 걸린다",
      G.is_recap_request("지금까지 한 거 뭐 했는지 정리해 줄래"))
check(f"요약 요청 {len(_YES)}개가 전부 걸린다",
      all(G.is_recap_request(t) for t in _YES),
      str([t for t in _YES if not G.is_recap_request(t)]))
check(f"\U0001f6a8 명령 {len(_NO)}개가 하나도 안 걸린다",
      not any(G.is_recap_request(t) for t in _NO),
      str([t for t in _NO if G.is_recap_request(t)]))
check("🚨 「정리」·「요약」만으로는 안 걸린다 (대상을 본다)",
      not G.is_recap_request("정리해줘") and not G.is_recap_request("요약해줘"))
check("🚨 범위만으로도 안 걸린다",
      not G.is_recap_request("지금까지 고마웠어"))


# ═══ ② 기록은 **코드가** 만든다 ═════════════════════════════════════
print(f"{NL}=== ② \U0001f6a8 기록은 코드가 만든다 (모델이 바꿀 재료가 없다) ===")

_MSGS = [
    HumanMessage(content="메모장 켜줘"),
    AIMessage(content="", tool_calls=[
        {"name": "open_app", "args": {"app": "메모장"}, "id": "c1"}]),
    ToolMessage(content="✓ 메모장을 열었어요", tool_call_id="c1", name="open_app"),
    AIMessage(content="메모장 열었어요"),
    HumanMessage(content="a.txt 지워줘"),
    AIMessage(content="", tool_calls=[
        {"name": "delete_file", "args": {"path": "a.txt"}, "id": "c2"}]),
    ToolMessage(content="✗ a.txt 를 찾지 못했어요", tool_call_id="c2", name="delete_file"),
    AIMessage(content="못 지웠어요"),
    HumanMessage(content="고마워"),
    AIMessage(content="천만에요"),
    HumanMessage(content="지금까지 한 거 뭐 했는지 정리해 줄래"),
]
_rec = G.build_recap(_MSGS)

check("무엇을 불렀는지 **인자까지** 적는다",
      "open_app(app='메모장')" in _rec and "delete_file(path='a.txt')" in _rec, _rec)
check("🚨 **된 것은 ✓**", "open_app(app='메모장') ✓" in _rec, _rec)
check("🚨 **안 된 것은 ✗** — 모델이 ✓ 로 바꿔 말할 재료가 없다",
      "delete_file(path='a.txt') ✗" in _rec, _rec)
# 🚨 2026-10-02 실기 — *"저녁 메뉴 추천해 줘"* 가 요약에서 빠졌다. 기록에는 **있었는데**
#   *"(도구를 부르지 않았습니다)"* 라고만 적혀 **빈칸처럼 보여서 모델이 뺐다.**
#   🔑 잡담 턴에서는 **말한 것이 곧 한 일**이다.
check("🚨 도구를 안 부른 턴은 **뭐라고 답했는지**를 적는다 (빈칸이 아니다)",
      "(도구 없이 말로 답함) 천만에요" in _rec, _rec)
check("🚨 **지금 묻고 있는 턴은 뺀다** (그것도 «한 일»로 세면 안 된다)",
      "정리해 줄래" not in _rec, _rec)
check("ToolMessage 가 없으면 기록도 없다 (지어내지 않는다)",
      G.build_recap([HumanMessage(content="지금까지 뭐 했지")]) == "")
check("빈 히스토리에도 안 죽는다", G.build_recap([]) == "")

# 🚨 **조용히 자르지 않는다.** 자른 줄 모르면 모델이 «그게 전부»로 요약한다 —
#   «못 잰 것을 0이라고 쓰지 않는다»와 같은 규칙이다.
_LONG = []
for i in range(20):
    _LONG += [HumanMessage(content=f"명령{i}"),
              AIMessage(content="", tool_calls=[
                  {"name": "open_app", "args": {"app": f"앱{i}"}, "id": f"t{i}"}]),
              ToolMessage(content="✓ 됐어요", tool_call_id=f"t{i}", name="open_app")]
_LONG.append(HumanMessage(content="지금까지 뭐 했는지 정리해줘"))
_long_rec = G.build_recap(_LONG)
check(f"턴이 많으면 {G._RECAP_MAX_TURNS}턴까지만 담는다",
      _long_rec.count("사용자:") == G._RECAP_MAX_TURNS,
      f"{_long_rec.count('사용자:')}턴")
check("🚨 **잘랐으면 잘랐다고 말한다** (조용히 자르지 않는다)",
      "빠졌습니다" in _long_rec and "모른다고 말하세요" in _long_rec)
check("   남긴 것은 **최근** 쪽이다", "앱19" in _long_rec and "앱0'" not in _long_rec)


# ═══ ③ 지시가 **시스템 자리**에 들어간다 ═════════════════════════════
#
# ⚠️ Gemini 는 시스템 지시를 따로 받아서 **두 번째 SystemMessage 는 무시되거나 400**이다.
#   `with_watch_directive` 가 같은 이유로 «기존 것을 교체»하는 자리다.
print(f"{NL}=== ③ 지시가 시스템 자리에 들어간다 ===")

_base = [SystemMessage(content="SYS"), HumanMessage(content="지금까지 뭐 했지")]
_out = G.with_recap_directive(_base, _rec)
check("SystemMessage 가 **하나 그대로다**",
      sum(1 for m in _out if isinstance(m, SystemMessage)) == 1)
check("기록이 그 안에 들어갔다", "실제로 일어난 일" in _out[0].content)
check("🚨 «✗ 는 안 된 것» 이라고 **규칙으로** 말한다",
      "안 된 것" in _out[0].content and "됐다고 하지 마세요" in _out[0].content)
check("🚨 «기록에 없는 것은 없다고 말하라»가 들어간다",
      "기록에 없어요" in _out[0].content)
check("🚨 «도구를 안 부른 턴도 한 일이니 빼지 말라»가 들어간다",
      "빼지 말고" in _out[0].content)
check("🔒 기록이 비면 **아무것도 안 바꾼다** (꺼진 경로가 예전과 같다)",
      G.with_recap_directive(_base, "") is _base)
check("시스템 메시지가 없으면 만들어서 **앞에** 둔다",
      isinstance(G.with_recap_directive([HumanMessage(content="x")], _rec)[0],
                 SystemMessage))


# ═══ ④ 🚨 그래프를 **실제로 돌린다** ════════════════════════════════
#
# 소스에 적혀 있는 것과 도는 것은 다르다(BL-83). 가짜 LLM 을 끼우고 한 바퀴 돌려
# **시스템 메시지에 무엇이 들어갔는지** 본다.
print(f"{NL}=== ④ \U0001f6a8 그래프를 실제로 돌린다 ===")


class FakeLLM:
    def __init__(self):
        self.calls = 0
        self.systems = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        self.systems.append(next(
            (str(getattr(m, "content", "")) for m in messages
             if isinstance(m, SystemMessage)), ""))
        return AIMessage(content="메모장을 열었고, a.txt 는 못 지웠어요.")


def _no_security(text):
    return False, ""


def _fast_miss(text):
    return None


llm = FakeLLM()
graph = G.build_pluiz_graph(llm=llm, tools=[], security_check=_no_security,
                            fast_resolve=_fast_miss)
cfg = {"configurable": {"thread_id": "recap-1"}}

graph.invoke({"messages": [
    HumanMessage(content="메모장 켜줘"),
    AIMessage(content="", tool_calls=[
        {"name": "open_app", "args": {"app": "메모장"}, "id": "c1"}]),
    ToolMessage(content="✓ 메모장을 열었어요", tool_call_id="c1", name="open_app"),
    AIMessage(content="메모장 열었어요"),
]}, cfg)
_before = llm.calls

st = graph.invoke({"messages": [
    HumanMessage(content="지금까지 한 거 뭐 했는지 정리해 줄래")]}, cfg)

check("요약 턴에서 LLM 이 불렸다", llm.calls > _before)
_sys = llm.systems[-1] if llm.systems else ""
check("🚨 **기록이 실제로 LLM 까지 갔다**",
      "실제로 일어난 일" in _sys, _sys[-200:])
check("   그 기록에 진짜 호출이 들어 있다",
      "open_app(app='메모장')" in _sys, _sys[-200:])
check("응답이 나온다", bool(G.extract_response(st)))

# 🚨 **턴을 넘겨 새면 안 된다** — `plan` 이 정확히 이 모양으로 데인 자리다(절대규칙 11).
st2 = graph.invoke({"messages": [HumanMessage(content="고마워")]}, cfg)
check("🚨 **다음 턴에는 기록이 안 남는다** (절대규칙 11 과 같은 모양)",
      "실제로 일어난 일" not in (llm.systems[-1] if llm.systems else ""),
      (llm.systems[-1] if llm.systems else "")[-200:])
check("   상태에서도 지워진다", not (st2.get("recap") or ""))

# 🔒 요약 요청이 아닌 턴은 **글자 그대로 예전과 같다.**
llm2 = FakeLLM()
g2 = G.build_pluiz_graph(llm=llm2, tools=[], security_check=_no_security,
                         fast_resolve=_fast_miss)
g2.invoke({"messages": [HumanMessage(content="메모장 켜줘")]},
          {"configurable": {"thread_id": "recap-2"}})
check("🔒 평범한 명령에는 **아무것도 안 붙는다**",
      "실제로 일어난 일" not in (llm2.systems[-1] if llm2.systems else ""))


# ═══ ⑤ 배선이 끊기지 않았다 ═══════════════════════════════════════
print(f"{NL}=== ⑤ 배선 ===")
_SRC = io.open(os.path.join(_ROOT, "core", "graph.py"), encoding="utf-8").read()
check("recap 노드가 그래프에 있다", 'g.add_node("recap", recap)' in _SRC)
check("recap 다음은 agent 다", 'g.add_edge("recap", "agent")' in _SRC)
check("🚨 **계획보다 먼저 본다** (요약은 단계가 아니라 읽는 일이다)",
      _SRC.find("is_recap_request(text)") < _SRC.find("_is_plannable(text)"))
check("🚨 새 턴마다 지운다 (input_guard 두 길 모두)",
      _SRC.count('"recap": ""') == 2)
check("🔒 **도구를 늘리지 않았다** — 상태를 보는 자리는 노드다",
      "summarize_session" not in _SRC)

print(f"{NL}결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
