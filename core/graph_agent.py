"""
PluizGraphAgent — 그래프 오케스트레이터 (단일 엔진)
==================================================
core/graph.py의 StateGraph를 감싸 `run_async` / `stream` 공개 API를 제공한다.

M1-P1.5에서 구 엔진(create_react_agent + 수동 if/return 전처리)과 동일한
시그니처로 만들어 USE_GRAPH 플래그로 교체 가능하게 했고, P2~P4 검증을 거쳐
M1-P5에서 구 엔진을 제거해 **유일한 엔진**이 되었다.
구 엔진 원본과 복원 방법: docs/design/M1_P5_엔진단일화.md

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

from core.graph import (
    build_pluiz_graph, extract_response, current_turn_messages, _NOTHING_HAPPENED_MSG,
)
from core.logger import get_logger

# 턴 요약 로그. 2026-09-03에 "명령을 실행했습니다"만 나온 턴이 왜 그랬는지
# **로그로 답할 수 없었다** — 그래프가 턴 단위로 아무것도 남기지 않았기 때문이다.
# 도구가 돌았는지/응답이 비었는지만 알아도 원인이 갈린다.
_log = get_logger("Agent")
from core.fast_path import resolve_fast_path


# ── 프로덕션 기본값 (lazy) ─────────────────────────────────────────
def _prod_settings():
    from config.settings import get_settings
    return get_settings()

def _prod_llm(settings):
    from core.llm import build_llm
    return build_llm(settings)

def _prod_target_exists(dcall: dict) -> bool:
    """삭제 대상이 실제로 존재하는가. (hitl 노드가 승인을 묻기 **전에** 확인)

    없는 대상인데 "정말 삭제할까요?"를 먼저 묻고 승인한 뒤에야 "없네요"라고
    답하던 문제를 막는다. 경로 해석은 도구와 **같은 규칙**을 써야 하므로
    `tools/filesystem.py`의 것을 그대로 재사용한다 — 여기서 따로 구현하면
    "바탕화면/..." 해석이 어긋나 엉뚱한 판정이 난다.
    """
    import os
    from tools.filesystem import _resolve_location_in_path

    args = dcall.get("args", {}) or {}
    target = args.get("file_path") or args.get("folder_path") or ""
    if not target:
        return True            # 판단할 수 없으면 원래대로 승인 절차를 밟는다
    return os.path.exists(_resolve_location_in_path(str(target)))

def _prod_visual_check(window: str, question: str) -> str:
    """화면을 실제로 보고 답한다. (visual_verify 노드가 도구 실행 직후 호출)

    Vision 도구를 다시 짜지 않고 `tools/vision.describe_screen`을 **그대로 재사용**한다.
    축소(긴 변 1600px)·임시파일 정리·오류 문자열 규약이 전부 거기 있어서, 여기서
    다시 구현하면 두 벌이 되어 한쪽만 고쳐진다.
    """
    from tools.vision import describe_screen
    return describe_screen.invoke({"window": window, "question": question})

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
        target_exists: Optional[Callable[[dict], bool]] = None,
        visual_check: Optional[Callable[[str, str], str]] = None,
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
        # 삭제 대상 존재 확인 (hitl이 묻기 전에). mock 테스트는 가짜 경로를 쓰므로
        # 주입할 수 있어야 한다 — 안 그러면 "없는 대상"으로 판정돼 승인 절차가 통째로 건너뛰어진다.
        self.target_exists = target_exists if target_exists is not None else _prod_target_exists
        # 실행 결과 시각적 검증 (Phase 2). None이면 graph.py가 노드 자체를 만들지 않아
        # 예전과 완전히 동일한 tools → agent 경로로 돈다.
        # ⚠️ 켜져 있으면 사용자가 화면을 묻지 않아도 스크린샷이 외부 LLM으로 나간다
        #    (OWASP LLM02). 그래서 설정 스위치를 통과해야만 붙인다.
        if visual_check is not None:
            self.visual_check = visual_check
        elif getattr(self.settings, "vision_verify_enabled", False):
            self.visual_check = _prod_visual_check
        else:
            self.visual_check = None

        self.graph = self._build()
        print(f"[PluizGraphAgent] 초기화 완료 | tools={len(self.tools)}개 | "
              f"화면검증={'on' if self.visual_check else 'off'}")

    def _build(self):
        return build_pluiz_graph(
            llm=self.llm, tools=self.tools,
            security_check=self.security_check,
            fast_resolve=self._fast_resolve,
            checkpointer=self.checkpointer,
            target_exists=self.target_exists,
            visual_check=self.visual_check,
        )

    def _default_fast_resolve(self, text: str) -> Optional[str]:
        """프로덕션 fast_path: 캐시 + 결정론적 라우터 (동기)."""
        from core.router import route_deterministic
        return resolve_fast_path(text, self.cache, route_deterministic)

    def _invoke_sync(self, payload, config):
        """동기 그래프 실행 (interrupt 호환). 오케스트레이터는 이를 스레드로 호출."""
        return self.graph.invoke(payload, config=config)

    def _pending_interrupt(self, config) -> bool:
        """해당 thread가 승인 대기(interrupt)로 멈춰 있는지.

        ⚠️ 여기서 False가 나오면 사용자의 "네"가 **승인이 아니라 새 명령**이 된다.
          예외를 조용히 삼키면 그 사실을 아무도 모른다 — 2026-09-03 실기에서
          "네"가 승인으로 안 먹은 원인을 로그로 못 밝혔다. 그래서 남긴다.
        """
        try:
            st = self.graph.get_state(config)
            nxt = tuple(getattr(st, "next", ()) or ())
            _log.debug("승인 대기 확인 | thread=%s | next=%s",
                       config.get("configurable", {}).get("thread_id"), nxt or "없음")
            return bool(nxt)
        except Exception as e:
            _log.warning("승인 대기 확인 실패(새 명령으로 처리됨): %s: %s",
                         type(e).__name__, e)
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
            _log.info("승인 재개 | thread=%s | 답변=%r", thread_id, user_input)
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
        tool_names = self._turn_tool_names(result)
        if not response.strip():
            # 여기까지 왔는데 비었으면 도구도 안 돌았다는 뜻이다(output_guard가
            # 도구 결과로 복원하기 때문). 됐다고 하지 않는다.
            _log.warning("빈 응답 — 도구도 실행되지 않았다. 입력=%r", user_input)
            response = _NOTHING_HAPPENED_MSG
        _log.info("턴 완료 | 입력=%r | 도구=%s | 응답 %d자",
                  user_input, tool_names or "없음", len(response))

        # LLM02/05: 출력 최종 마스킹(주민번호·카드번호·API키) — 사용자/TTS/기록 전에 적용
        try:
            from core.security import mask_sensitive_output
            response = mask_sensitive_output(response)
        except Exception as e:
            print(f"[PluizGraphAgent] 출력 마스킹 생략(무시): {e}")

        # P4-2: LLM이 성공 실행한 화이트리스트 제어명령의 사용자 표현을 학습(맞춤형·오프라인 확대)
        self._maybe_learn(user_input, result)

        try:
            self.session_memory.save(user_input, response)
        except Exception as e:
            print(f"[PluizGraphAgent] session_memory 저장 실패(무시): {e}")

        return response

    @staticmethod
    def _turn_tool_names(result: Any) -> list[str]:
        """이번 턴에 실제로 호출된 도구 이름. (로그용 — 실패해도 무시)"""
        try:
            msgs = current_turn_messages(result.get("messages", []))
            return [c.get("name", "?") if isinstance(c, dict) else getattr(c, "name", "?")
                    for m in msgs for c in (getattr(m, "tool_calls", None) or [])]
        except Exception:
            return []

    def _maybe_learn(self, user_input: str, result: Any) -> None:
        """그래프 실행 결과에서 도구 호출을 추출해, 성공 + 화이트리스트면 캐시에 학습.
        - fast_path 히트(도구호출 없음)·보안차단·오류는 자연히 제외됨.
        - 실제 학습 자격(단일 화이트리스트 도구·자유파라미터 없음)은 cache.learn()이 최종 판단.

        ⚠️ **이번 턴의 메시지만 본다**(`current_turn_messages`).
          `result["messages"]`는 thread의 전체 히스토리라, 그대로 훑으면:
            - 턴1의 open_app이 턴2의 "고마워"에 붙어 엉뚱한 표현이 학습되고
            - 도구 호출이 2개 이상 쌓이는 순간(len != 1) 그 세션의 학습이 영구히 멈추고
            - 턴1의 도구 실패가 그 세션의 모든 후속 학습을 차단한다.
          즉 P4 동적 학습이 thread당 1턴만 동작했다. 범위를 턴으로 좁혀 고친다.
        """
        cache = getattr(self, "cache", None)
        if cache is None or not isinstance(result, dict):
            return
        try:
            from langchain_core.messages import ToolMessage
            msgs = current_turn_messages(result.get("messages", []))
            tool_calls = []
            for m in msgs:
                for c in (getattr(m, "tool_calls", None) or []):
                    if isinstance(c, dict):
                        tool_calls.append({"name": c.get("name", ""), "args": c.get("args", {}) or {}})
                    else:
                        tool_calls.append({"name": getattr(c, "name", ""), "args": getattr(c, "args", {}) or {}})
            if not tool_calls:
                return
            # 도구 실행 실패 시 학습 금지
            for m in msgs:
                if isinstance(m, ToolMessage):
                    c = m.content
                    if isinstance(c, list):
                        c = " ".join(str(b) for b in c)
                    if str(c).strip()[:1] in ("✗",) or str(c).strip().startswith(("[오류", "오류", "Error", "[error")):
                        return
            cache.learn(user_input, tool_calls)
        except Exception as e:
            print(f"[PluizGraphAgent] 학습 시도 실패(무시): {e}")

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
