# app/agents/supervisor_agent.py
# JSON 명령 -> 실제 실행 코드 생성
import sys
import os
import re
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.agents.base_agent import BaseAgent
from config.settings import ACTIVE_PROVIDER, ACTIVE_MODEL

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
8. selenium 사용 시 반드시 아래 예시의 options 설정 그대로 사용할 것 (봇 감지 우회 + 기존 프로필)

Windows 환경 정보:
- 크롬: C:/Program Files/Google/Chrome/Application/chrome.exe
- 메모장: C:/Windows/System32/notepad.exe
- 계산기: C:/Windows/System32/calc.exe
- 바탕화면: os.path.join(os.environ['USERPROFILE'], 'Desktop')
- 다운로드: os.path.join(os.environ['USERPROFILE'], 'Downloads')

Windows 시스템 제어 방법:
- 볼륨 올리기: subprocess.run(["powershell", "-c", "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"])
- 볼륨 내리기: subprocess.run(["powershell", "-c", "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"])
- 음소거: subprocess.run(["powershell", "-c", "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"])
- 배터리 잔량:
    import subprocess
    result = subprocess.run(["powershell", "-c", "(Get-WmiObject Win32_Battery).EstimatedChargeRemaining"], capture_output=True, text=True)
    print(f"배터리 잔량: {result.stdout.strip()}%")
- 화면 캡처:
    import subprocess
    import os
    path = os.path.join(os.environ['USERPROFILE'], 'Desktop', 'screenshot.png')
    subprocess.run(["powershell", "-c", f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Screen]::PrimaryScreen | Out-Null; [System.Windows.Forms.SendKeys]::SendWait('%{{PRTSC}}')"])
- 현재 시간:
    from datetime import datetime
    print(datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분"))

selenium 사용 예시 (반드시 이 방식으로):
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time

# TODO: 사용자 기본 브라우저 감지 및 로그인 상태 유지 기능 개발 예정
# TODO: 봇 감지 우회 옵션 안정화 필요
# 현재는 기본 크롬으로 실행
options = Options()
driver = webdriver.Chrome(options=options)
"""

class SupervisorAgent(BaseAgent):
    def __init__(self):
        self._init_client(ACTIVE_PROVIDER, ACTIVE_MODEL)

    # BaseAgent 추상 메서드 구현 (SupervisorAgent는 analyze_command 안 씀)
    def analyze_command(self, user_input: str) -> dict:
        return {}

    def is_complex(self, command: dict) -> bool:
        # TODO: 추후 캐싱 시스템 구현 시 단순/복잡 명령 분기에 사용 예정
        return True

    def generate_code(self, command: dict, original_input: str) -> str:
        if not self.available:
            return None
        try:
            prompt = f"{BRAIN_PROMPT}\n\n사용자 명령: {original_input}\n\n실행할 파이썬 코드만 작성해줘:"
            text = self._call_llm(prompt)
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
            return self._call_llm(prompt)
        except:
            return "완료됐습니다." if success else "실행 중 오류가 발생했습니다."