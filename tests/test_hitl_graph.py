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


class TwoDeleteLLM:
    """한 배치에 **위험 호출 두 개**를 담는 mock. (BL-24)

    실기에서 재현하려면 사용자가 *"a도 b도 지워줘"* 라고 말해야 하고 계획 수립이
    그걸 보통 단계로 쪼갠다 — 그래서 **관측된 적이 없는 잠재 결함**이다.
    여기서는 그 배치를 **강제로 만들어** 검증한다(BL-20의 MixedLLM과 같은 방식).
    """
    _n = 0
    def bind_tools(self, tools): return self
    def invoke(self, messages):
        turn = G.current_turn_messages(messages)
        if any(isinstance(m, ToolMessage) for m in turn):
            return AIMessage(content="처리했어요.")
        TwoDeleteLLM._n += 1
        n = TwoDeleteLLM._n
        return AIMessage(content="", tool_calls=[
            {"name": "delete_file", "args": {"file_path": "바탕화면/a.txt"},
             "id": f"d1_{n}", "type": "tool_call"},
            {"name": "delete_file", "args": {"file_path": "바탕화면/b.txt"},
             "id": f"d2_{n}", "type": "tool_call"},
        ])


def build_two(target_exists=None):
    return G.build_pluiz_graph(
        llm=TwoDeleteLLM(), tools=[delete_file, open_app],
        security_check=fake_security, fast_resolve=fake_fast_resolve,
        target_exists=target_exists)


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
    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")
        # 실패했을 때 **무엇이 나왔는지**를 같이 찍는다. 없으면 로그만 보고는
        # 원인을 못 찾아 테스트를 다시 고쳐 돌려야 한다.
        if not cond and detail:
            for line in str(detail).splitlines():
                print(f"       {line}")

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

    # ── 🚨 BL-17 — 재질문 뒤 «승인 대기»를 실기가 알아보는가 ──────────
    #
    # 위 블록은 `Command(resume=)`를 **그래프에 직접** 준다. 실기는 그 전에
    # `PluizGraphAgent._pending_interrupt()`가 «지금 승인 대기인가»를 판단하고,
    # False면 사용자의 '네'를 **새 명령**으로 처리한다.
    #
    # **그 판정이 `next`만 보고 있어서 2026-09-10 실기에서 두 번 깨졌다.**
    # `interrupt()`가 같은 노드에서 두 번째로 걸리면(=재질문) 그 노드는 «다음에
    # 실행할 노드»가 아니라 «실행 중간에 멈춘 노드»라 `next`가 비어 있다:
    #
    #     | 신호               | 1차 질문   | 재질문   |
    #     | next               | ('hitl',) | 없음 ←🚨 |
    #     | tasks[].interrupts | 1         | 1        |
    #
    # 위 블록이 초록인데 실기가 깨진 이유가 이것이다 — **여기서 그 자리를 직접 본다.**
    print("=== BL-17 — 재질문 뒤에도 «승인 대기»로 읽히는가 ===")
    from core.graph_agent import PluizGraphAgent

    executed.clear()
    g17 = build(target_exists=lambda *a, **k: True)
    cfg17 = {"configurable": {"thread_id": "bl17"}}

    class _Shim:
        """실기의 판정 함수를 **그대로** 빌려 쓴다 (복사본이면 또 어긋난다)."""
        graph = g17
        _count_interrupts = staticmethod(PluizGraphAgent._count_interrupts)
        _pending_interrupt = PluizGraphAgent._pending_interrupt

    shim = _Shim()

    g17.invoke({"messages": [HumanMessage("바탕화면 test.txt 삭제해줘")]}, cfg17)
    check("1차 질문 뒤 승인 대기로 읽힌다", shim._pending_interrupt(cfg17) is True)

    g17.invoke(Command(resume="지호 맘몬"), cfg17)          # STT 잡음 → 재질문
    # next만 보면 여기서 False가 된다 — '네'가 새 명령이 되고 질문이 다시 뜬다
    check("🚨 재질문 뒤에도 승인 대기로 읽힌다 (BL-17)",
          shim._pending_interrupt(cfg17) is True)

    g17.invoke(Command(resume="응"), cfg17)
    check("재질문 뒤 승인이 실제로 실행된다", executed == ["바탕화면/test.txt"])
    check("실행이 끝나면 승인 대기가 아니다", shim._pending_interrupt(cfg17) is False)

    # 신호를 세는 쪽도 못 박는다 — langgraph 버전이 올라가며 한쪽이 사라져도
    # 조용히 0이 되지 않게 «둘 다 본다»는 것 자체를 검사한다.
    st17 = g17.get_state({"configurable": {"thread_id": "bl17"}})
    check("_count_interrupts가 스냅샷을 읽는다(예외 없이 정수)",
          isinstance(PluizGraphAgent._count_interrupts(st17), int))

    class _NoDirect:
        interrupts = None
        tasks = (type("T", (), {"interrupts": (1, 2)})(),)
    check("interrupts 속성이 없으면 tasks[]로 폴백한다",
          PluizGraphAgent._count_interrupts(_NoDirect()) == 2)

    # ── 🚨 «질문 없는 next» — 타임아웃이 남긴 시체를 승인 대기로 읽지 않는가 ──
    #
    # **2026-09-11 실기에서 세션이 영구 고장났다.** 오프라인 턴이 `agent_timeout`(45초)에
    # 걸리면 **실행 중간에 멈춘 그래프**가 체크포인트에 남는다:
    #
    #     next=('agent',) | 대기 중인 질문=0      ← 승인 대기가 아니다
    #
    # 예전 판정은 `bool(nxt) or n_itr > 0` 이라 이걸 «승인 대기»로 읽었고,
    # 그 뒤 **모든 입력이 `Command(resume=...)`로 소비**됐다. resume는
    # `input_guard`·`fast_path`를 거치지 않으므로 **캐시에 있는 명령조차 실행되지 않고**,
    # 재개 대상이 죽은 노드라 또 45초 타임아웃이 난다 → 17:32:51 이후 입력 8개가 침묵.
    print("=== 질문 없는 next는 승인 대기가 아니다 (타임아웃 시체) ===")

    def _shim_with(state):
        """`get_state`가 주어진 스냅샷을 돌려주는 최소 shim."""
        return type("S", (), {
            "graph": type("G", (), {"get_state": staticmethod(lambda cfg: state)})(),
            "_count_interrupts": staticmethod(PluizGraphAgent._count_interrupts),
            "_pending_interrupt": PluizGraphAgent._pending_interrupt,
            "_stale_thread": None,
        })()

    cfg_dead = {"configurable": {"thread_id": "dead"}}

    corpse = type("St", (), {"next": ("agent",), "interrupts": None, "tasks": ()})()
    s_corpse = _shim_with(corpse)
    check("🚨 next=('agent',)·질문 0은 승인 대기가 아니다",
          s_corpse._pending_interrupt(cfg_dead) is False,
          "여기서 True면 사용자 명령이 승인 답변으로 소비돼 세션이 죽는다")
    check("버릴 상태로 표시된다", s_corpse._stale_thread == "dead",
          "run_async가 이 표시를 보고 중단 상태를 지운다")

    # 반대로 hitl에 멈춘 것은 **질문이 아직 안 보여도** 승인 대기로 인정한다 —
    # langgraph 버전에 따라 interrupts가 늦게 채워질 수 있다.
    at_hitl = type("St", (), {"next": ("hitl",), "interrupts": None, "tasks": ()})()
    s_hitl = _shim_with(at_hitl)
    check("next=('hitl',)는 질문이 0이어도 승인 대기다",
          s_hitl._pending_interrupt(cfg_dead) is True)
    check("승인 대기는 버릴 상태로 표시하지 않는다", s_hitl._stale_thread is None)

    # 질문이 있으면 next가 비어 있어도 승인 대기다 (= BL-17 재질문). 시체 판정이
    # 이 경로를 가리면 BL-17이 그대로 재발하므로 **같이 못 박는다.**
    requiz = type("St", (), {"next": (), "interrupts": None,
                             "tasks": (type("T", (), {"interrupts": (1,)})(),)})()
    s_requiz = _shim_with(requiz)
    check("질문이 있으면 next가 비어도 승인 대기다 (BL-17 회귀 방지)",
          s_requiz._pending_interrupt(cfg_dead) is True)
    check("그 경우도 버릴 상태로 표시하지 않는다", s_requiz._stale_thread is None)

    # 완전히 끝난 스냅샷 — 아무것도 아니다
    clean = type("St", (), {"next": (), "interrupts": None, "tasks": ()})()
    s_clean = _shim_with(clean)
    check("끝난 그래프는 승인 대기도 시체도 아니다",
          s_clean._pending_interrupt(cfg_dead) is False
          and s_clean._stale_thread is None)

    # ── 🆕 BL-40 — 승인을 N번 묻지 않게 «한 배치로 모으라»고 지시하는가 ──
    #
    # **2026-09-11 사용자 지적**: *"a, b 텍스트 파일 한꺼번에 지워달라고 하면 하나씩
    # 처리해줘. 복합 명령을 하나씩 처리하면 너무 번거로운 HITL 아니야?"*
    #
    # 🚨 **BL-24의 버그가 아니다.** BL-24는 «**한 배치**에 위험 호출이 둘일 때» 하나의
    # 질문으로 묶는 장치다. 실기에서는 **모델이 삭제를 두 개의 agent 턴으로 쪼갰고**
    # (로그: 첫 질문 `out=82` → 승인 → 두 번째 질문 `LLM 2회 out=103`), 한 배치에
    # 둘이 아니니 BL-24가 개입할 자리가 없었다. **BL-24를 고쳐도 이건 그대로다.**
    #
    # 왜 답답함을 넘어 안전 문제인가 — 같은 질문이 N번 반복되면 사용자는 **읽지 않고
    # 「그래」를 말한다.** 실기 로그에 그게 남아 있다(17:23~17:24의 '오'·'음'·'그래라는 뜻이야').
    # **승인 피로는 승인을 무력화시킨다.**
    #
    # A안(프롬프트 유도)은 **확률만 올린다.** 그래서 ① 지시가 있는지와
    # ② **먹었는지 사후에 셀 수 있는지**를 둘 다 못 박는다 — ②가 없으면 다음 실기에서도
    # «쪼개졌다»를 로그에서 **추론**해야 한다(이번에 그랬다).
    print("=== BL-40 — 위험 호출을 한 배치로 모으게 하고, 셀 수 있게 남기는가 ===")
    sp = G.build_system_prompt()
    check("시스템 프롬프트가 «같은 응답에 한꺼번에» 호출하라고 지시한다",
          "한꺼번에" in sp and "delete_file" in sp)
    check("왜 그래야 하는지(확인 한 번)를 같이 말한다", "한 번만" in sp)
    # ⚠️ BL-19의 교훈 — 금지문을 앞에 두면 모델이 «아무것도 안 하는 쪽»으로 기운다.
    #   그래서 «하나씩 나눠 부르면…»(제약)은 «한꺼번에 호출하세요»(지시) **뒤**에 와야 한다.
    check("🚨 지시가 제약보다 앞에 온다 (BL-19의 교훈)",
          sp.index("한꺼번에") < sp.index("하나씩 나눠"))

    graph_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "core", "graph.py"), encoding="utf-8").read()
    check("승인 질문이 «위험 n개»를 로그로 남긴다 (A안이 먹었는지 세는 근거)",
          '"승인 질문 | 위험 %d개' in graph_src)

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

    print("=== BL-24 질문 문구 — 1개일 때는 «글자 그대로» 같아야 한다 ===")
    d1 = {"name": "delete_file", "args": {"file_path": "C:/x/a.txt"}}
    d2 = {"name": "delete_file", "args": {"file_path": "C:/x/b.txt"}}
    d3 = {"name": "delete_file", "args": {"file_path": "C:/x/c.txt"}}
    fol = {"name": "delete_folder", "args": {"folder_path": "C:/x/사진"}}
    # ⚠️ 이 줄이 회귀 방지의 핵심이다 — 문구가 미묘하게 바뀌면 기존 승인 흐름이
    #   («'a.txt' 파일을 …») 사용자 눈에 달라 보인다.
    check("파일 1개 — 조사까지 그대로",
          G._confirm_question(d1).startswith("'a.txt' 파일을 정말 삭제할까요?"))
    check("폴더 1개 — 조사가 «를»", G._confirm_question(fol).startswith("'사진' 폴더를 정말"))
    check("리스트로 줘도 1개면 같다", G._confirm_question([d1]) == G._confirm_question(d1))
    check("2개 — 둘 다 이름을 부르고 개수를 말한다",
          "'a.txt' 파일과 'b.txt' 파일 2개를" in G._confirm_question([d1, d2]))
    check("3개 — 이름은 줄여도 개수는 남는다",
          "외 2개를" in G._confirm_question([d1, d2, d3]))
    check("종류가 섞이면 각각의 종류로 부른다",
          "'a.txt' 파일과 '사진' 폴더 2개를" in G._confirm_question([d1, fol]))
    # 클릭은 «휴지통으로 갑니다»가 거짓이 되므로 결과 문구가 달라야 한다
    clk = {"name": "click_ui_element", "args": {"window": "메모장", "target": "파일 메뉴"}}
    q_mix = G._confirm_question([d1, clk])
    check("삭제+클릭이면 결과를 각각 말한다",
          "휴지통" in q_mix and "클릭은 되돌릴 수 없어요" in q_mix)
    check("재질문도 여러 개를 그대로 싣는다",
          "2개를" in G._reask_question([d1, d2]) and "'네'" in G._reask_question([d1, d2]))

    print("=== 🔒 BL-24 핵심 — 묻지 않은 삭제가 실행되지 않는다 ===")
    # 없는 파일이 섞이면 그건 «물어본 것»이 아니다. 승인해도 실행되면 안 된다.
    executed.clear(); opened.clear()
    g24 = build_two(target_exists=lambda c: "a.txt" in str(c.get("args", {})))
    cfg24 = {"configurable": {"thread_id": "bl24_partial"}}
    r0 = g24.invoke({"messages": [HumanMessage("a랑 b 지워줘")]}, cfg24)
    q24 = r0["__interrupt__"][0].value["question"]
    check("있는 것만 묻는다(a)", "a.txt" in q24)
    check("없는 것은 안 묻는다(b)", "b.txt" not in q24)
    r24 = g24.invoke(Command(resume="응 지워"), cfg24)
    check("🔒 승인해도 «없는» b.txt는 실행되지 않는다",
          "바탕화면/b.txt" not in executed)
    check("물어본 a.txt는 실행된다", "바탕화면/a.txt" in executed)
    check("없어서 못 지운 것을 말한다", "b.txt" in G.extract_response(r24))
    check("짝 불변식이 유지된다", pairs_intact(r24.get("messages", [])))
    check("대기 상태가 남지 않는다", not r24.get("__interrupt__"))

    print("=== BL-24 둘 다 있으면 둘 다 묻고 둘 다 실행한다 ===")
    executed.clear()
    g24b = build_two(target_exists=lambda c: True)
    cfg24b = {"configurable": {"thread_id": "bl24_both"}}
    r0b = g24b.invoke({"messages": [HumanMessage("a랑 b 지워줘")]}, cfg24b)
    qb = r0b["__interrupt__"][0].value["question"]
    check("질문이 둘 다 이름을 부른다", "a.txt" in qb and "b.txt" in qb)
    check("개수를 말한다", "2개" in qb)
    r24b = g24b.invoke(Command(resume="응"), cfg24b)
    check("승인하면 둘 다 실행된다",
          "바탕화면/a.txt" in executed and "바탕화면/b.txt" in executed)
    check("짝 불변식이 유지된다", pairs_intact(r24b.get("messages", [])))

    print("=== BL-24 거부는 BL-20 그대로 — 둘 다 취소된다 ===")
    executed.clear()
    g24c = build_two(target_exists=lambda c: True)
    cfg24c = {"configurable": {"thread_id": "bl24_reject"}}
    g24c.invoke({"messages": [HumanMessage("a랑 b 지워줘")]}, cfg24c)
    r24c = g24c.invoke(Command(resume="아니 취소해"), cfg24c)
    check("거부하면 둘 다 실행되지 않는다", executed == [])
    check("취소 사실이 응답에 남는다", "취소" in G.extract_response(r24c))
    check("짝 불변식이 유지된다", pairs_intact(r24c.get("messages", [])))

    print("=== BL-24 §1-2 — 배치 «순서»에 따라 결과가 달라지지 않는다 ===")
    # 예전엔 첫 호출 하나만 target_exists로 봤다:
    #   [없는것, 있는것] → 묻지 않고 끝  /  [있는것, 없는것] → 묻고 둘 다 실행
    # 지금은 각각 보므로 순서와 무관하게 «있는 것만» 묻고 «있는 것만» 실행한다.
    class RevLLM(TwoDeleteLLM):
        def invoke(self, messages):
            m = TwoDeleteLLM.invoke(self, messages)
            if getattr(m, "tool_calls", None):
                m.tool_calls.reverse()          # b.txt 가 먼저 오게
            return m
    executed.clear()
    grev = G.build_pluiz_graph(
        llm=RevLLM(), tools=[delete_file, open_app],
        security_check=fake_security, fast_resolve=fake_fast_resolve,
        target_exists=lambda c: "a.txt" in str(c.get("args", {})))
    cfgrev = {"configurable": {"thread_id": "bl24_order"}}
    rrev0 = grev.invoke({"messages": [HumanMessage("b랑 a 지워줘")]}, cfgrev)
    check("순서가 반대여도 «있는 것»을 묻는다",
          "a.txt" in rrev0["__interrupt__"][0].value["question"])
    rrev = grev.invoke(Command(resume="응"), cfgrev)
    check("순서가 반대여도 없는 b.txt는 실행되지 않는다",
          "바탕화면/b.txt" not in executed)
    check("순서가 반대여도 a.txt는 실행된다", "바탕화면/a.txt" in executed)

    print("=== BL-24 §6-3 — 승인 재발행분도 진행 근거로 두 번 세지 않는다 ===")
    # BL-20 §5와 같은 자리다. 세면 M3-1의 «못 한 단계 보고»가 조용해진다.
    two = [dict(d1, id="x1", type="tool_call"), dict(d2, id="x2", type="tool_call")]
    ri24 = G.reissue_message(two)
    turn24 = [HumanMessage("a랑 b 지워줘"), AIMessage(content="", tool_calls=two),
              ToolMessage(content="보류", tool_call_id="x1"),
              ToolMessage(content="보류", tool_call_id="x2"), ri24]
    check("원본 2개만 센다", G.turn_tool_call_count(turn24) == 2)

    print("\n=== BL-32 — 지웠으면 **지웠다고 말한다** (한 걸 말하지 않는 것) ===")
    # 실기(2026-09-10): "a.txt는 삭제하고 b.txt 열어줘" → 승인 "어" →
    #   🤖 "b.txt 파일을 열었어요."   ← a.txt를 지웠다는 말이 없다
    #   👤 "다 지운거야?"             ← 사용자가 되물어야 했다
    # BL-12·19·26(«안 한 걸 했다고 말하는 것»)의 **거울상**이고, 삭제는 되돌릴 수
    # 없으니 더 나쁘다. 여기서 고정하는 것은 **접미가 반드시 붙는다**는 것이다.
    dcall = {"name": "delete_file", "args": {"file_path": "바탕화면/a.txt"},
             "id": "d32", "type": "tool_call"}
    ocall = {"name": "open_file", "args": {"file_path": "바탕화면/b.txt"},
             "id": "o32", "type": "tool_call"}

    def turn32(said, tool_out="✓ 'a.txt' 휴지통으로 옮겼어요."):
        return [HumanMessage("a.txt는 삭제하고 b.txt 열어줘"),
                AIMessage(content="", tool_calls=[dcall, ocall]),
                ToolMessage(content=tool_out, tool_call_id="d32"),
                ToolMessage(content="✓ 'b.txt' 파일을 열었습니다.", tool_call_id="o32"),
                AIMessage(content=said)]

    said32 = "b.txt 파일을 열었어요."
    n32 = G.executed_danger_notice(turn32(said32), said32)
    check("🚩 원문 재현: 삭제를 말하지 않은 응답에 접미가 붙는다", n32 != "", f"→ {n32!r}")
    check("도구가 만든 문장을 그대로 싣는다 (LLM에 맡기지 않는다)",
          "휴지통으로 옮겼어요" in n32, f"→ {n32!r}")
    check("✓ 표시는 응답에 섞지 않는다", "✓" not in n32, f"→ {n32!r}")

    # 이미 말했으면 덧붙이지 않는다 — 같은 사실이 두 번 나가면 사람은 둘 중
    # 하나를 «다른 일»로 읽는다.
    said_ok = "'a.txt'를 지우고 b.txt를 열었어요."
    check("응답이 이미 그 대상을 말했으면 붙이지 않는다",
          G.executed_danger_notice(turn32(said_ok), said_ok) == "",
          f"→ {G.executed_danger_notice(turn32(said_ok), said_ok)!r}")

    # 실패는 여기서 말하지 않는다 — missing_notice와 T04가 맡는 자리다.
    check("실패한 삭제는 싣지 않는다 (두 번 말하지 않게)",
          G.executed_danger_notice(
              turn32(said32, "✗ 파일을 찾을 수 없습니다: a.txt"), said32) == "")

    # 같은 파일에 delete_file이 두 번 찍혀도(실기에서 실제로 그랬다) 한 번만 말한다
    dup = turn32(said32)
    dup.insert(3, ToolMessage(content="✓ 'a.txt' 휴지통으로 옮겼어요.",
                              tool_call_id="d32b"))
    dup[1] = AIMessage(content="", tool_calls=[
        dcall, dict(dcall, id="d32b"), ocall])
    check("같은 결과가 두 번 찍혀도 한 번만 말한다",
          G.executed_danger_notice(dup, said32).count("휴지통") == 1,
          f"→ {G.executed_danger_notice(dup, said32)!r}")

    # 위험하지 않은 도구는 이 접미의 대상이 아니다 (응답이 길어지기만 한다)
    safe32 = [HumanMessage("메모장 열어줘"),
              AIMessage(content="", tool_calls=[
                  {"name": "open_app", "args": {"app_name": "메모장"},
                   "id": "s32", "type": "tool_call"}]),
              ToolMessage(content="✓ '메모장'을 열었어요.", tool_call_id="s32"),
              AIMessage(content="열었어요.")]
    check("안전한 도구는 접미를 만들지 않는다",
          G.executed_danger_notice(safe32, "열었어요.") == "")

    # 🚨 절대규칙 6 — 지난 턴의 삭제를 이번 턴에 다시 보고하지 않는다
    across = turn32(said32) + [HumanMessage("고마워"), AIMessage(content="천만에요.")]
    check("🚨 지난 턴의 삭제를 이번 턴에 또 말하지 않는다 (턴 경계)",
          G.executed_danger_notice(across, "천만에요.") == "",
          f"→ {G.executed_danger_notice(across, '천만에요.')!r}")

    # 클릭도 되돌릴 수 없다 — 같은 규칙을 받는다
    ccall = {"name": "click_ui_element",
             "args": {"target": "파일 메뉴", "window": "메모장"},
             "id": "c32", "type": "tool_call"}
    clk = [HumanMessage("메모장에서 파일 메뉴 눌러줘"),
           AIMessage(content="", tool_calls=[ccall]),
           ToolMessage(content="✓ '파일 메뉴'를 클릭했어요.", tool_call_id="c32"),
           AIMessage(content="알겠습니다.")]
    check("클릭도 말하지 않으면 접미가 붙는다",
          "클릭했어요" in G.executed_danger_notice(clk, "알겠습니다."))

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
