# app/agents/supervisor_agent.py
# JSON 명령 -> 실제 실행 코드 생성
import sys
import os
import re
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.agents.base_agent import BaseAgent
from config.settings import ACTIVE_PROVIDER, ACTIVE_MODEL

# ──────────────────────────────────────────────────────────────────
# TODO: [창 제어 개선] 타겟 윈도우 자동 감지
# ──────────────────────────────────────────────────────────────────
# 현재 문제:
#   창 최대화/최소화/닫기 명령에서 타겟 미지정 시
#   GetForegroundWindow()를 사용하는데, 사용자가 채팅창(Electron UI)에서
#   명령을 입력하는 순간 포커스가 채팅창에 있어서
#   의도한 창이 아닌 채팅창 자체가 타겟이 되는 문제 발생.
#
# 해결 방향:
#   Pluiz 자신 + 시스템 프로세스를 제외하고,
#   Z-order 기준으로 직전에 사용자가 작업하던 창을 타겟으로 삼기.
#
# 구현 위치:
#   app/utils/window_utils.py (신규 파일) 에 get_target_window() 함수로 분리
#
# 무시할 프로세스 목록 (예시):
#   IGNORE_PROCESSES = {
#       "pluiz", "electron", "python", "cmd", "powershell",
#       "windowsterminal", "conhost", "explorer",
#       "searchhost", "textinputhost", "applicationframehost",
#       "shellexperiencehost", "startmenuexperiencehost",
#       "dwm", "csrss", "winlogon", "services", "svchost"
#   }
#
# 핵심 로직:
#   1. GetForegroundWindow()로 현재 포그라운드(채팅창) 핸들 획득
#   2. GetWindow(hwnd, 2) = GW_HWNDNEXT 로 Z-order 다음 창으로 이동
#   3. IsWindowVisible() + GetWindowTextLengthW() 로 유효한 창 필터
#   4. psutil로 프로세스명 확인 → IGNORE_PROCESSES 제외
#   5. 첫 번째 통과한 창 = 사용자가 직전에 작업하던 창 → 타겟으로 반환
#
# 완료 후:
#   BRAIN_PROMPT의 창 제어 섹션에서
#   GetForegroundWindow() 대신 get_target_window() 호출하도록 수정
#   from app.utils.window_utils import get_target_window
# ──────────────────────────────────────────────────────────────────


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
8. selenium 사용 시 반드시 아래 예시의 options 설정 그대로 사용할 것
9. 크롬/엣지/메모장/계산기 등 단순 앱 실행은 selenium 절대 금지
    반드시 subprocess.Popen(["경로/앱.exe"]) 방식만 사용
    selenium은 웹 검색/유튜브/지도 등 브라우저 조작 시에만 사용
10. taskkill 명령 사용 금지 (특히 explorer.exe 절대 금지)
11. wmic 명령 사용 금지 (Windows 11에서 deprecated)
12. 파일 생성 시 파일명은 사용자가 요청한 그대로 사용 (확장자 포함)
    내용은 빈 파일로 생성 (사용자가 내용을 별도로 요청한 경우에만 작성)
13. 경로 백슬래시 처리 시 반드시 아래 방식만 사용:
    path_fwd = '/'.join(path.split('\\'))
    절대 사용 금지: path.split('\') 또는 path.replace('\\', '/') 또는 path.replace('\', '/')

Windows 환경 정보:
- 크롬: C:/Program Files/Google/Chrome/Application/chrome.exe
- 메모장: C:/Windows/System32/notepad.exe
- 계산기: C:/Windows/System32/calc.exe
- 엣지: C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe
- 그림판: C:/Windows/System32/mspaint.exe
- 탐색기(파일탐색기 열기): C:/Windows/explorer.exe
- 카카오톡: os.path.join(os.environ['LOCALAPPDATA'], 'Kakao', 'KakaoTalk', 'KakaoTalk.exe')
- 바탕화면: os.path.join(os.environ['USERPROFILE'], 'Desktop')
- 다운로드: os.path.join(os.environ['USERPROFILE'], 'Downloads')
- 문서: os.path.join(os.environ['USERPROFILE'], 'Documents')
- Windows 설정: subprocess.Popen(["start", "ms-settings:"], shell=True)

Windows 창 제어 방법 (반드시 ctypes 사용):
- 창 제어 시 타겟 미지정이면 Z-order 두 번째 창을 타겟으로 사용
    (채팅 인터페이스가 포그라운드에 있을 수 있으므로)
- 창 최대화 (타겟 미지정):
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    next_hwnd = user32.GetWindow(hwnd, 2)
    while next_hwnd:
        if user32.IsWindowVisible(next_hwnd) and user32.GetWindowTextLengthW(next_hwnd) > 0:
            user32.ShowWindow(next_hwnd, 3)
            break
        next_hwnd = user32.GetWindow(next_hwnd, 2)
- 창 최소화 (타겟 미지정):
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    next_hwnd = user32.GetWindow(hwnd, 2)
    while next_hwnd:
        if user32.IsWindowVisible(next_hwnd) and user32.GetWindowTextLengthW(next_hwnd) > 0:
            user32.ShowWindow(next_hwnd, 6)
            break
        next_hwnd = user32.GetWindow(next_hwnd, 2)
- 창 닫기 (타겟 미지정):
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    next_hwnd = user32.GetWindow(hwnd, 2)
    while next_hwnd:
        if user32.IsWindowVisible(next_hwnd) and user32.GetWindowTextLengthW(next_hwnd) > 0:
            user32.PostMessageW(next_hwnd, 0x0010, 0, 0)
            break
        next_hwnd = user32.GetWindow(next_hwnd, 2)
- 앱 지정 창 최대화/최소화/닫기 (반드시 FindWindowW 방식 사용):
    앱별 클래스명:
        메모장 = "Notepad"
        파일탐색기 = "CabinetWClass"
        크롬 = "Chrome_WidgetWin_1"
        엣지 = "Chrome_WidgetWin_1"
    예시 (메모장 최대화):
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW("Notepad", None)
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 3)
    예시 (메모장 최소화):
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW("Notepad", None)
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 6)
    예시 (메모장 닫기):
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW("Notepad", None)
    if hwnd:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
    예시 (파일탐색기 닫기, explorer.exe 종료 금지):
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW("CabinetWClass", None)
    if hwnd:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
- 바탕화면 보이기 (모든 창 최소화):
    import subprocess
    subprocess.run(["powershell", "-c", "(New-Object -ComObject Shell.Application).MinimizeAll()"])

Windows 시스템 제어 방법:
- 볼륨 제어 규칙:
    keybd_event 1회 = 볼륨 2단위 변화
    기본값(지정 없음): 5회 반복 = 10단위
    "엄청/많이": 15회 반복 = 30단위
    "조금/살짝": 3회 반복 = 6단위
    숫자 + "올려줘/내려줘" = 상대값: round(숫자 / 2)회 반복
      예) "20 올려줘" → 10회 반복 (현재 볼륨 무관하게 +20)
    숫자 + "으로 해줘/설정해줘" = 절대값: 현재 볼륨 조회 후 차이만큼 반복
      예) "50으로 해줘" → 현재가 30이면 +20 → 10회 반복
    배수("10배"), 소수점("0.5") 입력 = 비정상 → 기본값 5회로 처리

- 볼륨 올리기 (기본, 10단위):
    import ctypes, time
    for _ in range(5):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
        time.sleep(0.05)
- 볼륨 내리기 (기본, 10단위):
    import ctypes, time
    for _ in range(5):
        ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
        time.sleep(0.05)
- 볼륨 상대값 올리기 예시 ("20 올려줘" → 10회):
    import ctypes, time
    steps = round(20 / 2)
    for _ in range(steps):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
        time.sleep(0.05)
- 볼륨 절대값 설정 예시 ("50으로 해줘"):
    import ctypes, time, subprocess
    result = subprocess.run(["powershell", "-c",
        "(Get-AudioDevice -Playback).Volume"],
        capture_output=True, text=True)
    current_vol = int(float(result.stdout.strip())) if result.stdout.strip() else 50
    target_vol = 50
    diff = target_vol - current_vol
    key = 0xAF if diff > 0 else 0xAE
    steps = abs(round(diff / 2))
    for _ in range(steps):
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(key, 0, 2, 0)
        time.sleep(0.05)
- 음소거 토글:
    import ctypes, time
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
- 현재 볼륨 조회 (절대값 설정 시 사용):
    import subprocess
    result = subprocess.run(["powershell", "-c",
        "(Get-AudioDevice -Playback).Volume"],
        capture_output=True, text=True)
    current_vol = int(float(result.stdout.strip())) if result.stdout.strip() else 50
- 배터리 잔량:
    import subprocess
    result = subprocess.run(["powershell", "-c",
        "(Get-WmiObject Win32_Battery).EstimatedChargeRemaining"],
        capture_output=True, text=True)
    print(f"배터리 잔량: {result.stdout.strip()}%")
- 화면 캡처 (전체 화면, DPI 대응, 반드시 이 방식 그대로 사용):
    import subprocess, os, base64
    _L = ["Add-Type -TypeDefinition @'",
          "using System;",
          "using System.Runtime.InteropServices;",
          "public class DPIHelper {",
          '    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();',
          '    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);',
          "}",
          "'@",
          "Add-Type -AssemblyName System.Drawing",
          "[DPIHelper]::SetProcessDPIAware()",
          "$w = [DPIHelper]::GetSystemMetrics(0)",
          "$h = [DPIHelper]::GetSystemMetrics(1)",
          "$path = [System.IO.Path]::Combine($env:USERPROFILE, 'Desktop', 'screenshot.png')",
          "$bmp = New-Object System.Drawing.Bitmap($w, $h)",
          "$g = [System.Drawing.Graphics]::FromImage($bmp)",
          "$g.CopyFromScreen(0, 0, 0, 0, $bmp.Size)",
          "$bmp.Save($path)",
          "$g.Dispose()",
          "$bmp.Dispose()"]
    encoded = base64.b64encode("\n".join(_L).encode('utf-16-le')).decode('ascii')
    subprocess.run(["powershell", "-EncodedCommand", encoded])
    path = os.path.join(os.environ['USERPROFILE'], 'Desktop', 'screenshot.png')
    print(f"스크린샷 저장: {path}")
- 현재 시간:
    from datetime import datetime
    print(datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분"))
- 화면 밝기 올리기:
    import subprocess
    result = subprocess.run(["powershell", "-c",
        "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"],
        capture_output=True, text=True)
    current = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 50
    new_val = min(100, current + 10)
    subprocess.run(["powershell", "-c",
        f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{new_val})"])
    print(f"밝기: {current}% → {new_val}%")
- 화면 밝기 내리기:
    import subprocess
    result = subprocess.run(["powershell", "-c",
        "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"],
        capture_output=True, text=True)
    current = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 50
    new_val = max(0, current - 10)
    subprocess.run(["powershell", "-c",
        f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{new_val})"])
    print(f"밝기: {current}% → {new_val}%")
- CPU 사용량:
    import psutil
    print(f"CPU 사용량: {psutil.cpu_percent(interval=1)}%")
- 메모리 사용량:
    import psutil
    mem = psutil.virtual_memory()
    print(f"RAM 사용량: {mem.percent}% ({mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB)")
- 저장공간 조회:
    import shutil
    total, used, free = shutil.disk_usage('C:\\')
    print(f"C드라이브 - 전체: {total//(1024**3)}GB, 사용: {used//(1024**3)}GB, 남은 공간: {free//(1024**3)}GB")

selenium 사용 예시 (반드시 이 방식으로):
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time

options = Options()
driver = webdriver.Chrome(options=options)

웹 검색/지도 예시 (selenium으로 구현):
- 구글 검색:
    driver.get("https://www.google.com/search?q=검색어")
- 유튜브 검색:
    driver.get("https://www.youtube.com/results?search_query=검색어")
- 네이버 검색:
    driver.get("https://search.naver.com/search.naver?query=검색어")
- 네이버 지도 경로 검색:
    driver.get("https://map.naver.com/v5/directions")
    time.sleep(2)
    inputs = driver.find_elements(By.CSS_SELECTOR, "input.input_search")
    if len(inputs) >= 2:
        inputs[0].send_keys("출발지명")
        inputs[1].send_keys("도착지명")
"""


class SupervisorAgent(BaseAgent):
    def __init__(self):
        self._init_client(ACTIVE_PROVIDER, ACTIVE_MODEL)

    def analyze_command(self, user_input: str) -> dict:
        return {}

    def is_complex(self, command: dict) -> bool:
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