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


def is_window_cloaked(hwnd: int) -> bool:
    """DWM이 **가려 둔(cloaked)** 창인가. 가려져 있으면 사용자 눈에 **안 보인다.**

    🚨 **2026-09-09 — 이 한 줄이 없어서 «설정 창을 열었다»고 세 번 거짓말했다.**

    Windows는 정지된 UWP 앱(설정·계산기 등)의 창을 **닫지 않고 cloak** 한다.
    그 창은 이렇게 보인다:

        IsWindowVisible : True          ← «보인다»고 나온다
        IsIconic        : False         ← 최소화도 아니다
        GetWindowRect   : 1536x912      ← 크기까지 정상
        제목            : '설정'
        DWMWA_CLOAKED   : 2             ← 실제로는 **가려져 있다**

    그래서 `IsWindowVisible`만 보면 **없는 창을 있다고 센다.** 포커스는 «성공»하고,
    캡처는 **낡거나 빈 픽셀**을 준다(포인팅 고리가 엉뚱한 데 그려진 이유이기도 하다).

    ⚠️ 실패하면 **False**(가려지지 않음)로 본다 — 판정 실패 때문에 멀쩡한 창을
      없다고 하면 그게 더 나쁘다.
    """
    try:
        cloaked = ctypes.c_int(0)
        # DWMWA_CLOAKED = 14
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return hr == 0 and cloaked.value != 0
    except Exception:
        return False


def _is_real_window(hwnd: int) -> bool:
    """사용자가 **실제로 볼 수 있는** 최상위 창인가."""
    u = ctypes.windll.user32
    if not u.IsWindowVisible(hwnd):
        return False
    return not is_window_cloaked(hwnd)


def _find_hwnd_by_title(keywords: list[str]) -> int:
    """창 제목으로 HWND 검색. UWP 앱(Calculator 등) PID 매칭 실패 시 fallback.
    keywords 중 하나라도 포함된 visible 창의 HWND 반환. 없으면 0.
    """
    found = ctypes.c_void_p(0)
    kws_lower = [k.lower() for k in keywords if k]

    def callback(h, _):
        # ⚠️ 여기도 cloaked를 걸러야 한다. 2026-09-09에 이 폴백이 정지된 UWP의
        #   `ApplicationFrameWindow`(제목 '설정')를 집어, 프로세스 필터를 통과한
        #   것도 아닌 **유령 창**을 «설정 창»으로 돌려줬다.
        if not _is_real_window(h):
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
    # ⚠️ `wt.exe`는 실행 스텁이고, **실제로 떠 있는 창의 프로세스는**
    #   `WindowsTerminal.exe`다. 2026-09-07 실기에서 확인했다 — 이게 없으면
    #   get_running_apps가 못 보고 close_app("터미널")도 못 찾는다.
    "terminal":   ["wt.exe", "windowsterminal.exe", "cmd.exe", "powershell.exe"],
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
        # ⚠️ IsWindowVisible만으로는 부족하다 — cloaked 창이 True를 준다
        if not _is_real_window(hwnd):
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


def find_hwnd_for_app(app_name: str) -> int:
    """
    앱 이름(한국어 포함)으로 **사용자가 실제로 볼 수 있는** 최상위 HWND 반환.
    0이면 창 없음. system.py의 창별 스크린샷 등 외부 모듈에서 재사용 가능.

    ⚠️ **cloaked 창은 «없는 것»으로 센다**(→ `is_window_cloaked`). 정지된 UWP 앱의
      유령 창을 세면, 있지도 않은 창을 «앞으로 가져왔다»고 답하게 된다.
    """
    app_key = _normalize(app_name)
    targets = {p.lower() for p in APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])}

    found = [0]

    def _cb(hwnd, _):
        # ⚠️ cloaked 창을 세면 «있는데 안 보이는 창»을 있다고 답하게 된다.
        #   그러면 포커스는 성공하고 캡처는 빈 픽셀을 준다 → 2026-09-09 «뻥카».
        if not _is_real_window(hwnd):
            return True
        pid_buf = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
        try:
            if psutil.Process(pid_buf.value).name().lower() in targets:
                found[0] = hwnd
                return False
        except Exception:
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)

    # 프로세스 기반으로 못 찾으면 제목 기반 fallback (explorer 등)
    if not found[0]:
        display = APP_DISPLAY_NAMES.get(app_key, app_name)
        found[0] = _find_hwnd_by_title([display, app_name, app_key])

    return found[0]


# UWP·내장 앱: focus API 신뢰도가 낮아 셸 명령으로 확실히 실행/전면화
_UWP_SHELL_COMMANDS: dict[str, str] = {
    "calculator": "calc.exe",
    "notepad":    "notepad.exe",
    "terminal":   "wt.exe",
    "settings":   "start ms-settings:",
}


# 새 작업 공간을 **탭**으로 여는 앱. 여기 없는 앱은 새 창으로 연다.
# (Ctrl+T가 표준 단축키다 — Win11 메모장·탐색기도 지원한다)
_TAB_APPS = {"chrome", "edge", "whale", "firefox", "notepad", "terminal", "explorer"}


def _open_new_view(app_key: str, name: str) -> str:
    """사용자가 **새로** 열어달라고 했을 때. 탭 지원 앱이면 탭, 아니면 새 창.

    ⚠️ 반드시 창을 **포커스한 뒤에** 단축키를 보낸다. 포커스에 실패했는데 키를
    보내면 사용자가 보고 있던 **다른 창**에 Ctrl+T가 들어간다 (BL-12와 같은 함정).
    그래서 포커스 성공을 확인하지 못하면 단축키를 아예 보내지 않는다.
    """
    if app_key in _TAB_APPS and _focus_window(app_key):
        try:
            import pyautogui
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "t")
            return f"✓ {name}에 새 탭을 열었습니다."
        except Exception as e:
            print(f"[open_app] 새 탭 단축키 실패 → 새 창으로 폴백: {e}")

    # 탭을 못 쓰거나 실패 → 새 인스턴스
    if app_key in _UWP_SHELL_COMMANDS:
        try:
            subprocess.Popen(_UWP_SHELL_COMMANDS[app_key], shell=True)
            time.sleep(0.5)
            return f"✓ {name}을(를) 새 창으로 열었습니다."
        except Exception as e:
            return f"✗ {name} 새 창 열기 실패: {e}"

    path = _resolve_path(app_key)
    if not path:
        return f"✗ '{name}' 앱을 찾을 수 없어 새로 열지 못했습니다."
    try:
        subprocess.Popen([path])
        time.sleep(0.8)
        return f"✓ {name}을(를) 새 창으로 열었습니다."
    except Exception as e:
        return f"✗ {name} 새 창 열기 실패: {e}"


# ── 도구 정의 ─────────────────────────────────────────────────────

def _await_window(app_key: str, timeout: float = 5.0, poll: float = 0.25) -> int:
    """창이 **실제로 뜰 때까지** 기다린다. 뜨면 hwnd, 아니면 0.

    🚨 **2026-09-09 — 이 함수가 없어서 거짓말을 했다.**
      `open_app("설정")`이 셸 명령(`ms-settings:`)을 쏘고 `time.sleep(0.5)` 뒤에
      **«✓ 설정 창을 앞으로 가져왔습니다»** 라고 답했다. 창이 떴는지 보지 않았고,
      실제로 설정 창은 뜨지 않았다. 사용자 평: *"설정창 띄워주지도 않고 거짓말도 하네."*

    ⚠️ UWP 앱(설정 등)은 **0.5초로는 안 뜬다.** 그리고 `_is_running`이 True여도
      창이 없을 수 있다 — Windows가 `SystemSettings.exe`를 창 없이 **살려 둔다.**
      «프로세스가 있다»와 «창이 보인다»는 다른 사실이고, 사용자가 원한 건 뒤쪽이다.
    """
    import time as _t
    deadline = _t.monotonic() + max(0.0, timeout)
    while True:
        hwnd = find_hwnd_for_app(app_key)
        if hwnd:
            return hwnd
        if _t.monotonic() >= deadline:
            return 0
        _t.sleep(poll)


def _launched_or_honest(app_key: str, name: str, eul_reul: str,
                        timeout: float = 5.0) -> str:
    """실행을 시도한 **뒤** 창을 확인하고, 본 대로 답한다.

    창이 안 뜨면 «열었다»고 하지 않는다 — 이 저장소가 반복해서 고쳐 온 결함이
    **«안 한 걸 했다고 말하는 것»** 이다(BL-12·BL-19·BL-21).
    """
    if _await_window(app_key, timeout):
        return f"✓ {name}{eul_reul} 열었습니다."
    return (f"⚠️ {name} 실행을 시도했지만 창이 나타나지 않았습니다. "
            f"잠시 뒤 다시 시도하거나 직접 열어 주세요.")


@tool
def open_app(app: str, new: bool = False) -> str:
    """
    Windows 앱을 엽니다. **이미 실행 중이면 새 창을 만들지 않고 그 창을 앞으로 가져옵니다.**
    app: 앱 이름 (예: chrome, notepad, calculator, kakaotalk, edge, explorer, word, excel, powerpoint, vscode, terminal, 설정)
    한국어도 가능 (크롬, 메모장, 계산기, 카카오톡, 설정 등)
    new: 사용자가 **"새로 열어줘" · "하나 더" · "새 탭"** 처럼 새 작업 공간을 원할 때만 True.
         탭을 지원하는 앱(크롬·엣지·메모장·터미널·탐색기)은 **새 탭**을,
         나머지는 새 창을 엽니다. 그냥 "열어줘"면 False로 두세요.
    """
    app_key = _normalize(app)
    name = _display_name(app_key, app)
    eul_reul = _korean_particle(name, "을", "를")

    # ── explorer 전용: 셸 프로세스로 항상 떠 있어서 _is_running이 항상 True
    # _is_running 체크 전에 별도 처리 → 항상 새 탐색기 창 열기
    # ⚠️ "기존 창 재사용" 규칙의 **유일한 예외**다. explorer.exe에는 바탕화면·작업표시줄
    #    창도 딸려 있어서 _focus_window가 그쪽을 잡을 수 있다. 탐색기는 여러 창을 띄워
    #    쓰는 게 보통이라 새 창이 사용자 기대에도 맞다.
    if app_key == "explorer":
        try:
            subprocess.Popen("explorer.exe", shell=True)
            time.sleep(0.5)
            return f"✓ {name}{eul_reul} 열었습니다."
        except Exception as e:
            return f"✗ {name} 실행 실패: {e}"

    # ── 이미 실행 중 ─────────────────────────────────────────────
    if _is_running(app_key):
        if new:
            return _open_new_view(app_key, name)

        # ⚠️ **포커스를 먼저 시도한다.** 예전엔 UWP 목록에 있으면 셸 명령을 먼저
        #    실행했는데, `notepad.exe`를 다시 띄우는 건 전면화가 아니라
        #    **새 창을 만드는 것**이다. 그래놓고 "창을 앞으로 가져왔습니다"라고
        #    답해서, 사용자는 계속 새 메모장이 쌓이는 걸 봐야 했다(2026-09-02 실기).
        #    셸 명령은 포커스가 **실패했을 때만** 폴백으로 쓴다
        #    (설정 앱처럼 창 핸들을 못 잡는 경우가 있다 — 그때는 원래 동작 그대로).
        if _focus_window(app_key):
            return f"✓ {name} 창을 앞으로 가져왔습니다."
        if app_key in _UWP_SHELL_COMMANDS:
            try:
                subprocess.Popen(_UWP_SHELL_COMMANDS[app_key], shell=True)
                # ⚠️ **«앞으로 가져왔습니다»라고 하지 않는다.** 포커스는 이미 실패했고
                #   여기서 하는 일은 **새로 띄우는 것**이다. 그리고 떴는지 확인한다 —
                #   확인 없이 성공을 보고하던 게 2026-09-09의 그 거짓말이다.
                return _launched_or_honest(app_key, name, eul_reul)
            except Exception:
                pass
        # 프로세스는 살아있지만 visible 창이 없음 (트레이 앱 등)
        # → exe 재실행하면 트레이 앱은 메인 창을 올려줌
        path = _resolve_path(app_key)
        if path:
            try:
                subprocess.Popen([path])
                return _launched_or_honest(app_key, name, eul_reul)
            except Exception:
                pass
        return f"⚠️ {name}은(는) 실행 중인데 창을 앞으로 못 가져왔어요. 작업표시줄/트레이에서 직접 클릭해 주세요."

    # ── UWP·내장 앱: shell 명령으로 직접 실행 ───────────────────
    if app_key in _UWP_SHELL_COMMANDS:
        try:
            subprocess.Popen(_UWP_SHELL_COMMANDS[app_key], shell=True)
            # UWP는 뜨는 데 몇 초 걸린다. 0.5초 자고 «실행했습니다»라고 하면
            # 사용자가 보기엔 아무 일도 안 일어난 채 성공 메시지만 뜬다.
            return _launched_or_honest(app_key, name, eul_reul)
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
            "⚠️ 파일 탐색기는 Windows 시스템 프로세스라 프로그램으로 닫을 수 없어요. "
            "창 우측 상단 ✕ 버튼으로 직접 닫아주세요. "
            "(열기는 가능합니다 — open_app 도구를 사용하세요)"
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

        # 여기 왔다는 건 프로세스는 있는데 보이는 창이 없다는 뜻이다.
        # (크롬처럼 창을 다 닫아도 백그라운드 프로세스가 남는 앱이 있다)
        # "실행 중인지 확인하세요"는 사실과 달라 사용자를 헷갈리게 하므로 정확히 말한다. (P3-3 정직 보고)
        return (f"⚠️ {app}은(는) 실행 중이지만 열려 있는 창이 없어요. "
                f"먼저 {app}을(를) 열어 주세요.")
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

        # 프로세스는 있는데 보이는 창이 없는 경우 — 정확히 보고한다. (P3-3 정직 보고)
        return (f"⚠️ {app}은(는) 실행 중이지만 열려 있는 창이 없어요. "
                f"먼저 {app}을(를) 열어 주세요.")
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
