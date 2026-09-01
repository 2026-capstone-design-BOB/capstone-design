"""
P1.5-b 그래프 노드 검증 (동기, mock — OS·API 불필요)
- A: 맥락 유지 (캐시 처리 명령 → 후속 지칭)
- B: 보안 차단
- C: verify_output (도구오류 보정 + 빈응답 복구)
실행: python test_graph_context.py
"""
import sys, os, importlib.util
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

spec = importlib.util.spec_from_file_location(
    "pluiz_graph", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "graph.py"))
G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class FakeLLM:
    """히스토리에 '메모장'이 있고 '그거'면 맥락 인지 응답. 동기 invoke."""
    def __init__(self): self.called = 0; self.last_messages = None
    def bind_tools(self, tools): return self
    def invoke(self, messages):
        self.called += 1; self.last_messages = messages
        hist = " ".join(str(getattr(m, "content", "")) for m in messages)
        last_human = ""
        for m in reversed(messages):
            if isinstance(m, HumanMessage): last_human = str(m.content); break
        if "그거" in last_human and "메모장" in hist:
            return AIMessage(content="메모장을 종료했어요.")
        if "그거" in last_human:
            return AIMessage(content="무엇을 닫을까요?")
        return AIMessage(content="네, 처리했어요.")


def fake_security(text):
    if "rm -rf" in text: return True, "⚠️ 보안 차단: 위험 명령"
    return False, ""

def fake_fast_resolve(text):
    if "메모장" in text and ("켜" in text or "열" in text):
        return "메모장을 실행했어요."
    return None


def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    print("=== A. 캐시 처리 → 후속 지칭 (맥락) ===")
    llm = FakeLLM()
    graph = G.build_pluiz_graph(llm=llm, tools=[],
                                security_check=fake_security,
                                fast_resolve=fake_fast_resolve)
    cfg = {"configurable": {"thread_id": "t1"}}
    s1 = graph.invoke({"messages": [HumanMessage("메모장 켜줘")]}, cfg)
    check("턴1 캐시 처리(LLM 미호출)", llm.called == 0)
    check("턴1 응답 메모장 실행", "메모장" in G.extract_response(s1))
    s2 = graph.invoke({"messages": [HumanMessage("그거 닫아줘")]}, cfg)
    r2 = G.extract_response(s2)
    check("턴2 LLM 호출됨", llm.called == 1)
    hist = " ".join(str(getattr(m, "content", "")) for m in llm.last_messages)
    check("턴2 히스토리에 메모장 포함", "메모장" in hist)
    check("턴2 맥락 복원 응답", "메모장" in r2 and "종료" in r2)

    print("=== B. 보안 차단 ===")
    llm2 = FakeLLM()
    g2 = G.build_pluiz_graph(llm=llm2, tools=[], security_check=fake_security,
                             fast_resolve=fake_fast_resolve)
    sb = g2.invoke({"messages": [HumanMessage("rm -rf / 해줘")]},
                   {"configurable": {"thread_id": "t2"}})
    check("차단 사유 응답", "차단" in G.extract_response(sb))
    check("차단 시 LLM 미호출", llm2.called == 0)

    print("=== C. verify_output ===")
    msgs1 = [HumanMessage("메모장 열어줘"),
             ToolMessage(content="[오류] 앱을 찾을 수 없습니다", tool_call_id="x"),
             AIMessage(content="메모장을 실행했어요.")]
    out1 = G.verify_output(msgs1)
    check("도구오류+성공응답 → 보정됨", out1 is not None and "문제가 생겼어요" in out1)
    msgs2 = [HumanMessage("계산기 열어줘"), AIMessage(content="계산기를 실행했어요.")]
    check("정상 응답 → None", G.verify_output(msgs2) is None)
    msgs3 = [HumanMessage("배터리 확인"),
             ToolMessage(content="배터리 82%입니다", tool_call_id="y"),
             AIMessage(content="")]
    check("빈 응답 → ToolMessage 복원", G.verify_output(msgs3) == "배터리 82%입니다")

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
