"""화면 포인팅 — «표시가 지금 화면에 떠 있는가»를 아는 한 곳. (M4)

*"블루투스 어디 있어?"* → `point_at_element`가 화면 좌표에 고리를 그린다.
그리는 것은 Electron이 하고, **여기는 그 표시의 «수명»만 관리한다.**

## 왜 별도 모듈인가 — 두 곳이 이 상태를 봐야 한다

표시는 **전체 화면을 덮는 always-on-top 창**이라 스크린샷에 그대로 찍힌다.
그래서 상태를 모르면 두 기능이 동시에 깨진다(→ docs/design/M4_포인팅_확대.md §5):

  - **캡처 도구**(`take_screenshot` → `describe_screen`·`locate_ui_element`)
    캡처에 우리 고리가 들어가 Gemini가 그걸 화면의 일부로 읽는다.
    최악은 **자기가 그린 표시를 UI 요소로 되짚는** 것이다.
    → `wait_until_clear()`로 **표시가 끝나기를 기다렸다** 찍는다.

  - **화면 감시**(`core/screen_monitor`)
    프리필터가 로컬 픽셀 비교라 **오버레이가 뜨고 지는 것 자체가 «변화»** 다.
    거르지 않으면 우리가 우리를 감시하고, «변화가 있을 때만 화면을 내보낸다»는
    전송량 방어가 헛돈다.
    → 그 구간의 프레임을 **비교에서 제외하고 기준 프레임을 유지**한다.

⚠️ 「지우고 찍는다」가 아니라 **「끝나기를 기다린다」**이다. 지웠다 다시 띄우면
   사용자 화면이 깜빡이고, 그 깜빡임이 또 변화로 잡힌다.

## 이 모듈은 아무것도 그리지 않는다

`_notifier`로 payload를 내보낼 뿐이고, 실제 창은 Electron이 만든다.
`screen_monitor`와 **같은 방식**이다(같은 WebSocket으로 나간다).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger("pluiz.pointer")

# 표시가 화면에 남는 시간. **자동 해제는 마지막 방어선이다** —
# always-on-top 전체화면 오버레이가 남으면 PC를 못 쓰게 만든다(ADR §4-2).
# 「사용자가 끄면 되니까」로 이 값을 없애지 말 것.
POINTER_SECONDS = 8.0

# 캡처가 표시를 기다리는 최대 시간. POINTER_SECONDS보다 **조금 길게** 둔다 —
# 같으면 경계에서 아슬아슬하게 못 기다리고 오버레이가 낀 화면을 찍는다.
CAPTURE_WAIT_MAX = POINTER_SECONDS + 1.0

_lock = threading.Lock()
_visible_until: float = 0.0          # time.monotonic() 기준. 0이면 표시 없음
_notifier: Optional[Callable[[dict], None]] = None


# ── 순수 함수 (테스트가 시계 없이 볼 수 있게) ──────────────────────
def point_payload(loc: Any, zoom: bool = False) -> Optional[dict]:
    """`locate_ui_element` 결과 → Electron에 보낼 payload. **못 찾았으면 None.**

    None이 이 함수의 핵심이다 — 못 찾았는데 오버레이를 띄우면
    «화면 어딘가에 있다»는 **틀린 인상**을 준다. 아무것도 그리지 않는 게 맞다.
    (ADR §4-3)

    좌표는 그대로 넘긴다. 여기서 보정하면 `click_ui_element`와 **다른 좌표**가
    되어, 같은 것을 가리키는 두 기능이 서로 다른 곳을 말하게 된다.
    """
    if not isinstance(loc, dict) or not loc.get("found"):
        return None
    rect = loc.get("rect")
    center = loc.get("center")
    if not rect and not center:
        return None
    return {
        "type": "point",
        "rect": list(rect) if rect else None,
        "center": list(center) if center else None,
        "label": str(loc.get("label") or ""),
        "zoom": bool(zoom),
        "seconds": POINTER_SECONDS,
    }


def remaining(now: Optional[float] = None, until: Optional[float] = None) -> float:
    """표시가 사라지기까지 남은 초. 이미 없으면 0.0. (시계를 주입받아 테스트한다)"""
    now = time.monotonic() if now is None else now
    until = _visible_until if until is None else until
    return max(0.0, until - now)


# ── 상태 ──────────────────────────────────────────────────────────
def set_notifier(fn: Optional[Callable[[dict], None]]) -> None:
    """UI 푸시 콜백 등록. `screen_monitor.set_notifier`와 같은 것을 넣는다."""
    global _notifier
    _notifier = fn


def _dispatch(payload: dict) -> None:
    if _notifier is None:
        log.debug("UI가 없어 표시 생략: %s", payload.get("type"))
        return
    try:
        _notifier(payload)
    except Exception as e:
        log.exception("표시 전달 실패: %s", e)


def is_visible() -> bool:
    """지금 화면에 표시가 떠 있는가."""
    with _lock:
        return remaining(until=_visible_until) > 0.0


def show(payload: dict) -> None:
    """표시를 띄운다. `payload`는 `point_payload()`가 만든 것."""
    global _visible_until
    seconds = float(payload.get("seconds") or POINTER_SECONDS)
    with _lock:
        _visible_until = time.monotonic() + seconds
    log.info("[Point] 표시 | %r | zoom=%s | %.0f초",
             payload.get("label"), payload.get("zoom"), seconds)
    _dispatch(payload)


def hide(reason: str = "") -> None:
    """표시를 즉시 지운다. **여러 번 불러도 안전하다.**

    다음 턴이 시작될 때(ADR §4-2 ②)와 포인팅을 연달아 할 때 쓴다 —
    안 지우면 두 번째 포인팅이 첫 번째가 사라지기를 8초 기다린다.
    """
    global _visible_until
    with _lock:
        was = remaining(until=_visible_until) > 0.0
        _visible_until = 0.0
    if was:
        log.info("[Point] 표시 해제 | 사유=%s", reason or "-")
        _dispatch({"type": "point_clear"})


def wait_until_clear(timeout: Optional[float] = None, poll: float = 0.1) -> bool:
    """표시가 사라질 때까지 기다린다. 안 떠 있으면 **즉시** True.

    반환값은 «깨끗한 화면인가»다. 시간이 다 돼도 안 사라졌으면 False —
    그때는 **찍긴 찍는다.** 캡처를 아예 포기하면 포인팅 때문에 다른 기능이
    죽는 것이고, 그건 이 기능이 감당할 대가가 아니다.
    ⚠️ 대신 로그를 남긴다. 조용히 오염된 화면을 내보내지 않는다.
    """
    timeout = CAPTURE_WAIT_MAX if timeout is None else timeout
    deadline = time.monotonic() + max(0.0, timeout)
    while is_visible():
        if time.monotonic() >= deadline:
            log.warning("[Point] 표시가 %.1f초 안에 안 사라져 그대로 캡처한다 "
                        "— 화면에 우리 표시가 찍힐 수 있다", timeout)
            return False
        time.sleep(poll)
    return True


def reset() -> None:
    """테스트용. 상태를 초기화한다(알림은 보내지 않는다)."""
    global _visible_until
    with _lock:
        _visible_until = 0.0
