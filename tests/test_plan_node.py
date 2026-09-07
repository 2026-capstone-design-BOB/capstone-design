"""
계획 수립 노드(planner, M3) 검증 — mock (LLM·Windows·API 불필요)
실행: python tests/test_plan_node.py

이 노드가 지키기로 한 **계약**을 확인한다. 분해기(plan_decompose)가 DI이므로
LLM을 부르지 않고 **결정론적 분해기를 주입**한다(core/graph.py는 DI로 만들어져 있다).

여기서 보는 것:
  - 계획을 세웠으면 도구가 **순서대로 전부** 불리는가
  - **계획을 못 세웠을 때 오늘과 완전히 같은가** (사과 문구가 없다) ← 설계의 핵심
  - 승인 중단을 **살아남아 완주**하는가 / 거부되면 **못 한 단계를 말하는가**
  - 승인 대기 중 다른 명령이 오면 **옛 계획이 새 명령에 새지 않는가** ← 사고 이력이 있는 자리
  - 분해기 미주입이면 **planner 노드가 아예 없는가**

⚠️ 이 프로젝트는 "설계대로 도는지만 보고 그 설계가 맞는지는 묻지 않은" 테스트에 두 번
   데였다. 그래서 아래는 노드가 **하지 않기로 한 것**을 더 많이 본다([2][4][6][8]).
"""
import _testenv  # noqa: F401  — 제품 로그·캐시를 더럽히지 않는다(tests/_testenv.py 참조)
import sys, os, re, importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# core/__init__ 을 거치지 않고 graph.py 만 직접 로드 (test_hitl_graph.py와 같은 방식)
spec = importlib.util.spec_from_file_location(
    "pluiz_graph", os.path.join(_ROOT, "core", "graph.py"))
G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

passed = total = 0

def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


# ── 가짜 도구 ─────────────────────────────────────────────────────
order: list[str] = []      # 실행 순서 (계획대로 도는지 보는 유일한 증거)

@tool
def open_app(app: str, new: bool = False) -> str:
    """앱 실행(mock)."""
    order.append(f"open:{app}")
    return f"✓ {app}을(를) 열었습니다."

@tool
def close_app(app: str) -> str:
    """앱 종료(mock)."""
    order.append(f"close:{app}")
    return f"✓ {app}을(를) 닫았습니다."

@tool
def delete_file(file_path: str) -> str:
    """파일 삭제(mock) — DANGEROUS_TOOLS라 승인을 거친다."""
    order.append(f"delete:{file_path}")
    return f"✓ '{file_path}' 삭제했어요."


_DIRECTIVE_RE = re.compile(r'지금은 \*\*(\d+)단계: (.+?)\*\*')


class FakeLLM:
    """시스템 프롬프트에 들어온 **단계 지시를 읽고** 그 단계의 도구를 부르는 mock.

    지시가 메시지가 아니라 SystemMessage로 오는 게 이 설계의 핵심이라(절대규칙 6),
    거기서 읽는 것 자체가 검증이다. 이번 턴의 마지막이 ToolMessage면 그 단계는
    끝난 것이므로 도구를 부르지 않는다 → 그래야 커서가 전진한다.
    """
    _n = 0

    def __init__(self):
        self.directives: list[str] = []      # 받은 단계 지시 (누수 확인용)

    def bind_tools(self, tools): return self

    def invoke(self, messages):
        sys_text = str(getattr(messages[0], "content", ""))
        m = _DIRECTIVE_RE.search(sys_text)
        turn = G.current_turn_messages(messages)
        last_is_tool = bool(turn) and isinstance(turn[-1], ToolMessage)

        if m:
            self.directives.append(m.group(2))
            if last_is_tool:
                return AIMessage(content=f"{m.group(2)} 했어요.")
            return self._for(m.group(2))

        # 계획이 없을 때 = 오늘 경로. 도구를 한 번 부르고 요약한다.
        if last_is_tool:
            return AIMessage(content="네, 처리했어요.")
        human = next((x for x in turn if isinstance(x, HumanMessage)), None)
        return self._for(str(getattr(human, "content", "")) if human else "")

    def _for(self, text: str):
        if "삭제" in text or "지워" in text:
            return self._call("delete_file", {"file_path": "바탕화면/test.txt"})
        if "닫" in text or "꺼" in text:
            return self._call("close_app", {"app": "크롬"})
        if "네이버" in text:
            return self._call("open_app", {"app": "네이버"})
        if "계산기" in text:
            return self._call("open_app", {"app": "계산기"})
        if "열" in text:
            return self._call("open_app", {"app": "메모장"})
        return AIMessage(content="네, 처리했어요.")

    def _call(self, name, args):
        FakeLLM._n += 1
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": args, "id": f"call_{FakeLLM._n}", "type": "tool_call"}])


def fake_security(text): return (False, "")
def no_fast(text): return None


class Decomposer:
    """호출 횟수를 세는 결정론적 분해기."""
    def __init__(self, reply):
        self.reply, self.calls = reply, []
    def __call__(self, text):
        self.calls.append(text)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(text) if callable(self.reply) else self.reply


def build(decomposer=None, fast_resolve=no_fast, llm=None):
    return G.build_pluiz_graph(
        llm=llm or FakeLLM(), tools=[open_app, close_app, delete_file],
        security_check=fake_security, fast_resolve=fast_resolve,
        plan_decompose=decomposer,
    )


def node_names(graph) -> set:
    try:
        return set(graph.get_graph().nodes)
    except Exception:
        return set(getattr(graph, "nodes", {}))


def last_ai(result) -> str:
    return G.extract_response(result)


# ══════════════════════════════════════════════════════════════════
print("\n[1] parse_plan — 판정이 아니라 추출이다")

check("정상 번호 목록 → 2단계",
      G.parse_plan("1. 메모장 열기\n2. 크롬 닫기", "메모장 열고 크롬 닫아줘")
      == ["메모장 열기", "크롬 닫기"])
check("산문만 오면 계획 없음",
      G.parse_plan("네, 메모장을 열고 크롬을 닫을게요!", "메모장 열고 크롬 닫아줘") == [])
check("빈 응답 · None → 계획 없음",
      G.parse_plan("", "x") == [] and G.parse_plan(None, "x") == [])
check("1단계뿐이면 계획 없음(나눌 게 없었다)",
      G.parse_plan("1. 메모장 열기", "메모장 열어줘") == [])
check("단계가 입력 원문 그대로면 계획 없음(분해 실패)",
      G.parse_plan("1. 메모장 열고 크롬 닫아줘\n2. 크롬 닫기", "메모장 열고 크롬 닫아줘") == [])
check(f"상한({G.PLAN_MAX_STEPS})을 넘으면 **자르지 않고** 통째로 버린다",
      G.parse_plan("1. a\n2. b\n3. c", "x") == [])

# ══════════════════════════════════════════════════════════════════
print("\n[2] 게이트 — 계획하지 않기로 한 것들")

check("복합 명령은 계획 대상", G._is_plannable("메모장 열고 크롬 닫아줘") is True)
check("단일 명령은 계획하지 않는다", G._is_plannable("메모장 열어줘") is False)
check("부정어가 있으면 계획하지 않는다(단계가 둘이 아니다)",
      G._is_plannable("크롬 말고 메모장 열어줘") is False)
check("감시 요청은 계획하지 않는다(BL-19 그물을 깨뜨린다)",
      G._is_plannable("메모장 지켜보다가 글자 생기면 알려줘") is False)

order.clear()
dec = Decomposer("1. 메모장 열기\n2. 크롬 닫기")
g = build(dec, fast_resolve=lambda t: "✓ 캐시가 처리했어요.")
r = g.invoke({"messages": [HumanMessage("메모장 열고 크롬 닫아줘")]},
             {"configurable": {"thread_id": "cache_hit"}})
check("캐시 히트는 planner를 타지 않는다 (LLM 왕복 3초를 얹지 않는다)",
      dec.calls == [] and order == [], f"calls={dec.calls} order={order}")

# ══════════════════════════════════════════════════════════════════
print("\n[3] 정상 2단계 — 도구가 순서대로 전부 불린다")

order.clear()
dec = Decomposer("1. 메모장 열기\n2. 크롬 닫기")
llm = FakeLLM()
g = build(dec, llm=llm)
r = g.invoke({"messages": [HumanMessage("메모장 열고 크롬 닫아줘")]},
             {"configurable": {"thread_id": "happy"}})
check("두 단계가 계획된 순서대로 실행됐다",
      order == ["open:메모장", "close:크롬"], f"→ {order}")
check("분해기는 턴당 **1회만** 불린다 (replan 없음)", len(dec.calls) == 1, f"→ {dec.calls}")
check("다 했으면 '못 했어요'라고 하지 않는다",
      "못 했어요" not in last_ai(r), f"→ {last_ai(r)}")

# ══════════════════════════════════════════════════════════════════
print("\n[4] 계획 실패 = 오늘과 완전히 동일 (사용자에게 들리지 않는다)")

for label, reply in [("None을 반환", lambda t: None),
                     ("산문만 반환", "네, 알겠습니다!"),
                     ("예외를 던짐", RuntimeError("분해기 폭발(테스트)"))]:
    order.clear()
    dec = Decomposer(reply)
    g = build(dec)
    r = g.invoke({"messages": [HumanMessage("메모장 열고 크롬 닫아줘")]},
                 {"configurable": {"thread_id": f"fail_{label}"}})
    resp = last_ai(r)
    ok = (order and resp.strip()
          and "계획" not in resp and "못 했어요" not in resp
          and not (r.get("plan") or []))
    check(f"분해기가 {label} → 도구는 돌고 사과 문구가 없다",
          bool(ok), f"order={order} resp={resp!r}")

# ══════════════════════════════════════════════════════════════════
print("\n[5] HITL — 승인 중단을 살아남아 완주한다")

order.clear()
dec = Decomposer("1. 메모장 열기\n2. test.txt 삭제")
g = build(dec)
cfg = {"configurable": {"thread_id": "hitl_ok"}}
r1 = g.invoke({"messages": [HumanMessage("메모장 열고 test.txt 삭제해줘")]}, cfg)
check("2단계(삭제)에서 승인 질문이 뜬다", bool(r1.get("__interrupt__")), f"→ {order}")
check("중단 시점에 1단계는 이미 실행됐다", order == ["open:메모장"], f"→ {order}")
r2 = g.invoke(Command(resume="응"), cfg)
check("'응' 이후 계획이 살아남아 2단계까지 완주한다",
      order == ["open:메모장", "delete:바탕화면/test.txt"]
      and "못 했어요" not in last_ai(r2), f"order={order} resp={last_ai(r2)!r}")

# ══════════════════════════════════════════════════════════════════
print("\n[6] 회귀 — 승인 대기 중 다른 명령에 **옛 계획이 새지 않는다**")
# 취소 플래그가 턴을 넘어 새어 "삭제해 놓고 취소했다"고 답한 사고와 같은 자리다.
# Command(resume)는 input_guard를 거치지 않으므로 hitl이 손으로 지워야 한다.

order.clear()
dec = Decomposer("1. 메모장 열기\n2. test.txt 삭제")
llm = FakeLLM()
g = build(dec, llm=llm)
cfg = {"configurable": {"thread_id": "leak"}}
g.invoke({"messages": [HumanMessage("메모장 열고 test.txt 삭제해줘")]}, cfg)
seen_before = len(llm.directives)
r3 = g.invoke(Command(resume="네이버 열어줘"), cfg)
after = llm.directives[seen_before:]
check("새 명령을 처리하는 agent가 옛 단계 지시를 받지 않는다",
      not any("삭제" in d for d in after), f"→ {after}")
check("상태에서 계획이 지워졌다",
      not (r3.get("plan") or []) and int(r3.get("plan_cursor") or 0) == 0,
      f"→ plan={r3.get('plan')} cursor={r3.get('plan_cursor')}")
check("삭제는 실행되지 않고 새 명령이 실행됐다",
      "delete:바탕화면/test.txt" not in order and "open:네이버" in order, f"→ {order}")

# ══════════════════════════════════════════════════════════════════
print("\n[7] 정직 보고 — 거부로 끝나면 못 한 단계를 말한다")

order.clear()
dec = Decomposer("1. 메모장 열기\n2. test.txt 삭제")
g = build(dec)
cfg = {"configurable": {"thread_id": "reject"}}
g.invoke({"messages": [HumanMessage("메모장 열고 test.txt 삭제해줘")]}, cfg)
r4 = g.invoke(Command(resume="아니 취소해"), cfg)
resp = last_ai(r4)
check("거부하면 '아니'라고 한 뒤에 계속 움직이지 않는다",
      "delete:바탕화면/test.txt" not in order, f"→ {order}")
check("못 한 단계를 그대로 말한다", "못 했어요" in resp and "test.txt 삭제" in resp,
      f"→ {resp!r}")

# ══════════════════════════════════════════════════════════════════
print("\n[8] 분해기 미주입 = 예전 그대로 (노드가 아예 없다)")

off = build(None)
on = build(Decomposer("1. a\n2. b"))
check("plan_decompose가 없으면 planner 노드를 만들지 않는다",
      "planner" not in node_names(off), f"→ {sorted(node_names(off))}")
check("주입하면 planner 노드가 생긴다", "planner" in node_names(on),
      f"→ {sorted(node_names(on))}")

order.clear()
r5 = off.invoke({"messages": [HumanMessage("메모장 열고 크롬 닫아줘")]},
                {"configurable": {"thread_id": "off"}})
check("OFF에서 복합 명령은 to_plan이 아니라 오늘 경로로 간다",
      r5.get("decision") == "to_agent" and bool(order), f"→ {r5.get('decision')} {order}")


# ══════════════════════════════════════════════════════════════════
print("")
print("[9] M3-1 — 커서를 그대로 믿지 않는다 (BL-21 ①)")

# 라이브 2026-09-07에서 A와 B가 **같은 날 둘 다** 나왔다. 한 신호만 보면 반드시
# 하나가 깨진다 — 커서만 보면 B가(커서는 무조건 전진한다), 도구 수만 보면 C가.
#   A 둘 다 실행됨   커서 2 · 호출 2 → 조용해야 한다 (거짓 실패를 만들지 않는다)
#   B 단계를 건너뜀  커서 2 · 호출 1 → 말해야 한다
#   C 승인 거부      커서 1 · 호출 2 → 말해야 한다  ← 위 [7]이 본다
# → docs/design/M3-1_단계완료판정.md

check("A: 근거가 겹치는 데까지만 인정한다", G.steps_covered(2, 2) == 2)
check("B: 커서가 앞서가면 도구 수를 믿는다", G.steps_covered(2, 1) == 1)
check("C: 도구 수가 앞서가면 커서를 믿는다", G.steps_covered(1, 2) == 1)
check("망가진 값은 0으로 떨어진다(턴을 죽이지 않는다)",
      G.steps_covered(None, "x") == 0 and G.steps_covered(-5, 3) == 0)


class SkippingLLM:
    """1단계는 하고 2단계는 말로만 때운다 — 라이브에서 나온 그 모습."""

    def bind_tools(self, tools): return self

    def invoke(self, messages):
        m = _DIRECTIVE_RE.search(str(getattr(messages[0], "content", "")))
        turn = G.current_turn_messages(messages)
        last_is_tool = bool(turn) and isinstance(turn[-1], ToolMessage)
        if m and m.group(1) == "1" and not last_is_tool:
            return AIMessage(content="", tool_calls=[{
                "name": "open_app", "args": {"app": "메모장"},
                "id": "skip1", "type": "tool_call"}])
        return AIMessage(content="네, 둘 다 처리했어요!")   # 2단계는 그냥 잡담


class BatchLLM:
    """1단계 지시에 두 단계를 **한 배치로** 처리한다 — 이것도 라이브에서 나왔다."""

    def bind_tools(self, tools): return self

    def invoke(self, messages):
        turn = G.current_turn_messages(messages)
        if any(isinstance(x, ToolMessage) for x in turn):
            return AIMessage(content="둘 다 열었어요.")
        return AIMessage(content="", tool_calls=[
            {"name": "open_app", "args": {"app": "메모장"},
             "id": "b1", "type": "tool_call"},
            {"name": "open_app", "args": {"app": "계산기"},
             "id": "b2", "type": "tool_call"}])


order.clear()
_two_steps = "1. 메모장 열기\n2. 계산기 열기"
gB = build(Decomposer(_two_steps), llm=SkippingLLM())
rB = gB.invoke({"messages": [HumanMessage("메모장이랑 계산기 열어줘")]},
               {"configurable": {"thread_id": "skip"}})
respB = last_ai(rB)
check("B: 건너뛴 단계를 말한다 — 라이브에서 조용히 넘어가던 그 문장",
      "못 했어요" in respB and "계산기 열기" in respB, f"→ {respB!r}")
check("B: 커서는 그래도 끝까지 전진한다(무한루프 방지는 그대로)",
      int(rB.get("plan_cursor") or 0) == 2, f"→ 커서 {rB.get('plan_cursor')}")
check("B: 실제로 계산기는 안 열렸다", "open:계산기" not in order, f"→ {order}")

order.clear()
gA = build(Decomposer(_two_steps), llm=BatchLLM())
rA = gA.invoke({"messages": [HumanMessage("메모장 열고 계산기도 열어줘")]},
               {"configurable": {"thread_id": "batch"}})
respA = last_ai(rA)
check("A: 한 배치로 다 했으면 **거짓 실패를 만들지 않는다**",
      "못 했어요" not in respA, f"→ {respA!r}")
check("A: 두 앱이 실제로 열렸다",
      "open:메모장" in order and "open:계산기" in order, f"→ {order}")

print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
