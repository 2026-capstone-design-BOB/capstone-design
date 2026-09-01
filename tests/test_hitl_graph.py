"""
P2-2 그래프 HITL(interrupt) 검증 (동기 invoke, mock)
- 위험 도구(delete_file) → interrupt(질문)
- resume '응' → 실행 / resume '아니' → 취소
실행: python test_hitl_graph.py
"""
import sys, os, importlib.util
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

spec = importlib.util.spec_from_file_location(
    "pluiz_graph", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "graph.py"))
G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

executed = []

@tool
def delete_file(file_path: str) -> str:
    """파일 삭제(mock)."""
    executed.append(file_path)
    return f"✓ '{file_path}' 삭제했어요."


class FakeLLM:
    """첫 호출: delete_file 도구콜. ToolMessage 있으면 요약. 동기 invoke."""
    def bind_tools(self, tools): return self
    def invoke(self, messages):
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="삭제 완료했어요.")
        return AIMessage(content="", tool_calls=[{
            "name": "delete_file",
            "args": {"file_path": "바탕화면/test.txt"},
            "id": "call_1", "type": "tool_call",
        }])

def fake_security(text): return (False, "")
def fake_fast_resolve(text): return None


def build():
    return G.build_pluiz_graph(
        llm=FakeLLM(), tools=[delete_file],
        security_check=fake_security, fast_resolve=fake_fast_resolve)


def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    print("=== 승인: 삭제 → 질문 → '응' → 실행 ===")
    executed.clear()
    g = build()
    cfg = {"configurable": {"thread_id": "approve"}}
    r1 = g.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg)
    itr = r1.get("__interrupt__")
    check("interrupt 발생(멈춤)", bool(itr))
    q = itr[0].value.get("question", "") if itr else ""
    check("질문에 파일명 포함", "test.txt" in q and "삭제" in q)
    check("아직 미실행", executed == [])
    r2 = g.invoke(Command(resume="응 삭제해줘"), cfg)
    check("승인 후 실제 실행됨", executed == ["바탕화면/test.txt"])
    check("완료 응답", "완료" in G.extract_response(r2) or "삭제" in G.extract_response(r2))

    print("=== 거부: 삭제 → 질문 → '아니' → 취소 ===")
    executed.clear()
    g2 = build()
    cfg2 = {"configurable": {"thread_id": "reject"}}
    g2.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg2)
    r3 = g2.invoke(Command(resume="아니 취소해"), cfg2)
    check("거부 시 미실행", executed == [])
    check("취소 응답", "취소" in G.extract_response(r3))

    print("=== interpret_confirmation ===")
    check("'응' → True", G.interpret_confirmation("응") is True)
    check("'아니' → False", G.interpret_confirmation("아니") is False)
    check("'아니 삭제해'(모순) → False", G.interpret_confirmation("아니 삭제해") is False)
    check("'글쎄'(애매) → False(안전)", G.interpret_confirmation("글쎄") is False)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
