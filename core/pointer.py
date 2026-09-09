"""화면 포인팅 — «표시가 지금 화면에 떠 있는가»를 아는 한 곳. (M4)

*"블루투스 어디 있어?"* → `point_at_element`가 화면 좌표에 고리를 그린다.
그리는 것은 Electron이 하고, **여기는 그 표시의 «수명»만 관리한다.**

## 왜 별도 모듈인가 — 두 곳이 이 상태를 봐야 한다

표시는 **전체 화면을 덮는 always-on-top 창**이라 스크린샷에 그대로 찍힌다.
그래서 상태를 모르면 두 기능이 동시에 깨진다(→ docs/design/M4_포인팅_확대.md §5):

  - **캡처 도구**(`take_screenshot` → `describe_screen`·`locate_ui_element`)
    캡처에 우리 고리가 들어가 Gemini가 그걸 화면의 일부로 읽는다.
    최악은 **자기가 그린 표시를 UI 요소로 되짚는** 것이다.
    → `clear_for_capture()`로 **먼저 치우고** 찍는다.

  - **화면 감시**(`core/screen_monitor`)
    프리필터가 로컬 픽셀 비교라 **오버레이가 뜨고 지는 것 자체가 «변화»** 다.
    거르지 않으면 우리가 우리를 감시하고, «변화가 있을 때만 화면을 내보낸다»는
    전송량 방어가 헛돈다.
    → 그 구간의 프레임을 **비교에서 제외하고 기준 프레임을 유지**한다.

🚨 **2026-09-09 정정.** 원래 설계는 「끝나기를 기다린다」였는데, 실기에서 한 턴에
   포인팅+화면설명이 같이 오자(계획 2단계) 8초가 통째로 지연에 얹혀 **턴이 28초**가
   됐다. 다시 띄우지 않으므로 «깜빡임이 변화로 잡힌다»는 걱정도 성립하지 않는다.
   자세한 근거는 `clear_for_capture()` 안에 있다.

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
    payload = {
        "type": "point",
        "rect": list(rect) if rect else None,
        "center": list(center) if center else None,
        "label": str(loc.get("label") or ""),
        "zoom": bool(zoom),
        "seconds": POINTER_SECONDS,
    }
    # 확대본(§6). **없으면 조용히 고리만 그린다** — 확대는 곁들이라서,
    # 못 만들었다고 포인팅 자체를 실패시키지 않는다.
    crop = loc.get("crop") if zoom else None
    if crop:
        payload["zoomImage"] = crop
    elif zoom:
        payload["zoom"] = False          # 그릴 게 없으면 «확대했다»고 하지 않는다
    return payload


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


def clear_for_capture(reason: str = "캡처") -> bool:
    """캡처 직전에 표시를 **치운다.** 이미 없으면 아무 일도 하지 않는다.

    반환값은 «치웠는가»(=표시가 떠 있었는가)다.

    🚨 **2026-09-09 정정 — 원래는 «사라지기를 기다렸다»(ADR §5).**
      실기에서 그 대가가 측정됐다: 한 턴에 `point_at_element`와 `describe_screen`이
      같이 들어가면(계획 2단계 — 흔한 조합이다) 캡처가 표시 8초를 **통째로 기다려**
      턴이 28초가 됐다. 그중 9초가 이 대기였다.

      ADR이 «지우지 말고 기다리라»고 한 근거는 *"지웠다 **다시 띄우면** 화면이
      깜빡이고 그 깜빡임이 또 감시의 변화로 잡힌다"* 였다. 그런데 **다시 띄우지
      않는다.** 그리고 감시의 기준 프레임은 표시 이전 화면 그대로다(표시 구간을
      건너뛰므로) — 지우고 나면 그 기준과 **같은 화면**이라 변화로 잡히지도 않는다.
      즉 기다릴 이유가 처음부터 없었고, 남는 건 지연뿐이었다.

    ⚠️ 사용자 눈에는 표시가 예정보다 일찍 사라진다. 그건 대가가 맞지만,
      캡처를 시킨 것 자체가 «지금 화면을 보여 달라»는 뜻이고 **우리 오버레이는
      그 화면의 일부가 아니다.**
    """
    if not is_visible():
        return False
    log.info("[Point] 캡처를 위해 표시를 먼저 치운다 | 사유=%s", reason)
    hide(reason)
    return True


def reset() -> None:
    """테스트용. 상태를 초기화한다(알림은 보내지 않는다)."""
    global _visible_until
    with _lock:
        _visible_until = 0.0
