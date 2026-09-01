"""
시스템 제어 도구
볼륨 / 밝기 / 스크린샷 / 배터리 / 시간 / 실행 앱 목록
"""

import os
import subprocess
import ctypes
import time
from datetime import datetime
from langchain_core.tools import tool
import psutil


# ── 볼륨 ─────────────────────────────────────────────────────────

def _get_volume() -> int:
    """현재 볼륨(0-100) 반환."""
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        return int(volume.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        return -1


def _set_volume_level(level: int):
    """볼륨을 0-100 사이 값으로 설정."""
    level = max(0, min(100, level))
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(level / 100, None)
        return True
    except Exception:
        pass

    # keybd_event fallback: 0으로 내린 후 목표까지 올리기 (volume_up/down과 동일 방식)
    # WScript.Shell SendKeys는 미디어 키를 지원하지 않으므로 직접 keybd_event 사용
    for _ in range(50):
        ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)  # VK_VOLUME_DOWN
        ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
    for _ in range(level // 2):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)  # VK_VOLUME_UP
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
    return True


@tool
def volume_up(amount: int = 10) -> str:
    """
    볼륨을 올립니다.
    amount: 올릴 양 (1-100, 기본 10)
    """
    current = _get_volume()
    if current < 0:
        # pycaw 없을 시 키보드 시뮬레이션
        for _ in range(max(1, amount // 2)):
            ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)  # VK_VOLUME_UP
            ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
        return f"✓ 볼륨을 올렸습니다."

    new_level = min(100, current + amount)
    _set_volume_level(new_level)
    return f"✓ 볼륨: {current}% → {new_level}%"


@tool
def volume_down(amount: int = 10) -> str:
    """
    볼륨을 내립니다.
    amount: 내릴 양 (1-100, 기본 10)
    """
    current = _get_volume()
    if current < 0:
        for _ in range(max(1, amount // 2)):
            ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)  # VK_VOLUME_DOWN
            ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
        return f"✓ 볼륨을 내렸습니다."

    new_level = max(0, current - amount)
    _set_volume_level(new_level)
    return f"✓ 볼륨: {current}% → {new_level}%"


@tool
def set_volume(level: int) -> str:
    """
    볼륨을 특정 값으로 설정합니다.
    level: 0-100 사이의 볼륨 값
    """
    if not 0 <= level <= 100:
        return f"✗ 볼륨은 0에서 100 사이 값이어야 합니다. (입력: {level})"
    _set_volume_level(level)
    return f"✓ 볼륨을 {level}%로 설정했습니다."


@tool
def mute_toggle() -> str:
    """볼륨을 음소거하거나 음소거를 해제합니다."""
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)  # VK_VOLUME_MUTE
    ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
    return "✓ 음소거 상태를 전환했습니다."


# ── 밝기 ─────────────────────────────────────────────────────────

def _get_brightness() -> int:
    """현재 밝기(0-100) 반환. WMI 사용."""
    try:
        import wmi
        c = wmi.WMI(namespace="wmi")
        monitor = c.WmiMonitorBrightness()[0]
        return monitor.CurrentBrightness
    except Exception:
        return -1


def _set_brightness(level: int):
    """밝기 설정. WMI 사용."""
    level = max(0, min(100, level))
    try:
        import wmi
        c = wmi.WMI(namespace="wmi")
        methods = c.WmiMonitorBrightnessMethods()[0]
        methods.WmiSetBrightness(level, 0)
    except Exception:
        # PowerShell fallback
        subprocess.run(
            ["powershell", "-Command",
             f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"],
            capture_output=True
        )


@tool
def brightness_up(amount: int = 10) -> str:
    """
    화면 밝기를 올립니다.
    amount: 올릴 양 (1-100, 기본 10)
    """
    current = _get_brightness()
    if current < 0:
        _set_brightness(70)
        return "✓ 밝기를 올렸습니다."
    new_level = min(100, current + amount)
    _set_brightness(new_level)
    return f"✓ 밝기: {current}% → {new_level}%"


@tool
def brightness_down(amount: int = 10) -> str:
    """
    화면 밝기를 내립니다.
    amount: 내릴 양 (1-100, 기본 10)
    """
    current = _get_brightness()
    if current < 0:
        _set_brightness(30)
        return "✓ 밝기를 내렸습니다."
    new_level = max(0, current - amount)
    _set_brightness(new_level)
    return f"✓ 밝기: {current}% → {new_level}%"


# ── 시스템 정보 ───────────────────────────────────────────────────

def _capture_hwnd(hwnd: int):
    """
    PrintWindow API로 HWND 창 픽셀만 캡처. PIL Image(RGB) 반환.
    - DWM 그림자/배경 없이 창 내용만 정확히 추출
    - PW_RENDERFULLCONTENT(=2) 플래그로 Chrome 등 GPU 렌더링 앱도 지원
    """
    import ctypes, ctypes.wintypes
    from PIL import Image

    # DWM 실제 표시 영역 (그림자 제외) — DWMWA_EXTENDED_FRAME_BOUNDS = 9
    rect = ctypes.wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)
    ) != 0:
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

    w = rect.right  - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        raise ValueError("창 크기가 유효하지 않습니다")

    # GDI DC + 비트맵 생성
    hdc_src = ctypes.windll.user32.GetWindowDC(hwnd)
    hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_src)
    hbmp    = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc_src, w, h)
    ctypes.windll.gdi32.SelectObject(hdc_mem, hbmp)

    # PrintWindow (PW_RENDERFULLCONTENT = 2)
    ctypes.windll.user32.PrintWindow(hwnd, hdc_mem, 2)

    # BITMAPINFOHEADER 설정
    class _BIH(ctypes.Structure):
        _fields_ = [
            ('biSize',          ctypes.c_uint32),
            ('biWidth',         ctypes.c_int32),
            ('biHeight',        ctypes.c_int32),
            ('biPlanes',        ctypes.c_uint16),
            ('biBitCount',      ctypes.c_uint16),
            ('biCompression',   ctypes.c_uint32),
            ('biSizeImage',     ctypes.c_uint32),
            ('biXPelsPerMeter', ctypes.c_int32),
            ('biYPelsPerMeter', ctypes.c_int32),
            ('biClrUsed',       ctypes.c_uint32),
            ('biClrImportant',  ctypes.c_uint32),
        ]

    bih = _BIH()
    bih.biSize     = ctypes.sizeof(_BIH)
    bih.biWidth    = w
    bih.biHeight   = -h   # top-down
    bih.biPlanes   = 1
    bih.biBitCount = 32
    bih.biCompression = 0  # BI_RGB

    buf = (ctypes.c_byte * (4 * w * h))()
    ctypes.windll.gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bih), 0)

    # GDI 자원 해제
    ctypes.windll.gdi32.DeleteObject(hbmp)
    ctypes.windll.gdi32.DeleteDC(hdc_mem)
    ctypes.windll.user32.ReleaseDC(hwnd, hdc_src)

    # BGRA → RGB PIL Image
    return Image.frombuffer('RGBA', (w, h), bytes(buf), 'raw', 'BGRA', 0, 1).convert('RGB')


@tool
def take_screenshot(save_path: str = "", window: str = "") -> str:
    """
    화면을 캡처하여 저장합니다.
    save_path: 저장 경로 (비워두면 바탕화면에 자동 저장)
    window: 캡처 대상 — 비워두면 전체 화면 / "활성창"이면 현재 포커스 창 / 앱 이름이면 해당 창만
            예: window="chrome", window="메모장", window="활성창"
    """
    import ctypes
    import ctypes.wintypes

    if not save_path:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{window.replace(' ', '_')}" if window else ""
        save_path = os.path.join(desktop, f"screenshot{suffix}_{timestamp}.png")

    try:
        import PIL.ImageGrab

        # ── 전체 화면 ────────────────────────────────────────────
        if not window:
            img = PIL.ImageGrab.grab()
            img.save(save_path)
            return f"✓ 전체 화면 스크린샷을 저장했습니다.\n경로: {save_path}"

        # ── HWND 획득 ────────────────────────────────────────────
        _ACTIVE = {"활성창", "현재창", "지금창", "포커스", "active"}
        if window.lower() in _ACTIVE:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            label = "활성 창"
        else:
            try:
                from tools.app_control import find_hwnd_for_app
                hwnd = find_hwnd_for_app(window)
            except Exception as import_err:
                return f"✗ 앱 창 조회 실패: {import_err}"
            label = window

        if not hwnd:
            return f"✗ '{window}' 창을 찾을 수 없습니다. 앱이 실행 중인지 확인해주세요."

        # ── 최소화 상태면 잠깐 복원 후 캡처, 이후 재최소화 ────────
        was_minimized = bool(ctypes.windll.user32.IsIconic(hwnd))
        if was_minimized:
            ctypes.windll.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            import time; time.sleep(0.4)

        img = _capture_hwnd(hwnd)
        img.save(save_path)

        if was_minimized:
            ctypes.windll.user32.ShowWindow(hwnd, 6)   # SW_MINIMIZE

        note = " (최소화 상태에서 잠깐 복원 후 촬영)" if was_minimized else ""
        return f"✓ '{label}' 창 스크린샷을 저장했습니다{note}.\n경로: {save_path}"

    except ImportError:
        if window:
            return "✗ 창별 스크린샷은 Pillow가 필요합니다. (pip install pillow)"
        ps_cmd = (
            f'Add-Type -AssemblyName System.Windows.Forms; '
            f'$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; '
            f'$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; '
            f'$g = [System.Drawing.Graphics]::FromImage($bmp); '
            f'$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); '
            f'$bmp.Save("{save_path.replace(chr(92), "/")}")'
        )
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)
        return f"✓ 스크린샷을 저장했습니다.\n경로: {save_path}"
    except Exception as e:
        return f"✗ 스크린샷 실패: {e}"


@tool
def get_battery_status() -> str:
    """현재 배터리 상태(잔량, 충전 여부)를 확인합니다."""
    battery = psutil.sensors_battery()
    if battery is None:
        return "✗ 배터리 정보를 가져올 수 없습니다. (데스크탑이거나 드라이버 문제)"

    percent = battery.percent
    charging = battery.power_plugged
    secs_left = battery.secsleft

    status = "충전 중" if charging else "배터리 사용 중"
    if secs_left > 0 and not charging:
        hours, remainder = divmod(secs_left, 3600)
        minutes = remainder // 60
        time_left = f", 잔여 시간: 약 {hours}시간 {minutes}분"
    else:
        time_left = ""

    return f"✓ 배터리: {percent:.0f}% ({status}{time_left})"


@tool
def get_current_time() -> str:
    """현재 날짜와 시간을 알려줍니다."""
    now = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays[now.weekday()]
    return (
        f"✓ 현재 시각: {now.year}년 {now.month}월 {now.day}일 ({weekday}요일) "
        f"{now.hour:02d}시 {now.minute:02d}분"
    )


@tool
def get_running_apps() -> str:
    """현재 실행 중인 주요 앱 목록을 반환합니다."""
    known = {
        "chrome.exe": "Google Chrome",
        "msedge.exe": "Microsoft Edge",
        "firefox.exe": "Firefox",
        "notepad.exe": "메모장",
        "code.exe": "VS Code",
        "kakaotalk.exe": "카카오톡",
        "winword.exe": "Microsoft Word",
        "excel.exe": "Microsoft Excel",
        "powerpnt.exe": "PowerPoint",
        "explorer.exe": "파일 탐색기",
        "wt.exe": "Windows Terminal",
    }

    running_names = {p.name().lower() for p in psutil.process_iter(["name"])}
    found = [label for exe, label in known.items() if exe in running_names]

    if found:
        return "✓ 현재 실행 중인 앱:\n" + "\n".join(f"  • {app}" for app in found)
    return "✓ 현재 실행 중인 주요 앱이 없습니다."
