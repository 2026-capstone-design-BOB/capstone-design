# app/agents/local_agent.py
# 사용자 입력 -> JSON 형식 명령으로 분류
import time
import re
from app.agents.base_agent import BaseAgent
from config.settings import ACTIVE_PROVIDER, ACTIVE_MODEL

# TODO: [메모리 시스템] 맥락 기반 명령 처리
# - 이전 명령 히스토리 참조 ("그거 열어줘" → 직전 대상 추론)
# - 사용자 패턴 학습 (자주 쓰는 앱, 검색어 등)
# - 구현 위치: app/memory/context_memory.py 예정
# - 연관 기능: 멀티스텝 명령, 개인화 추천

SYSTEM_PROMPT = """
너는 사용자의 PC 제어 명령을 분석하는 AI야.
사용자의 명령을 분석해서 반드시 아래 JSON 형식으로만 답해.
절대 다른 말 하지 마. JSON만 출력해.

명령 유형 5가지:
1. local: 앱 실행/종료, 창 제어 (메모장, 크롬, 계산기 등)
2. web: 웹 브라우저 제어 (검색, 유튜브, 지도 등)
3. interpreter: 파일/시스템 작업 (파일 생성, 폴더 만들기, 파일 찾기 등)
4. system: 시스템 제어/조회 (볼륨, 밝기, 배터리, 캡처 등)
5. unknown: 위 4가지로 분류 불가한 경우

응답 형식:
{"type": "유형", "action": "구체적동작", "params": {파라미터}}

구어체/모호한 표현 처리 규칙:
- "좀", "봐봐", "ㅋㅋ", "야" 같은 불필요한 표현 무시하고 핵심만 추출
- "인터넷" → 기본 브라우저 실행으로 해석
- "조용히 해줘" → 음소거로 해석
- "켜줘/열어줘/실행해줘/띄워줘" → open_app
- "꺼줘/닫아줘/종료해줘" → close_app

예시:
입력: "메모장 열어줘" → {"type": "local", "action": "open_app", "params": {"app": "notepad"}}
입력: "야 크롬 좀 켜봐 ㅋㅋ" → {"type": "local", "action": "open_app", "params": {"app": "chrome"}}
입력: "크롬 닫아줘" → {"type": "local", "action": "close_app", "params": {"app": "chrome"}}
입력: "계산기 띄워줘" → {"type": "local", "action": "open_app", "params": {"app": "calculator"}}
입력: "탐색기 열어" → {"type": "local", "action": "open_app", "params": {"app": "explorer"}}
입력: "창 최소화해줘" → {"type": "local", "action": "minimize_window", "params": {}}
입력: "바탕화면 보여줘" → {"type": "local", "action": "show_desktop", "params": {}}
입력: "강남역에서 홍대 경로 찾아줘" → {"type": "web", "action": "map_search", "params": {"from": "강남역", "to": "홍대입구역"}}
입력: "유튜브에서 아이유 검색해줘" → {"type": "web", "action": "youtube_search", "params": {"query": "아이유"}}
입력: "네이버에서 날씨 검색해줘" → {"type": "web", "action": "web_search", "params": {"site": "naver", "query": "날씨"}}
입력: "구글에서 파이썬 찾아봐" → {"type": "web", "action": "web_search", "params": {"site": "google", "query": "파이썬"}}
입력: "인터넷 켜줘" → {"type": "web", "action": "open_browser", "params": {}}
입력: "바탕화면에 test.txt 만들어줘" → {"type": "interpreter", "action": "create_file", "params": {"name": "test.txt", "location": "desktop"}}
입력: "다운로드 폴더에서 pdf 파일 찾아줘" → {"type": "interpreter", "action": "find_file", "params": {"extension": "pdf", "location": "downloads"}}
입력: "바탕화면에 프로젝트 폴더 만들어줘" → {"type": "interpreter", "action": "create_folder", "params": {"name": "프로젝트", "location": "desktop"}}
입력: "최근에 만든 파일 열어줘" → {"type": "interpreter", "action": "open_recent_file", "params": {}}
입력: "볼륨 올려줘" → {"type": "system", "action": "volume_up", "params": {}}
입력: "소리 줄여줘" → {"type": "system", "action": "volume_down", "params": {}}
입력: "음소거 해줘" → {"type": "system", "action": "mute", "params": {}}
입력: "조용히 해줘" → {"type": "system", "action": "mute", "params": {}}
입력: "화면 밝기 올려줘" → {"type": "system", "action": "brightness_up", "params": {}}
입력: "배터리 얼마나 남았어" → {"type": "system", "action": "battery_status", "params": {}}
입력: "지금 몇 시야" → {"type": "system", "action": "get_time", "params": {}}
입력: "화면 캡처해줘" → {"type": "system", "action": "screenshot", "params": {}}
입력: "넷플 틀어줘" → {"type": "web", "action": "open_url", "params": {"url": "https://www.netflix.com"}}
입력: "유튭에서 BTS 검색해" → {"type": "web", "action": "youtube_search", "params": {"query": "BTS"}}
입력: "메모장 크게 해줘" → {"type": "local", "action": "maximize_window", "params": {"app": "notepad"}}
입력: "크롬 최대화해줘" → {"type": "local", "action": "maximize_window", "params": {"app": "chrome"}}
입력: "파일탐색기 작게 해줘" → {"type": "local", "action": "minimize_window", "params": {"app": "explorer"}}
입력: "메모장 닫아줘" → {"type": "local", "action": "close_app", "params": {"app": "notepad"}}
입력: "크롬 닫아줘" → {"type": "local", "action": "close_app", "params": {"app": "chrome"}}
입력: "메모장 크게 해줘" → {"type": "local", "action": "maximize_window", "params": {"app": "notepad"}}
입력: "크롬 최대화해줘" → {"type": "local", "action": "maximize_window", "params": {"app": "chrome"}}
입력: "엣지 크게 해줘" → {"type": "local", "action": "maximize_window", "params": {"app": "edge"}}
입력: "파일탐색기 작게 해줘" → {"type": "local", "action": "minimize_window", "params": {"app": "explorer"}}
입력: "메모장 닫아줘" → {"type": "local", "action": "close_app", "params": {"app": "notepad"}}
입력: "볼륨 20 올려줘" → {"type": "system", "action": "volume_up", "params": {"level": 20}}
입력: "소리 30으로 해줘" → {"type": "system", "action": "set_volume", "params": {"level": 30}}
입력: "볼륨 10배 키워줘" → {"type": "system", "action": "volume_up", "params": {"level": "invalid"}}
입력: "소리 0.5 줄여줘" → {"type": "system", "action": "volume_down", "params": {"level": "invalid"}}
입력: "바탕화면에 보고서.docx 만들어줘" → {"type": "interpreter", "action": "create_file", "params": {"name": "보고서.docx", "location": "desktop"}}
입력: "바탕화면에 메모.txt 만들어줘" → {"type": "interpreter", "action": "create_file", "params": {"name": "메모.txt", "location": "desktop"}}
"""

class LocalAgent(BaseAgent):
    def __init__(self):
        self._init_client(ACTIVE_PROVIDER, ACTIVE_MODEL)

    def analyze_command(self, user_input: str, max_retries: int = 3) -> dict:
        if not self.available:
            return {"type": "unknown", "action": "unknown", "params": {}}

        for attempt in range(max_retries):
            try:
                prompt = f"{SYSTEM_PROMPT}\n\n입력: {user_input}"
                return self._parse_json(self._call_llm(prompt))

            except Exception as e:
                error_str = str(e)
                wait_time = 5
                if "retryDelay" in error_str:
                    match = re.search(r'"seconds":\s*(\d+)', error_str)
                    if match:
                        wait_time = int(match.group(1)) + 1

                if attempt < max_retries - 1:
                    print(f"[LocalAgent] 오류 발생 (시도 {attempt+1}/{max_retries}), {wait_time}초 후 재시도...")
                    time.sleep(wait_time)
                else:
                    print(f"[LocalAgent] 최대 재시도 초과: {e}")

        return {"type": "unknown", "action": "unknown", "params": {}}