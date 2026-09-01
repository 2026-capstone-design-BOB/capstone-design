"""
Pluiz Agent Core
----------------
LangGraph 기반 ReAct 에이전트.
사용자 입력 → LLM이 도구 선택 → 결정론적 실행 → 결과 관찰 → 반복
"""

import re
import asyncio
from typing import AsyncGenerator
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, AIMessageChunk, ToolMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from config.settings import get_settings
from core.tool_registry import get_all_tools
from memory.session import SessionMemory


def _build_system_prompt() -> str:
    """현재 날짜/시간을 포함한 시스템 프롬프트 생성."""
    from datetime import datetime
    now = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    date_str = f"{now.year}년 {now.month}월 {now.day}일 ({weekdays[now.weekday()]})"
    time_str = f"{now.hour:02d}:{now.minute:02d}"
    return f"""당신은 소윤이입니다. 한국어 음성 명령으로 Windows PC를 제어해주는 AI 에이전트예요.

현재 날짜/시간: {date_str} {time_str}
(일정 추가 등 날짜 계산이 필요할 때 이 정보를 기준으로 사용하세요. "내일"은 {now.month}월 {now.day + 1}일, "다음 주"는 7일 후입니다.)

응답 스타일 (반드시 준수):
- 응답은 1~2문장으로 짧고 간결하게. 긴 설명, 목록, 부가 설명 절대 금지.
- 말투는 친근한 구어체로. "~했습니다" 대신 "~했어요", "~할게요", "~됐어요" 사용.
- 도구 실행 결과는 핵심만 한 문장으로 요약. 경로나 기술적 세부사항 생략.
- 예시: "메모장 켰어요!", "볼륨 50%로 맞췄어요.", "강남역 지도 열었어요!"

핵심 규칙 (반드시 준수):
- PC 제어 명령(앱 실행/종료, 볼륨, 파일 생성, 웹 검색 등)은 반드시 해당 도구를 호출해서 실행해요.
- 도구 호출 없이 "실행했어요"라고만 응답하는 건 절대 안 돼요.
- 명령이 충분히 명확하면 확인 없이 바로 도구를 호출해요.
- "유튜브에서/유튜브에/유튜브로 X 검색해줘", "유튜브 X 틀어줘" → 반드시 youtube_search 도구 사용. (web_search 금지)
- "지도에서 X 찾아줘" / "X 가는 길 알려줘" / "X 어디야" → 반드시 map_search 도구 사용.
- 일정 추가 요청 → 반드시 create_calendar_event 도구 사용. 날짜는 위 현재 날짜 기준으로 계산해서 YYYY-MM-DD 형식으로 전달.

보안 지침 (반드시 준수):
- 파일/폴더 삭제 명령은 "정말 삭제할까요?" 확인 후 실행해요.
- 휴지통 비우기, 영구 삭제 요청은 다시 한번 확인해요.
- C:\\Windows, System32 등 시스템 경로 접근은 거부해요.
- 절대 실행하지 않을 것: rm -rf, del /f /s, format, reg delete, shutdown /f 등.

일반:
- "X 알려줘", "X 어때", "X 뭐야" → fetch_web_info로 정보 가져와서 답해요. 지역·조건이 불명확해도 묻지 말고 바로 검색해요. (예: "날씨 알려줘" → fetch_web_info("오늘 날씨"))
- "X 검색해줘", "X 찾아줘" → web_search로 브라우저 열어요. 지역·조건 불명확해도 묻지 말고 바로 검색해요. (예: "날씨 검색해줘" → web_search("오늘 날씨"))
- "X 검색해서 파일/메모장에 저장해줘" 등 검색+저장 작업은 반드시 이 순서로:
  1. fetch_web_info(query="X") → 검색 결과 및 URL 확보
  2. crawl_page(url) → 필요하면 실제 페이지 본문 읽기 (선택)
  3. create_file(name="파일명.txt", content=정리된내용) → 파일에 직접 저장
  브라우저를 열거나 사용자에게 내용을 직접 붙여넣으라고 하면 절대 안 돼요.
- "비교표/스펙표를 엑셀로 저장해줘" 작업:
  1. fetch_web_info()로 관련 URL 확보
  2. crawl_page(url)로 실제 페이지 본문 읽기
  3. 수집한 웹 데이터를 write_excel로 저장
  웹 데이터 수집이 실패하면 "페이지를 읽어오지 못했어요"라고 솔직하게 말해요. 근거 없는 정보로 파일을 만들지 마세요.
- type_text 도구는 사용자가 "타이핑해줘", "입력해줘"라고 명시적으로 요청할 때만 써요.
  검색 결과를 채팅창이나 다른 앱 입력창에 타이핑하는 용도로 절대 쓰지 마세요.
- 불가능한 요청은 이유를 한 문장으로 설명해요.
- 응답은 항상 한국어로 해요.
"""

SYSTEM_PROMPT = _build_system_prompt()

# 히스토리 최대 메시지 수 (시스템 메시지 제외). ~10턴에 해당.
_MAX_HISTORY_MSGS = 20


def _build_prompt_modifier(state: dict) -> list:
    """
    LangGraph prompt callable — 매 LLM 호출 시 실행.
    - 시스템 프롬프트: 현재 날짜/시간으로 매번 갱신
    - 히스토리: 최근 _MAX_HISTORY_MSGS개만 LLM에 전달 (오래된 맥락 자동 드롭)
    """
    from langchain_core.messages import SystemMessage, trim_messages

    system_msg = SystemMessage(content=_build_system_prompt())

    # 시스템 메시지 제외한 대화 히스토리
    history = [m for m in state["messages"] if not isinstance(m, SystemMessage)]

    try:
        trimmed = trim_messages(
            history,
            max_tokens=_MAX_HISTORY_MSGS,
            strategy="last",
            token_counter=len,   # 메시지 개수 기준 (토큰 수 아님)
            allow_partial=False,
            start_on="human",    # HumanMessage로 시작 보장
        )
    except Exception:
        # trim 실패 시 단순 슬라이싱 fallback
        trimmed = history[-_MAX_HISTORY_MSGS:]

    return [system_msg] + trimmed


RETRY_PROMPT = """이전 응답에서 도구를 호출하지 않았습니다.
PC 제어 명령입니다. 반드시 적절한 도구를 호출하여 실행해주세요.

도구 호출 예시:
- 앱 실행 → open_app("앱이름")
- 볼륨 조절 → volume_up() / volume_down() / volume_set(level=50)
- 파일 생성 → create_file(name="파일명.txt", location="desktop")
- 폴더 생성 → create_folder(name="폴더명", location="desktop")
- 웹 검색 → web_search(query="검색어")
- 유튜브 검색 → youtube_search(query="검색어")
- 지도 검색 → map_search(destination="장소명")

지금 즉시 위 형식으로 도구를 호출하세요."""

# ── T04: 도구 오류 감지 패턴 ─────────────────────────────────────
# ToolMessage.content가 아래 패턴으로 시작하면 도구 실행 실패로 판단
_TOOL_ERROR_RE = re.compile(
    r'^\[(?:오류|error|[가-힣a-zA-Z_]+ 오류)\]'  # [오류], [type_text 오류], [Error] 등
    r'|^오류\s*:'                                   # "오류: ..."
    r'|^Error\s*:',                                 # "Error: ..."
    re.IGNORECASE,
)

# LLM 응답이 "성공처럼" 보이는 패턴 — 도구 오류와 함께 감지되면 보정 대상
# "못했어요", "하지 못했어요" 같은 부정형은 제외 (negative lookbehind)
_SUCCESS_LIKE_RE = re.compile(
    r'(?<!못)(?:했어요|켰어요|열었어요|닫았어요|실행했어요|설정했어요|만들었어요|저장했어요|됐어요|완료했어요|완료)[!.]?\s*$'
)


# ── 결정론적 라우터 패턴 ────────────────────────────────────────────
# LLM 없이 처리 가능한 파라미터형 명령 패턴 (youtube_search, map_search, create_folder)
# 캐시 시드는 고정 패턴만 커버하므로 동적 파라미터는 여기서 처리

_ROUTER_YT = re.compile(
    r'유튜브(?:에서|에|로)?\s+(.+?)\s*(?:검색\s*해\s*줘|검색해|틀어\s*줘|틀어|찾아\s*줘|찾아)\s*$'
)
_ROUTER_MAP_ROUTE = re.compile(
    r'^(.+?)에서\s+(.+?)\s+(?:가는\s*길|경로)\s*(?:알려\s*줘|찾아\s*줘)?\s*$'
)
_ROUTER_MAP_SIMPLE = re.compile(
    r'^(.+?)\s+(?:지도\s*(?:찾아\s*줘|보여\s*줘|열어\s*줘|검색\s*해\s*줘|알려\s*줘)?|어디야|어디에\s*있어|어디에요)\s*$'
)
_ROUTER_FOLDER = re.compile(
    r'^(?:(바탕화면|데스크탑|다운로드|문서|사진)에\s+)?(.+?)\s+(?:폴더|디렉토리)\s+(?:만들어\s*줘|만들어|생성\s*해\s*줘|생성해)\s*$'
)
_ROUTER_VOLUME = re.compile(
    r'볼륨\s*(\d+)\s*(?:%로|%|퍼센트|으로|로)?\s*(?:설정\s*해\s*줘|설정해|맞춰\s*줘|맞춰|해\s*줘)?\s*$'
)
_ROUTER_VOL_UP = re.compile(
    r'^볼륨\s*(\d+)?\s*(?:정도만?|만큼|씩|만)?\s*(?:올려|높여|크게)\s*(?:줘|달라고|줄래|해\s*줘)?\s*$'
)
_ROUTER_VOL_DOWN = re.compile(
    r'^볼륨\s*(\d+)?\s*(?:정도만?|만큼|씩|만)?\s*(?:내려|줄여|작게)\s*(?:줘|달라고|줄래|해\s*줘)?\s*$'
)
_ROUTER_MAXIMIZE = re.compile(
    r'^(.+?)\s+최대화\s*(?:해\s*줘|해달라고|해|줄래)?\s*$'
)
_ROUTER_MINIMIZE = re.compile(
    r'^(.+?)\s+최소화\s*(?:해\s*줘|해달라고|해|줄래)?\s*$'
)

# 복합 명령 감지 패턴 — 캐시 바이패스 후 LLM으로 전달
# "닫고/열고/켜고/끄고" 등 동사 연결형 + 문맥 참조형("방금", "빼고" 등)도 포함
_COMPOUND_CMD = re.compile(
    r'이랑|랑\s|하고\s|그리고\s|그리고$|,\s*그리고|,\s*그다음|다음에\s'
    r'|닫고\s|열고\s|켜고\s|끄고\s|보내고\s|저장하고\s|검색하고\s|만들고\s'
    r'|방금|아까|빼고|제외하고|것들|이것|그것|다\s*닫|전부\s*닫|모두\s*닫'
)

# 단어 하나짜리 앱 이름 집합 — 2개 이상 등장하면 다중 앱 명령으로 판단
_MULTI_APP_NAMES = frozenset([
    '크롬', '메모장', '계산기', '탐색기', '카카오', '엣지', '스팀',
    '디스코드', '슬랙', '노트패드', '워드', '엑셀', '파워포인트',
])


def _is_multi_app_command(text: str) -> bool:
    """두 개 이상의 앱 이름이 포함된 다중 앱 명령 감지."""
    count = sum(1 for app in _MULTI_APP_NAMES if app in text)
    return count >= 2


# PC 제어 명령으로 판단하는 키워드 집합
# 이 키워드가 포함된 입력에서 도구가 호출되지 않으면 재시도 트리거
_CONTROL_KEYWORDS = frozenset([
    "열어", "켜줘", "켜", "실행", "시작", "띄워",
    "닫아", "꺼줘", "꺼", "종료",
    "검색", "찾아", "만들어", "저장", "열기",
    "볼륨", "소리", "밝기", "화면",
    "스크린샷", "캡처",
    "유튜브", "구글", "네이버", "지도",
    "탐색기", "파일", "폴더", "앱",
    "크롬", "엣지", "메모장", "계산기", "카카오",
    "배터리", "최대화", "최소화", "바탕화면",
    "입력", "타이핑", "붙여", "복사",
    "클립보드",
])


def _is_network_error(e: Exception) -> bool:
    """LLM API 호출 실패가 네트워크 오류(오프라인)인지 판단."""
    msg = str(e)
    return any(kw in msg for kw in [
        "getaddrinfo failed", "ClientConnector", "Cannot connect",
        "Network is unreachable", "ConnectionRefusedError", "TimeoutError",
    ])


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

        # LangGraph ReAct 에이전트 생성 (초기화 시점 날짜로 프롬프트 생성)
        self.graph = create_react_agent(
            model=self.llm,
            tools=self.tools,
            checkpointer=self.checkpointer,
            prompt=_build_prompt_modifier,   # trim + 날짜 갱신 포함 callable
        )

        print(f"[PluizAgent] 초기화 완료 | provider={settings.llm_provider} | tools={len(self.tools)}개")

    async def run_async(self, user_input: str, thread_id: str = "default",
                        _skip_cache: bool = False) -> str:
        """비동기 실행. FastAPI 엔드포인트에서 사용.

        _skip_cache: True면 캐시 조회를 건너뜀.
                     stream()에서 이미 캐시 미스 확인 후 이 메서드를 호출할 때 사용
                     (BUG-06: 이중 캐시 조회 방지).
        """
        # 복합 명령("이랑", "랑", "닫고" 등 / 다중 앱 나열) 감지 → 캐시 바이패스
        is_compound = bool(_COMPOUND_CMD.search(user_input)) or _is_multi_app_command(user_input)
        if is_compound:
            print(f"[CommandCache] 복합 명령 감지 → 캐시 바이패스: {user_input!r}")
            _skip_cache = True

        # 커맨드 캐시 확인 (API 없이 직접 실행)
        if not _skip_cache:
            try:
                from core.command_cache import get_cache
                cache = get_cache()
                hit = cache.find(user_input)
                if hit:
                    entry, score = hit
                    print(f"[CommandCache] 히트 (유사도 {score:.2f}): {entry.pattern!r}")
                    result_text = await cache.execute(entry)
                    cache.increment_hit(entry.pattern)
                    self.session_memory.save(user_input, result_text)
                    # 맥락 통합: 캐시로 처리한 명령도 LangGraph 기억에 남긴다
                    self._record_fast_path(thread_id, user_input, result_text)
                    return result_text
            except Exception as cache_err:
                print(f"[CommandCache] 캐시 확인 오류 (무시): {cache_err}")

        # 결정론적 라우터 (youtube_search, map_search, create_folder 등 파라미터 패턴)
        try:
            route_result = await self._route_deterministic(user_input)
            if route_result is not None:
                self.session_memory.save(user_input, route_result)
                # 맥락 통합: 라우터로 처리한 명령도 LangGraph 기억에 남긴다
                self._record_fast_path(thread_id, user_input, route_result)
                return route_result
        except Exception as route_err:
            print(f"[Router] 라우팅 오류 (무시): {route_err}")

        # LLM 실행
        # 단일 thread: 정보 조회·제어 명령 모두 같은 맥락 공유
        # trim (_build_prompt_modifier)이 최근 20개 메시지만 LLM에 전달해 컨텍스트 범람 방지
        is_ctrl = self._is_control_command(user_input)
        effective_thread = thread_id

        config = {
            "configurable": {"thread_id": effective_thread},
            "recursion_limit": 10,
        }
        messages = [HumanMessage(content=user_input)]

        retry_thread: str | None = None
        try:
            result = await self._ainvoke_with_timeout({"messages": messages}, config)
        except (asyncio.TimeoutError, TimeoutError):
            # BL-01: 처리 시간 초과 → 무한 대기 대신 친절 메시지
            print(f"[PluizAgent] 처리 시간 초과({getattr(self.settings, 'agent_timeout', 30)}초) → thread '{effective_thread}' 초기화")
            self._clear_thread(effective_thread)
            return "처리가 너무 오래 걸려서 중단했어요. 조금 더 간단하게 말씀해 주시겠어요?"
        except Exception as e:
            err_msg = str(e)
            if "tool_calls that do not have a corresponding ToolMessage" in err_msg:
                print(f"[PluizAgent] 히스토리 오염 → thread '{effective_thread}' 초기화 후 재시도")
                self._clear_thread(effective_thread)
                # BUG-03: 재시도 ainvoke도 try/except로 보호
                try:
                    result = await self._ainvoke_with_timeout({"messages": messages}, config)
                except (asyncio.TimeoutError, TimeoutError):
                    print(f"[PluizAgent] 재시도 처리 시간 초과 → thread '{effective_thread}' 초기화")
                    self._clear_thread(effective_thread)
                    return "처리가 너무 오래 걸려서 중단했어요. 조금 더 간단하게 말씀해 주시겠어요?"
                except Exception as retry_err:
                    print(f"[PluizAgent] 히스토리 오염 재시도도 실패: {type(retry_err).__name__}: {retry_err}")
                    self._clear_thread(effective_thread)
                    if _is_network_error(retry_err):
                        return "인터넷 연결이 없어서 이 명령은 처리하기 어려워요. 앱 실행, 볼륨 조절 같은 기본 명령은 오프라인에서도 쓸 수 있어요!"
                    return f"명령 처리 중 오류가 발생했어요: {retry_err}"
            else:
                print(f"[PluizAgent] 예외 발생 → thread '{effective_thread}' 초기화: {type(e).__name__}: {e}")
                self._clear_thread(effective_thread)
                if _is_network_error(e):
                    return "인터넷 연결이 없어서 이 명령은 처리하기 어려워요. 앱 실행, 볼륨 조절 같은 기본 명령은 오프라인에서도 쓸 수 있어요!"
                return f"명령 처리 중 오류가 발생했어요: {e}"

        response = self._extract_response(result)

        # 도구 미호출 + 제어 명령 = 재시도 (새 thread, clearing 불필요)
        if not self._has_tool_message(result) and is_ctrl:
            retry_thread = f"{effective_thread}_retry"
            print(f"[PluizAgent] 도구 미호출 감지 (제어 명령) → 재시도 (thread: {retry_thread})")
            retry_messages = [
                HumanMessage(content=user_input),
                HumanMessage(content=RETRY_PROMPT),
            ]
            retry_config = {
                "configurable": {"thread_id": retry_thread},
                "recursion_limit": 10,
            }
            # BUG-03: 재시도 ainvoke도 try/except로 보호
            try:
                result = await self._ainvoke_with_timeout({"messages": retry_messages}, retry_config)
                response = self._extract_response(result)
            except (asyncio.TimeoutError, TimeoutError):
                print(f"[PluizAgent] 도구 미호출 재시도 시간 초과 (무시, 기존 응답 유지)")
            except Exception as e:
                print(f"[PluizAgent] 재시도 실패: {type(e).__name__}: {e}")

        # 여전히 빈 응답이면 ToolMessage에서 복원
        if not response.strip():
            print("[PluizAgent] ToolMessage에서 복원 시도")
            for msg in reversed(result["messages"]):
                if isinstance(msg, ToolMessage) and msg.content:
                    tool_content = msg.content
                    if isinstance(tool_content, list):
                        tool_content = " ".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in tool_content
                        ).strip()
                    if tool_content.strip():
                        response = tool_content
                        break
            if not response.strip():
                response = "명령을 실행했습니다."

        # ── T04: 도구 실행 결과 검증 ─────────────────────────────────
        # ToolMessage에 오류가 있는데 LLM이 성공처럼 응답했으면 보정
        tool_errors = self._extract_tool_errors(result)
        if tool_errors:
            response = self._patch_response_on_error(response, tool_errors)

        # ctrl thread는 맥락 유지를 위해 보존 (오염 오류 시에만 위 except에서 초기화)
        # 재시도용 임시 thread만 정리
        if retry_thread:
            self._clear_thread(retry_thread)

        self.session_memory.save(user_input, response)
        return response

    def _extract_response(self, result: dict) -> str:
        """마지막 AIMessage content 추출 + list 형태 처리."""
        response = result["messages"][-1].content
        if isinstance(response, list):
            response = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in response
            ).strip()
        return response

    def _has_tool_message(self, result: dict) -> bool:
        """ToolMessage가 하나라도 있는지 확인."""
        return any(isinstance(msg, ToolMessage) for msg in result["messages"])

    def _extract_tool_errors(self, result: dict) -> list[str]:
        """
        result의 ToolMessage에서 오류 메시지 목록을 추출한다.
        _TOOL_ERROR_RE 패턴으로 시작하는 content만 오류로 분류.
        """
        errors: list[str] = []
        for msg in result.get("messages", []):
            if not isinstance(msg, ToolMessage):
                continue
            content = msg.content
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                ).strip()
            content = str(content).strip()
            if _TOOL_ERROR_RE.match(content):
                errors.append(content)
        return errors

    def _patch_response_on_error(self, response: str, errors: list[str]) -> str:
        """
        도구 오류가 있는데 LLM이 성공처럼 응답했으면 오류 내용으로 교체.
        LLM이 이미 실패를 인지한 응답이면 그대로 반환.
        """
        first_error = errors[0]
        if _SUCCESS_LIKE_RE.search(response):
            # 오류 메시지에서 접두 태그([...]) 제거하고 핵심만 추출
            clean = re.sub(r'^\[[^\]]+\]\s*', '', first_error).strip() or first_error
            print(f"[T04] 도구 오류 감지, LLM 응답 보정 → {clean!r}")
            return f"실행 중 문제가 생겼어요: {clean}"
        else:
            # LLM이 이미 오류를 인지해 응답함 — 유지
            print(f"[T04] 도구 오류 감지, LLM이 이미 처리 완료: {first_error!r}")
            return response

    async def _route_deterministic(self, user_input: str) -> str | None:
        """
        LLM 없이 처리 가능한 파라미터형 명령 직접 라우팅.
        youtube_search / map_search / create_folder 패턴을 정규식으로 감지하고
        파라미터를 추출해 도구를 직접 호출합니다.

        Returns: 결과 문자열 (히트 시) 또는 None (미히트 시)
        """
        text = user_input.strip()

        # 1. youtube_search: "유튜브에서 아이유 검색해줘", "유튜브 BTS 틀어줘"
        m = _ROUTER_YT.search(text)
        if m:
            query = m.group(1).strip()
            if query:
                try:
                    from tools.web import youtube_search
                    result = await youtube_search.ainvoke({"query": query})
                    print(f"[Router] youtube_search({query!r})")
                    return str(result)
                except Exception as e:
                    print(f"[Router] youtube_search 오류: {e}")

        # 2. map_search 경로: "서울시청에서 강남역 가는 길 알려줘"
        m = _ROUTER_MAP_ROUTE.search(text)
        if m:
            origin = m.group(1).strip()
            dest   = m.group(2).strip()
            if origin and dest:
                try:
                    from tools.web import map_search
                    result = await map_search.ainvoke({"destination": dest, "origin": origin})
                    print(f"[Router] map_search({dest!r}, origin={origin!r})")
                    return str(result)
                except Exception as e:
                    print(f"[Router] map_search(route) 오류: {e}")

        # 3. map_search 장소: "강남역 지도 찾아줘", "강남역 어디야"
        m = _ROUTER_MAP_SIMPLE.search(text)
        if m:
            dest = m.group(1).strip()
            if len(dest) > 1:
                try:
                    from tools.web import map_search
                    result = await map_search.ainvoke({"destination": dest})
                    print(f"[Router] map_search({dest!r})")
                    return str(result)
                except Exception as e:
                    print(f"[Router] map_search(simple) 오류: {e}")

        # 4. create_folder: "바탕화면에 pluiz_test_folder 폴더 만들어줘"
        m = _ROUTER_FOLDER.search(text)
        if m:
            location = (m.group(1) or "바탕화면").strip()
            name     = m.group(2).strip()
            if name:
                try:
                    from tools.filesystem import create_folder
                    result = await create_folder.ainvoke({"name": name, "location": location})
                    print(f"[Router] create_folder({name!r}, {location!r})")
                    return str(result)
                except Exception as e:
                    print(f"[Router] create_folder 오류: {e}")

        # 5. set_volume: "볼륨 50으로 설정해줘", "볼륨 30%"
        m = _ROUTER_VOLUME.search(text)
        if m:
            level = int(m.group(1))
            if 0 <= level <= 100:
                try:
                    from tools.system import set_volume
                    result = await set_volume.ainvoke({"level": level})
                    print(f"[Router] set_volume({level})")
                    return str(result)
                except Exception as e:
                    print(f"[Router] set_volume 오류: {e}")

        # 6. volume_up with amount: "볼륨 10 올려줘", "볼륨 20정도 올려줘"
        m = _ROUTER_VOL_UP.search(text)
        if m:
            amount = int(m.group(1)) if m.group(1) else 10
            try:
                from tools.system import volume_up
                result = await volume_up.ainvoke({"amount": amount})
                print(f"[Router] volume_up({amount})")
                return str(result)
            except Exception as e:
                print(f"[Router] volume_up 오류: {e}")

        # 7. volume_down with amount: "볼륨 10 내려줘", "볼륨 20정도 줄여줘"
        m = _ROUTER_VOL_DOWN.search(text)
        if m:
            amount = int(m.group(1)) if m.group(1) else 10
            try:
                from tools.system import volume_down
                result = await volume_down.ainvoke({"amount": amount})
                print(f"[Router] volume_down({amount})")
                return str(result)
            except Exception as e:
                print(f"[Router] volume_down 오류: {e}")

        # 8. maximize_window: "계산기 최대화", "메모장 최대화 해줘"
        # 앱 이름에 복합 연결어 포함 시 → 복합 명령으로 판단해 스킵 (LLM이 처리)
        m = _ROUTER_MAXIMIZE.search(text)
        if m:
            app = m.group(1).strip()
            if app and not _COMPOUND_CMD.search(app):
                try:
                    from tools.app_control import maximize_window
                    result = await maximize_window.ainvoke({"app": app})
                    print(f"[Router] maximize_window({app!r})")
                    return str(result)
                except Exception as e:
                    print(f"[Router] maximize_window 오류: {e}")

        # 9. minimize_window: "계산기 최소화", "메모장 최소화 해줘"
        m = _ROUTER_MINIMIZE.search(text)
        if m:
            app = m.group(1).strip()
            if app and not _COMPOUND_CMD.search(app):
                try:
                    from tools.app_control import minimize_window
                    result = await minimize_window.ainvoke({"app": app})
                    print(f"[Router] minimize_window({app!r})")
                    return str(result)
                except Exception as e:
                    print(f"[Router] minimize_window 오류: {e}")

        return None

    def _is_control_command(self, text: str) -> bool:
        """입력이 PC 제어 명령인지 판단.

        _CONTROL_KEYWORDS 중 하나라도 포함되면 True.
        대화형 입력(인사, 질문 등)은 False → 재시도 불필요.
        """
        lower = text.lower()
        return any(kw in lower for kw in _CONTROL_KEYWORDS)

    def _clear_thread(self, thread_id: str):
        """MemorySaver에서 특정 thread 히스토리 전체 삭제.

        MemorySaver는 공식 삭제 API가 없어 내부 storage dict에 직접 접근함.
        storage 속성이 없을 경우(LangGraph 버전 변경) checkpointer 전체 재생성으로 fallback.
        """
        storage = getattr(self.checkpointer, "storage", None)
        if storage is None:
            print(f"[PluizAgent] storage 속성 없음 → checkpointer 재생성")
            self.checkpointer = MemorySaver()
            self.graph = create_react_agent(
                model=self.llm,
                tools=self.tools,
                checkpointer=self.checkpointer,
                prompt=_build_prompt_modifier,
            )
            return

        keys_to_delete = [k for k in list(storage.keys()) if k[0] == thread_id]
        for k in keys_to_delete:
            del storage[k]
        print(f"[PluizAgent] thread '{thread_id}' 초기화 완료 ({len(keys_to_delete)}개 항목)")

    async def _ainvoke_with_timeout(self, payload: dict, config: dict):
        """graph.ainvoke를 agent_timeout(초)으로 감싼다.

        BL-01: 복잡한 명령에서 LLM 호출이 지연/정지 시 UI가 무한 "처리중"이 되는 문제 방지.
        초과 시 asyncio.TimeoutError를 발생시켜 호출부에서 친절 메시지로 처리한다.
        """
        timeout = getattr(self.settings, "agent_timeout", 30) or 30
        return await asyncio.wait_for(
            self.graph.ainvoke(payload, config=config), timeout=timeout
        )

    def _record_fast_path(self, thread_id: str, user_input: str, result_text: str) -> None:
        """빠른 경로(캐시/라우터)로 처리한 명령을 LangGraph 대화 기억에 남긴다.

        캐시/라우터는 LLM(graph)을 거치지 않고 즉시 실행하므로, 그대로 두면 해당 명령이
        MemorySaver 히스토리에 누락된다. 그 결과 다음 턴의 맥락 참조("그거 닫아줘")가
        기억할 대상이 없어 실패한다. update_state로 (사용자 발화, 실행 결과)를 같은
        thread_id 히스토리에 append 하여 후속 LLM 턴이 맥락을 참조할 수 있게 한다.
        """
        try:
            config = {"configurable": {"thread_id": thread_id}}
            self.graph.update_state(
                config,
                {"messages": [
                    HumanMessage(content=user_input),
                    AIMessage(content=result_text),
                ]},
            )
        except Exception as e:
            print(f"[PluizAgent] 맥락 기억 저장 실패(무시): {type(e).__name__}: {e}")

    async def stream(self, user_input: str, thread_id: str = "default") -> AsyncGenerator[str, None]:
        """
        스트리밍 실행. 토큰 단위로 응답을 yield.
        캐시 히트 시 단일 청크로 즉시 반환 (API 미호출).
        PC 제어 명령은 run_async() 경유 (도구 미호출 감지·재시도·fallback 포함).
        대화형 입력만 실시간 스트리밍.

        session_memory 저장 책임:
          - 캐시 히트 경로:  이 메서드 내에서 저장
          - 제어 명령 경로:  run_async() 내부에서 저장 (_skip_cache=True로 이중 캐시 방지)
          - 대화형 경로:     astream 완료 후 이 메서드 내에서 저장
          ws 핸들러에서는 저장하지 않음 (BUG-01 수정).
        """
        # 복합 명령 감지 → 캐시 바이패스
        is_compound = bool(_COMPOUND_CMD.search(user_input)) or _is_multi_app_command(user_input)
        cache_miss = False
        if is_compound:
            print(f"[CommandCache/ws] 복합 명령 감지 → 캐시 바이패스: {user_input!r}")
            cache_miss = True
        else:
            try:
                from core.command_cache import get_cache
                cache = get_cache()
                hit = cache.find(user_input)
                if hit:
                    entry, score = hit
                    print(f"[CommandCache/ws] 히트 (유사도 {score:.2f}): {entry.pattern!r}")
                    result_text = await cache.execute(entry)
                    cache.increment_hit(entry.pattern)
                    self.session_memory.save(user_input, result_text)
                    # 맥락 통합: 캐시로 처리한 명령도 LangGraph 기억에 남긴다
                    self._record_fast_path(thread_id, user_input, result_text)
                    yield result_text
                    return
                cache_miss = True
            except Exception as cache_err:
                print(f"[CommandCache/ws] 캐시 확인 오류 (무시): {cache_err}")
                cache_miss = True

        # PC 제어 명령: run_async() 경유 (retry + ToolMessage fallback 포함)
        # BUG-06: 이미 캐시 미스 확인 완료 → _skip_cache=True로 이중 캐시 조회 방지
        if self._is_control_command(user_input):
            print(f"[PluizAgent/ws] 제어 명령 감지 → run_async() 경유")
            result_text = await self.run_async(user_input, thread_id, _skip_cache=cache_miss)
            yield result_text
            return

        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 10,
        }
        messages = [HumanMessage(content=user_input)]

        # BUG-01: 대화형 astream 경로에서 session_memory 저장을 위해 응답을 누적
        collected: list[str] = []
        try:
            async for chunk in self.graph.astream(
                {"messages": messages},
                config=config,
                stream_mode="messages",
            ):
                msg, meta = chunk
                # AIMessageChunk만 처리 — AIMessage는 청크 조합본이라 중복 출력됨
                # 청크가 하나도 없으면(비스트리밍 응답) AIMessage도 허용
                if isinstance(msg, AIMessageChunk):
                    pass  # 스트리밍 청크: 항상 처리
                elif isinstance(msg, AIMessage) and not collected:
                    pass  # 비스트리밍 폴백: 청크가 없을 때만 처리
                else:
                    continue
                content = msg.content
                if isinstance(content, list):
                    content = " ".join(
                        b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                    ).strip()
                if content:
                    collected.append(content)
                    yield content
        except Exception as stream_err:
            if _is_network_error(stream_err):
                msg = "인터넷 연결이 없어서 이 명령은 처리하기 어려워요. 앱 실행, 볼륨 조절 같은 기본 명령은 오프라인에서도 쓸 수 있어요!"
                print(f"[PluizAgent/ws] 네트워크 오류 → 친절 메시지 반환: {stream_err}")
            else:
                msg = f"명령 처리 중 오류가 발생했어요: {stream_err}"
                print(f"[PluizAgent/ws] astream 오류: {type(stream_err).__name__}: {stream_err}")
            collected.append(msg)
            yield msg

        # BUG-01: 대화형 경로 — astream 완료 후 session_memory 저장
        full = "".join(collected)
        if full.strip():
            self.session_memory.save(user_input, full)


# ── 싱글톤 ────────────────────────────────────────────────────────
_agent_instance: PluizAgent | None = None


def get_agent() -> PluizAgent:
    """싱글톤 에이전트 인스턴스 반환. 없으면 생성."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = PluizAgent()
    return _agent_instance


def reset_agent():
    """에이전트 인스턴스 초기화 (API 키 변경 후 호출)."""
    global _agent_instance
    _agent_instance = None
    print("[PluizAgent] 에이전트 인스턴스 초기화 완료")
