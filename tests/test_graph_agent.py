"""
P1.5-c PluizGraphAgent 오케스트레이터 검증 (동기 그래프, async 오케스트레이터, mock)
실행: python test_graph_agent.py
"""
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
    def __init__(self, t=30): self.agent_timeout = t

def fake_security(text):
    if "rm -rf" in text: return True, "⚠️ 보안 차단: 위험 명령"
    return False, ""

def fake_fast_resolve(text):
    if "메모장" in text and ("켜" in text or "열" in text):
        return "메모장을 실행했어요."
    return None


def make_agent(llm=None, timeout=30):
    mem = MockMem()
    agent = GA.PluizGraphAgent(
        llm=llm or FakeLLM(), tools=[],
        security_check=fake_security,
        fast_resolve=fake_fast_resolve,
        session_memory=mem,
        settings=FakeSettings(timeout),
    )
    return agent, mem


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

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run()) else 1)
