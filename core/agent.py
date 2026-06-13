"""
Pluiz Agent Core
----------------
LangGraph 기반 ReAct 에이전트.
사용자 입력 → LLM이 도구 선택 → 결정론적 실행 → 결과 관찰 → 반복
"""

import re
from typing import AsyncGenerator
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, AIMessageChunk, ToolMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from config.settings import get_settings
from core.tool_registry import get_all_tools
from memory.session import SessionMemory


SYSTEM_PROMPT = """당신은 Pluiz입니다. 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트입니다.

핵심 규칙 (반드시 준수):
- PC 제어 명령(앱 실행/종료, 볼륨, 닫기, 파일 생성, 웹 검색 등)은 반드시 해당 도구를 호출하여 실행합니다.
- 도구 호출 없이 "실행했습니다"라고만 응답하는 것은 절대 금지입니다.
- 앱 실행, 볼륨 조절, 파일 생성, 웹 열기 등 모든 PC 조작은 도구를 통해서만 수행합니다.
- 명령이 점진적으로 명확하다면 확인 없이 바로 도구를 호출합니다.
- "유튜브에서/유튜브에/유튜브로 X 검색해줘", "유튜브 X 틀어줘" 명령은 반드시 youtube_search 도구를 호출합니다. (web_search 사용 금지)
- "지도에서 X 찾아줘" / "X 가는 길 알려줘" / "X 어디야" 명령은 반드시 map_search 도구를 호출합니다.

역할:
- 사용자의 자연어 명령을 이해하고 적절한 도구를 호출하여 PC를 제어합니다.
- 한국어 구어체 및 줄임말을 자연스럽게 처리합니다.
- 명령이 모호하면 짧게 확인 후 실행합니다.
- 실행 결과를 간결하게 한국어로 보고합니다.

보안 지침 (반드시 준수):
- 파일/폴더 삭제 명령은 반드시 "정말 삭제하시겠습니까?" 확인 후 실행합니다.
- 휴지통 비우기, 영구 삭제(shift+delete 등) 요청은 구체적으로 재확인합니다.
- 시스템 설정 변경(레지스트리, 방화벽, 계정 등)은 신중하게 재확인합니다.
- 여러 파일을 한꺼번에 삭제하는 경우 대상 목록을 사용자에게 먼저 보여줍니다.
- C:\\Windows, System32 등 시스템 경로 접근은 거부합니다.
- 절대 실행하지 말 것: rm -rf, del /f /s, format, reg delete, shutdown /f 등 불가역적 명령.

일반 주의:
- 날씨, 뉴스, 검색 결과 등 실시간 정보 요청은 fetch_web_info 도구로 가져와 파일 저장 또는 답변합니다.
- 불가능한 요청은 이유를 간결하게 설명합니다.
- 응답은 항상 한국어로 합니다.
- 도구 실행 결과를 그대로 전달하되, 사용자가 이해하기 쉽게 요약합니다.
"""

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


# ── 결정론적 라우터 패턴 ────────────────────────────────────────────
# LLM 없이 처리 가능한 파라미터형 명령 패턴 (youtube_search, map_search, create_folder)
# 캐시 시드는 고정 패턴만 커버하므로 동적 파라미터는 여기서 처리

_ROUTER_YT = re.compile(
    r'유튜브(?:에서|에|로)?\s+(.+?)\s*(?:검색해줘|검색해|틀어줘|틀어|찾아줘|찾아)\s*$'
)
_ROUTER_MAP_ROUTE = re.compile(
    r'^(.+?)에서\s+(.+?)\s+(?:가는\s*길|경로)\s*(?:알려줘|찾아줘)?\s*$'
)
_ROUTER_MAP_SIMPLE = re.compile(
    r'^(.+?)\s+(?:지도\s*(?:찾아줘|보여줘|열어줘|검색해줘|알려줘)?|어디야|어디에\s*있어|어디에요)\s*$'
)
_ROUTER_FOLDER = re.compile(
    r'^(?:(바탕화면|데스크탑|다운로드|문서|사진)에\s+)?(.+?)\s+(?:폴더|디렉토리)\s+(?:만들어줘|만들어|생성해줘|생성해)\s*$'
)
_ROUTER_VOLUME = re.compile(
    r'볼륨\s*(\d+)\s*(?:%로|%|퍼센트|으로|로)?\s*(?:설정해줘|설정해|맞춰줘|맞춰|해줘)?\s*$'
)

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

        # LangGraph ReAct 에이전트 생성
        self.graph = create_react_agent(
            model=self.llm,
            tools=self.tools,
            checkpointer=self.checkpointer,
            prompt=SYSTEM_PROMPT,
        )

        print(f"[PluizAgent] 초기화 완료 | provider={settings.llm_provider} | tools={len(self.tools)}개")

    async def run_async(self, user_input: str, thread_id: str = "default",
                        _skip_cache: bool = False) -> str:
        """비동기 실행. FastAPI 엔드포인트에서 사용.

        _skip_cache: True면 캐시 조회를 건너뜀.
                     stream()에서 이미 캐시 미스 확인 후 이 메서드를 호출할 때 사용
                     (BUG-06: 이중 캐시 조회 방지).
        """
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
                    return result_text
            except Exception as cache_err:
                print(f"[CommandCache] 캐시 확인 오류 (무시): {cache_err}")

        # 결정론적 라우터 (youtube_search, map_search, create_folder 등 파라미터 패턴)
        try:
            route_result = await self._route_deterministic(user_input)
            if route_result is not None:
                self.session_memory.save(user_input, route_result)
                return route_result
        except Exception as route_err:
            print(f"[Router] 라우팅 오류 (무시): {route_err}")

        # LLM 실행
        # 제어 명령: 매 호출마다 고유 스레드 사용 → 이전 실패 attempt가 다음 명령 컨텍스트 오염 방지
        import time as _time
        is_ctrl = self._is_control_command(user_input)
        if is_ctrl:
            effective_thread = f"{thread_id}_cmd_{int(_time.time()*1000)}"
        else:
            effective_thread = thread_id

        config = {
            "configurable": {"thread_id": effective_thread},
            "recursion_limit": 10,
        }
        messages = [HumanMessage(content=user_input)]

        retry_thread: str | None = None
        try:
            result = await self.graph.ainvoke({"messages": messages}, config=config)
        except Exception as e:
            err_msg = str(e)
            if "tool_calls that do not have a corresponding ToolMessage" in err_msg:
                print(f"[PluizAgent] 히스토리 오염 → thread '{effective_thread}' 초기화 후 재시도")
                self._clear_thread(effective_thread)
                # BUG-03: 재시도 ainvoke도 try/except로 보호
                try:
                    result = await self.graph.ainvoke({"messages": messages}, config=config)
                except Exception as retry_err:
                    print(f"[PluizAgent] 히스토리 오염 재시도도 실패: {type(retry_err).__name__}: {retry_err}")
                    self._clear_thread(effective_thread)
                    return f"명령 처리 중 오류가 발생했습니다: {retry_err}"
            else:
                print(f"[PluizAgent] 예외 발생 → thread '{effective_thread}' 초기화: {type(e).__name__}: {e}")
                self._clear_thread(effective_thread)
                return f"명령 처리 중 오류가 발생했습니다: {e}"

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
                result = await self.graph.ainvoke({"messages": retry_messages}, config=retry_config)
                response = self._extract_response(result)
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

        # BUG-05: 제어 명령용 임시 thread는 결과 확보 후 즉시 MemorySaver에서 정리
        if is_ctrl:
            self._clear_thread(effective_thread)
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
                prompt=SYSTEM_PROMPT,
            )
            return

        keys_to_delete = [k for k in list(storage.keys()) if k[0] == thread_id]
        for k in keys_to_delete:
            del storage[k]
        print(f"[PluizAgent] thread '{thread_id}' 초기화 완료 ({len(keys_to_delete)}개 항목)")

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
        cache_miss = False
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
        async for chunk in self.graph.astream(
            {"messages": messages},
            config=config,
            stream_mode="messages",
        ):
            msg, meta = chunk
            if not isinstance(msg, (AIMessage, AIMessageChunk)):
                continue
            content = msg.content
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                ).strip()
            if content:
                collected.append(content)
                yield content

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
