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

{HISTORY_SECTION}

반드시 지켜야 할 규칙:
1. 파일 삭제, 시스템 파일 수정 절대 금지
2. 웹 작업은 반드시 selenium 사용
3. 새로운 라이브러리 설치 시도 금지
4-1. 사용 가능한 라이브러리 (허용 목록):
    ctypes, psutil, subprocess, os, time, re, datetime, shutil, glob,
    json, sqlite3, base64, io, sys, selenium, requests, winreg
    그 외 모든 외부 라이브러리 import 금지 (pywinauto, win32gui, win32con,
    pynput, keyboard, mouse, pyautogui, PIL, cv2, numpy 등 전부 금지)
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
    path_fwd = '/'.join(path.split('\\\\'))
    절대 사용 금지: path.split('\\') 또는 path.replace('\\\\', '/') 또는 path.replace('\\', '/')
14. 모든 코드는 반드시 try/except로 감싸서 작성할 것
15. PostMessageW, SendMessageW를 while 루프로 여러 창에 반복 적용 절대 금지
    반드시 특정 앱 하나만 타겟으로 FindWindowW 방식 사용
16. "모두 닫아줘", "전부 닫아줘", "다 닫아줘" 등 전체 종료 명령은
    히스토리에 특정 앱이 명시된 경우 그 앱만 닫을 것
    히스토리에도 대상이 없으면 Z-order 두 번째 창 하나만 닫을 것
17. shutdown, restart, logoff 등 시스템 종료/재시작 명령 절대 금지
18. except 블록에서 반드시 print(f"실행 실패: {e}") 출력할 것
    예시:
    try:
        import subprocess
        subprocess.Popen(["C:/Windows/System32/notepad.exe"])
    except Exception as e:
        print(f"실행 실패: {e}")
19. 코드 마지막에 반드시 print("실행 완료") 출력할 것
    단, 되묻기 출력(print("되묻기:..."))이 있는 경우는 제외
    성공/실패 분기가 있는 경우 반드시 성공 분기 안에 print("실행 완료") 포함할 것
    예시 (단순 실행):
    try:
        import subprocess
        subprocess.Popen(["C:/Windows/System32/notepad.exe"])
        print("실행 완료")
    except Exception as e:
        print(f"실행 실패: {e}")
    예시 (창 제어 — 성공/실패 분기 있는 경우):
    try:
        # ... psutil, EnumWindows 로직 ...
        if not result[0]:
            print("실행 실패: 창을 찾을 수 없습니다")
        else:
            print("실행 완료")  # ← 반드시 성공 분기 안에 포함
    except Exception as e:
        print(f"실행 실패: {e}")
20. 파일 또는 폴더 생성 시 생성된 전체 경로를 반드시 출력할 것
    형식: print(f"생성 완료: {전체경로변수}")
    예시:
    try:
        import os
        full_path = os.path.join(os.path.expanduser("~"), "Desktop", "test.txt")
        with open(full_path, "w") as f:
            pass
        print(f"생성 완료: {full_path}")
        print("실행 완료")
    except Exception as e:
        print(f"실행 실패: {e}")


{APP_PATHS_PLACEHOLDER}
- 바탕화면: os.path.join(os.environ['USERPROFILE'], 'Desktop')
- 다운로드: os.path.join(os.environ['USERPROFILE'], 'Downloads')
- 문서: os.path.join(os.environ['USERPROFILE'], 'Documents')
- Windows 설정: subprocess.Popen(["start", "ms-settings:"], shell=True)

Windows 창 제어 방법 (반드시 ctypes 사용):

[핵심 원칙]
- 앱명이 명시된 경우: 반드시 psutil로 실행 중인 프로세스를 찾아 해당 창만 제어
- 앱명 불명인 경우에만: Z-order 방식으로 현재 포그라운드 다음 창 제어
- Z-order 방식을 앱명 있는 명령에 절대 사용 금지 (엉뚱한 창 제어됨)

앱별 프로세스명 매핑:
  크롬    → "chrome.exe"
  엣지    → "msedge.exe"
  메모장  → "notepad.exe"
  파일탐색기 → "explorer.exe" (단, explorer.exe 종료 금지 — 창 닫기만)
  카카오톡 → "kakaotalk.exe"
  워드   → "winword.exe"
  엑셀   → "excel.exe"

앱별 윈도우 클래스명:
  메모장 = "Notepad"
  파일탐색기 = "CabinetWClass"
  크롬 = "Chrome_WidgetWin_1"
  엣지 = "Chrome_WidgetWin_1"

- 앱 지정 창 제어 (앱명 있을 때 — 반드시 이 방식):
  psutil로 실행 중인지 먼저 확인 후 hwnd 탐색.
  ※ exec() 환경에서 nonlocal, global 사용 금지 — 반드시 리스트로 상태 전달:
  ※ wt는 외부 모듈이 아님 — 반드시 'import ctypes, ctypes.wintypes as wt' 형태로 import할 것. 'import wt' 절대 금지.
    import ctypes, ctypes.wintypes as wt, psutil
    try:
        target_proc = "chrome.exe"  # 앱에 맞게 교체
        pids = {p.pid for p in psutil.process_iter(["name"]) if p.info["name"].lower() == target_proc}
        if not pids:
            print(f"실행 실패: {target_proc} 프로세스가 실행 중이지 않습니다")
        else:
            user32 = ctypes.windll.user32
            result = [False]  # nonlocal 대신 리스트로 상태 공유 (exec 환경 호환)
            def _enum_cb(hwnd, _):
                if not user32.IsWindowVisible(hwnd) or result[0]:
                    return True
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in pids:
                    user32.ShowWindow(hwnd, 6)  # 6=최소화, 3=최대화
                    # 닫기: user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    result[0] = True
                    return False
                return True
            user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(_enum_cb), 0)
            if not result[0]:
                print("실행 실패: 창을 찾을 수 없습니다")
    except Exception as e:
        print(f"실행 실패: {e}")

- 앱 지정 창 열기/새 탭 (크롬/엣지 — 이미 실행 중이면 새 탭, 아니면 새 창):
    import subprocess, psutil
    try:
        is_running = any(p.name().lower() == "chrome.exe" for p in psutil.process_iter(["name"]))
        chrome_path = "C:/Program Files/Google/Chrome/Application/chrome.exe"
        if is_running:
            subprocess.Popen([chrome_path, "--new-tab"])
        else:
            subprocess.Popen([chrome_path])
    except Exception as e:
        print(f"실행 실패: {e}")

- 창 제어 (타겟 불명):
    앱명 없이 창 제어 동작만 있는 경우 — 코드 생성 금지, 되묻기 출력.
    해당 패턴: "최소화", "최소화 해줘", "최대화", "최대화 해줘", "닫아줘", "닫아", "창 닫아줘",
              "원상복구", "원래대로", "복구해줘" 등 앱명 없이 동작 키워드만 있는 모든 경우.

    되묻기 형식 규칙 (반드시 준수):
    - 동작이 최소화/minimize/작게 계열 → print("되묻기:[최소화] 어떤 앱을 최소화할까요?")
    - 동작이 최대화/maximize/크게 계열 → print("되묻기:[최대화] 어떤 앱을 최대화할까요?")
    - 동작이 닫기/close/종료 계열      → print("되묻기:[닫기] 어떤 앱을 닫을까요?")
    - 동작이 원상복구/복원/restore 계열 → print("되묻기:[원상복구] 어떤 앱을 원상복구할까요?")
    - 그 외 창 제어 동작               → print("되묻기:[기타] 어떤 앱을 제어할까요?")

    예시:
      "최소화"      → print("되묻기:[최소화] 어떤 앱을 최소화할까요?")
      "최대화 해줘" → print("되묻기:[최대화] 어떤 앱을 최대화할까요?")
      "닫아줘"      → print("되묻기:[닫기] 어떤 앱을 닫을까요?")
      "원상복구"    → print("되묻기:[원상복구] 어떤 앱을 원상복구할까요?")

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
    level = 20  # 반드시 사용자가 요청한 실제 숫자로 교체할 것
    steps = round(level / 2)
    for _ in range(steps):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
        time.sleep(0.05)
- 볼륨 상대값 내리기 예시 ("30 줄여줘" → 15회):
    import ctypes, time
    level = 30  # 반드시 사용자가 요청한 실제 숫자로 교체할 것
    steps = round(level / 2)
    for _ in range(steps):
        ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
        time.sleep(0.05)
- 볼륨 절대값 설정 예시 ("50으로 해줘"):
    # 현재 볼륨 조회 → 차이만큼 상대 조절
    import ctypes, time, subprocess
    try:
        result = subprocess.run(
            ["powershell", "-c",
             "Add-Type -TypeDefinition '"
             "using System.Runtime.InteropServices;"
             "[Guid(\"5CDF2C82-841E-4546-9722-0CF74078229A\")]"
             "[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]"
             "interface IAudioEndpointVolume { int f1(); int f2(); int f3(); int f4();"
             "int GetMasterVolumeLevelScalar(out float fLevel); }'"
             "; $vol = 50"],
            capture_output=True, text=True, timeout=5
        )
    except:
        pass
    # 외부 모듈 없이 안정적으로: 현재 볼륨을 0으로 내린 뒤 목표값만큼 올리기
    # 먼저 음소거 후 목표 볼륨까지 올리는 방식
    import ctypes, time
    # 1. 볼륨 0으로
    for _ in range(50):
        ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
        time.sleep(0.02)
        ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
        time.sleep(0.02)
    # 2. 목표값(예: 50)만큼 올리기 — keybd_event 1회 = 2단위
    target_vol = 50
    steps = round(target_vol / 2)
    for _ in range(steps):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
        time.sleep(0.02)
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
        time.sleep(0.02)
- 음소거 토글:
    import ctypes, time
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
- 배터리 잔량:
    import subprocess
    result = subprocess.run(["powershell", "-c",
        "(Get-WmiObject Win32_Battery).EstimatedChargeRemaining"],
        capture_output=True, text=True)
    print(f"배터리 잔량: {result.stdout.strip()}%")
- 화면 캡처 (반드시 아래 코드 그대로 사용):
    import subprocess, os, base64
    try:
        _L = [
            "Add-Type -TypeDefinition @'",
            "using System;",
            "using System.Runtime.InteropServices;",
            "public class DPIHelper {",
            "    [DllImport(\"user32.dll\")] public static extern bool SetProcessDPIAware();",
            "    [DllImport(\"user32.dll\")] public static extern int GetSystemMetrics(int nIndex);",
            "}",
            "'@",
            "Add-Type -AssemblyName System.Drawing",
            "[DPIHelper]::SetProcessDPIAware()",
            "$w = [DPIHelper]::GetSystemMetrics(0)",
            "$h = [DPIHelper]::GetSystemMetrics(1)",
            "$ts = Get-Date -Format 'yyyyMMdd_HHmmss'",
            "$path = [System.IO.Path]::Combine($env:USERPROFILE, 'Desktop', ('screenshot_' + $ts + '.png'))",
            "$bmp = New-Object System.Drawing.Bitmap($w, $h)",
            "$g = [System.Drawing.Graphics]::FromImage($bmp)",
            "$g.CopyFromScreen(0, 0, 0, 0, $bmp.Size)",
            "$bmp.Save($path)",
            "$g.Dispose()",
            "$bmp.Dispose()"
        ]
        encoded = base64.b64encode("\n".join(_L).encode("utf-16-le")).decode("ascii")
        subprocess.run(["powershell", "-EncodedCommand", encoded])
        print("스크린샷 저장: 바탕화면/screenshot_YYYYMMDD_HHMMSS.png")
    except Exception as e:
        print(f"실행 실패: {e}")
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
    total, used, free = shutil.disk_usage('C:\\\\')
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


def _build_history_section(history: list[dict]) -> str:
    """
    히스토리 리스트 → BRAIN_PROMPT에 주입할 텍스트 블록 생성.
    history 항목: {"user_input": str, "command": dict, "result": dict}
    """
    if not history:
        return ""

    # 노이즈 필터링 — history_response(히스토리 조회)는 맥락 불필요
    SKIP_ACTIONS = {"history_response"}

    lines = []
    idx = 1
    for h in history:
        cmd = h.get("command", {})
        action = cmd.get("action", "")
        params = cmd.get("params", {})
        result_status = h.get("result", {}).get("status", "")

        if action in SKIP_ACTIONS:
            continue

        user_input = h.get("user_input", "")
        status_str = f" [{'성공' if result_status == 'success' else '실패'}]" if result_status else ""

        # natural_language는 user_input이 곧 명령 내용 — action 표기 불필요
        if action == "natural_language":
            cmd_summary = user_input
        else:
            param_str = ", ".join(
                f"{k}={v}" for k, v in params.items()
                if k in ("app", "name", "file", "url", "query") and v
            )
            cmd_summary = f"{action}({param_str})" if param_str else action

        lines.append(f"  [{idx}] \"{user_input}\" → {cmd_summary}{status_str}")
        idx += 1

    history_text = "\n".join(lines)
    return f"""[대화 히스토리 — 맥락 참조용]
아래는 사용자의 최근 명령 기록이야. 맥락 해석 규칙을 반드시 따를 것.

[맥락 해석 규칙 — 우선순위 순서]
1. 순수 반복 지시어("다시 해줘", "또 해줘", "한 번 더")가 있으면:
   - 직전 명령이 [성공]인 경우 → 되묻기 없이 그대로 재실행
   - 직전 명령이 [실패]인 경우 → 다른 방식으로 재시도
   - 히스토리가 비어있는 경우 → 되묻기
   주의: "다시 내려줘", "다시 올려줘"처럼 동작이 명시된 경우는 새 명령으로 처리
2. "그거", "이거", "그것", "아까" 등 지시어가 있으면:
   히스토리에서 대상(앱/파일/URL 등)을 파악해서 코드 생성
3. 히스토리와 무관한 명령이면 히스토리 무시

{history_text}

"""


class SupervisorAgent(BaseAgent):
    def __init__(self):
        self._init_client(ACTIVE_PROVIDER, ACTIVE_MODEL)
        self.prompt = BRAIN_PROMPT
        try:
            from app.utils.path_resolver import PathResolver
            resolver = PathResolver()
            path_info = resolver.get_prompt_paths()
            self.prompt = self.prompt.replace("{APP_PATHS_PLACEHOLDER}", path_info)
            print(f"[SupervisorAgent] 경로 주입 완료")
        except Exception as e:
            self.prompt = self.prompt.replace("{APP_PATHS_PLACEHOLDER}", "")
            print(f"[SupervisorAgent] 경로 주입 실패, 기본값 사용: {e}")

    def analyze_command(self, user_input: str) -> dict:
        return {}

    def is_complex(self, command: dict) -> bool:
        return True

    def generate_code(
        self,
        command: dict,
        original_input: str,
        error_context: dict = None,
        history: list[dict] = None,
    ) -> str:
        """
        파이썬 실행 코드 생성.

        Args:
            command:        {type, action, params} — InterpreterExecutor에서 전달
            original_input: 사용자 원본 자연어 입력 (앱 경로 주입 후 버전일 수 있음)
            error_context:  재시도 시 이전 실패 정보
            history:        ContextMemory에서 가져온 최근 히스토리 (맥락 해석용)
        """
        try:
            # ── 히스토리 섹션 구성 ────────────────────────────────
            history_section = _build_history_section(history or [])
            if history_section:
                print(f"[Supervisor] 히스토리 주입:\n{history_section.strip()}")
            else:
                print("[Supervisor] 히스토리 없음")
            prompt_with_history = self.prompt.replace(
                "{HISTORY_SECTION}", history_section
            )

            # ── 에러 피드백 구성 ──────────────────────────────────
            if error_context:
                error_type    = error_context.get("type", "unknown")
                error_reason  = error_context.get("reason", "")
                previous_code = error_context.get("code", "")

                type_guide = {
                    "syntax_error": "이전 코드에 문법 오류가 있었음. 올바른 Python 문법으로 다시 작성할 것.",
                    "error": "이전 코드 실행 중 런타임 오류 발생. 오류 원인을 분석하고 다른 방식으로 작성할 것.",
                    "verification_failed": (
                        "이전 코드가 실행은 됐지만 의도한 결과가 확인되지 않음. "
                        "완전히 다른 접근 방식을 사용할 것. "
                        "이전과 동일한 경로나 방식 사용 금지."
                    ),
                }.get(error_type, "이전 시도가 실패함. 다른 방식으로 작성할 것.")

                feedback = (
                    f"\n\n[이전 시도 실패 — 반드시 다른 방식으로 작성할 것]\n"
                    f"실패 유형: {error_type}\n"
                    f"실패 원인: {error_reason}\n"
                    f"대응 방법: {type_guide}\n"
                    f"실패한 코드:\n```python\n{previous_code}\n```\n"
                    f"위 코드와 동일한 경로, 동일한 방식 절대 사용 금지."
                )
            else:
                feedback = ""

            prompt = (
                f"{prompt_with_history}\n\n"
                f"사용자 명령: {original_input}"
                f"{feedback}\n\n"
                f"실행할 파이썬 코드만 작성해줘:"
            )
            text = self._call_llm(prompt)
            code_match = re.search(r'```python\n(.*?)\n```', text, re.DOTALL)
            if code_match:
                return code_match.group(1)
            return text.strip()
        except Exception as e:
            print(f"[Supervisor 오류] {e}")
            return None


    def classify_steps(self, user_input: str) -> list[dict] | None:
        """
        자연어 입력이 순서 독립 멀티스텝인지 판단.
        멀티스텝이면 스텝 배열 반환, 단일 명령이면 None 반환.

        지원: 순서 독립적인 2개 스텝까지
        미지원: 스텝 간 결과 전달 필요한 명령 → None 반환 (단일 명령 폴백)
        """
        if not self.available:
            return None
        try:
            prompt = (
                "사용자 입력이 독립적인 여러 PC 제어 명령을 포함하는지 판단해줘.\n\n"
                "판단 기준:\n"
                "- 각 명령이 서로 독립적으로 실행 가능한 경우 → 분리\n"
                "- 앞 명령의 결과가 뒤 명령의 전제조건인 경우 → 분리 불가 (single 반환)\n"
                "  예) '크롬 열고 유튜브 검색해줘' → 크롬 열림 후 검색 필요 → single\n"
                "  예) '메모장 열고 안녕 입력해줘' → 메모장 열림 후 입력 필요 → single\n"
                "- 3개 이상 명령 → single 반환\n"
                "- 명확히 독립적인 2개 명령만 분리\n"
                "  예) '메모장이랑 계산기 열어줘' → 분리 가능\n"
                "  예) '볼륨 올리고 화면 캡처해줘' → 분리 가능\n"
                "  예) '메모장 열어줘' → 단일 명령\n\n"
                "응답 형식 (JSON만, 설명 없이):\n"
                '분리 가능: {"type": "multi", "steps": ["스텝1 자연어", "스텝2 자연어"]}\n'
                '분리 불가: {"type": "single"}\n\n'
                f"사용자 입력: {user_input}"
            )

            text = self._call_llm(prompt).strip()
            import json as _json, re as _re
            json_match = _re.search(r'\{.*\}', text, _re.DOTALL)
            if not json_match:
                return None
            parsed = _json.loads(json_match.group())
            if parsed.get("type") != "multi":
                return None
            steps_text = parsed.get("steps", [])
            if len(steps_text) != 2:
                return None
            return [
                {
                    "type": "interpreter",
                    "action": "natural_language",
                    "params": {"input": s},
                }
                for s in steps_text
            ]
        except Exception as e:
            print(f"[Supervisor] classify_steps 오류 → 단일 명령 폴백: {e}")
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