"""
P1.5-c PluizGraphAgent 오케스트레이터 검증 (동기 그래프, async 오케스트레이터, mock)
실행: python test_graph_agent.py
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
import sys, os, asyncio, time, importlib.util
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
_load("core.graph", os.path.join(base, "graph.py"))
_load("core.fast_path", os.path.join(base, "fast_path.py"))
GA = _load("core.graph_agent", os.path.join(base, "graph_agent.py"))

from langchain_core.messages import AIMessage, HumanMessage


class FakeLLM:
    def __init__(self): self.called = 0
    def bind_tools(self, tools): return self
    def invoke(self, messages):
        self.called += 1
        hist = " ".join(str(getattr(m, "content", "")) for m in messages)
        last = ""
        for m in reversed(messages):
            if isinstance(m, HumanMessage): last = str(m.content); break
        if "그거" in last and "메모장" in hist:
            return AIMessage(content="메모장을 종료했어요.")
        if "그거" in last:
            return AIMessage(content="무엇을 닫을까요?")
        return AIMessage(content="네, 처리했어요.")

class SlowLLM(FakeLLM):
    def invoke(self, messages):
        time.sleep(3)  # 타임아웃 유발
        return super().invoke(messages)

class MockMem:
    def __init__(self): self.saved = []
    def save(self, u, a): self.saved.append((u, a))

class FakeSettings:
    def __init__(self, t=30, plan=False):
        self.agent_timeout = t
        self.plan_enabled = plan        # settings로 켜지는 경로(제품 분해기)를 보기 위해


class PlanLLM(FakeLLM):
    """분해 요청이면 번호 목록을, 아니면 평범한 답을 준다.

    ⚠️ mock 스위트에서 **제품 분해기(_prod_plan_decompose)를 실제로 지나가는 유일한
      자리**다. 여기가 없으면 프롬프트 상수나 응답 추출이 깨져도 아무도 모른다.
    """
    def invoke(self, messages):
        self.called += 1
        head = str(getattr(messages[0], "content", ""))
        if "실행 순서대로 나누는 도구" in head:
            return AIMessage(content="1. 메모장 열기\n2. 계산기 열기")
        return AIMessage(content="네, 처리했어요.")

def fake_security(text):
    if "rm -rf" in text: return True, "⚠️ 보안 차단: 위험 명령"
    return False, ""

def fake_fast_resolve(text):
    if "메모장" in text and ("켜" in text or "열" in text):
        return "메모장을 실행했어요."
    return None


def make_agent(llm=None, timeout=30, plan_decompose=None):
    mem = MockMem()
    agent = GA.PluizGraphAgent(
        llm=llm or FakeLLM(), tools=[],
        security_check=fake_security,
        fast_resolve=fake_fast_resolve,
        session_memory=mem,
        settings=FakeSettings(timeout),
        plan_decompose=plan_decompose,
    )
    return agent, mem


def spy_limit(agent, seen):
    """이 실행이 어떤 recursion_limit으로 돌았는지 기록한다."""
    orig = agent._invoke_sync
    def _spy(payload, config):
        seen["limit"] = config.get("recursion_limit")
        return orig(payload, config)
    agent._invoke_sync = _spy
    return agent


async def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    print("=== A. run_async + 맥락 + 세션저장 ===")
    llm = FakeLLM()
    agent, mem = make_agent(llm)
    r1 = await agent.run_async("메모장 켜줘", "s1")
    check("턴1 캐시 처리(LLM 미호출)", llm.called == 0 and "메모장" in r1)
    r2 = await agent.run_async("그거 닫아줘", "s1")
    check("턴2 맥락 복원(메모장 종료)", "메모장" in r2 and "종료" in r2)
    check("세션메모리 2건 저장", len(mem.saved) == 2)

    print("=== B. 보안 차단 ===")
    agent2, _ = make_agent(FakeLLM())
    rb = await agent2.run_async("rm -rf / 해줘", "s2")
    check("보안 차단 응답", "차단" in rb)

    print("=== C. 타임아웃 ===")
    agent3, _ = make_agent(SlowLLM(), timeout=1)
    rc = await agent3.run_async("복잡한 명령 처리해줘", "s3")
    check("타임아웃 → 친절 메시지", "오래 걸려" in rc)

    print("=== D. stream() 동일 API ===")
    agent4, _ = make_agent(FakeLLM())
    chunks = [c async for c in agent4.stream("메모장 켜줘", "s4")]
    check("stream 청크 반환", len(chunks) == 1 and "메모장" in chunks[0])

    print("=== E. 계획 수립(M3) 배선 ===")
    # ⚠️ recursion_limit을 안 올리면 2단계 계획이 곧바로 GraphRecursionError다
    #    (도구 1회에 6 슈퍼스텝, 이후 1회마다 +2 → 10은 도구 3회에서 소진).
    #    반대로 꺼져 있을 땐 올리지 않는다 — 폭주 루프가 2.4배 오래 돈다.
    seen_off = {}
    agent5, _ = make_agent(FakeLLM())
    check("계획은 기본 OFF (분해기 미주입 · settings.plan_enabled 없음)",
          agent5.plan_decompose is None)
    await spy_limit(agent5, seen_off).run_async("아무거나 해줘", "s5")
    check("OFF면 recursion_limit은 예전 그대로 10", seen_off.get("limit") == 10)

    seen_on = {}
    agent6, _ = make_agent(FakeLLM(), plan_decompose=lambda t: None)
    await spy_limit(agent6, seen_on).run_async("아무거나 해줘", "s6")
    check("계획이 켜지면 recursion_limit 24 (ADR §1-1)", seen_on.get("limit") == 24)

    # settings.plan_enabled=True 로 켜지는 **제품 경로**. 분해기를 주입하지 않는다.
    mem7 = MockMem()
    agent7 = GA.PluizGraphAgent(
        llm=PlanLLM(), tools=[], security_check=fake_security,
        fast_resolve=lambda t: None, session_memory=mem7,
        settings=FakeSettings(plan=True))
    check("settings.plan_enabled=True면 제품 분해기가 배선된다",
          agent7.plan_decompose is not None)
    r7 = await agent7.run_async("메모장 열고 계산기도 열어줘", "s7")
    # 도구가 없는 에이전트라 1단계에서 더 나아가지 못한다 → **그 사실을 말해야 한다.**
    check("못 한 단계를 응답 끝에 정직하게 붙인다",
          "못 했어요" in r7 and "계산기 열기" in r7)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run()) else 1)
