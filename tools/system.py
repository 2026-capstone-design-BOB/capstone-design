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

from core.logger import get_logger

#: 설정이 **안 먹었을 때**를 셀 수 있게 한다 (감사 G-11). 예전엔 조용히 넘어갔다.
_log = get_logger("System")


# ── 🔑 이 파일의 규칙 — «맞췄다»와 «맞았다»는 다른 말이다 (감사 G-11) ──────
#
# 볼륨·밝기는 **설정한 값을 되읽을 수 있는 몇 안 되는 자리**다. 그런데 예전 코드는
# 실행 **전** 값만 읽고 `✓ 볼륨: 40% → 50%` 라고 답했다 — 뒤의 50%는 **의도이지
# 결과가 아니다.** 설정이 실패해도(pycaw 없음 · WMI 거부 · PowerShell 폴백 실패)
# 같은 문장이 나갔다.
#
# 그래서 세 가지를 나눠 말한다:
#   ✓ 되읽었고 맞다        → `✓ 볼륨: 40% → 50%`  (50%는 **읽은 값**이다)
#   ✓ 됐지만 못 읽는 PC다  → `✓ … (확인은 못 했어요)`  ← 실패가 아니다. 모르는 것이다
#   ⚠️ 되읽었는데 다르다   → `⚠️ …로 맞추려 했는데 지금 …%입니다`
#
# ⚠️ **«못 읽는다»를 실패(✗·⚠️)로 만들지 말 것.** 그러면 읽기가 안 되는 PC에서
#   볼륨 명령이 통째로 «실패»가 되어 [캐시 학습](../core/command_cache.py)에서
#   빠지고, 매번 LLM 을 타게 된다. 모르는 것은 모른다고만 한다.
#
# 📏 되읽기 허용 오차. 모니터·사운드 장치가 **단계로 반올림**하는 경우가 있다.
_SETTING_TOLERANCE = 2


# ── 볼륨 ─────────────────────────────────────────────────────────

def _endpoint_volume():
    """스피커의 볼륨 인터페이스. 못 얻으면 `None`.

    🚨 **2026-09-19 — pycaw 의 API 가 굴러갔다.** 예전 pycaw 는
    `AudioUtilities.GetSpeakers()` 가 COM 장치를 그대로 줘서 `.Activate(...)` 로
    인터페이스를 꺼냈는데, **지금 버전(20251023)은 `AudioDevice` 래퍼를 준다** —
    `.Activate` 가 아예 없고 `.EndpointVolume` 프로퍼티가 대신 있다.

    그래서 이 PC 에서 볼륨이 **계속 «못 읽음»(-1)** 이었다. [BL-57](../docs/BACKLOG.md)
    (모델 별칭이 굴러가 모든 명령이 죽었다)과 **같은 모양**이다 — 우리 코드는 한 줄도
    안 바뀌었는데 밖이 움직였다.

    🔑 **두 API 를 다 받는다.** 버전을 못 박는 것보다 싸고, 어느 쪽이든 도는 편이
      «이 PC 에서만 된다»를 안 만든다.
    """
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        dev = AudioUtilities.GetSpeakers()
        ep = getattr(dev, "EndpointVolume", None)       # 새 API (20251023~)
        if ep is not None:
            return ep
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        interface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))   # 옛 API
    except Exception as e:                                    # noqa: BLE001
        # ⚠️ 여기가 조용하면 «이 PC 는 볼륨을 못 읽는다»가 **이유 없이** 굳는다.
        #   실제로 그렇게 굳어 있었다 — 2026-09-19에 읽기 점검을 돌려서야 드러났다.
        _log.warning("[볼륨] 인터페이스를 못 얻었다 (키보드 시늉으로 간다) | %s: %s",
                     type(e).__name__, e)
        return None


def _get_volume() -> int:
    """현재 볼륨(0-100) 반환. 못 읽으면 -1."""
    ep = _endpoint_volume()
    if ep is None:
        return -1
    try:
        return int(ep.GetMasterVolumeLevelScalar() * 100)
    except Exception:                                         # noqa: BLE001
        return -1


def _set_volume_level(level: int) -> bool:
    """볼륨을 0-100 사이 값으로 설정.

    Returns:
        **정확한 값으로 설정했는가.** 키보드 시뮬레이션 폴백은 `False` 다 —
        2단계씩 눌러 맞추는 것이라 목표값에 닿았는지 이 함수는 모른다.
        🚨 예전에는 **항상 `True`** 였다(감사 G-11).
    """
    level = max(0, min(100, level))
    ep = _endpoint_volume()
    if ep is not None:
        try:
            ep.SetMasterVolumeLevelScalar(level / 100, None)
            return True
        except Exception as e:                                # noqa: BLE001
            _log.warning("[볼륨] 설정 실패 → 키보드 폴백 | %s: %s",
                         type(e).__name__, e)

    # keybd_event fallback: 0으로 내린 후 목표까지 올리기 (volume_up/down과 동일 방식)
    # WScript.Shell SendKeys는 미디어 키를 지원하지 않으므로 직접 keybd_event 사용
    for _ in range(50):
        ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)  # VK_VOLUME_DOWN
        ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
    for _ in range(level // 2):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)  # VK_VOLUME_UP
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
    return False              # 눌렀을 뿐이다. 맞았는지는 모른다


def _readback(what: str, before: int, target: int, read, *,
              eul_reul: str) -> str:
    """설정한 **뒤** 다시 읽고, 본 대로 말한다. (감사 G-11)

    `close_app` 의 `_await_gone()` · `open_app` 의 `_await_window()` 와 같은 자리다 —
    이 저장소가 아홉 번 고친 «확인하지 않고 의도를 보고한다»를 **설정 쪽**에서 막는다.
    """
    actual = read()
    if actual < 0:
        # 읽을 수 없는 PC. **모르는 것이지 실패가 아니다** — ✓ 를 유지하되 말을 보탠다.
        return f"✓ {what}{eul_reul} {target}%로 맞췄어요. (이 PC는 값을 읽지 못해 확인은 못 했어요)"
    if abs(actual - target) <= _SETTING_TOLERANCE:
        if before < 0:                 # 전 값을 못 읽었다 — 화살표로 말하지 않는다
            return f"✓ {what}{eul_reul} {actual}%로 맞췄어요."
        return f"✓ {what}: {before}% → {actual}%"
    _log.warning("[%s] 설정=%d%% ↔ 되읽기=%d%% (이전 %d%%)", what, target, actual, before)
    return (f"⚠️ {what}{eul_reul} {target}%로 맞추려 했는데 지금 {actual}%입니다. "
            f"다시 해볼까요?")


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
        return "✓ 볼륨을 올렸어요. (이 PC는 볼륨을 읽지 못해 확인은 못 했어요)"

    new_level = min(100, current + amount)
    _set_volume_level(new_level)
    return _readback("볼륨", current, new_level, _get_volume, eul_reul="을")


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
        return "✓ 볼륨을 내렸어요. (이 PC는 볼륨을 읽지 못해 확인은 못 했어요)"

    new_level = max(0, current - amount)
    _set_volume_level(new_level)
    return _readback("볼륨", current, new_level, _get_volume, eul_reul="을")


@tool
def set_volume(level: int) -> str:
    """
    볼륨을 특정 값으로 설정합니다.
    level: 0-100 사이의 볼륨 값
    """
    if not 0 <= level <= 100:
        return f"✗ 볼륨은 0에서 100 사이 값이어야 합니다. (입력: {level})"
    before = _get_volume()
    _set_volume_level(level)
    # 🚨 여기는 예전에 **되읽기조차 없었다.** 설정을 못 해도 «설정했습니다»가 나갔다.
    return _readback("볼륨", before, level, _get_volume, eul_reul="을")


def _get_mute() -> int:
    """음소거 상태. 1=음소거 · 0=아님 · -1=읽을 수 없음."""
    ep = _endpoint_volume()
    if ep is None:
        return -1
    try:
        return int(bool(ep.GetMute()))
    except Exception:                                         # noqa: BLE001
        return -1


@tool
def mute_toggle() -> str:
    """볼륨을 음소거하거나 음소거를 해제합니다."""
    # 🚨 «전환했습니다»도 의도였다 (감사 G-11과 같은 자리). 키를 눌렀을 뿐이고,
    #   상태가 정말 바뀌었는지는 보지 않았다. 볼륨과 달리 여기는 **어느 쪽이
    #   됐는지**가 사용자에게 중요하다 — «껐어요»와 «켰어요»는 반대말이다.
    before = _get_mute()
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)  # VK_VOLUME_MUTE
    ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
    after = _get_mute()
    if before < 0 or after < 0:
        return "✓ 음소거 키를 눌렀어요. (이 PC는 상태를 읽지 못해 확인은 못 했어요)"
    if after == before:
        _log.warning("[음소거] 눌렀는데 상태가 그대로다 (%d)", before)
        return "⚠️ 음소거 키를 눌렀는데 상태가 그대로예요. 다시 해볼까요?"
    return "✓ 음소거했어요." if after else "✓ 음소거를 해제했어요."


# ── 밝기 ─────────────────────────────────────────────────────────

#: 우리가 **마지막으로 설정한** 밝기. WMI 읽기가 안 되는 PC를 위한 기억이다.
#
# 🚨 **왜 필요한가 (2026-09-11 3차 실기).** 사용자 지적:
#   *"밝기 조절은 세기가 되게 확확 바뀌어서 조금 불편해."*
#   당시 이 PC에서 `_get_brightness()`가 **-1**(읽기 실패)이었다. 그러면 예전 코드는
#   상대 조절을 포기하고 **절대값으로 점프**했다 — 올리면 70, 내리면 30.
#   즉 «올려/내려»를 번갈아 하면 **70 ↔ 30을 왕복**한다. **한 번에 40%**다.
#   사용자가 본 응답이 `✓ 밝기를 올렸습니다.`(퍼센트가 없다)인 것이 그 증거다 —
#   읽기가 됐다면 `✓ 밝기: 50% → 60%`가 나왔을 것이다.
#
# 🔑 **읽을 수 없으면 «우리가 쓴 값»을 기억하면 된다.** 처음 한 번만 중앙값에서
#   출발하고, 그 뒤로는 10%씩 움직인다 — 읽기가 되는 PC와 같은 체감이 된다.
# ⚠️ 사용자가 키보드 밝기 키로 직접 바꾸면 이 기억은 어긋난다. 그건 받아들인다 —
#   **40% 점프보다는 낫고**, 읽기가 되는 PC에서는 애초에 이 경로를 타지 않는다.
#
# 🔎 **2026-09-12 정정 (BL-47).** 「읽기 실패」의 원인은 하드웨어가 아니라
#   **`wmi` 모듈 미설치**였다. 깔고 나니 이 PC도 읽는다(`40%`). 그래서 지금 이 기억은
#   **상시 경로가 아니라 진짜 폴백**이다 — 아래 `_brightness_base()`가 실제 값을 먼저 본다.
#   ⚠️ 그렇다고 이 폴백을 지우지 말 것. 읽기가 정말 안 되는 PC가 있고,
#   `requirements.txt`가 `wmi`를 요구하지만 설치가 깨질 수도 있다.
_last_brightness: "int | None" = None

#: 읽지도 못하고 기억도 없을 때의 출발점. 양쪽으로 움직일 여지를 남긴다.
_BRIGHTNESS_FALLBACK_START = 50


def _get_brightness() -> int:
    """현재 밝기(0-100) 반환. WMI 사용."""
    try:
        import wmi
        c = wmi.WMI(namespace="wmi")
        monitor = c.WmiMonitorBrightness()[0]
        return monitor.CurrentBrightness
    except Exception:
        return -1


def _brightness_base() -> int:
    """조절의 기준값 — 읽을 수 있으면 실제값, 아니면 **마지막으로 쓴 값**."""
    current = _get_brightness()
    if current >= 0:
        return current
    if _last_brightness is not None:
        return _last_brightness
    return _BRIGHTNESS_FALLBACK_START


def _set_brightness(level: int) -> bool:
    """밝기 설정. WMI 사용.

    Returns:
        **설정이 받아들여졌는가** (감사 G-11). 예전에는 아무것도 안 돌려줬고,
        PowerShell 폴백의 **종료코드도 보지 않았다** — 그래서 밝기가 안 바뀌어도
        `✓ 밝기: 40% → 50%` 가 그대로 나갔다.
    """
    global _last_brightness
    level = max(0, min(100, level))
    try:
        import wmi
        c = wmi.WMI(namespace="wmi")
        methods = c.WmiMonitorBrightnessMethods()[0]
        methods.WmiSetBrightness(level, 0)
        _last_brightness = level      # 읽기가 안 되는 PC를 위해 기억해 둔다
        return True
    except Exception as e:                                    # noqa: BLE001
        _log.warning("[밝기] WMI 설정 실패 → PowerShell 폴백 | %s: %s",
                     type(e).__name__, e)

    # PowerShell fallback
    try:
        p = subprocess.run(
            ["powershell", "-Command",
             f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"],
            capture_output=True, timeout=10
        )
    except Exception as e:                                    # noqa: BLE001
        _log.error("[밝기] PowerShell 폴백 실행 실패 | %s: %s", type(e).__name__, e)
        return False
    # 🔑 종료코드만 보면 안 된다. PowerShell 은 **비종료 오류**(개체가 null 이라
    #   메서드를 못 부르는 경우)에도 0 으로 끝난다 — 그게 이 폴백의 흔한 실패 모양이다.
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    if p.returncode != 0 or err:
        _log.error("[밝기] PowerShell 폴백 실패 | 종료코드=%s | %s",
                   p.returncode, err[:200])
        return False
    # 🚨 **실패했으면 기억하지 않는다.** 기억해 버리면 다음 «밝기 올려»가
    #   «안 먹은 값»을 기준으로 움직여, 한 번 실패한 뒤로 계속 어긋난다.
    _last_brightness = level
    return True


@tool
def brightness_up(amount: int = 10) -> str:
    """
    화면 밝기를 올립니다.
    amount: 올릴 양 (1-100, 기본 10)
    """
    current = _brightness_base()
    new_level = min(100, current + amount)
    if new_level == current:
        return f"⚠️ 이미 가장 밝아요 ({current}%)."
    if not _set_brightness(new_level):
        return "⚠️ 밝기를 바꾸지 못했어요. 이 PC가 밝기 조절을 지원하지 않을 수 있어요."
    return _readback("밝기", current, new_level, _get_brightness, eul_reul="를")


@tool
def brightness_down(amount: int = 10) -> str:
    """
    화면 밝기를 내립니다.
    amount: 내릴 양 (1-100, 기본 10)
    """
    current = _brightness_base()
    new_level = max(0, current - amount)
    if new_level == current:
        return f"⚠️ 이미 가장 어두워요 ({current}%)."
    if not _set_brightness(new_level):
        return "⚠️ 밝기를 바꾸지 못했어요. 이 PC가 밝기 조절을 지원하지 않을 수 있어요."
    return _readback("밝기", current, new_level, _get_brightness, eul_reul="를")


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
