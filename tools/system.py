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

    # PowerShell fallback (pycaw 실패 시)
    try:
        ps = (
            f"$wsh = New-Object -ComObject WScript.Shell; "
            f"1..50 | ForEach-Object {{ $wsh.SendKeys([char]174) }}; "   # 볼륨 0으로
            f"1..{level // 2} | ForEach-Object {{ $wsh.SendKeys([char]175) }}"  # 목표치까지 올리기
        )
        subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=8)
        return True
    except Exception:
        pass

    return False


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

@tool
def take_screenshot(save_path: str = "") -> str:
    """
    화면을 캡처합니다.
    save_path: 저장 경로 (비워두면 바탕화면에 자동 저장)
    """
    if not save_path:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(desktop, f"screenshot_{timestamp}.png")

    try:
        import PIL.ImageGrab
        img = PIL.ImageGrab.grab()
        img.save(save_path)
        return f"✓ 스크린샷을 저장했습니다.\n경로: {save_path}"
    except ImportError:
        # Pillow 없을 때 PowerShell fallback
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
