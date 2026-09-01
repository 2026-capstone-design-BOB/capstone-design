"""
P2-3 오케스트레이터 레벨 HITL 흐름 검증 (실제 사용 경로, mock)
- run_async("삭제해줘") → 질문 반환(미실행)
- run_async("응")      → 실행 (resume)
- run_async("아니")    → 취소
실행: python test_hitl_agent.py
"""
import sys, os, asyncio, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod
    spec.loader.exec_module(mod); return mod

base = os.path.join(os.path.dirname(__file__), "core")
_load("core.graph", os.path.join(base, "graph.py"))
_load("core.fast_path", os.path.join(base, "fast_path.py"))
GA = _load("core.graph_agent", os.path.join(base, "graph_agent.py"))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

executed = []

@tool
def delete_file(file_path: str) -> str:
    """파일 삭제(mock)."""
    executed.append(file_path)
    return f"✓ '{file_path}' 삭제했어요."


class DeleteLLM:
    """실제 LLM처럼 '마지막 메시지'로 판단: 도구실행 직후(ToolMessage)면 요약,
    사용자가 삭제 요청이면 삭제 도구콜."""
    _n = 0
    def bind_tools(self, tools): return self
    def invoke(self, messages):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            return AIMessage(content="삭제 완료했어요.")
        # 가장 최근 사용자 발화 확인
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                if "삭제" in str(m.content):
                    DeleteLLM._n += 1
                    return AIMessage(content="", tool_calls=[{
                        "name": "delete_file",
                        "args": {"file_path": "바탕화면/test.txt"},
                        "id": f"c{DeleteLLM._n}", "type": "tool_call"}])
                break
        return AIMessage(content="네.")

class MockMem:
    def __init__(self): self.saved = []
    def save(self, u, a): self.saved.append((u, a))

class FakeSettings:
    agent_timeout = 30

def fake_security(text): return (False, "")
def fake_fast_resolve(text): return None


def make():
    mem = MockMem()
    return GA.PluizGraphAgent(
        llm=DeleteLLM(), tools=[delete_file],
        security_check=fake_security, fast_resolve=fake_fast_resolve,
        session_memory=mem, settings=FakeSettings()), mem


async def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    print("=== 승인 흐름 ===")
    executed.clear()
    agent, mem = make()
    q = await agent.run_async("바탕화면 test.txt 삭제해줘", "h1")
    check("질문 반환(삭제 여부)", "삭제" in q and "test.txt" in q)
    check("아직 미실행", executed == [])
    check("대기 중엔 세션 저장 안 함", len(mem.saved) == 0)
    r = await agent.run_async("응 해줘", "h1")
    check("승인 후 실제 실행", executed == ["바탕화면/test.txt"])
    check("완료 응답", "완료" in r or "삭제" in r)

    print("=== 거부 흐름 ===")
    executed.clear()
    agent2, _ = make()
    await agent2.run_async("바탕화면 test.txt 삭제해줘", "h2")
    r2 = await agent2.run_async("아니 하지마", "h2")
    check("거부 시 미실행", executed == [])
    check("취소 응답", "취소" in r2)

    print("=== 승인 후 일반 명령 정상(대기 해제 확인) ===")
    # 승인 완료 후 같은 thread에서 새 명령이 재개로 오인되지 않아야
    executed.clear()
    agent3, _ = make()
    await agent3.run_async("test.txt 삭제해줘", "h3")   # 질문
    await agent3.run_async("응", "h3")                  # 실행 완료 → 대기 해제
    r3 = await agent3.run_async("test.txt 삭제해줘", "h3")  # 다시 질문이어야
    check("대기 해제 후 새 삭제요청 → 다시 질문", "삭제" in r3 and "test.txt" in r3)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run()) else 1)
