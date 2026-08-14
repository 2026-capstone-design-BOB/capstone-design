"""
PluizGraphAgent (M1-P1.5-c) — 그래프 오케스트레이터
==================================================
core/graph.py의 StateGraph를 감싸, 기존 core/agent.py(PluizAgent)와
**동일한 공개 API**(`run_async`, `stream`)를 제공한다.
→ main.py가 플래그(USE_GRAPH)로 신/구 코어를 무중단 교체 가능(P1.5-d).

책임:
- 실제 의존성 배선: llm / tools / 보안검사 / fast_path(캐시+라우터) / 세션메모리.
- 타임아웃(settings.agent_timeout), 세션 저장, 네트워크/타임아웃/오염 예외 처리.

설계: 모든 의존성은 **주입 가능**(테스트용). 미주입 시 프로덕션 기본값을 **lazy import**로
      생성 → 이 모듈 import 자체는 Windows·LLM API 없이도 가능(테스트 용이).
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Any, Optional, Callable

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from core.graph import build_pluiz_graph, extract_response
from core.fast_path import resolve_fast_path


# ── 프로덕션 기본값 (lazy) ─────────────────────────────────────────
def _prod_settings():
    from config.settings import get_settings
    return get_settings()

def _prod_llm(settings):
    from core.agent import _build_llm
    return _build_llm(settings)

def _prod_tools():
    from core.tool_registry import get_all_tools
    return get_all_tools()

def _prod_security():
    from core.security import check_security
    return check_security

def _prod_cache():
    from core.command_cache import get_cache
    return get_cache()

def _prod_session_memory():
    from memory.session import SessionMemory
    return SessionMemory()


def _is_network_error(e: Exception) -> bool:
    msg = str(e)
    return any(kw in msg for kw in [
        "getaddrinfo failed", "ClientConnector", "Cannot connect",
        "Network is unreachable", "ConnectionRefusedError",
    ])


_TIMEOUT_MSG = "처리가 너무 오래 걸려서 중단했어요. 조금 더 간단하게 말씀해 주시겠어요?"
_OFFLINE_MSG = ("인터넷 연결이 없어서 이 명령은 처리하기 어려워요. "
                "앱 실행, 볼륨 조절 같은 기본 명령은 오프라인에서도 쓸 수 있어요!")


class PluizGraphAgent:
    def __init__(
        self, *,
        llm: Any = None,
        tools: Optional[list] = None,
        security_check: Optional[Callable] = None,
        fast_resolve: Optional[Callable] = None,
        cache: Any = None,
        session_memory: Any = None,
        checkpointer: Any = None,
        settings: Any = None,
    ):
        self.settings = settings if settings is not None else _prod_settings()
        self.llm = llm if llm is not None else _prod_llm(self.settings)
        self.tools = tools if tools is not None else _prod_tools()
        self.security_check = security_check or _prod_security()
        self.cache = cache if cache is not None else (
            _prod_cache() if fast_resolve is None else None)
        self.session_memory = (session_memory if session_memory is not None
                               else _prod_session_memory())
        self.checkpointer = checkpointer or MemorySaver()
        self._fast_resolve = fast_resolve or self._default_fast_resolve

        self.graph = self._build()
        print(f"[PluizGraphAgent] 초기화 완료 | tools={len(self.tools)}개")

    def _build(self):
        return build_pluiz_graph(
            llm=self.llm, tools=self.tools,
            security_check=self.security_check,
            fast_resolve=self._fast_resolve,
            checkpointer=self.checkpointer,
        )

    def _default_fast_resolve(self, text: str) -> Optional[str]:
        """프로덕션 fast_path: 캐시 + 결정론적 라우터 (동기)."""
        from core.router import route_deterministic
        return resolve_fast_path(text, self.cache, route_deterministic)

    def _invoke_sync(self, payload, config):
        """동기 그래프 실행 (interrupt 호환). 오케스트레이터는 이를 스레드로 호출."""
        return self.graph.invoke(payload, config=config)

    def _pending_interrupt(self, config) -> bool:
        """해당 thread가 승인 대기(interrupt)로 멈춰 있는지."""
        try:
            st = self.graph.get_state(config)
            return bool(getattr(st, "next", ()))
        except Exception:
            return False

    def _clear_thread(self, thread_id: str):
        """MemorySaver에서 특정 thread 기록 제거. storage 없으면 전체 재생성."""
        storage = getattr(self.checkpointer, "storage", None)
        if storage is None:
            self.checkpointer = MemorySaver()
            self.graph = self._build()
            return
        for k in [k for k in list(storage.keys()) if k[0] == thread_id]:
            del storage[k]

    def _timeout(self) -> int:
        return getattr(self.settings, "agent_timeout", 30) or 30

    async def run_async(self, user_input: str, thread_id: str = "default") -> str:
        """비동기 실행 (기존 PluizAgent.run_async와 동일 시그니처).

        그래프는 동기 invoke를 워커 스레드에서 실행(asyncio.to_thread) — langgraph의
        interrupt가 sync 경로에서만 안정 동작하기 때문. 이벤트 루프는 블로킹하지 않음.
        승인 대기(interrupt) 중이면 이번 발화를 Command(resume)로 전달(승인/거부).
        """
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 10}

        # 승인 대기 상태면 이번 발화를 재개(resume) 신호로 전달
        if self._pending_interrupt(config):
            payload = Command(resume=user_input)
        else:
            # 하이브리드 가드(P3-4): 규칙 통과했지만 의심스러운 신규 입력만 LLM 판정.
            # 스레드+타임아웃, 실패 시 skip(규칙 결과만 사용).
            try:
                from core.guardrails import hybrid_guard_check
                blocked, reason = await asyncio.wait_for(
                    asyncio.to_thread(hybrid_guard_check, user_input, self.llm),
                    timeout=8)
                if blocked:
                    return reason
            except Exception as e:
                print(f"[PluizGraphAgent] 하이브리드 가드 skip(무시): {e}")
            payload = {"messages": [HumanMessage(content=user_input)]}

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._invoke_sync, payload, config),
                timeout=self._timeout())
        except (asyncio.TimeoutError, TimeoutError):
            self._clear_thread(thread_id)
            return _TIMEOUT_MSG
        except Exception as e:
            err = str(e)
            if "tool_calls that do not have a corresponding ToolMessage" in err:
                # 히스토리 오염 → 초기화 후 새 입력으로 1회 재시도
                self._clear_thread(thread_id)
                fresh = {"messages": [HumanMessage(content=user_input)]}
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(self._invoke_sync, fresh, config),
                        timeout=self._timeout())
                except (asyncio.TimeoutError, TimeoutError):
                    self._clear_thread(thread_id); return _TIMEOUT_MSG
                except Exception as e2:
                    self._clear_thread(thread_id)
                    return _OFFLINE_MSG if _is_network_error(e2) else f"명령 처리 중 오류가 발생했어요: {e2}"
            else:
                self._clear_thread(thread_id)
                return _OFFLINE_MSG if _is_network_error(e) else f"명령 처리 중 오류가 발생했어요: {e}"

        # 승인 대기(interrupt) 발생 → 질문을 반환하고 대기 (다음 발화가 승인/거부)
        itr = result.get("__interrupt__") if isinstance(result, dict) else None
        if itr:
            try:
                question = itr[0].value.get("question", "정말 진행할까요?")
            except Exception:
                question = "정말 진행할까요?"
            return question

        response = extract_response(result)
        if not response.strip():
            response = "명령을 실행했습니다."

        # LLM02/05: 출력 최종 마스킹(주민번호·카드번호·API키) — 사용자/TTS/기록 전에 적용
        try:
            from core.security import mask_sensitive_output
            response = mask_sensitive_output(response)
        except Exception as e:
            print(f"[PluizGraphAgent] 출력 마스킹 생략(무시): {e}")

        try:
            self.session_memory.save(user_input, response)
        except Exception as e:
            print(f"[PluizGraphAgent] session_memory 저장 실패(무시): {e}")

        return response

    async def stream(self, user_input: str, thread_id: str = "default") -> AsyncGenerator[str, None]:
        """스트리밍 실행 (동일 시그니처). P1.5-c: 결과를 단일 청크로 반환.
        (토큰 단위 스트리밍은 P1.5 이후 정교화 대상 — 기능 동작엔 지장 없음)"""
        result_text = await self.run_async(user_input, thread_id)
        yield result_text


# ── 싱글톤 ────────────────────────────────────────────────────────
_instance: Optional[PluizGraphAgent] = None

def get_graph_agent() -> PluizGraphAgent:
    global _instance
    if _instance is None:
        _instance = PluizGraphAgent()
    return _instance

def reset_graph_agent():
    global _instance
    _instance = None
