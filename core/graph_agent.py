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
import re
import time
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
from core.fast_path import resolve_fast_path, is_compound_command
from core.tool_result import tool_failed


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

def _prod_plan_decompose(llm):
    """복합 명령을 단계로 나눈다 (M3). **도구를 붙이지 않은** llm으로 턴당 1회.

    replan은 없다 — 계획은 한 번만 세운다(ADR §3-1). 프롬프트를 여기서 새로 쓰지 않고
    `core.graph.PLAN_DECOMPOSE_PROMPT`를 그대로 쓴다. 두 벌이 되면 한쪽만 고쳐진다.
    실패(예외·산문)의 착지점은 오류가 아니라 **오늘의 정상 경로**다 — planner 노드가
    전부 삼키고 단일 루프로 진행한다.
    """
    from langchain_core.messages import SystemMessage
    from core.graph import PLAN_DECOMPOSE_PROMPT, _msg_text

    def _decompose(text: str) -> str:
        resp = llm.invoke([SystemMessage(content=PLAN_DECOMPOSE_PROMPT),
                           HumanMessage(content=text)])
        return _msg_text(resp)

    return _decompose


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
        plan_decompose: Optional[Callable[[str], Any]] = None,
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

        # 계획 수립 (M3). None이면 graph.py가 planner 노드 자체를 만들지 않아
        # 예전과 완전히 동일한 fast_path → agent 경로로 돈다.
        # ⚠️ 기본 꺼짐이다(settings.plan_enabled=False) — 라이브 증거 전엔 켜지 않는다.
        if plan_decompose is not None:
            self.plan_decompose = plan_decompose
        elif getattr(self.settings, "plan_enabled", False):
            self.plan_decompose = _prod_plan_decompose(self.llm)
        else:
            self.plan_decompose = None

        self.graph = self._build()
        print(f"[PluizGraphAgent] 초기화 완료 | tools={len(self.tools)}개 | "
              f"화면검증={'on' if self.visual_check else 'off'} | "
              f"계획={'on' if self.plan_decompose else 'off'}")

    def _build(self):
        return build_pluiz_graph(
            llm=self.llm, tools=self.tools,
            security_check=self.security_check,
            fast_resolve=self._fast_resolve,
            checkpointer=self.checkpointer,
            target_exists=self.target_exists,
            visual_check=self.visual_check,
            plan_decompose=self.plan_decompose,
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

        🚨 **`next`만 보면 안 된다 (BL-17).** `interrupt()`가 **같은 노드 안에서
          두 번째로** 걸리면 — 즉 애매한 답에 «다시 물어볼» 때 — 그 노드는
          «다음에 실행할 노드»가 아니라 **«실행 중간에 멈춘 노드»** 다.
          `next`는 비고 `tasks[].interrupts`에만 남는다:

              | 신호               | 1차 질문   | 재질문   |
              | next               | ('hitl',) | **없음** |
              | tasks[].interrupts | 1         | **1**    |

          2026-09-10 실기에서 이것 때문에 두 번 깨졌다 — 재질문 뒤의 '그래'가
          새 명령이 돼서 **승인 질문이 처음부터 다시 떴고**, 사용자는 같은 삭제를
          두 번 승인해야 했다. 한 번은 승인 대기가 통째로 사라져
          *"네? 어떤 작업을 말씀하시는지…"* 로 끝났다.

          ⚠️ mock 테스트는 `Command(resume=)`를 **그래프에 직접** 줘서 이 자리를
            건너뛴다. 그래서 114건이 전부 초록인데 실기가 깨졌다.
            `tests/test_hitl_graph.py` §BL-17이 이제 이 함수를 직접 부른다.
        """
        try:
            st = self.graph.get_state(config)
            nxt = tuple(getattr(st, "next", ()) or ())
            n_itr = self._count_interrupts(st)
            _log.debug("승인 대기 확인 | thread=%s | next=%s | 대기 중인 질문=%d",
                       config.get("configurable", {}).get("thread_id"),
                       nxt or "없음", n_itr)
            return bool(nxt) or n_itr > 0
        except Exception as e:
            _log.warning("승인 대기 확인 실패(새 명령으로 처리됨): %s: %s",
                         type(e).__name__, e)
            return False

    @staticmethod
    def _count_interrupts(st) -> int:
        """스냅샷에 «답을 기다리는 질문»이 몇 개인가.

        langgraph 버전에 따라 스냅샷에 `interrupts`가 바로 있기도 하고
        `tasks[].interrupts`에만 있기도 하다. **둘 다 본다** — 한쪽만 보면
        버전이 올라갈 때 조용히 0이 되고, 그러면 BL-17이 그대로 재발한다.
        """
        direct = getattr(st, "interrupts", None)
        if direct:
            return len(direct)
        total = 0
        for t in (getattr(st, "tasks", ()) or ()):
            total += len(getattr(t, "interrupts", ()) or ())
        return total

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
        # ⚠️ 계획이 켜지면 상한을 반드시 올린다(ADR §1-1). 10은 이미 **순차 도구 3회**
        #   에서 정확히 소진된다(input_guard·fast_path·agent·tools·agent·output_guard
        #   = 도구 1회에 6, 이후 도구 1회마다 +2). 2단계 계획에 planner 한 슈퍼스텝과
        #   hitl·visual_verify가 하나만 끼어도 즉시 GraphRecursionError이고, 그 예외는
        #   아래 포괄 except가 잡아 **스레드를 지우고** "오류가 발생했어요"로 끝난다.
        #   반대로 꺼져 있을 땐 올리지 않는다 — 폭주 ReAct 루프가 2.4배 오래 돈다.
        # 계측(2026-09-08): 이 턴이 몇 초 걸렸는지. 11월 「SW 검증·성능 측정」의 전제라
        # 지금부터 쌓아 둔다 — 그날 넣으면 과거 데이터가 0이다. 화면 감시(`elapsed`)와
        # 같은 방식(perf_counter)이다. ⚠️ 하이브리드 가드의 LLM 왕복도 포함된다 —
        # 사용자가 체감하는 시간이 그것까지 합한 값이기 때문이다.
        started = time.perf_counter()

        limit = 24 if self.plan_decompose is not None else 10
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": limit}

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
            # 승인 질문으로 끝난 턴은 "턴 완료"를 찍지 않는다. 여기서 안 남기면
            # **HITL 턴만 지연 통계에서 통째로 빠져** 평균이 낙관적으로 기운다.
            _log.info("승인 대기 | 입력=%r%s", user_input,
                      self._metrics_note(result, time.perf_counter() - started))
            return question

        response = extract_response(result)
        tool_names = self._turn_tool_names(result)
        if not response.strip():
            # 여기까지 왔는데 비었으면 도구도 안 돌았다는 뜻이다(output_guard가
            # 도구 결과로 복원하기 때문). 됐다고 하지 않는다.
            _log.warning("빈 응답 — 도구도 실행되지 않았다. 입력=%r", user_input)
            response = _NOTHING_HAPPENED_MSG
        _log.info("턴 완료 | 입력=%r | 도구=%s | 응답 %d자%s%s%s",
                  user_input, tool_names or "없음", len(response),
                  self._reason_note(result, response, tool_names),
                  self._plan_note(result),
                  self._metrics_note(result, time.perf_counter() - started))

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

    # 「못 함」으로 분류할 응답의 꼴. **응답 본문은 로그에 남기지 않는다** —
    # 분류는 여기 프로세스 안에서 하고, 로그에는 **한 단어**만 나간다(BL-28).
    _FAILED_RE = re.compile(
        r"(못 했|못했|못 봤|못 찾|찾지 못|하지 못|할 수 없|안 됐|안됐|실패|"
        r"시작하지 못|처리하지 못|어려워요|오류가 발생)")

    @classmethod
    def _reason_note(cls, result: Any, response: str, tool_names: list) -> str:
        """도구를 **하나도 안 부른** 턴이 왜 그랬는지 한 단어로. (BL-28)

        `도구=없음`에는 서로 다른 네 가지가 섞여 있었고, 로그가 응답을 «13자»로만
        남겨 **사후에 못 갈랐다.** 2026-09-10 도구 사용 실측 ②가 그래서 답을 못 냈다
        (명령처럼 보이는 후보 7턴이 나왔는데 «못 한 것»인지 «안 해도 됐던 것»인지 불명).
        → [research/2026-09_도구사용_실측.md](../docs/research/2026-09_도구사용_실측.md)

        | 태그 | 뜻 |
        |---|---|
        | `캐시` | fast_path가 처리했다. **도구를 안 부른 게 아니라 LLM을 안 거친 것** |
        | `차단` | input_guard가 막았다(보안) |
        | `승인거부` | 위험 도구를 사용자가 거부했다 |
        | `못함` | 모델이 «못 했다»고 답했다 ← **여기가 진짜 실패다** |
        | `잡담` | 명령이 아니었다 |

        ⚠️ **도구가 하나라도 돌았으면 붙이지 않는다.** 그 턴은 «안 부른 턴»이 아니다.
        ⚠️ 분류는 휴리스틱이다(응답 문구를 본다). 추세로 쓰고 단정하지 않는다.
        ⚠️ **응답 전문을 로그에 넣지 않는다** — 개인정보가 로그로 새는 길이고
           [보안 방향](../docs/ARCHITECTURE.md)과 반대다. 한 단어면 충분하다.
        """
        if tool_names:
            return ""
        try:
            state = result if isinstance(result, dict) else {}
            decision = state.get("decision") or ""
            if decision == "fast_hit":
                return " | 사유=캐시"
            if decision == "blocked":
                return " | 사유=차단"
            if state.get("deletion_cancelled"):
                return " | 사유=승인거부"
            if response == _NOTHING_HAPPENED_MSG or cls._FAILED_RE.search(response or ""):
                return " | 사유=못함"
            return " | 사유=잡담"
        except Exception:                       # 분류가 턴을 죽이지 않는다
            return ""

    @staticmethod
    def _plan_note(result: Any) -> str:
        """계획을 세운 턴이면 " | 계획 1/2"처럼 남긴다. (로그용 — 실패해도 무시)

        **몇 단계를 못 했는지 사후에 알 수 있어야 한다**는 게 이 기능의 존재 이유다.
        사용자에게 말하는 건 output_guard가 하고, 여기는 로그 쪽 절반이다.
        """
        try:
            plan = (result or {}).get("plan") or []
            if not plan:
                return ""
            done = min(int((result or {}).get("plan_cursor") or 0), len(plan))
            return f" | 계획 {done}/{len(plan)}"
        except Exception:
            return ""

    @staticmethod
    def _turn_usage(result: Any) -> tuple[int, int, int]:
        """이번 턴 LLM 응답의 (usage가 실린 응답 수, 입력토큰, 출력토큰).

        `AIMessage.usage_metadata`는 langchain-core의 **표준 필드**이고
        langchain-google-genai 4.x가 응답마다 채운다(`chat_models.py`의 `lc_usage`).
        2026-09-08에 설치본에서 직접 확인했다 — 안 실려 온다면 아래 «미상»으로 떨어질 뿐
        턴은 멀쩡히 끝난다.

        ⚠️ **이번 턴만 본다**(`current_turn_messages`). `result["messages"]`는 thread
          전체라, 그냥 훑으면 지난 턴 토큰이 이번 턴에 계속 더해져 **누적값이 턴 비용으로
          기록된다**(절대규칙 6이 말하는 오염의 토큰판).

        usage가 실린 메시지만 세므로 output_guard가 덧붙인 AIMessage나 mock 응답은
        자연히 빠진다. 그래서 이 수는 "LLM을 몇 번 불렀나"가 아니라
        **"몇 번의 왕복을 실제로 계측했나"** 이고, 0이면 «미상»이라고 말한다.

        토큰은 왕복마다 히스토리를 다시 보내므로 입력이 중복 계상되는데,
        그게 **실제로 청구되는 값**이라 그대로 더한다.
        """
        calls = tin = tout = 0
        try:
            for m in current_turn_messages((result or {}).get("messages", [])):
                u = getattr(m, "usage_metadata", None) or {}
                if not u:
                    continue
                calls += 1
                tin += int(u.get("input_tokens") or 0)
                tout += int(u.get("output_tokens") or 0)
        except Exception:
            return calls, tin, tout
        return calls, tin, tout

    @classmethod
    def _metrics_note(cls, result: Any, elapsed: float) -> str:
        """" | 소요 1.83s | LLM 2회 | 토큰 in=1234 out=56" 형태의 계측 꼬리표.

        **형식을 함부로 바꾸지 말 것** — 11월에 이 줄을 grep해서 추이를 낸다.
        (`도구=[...]`를 세어 도구 사용률을 내기로 한 것과 같은 방식이다.)

        세 가지 경우를 구분해서 말한다:
          - 계측됨      → `LLM 2회 | 토큰 in=1234 out=56`
          - 캐시 히트   → `LLM 0회(캐시) | 토큰 0`  ← **차별점의 근거 데이터다**
          - 계측 실패   → `LLM ?회 | 토큰 미상`     ← 불렀는데 usage가 없었다

        마지막 경우를 «0회»라고 쓰지 않는 게 핵심이다. 안 부른 것과 못 잰 것을
        같은 숫자로 적으면, 11월에 캐시 효과가 실제보다 커 보인다.
        """
        try:
            calls, tin, tout = cls._turn_usage(result)
            cached = isinstance(result, dict) and result.get("decision") == "fast_hit"
            if calls:
                tail = f"LLM {calls}회 | 토큰 in={tin} out={tout}"
            elif cached:
                # 캐시 히트는 그래프 안에서 LLM을 한 번도 부르지 않는다(fast_path가
                # 도구를 직접 돌린다). ⚠️ 다만 하이브리드 가드가 의심 입력에 한해
                # 그래프 **밖에서** 한 번 부를 수 있다 — 그 왕복은 여기 안 잡힌다.
                tail = "LLM 0회(캐시) | 토큰 0"
            else:
                tail = "LLM ?회 | 토큰 미상"
            return f" | 소요 {elapsed:.2f}s | {tail}"
        except Exception:                       # 계측이 턴을 죽이지 않는다
            return ""

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

        # ── BL-21: **복합 명령은 학습하지 않는다.** ───────────────────
        # 2026-09-07 라이브에서 이렇게 굳었다:
        #     "메모장이랑 계산기 열어줘"           → [open_app(메모장)]   ← 계산기가 없다
        #     "메모장 열고 testing.txt 지워달라고"  → [open_app(메모장)]   ← 삭제가 없다
        # 계획이 2단계인데 **한 단계를 건너뛰어** 도구가 1개만 돌았고, 완료 판정이
        # 그걸 성공으로 읽어(계획 2/2) 여기까지 왔다. 다음부터는 캐시 히트라
        # **LLM을 거치지도 않으므로 틀린 답이 고쳐질 기회가 없다.**
        #
        # ⚠️ 통째로 막아도 **잃는 게 없다**: `_is_learnable`이 `len(tool_calls) != 1`을
        #   이미 거절하므로, 계획이 제대로 실행된 턴(도구 2개 이상)은 애초에 학습되지
        #   않는다. 즉 **여기 도달하는 복합 턴은 실패한 턴뿐**이다.
        #
        # 계획이 꺼져 있어도(`PLAN_ENABLED=false`) 같은 일이 나므로 발화로도 본다.
        # 읽는 쪽에서 *"잔여 명령이 있으면 캐시를 포기한다"* 고 정한 BL-15의 쓰기 쪽 짝이다.
        # (`is_compound_command`는 부정어까지 넓게 잡는데, 여기서는 넓은 게 안전하다 —
        #  학습을 덜 할 뿐이고, 부정어 학습 거부는 BL-02가 바라던 것이다.)
        try:
            planned = len(result.get("plan") or [])
            if planned or is_compound_command(user_input):
                _log.info("[BL-21] 복합 명령은 학습하지 않는다 | 입력=%r | 계획 %d단계",
                          user_input, planned)
                return
        except Exception as e:                    # 학습은 부가 기능이다 — 턴을 죽이지 않는다
            print(f"[PluizGraphAgent] 복합 판정 실패(학습 계속): {e}")
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
            # 도구 실행 실패 시 학습 금지.
            # 판정은 core/tool_result.py 하나가 한다 — 여기 규칙을 따로 두면
            # 읽는 쪽 셋이 다시 어긋난다(BL-29). ⚠️ 는 «부분 실패»라 여기서도 막는다:
            # 최대화가 안 된 턴을 학습하면 안 되는 상황과 함께 굳는다.
            for m in msgs:
                if isinstance(m, ToolMessage) and tool_failed(m.content):
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
