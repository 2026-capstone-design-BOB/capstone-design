"""
P4-2 학습 연결 검증 (오케스트레이터, mock)
실행: python test_cache_wire.py
"""
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

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run()) else 1)
