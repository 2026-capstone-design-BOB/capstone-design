"""
P4-2 학습 연결 검증 (오케스트레이터, mock)
실행: python test_cache_wire.py
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
import sys, os, asyncio, importlib.util, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
core_pkg = types.ModuleType("core"); core_pkg.__path__ = [base]; sys.modules["core"] = core_pkg
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s)
    sys.modules[n] = m; s.loader.exec_module(m); return m
_load("core.security", os.path.join(base, "security.py"))
_load("core.graph", os.path.join(base, "graph.py"))
_load("core.fast_path", os.path.join(base, "fast_path.py"))
GA = _load("core.graph_agent", os.path.join(base, "graph_agent.py"))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class MockCache:
    def __init__(self): self.learned = []
    def learn(self, user_input, tool_calls):
        # 실제 정책 근사: 단일 화이트리스트 + 파라미터 없음만 수용
        WL = {"open_app", "take_screenshot", "volume_up"}
        if len(tool_calls) == 1 and tool_calls[0]["name"] in WL:
            args = tool_calls[0].get("args", {})
            if all(k == "app" or (k == "amount" and str(v) == "10") for k, v in args.items()):
                self.learned.append(user_input); return True
        return False

class OpenLLM:
    """앱 열기 도구콜 생성 → ToolMessage 성공 → 요약."""
    def __init__(self, tool="open_app", args=None, err=False):
        self.tool = tool; self.args = args or {"app": "메모장"}; self.err = err
    def bind_tools(self, t): return self
    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="실행했어요.")
        return AIMessage(content="", tool_calls=[{"name": self.tool, "args": self.args,
                                                  "id": "c1", "type": "tool_call"}])

class ScriptedLLM:
    """턴마다 다르게 행동하는 LLM mock.

    plan[i] = (tool_name, args)  → 그 턴에 해당 도구를 호출
    plan[i] = None               → 그 턴엔 도구 없이 텍스트만 답함

    ⚠️ 턴 판정은 **마지막 HumanMessage 이후**를 본다. 전체 히스토리에서
      ToolMessage 유무를 보면(기존 OpenLLM 방식) 2턴째부터 도구를 못 부른다.
    """
    def __init__(self, plan): self.plan = plan
    def bind_tools(self, t): return self
    def invoke(self, messages):
        idx = -1
        for i, m in enumerate(messages):
            if isinstance(m, HumanMessage):
                idx = i
        turn_msgs = messages[idx:] if idx >= 0 else messages
        turn_no = sum(1 for m in messages if isinstance(m, HumanMessage)) - 1
        if any(isinstance(m, ToolMessage) for m in turn_msgs):
            return AIMessage(content="처리했어요.")          # 이번 턴 도구 실행 후 요약
        step = self.plan[turn_no] if 0 <= turn_no < len(self.plan) else None
        if step is None:
            return AIMessage(content="네, 알겠어요.")        # 도구 없는 잡담 턴
        name, args = step
        return AIMessage(content="", tool_calls=[{"name": name, "args": args,
                                                  "id": "c" + str(turn_no), "type": "tool_call"}])


class ToolNodeFake:
    """ToolMessage를 넣어주는 가짜 tools 노드 대용 — 여기선 실제 도구 대신 성공/실패 메시지."""

class MockMem:
    def __init__(self): self.saved = []
    def save(self, u, a): self.saved.append((u, a))
class FakeSettings: agent_timeout = 30
def fake_sec(t): return (False, "")
def fake_fr(t): return None


def make(tool="open_app", args=None, tool_impl=None):
    from langchain_core.tools import tool as mktool
    cache = MockCache()
    # 실제 도구를 mock으로 (성공/실패 결정)
    agent = GA.PluizGraphAgent(
        llm=OpenLLM(tool, args), tools=[tool_impl] if tool_impl else [],
        security_check=fake_sec, fast_resolve=fake_fr,
        session_memory=MockMem(), settings=FakeSettings(), cache=cache)
    return agent, cache


async def run():
    from langchain_core.tools import tool as mktool
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    @mktool
    def open_app(app: str = "") -> str:
        """열기"""
        return f"✓ {app} 실행했어요."
    @mktool
    def create_folder(name: str = "", location: str = "") -> str:
        """폴더"""
        return f"✓ {name} 폴더 만들었어요."
    @mktool
    def open_app_fail(app: str = "") -> str:
        """실패"""
        return "✗ 앱을 찾을 수 없습니다"

    print("=== 1. 성공한 화이트리스트 명령 → 학습됨 ===")
    a, c = make("open_app", {"app": "메모장"}, open_app)
    await a.run_async("메모장 띄워봐", "s1")
    check("open_app 성공 → 학습", "메모장 띄워봐" in c.learned)

    print("=== 2. 파라미터 명령(폴더) → 학습 안 됨 ===")
    a, c = make("create_folder", {"name": "새폴더", "location": "desktop"}, create_folder)
    await a.run_async("새폴더 만들어줘", "s2")
    check("create_folder → 학습 거부", "새폴더 만들어줘" not in c.learned)

    print("=== 3. 실행 실패(✗) → 학습 안 됨 ===")
    a, c = make("open_app_fail", {"app": "없는앱"}, open_app_fail)
    await a.run_async("없는앱 열어줘", "s3")
    check("실패 도구 → 학습 거부", len(c.learned) == 0)

    # -- 다중 턴 — '이번 턴' 경계 (D-2 회귀) --------------------------
    # state["messages"]는 thread 전체 히스토리다. 예전엔 _maybe_learn이 그걸
    # 통째로 훑어서, 학습이 thread당 1턴만 정상 동작했다.
    def make_scripted(plan, tools):
        cache = MockCache()
        return GA.PluizGraphAgent(
            llm=ScriptedLLM(plan), tools=tools,
            security_check=fake_sec, fast_resolve=fake_fr,
            session_memory=MockMem(), settings=FakeSettings(), cache=cache), cache

    print("=== 4. 턴1 도구 → 턴2 잡담: 잡담이 학습되면 안 됨 ===")
    a, c = make_scripted([("open_app", {"app": "메모장"}), None], [open_app])
    await a.run_async("메모장 띄워봐", "m1")
    await a.run_async("고마워", "m1")
    check("턴1 명령은 학습됨", "메모장 띄워봐" in c.learned)
    check("턴2 잡담은 학습 안 됨", "고마워" not in c.learned)

    print("=== 5. 도구 호출이 쌓여도 학습이 멈추지 않음 ===")
    a, c = make_scripted([("open_app", {"app": "메모장"}),
                          ("open_app", {"app": "계산기"})], [open_app])
    await a.run_async("메모장 띄워봐", "m2")
    await a.run_async("계산기 띄워봐", "m2")
    check("턴2 명령도 학습됨", "계산기 띄워봐" in c.learned)

    print("=== 6. 과거 턴의 도구 실패가 이후 학습을 막지 않음 ===")
    a, c = make_scripted([("open_app_fail", {"app": "없는앱"}),
                          ("open_app", {"app": "메모장"})], [open_app, open_app_fail])
    await a.run_async("없는앱 열어줘", "m3")
    await a.run_async("메모장 띄워봐", "m3")
    check("실패한 턴1은 학습 안 됨", "없는앱 열어줘" not in c.learned)
    check("성공한 턴2는 학습됨", "메모장 띄워봐" in c.learned)

    print("=== 7. BL-21 — 복합 명령은 학습하지 않는다 ===")
    # 2026-09-07 라이브에서 실제로 이렇게 굳었다:
    #     "메모장이랑 계산기 열어줘" → [open_app(메모장)]   ← 계산기가 빠진 채로
    # 계획 2단계 중 하나를 건너뛰었는데 완료로 기록됐고(계획 2/2), 도구가 1개뿐이라
    # _is_learnable을 통과해 캐시에 박혔다. 그다음부터는 캐시 히트라 LLM을 거치지도
    # 않으므로 **틀린 답이 고쳐질 기회가 없다.**
    #
    # 통째로 막아도 잃는 게 없다 — 계획이 제대로 실행되면 도구가 2개 이상이라
    # 어차피 학습 대상이 아니다. 즉 여기 도달하는 복합 턴은 실패한 턴뿐이다.
    stub = types.SimpleNamespace(cache=MockCache())

    def learn_attempt(text, tool_calls, plan=None):
        """_maybe_learn만 떼어 부른다 — self.cache 말고는 쓰지 않는다."""
        stub.cache = MockCache()
        calls = [dict(c, id=f"c{i}", type="tool_call") for i, c in enumerate(tool_calls)]
        msgs = [HumanMessage(content=text),
                AIMessage(content="", tool_calls=calls),
                ToolMessage(content="✓ 실행했습니다.", tool_call_id="c0")]
        result = {"messages": msgs, "plan": plan or [], "plan_cursor": len(plan or [])}
        GA.PluizGraphAgent._maybe_learn(stub, text, result)
        return stub.cache.learned

    one = [{"name": "open_app", "args": {"app": "메모장"}}]

    check("단일 명령은 그대로 학습된다(회귀)",
          "메모장 띄워봐" in learn_attempt("메모장 띄워봐", one))

    check("계획이 선 턴은 학습하지 않는다 — 실기에서 굳었던 그 문장",
          "메모장이랑 계산기 열어줘" not in learn_attempt(
              "메모장이랑 계산기 열어줘", one, plan=["메모장 열기", "계산기 열기"]))

    check("삭제가 빠진 채 굳던 문장도 막힌다",
          "메모장 열고 testing.txt 지워달라고" not in learn_attempt(
              "메모장 열고 testing.txt 지워달라고", one,
              plan=["메모장 열기", "testing.txt 지우기"]))

    # 계획이 꺼져 있어도(plan 없음) 같은 일이 난다 — 발화로도 본다.
    check("계획이 꺼져 있어도 복합 발화는 학습하지 않는다",
          "메모장 열고 계산기도 열어줘" not in learn_attempt("메모장 열고 계산기도 열어줘", one))

    # 부정어 학습 거부는 덤이다(BL-02가 바라던 것).
    check("부정어가 든 발화도 학습하지 않는다",
          "크롬 말고 메모장 열어줘" not in learn_attempt("크롬 말고 메모장 열어줘", one))

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run()) else 1)
