"""
Pluiz Graph (M1-P1.5) — 명시적 LangGraph StateGraph
===================================================
기존 core/agent.py(create_react_agent + 수동 if/return 전처리)를 대체할
차세대 파이프라인. 모든 경로(보안·캐시·라우터·LLM)가 **단일 상태(messages)**를
공유·갱신하므로 맥락이 근본적으로 통합된다.

설계 원칙:
- 의존성 주입(DI): llm / tools / 보안검사 / fast_path 해석기를 인자로 받는다.
  → Windows·LLM API 없이도 mock으로 그래프 로직을 단위 테스트할 수 있다.
  → 기존 agent.py는 건드리지 않고 병행 제작(점진 전환·롤백 가능).
- 동기 노드(sync): langgraph interrupt가 sync invoke에서만 안정 동작하므로 노드는 동기.
  오케스트레이터가 graph.invoke를 워커 스레드(asyncio.to_thread)로 실행해 루프를 막지 않음.

노드 구성:
    START → input_guard → fast_path ─(hit)→ output_guard → END
                              │
                            (miss)
                              ▼
                            agent ⇄ tools → output_guard → END
    input_guard 차단 시 → output_guard → END (사유 응답만)

핵심(맥락 버그 해결):
    fast_path가 캐시/라우터로 명령을 처리해도, 그 결과를 AIMessage로
    state.messages에 append 한다. 따라서 다음 턴의 LLM이 이전 명령을 볼 수 있다.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional, Any
from datetime import datetime

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage, AnyMessage, trim_messages,
)


# ── HITL: 위험 도구 정의 & 승인 해석 (P2) ─────────────────────────
# 이 도구 호출은 실행 전 hitl 노드에서 사용자 승인을 받는다.
DANGEROUS_TOOLS = {"delete_file", "delete_folder"}

_APPROVE_RE = re.compile(r'응|네|예|그래|좋아|해\s*줘|해도\s*돼|맞아|오케이|okay|ok|ㅇㅇ|진행|삭제해|지워')
_REJECT_RE = re.compile(r'아니|취소|하지\s*마|하지마|싫|안\s*돼|안돼|관둬|그만|멈춰|ㄴㄴ|말아')


def interpret_confirmation(text: Any) -> bool:
    """승인 응답 해석. 거부어 우선 검사 → 승인어 → 애매하면 안전하게 취소(False)."""
    t = str(text).strip().lower()
    if _REJECT_RE.search(t):
        return False
    if _APPROVE_RE.search(t):
        return True
    return False   # 애매 → 위험 동작이므로 취소가 안전


def _confirm_question(dcall: Optional[dict]) -> str:
    """위험 도구 호출로부터 승인 질문 문구 생성."""
    if not dcall:
        return "정말 실행할까요? (되돌리기 어려워요)"
    name = dcall.get("name", "")
    args = dcall.get("args", {}) or {}
    target = args.get("file_path") or args.get("folder_path") or ""
    kind = "폴더" if name == "delete_folder" else "파일"
    base = os.path.basename(str(target).rstrip("/\\")) or str(target)
    return f"'{base}' {kind}을(를) 정말 삭제할까요? (되돌리기 어려워요)"


# ── 상태 정의 ──────────────────────────────────────────────────────
class PluizState(MessagesState):
    """messages(add_messages reducer) + 라우팅 결정 필드.

    decision: input_guard/fast_path가 다음 경로를 지시하는 임시 신호.
              'blocked' | 'fast_hit' | 'to_agent'
    """
    decision: str


# ── 시스템 프롬프트 (날짜 갱신) ───────────────────────────────────
_MAX_HISTORY_MSGS = 20


def build_system_prompt() -> str:
    now = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    date_str = f"{now.year}년 {now.month}월 {now.day}일 ({weekdays[now.weekday()]})"
    time_str = f"{now.hour:02d}:{now.minute:02d}"
    return (
        "당신은 소윤이입니다. 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트예요.\n"
        f"현재 날짜/시간: {date_str} {time_str}\n"
        "응답은 1~2문장으로 짧고 친근한 구어체로. 도구 실행 결과는 핵심만 요약.\n"
        "PC 제어 명령은 반드시 도구를 호출해서 실행하고, 도구 없이 '실행했어요'라고만 답하지 마세요.\n"
        "이전 대화 맥락을 활용하세요. '그거', '아까 그거' 같은 지칭은 직전 대화를 참고해 해석하세요.\n"
        "사용자가 '안 됐어/안 열렸어/실행 안 됨'처럼 실패를 알리면, 같은 답을 반복하지 말고 "
        "get_running_apps로 실제 실행 여부를 확인한 뒤 다른 방법으로 다시 시도하세요. "
        "정말 안 되면 솔직하게 '안 됐다'고 말하고, 됐는지 불확실하면 확실한 척하지 마세요.\n"
        "응답은 항상 한국어로 해요."
    )


# ── 메시지 유틸 ────────────────────────────────────────────────────
def _msg_text(m: Any) -> str:
    """메시지/블록 리스트의 텍스트를 평문으로 추출."""
    c = getattr(m, "content", m)
    if isinstance(c, list):
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in c
        ).strip()
    return str(c)


def _prepare_messages(history: list[AnyMessage]) -> list[AnyMessage]:
    """LLM 호출용 메시지 구성: 시스템 프롬프트(매번 갱신) + 최근 N개 히스토리.

    ※ 단순 슬라이스(convo[-N:])는 (도구호출 AIMessage ↔ ToolMessage) 쌍을 중간에서
      잘라 깨진 시퀀스를 만들 수 있고, Gemini가 이를 400(INVALID_ARGUMENT)으로 거부한다.
      → trim_messages(start_on="human")으로 항상 사람 발화부터 시작하는 유효 시퀀스 보장.
    """
    system = SystemMessage(content=build_system_prompt())
    convo = [m for m in history if not isinstance(m, SystemMessage)]
    try:
        trimmed = trim_messages(
            convo,
            max_tokens=_MAX_HISTORY_MSGS,
            strategy="last",
            token_counter=len,          # 토큰 수가 아닌 '메시지 개수' 기준
            start_on="human",           # 항상 HumanMessage로 시작 → 고아 ToolMessage 방지
            include_system=False,       # 시스템 메시지는 위에서 별도 부착
            allow_partial=False,
        )
    except Exception as e:
        print(f"[graph._prepare_messages] trim 실패, fallback: {e}")
        # 최소 방어: 앞쪽의 고아 ToolMessage/도구호출 AIMessage 제거
        trimmed = convo[-_MAX_HISTORY_MSGS:]
        while trimmed and (
            isinstance(trimmed[0], ToolMessage)
            or (isinstance(trimmed[0], AIMessage) and getattr(trimmed[0], "tool_calls", None))
        ):
            trimmed = trimmed[1:]
    return [system] + trimmed


def _last_human_text(messages: list[AnyMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return _msg_text(m)
    return ""


# ── 출력 검증 (T04 + 빈응답 복구) — output_guard의 순수 로직 ─────────
_TOOL_ERROR_RE = re.compile(
    r'^\[(?:오류|error|[가-힣a-zA-Z_]+ 오류)\]'
    r'|^오류\s*:'
    r'|^Error\s*:',
    re.IGNORECASE,
)
_SUCCESS_LIKE_RE = re.compile(
    r'(?<!못)(?:했어요|켰어요|열었어요|닫았어요|실행했어요|설정했어요|만들었어요|저장했어요|됐어요|완료했어요|완료)[!.]?\s*$'
)


def verify_output(messages: list[AnyMessage]) -> Optional[str]:
    """도구 실행 결과를 검증해 필요 시 보정 텍스트를 반환한다.

    - 마지막 AI 응답이 비어 있으면 → 마지막 ToolMessage 내용으로 복원.
    - 도구 오류가 있는데 AI가 성공처럼 응답했으면 → 오류 내용으로 교체.
    - 보정 불필요하면 None.

    (agent.py의 빈응답 복구 + T04 로직을 노드용 순수 함수로 이관)
    """
    # 마지막 AIMessage(응답) 추출
    response = ""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            response = _msg_text(m)
            break

    # 도구 오류 수집
    tool_errors: list[str] = []
    for m in messages:
        if isinstance(m, ToolMessage):
            c = _msg_text(m).strip()
            if _TOOL_ERROR_RE.match(c):
                tool_errors.append(c)

    # 1) 빈 응답 → ToolMessage에서 복원
    if not response.strip():
        for m in reversed(messages):
            if isinstance(m, ToolMessage):
                c = _msg_text(m).strip()
                if c:
                    return c
        return "명령을 실행했습니다."

    # 2) 도구 오류 + 성공처럼 보이는 응답 → 오류로 보정
    if tool_errors and _SUCCESS_LIKE_RE.search(response):
        clean = re.sub(r'^\[[^\]]+\]\s*', '', tool_errors[0]).strip() or tool_errors[0]
        return f"실행 중 문제가 생겼어요: {clean}"

    return None


def extract_response(state: dict) -> str:
    """그래프 실행 결과 state에서 마지막 AIMessage 텍스트를 추출."""
    for m in reversed(state["messages"]):
        if isinstance(m, AIMessage):
            t = _msg_text(m)
            if t.strip():
                return t
    return ""


# ── 그래프 빌더 ────────────────────────────────────────────────────
def build_pluiz_graph(
    *,
    llm: Any,
    tools: Optional[list] = None,
    security_check: Callable[[str], tuple[bool, str]],
    fast_resolve: Optional[Callable[[str], Any]] = None,
    checkpointer: Optional[Any] = None,
    dangerous_tools: Optional[set] = None,
):
    """Pluiz StateGraph를 구성해 compiled graph를 반환한다. (async 노드)

    Args:
        llm: bind_tools/invoke를 지원하는 채팅 모델 (또는 동일 인터페이스 mock).
        tools: LangChain 도구 리스트 (ToolNode용). 없으면 tools 노드 생략.
        security_check(text) -> (blocked, reason): 입력 보안 검사(코드 레벨).
        fast_resolve(text) -> Optional[str] | Awaitable: 캐시/라우터 즉시 처리 결과,
            처리 불가 시 None. (동기·비동기 모두 허용)
        checkpointer: 대화 영속성. 없으면 MemorySaver 기본 생성.
    """
    tools = tools or []
    dangerous = dangerous_tools if dangerous_tools is not None else DANGEROUS_TOOLS
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    # ── 노드 ───────────────────────────────────────────────────────
    def input_guard(state: PluizState) -> dict:
        """OWASP LLM01/02 자리. 현재는 코드 레벨 보안 검사."""
        text = _last_human_text(state["messages"])
        blocked, reason = security_check(text)
        if blocked:
            return {"messages": [AIMessage(content=reason)], "decision": "blocked"}
        return {"decision": ""}

    def fast_path(state: PluizState) -> dict:
        """캐시/라우터 빠른 경로. 히트 시 결과를 messages에 기록(맥락 통합 핵심)."""
        if fast_resolve is None:
            return {"decision": "to_agent"}
        text = _last_human_text(state["messages"])
        try:
            result = fast_resolve(text)
        except Exception as e:
            print(f"[graph.fast_path] 오류(무시): {type(e).__name__}: {e}")
            result = None
        if result is not None:
            return {"messages": [AIMessage(content=str(result))], "decision": "fast_hit"}
        return {"decision": "to_agent"}

    def agent(state: PluizState) -> dict:
        """LLM ReAct 추론 노드 (동기 invoke — interrupt 호환)."""
        msgs = _prepare_messages(state["messages"])
        response = llm_with_tools.invoke(msgs)
        return {"messages": [response]}

    def output_guard(state: PluizState) -> dict:
        """OWASP LLM05 + reflection 자리. T04 보정 + 빈응답 복구."""
        corrected = verify_output(state["messages"])
        if corrected is not None:
            return {"messages": [AIMessage(content=corrected)]}
        return {}

    def hitl(state: PluizState) -> dict:
        """위험 도구 실행 전 사람 승인(HITL, Lab19). interrupt로 그래프를 일시정지.
        재개 시 응답을 해석해 승인이면 tools로, 거부면 취소 응답.
        (interrupt는 동기 호출이라 동기 노드로 둔다 — config 컨텍스트 보장)"""
        last = state["messages"][-1]
        calls = list(getattr(last, "tool_calls", []) or [])
        dcall = next((c for c in calls if c.get("name") in dangerous), None)

        # 그래프를 멈추고 사용자에게 질문(오케스트레이터가 질문을 UI로 전달)
        answer = interrupt({"question": _confirm_question(dcall)})

        if interpret_confirmation(answer):
            return {"decision": "approved"}

        # 거부: 매달린 tool_calls를 ToolMessage로 마감(오염 방지) + 취소 응답
        cancel = [ToolMessage(content="사용자가 삭제를 취소했습니다.", tool_call_id=c["id"])
                  for c in calls if c.get("id")]
        cancel.append(AIMessage(content="네, 삭제를 취소했어요."))
        return {"messages": cancel, "decision": "rejected"}

    # ── 라우팅 ─────────────────────────────────────────────────────
    def route_after_guard(state: PluizState) -> str:
        return "output_guard" if state.get("decision") == "blocked" else "fast_path"

    def route_after_fast(state: PluizState) -> str:
        return "output_guard" if state.get("decision") == "fast_hit" else "agent"

    def route_after_agent(state: PluizState) -> str:
        last = state["messages"][-1]
        calls = getattr(last, "tool_calls", None)
        if calls:
            if any(c.get("name") in dangerous for c in calls):
                return "hitl"      # 위험 도구 → 승인 절차
            return "tools"
        return "output_guard"

    def route_after_hitl(state: PluizState) -> str:
        return "tools" if state.get("decision") == "approved" else "output_guard"

    # ── 조립 ───────────────────────────────────────────────────────
    g = StateGraph(PluizState)
    g.add_node("input_guard", input_guard)
    g.add_node("fast_path", fast_path)
    g.add_node("agent", agent)
    g.add_node("output_guard", output_guard)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", route_after_guard,
                            {"fast_path": "fast_path", "output_guard": "output_guard"})

    if tools:
        g.add_node("tools", ToolNode(tools))
        g.add_node("hitl", hitl)
        g.add_conditional_edges("fast_path", route_after_fast,
                                {"agent": "agent", "output_guard": "output_guard"})
        g.add_conditional_edges("agent", route_after_agent,
                                {"tools": "tools", "hitl": "hitl", "output_guard": "output_guard"})
        g.add_conditional_edges("hitl", route_after_hitl,
                                {"tools": "tools", "output_guard": "output_guard"})
        g.add_edge("tools", "agent")
    else:
        g.add_conditional_edges("fast_path", route_after_fast,
                                {"agent": "agent", "output_guard": "output_guard"})
        g.add_edge("agent", "output_guard")

    g.add_edge("output_guard", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
