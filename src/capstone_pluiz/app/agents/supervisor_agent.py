# app/agents/supervisor_agent.py
from google import genai
import sys
import os
import re
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.settings import GEMINI_API_KEY

BRAIN_PROMPT = """
너는 사용자의 PC를 제어하는 AI 비서야.
사용자 명령을 받아서 실행할 파이썬 코드를 생성해줘.

반드시 지켜야 할 규칙:
1. 파일 삭제, 시스템 파일 수정 절대 금지
2. 웹 작업은 반드시 selenium 사용
3. 새로운 라이브러리 설치 시도 금지
4. 앱 실행은 subprocess.Popen으로 직접 경로 실행
5. 코드만 출력, 설명 없이
6. 웹 브라우저 작업 후 driver.quit() 절대 호출 금지 (브라우저 열린 상태 유지)
7. webdriver_manager 사용 금지, 반드시 Options()만 사용

Windows 환경 정보:
- 크롬: C:/Program Files/Google/Chrome/Application/chrome.exe
- 메모장: C:/Windows/System32/notepad.exe
- 계산기: C:/Windows/System32/calc.exe
- 바탕화면: os.path.join(os.environ['USERPROFILE'], 'Desktop')
- 다운로드: os.path.join(os.environ['USERPROFILE'], 'Downloads')

selenium 사용 예시 (반드시 이 방식으로):
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time

options = Options()
driver = webdriver.Chrome(options=options)
"""

class SupervisorAgent:
    def __init__(self):
        if GEMINI_API_KEY:
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            self.model_id = "gemini-2.5-flash-lite"
            self.available = True
            print("[Supervisor] Gemini 두뇌 초기화 완료")
        else:
            self.available = False
            print("[Supervisor] API 없음, 로컬 모드로 동작")

    def is_complex(self, command: dict) -> bool:
        # TODO: 추후 캐싱 시스템 구현 시 단순/복잡 명령 분기에 사용 예정
        # 단순 명령 (앱 실행 등) → 캐시 히트 시 로컬 LLM (빠름, 무료)
        # 복잡 명령 (웹 제어, 파일 자동화 등) → Gemini API (정확함)
        # 현재는 모든 명령을 Gemini로 처리하므로 항상 True 반환
        return True

    def generate_code(self, command: dict, original_input: str) -> str:
        if not self.available:
            return None
        try:
            prompt = f"{BRAIN_PROMPT}\n\n사용자 명령: {original_input}\n\n실행할 파이썬 코드만 작성해줘:"
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            text = response.text
            code_match = re.search(r'```python\n(.*?)\n```', text, re.DOTALL)
            if code_match:
                return code_match.group(1)
            return text.strip()
        except Exception as e:
            print(f"[Supervisor 오류] {e}")
            return None

    def explain_result(self, original_input: str, success: bool) -> str:
        if not self.available:
            return "완료됐습니다." if success else "실행 중 오류가 발생했습니다."
        try:
            status = "성공" if success else "실패"
            prompt = f"사용자가 '{original_input}'을 요청했고 {status}했어. 한 문장으로 결과 설명해줘."
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            return response.text.strip()
        except:
            return "완료됐습니다." if success else "실행 중 오류가 발생했습니다."