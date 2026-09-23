"""
화면 변화 모니터링 — 감시 엔진 (Phase 2 마지막 항목)
====================================================
*"오류 뜨면 알려줘"* — 턴이 끝난 뒤에도 화면을 지켜보다가 **먼저 말을 건다.**

보기(`describe_screen`) → 찾기(`find_ui_element`) → 누르기(`click_ui_element`)에 이어
Phase 2를 닫는 항목이다. → docs/ROADMAP.md

## 왜 이 파일이 core/에 있나

루프·상한·판정·중단 조건은 **정책 로직**이다. 캡처와 Vision은 전부 **주입받는다**
(`core/graph.py`가 llm·tools·security_check를 주입받는 것과 같은 방식).
그래서 Windows도 API 키도 없이 mock으로 전부 검증할 수 있다.

⚠️ **PIL·Win32·langchain을 모듈 최상단에서 import 하지 말 것.**
CI mock 잡은 langgraph와 langchain-core만 설치한다(`core/auth.py`가 stdlib만 쓰는 것과
같은 제약). 프로덕션 의존성은 함수 안에서 lazy import 한다.

## ⚠️ 개인정보 (OWASP LLM02) — 이 기능이 지금까지 중 전송량이 가장 크다

주기적 캡처는 **화면을 계속 외부 LLM으로 보내는** 일이다. 그래서 두 겹으로 줄인다.

1. **픽셀 차이로 먼저 거른다.** 5초마다 찍는 건 전부 로컬에서 끝난다(전송 0, 비용 0).
   32×32 그레이스케일로 줄여 비교하고, **변화가 있을 때만** Vision을 부른다.
2. **상한이 곧 전송량 상한이다.** 최대 10분 · Vision 20회. 둘 중 먼저 닿는 쪽에서
   자동 종료한다. 캡처를 몇 번 했든 밖으로 나가는 건 최대 20장이다.

## 정직성 규칙 — 이 기능에서 특히 중요하다

이 프로젝트가 반복해서 데인 것은 **확인하지 않고 됐다고 말하는 것**이다
(BL-12 · BL-15 · `visual_verify` 첫 판본). 감시는 **사용자가 보고 있지 않을 때**
도는 기능이라 그 위험이 더 크다. 그래서:

- **조용히 끝나지 않는다.** 상한 도달·캡처 실패·판독 실패 — 어떤 이유로 멈추든
  사용자에게 알린다. 말없이 사라지면 사용자는 아직 지켜보는 줄 안다.
- **증거 없는 감지는 알리지 않는다.** Vision이 `detected: true`라고만 하고 무엇을
  봤는지 말하지 못하면 그건 감지가 아니다.
- **Vision의 말을 그대로 옮긴다.** 요약하거나 바꿔 말하지 않는다.
- **놓쳤을 가능성을 숨기지 않는다.** 종료 알림에 화면을 몇 번 봤는지 함께 적는다.
- **판정을 정규식으로 하지 않는다.** 손으로 쓴 정규식이 이 프로젝트를 반복해서
  무너뜨렸다(BL-02 · BL-15 · HITL 승인 무한루프). Vision에게 불리언 하나를 JSON으로
  받고, 못 믿을 답이면 **알리지 않는 쪽**으로 기운다.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from core.logger import get_logger

log = get_logger("Monitor")


# ── 변화 판정 상수 ────────────────────────────────────────────────
#
# 서명은 32×32 = 1024셀 그레이스케일이다. 왜 이 크기인가 —
# 더 크면 시계 초침·커서 깜빡임 같은 잡음이 살아남고, 더 작으면 대화상자가 묻힌다.
SIGNATURE_SIDE = 32
SIGNATURE_CELLS = SIGNATURE_SIDE * SIGNATURE_SIDE

# 한 셀이 "바뀌었다"고 볼 밝기 차이(0~255).
_CELL_DELTA = 12

# 바뀐 셀이 전체의 이 비율을 넘으면 **화면이 바뀐 것**으로 본다.
#
# ⚠️ 평균 차이가 아니라 **셀 비율**을 쓴다. 평균은 화면 일부의 큰 변화가 전체 면적에
#    나눠지며 묻힌다.
#
# 2026-09-07 — 2%에서 1%로 낮췄다. 실기에서 *"메모장 지켜보다가 글자 생기면 알려줘"* 가
# 2분 21초 동안 **Vision 0회**로 끝났다. 감시는 정상으로 돌았고 프리필터가
# 타이핑을 변화로 보지 않은 것이다. 1000x700 창을 그려 재봤다(셀 1024개 기준):
#
#     커서 1개 깜빡임      2셀  0.20%   ← 잡으면 안 되는 것
#     상태표시줄 시계      1셀  0.10%   ←
#     글자 한 줄(12자)    13셀  1.27%   ← 잡아야 하는 것
#     글자 두 줄          21셀  2.05%
#     대화상자           140셀 13.70%
#
# 2%는 **한 줄을 통째로 놓치는** 자리였다(대화상자 기준으로 잡혀 있었다).
# 1%면 한 줄(1.27%)이 걸리고 커서(0.20%)와는 6배가 벌어진다.
#
# ⚠️ **글자 1~2자(0.29%)는 여전히 못 잡는다.** 커서 깜빡임(0.20%)과 구분되지 않아
#    구조적으로 불가능하다 — 더 낮추면 커서를 변화로 보고 Vision을 계속 부른다.
#    프리필터는 '거를' 뿐이고 최종 판정은 Vision이 하므로, 오탐이 늘어도
#    `SCREEN_WATCH_MAX_VISION_CALLS`(기본 20)가 전송량 상한을 유지한다.
_CHANGED_RATIO = 0.01

# 변화를 감지한 뒤 Vision에 보낼 프레임을 다시 찍기까지 기다리는 시간.
# 창이 열리는 애니메이션 중간 프레임을 보내면 Vision이 헛것을 본다.
_SETTLE_SECONDS = 1.0

# 연속 실패 상한 — 이만큼 이어지면 멈추고 사유를 알린다.
_MAX_CAPTURE_FAILURES = 3      # 창이 닫혔거나 최소화됐다
_MAX_UNPARSEABLE = 3           # Vision이 계속 알아들을 수 없는 답을 한다

# 기본값. 실제 값은 config/settings.py 에서 오고 `.env`로 바꿀 수 있다.
DEFAULT_INTERVAL = 5           # 초
DEFAULT_MAX_MINUTES = 10
DEFAULT_MAX_VISION_CALLS = 20

# 종료 사유. `stopped`만 사용자가 직접 시킨 것이라 푸시 알림을 보내지 않는다
# (도구 응답으로 이미 알고 있다). 나머지는 **전부 알린다.**
REASON_DETECTED = "detected"
REASON_TIMEOUT = "timeout"
REASON_BUDGET = "budget"
REASON_CAPTURE_FAILED = "capture_failed"
REASON_UNREADABLE = "unreadable"
REASON_STOPPED = "stopped"


def signature_changed(before, after) -> bool:
    """두 서명 사이에 **의미 있는 변화**가 있는가.

    길이가 다르면(창 크기 변경 등) 변화로 본다 — 비교할 수 없는 것을 "같다"고
    하면 그때부터 영영 아무것도 감지하지 못한다.
    """
    if not before or not after:
        return False
    if len(before) != len(after):
        return True
    changed = sum(1 for a, b in zip(before, after) if abs(a - b) > _CELL_DELTA)
    return (changed / len(before)) > _CHANGED_RATIO


class ScreenMonitor:
    """화면을 주기적으로 보고 변화가 있으면 Vision에 물어보는 감시 스레드.

    **동시에 하나만 돈다.** 여러 개가 쌓이면 전송량 상한이 개수만큼 곱해진다.

    Args:
        capture_signature(window) -> Optional[tuple[int, ...]]:
            화면을 32×32 그레이스케일로 줄인 값. `None`이면 캡처 실패
            (창이 닫혔거나 최소화됐다).
        vision_check(window, what) -> dict:
            화면을 실제로 보고 판정한다. 반환 규약:
              {"ok": bool, "detected": bool, "detail": str, "reason": str}
            `ok`가 False면 **응답을 해석하지 못한 것**이다(알리지 않는다).
        notify(message, reason) -> None:
            사용자에게 밀어넣을 알림. 감시 스레드에서 호출된다.
        on_state(active, what) -> None:
            감시 시작/종료 상태 변화(UI 배지용). 선택적.
        config_provider() -> dict:
            `{"enabled", "interval", "max_minutes", "max_vision_calls"}`.
            **시작할 때마다** 호출한다 — `.env`를 고쳐도 재시작 없이 반영된다.
        sleep(seconds), now() -> float:
            테스트용 주입점. 기본은 중단 신호에 즉시 깨는 `Event.wait`.
    """

    def __init__(
        self, *,
        capture_signature: Callable[[str], Optional[Any]],
        vision_check: Callable[[str, str], dict],
        notify: Callable[[str, str], None],
        on_state: Optional[Callable[[bool, str], None]] = None,
        config_provider: Optional[Callable[[], dict]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        now: Callable[[], float] = time.monotonic,
        pointer_visible: Optional[Callable[[], bool]] = None,
    ):
        self._capture = capture_signature
        self._vision = vision_check
        self._notify = notify
        # 포인팅 표시(M4)가 화면에 떠 있는지. **None이면 항상 False** —
        # mock 테스트와 포인팅 없는 환경에서 지금까지와 똑같이 돈다.
        self._pointer_visible = pointer_visible or (lambda: False)
        self._on_state = on_state
        self._config_provider = config_provider or (lambda: {})
        self._sleep_fn = sleep
        self._now = now

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 현재 세션 상태 (감시 중이 아니면 what이 빈 문자열)
        self._what = ""
        self._window = ""
        self._vision_calls = 0
        self._started_at = 0.0
        self._cfg: dict = {}

    # ── 설정 ──────────────────────────────────────────────────────
    def _load_config(self) -> dict:
        raw = {}
        try:
            raw = self._config_provider() or {}
        except Exception as e:
            log.warning("설정을 읽지 못해 기본값을 씁니다: %s: %s", type(e).__name__, e)

        def _int(key, default, lo, hi):
            try:
                return max(lo, min(hi, int(raw.get(key, default))))
            except Exception:
                return default

        return {
            "enabled": bool(raw.get("enabled", True)),
            # 1초보다 짧으면 캡처가 CPU를 먹고, 5분보다 길면 감시라고 할 수 없다
            "interval": _int("interval", DEFAULT_INTERVAL, 1, 300),
            "max_minutes": _int("max_minutes", DEFAULT_MAX_MINUTES, 1, 120),
            # ⚠️ 이 값이 곧 **외부로 나가는 화면 장수의 상한**이다
            "max_vision_calls": _int("max_vision_calls", DEFAULT_MAX_VISION_CALLS, 1, 200),
        }

    # ── 공개 API ──────────────────────────────────────────────────
    def is_active(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive())

    def status(self) -> dict:
        """지금 무엇을 지켜보고 있는지. 감시 중이 아니면 `active: False`."""
        if not self.is_active():
            return {"active": False}
        return {
            "active": True,
            "what": self._what,
            "window": self._window,
            "vision_calls": self._vision_calls,
            "elapsed": round(self._now() - self._started_at, 1),
            **self._cfg,
        }

    def start(self, what: str, window: str = "") -> dict:
        """감시를 시작한다.

        반환: `{"started": bool, "reason": str, ...설정값}`.
        `started`가 False면 **아무것도 시작하지 않았다** — 호출부는 그 사실을
        사용자에게 그대로 전해야 한다. (시작하지 않았는데 시작했다고 말하는 것이
        이 프로젝트가 반복해서 저지른 결함이다)
        """
        what = (what or "").strip()
        window = (window or "").strip()
        if not what:
            return {"started": False, "reason": "no_target"}

        cfg = self._load_config()
        if not cfg["enabled"]:
            return {"started": False, "reason": "disabled", **cfg}

        with self._lock:
            if self.is_active():
                # 이미 돌고 있으면 **새로 시작하지 않는다.** 두 개가 돌면 상한이 두 배가 된다.
                return {"started": False, "reason": "already_watching",
                        "what": self._what, "window": self._window, **cfg}

            self._stop_event = threading.Event()
            self._what = what
            self._window = window
            self._vision_calls = 0
            self._started_at = self._now()
            self._cfg = cfg

            self._thread = threading.Thread(
                target=self._run, name="pluiz-screen-monitor", daemon=True)
            self._thread.start()

        log.info("감시 시작 | 대상=%r | 창=%s | %d초 간격 · 최대 %d분 · Vision %d회",
                 what, window or "전체화면", cfg["interval"],
                 cfg["max_minutes"], cfg["max_vision_calls"])
        self._emit_state(True, what)
        return {"started": True, "what": what, "window": window, **cfg}

    def stop(self) -> dict:
        """사용자 요청으로 감시를 중단한다. 감시 중이 아니면 `stopped: False`."""
        with self._lock:
            if not self.is_active():
                return {"stopped": False}
            what, window = self._what, self._window
            calls = self._vision_calls
            self._stop_event.set()
            thread = self._thread

        # 루프가 sleep 중이면 Event.wait가 즉시 깨어 종료한다.
        # 붙잡혀 있어도(Vision 호출 중) 사용자를 기다리게 하지 않는다 — 짧게만 기다린다.
        if thread is not None:
            thread.join(timeout=2.0)
        log.info("감시 중단(사용자 요청) | 대상=%r | Vision %d회", what, calls)
        return {"stopped": True, "what": what, "window": window, "vision_calls": calls}

    # ── 내부 ──────────────────────────────────────────────────────
    def _sleep(self, seconds: float) -> None:
        """중단 신호에 **즉시 깨는** 대기. 주입되면 그걸 쓴다(테스트용 가짜 시계)."""
        if self._sleep_fn is not None:
            self._sleep_fn(seconds)
        else:
            self._stop_event.wait(seconds)

    def _emit_state(self, active: bool, what: str) -> None:
        if self._on_state is None:
            return
        try:
            self._on_state(active, what)
        except Exception as e:
            log.warning("상태 알림 실패(무시): %s: %s", type(e).__name__, e)

    def _finish(self, reason: str, detail: str = "") -> None:
        """감시를 마치고 **사용자에게 알린다.**

        ⚠️ `stopped`(사용자가 직접 멈춤)를 뺀 모든 종료는 알림을 보낸다.
          말없이 사라지면 사용자는 아직 지켜보는 줄 안다 — 이 기능이 고치려는
          바로 그 문제(확인 안 하고 넘어가기)를 스스로 저지르는 꼴이다.
        """
        what, calls = self._what, self._vision_calls
        log.info("감시 종료 | 사유=%s | 대상=%r | Vision %d회", reason, what, calls)

        if reason != REASON_STOPPED:
            try:
                self._notify(self._build_message(reason, detail), reason)
            except Exception as e:
                log.exception("알림 전달 실패: %s", e)

        self._what = ""
        self._window = ""
        self._emit_state(False, what)

    def _build_message(self, reason: str, detail: str) -> str:
        """알림 문구. **Vision의 말을 그대로 옮기고 요약하지 않는다.**"""
        what = self._what
        where = f"'{self._window}' 창에서 " if self._window else ""
        calls = self._vision_calls
        minutes = self._cfg.get("max_minutes", DEFAULT_MAX_MINUTES)

        if reason == REASON_DETECTED:
            return (f"👁 {where}'{what}'을(를) 봤어요.\n{detail}\n"
                    "— 화면을 보고 판단한 거라 직접 확인해 주세요. 감시는 여기서 멈출게요.")
        if reason == REASON_TIMEOUT:
            return (f"👁 {minutes}분 동안 {where}'{what}'을(를) 지켜봤지만 못 봤어요. "
                    f"(화면 확인 {calls}회) 감시를 멈출게요.")
        if reason == REASON_BUDGET:
            return (f"👁 화면 확인 {calls}회를 다 써서 '{what}' 감시를 멈췄어요. "
                    "그때까지는 못 봤어요. 계속 보려면 다시 말씀해 주세요.")
        if reason == REASON_CAPTURE_FAILED:
            target = f"'{self._window}' 창" if self._window else "화면"
            return (f"👁 {target}을(를) 볼 수 없어서 '{what}' 감시를 멈췄어요. "
                    "창이 닫혔거나 최소화된 것 같아요.")
        if reason == REASON_UNREADABLE:
            return (f"👁 화면을 제대로 읽지 못해서 '{what}' 감시를 멈췄어요. "
                    f"(화면 확인 {calls}회)")
        return f"👁 '{what}' 감시를 멈췄어요."

    def _run(self) -> None:
        """감시 루프. 예외가 나도 **알리고** 끝낸다 — 조용히 죽지 않는다."""
        try:
            self._loop()
        except Exception as e:
            log.exception("감시 루프 오류")
            try:
                self._notify(f"👁 '{self._what}' 감시 중 문제가 생겨 멈췄어요: "
                             f"{type(e).__name__}", REASON_CAPTURE_FAILED)
            except Exception:
                pass
            self._what = ""
            self._window = ""
            self._emit_state(False, "")

    def _loop(self) -> None:
        cfg = self._cfg
        interval = cfg["interval"]
        deadline = self._started_at + cfg["max_minutes"] * 60
        budget = cfg["max_vision_calls"]

        baseline = None
        capture_fails = 0
        unparseable = 0

        while True:
            if self._stop_event.is_set():
                self._finish(REASON_STOPPED)
                return
            if self._now() >= deadline:
                self._finish(REASON_TIMEOUT)
                return
            if self._vision_calls >= budget:
                self._finish(REASON_BUDGET)
                return

            # ── 포인팅 표시 구간은 **비교에서 제외한다** (M4 ADR §5) ──
            # 오버레이는 전체화면 always-on-top이라 프리필터의 로컬 픽셀 비교에
            # **변화로 잡힌다.** 거르지 않으면 우리가 우리를 감시하고,
            # «변화가 있을 때만 화면을 내보낸다»는 전송량 방어가 헛돈다.
            # ⚠️ **baseline을 갱신하지 않고 넘긴다.** 오버레이가 낀 프레임을
            #   기준으로 삼으면 **사라질 때 또 변화로 잡힌다** — 한 번 새는 게
            #   아니라 뜰 때와 질 때 두 번 샌다.
            if self._pointer_visible():
                log.debug("[Monitor] 포인팅 표시 중 — 이 프레임은 건너뛴다")
                self._sleep(interval)
                continue

            sig = self._safe_capture()
            if sig is None:
                capture_fails += 1
                if capture_fails >= _MAX_CAPTURE_FAILURES:
                    self._finish(REASON_CAPTURE_FAILED)
                    return
                self._sleep(interval)
                continue
            capture_fails = 0

            if baseline is None:
                # 첫 프레임은 기준일 뿐이다. 여기서 Vision을 부르면 감시가 아니라
                # 그냥 화면 설명이 된다.
                baseline = sig
                self._sleep(interval)
                continue

            if not signature_changed(baseline, sig):
                self._sleep(interval)
                continue

            # ── 여기서부터가 외부 전송 구간 ────────────────────────
            # 창이 열리는 애니메이션 중간을 찍지 않도록 잠깐 기다렸다 다시 본다.
            self._sleep(_SETTLE_SECONDS)
            if self._stop_event.is_set():
                self._finish(REASON_STOPPED)
                return
            settled = self._safe_capture()
            if settled is not None:
                sig = settled

            self._vision_calls += 1
            log.info("변화 감지 → 화면 확인 %d/%d회", self._vision_calls, budget)
            res = self._safe_vision()

            # Vision 호출은 몇 초가 걸린다. 그 사이 사용자가 "그만 봐"라고 했으면
            # 그 뜻이 우선이다. 여기서 알림을 보내면 방금 "멈췄어요"라고 답한 것과
            # 어긋나는 말이 뒤늦게 도착한다.
            if self._stop_event.is_set():
                self._finish(REASON_STOPPED)
                return

            if not res.get("ok"):
                # 해석하지 못한 답으로는 **아무것도 알리지 않는다.**
                unparseable += 1
                log.warning("화면 판독 실패 %d/%d: %s",
                            unparseable, _MAX_UNPARSEABLE, res.get("reason", ""))
                if unparseable >= _MAX_UNPARSEABLE:
                    self._finish(REASON_UNREADABLE)
                    return
                baseline = sig
                self._sleep(interval)
                continue
            unparseable = 0

            detail = str(res.get("detail") or "").strip()
            if res.get("detected") and detail:
                self._finish(REASON_DETECTED, detail)
                return
            if res.get("detected"):
                # **증거 없는 감지는 감지가 아니다.** 무엇을 봤는지 말하지 못하는
                # true 하나로 사용자를 부르면, 확인하지 않고 됐다고 말하는 것과 같다.
                log.warning("감지라고 했으나 근거가 비어 있어 무시함")

            baseline = sig
            self._sleep(interval)

    def _safe_capture(self):
        try:
            sig = self._capture(self._window)
        except Exception as e:
            log.warning("캡처 실패: %s: %s", type(e).__name__, e)
            return None
        if not sig:
            return None
        return sig

    def _safe_vision(self) -> dict:
        try:
            res = self._vision(self._window, self._what)
        except Exception as e:
            log.exception("화면 확인 호출 실패")
            return {"ok": False, "detected": False, "detail": "",
                    "reason": f"{type(e).__name__}: {e}"}
        if not isinstance(res, dict):
            return {"ok": False, "detected": False, "detail": "",
                    "reason": "판정 결과 형식이 올바르지 않아요"}
        return res


# ── 알림 채널 ──────────────────────────────────────────────────────
#
# 감시 스레드는 턴이 끝난 뒤에 돌기 때문에 **응답으로 돌려줄 곳이 없다.**
# 서버(main.py)가 기동할 때 여기에 콜백을 심어, 열려 있는 /ws로 밀어넣는다.
# 서버 없이 도는 테스트에서는 콜백이 없고, 그때는 로그에만 남는다.

_notifier: Optional[Callable[[dict], None]] = None


def set_notifier(fn: Optional[Callable[[dict], None]]) -> None:
    """UI 푸시 콜백 등록. 인자는 그대로 WebSocket으로 나갈 payload dict다."""
    global _notifier
    _notifier = fn


def _dispatch(payload: dict) -> None:
    if _notifier is None:
        # 알림은 놓치면 곤란하니 경고로, 배지용 상태 변화는 조용히 남긴다.
        if payload.get("type") == "notify":
            log.warning("알림을 전달할 UI가 없어요(서버 미기동): %s",
                        payload.get("text"))
        else:
            log.debug("UI가 없어 상태 알림 생략: %s", payload)
        return
    try:
        _notifier(payload)
    except Exception as e:
        log.exception("알림 전달 실패: %s", e)


def _prod_notify(message: str, reason: str) -> None:
    _dispatch({"type": "notify", "text": message, "reason": reason})


def _prod_state(active: bool, what: str) -> None:
    _dispatch({"type": "watch_state", "active": bool(active), "what": what})


# ── 프로덕션 의존성 (lazy — CI에는 PIL도 API 키도 없다) ────────────
def _prod_capture(window: str):
    from tools.vision import screen_signature
    return screen_signature(window)


def _prod_vision(window: str, what: str) -> dict:
    from tools.vision import vision_watch_check
    return vision_watch_check(window, what)


def _prod_pointer_visible() -> bool:
    from core.pointer import is_visible
    return is_visible()


def _prod_config() -> dict:
    """시작할 때마다 `.env`를 다시 읽는다 (`get_settings`는 `@lru_cache`다 — 절대규칙 4)."""
    from config.settings import get_settings
    s = get_settings()
    return {
        "enabled": s.screen_watch_enabled,
        "interval": s.screen_watch_interval,
        "max_minutes": s.screen_watch_max_minutes,
        "max_vision_calls": s.screen_watch_max_vision_calls,
    }


# ── 싱글톤 ─────────────────────────────────────────────────────────
_instance: Optional[ScreenMonitor] = None


def get_monitor() -> ScreenMonitor:
    global _instance
    if _instance is None:
        _instance = ScreenMonitor(
            capture_signature=_prod_capture,
            pointer_visible=_prod_pointer_visible,
            vision_check=_prod_vision,
            notify=_prod_notify,
            on_state=_prod_state,
            config_provider=_prod_config,
        )
    return _instance


def reset_monitor() -> None:
    """감시를 멈추고 싱글톤을 버린다. (서버 종료 · 테스트)"""
    global _instance
    if _instance is not None:
        try:
            _instance.stop()
        except Exception:
            pass
    _instance = None
