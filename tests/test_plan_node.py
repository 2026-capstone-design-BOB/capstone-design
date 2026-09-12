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

# ── 🚩 BL-30 — 같은 동작은 나누지 않는다 (2026-09-10 실기) ──────────
#
# *"a.txt, b.txt 지워줘"* 가 2단계로 쪼개져서 **승인 질문이 두 번** 떴다.
# 그리고 2단계가 위험 도구면 LLM이 그 단계에서 도구를 아예 안 부르는 일이 있었다:
#     [Plan] 1/2 '메모장 최소화' → 2/2 'b.txt 파일 지우기'
#     턴 완료 | 도구=['minimize_window']        ← 삭제를 안 불렀다
#
# 사용자: *"두 파일 지워달라고 하면 꼭 뒤 파일과 관련해서는 실행이 안 되는 것 같아"*
#
# 쪼개지 않으면 LLM이 한 배치에 담고, **BL-24가 이미 만든 «전부를 이름으로 부르는
# 질문»이 그대로 받는다** — 새 기계가 필요 없다.
print("\n=== BL-30 — 같은 동작은 나누지 않는다 ===")

check("🚩 삭제 둘은 안 나눈다", not G.parse_plan(["a.txt 지우기", "b.txt 지우기"]))
check("🚩 표현이 달라도 같은 동작이면 안 나눈다",
      not G.parse_plan(["a.txt 지우기", "b.txt 삭제"]))
check("🚩 '휴지통'도 삭제로 읽는다",
      not G.parse_plan(["a.txt 휴지통으로", "b.txt 지우기"]))

# ⚠️ 여기가 이 규칙의 경계다. 넓히면 M3가 무력해진다 —
#   열기는 **쪼개도 피해가 없고**(승인이 없다), 쪼개야 «계산기는 못 했어요»를 말한다.
check("열기 둘은 **그대로 나눈다** (M3의 «못 했어요»를 지킨다)",
      len(G.parse_plan(["메모장 열기", "계산기 열기"])) == 2)
check("동작이 다르면 나눈다", len(G.parse_plan(["메모장 열기", "크롬 닫기"])) == 2)
check("실기 사례(최소화+삭제)는 나눈다 — 동작이 다르다",
      len(G.parse_plan(["메모장 최소화", "b.txt 파일 지우기"])) == 2)
check("동작을 모르면 나눈다 (모르는 건 건드리지 않는다)",
      len(G.parse_plan(["화면 밝기 올리기", "볼륨 줄이기"])) == 2)

check("_step_action이 동의어를 같은 값으로 읽는다",
      G._step_action("a.txt 지우기") == G._step_action("b.txt 삭제") == "삭제")
check("묶는 동작은 «되돌릴 수 없는 것»으로 한정돼 있다",
      G._BATCHABLE_ACTIONS == frozenset({"삭제"}), f"→ {G._BATCHABLE_ACTIONS}")

# ── 끝단 — 정말 «한 번만» 묻고 «둘 다» 지우는가 ──────────────────
# 단계 판정만 맞고 승인이 두 번 뜨면 고친 게 아니다. 그래프를 끝까지 돌린다.
print("\n=== BL-30 끝단 — 한 번 묻고 둘 다 지운다 ===")
from langchain_core.tools import tool as _tool
from langgraph.types import Command as _Command

_deleted = []

@_tool
def delete_file(file_path: str) -> str:
    """파일 삭제(mock)."""
    _deleted.append(file_path)
    return f"✓ '{file_path}' 삭제했어요."

class _TwoDelete:
    """실기처럼 «두 파일 삭제»를 한 배치에 담는다."""
    _n = 0
    def bind_tools(self, t): return self
    def invoke(self, m):
        turn = G.current_turn_messages(m)
        if any(isinstance(x, ToolMessage) for x in turn):
            return AIMessage(content="다 지웠어요.")
        _TwoDelete._n += 1
        return AIMessage(content="", tool_calls=[
            {"name": "delete_file", "args": {"file_path": "바탕화면/a.txt"},
             "id": f"b{_TwoDelete._n}a", "type": "tool_call"},
            {"name": "delete_file", "args": {"file_path": "바탕화면/b.txt"},
             "id": f"b{_TwoDelete._n}b", "type": "tool_call"}])

g30 = G.build_pluiz_graph(
    llm=_TwoDelete(), tools=[delete_file],
    security_check=lambda t: (False, ""), fast_resolve=lambda t: None,
    target_exists=lambda *a, **k: True)
cfg30 = {"configurable": {"thread_id": "bl30"}}
r30 = g30.invoke({"messages": [HumanMessage("a.txt랑 b.txt 지워줘")]}, cfg30)
itr30 = r30.get("__interrupt__")
q30 = itr30[0].value.get("question", "") if itr30 else ""

check("질문이 한 번 뜬다", bool(itr30))
check("🔒 질문이 **둘 다** 이름을 부른다", "a.txt" in q30 and "b.txt" in q30, f"→ {q30!r}")
check("🔒 개수를 말한다 (묻지 않은 삭제를 알아챌 단서)", "2개" in q30, f"→ {q30!r}")

r30b = g30.invoke(_Command(resume="응"), cfg30)
check("승인하면 **둘 다** 지워진다",
      _deleted == ["바탕화면/a.txt", "바탕화면/b.txt"], f"→ {_deleted}")
check("🚨 질문이 두 번 뜨지 않는다 (실기에서 두 번 떴다)",
      not r30b.get("__interrupt__"))

_deleted.clear()
g30r = G.build_pluiz_graph(
    llm=_TwoDelete(), tools=[delete_file],
    security_check=lambda t: (False, ""), fast_resolve=lambda t: None,
    target_exists=lambda *a, **k: True)
cfg30r = {"configurable": {"thread_id": "bl30r"}}
g30r.invoke({"messages": [HumanMessage("a.txt랑 b.txt 지워줘")]}, cfg30r)
g30r.invoke(_Command(resume="아니"), cfg30r)
check("거부하면 **둘 다** 안 지워진다", _deleted == [], f"→ {_deleted}")

# ── BL-51 — 한 응답에서 말이 세 번 바뀌지 않는가 ──────────────────
# 1차 리허설(2026-09-12) 대본 7장면에서 그대로 나갔다:
#
#   🤖 ✓ 'test.txt' 휴지통으로 옮겼어요.
#      다만 이건 못 했어요: 'test.txt 파일 지우기'.
#      그리고 'test.txt' 휴지통으로 옮겼어요.
#
#   «했다 → 못 했다 → 또 했다». 세 조각이 각각 다른 곳에서 나왔고 **서로를 안 봤다.**
# ⚠️ 문구가 아니라 **모순**을 본다 — 한 응답이 같은 파일을 두고 «했다»와 «못 했다»를
#   같이 말하지 않는가, 같은 사실을 두 번 말하지 않는가.
print("\n=== BL-51 한 응답 안에서 말이 바뀌지 않는다 ===")

_P51 = os.path.join("C:", os.sep, "Users", "me", "Desktop", "test.txt")

# [순수 함수] 성공한 위험 도구의 대상은 «못 한 단계»에서 빠진다
_m51 = [
    HumanMessage("메모장 열고 test.txt 파일 지워줘"),
    AIMessage(content="", tool_calls=[{"name": "delete_file",
              "args": {"file_path": _P51}, "id": "p51", "type": "tool_call"}]),
    ToolMessage(content="✓ 'test.txt' 휴지통으로 옮겼어요.", tool_call_id="p51"),
]
_pruned = G.prune_done_steps(["메모장 열기", "test.txt 파일 지우기"], _m51)
check("[BL-51] 성공한 대상을 담은 단계는 «못 했다»에서 빠진다",
      _pruned == ["메모장 열기"], f"→ {_pruned}")
check("[BL-51] 증거가 없으면 목록을 그대로 둔다 (침묵으로 기울지 않는다)",
      G.prune_done_steps(["메모장 열기", "계산기 열기"], [HumanMessage("두 개 열어줘")])
      == ["메모장 열기", "계산기 열기"])
check("[BL-51] succeeded_danger는 **성공한 것만** 센다",
      G.succeeded_danger(_m51[:2] + [ToolMessage(content="✗ 파일을 찾지 못했어요.",
                                                 tool_call_id="p51")]) == [])

# [끝단] 대본 7장면을 그대로 돌린다 — 빈 요약(실기에서 관측된 모양)까지 포함


# ⚠️ 이름이 반드시 `delete_file`이어야 한다 — `DANGEROUS_TOOLS`에 들어 있는
#   이름으로만 hitl(승인)과 BL-32/BL-51 경로가 열린다. 다른 이름을 주면
#   테스트가 «통과»하는데 정작 본 경로를 한 줄도 안 지난다.
@tool("delete_file")
def _d51(file_path: str) -> str:
    """파일 삭제(mock)."""
    return "✓ '%s' 휴지통으로 옮겼어요." % os.path.basename(file_path)


class _Scene7:
    """1단계는 **도구 없이** 넘어가고(이미 열려 있다), 2단계에서 삭제한다.

    요약이 `empty`면 **빈 응답**이다 — `verify_output`이 본문을 도구 문장으로
    복원하는 경로이고, BL-51의 중복은 정확히 거기서 나왔다.
    """
    def __init__(self, empty): self.empty = empty; self.n = 0
    def bind_tools(self, t, **kw): return self
    def invoke(self, m):
        turn = G.current_turn_messages(m)
        done = {c["name"] for x in turn if isinstance(x, AIMessage)
                for c in (getattr(x, "tool_calls", None) or [])}
        if "delete_file" in done:
            return AIMessage(content="" if self.empty else "네, 지웠어요.")
        if any(isinstance(x, AIMessage) and not getattr(x, "tool_calls", None)
               for x in turn):
            self.n += 1
            return AIMessage(content="", tool_calls=[
                {"name": "delete_file", "args": {"file_path": _P51},
                 "id": "s7_%d" % self.n, "type": "tool_call"}])
        return AIMessage(content="메모장은 이미 열려 있어요.")     # ← 도구 0개


for _empty, _label in ((True, "빈 요약"), (False, "요약 있음")):
    _g51 = G.build_pluiz_graph(
        llm=_Scene7(_empty), tools=[_d51],
        security_check=lambda t: (False, ""), fast_resolve=lambda t: None,
        plan_decompose=lambda t: ["메모장 열기", "test.txt 파일 지우기"],
        target_exists=lambda *a, **k: True)
    _c51 = {"configurable": {"thread_id": "bl51_%s" % _empty}}
    _g51.invoke({"messages": [HumanMessage("메모장 열고 test.txt 파일 지워줘")]}, _c51)
    _body = _g51.invoke(Command(resume="어"), _c51)["messages"][-1].content

    check("🚨 [BL-51/%s] 지운 것을 «못 했다»고 하지 않는다" % _label,
          "못 했어요: 'test.txt 파일 지우기'" not in _body, f"→ {_body!r}")
    check("🚨 [BL-51/%s] 같은 삭제를 두 번 말하지 않는다" % _label,
          _body.count("휴지통으로 옮겼어요") <= 1, f"→ {_body!r}")
    check("[BL-51/%s] 그래도 삭제 사실은 남는다 (BL-32를 되돌리지 않는다)" % _label,
          "test.txt" in _body, f"→ {_body!r}")


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
