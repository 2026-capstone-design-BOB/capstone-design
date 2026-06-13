"""
앱 제어 도구
앱 실행 / 종료 / 창 최대화·최소화 / 바탕화면 보기
"""

import os
import subprocess
import time
import glob
import concurrent.futures
import ctypes
import ctypes.wintypes
import psutil
from langchain_core.tools import tool

# ── 앱 정보 매핑 ──────────────────────────────────────────────────

APP_ALIASES: dict[str, str] = {
    # 한국어 → 내부 키
    "크롬": "chrome", "구글크롬": "chrome",
    "엣지": "edge", "마이크로소프트엣지": "edge",
    "메모장": "notepad",
    "계산기": "calculator",
    "탐색기": "explorer", "파일탐색기": "explorer", "파일 탐색기": "explorer",
    "카카오톡": "kakaotalk", "카톡": "kakaotalk", "카카오": "kakaotalk",
    "워드": "word", "msword": "word",
    "엑셀": "excel", "msexcel": "excel",
    "파워포인트": "powerpoint", "ppt": "powerpoint",
    "vscode": "vscode", "비주얼스튜디오코드": "vscode",
    "파이어폭스": "firefox",
    "터미널": "terminal", "cmd": "terminal",
    # 설정
    "설정": "settings", "윈도우설정": "settings", "windows설정": "settings",
}

# ── 한국어 표시 이름 ──────────────────────────────────────────────

APP_DISPLAY_NAMES: dict[str, str] = {
    "notepad":    "메모장",
    "calculator": "계산기",
    "chrome":     "Chrome",
    "edge":       "Edge",
    "explorer":   "파일 탐색기",
    "firefox":    "Firefox",
    "word":       "Word",
    "excel":      "Excel",
    "powerpoint": "PowerPoint",
    "vscode":     "VS Code",
    "kakaotalk":  "카카오톡",
    "terminal":   "터미널",
    "settings":   "설정",
}


def _display_name(app_key: str, original: str) -> str:
    """앱 표시 이름 반환 (한국어 우선)."""
    return APP_DISPLAY_NAMES.get(app_key, original)


def _find_hwnd_by_title(keywords: list[str]) -> int:
    """창 제목으로 HWND 검색. UWP 앱(Calculator 등) PID 매칭 실패 시 fallback.
    keywords 중 하나라도 포함된 visible 창의 HWND 반환. 없으면 0.
    """
    found = ctypes.c_void_p(0)
    kws_lower = [k.lower() for k in keywords if k]

    def callback(h, _):
        if not ctypes.windll.user32.IsWindowVisible(h):
            return True
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(h, buf, 256)
        title = buf.value.lower()
        if any(kw in title for kw in kws_lower):
            found.value = h
            return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found.value or 0


def _korean_particle(name: str, with_batchim: str, without_batchim: str) -> str:
    """한국어 조사 선택 (을/를, 이/가 등). 마지막 글자 받침 여부로 결정."""
    if not name:
        return with_batchim
    last = name[-1]
    code = ord(last)
    if code < 0xAC00 or code > 0xD7A3:
        # ASCII/특수문자: 받침 없는 것으로 처리
        return without_batchim
    has_batchim = (code - 0xAC00) % 28 != 0
    return with_batchim if has_batchim else without_batchim

APP_PROCESS_MAP: dict[str, list[str]] = {
    "settings":   ["systemsettings.exe"],
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


def _focus_window(app_key: str) -> bool:
    """실행 중인 앱 창을 포그라운드로 가져옴. 성공 시 True."""
    targets = {p.lower() for p in APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])}
    found_hwnd = None

    def _enum_cb(hwnd, _):
        nonlocal found_hwnd
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        pid_buf = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
        try:
            proc = psutil.Process(pid_buf.value)
            if proc.name().lower() in targets:
                found_hwnd = hwnd
                return False  # 탐색 중단
        except Exception:
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)

    if not found_hwnd:
        return False

    # Windows 포그라운드 권한 우회 (AttachThreadInput 트릭)
    try:
        SW_RESTORE = 9
        fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
        fg_tid  = ctypes.windll.user32.GetWindowThreadProcessId(fg_hwnd, None)
        my_tid  = ctypes.windll.kernel32.GetCurrentThreadId()
        if fg_tid and fg_tid != my_tid:
            ctypes.windll.user32.AttachThreadInput(my_tid, fg_tid, True)
        ctypes.windll.user32.ShowWindow(found_hwnd, SW_RESTORE)
        ctypes.windll.user32.BringWindowToTop(found_hwnd)
        ctypes.windll.user32.SetForegroundWindow(found_hwnd)
        if fg_tid and fg_tid != my_tid:
            ctypes.windll.user32.AttachThreadInput(my_tid, fg_tid, False)
        return True
    except Exception:
        return False


def _resolve_path(app_key: str) -> str | None:
    """앱 실행 경로 탐색. 순서: where → fallback → registry → glob(알려진 앱만)."""
    exe_name = APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])[0]

    # 1. where 명령 (PATH에 등록된 앱)
    try:
        result = subprocess.run(["where", exe_name], capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            path = result.stdout.strip().splitlines()[0]
            if os.path.exists(path):
                return path
    except Exception:
        pass

    # ── 알려지지 않은 앱: where 실패 시 즉시 포기 (느린 glob 탐색 방지) ──
    if app_key not in APP_FALLBACK_PATHS:
        return None

    # 2. fallback 경로 (알려진 앱만)
    for path in APP_FALLBACK_PATHS.get(app_key, []):
        if "*" in path:
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

    # 4. glob 탐색 (알려진 앱, 3초 제한)
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
            return ex.submit(_glob).result(timeout=3)
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
    Windows 앱을 실행하거나 이미 실행 중이면 창을 활성화합니다.
    app: 앱 이름 (예: chrome, notepad, calculator, kakaotalk, edge, explorer, word, excel, powerpoint, vscode, terminal, 설정)
    한국어도 가능 (크롬, 메모장, 계산기, 카카오톡, 설정 등)
    """
    app_key = _normalize(app)
    name = _display_name(app_key, app)
    eul_reul = _korean_particle(name, "을", "를")

    # ── 이미 실행 중이면 창 활성화 (새 창 열지 않음) ──────────────
    if _is_running(app_key):
        if _focus_window(app_key):
            return f"✓ {name} 창을 앞으로 가져왔습니다."
        return f"✓ {name}은(는) 이미 실행 중입니다."

    # ── UWP·내장 앱: shell 명령으로 직접 실행 ───────────────────
    UWP_SHELL_COMMANDS = {
        "calculator": "calc.exe",
        "notepad":    "notepad.exe",
        "explorer":   "explorer.exe",
        "terminal":   "wt.exe",
        "settings":   "start ms-settings:",
    }
    if app_key in UWP_SHELL_COMMANDS:
        try:
            subprocess.Popen(UWP_SHELL_COMMANDS[app_key], shell=True)
            time.sleep(0.5)
            return f"✓ {name}{eul_reul} 실행했습니다."
        except Exception as e:
            return f"✗ {name} 실행 실패: {e}"

    path = _resolve_path(app_key)
    if not path:
        return (
            f"✗ '{name}' 앱을 찾을 수 없습니다. "
            "설치되어 있지 않거나 지원하지 않는 앱입니다."
        )

    try:
        subprocess.Popen([path])
        time.sleep(0.8)
        if _is_running(app_key):
            return f"✓ {name}{eul_reul} 실행했습니다."
        return f"✓ {name} 실행 명령을 보냈습니다."
    except Exception as e:
        return f"✗ {name} 실행 실패: {e}"


@tool
def close_app(app: str) -> str:
    """
    실행 중인 앱을 종료합니다.
    app: 앱 이름 (예: chrome, notepad, calculator 등)
    """
    app_key = _normalize(app)

    # BUG-11: explorer.exe는 Windows 셸 프로세스 — 종료 시 바탕화면·작업표시줄 전체 소멸
    if app_key == "explorer":
        return (
            "⚠️ 파일 탐색기(explorer.exe)는 Windows 셸 프로세스입니다. "
            "종료하면 바탕화면과 작업 표시줄이 사라집니다. "
            "탐색기 창을 닫으려면 해당 창의 ✕ 버튼을 직접 눌러주세요."
        )

    targets = APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])

    killed = []
    for proc in psutil.process_iter(["name", "pid"]):
        if proc.info["name"].lower() in [t.lower() for t in targets]:
            try:
                proc.terminate()
                killed.append(proc.info["name"])
            except Exception:
                pass

    name = _display_name(app_key, app)
    if killed:
        eul_reul = _korean_particle(name, "을", "를")
        return f"✓ {name}{eul_reul} 종료했습니다."
    i_ga = _korean_particle(name, "이", "가")
    return f"✗ '{name}'{i_ga} 실행 중이지 않습니다."


@tool
def maximize_window(app: str = "") -> str:
    """
    앱 창을 최대화합니다.
    app: 앱 이름 (비워두면 현재 활성 창)
    """
    SW_MAXIMIZE = 3

    if app:
        app_key = _normalize(app)
        targets = {t.lower() for t in APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])}

        # 매칭 프로세스 PID 전체 수집 (Chrome 등 멀티 프로세스 대응)
        target_pids: set[int] = set()
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"].lower() in targets:
                target_pids.add(proc.info["pid"])

        if not target_pids:
            return f"✗ {app}이(가) 실행 중이지 않습니다."

        found = False
        def callback(h, _):
            nonlocal found
            if found:
                return False  # 첫 번째 창 찾으면 중단
            if not ctypes.windll.user32.IsWindowVisible(h):
                return True
            buf = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(h, ctypes.byref(buf))
            if buf.value in target_pids:
                ctypes.windll.user32.ShowWindow(h, SW_MAXIMIZE)
                found = True
                return False
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)

        if found:
            return f"✓ {app} 창을 최대화했습니다."

        # UWP 앱 fallback: 창 제목으로 검색 (ApplicationFrameHost 등)
        display = APP_DISPLAY_NAMES.get(app_key, app)
        hwnd = _find_hwnd_by_title([display, app, app_key])
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, SW_MAXIMIZE)
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
    SW_MINIMIZE = 6

    if app:
        app_key = _normalize(app)
        targets = {t.lower() for t in APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])}

        target_pids: set[int] = set()
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"].lower() in targets:
                target_pids.add(proc.info["pid"])

        if not target_pids:
            return f"✗ {app}이(가) 실행 중이지 않습니다."

        found = False
        def callback(h, _):
            nonlocal found
            if found:
                return False
            if not ctypes.windll.user32.IsWindowVisible(h):
                return True
            buf = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(h, ctypes.byref(buf))
            if buf.value in target_pids:
                ctypes.windll.user32.ShowWindow(h, SW_MINIMIZE)
                found = True
                return False
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)

        if found:
            return f"✓ {app} 창을 최소화했습니다."

        # UWP 앱 fallback: 창 제목으로 검색
        display = APP_DISPLAY_NAMES.get(app_key, app)
        hwnd = _find_hwnd_by_title([display, app, app_key])
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
            return f"✓ {app} 창을 최소화했습니다."

        return f"✗ {app} 창을 찾을 수 없습니다."
    else:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
        return "✓ 현재 창을 최소화했습니다."


@tool
def show_desktop() -> str:
    """모든 창을 최소화하여 바탕화면을 표시합니다."""
    ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win
    ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)  # D
    ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)
    ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)
    return "\u2713 \ubc14\ud0d5\ud654\uba74\uc744 \ud45c\uc2dc\ud588\uc2b5\ub2c8\ub2e4."
