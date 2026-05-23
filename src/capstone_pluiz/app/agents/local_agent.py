# app/agents/local_agent.py
import requests
from app.agents.base_agent import BaseAgent

SYSTEM_PROMPT = """
너는 사용자의 PC 제어 명령을 분석하는 AI야.
사용자의 명령을 분석해서 반드시 아래 JSON 형식으로만 답해.
절대 다른 말 하지 마. JSON만 출력해.

명령 유형 3가지:
1. local: 앱 실행/종료 (메모장, 계산기, 크롬 등)
2. web: 웹 브라우저 제어 (지도 검색, 유튜브, 네이버 검색 등)
3. interpreter: 파일/시스템 작업 (파일 생성, 폴더 만들기, 파일 찾기 등)

응답 형식:
{"type": "local/web/interpreter", "action": "구체적동작", "params": {파라미터}}

예시:
입력: "메모장 열어줘" → {"type": "local", "action": "open_app", "params": {"app": "notepad"}}
입력: "크롬 닫아줘" → {"type": "local", "action": "close_app", "params": {"app": "chrome"}}
입력: "강남역에서 홍대 경로 찾아줘" → {"type": "web", "action": "map_search", "params": {"from": "강남역", "to": "홍대입구역"}}
입력: "유튜브에서 아이유 검색해줘" → {"type": "web", "action": "youtube_search", "params": {"query": "아이유"}}
입력: "바탕화면에 test.txt 만들어줘" → {"type": "interpreter", "action": "create_file", "params": {"name": "test.txt", "location": "desktop"}}
입력: "다운로드 폴더에서 pdf 파일 찾아줘" → {"type": "interpreter", "action": "find_file", "params": {"extension": "pdf", "location": "downloads"}}
"""

class LocalAgent(BaseAgent):
    def __init__(self, model: str = "llama3", ollama_url: str = "http://localhost:11434"):
        self.model = model
        self.ollama_url = ollama_url
    
    def analyze_command(self, user_input: str) -> dict:
        try:
            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_input}
                    ],
                    "stream": False
                },
                timeout=30
            )
            
            result = response.json()
            text = result["message"]["content"]
            return self._parse_json(text)
            
        except Exception as e:
            print(f"[LocalAgent 오류] {e}")
            return {"type": "unknown", "action": "unknown", "params": {}}