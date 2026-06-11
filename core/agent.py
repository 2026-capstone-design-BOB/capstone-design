"""
Pluiz Agent Core
----------------
LangGraph 기반 ReAct 에이전트.
사용자 입력 → LLM이 도구 선택 → 결정론적 실행 → 결과 관찰 → 반복
"""

from typing import AsyncGenerator
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, AIMessageChunk
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from config.settings import get_settings
from core.tool_registry import get_all_tools
from memory.session import SessionMemory


SYSTEM_PROMPT = """당신은 Pluiz입니다. 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트입니다.

역할:
- 사용자의 자연어 명령을 이해하고 적절한 도구를 호출하여 PC를 제어합니다.
- 한국어 구어체 및 줄임말을 자연스럽게 처리합니다.
- 명령이 모호하면 짧게 확인 후 실행합니다.
- 실행 결과를 간결하게 한국어로 보고합니다.

주의:
- 시스템 파일 삭제, 개인정보 수집 등 위험한 작업은 거부합니다.
- 불가능한 요청은 이유를 설명합니다.
- 응답은 항상 한국어로 합니다.
"""


def _build_llm(settings=None):
    """설정에 따라 LLM 인스턴스 반환."""
    if settings is None:
        settings = get_settings()

    provider = settings.llm_provider

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=0,
        )
    elif provider == "claude":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.claude_api_key,
            temperature=0,
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0,
        )
    else:
        raise ValueError(f"지원하지 않는 LLM provider: {provider}")


class PluizAgent:
    """
    Pluiz 메인 에이전트.

    내부적으로 LangGraph create_react_agent를 사용.
    - 대화 히스토리: MemorySaver (인메모리 체크포인트)
    - 도구: tool_registry에 등록된 모든 도구 자동 로드
    - thread_id: 세션별 대화 격리
    """

    def __init__(self):
        settings = get_settings()
        self.settings = settings

        self.llm = _build_llm(settings)
        self.tools = get_all_tools()
        self.checkpointer = MemorySaver()
        self.session_memory = SessionMemory()

        # LangGraph ReAct 에이전트 생성
        self.graph = create_react_agent(
            model=self.llm,
            tools=self.tools,
            checkpointer=self.checkpointer,
            prompt=SYSTEM_PROMPT,
        )

        print(f"[PluizAgent] 초기화 완료 | provider={settings.llm_provider} | tools={len(self.tools)}개")

    def run(self, user_input: str, thread_id: str = "default") -> str:
        """
        동기 실행. 사용자 입력 → 최종 응답 반환.
        thread_id로 세션별 대화 히스토리 격리.
        """
        config = {"configurable": {"thread_id": thread_id}}
        messages = [HumanMessage(content=user_input)]

        result = self.graph.invoke(
            {"messages": messages},
            config=config,
        )

        # 마지막 AI 메시지 반환
        response = result["messages"][-1].content
        self.session_memory.save(user_input, response)
        return response

    async def run_async(self, user_input: str, thread_id: str = "default") -> str:
        """비동기 실행. FastAPI 엔드포인트에서 사용."""
        config = {"configurable": {"thread_id": thread_id}}
        messages = [HumanMessage(content=user_input)]

        try:
            result = await self.graph.ainvoke({"messages": messages}, config=config)
        except Exception as e:
            err_msg = str(e)
            # 히스토리 오염 감지 → thread 초기화 후 재시도
            if "tool_calls that do not have a corresponding ToolMessage" in err_msg:
                print(f"[PluizAgent] 히스토리 오염 → thread '{thread_id}' 초기화 후 재시도")
                self._clear_thread(thread_id)
                result = await self.graph.ainvoke({"messages": messages}, config=config)
            else:
                # 그 외 예외: thread 초기화 + 에러 메시지 반환 (서버 크래시 방지)
                print(f"[PluizAgent] 예외 발생 → thread '{thread_id}' 초기화: {type(e).__name__}: {e}")
                self._clear_thread(thread_id)
                return f"명령 처리 중 오류가 발생했습니다: {e}"

        response = result["messages"][-1].content
        # Gemini 2.0+는 content가 list로 올 수 있음 → str로 변환
        if isinstance(response, list):
            response = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in response
            ).strip()
        self.session_memory.save(user_input, response)
        return response

    def _clear_thread(self, thread_id: str):
        """MemorySaver에서 특정 thread 히스토리 전체 삭제."""
        storage = self.checkpointer.storage
        keys_to_delete = [k for k in list(storage.keys()) if k[0] == thread_id]
        for k in keys_to_delete:
            del storage[k]
        print(f"[PluizAgent] thread '{thread_id}' 초기화 완료")

    async def stream(self, user_input: str, thread_id: str = "default") -> AsyncGenerator[str, None]:
        """
        스트리밍 실행. 토큰 단위로 응답을 yield.
        UI에서 실시간 타이핑 효과를 원할 때 사용.
        """
        config = {"configurable": {"thread_id": thread_id}}
        messages = [HumanMessage(content=user_input)]

        async for chunk in self.graph.astream(
            {"messages": messages},
            config=config,
            stream_mode="messages",
        ):
            # (message_chunk, metadata) 형태 — AI 응답 토큰만 yield (tool 메시지 제외)
            msg, meta = chunk
            if not isinstance(msg, (AIMessage, AIMessageChunk)):
                continue
            content = msg.content
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                ).strip()
            if content:
                yield content

    def reset_session(self, thread_id: str = "default"):
        """특정 세션의 대화 히스토리 초기화."""
        # MemorySaver는 thread_id별로 독립적이므로
        # 새 thread_id 사용이 사실상 초기화와 동일
        print(f"[PluizAgent] 세션 초기화: {thread_id}")


# ── 싱글턴 ────────────────────────────────────────────────────────
_agent_instance: PluizAgent | None = None


def get_agent() -> PluizAgent:
    """싱글턴 에이전트 반환. 처음 호출 시 초기화."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = PluizAgent()
    return _agent_instance


def reset_agent():
    """API 키 변경 시 에이전트 재초기화 (다음 get_agent() 호출에서 새로 생성)."""
    global _agent_instance
    _agent_instance = None
    print("[PluizAgent] 인스턴스 초기화됨 - 다음 요청 시 재생성")
