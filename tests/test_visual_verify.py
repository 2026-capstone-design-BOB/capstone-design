"""
실행 결과 시각적 검증(visual_verify) 검증 — mock (LLM·Windows·API 불필요)
실행: python tests/test_visual_verify.py

이 노드가 지키기로 한 **계약**을 확인한다. Vision을 실제로 부르지 않고, 호출 횟수와
인자를 세는 가짜 `visual_check`를 주입한다(core/graph.py는 DI로 만들어져 있다).

여기서 보는 것:
  - 증거가 도구 결과에 **붙는가** (원본 문구를 지우지 않고)
  - Vision을 **부르지 말아야 할 때 안 부르는가** (1회 8초짜리다)
  - Vision이 "안 됐다"고 해도 **응답을 조작하거나 재시도하지 않는가** ← 이번 설계의 핵심
  - 검증이 실패해도 **본 명령이 살아남는가**

⚠️ 이 프로젝트는 "설계대로 도는지만 보고 그 설계가 맞는지는 묻지 않은" 테스트에
   두 번 데였다(2026-09-02). 그래서 아래는 노드가 **하지 않기로 한 것**을 더 많이 본다.
"""
import sys, os, importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# core/__init__ 을 거치지 않고 graph.py 만 직접 로드 (test_hitl_graph.py와 같은 방식)
spec = importlib.util.spec_from_file_location(
    "pluiz_graph", os.path.join(_ROOT, "core", "graph.py"))
G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

passed = total = 0

def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


# ── 가짜 도구 ─────────────────────────────────────────────────────
typed = []
opened = []
fail_next = {"on": False}

@tool
def type_text(text: str, target: str = "") -> str:
    """텍스트 입력(mock)."""
    typed.append(text)
    if fail_next["on"]:
        return f"✗ '{target}' 창을 앞으로 가져오지 못해 입력하지 않았습니다."
    return f"✓ '{target}' 창에 입력했습니다: '{text}'"

@tool
def open_app(app: str, new: bool = False) -> str:
    """앱 실행(mock)."""
    opened.append(app)
    return f"✓ {app} 창을 앞으로 가져왔습니다."

@tool
def get_current_time() -> str:
    """현재 시각(mock) — 화면 검증 대상이 아니다."""
    return "지금은 오후 3시예요."


class FakeVision:
    """화면을 보는 척하는 mock. 호출 횟수와 인자를 기록한다."""
    def __init__(self, answer="메모장 본문에 '회의록'이라고 적혀 있습니다.", boom=False):
        self.answer, self.boom = answer, boom
        self.calls = []
    def __call__(self, window, question):
        self.calls.append((window, question))
        if self.boom:
            raise RuntimeError("Vision API 쿼터 초과(테스트)")
        return self.answer


class FakeLLM:
    """이번 턴에 ToolMessage가 있으면 요약, 없으면 발화에 맞는 도구를 부른다.

    ⚠️ 턴 단위로 판단한다(test_hitl_graph.py의 FakeLLM과 같은 이유) — 히스토리
      전체를 보면 한 thread의 두 번째 명령부터 도구를 못 부른다.
    """
    _n = 0
    def __init__(self, calls_per_turn=1):
        self.calls_per_turn = calls_per_turn
    def bind_tools(self, tools): return self
    def invoke(self, messages):
        turn = G.current_turn_messages(messages)
        tool_msgs = [m for m in turn if isinstance(m, ToolMessage)]
        human = next((m for m in turn if isinstance(m, HumanMessage)), None)
        text = str(getattr(human, "content", "")) if human else ""

        # 한 턴에 도구를 두 번 부르는 시나리오(턴당 1회 검증 확인용)
        if tool_msgs and len(tool_msgs) < self.calls_per_turn:
            return self._call("type_text", {"text": f"두번째-{len(tool_msgs)}", "target": "메모장"})
        if tool_msgs:
            # 마지막 도구 결과를 그대로 옮긴다 — 증거가 LLM에 도달했는지 볼 수 있다
            return AIMessage(content=f"결과: {tool_msgs[-1].content}")

        if "적어" in text or "입력" in text:
            return self._call("type_text", {"text": "회의록", "target": "메모장"})
        if "열어" in text:
            return self._call("open_app", {"app": "메모장"})
        if "몇 시" in text:
            return self._call("get_current_time", {})
        return AIMessage(content="네, 처리했어요.")

    def _call(self, name, args):
        FakeLLM._n += 1
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": args,
            "id": f"call_{FakeLLM._n}", "type": "tool_call",
        }])


def build(visual_check, calls_per_turn=1):
    return G.build_pluiz_graph(
        llm=FakeLLM(calls_per_turn), tools=[type_text, open_app, get_current_time],
        security_check=lambda t: (False, ""), fast_resolve=lambda t: None,
        visual_check=visual_check)


def run(g, text, thread):
    return g.invoke({"messages": [HumanMessage(text)]},
                    {"configurable": {"thread_id": thread}})


def tool_contents(result):
    return [str(m.content) for m in result["messages"] if isinstance(m, ToolMessage)]


# ══════════════════════════════════════════════════════════════════
print("=== ① 질문 생성 (순수 함수) ===")

q = G.build_visual_question("type_text", {"text": "회의록 초안", "target": "메모장"})
check("type_text → **의도한 창**을 캡처 (활성창 아님)", q and q[0] == "메모장", f"→ {q}")
check("질문에 입력한 내용이 들어간다", q and "회의록 초안" in q[1], f"→ {q}")
check("비어 있으면 비었다고 말하라는 지시", q and "비어 있" in q[1])
check("다른 내용만 있으면 그걸 말하라는 지시", q and "다른 내용" in q[1], f"→ {q}")

# ⚠️ 2026-09-03 실기에서 데인 지점. 예전엔 "활성창"을 찍었는데, type_text는 애초에
#    활성창에 글자를 넣는다 → 글자가 간 그 창을 그대로 확인하니 **항상 "있다"**.
#    실제로 Pluiz 오버레이 입력창에 들어간 "회의록"을 보고 "됐다"고 확인해 줬다.
check("⚠️ target이 없으면 **검증하지 않는다** (순환 방지)",
      G.build_visual_question("type_text", {"text": "회의록"}) is None)
check("target이 공백뿐이어도 검증하지 않는다",
      G.build_visual_question("type_text", {"text": "회의록", "target": "  "}) is None)
check("질문 어디에도 '활성창'을 쓰지 않는다",
      q and "활성창" not in q[0] and "활성창" not in q[1], f"→ {q}")

check("검증 대상 아닌 도구는 None", G.build_visual_question("get_current_time", {}) is None)
check("text가 비면 None (물을 게 없다)",
      G.build_visual_question("type_text", {"text": "", "target": "메모장"}) is None)

print("\n=== ② 검증 대상 집합 ===")
check("type_text 포함 (BL-12)", "type_text" in G.VISUAL_VERIFY_TOOLS)
# open_app을 뺐다 — take_screenshot(window=앱)은 그 창만 찍으므로 이미지만 봐서는
# 맨 앞인지 가려졌는지 알 수 없다. 답할 수 없는 걸 묻는 검증이었다.
check("⚠️ open_app 제외 — Vision이 답할 수 없는 물음이었다",
      "open_app" not in G.VISUAL_VERIFY_TOOLS)
check("⚠️ describe_screen 제외 — 자기 자신을 검증하면 재귀가 된다",
      "describe_screen" not in G.VISUAL_VERIFY_TOOLS)
check("삭제 도구는 대상 아님 (승인은 HITL이 이미 받는다)",
      not (G.VISUAL_VERIFY_TOOLS & G.DANGEROUS_TOOLS))


print("\n=== ③ 정상 경로 — 증거가 도구 결과에 붙는다 ===")
typed.clear()
v = FakeVision()
r = run(build(v), "메모장에 회의록이라고 적어줘", "t3")
tc = tool_contents(r)
check("Vision 호출 정확히 1회", len(v.calls) == 1, f"→ {len(v.calls)}회")
check("의도한 창(메모장)을 찍었다 — 활성창이 아니다",
      v.calls and v.calls[0][0] == "메모장", f"→ {v.calls[:1]}")
check("[화면 확인] 증거가 붙었다", any("[화면 확인]" in c for c in tc), f"→ {tc}")
check("원본 도구 결과를 지우지 않았다",
      any("창에 입력했습니다" in c for c in tc), f"→ {tc}")
check("도구가 **어느 창에** 넣었는지 밝힌다", any("'메모장'" in c for c in tc), f"→ {tc}")
check("ToolMessage가 늘지 않았다 (교체이지 추가가 아니다)", len(tc) == 1, f"→ {len(tc)}개")
check("증거가 LLM에 도달했다", "[화면 확인]" in G.extract_response(r), f"→ {G.extract_response(r)[:80]}")

print("\n=== ④ open_app은 더 이상 Vision을 부르지 않는다 ===")
opened.clear()
v = FakeVision()
r = run(build(v), "메모장 열어줘", "t4")
check("open_app 턴 → Vision 호출 0회 (8초 절약)", len(v.calls) == 0, f"→ {len(v.calls)}회")
check("앱은 정상 실행", opened == ["메모장"], f"→ {opened}")
check("응답 정상", bool(G.extract_response(r).strip()))


print("\n=== ⑤ 부르지 말아야 할 때 — Vision 1회는 8초다 ===")

fail_next["on"] = True
v = FakeVision()
r = run(build(v), "메모장에 회의록이라고 적어줘", "t5a")
fail_next["on"] = False
check("도구가 이미 ✗로 실패를 자백 → 호출 0회", len(v.calls) == 0, f"→ {len(v.calls)}회")
check("실패 문구는 그대로 남는다", any("✗" in c for c in tool_contents(r)))

v = FakeVision()
run(build(v), "지금 몇 시야", "t5b")
check("검증 대상 아닌 도구(get_current_time) → 호출 0회", len(v.calls) == 0, f"→ {len(v.calls)}회")

v = FakeVision()
run(build(v), "고마워", "t5c")   # 도구 자체를 안 쓰는 턴
check("도구를 아예 안 쓴 턴 → 호출 0회", len(v.calls) == 0, f"→ {len(v.calls)}회")

v = FakeVision()
run(build(v, calls_per_turn=2), "메모장에 회의록이라고 적어줘", "t5d")
check("한 턴에 도구를 두 번 써도 → 호출 1회 (턴당 1회)", len(v.calls) == 1, f"→ {len(v.calls)}회")

v = FakeVision()
g = build(v)
run(g, "메모장에 회의록이라고 적어줘", "t5e")
run(g, "메모장에 회의록이라고 적어줘", "t5e")     # 같은 thread, 다음 턴
check("다음 턴에는 플래그가 리셋돼 다시 검증한다 → 2회",
      len(v.calls) == 2, f"→ {len(v.calls)}회")


print("\n=== ⑥ 검증이 실패해도 본 명령은 살아남는다 ===")
typed.clear()
v = FakeVision(boom=True)
r = run(build(v), "메모장에 회의록이라고 적어줘", "t6a")
check("Vision이 예외를 던져도 그래프가 완주한다", bool(G.extract_response(r).strip()))
check("도구는 정상 실행됐다", typed == ["회의록"], f"→ {typed}")
check("증거는 안 붙는다 (못 본 걸 봤다고 하지 않는다)",
      not any("[화면 확인]" in c for c in tool_contents(r)))

v = FakeVision(answer="✗ 화면을 캡처하지 못했습니다.")
r = run(build(v), "메모장에 회의록이라고 적어줘", "t6b")
check("Vision이 ✗를 반환하면 증거로 붙이지 않는다",
      not any("[화면 확인]" in c for c in tool_contents(r)), f"→ {tool_contents(r)}")

v = FakeVision(answer="   ")
r = run(build(v), "메모장에 회의록이라고 적어줘", "t6c")
check("Vision 응답이 비면 증거로 붙이지 않는다",
      not any("[화면 확인]" in c for c in tool_contents(r)))


print("\n=== ⑦ 정직 보고 계약 — 판정도 재시도도 하지 않는다 ===")
typed.clear()
v = FakeVision(answer="메모장 본문은 0자로, 비어 있습니다.")
r = run(build(v), "메모장에 회의록이라고 적어줘", "t7")
resp = G.extract_response(r)
check("도구를 다시 실행하지 않는다 (자동 재시도 없음)", typed == ["회의록"], f"→ {typed}")
check("반박 증거가 응답까지 전달된다", "비어 있습니다" in resp, f"→ {resp[:90]}")
check("노드가 응답을 '실패'로 바꿔치지 않는다 — 문구는 agent 몫",
      "실행 중 문제가 생겼어요" not in resp, f"→ {resp[:90]}")


print("\n=== ⑧ visual_check 미주입 = 예전 그대로 ===")
typed.clear()
r = run(build(None), "메모장에 회의록이라고 적어줘", "t8")
check("증거가 붙지 않는다", not any("[화면 확인]" in c for c in tool_contents(r)))
check("도구는 정상 실행", typed == ["회의록"], f"→ {typed}")
check("응답 정상", bool(G.extract_response(r).strip()))
check("visual_verify 노드가 그래프에 없다",
      "visual_verify" not in build(None).get_graph().nodes)
check("주입하면 노드가 생긴다",
      "visual_verify" in build(FakeVision()).get_graph().nodes)


print("\n=== ⑨ 아무 일도 안 일어난 턴은 '실행했다'고 하지 않는다 ===")
# 2026-09-03 실기: "메모장 새로 열어줘" → "명령을 실행했습니다." 인데 새 탭은 안 열렸다.
# LLM 응답이 비었고 이번 턴에 도구도 안 돌았으면 **아무 일도 없었던 것**이다.
from langchain_core.messages import AIMessage as _AI, HumanMessage as _H, ToolMessage as _T

r = G.verify_output([_H("메모장 새로 열어줘"), _AI(content="")])
check("도구도 응답도 없음 → '실행했습니다'라고 하지 않는다",
      r is not None and "실행했" not in r, f"→ {r}")
check("처리하지 못했다고 말한다", r and "처리하지 못했" in r, f"→ {r}")
check("다시 말해 달라고 안내한다", r and "다시" in r, f"→ {r}")

# 도구가 돌았으면 예전처럼 그 결과로 복원한다 (회귀 확인)
r2 = G.verify_output([_H("메모장 열어줘"),
                      _AI(content="", tool_calls=[{"name": "open_app", "args": {},
                                                   "id": "c1", "type": "tool_call"}]),
                      _T(content="✓ 메모장을 실행했습니다.", tool_call_id="c1"),
                      _AI(content="")])
check("도구가 돌았으면 그 결과로 복원한다", r2 == "✓ 메모장을 실행했습니다.", f"→ {r2}")


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
