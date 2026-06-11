"""
앱 제어 도구
앱 실행 / 종료 / 창 최대화·최소화 / 바탕화면 보기
"""

import os
import subprocess
import time
import glob
import concurrent.futures
import psutil
from langchain_core.tools import tool

# ── 앱 정보 매핑 ──────────────────────────────────────────────────

APP_ALIASES: dict[str, str] = {
    # 한국어 → 내부 키
    "크롬": "chrome", "구글크롬": "chrome",
    "엣지": "edge", "마이크로소프트엣지": "edge",
    "메모장": "notepad",
    "계산기": "calculator",
    "탐색기": "explorer", "파일탐색기": "explorer",
    "카카오톡": "kakaotalk", "카톡": "kakaotalk", "카카오": "kakaotalk",
    "워드": "word", "msword": "word",
    "엑셀": "excel", "msexcel": "excel",
    "파워포인트": "powerpoint", "ppt": "powerpoint",
    "vscode": "vscode", "비주얼스튜디오코드": "vscode",
    "파이어폭스": "firefox",
    "터미널": "terminal", "cmd": "terminal",
}

APP_PROCESS_MAP: dict[str, list[str]] = {
    "notepad":    ["notepad.exe"],
    "calculator": ["calculatorapp.exe", "calculator.exe"],
    "chrome":     ["chrome.exe"],
    "edge":       ["msedge.exe"],
    "explorer":   ["explorer.exe"],
    "firefox":    ["firefox.exe"],
    "word":       ["winword.exe"],
    "excel":      ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "vscode":     ["code.exe"],
    "kakaotalk":  ["kakaotalk.exe"],
    "terminal":   ["wt.exe", "cmd.exe", "powershell.exe"],
}

APP_FALLBACK_PATHS: dict[str, list[str]] = {
    "chrome": [
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"), "Google/Chrome/Application/chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google/Chrome/Application/chrome.exe"),
    ],
    "edge": [
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Microsoft/Edge/Application/msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft/Edge/Application/msedge.exe"),
    ],
    "firefox": [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Mozilla Firefox/firefox.exe"),
    ],
    "kakaotalk": [
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Kakao/KakaoTalk/KakaoTalk.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Kakao/KakaoTalk/KakaoTalk.exe"),
    ],
    "word": [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft Office/root/Office16/WINWORD.EXE"),
    ],
    "excel": [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft Office/root/Office16/EXCEL.EXE"),
    ],
    "powerpoint": [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft Office/root/Office16/POWERPNT.EXE"),
    ],
    "vscode": [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs/Microsoft VS Code/Code.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft VS Code/Code.exe"),
    ],
    "terminal": [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft/WindowsApps/wt.exe"),
        "C:/Windows/System32/cmd.exe",
    ],
    "notepad": ["C:/Windows/System32/notepad.exe"],
    "calculator": [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "WindowsApps/Microsoft.WindowsCalculator*/Calculator.exe"),
    ],
    "explorer": ["C:/Windows/explorer.exe"],
}


# ── 내부 유틸 ─────────────────────────────────────────────────────

def _normalize(app_name: str) -> str:
    """앱 이름 정규화: 한국어/영어 모두 내부 키로 변환."""
    key = app_name.lower().replace(" ", "")
    return APP_ALIASES.get(key, key)


def _resolve_path(app_key: str) -> str | None:
    """앱 실행 경로 탐색. 순서: where → fallback → registry → glob."""
    exe_name = APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])[0]

    # 1. where 명령
    try:
        result = subprocess.run(["where", exe_name], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            path = result.stdout.strip().splitlines()[0]
            if os.path.exists(path):
                return path
    except Exception:
        pass

    # 2. fallback 경로
    for path in APP_FALLBACK_PATHS.get(app_key, []):
        if "*" in path:  # glob 패턴
            matches = glob.glob(path)
            if matches:
                return matches[0]
        elif os.path.exists(path):
            return path

    # 3. 레지스트리
    try:
        import winreg
        for hkey in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
            try:
                with winreg.OpenKey(hkey, subkey) as k:
                    reg_path, _ = winreg.QueryValueEx(k, "")
                    if os.path.exists(reg_path):
                        return reg_path
            except OSError:
                continue
    except ImportError:
        pass

    # 4. glob 탐색 (5초 제한)
    def _glob():
        roots = [
            os.environ.get("PROGRAMFILES", "C:/Program Files"),
            os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        for root in roots:
            if root and os.path.exists(root):
                matches = glob.glob(os.path.join(root, "**", exe_name), recursive=True)
                if matches:
                    return matches[0]
        return None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_glob).result(timeout=5)
    except Exception:
        return None


def _is_running(app_key: str) -> bool:
    targets = {p.lower() for p in APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])}
    running = {p.name().lower() for p in psutil.process_iter(["name"])}
    return bool(targets & running)


# ── 도구 정의 ─────────────────────────────────────────────────────

@tool
def open_app(app: str) -> str:
    """
    Windows 앱을 실행합니다.
    app: 앱 이름 (예: chrome, notepad, calculator, kakaotalk, edge, explorer, word, excel, powerpoint, vscode, terminal)
    한국어도 가능 (크롬, 메모장, 계산기, 카카오톡 등)
    """
    app_key = _normalize(app)

    # UWP 앱 및 내장 앱: 경로 탐색 없이 shell 명령으로 직접 실행
    UWP_SHELL_COMMANDS = {
        "calculator": "calc.exe",
        "notepad":    "notepad.exe",
        "explorer":   "explorer.exe",
        "terminal":   "wt.exe",
    }
    if app_key in UWP_SHELL_COMMANDS:
        try:
            subprocess.Popen(UWP_SHELL_COMMANDS[app_key], shell=True)
            time.sleep(0.5)
            return f"✓ {app}을(를) 실행했습니다."
        except Exception as e:
            return f"✗ {app} 실행 실패: {e}"

    path = _resolve_path(app_key)
    if not path:
        return f"✗ '{app}' 앱을 찾을 수 없습니다. 설치 여부를 확인하거나 정확한 앱 이름을 알려주세요."

    try:
        subprocess.Popen([path])
        time.sleep(0.8)
        if _is_running(app_key):
            return f"✓ {app}을(를) 실행했습니다."
        return f"✓ {app} 실행 명령을 보냈습니다."
    except Exception as e:
        return f"✗ {app} 실행 실패: {e}"


@tool
def close_app(app: str) -> str:
    """
    실행 중인 앱을 종료합니다.
    app: 앱 이름 (예: chrome, notepad, calculator 등)
    """
    app_key = _normalize(app)
    targets = APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])

    killed = []
    for proc in psutil.process_iter(["name", "pid"]):
        if proc.info["name"].lower() in [t.lower() for t in targets]:
            try:
                proc.terminate()
                killed.append(proc.info["name"])
            except Exception:
                pass

    if killed:
        return f"✓ {app}을(를) 종료했습니다."
    return f"✗ '{app}'이(가) 실행 중이지 않습니다."


@tool
def maximize_window(app: str = "") -> str:
    """
    앱 창을 최대화합니다.
    app: 앱 이름 (비워두면 현재 활성 창)
    """
    import ctypes
    SW_MAXIMIZE = 3

    if app:
        app_key = _normalize(app)
        targets = [t.lower() for t in APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])]

        hwnd = ctypes.windll.user32.FindWindowW(None, None)
        found = False
        # EnumWindows로 타겟 프로세스의 창 찾기
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"].lower() in targets:
                try:
                    import ctypes.wintypes
                    pid = proc.info["pid"]
                    # GetWindowThreadProcessId로 일치하는 hwnd 탐색
                    def callback(h, _):
                        nonlocal found
                        buf = ctypes.wintypes.DWORD()
                        ctypes.windll.user32.GetWindowThreadProcessId(h, ctypes.byref(buf))
                        if buf.value == pid and ctypes.windll.user32.IsWindowVisible(h):
                            ctypes.windll.user32.ShowWindow(h, SW_MAXIMIZE)
                            found = True
                        return True
                    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                    ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
                except Exception:
                    pass
                break

        if found:
            return f"✓ {app} 창을 최대화했습니다."
        return f"✗ {app} 창을 찾을 수 없습니다. 앱이 실행 중인지 확인하세요."
    else:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ctypes.windll.user32.ShowWindow(hwnd, SW_MAXIMIZE)
        return "✓ 현재 창을 최대화했습니다."


@tool
def minimize_window(app: str = "") -> str:
    """
    앱 창을 최소화합니다.
    app: 앱 이름 (비워두면 현재 활성 창)
    """
    import ctypes
    SW_MINIMIZE = 6

    if app:
        app_key = _normalize(app)
        targets = [t.lower() for t in APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])]
        found = False

        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"].lower() in targets:
                try:
                    import ctypes.wintypes
                    pid = proc.info["pid"]
                    def callback(h, _):
                        nonlocal found
                        buf = ctypes.wintypes.DWORD()
                        ctypes.windll.user32.GetWindowThreadProcessId(h, ctypes.byref(buf))
                        if buf.value == pid and ctypes.windll.user32.IsWindowVisible(h):
                            ctypes.windll.user32.ShowWindow(h, SW_MINIMIZE)
                            found = True
                        return True
                    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                    ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
                except Exception:
                    pass
                break

        if found:
            return f"✓ {app} 창을 최소화했습니다."
        return f"✗ {app} 창을 찾을 수 없습니다."
    else:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
        return "✓ 현재 창을 최소화했습니다."


@tool
def show_desktop() -> str:
    """모든 창을 최소화하여 바탕화면을 표시합니다."""
    import ctypes
    ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win 키
    ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)  # D 키
    ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)
    ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)
    return "✓ 바탕화면을 표시했습니다."
