"""
P2-2 그래프 HITL(interrupt) 검증 (동기 invoke, mock)
- 위험 도구(delete_file) → interrupt(질문)
- resume '응' → 실행 / resume '아니' → 취소
실행: python test_hitl_graph.py
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
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
    """턴 단위로 판단하는 mock. **이번 턴**의 사용자 발화가 삭제 요청이면 도구콜,
    이번 턴에 ToolMessage가 있으면 요약, 그 외엔 평범한 답.

    ⚠️ 예전엔 "히스토리에 ToolMessage가 하나라도 있으면 요약"이었는데, 그러면
    한 thread에서 **두 번째 삭제 요청부터 도구를 못 부른다.** 취소 플래그가
    턴을 넘어 새는 회귀를 재현하려면 이 시나리오가 필요했다.
    (같은 이유로 test_cache_wire에도 ScriptedLLM이 있다)
    """
    _n = 0
    def bind_tools(self, tools): return self
    def invoke(self, messages):
        turn = G.current_turn_messages(messages)
        if any(isinstance(m, ToolMessage) for m in turn):
            return AIMessage(content="삭제 완료했어요.")
        human = next((m for m in turn if isinstance(m, HumanMessage)), None)
        text = str(getattr(human, "content", "")) if human else ""
        if "삭제" in text or "지워" in text:
            FakeLLM._n += 1
            return AIMessage(content="", tool_calls=[{
                "name": "delete_file",
                "args": {"file_path": "바탕화면/test.txt"},
                "id": f"call_{FakeLLM._n}", "type": "tool_call",
            }])
        return AIMessage(content="네, 처리했어요.")

def fake_security(text): return (False, "")
def fake_fast_resolve(text): return None


def build(target_exists=None):
    return G.build_pluiz_graph(
        llm=FakeLLM(), tools=[delete_file],
        security_check=fake_security, fast_resolve=fake_fast_resolve,
        target_exists=target_exists)


# ── BL-20 — 한 배치에 «위험 + 안전»이 섞여 오는 경우 ────────────────
# 이 mock이 이 결함의 전제 조건 그 자체다. 오늘 실기에서 드물게 나오는 배치를
# 여기서는 **반드시** 나오게 만들어 놓고, 거부했을 때 안전한 쪽이 살아남는지 본다.
# → docs/design/BL-20_거부후_안전호출.md
opened = []

@tool
def open_app(app_name: str) -> str:
    """앱 실행(mock)."""
    opened.append(app_name)
    return f"✓ '{app_name}'을(를) 열었어요."


class MixedLLM:
    """삭제 요청에 **[open_app, delete_file] 두 개를 한 AIMessage에** 담는 mock."""
    _n = 0
    def bind_tools(self, tools, **kw): return self
    def invoke(self, messages):
        turn = G.current_turn_messages(messages)
        if any(isinstance(m, ToolMessage) for m in turn):
            return AIMessage(content="메모장을 열었어요.")
        human = next((m for m in turn if isinstance(m, HumanMessage)), None)
        text = str(getattr(human, "content", "")) if human else ""
        if "삭제" in text or "지워" in text:
            MixedLLM._n += 1
            n = MixedLLM._n
            calls = [{"name": "delete_file",
                      "args": {"file_path": "바탕화면/test.txt"},
                      "id": f"mix_del_{n}", "type": "tool_call"}]
            if "메모장" in text:
                calls.insert(0, {"name": "open_app", "args": {"app_name": "메모장"},
                                 "id": f"mix_open_{n}", "type": "tool_call"})
            return AIMessage(content="", tool_calls=calls)
        return AIMessage(content="네, 처리했어요.")


def build_mixed(target_exists=None):
    return G.build_pluiz_graph(
        llm=MixedLLM(), tools=[delete_file, open_app],
        security_check=fake_security, fast_resolve=fake_fast_resolve,
        target_exists=target_exists)


def pairs_intact(msgs) -> bool:
    """모든 tool_call.id에 ToolMessage가 하나씩 있는가 (절대규칙 3 / ADR §3-1).

    깨지면 실기에서 Gemini 400이다 — mock으로는 안 터지므로 여기서 직접 센다.
    """
    want, got = [], []
    for m in msgs:
        for c in (getattr(m, "tool_calls", None) or []):
            want.append(c["id"])
        if isinstance(m, ToolMessage):
            got.append(m.tool_call_id)
    return sorted(want) == sorted(got)


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

    # ⚠️ 재질문 경로는 **진짜 알아들을 수 없는 답**으로 검증해야 한다.
    #    예전엔 여기에 "네이버 열어줘"를 썼는데, 그건 애매한 게 아니라 다른 명령이다.
    #    그 기대 때문에 "명령을 삼키는 동작"이 PASS로 찍히고 있었다(실기에서 발견).
    #    STT 잡음은 실제로 이렇게 들어온다: "베이", "지호 맘몬", "오 오 오"
    print("=== 애매한 답 → 즉시 취소하지 않고 재질문 ===")
    executed.clear()
    g3 = build()
    cfg3 = {"configurable": {"thread_id": "unclear"}}
    g3.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg3)
    r4 = g3.invoke(Command(resume="지호 맘몬"), cfg3)          # STT 잡음
    itr4 = r4.get("__interrupt__")
    check("애매한 답 → 미실행", executed == [])
    check("애매한 답 → 재질문(대기 유지)", bool(itr4))
    q4 = itr4[0].value.get("question", "") if itr4 else ""
    check("재질문이 예/아니오를 요구", "아니오" in q4)
    r5 = g3.invoke(Command(resume="응"), cfg3)                # 이제 승인
    check("재질문 후 승인 → 실행됨", executed == ["바탕화면/test.txt"])

    print("=== 끝까지 애매 → 취소(안전 기본값) ===")
    executed.clear()
    g4 = build()
    cfg4 = {"configurable": {"thread_id": "unclear2"}}
    g4.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg4)
    g4.invoke(Command(resume="베이"), cfg4)
    r6 = g4.invoke(Command(resume="오 오 오"), cfg4)
    check("두 번 애매 → 미실행", executed == [])
    check("두 번 애매 → 취소 응답", "취소" in G.extract_response(r6))

    # 🚨 실기에서 나온 결함 — 승인 대기 중 "네이버 열어줘"가 재질문으로 처리돼
    #    사용자가 같은 말을 두 번 해야 했다. 이제는 삭제를 취소하고 그 명령을 실행한다.
    print("=== 승인 대기 중 다른 명령 → 삭제 취소 + 그 명령 실행 ===")
    executed.clear()
    g5 = build()
    cfg5 = {"configurable": {"thread_id": "other_cmd"}}
    g5.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg5)
    r7 = g5.invoke(Command(resume="네이버 열어줘"), cfg5)
    check("다른 명령 → 삭제 미실행", executed == [])
    check("다른 명령 → 재질문하지 않는다 (대기 종료)", not r7.get("__interrupt__"))
    msgs7 = r7.get("messages", [])
    check("다른 명령이 HumanMessage로 들어간다 (이번 턴이 된다)",
          any(type(m).__name__ == "HumanMessage" and "네이버" in G._msg_text(m)
              for m in msgs7))
    check("취소 사실을 응답에 알린다", "취소" in G.extract_response(r7))

    # 🚨 실기 회귀 — 띄어쓰기 하나로 승인이 "다른 명령"이 돼 무한 루프를 돌았다.
    #    "응 지워 줘" → 어절 [응][지워][줘] → "줘"가 긍정어 목록에 없어 승인 실패
    #    → 명령형 어미로 보여 other_command → 삭제 취소 후 재실행 → 또 질문...
    #    사용자는 네 번을 말하고 나서야 삭제됐다.
    print("=== 승인의 띄어쓰기 변형 (실기 회귀) ===")
    for ok_cmd in ["응 지워 줘", "그래 정말 삭제해 줘", "어 지워 버려",
                   "오케이 그냥 지워줘", "응 지워 봐", "네 그냥 다 지워줘",
                   "네 삭제해 주세요"]:
        check(f"'{ok_cmd}' → approve",
              G.classify_confirmation(ok_cmd) == "approve")
    # 강조어만 있으면 승인이 아니다 ("정말?" 을 승인으로 읽으면 안 된다)
    check("'정말' 한 마디 → approve 아님", G.classify_confirmation("정말") != "approve")
    check("'그냥' 한 마디 → approve 아님", G.classify_confirmation("그냥") != "approve")

    # 🚨 실기 회귀 — 앞 턴에서 켜진 취소 플래그가 살아남아, **실제로 삭제해 놓고**
    #    "삭제는 취소했어요 … 휴지통으로 옮겼어요" 라고 답했다. 모순이자 위험하다.
    print("=== 다른 명령으로 취소한 뒤, 다음 삭제는 정상 보고 ===")
    executed.clear()
    g8 = build()
    cfg8 = {"configurable": {"thread_id": "flag_leak"}}
    g8.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg8)
    g8.invoke(Command(resume="네이버 열어줘"), cfg8)          # 취소 플래그 ON
    g8.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg8)
    r10 = g8.invoke(Command(resume="응 지워 줘"), cfg8)        # 이번엔 진짜 승인
    resp10 = G.extract_response(r10)
    check("승인했으면 실제로 실행된다", executed == ["바탕화면/test.txt"])
    check("실행해 놓고 '취소했어요'라고 하지 않는다", "취소" not in resp10, )

    print("=== classify_confirmation — 다른 명령 vs 애매 ===")
    for cmd in ["네이버 열어줘", "음소거 해줘", "진행 상황 알려줘",
                "그래프 그려줘", "네이버 열어 달라니까", "메모장 켜줄래"]:
        check(f"'{cmd}' → other_command",
              G.classify_confirmation(cmd) == "other_command")
    for noise in ["지호 맘몬", "베이", "오 오 오", "글쎄", "음"]:
        check(f"'{noise}'(STT 잡음) → unclear",
              G.classify_confirmation(noise) == "unclear")

    # 대상이 없으면 **묻지 않는다** — 예전엔 묻고 승인받은 뒤에야 "없네요"라고 했다.
    print("=== 삭제 대상이 없으면 승인을 묻지 않는다 ===")
    executed.clear()
    g6 = build(target_exists=lambda dcall: False)
    cfg6 = {"configurable": {"thread_id": "not_found"}}
    r8 = g6.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg6)
    check("없는 대상 → interrupt 없음(안 물어봄)", not r8.get("__interrupt__"))
    check("없는 대상 → 삭제 미실행", executed == [])

    executed.clear()
    g7 = build(target_exists=lambda dcall: True)
    cfg7 = {"configurable": {"thread_id": "found"}}
    r9 = g7.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg7)
    check("있는 대상 → 평소대로 승인 질문", bool(r9.get("__interrupt__")))

    print("=== classify_confirmation ===")
    check("'응' → approve", G.classify_confirmation("응") == "approve")
    check("'네 삭제해줘' → approve", G.classify_confirmation("네 삭제해줘") == "approve")
    check("'아니' → reject", G.classify_confirmation("아니") == "reject")
    check("'아니 삭제해'(모순) → reject", G.classify_confirmation("아니 삭제해") == "reject")
    check("'글쎄'(애매) → unclear", G.classify_confirmation("글쎄") == "unclear")

    # 🚨 회귀 방지 — 승인 대기 중 사용자가 말한 **평범한 명령**이 승인으로 읽히던 버그.
    #    옛 정규식은 부분 문자열(네/해 줘/그래/진행/응/예)만 보고 삭제를 실행했다.
    print("=== 일상 명령이 승인으로 오인되지 않는다 (회귀) ===")
    for cmd in ["네이버 열어줘", "음소거 해줘", "그래프 그려줘",
                "진행 상황 알려줘", "응용 프로그램 목록", "예약 확인해줘",
                "메모장 켜줘", "볼륨 올려줘"]:
        check(f"'{cmd}' → 승인 아님",
              G.classify_confirmation(cmd) != "approve"
              and G.interpret_confirmation(cmd) is False)

    print("=== interpret_confirmation (하위호환) ===")
    check("'응' → True", G.interpret_confirmation("응") is True)
    check("'아니' → False", G.interpret_confirmation("아니") is False)
    check("'아니 삭제해'(모순) → False", G.interpret_confirmation("아니 삭제해") is False)
    check("'글쎄'(애매) → False(안전)", G.interpret_confirmation("글쎄") is False)

    # ═══ BL-20 — 위험 도구를 거부해도 안전한 호출은 살린다 ═══════════
    # docs/design/BL-20_거부후_안전호출.md
    print("=== BL-20 순수 함수 — 가르기 · 재발행 ===")
    mixed = [{"name": "open_app", "args": {}, "id": "a", "type": "tool_call"},
             {"name": "delete_file", "args": {}, "id": "b", "type": "tool_call"}]
    safe, risky = G.split_calls(mixed, {"delete_file"})
    check("split_calls — 안전/위험이 갈린다",
          [c["id"] for c in safe] == ["a"] and [c["id"] for c in risky] == ["b"])
    check("split_calls — 안전한 것만 있으면 위험은 빈 목록",
          G.split_calls(mixed[:1], {"delete_file"})[1] == [])
    check("살릴 게 없으면 재발행하지 않는다(None)", G.reissue_message([]) is None)
    ri = G.reissue_message(safe)
    check("재발행 id가 원본과 다르다", ri.tool_calls[0]["id"] != "a")
    check("재발행에 위험 호출이 없다",
          [c["name"] for c in ri.tool_calls] == ["open_app"])
    check("재발행에는 표식이 붙는다", G.is_reissued(ri))
    check("보통 AIMessage는 표식이 없다", not G.is_reissued(AIMessage(content="x")))

    # ⚠️ §5 — 표식이 없으면 재발행분이 «진행 근거»로 두 번 세어져, M3-1이 지키려던
    #   «승인 거부 → 못 한 단계 보고»가 조용해진다. 접두 문구로는 못 메운다.
    print("=== BL-20 §5 — 재발행분은 진행 근거로 세지 않는다 ===")
    turn = [HumanMessage("메모장 열고 test.txt 지워줘"),
            AIMessage(content="", tool_calls=mixed),
            ToolMessage(content="보류", tool_call_id="a"),
            ToolMessage(content="취소", tool_call_id="b"),
            ri]
    check("원본 2개만 센다(재발행 1개는 제외)", G.turn_tool_call_count(turn) == 2)
    check("그래야 거부 단계가 '못 했어요'로 남는다",
          G.steps_covered(1, G.turn_tool_call_count(turn)) == 1)

    print("=== BL-20 ① 거부 → 삭제만 취소, 메모장은 열린다 ===")
    executed.clear(); opened.clear()
    gb1 = build_mixed()
    cfgb1 = {"configurable": {"thread_id": "bl20_reject"}}
    gb1.invoke({"messages": [HumanMessage("메모장 열고 test.txt 지워줘")]}, cfgb1)
    rb1 = gb1.invoke(Command(resume="아니 취소해"), cfgb1)
    check("거부한 삭제는 실행되지 않는다", executed == [])
    check("같이 온 안전한 호출은 실행된다", opened == ["메모장"])
    respb1 = G.extract_response(rb1)
    check("거부 사실이 응답에 남는다(접두)", "취소" in respb1)
    check("한 일도 같이 말한다", "메모장" in respb1)
    check("짝 불변식이 유지된다", pairs_intact(rb1.get("messages", [])))
    check("대기 상태가 남지 않는다", not rb1.get("__interrupt__"))

    print("=== BL-20 ③ 안전 호출이 없으면 오늘과 똑같다 ===")
    executed.clear(); opened.clear()
    gb2 = build_mixed()
    cfgb2 = {"configurable": {"thread_id": "bl20_only_risky"}}
    gb2.invoke({"messages": [HumanMessage("test.txt 지워줘")]}, cfgb2)   # 메모장 없음
    rb2 = gb2.invoke(Command(resume="아니 취소해"), cfgb2)
    check("살릴 게 없으면 미실행 그대로", executed == [] and opened == [])
    check("살릴 게 없으면 기존 취소 응답 그대로", "취소" in G.extract_response(rb2))
    check("살릴 게 없으면 짝도 그대로", pairs_intact(rb2.get("messages", [])))

    print("=== BL-20 ④ 승인 경로는 바뀌지 않는다 ===")
    executed.clear(); opened.clear()
    gb3 = build_mixed()
    cfgb3 = {"configurable": {"thread_id": "bl20_approve"}}
    gb3.invoke({"messages": [HumanMessage("메모장 열고 test.txt 지워줘")]}, cfgb3)
    rb3 = gb3.invoke(Command(resume="응 지워 줘"), cfgb3)
    check("승인하면 배치 전체가 실행된다",
          executed == ["바탕화면/test.txt"] and opened == ["메모장"])
    check("승인했는데 '취소했어요'라고 하지 않는다",
          "취소" not in G.extract_response(rb3))

    print("=== BL-20 ④' 끝까지 애매하면 재발행하지 않는다(안전 기본값) ===")
    executed.clear(); opened.clear()
    gb4 = build_mixed()
    cfgb4 = {"configurable": {"thread_id": "bl20_unclear"}}
    gb4.invoke({"messages": [HumanMessage("메모장 열고 test.txt 지워줘")]}, cfgb4)
    gb4.invoke(Command(resume="베이"), cfgb4)
    rb4 = gb4.invoke(Command(resume="오 오 오"), cfgb4)
    check("애매 → 삭제도 안전 호출도 실행하지 않는다",
          executed == [] and opened == [])
    check("애매 → 다시 말해 달라고 한다", "다시" in G.extract_response(rb4))

    print("=== BL-20 ⑥ 다른 명령이면 재발행하지 않는다 ===")
    executed.clear(); opened.clear()
    gb5 = build_mixed()
    cfgb5 = {"configurable": {"thread_id": "bl20_other"}}
    gb5.invoke({"messages": [HumanMessage("메모장 열고 test.txt 지워줘")]}, cfgb5)
    rb5 = gb5.invoke(Command(resume="네이버 열어줘"), cfgb5)
    check("다른 명령 → 지난 배치의 안전 호출을 되살리지 않는다", opened == [])
    check("다른 명령 → 삭제도 안 한다", executed == [])
    check("다른 명령 → 짝은 그대로", pairs_intact(rb5.get("messages", [])))

    print("=== BL-20 대상이 없을 때도 안전 호출은 살린다 ===")
    executed.clear(); opened.clear()
    gb6 = build_mixed(target_exists=lambda dcall: False)
    cfgb6 = {"configurable": {"thread_id": "bl20_not_found"}}
    rb6 = gb6.invoke({"messages": [HumanMessage("메모장 열고 test.txt 지워줘")]}, cfgb6)
    check("없는 대상 → 묻지 않는다", not rb6.get("__interrupt__"))
    check("없는 대상 → 삭제 미실행", executed == [])
    check("없는 대상이어도 메모장은 열린다", opened == ["메모장"])
    check("없는 대상 경로도 짝이 유지된다", pairs_intact(rb6.get("messages", [])))

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
