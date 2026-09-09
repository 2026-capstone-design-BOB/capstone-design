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

# 캡처 대상 지정어. "활성창"·"현재창" 등은 지금 포커스된 창을 뜻한다.
_ACTIVE_WINDOW_WORDS = {"활성창", "현재창", "지금창", "포커스", "active"}


def window_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    """창의 **화면 좌표** 사각형 (left, top, width, height).

    ⚠️ `_capture_hwnd`가 캡처하는 영역과 **반드시 같아야 한다.** 그래서 한 곳에만 둔다.
      캡처 이미지의 (0,0)이 화면의 (left, top)이라는 관계가 여기서 나오고,
      Vision이 찾은 좌표를 화면 좌표로 되돌릴 때 그 관계를 쓴다.
      따로 구현하면 좌표가 조용히 어긋난다 — 클릭이 엉뚱한 데를 누른다.
    """
    import ctypes, ctypes.wintypes

    # DWM 실제 표시 영역 (그림자 제외) — DWMWA_EXTENDED_FRAME_BOUNDS = 9
    rect = ctypes.wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)
    ) != 0:
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        raise ValueError("창 크기가 유효하지 않습니다")
    return (rect.left, rect.top, w, h)


def resolve_window_hwnd(window: str) -> tuple[int, str]:
    """캡처 대상 문자열 → (hwnd, 표시용 이름). 못 찾으면 (0, 이름).

    `take_screenshot`과 좌표 계산이 **같은 창을 가리키도록** 한 곳에 둔다.
    """
    import ctypes

    if window.lower() in _ACTIVE_WINDOW_WORDS:
        return (ctypes.windll.user32.GetForegroundWindow(), "활성 창")
    from tools.app_control import find_hwnd_for_app
    return (find_hwnd_for_app(window), window)


def capture_origin(window: str = "") -> tuple[int, int]:
    """캡처 이미지의 (0,0)이 화면의 어느 좌표인지. 전체화면이면 (0, 0).

    Vision이 이미지 안에서 찾은 위치를 **화면 좌표**로 옮길 때 쓴다.
    """
    if not window:
        return (0, 0)
    hwnd, _label = resolve_window_hwnd(window)
    if not hwnd:
        raise ValueError(f"'{window}' 창을 찾을 수 없습니다")
    left, top, _w, _h = window_screen_rect(hwnd)
    return (left, top)


def ensure_window_ready(window: str, launch: bool = True) -> dict:
    """포인팅·탐색 **전에** 창을 «볼 수 있는 상태»로 만든다.

    반환 `{"ok", "action", "label", "reason"}`.
    `action`은 `""` · `"launched"` · `"restored"` · `"fronted"` 중 하나다.

    ## 왜 필요한가 (2026-09-09 사용자 요청)

    *"뭔가를 시각적으로 해달라고 한 거니까, 실행 중이지 않으면 실행하겠다고 한 다음에
    표시해 주든지, 최소화된 상태라면 다시 앞으로 가져온 뒤에 조치를 취해야 할 것 같은데"*

    맞는 말이다. 지금은 창이 없거나 최소화면 **«찾지 못했습니다»** 로 끝나는데,
    그건 사실이지만 **도움이 안 된다** — 사용자가 원한 건 «화면에서 보는 것»이고,
    보이지 않는 이유가 «없어서»가 아니라 **«가려져서»** 일 때가 많다.

    ⚠️ **`take_screenshot`과 다르다.** 그쪽은 찍고 **다시 최소화**한다(한 장 찍는 게
      목적이라 사용자를 방해하지 않는 게 맞다). 포인팅은 **사용자가 그 창을 볼 것**이
      목적이므로 **앞에 남겨 둔다.**

    ⚠️ **클릭 경로에는 쓰지 않는다.** 승인 질문은 «클릭»에 대해 물은 것이지
      «앱을 실행»에 대해 물은 게 아니다. 승인받은 범위를 넘기지 않는다.
    """
    import ctypes
    import time as _t

    out = {"ok": True, "action": "", "label": window, "reason": ""}
    if not window:
        return out                      # 전체화면 — 만들 상태가 없다

    u = ctypes.windll.user32
    hwnd, label = resolve_window_hwnd(window)
    out["label"] = label or window

    # ① 창이 없다 → 열어 준다 (사용자가 «실행하겠다고 한 다음에»라고 했다)
    if not hwnd:
        if not launch:
            out.update(ok=False, reason=f"'{window}' 창을 찾을 수 없습니다")
            return out
        try:
            from tools.app_control import open_app
            open_app.invoke({"app": window})
        except Exception as e:
            out.update(ok=False, reason=f"'{window}'을(를) 열지 못했습니다: {e}")
            return out
        # 창이 뜰 때까지 잠깐 기다린다. 바로 캡처하면 흰 화면을 찍는다.
        for _ in range(20):             # 최대 4초
            _t.sleep(0.2)
            hwnd, label = resolve_window_hwnd(window)
            if hwnd:
                break
        if not hwnd:
            out.update(ok=False, reason=f"'{window}'을(를) 열었지만 창이 나타나지 않았습니다")
            return out
        out.update(action="launched", label=label or window)
        _t.sleep(0.6)                   # 첫 렌더가 끝나도록
        return out

    # ② 최소화돼 있다 → 되살린다 (그리고 **다시 최소화하지 않는다**)
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)           # SW_RESTORE
        _t.sleep(0.4)
        out["action"] = "restored"

    # ③ 뒤에 있다 → 앞으로. 실패해도 진행한다 —
    #    Windows가 포그라운드 전환을 거부하는 경우가 있는데(다른 앱이 활성),
    #    그때도 창은 보이므로 캡처와 표시는 된다.
    try:
        if u.GetForegroundWindow() != hwnd:
            u.SetForegroundWindow(hwnd)
            _t.sleep(0.25)
            if not out["action"]:
                out["action"] = "fronted"
    except Exception:
        pass
    return out


def _capture_hwnd(hwnd: int):
    """
    PrintWindow API로 HWND 창 픽셀만 캡처. PIL Image(RGB) 반환.
    - DWM 그림자/배경 없이 창 내용만 정확히 추출
    - PW_RENDERFULLCONTENT(=2) 플래그로 Chrome 등 GPU 렌더링 앱도 지원
    """
    import ctypes, ctypes.wintypes
    from PIL import Image

    _left, _top, w, h = window_screen_rect(hwnd)

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

    # ⚠️ 포인팅 표시(M4)가 화면에 떠 있으면 **그것까지 찍힌다.** 전체화면
    #   always-on-top 오버레이라서다. 그대로 찍으면 Gemini가 우리 고리를 화면의
    #   일부로 읽고, 최악은 **자기가 그린 표시를 UI 요소로 되짚는** 것이다.
    #   **치우고 찍는다.** (2026-09-09 정정: 원래는 «사라지기를 기다렸다»인데,
    #   한 턴에 포인팅+화면설명이 같이 오면 8초를 통째로 기다려 턴이 28초가 됐다.
    #   다시 띄우지 않으므로 감시가 «변화»로 잡을 것도 없다 → core/pointer.py)
    #   → docs/design/M4_포인팅_확대.md §5
    try:
        from core.pointer import clear_for_capture
        clear_for_capture("take_screenshot")
    except Exception:
        pass          # 포인팅이 없는 환경(테스트·CI)에서도 캡처는 되어야 한다

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

        # ── HWND 획득 (좌표 계산과 같은 해석기를 쓴다) ────────────
        try:
            hwnd, label = resolve_window_hwnd(window)
        except Exception as import_err:
            return f"✗ 앱 창 조회 실패: {import_err}"

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
    # ⚠️ **여기서 앱 목록을 따로 갖지 않는다.** 예전에는 이 함수가 자기만의
    #   12개짜리 화이트리스트를 들고 있었고 거기에 **계산기가 없었다.** 그래서
    #   2026-09-07 실기에서 계산기를 열어 둔 채 물었더니
    #   *"계산기는 지금 실행 중인 앱 목록에 없네요"* 라고 답했다.
    #   `wt.exe`도 실제 프로세스명이 `WindowsTerminal.exe`라 못 잡고 있었다.
    #   `open_app`이 **열 수 있는** 앱을 `get_running_apps`가 **모르는** 상태였다 —
    #   같은 사실이 두 곳에 있어 한쪽만 갱신된, 이 프로젝트가 반복해서 데인 모양이다.
    #   그래서 단일 출처인 `APP_PROCESS_MAP` 하나만 본다.
    from tools.app_control import APP_PROCESS_MAP, APP_DISPLAY_NAMES

    running: set[str] = set()
    for proc in psutil.process_iter(["name"]):
        name = (proc.info or {}).get("name")
        if name:                  # 죽는 중인 프로세스는 이름이 없을 수 있다
            running.add(name.lower())

    found = [APP_DISPLAY_NAMES.get(key, key)
             for key, exes in APP_PROCESS_MAP.items()
             if any(exe.lower() in running for exe in exes)]

    # ⚠️ 마지막 줄(tail)을 빼지 말 것 — 이 목록은 **Pluiz가 아는 앱만** 본다.
    #   없으면 모델이 *"…만 실행 중이에요"* 라고 단정한다(실기에서 실제로 그랬다).
    #   확인하지 않은 것을 확인한 것처럼 말하지 않는다.
    tail = ("\n(이 목록에 없는 앱도 켜져 있을 수 있어요 — "
            "Pluiz가 아는 앱만 확인합니다.)")
    if found:
        return ("✓ 실행 중인 앱:\n"
                + "\n".join(f"  • {app}" for app in found) + tail)
    return "✓ Pluiz가 아는 앱 중에는 실행 중인 것이 없습니다." + tail
