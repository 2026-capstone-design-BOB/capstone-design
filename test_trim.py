"""
graph._prepare_messages trim 검증 — 도구호출/도구결과 쌍이 안 잘리는지
(Gemini 400 'function call turn...' 회귀 방지)
실행: python test_trim.py
"""
import sys, os, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "pluiz_graph", os.path.join(os.path.dirname(__file__), "core", "graph.py"))
G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage


def make_tool_turn(i):
    """한 턴: Human → AI(tool_call) → Tool → AI(요약)."""
    tcid = f"call_{i}"
    return [
        HumanMessage(content=f"파일 {i} 찾아줘"),
        AIMessage(content="", tool_calls=[{"name": "find_file", "args": {"name": f"f{i}"},
                                           "id": tcid, "type": "tool_call"}]),
        ToolMessage(content=f"파일 {i} 결과", tool_call_id=tcid),
        AIMessage(content=f"파일 {i} 찾았어요"),
    ]


def valid_sequence(msgs) -> bool:
    """Gemini 규칙 근사 검증: ToolMessage는 반드시 직전이 tool_calls를 가진 AIMessage.
    그리고 tool_calls를 가진 AIMessage 다음은 ToolMessage여야 함."""
    for idx, m in enumerate(msgs):
        if isinstance(m, ToolMessage):
            prev = msgs[idx-1] if idx > 0 else None
            if not (isinstance(prev, AIMessage) and getattr(prev, "tool_calls", None)):
                return False
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            nxt = msgs[idx+1] if idx+1 < len(msgs) else None
            if not isinstance(nxt, ToolMessage):
                return False
    return True


def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    # 10턴짜리 긴 기록(40개 메시지) — 도구 쌍 다수
    history = []
    for i in range(10):
        history += make_tool_turn(i)

    out = G._prepare_messages(history)
    body = [m for m in out if not isinstance(m, SystemMessage)]

    check("첫 메시지 = SystemMessage", isinstance(out[0], SystemMessage))
    check("본문 첫 메시지 = HumanMessage (고아 Tool 없음)",
          len(body) > 0 and isinstance(body[0], HumanMessage))
    check("트림 후 도구 쌍 시퀀스 유효 (Gemini 400 방지)", valid_sequence(body))
    check("최근 것 위주로 남음(개수 제한)", len(body) <= G._MAX_HISTORY_MSGS + 1)

    # 극단: ToolMessage로 시작하는 잘린 기록도 정리되는지
    bad = make_tool_turn(0)[2:]  # ToolMessage, AI 로 시작(고아)
    out2 = G._prepare_messages(bad)
    body2 = [m for m in out2 if not isinstance(m, SystemMessage)]
    check("고아 ToolMessage로 시작 → 정리됨",
          not body2 or not isinstance(body2[0], ToolMessage))

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
