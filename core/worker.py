"""
백그라운드 작업자 — 「나중에 말 걸겠다」는 약속의 목록
=====================================================
*"30분 뒤에 알려줘"* · *"메일 오면 알려줘"* · *"끝나면 알려줘"* —
**턴이 끝난 뒤에 일어나는 일**을 맡는 곳이다.

## 🚨 왜 그래프 «밖»인가 — 절대규칙 1과 정면으로 부딪히는 자리다

[피벗 제안](../docs/planning/피벗_제안_2026-09-21.md)이 *"`ToolNode` 를
`asyncio.create_task` 로 바꾸라"* 고 지시했는데, 그것이 **정확히 노드를 async 로
만드는 일**이고 LangGraph `interrupt`(사람 승인)는 sync 경로에서만 안정 동작한다.

**그래서 그래프는 기다리지 않는다.** 도구는 여기에 작업을 «얹고» sync 인 채로
즉시 끝난다. 승인 노드는 한 줄도 안 건드린다. 사용자가 보는 경험은 똑같다 —
*"백그라운드에서 할게요"*.

## 왜 이 파일이 core/ 에 있나

루프·상한·판정·중단 조건은 **정책 로직**이다. 시계·스레드·알림 통로는 전부
**주입받는다**(`core/screen_monitor.py` 와 같은 방식). 그래서 Windows 도 API 키도
없이 mock 으로 전부 검증할 수 있고, 테스트는 **진짜 시간을 안 쓴다.**

⚠️ **프로덕션 의존성을 모듈 최상단에서 import 하지 말 것.** CI mock 잡은
langgraph·langchain-core 만 설치한다. 함수 안에서 lazy import 한다.

## 정직성 규칙 — 감시(screen_monitor)에서 배운 것을 그대로 가져온다

이 기능은 **사용자가 보고 있지 않을 때** 돈다. 그래서 «확인하지 않고 됐다고
말하기»(BL-12 · BL-15)가 여기서 가장 위험하다.

- **조용히 끝나지 않는다.** 완료·실패·상한 — 어떤 이유로 끝나든 알린다.
  말없이 사라지면 사용자는 **아직 기다리는 줄 안다.**
- **약속을 «했다»고만 말하지 않는다.** 도구 문구가 *언제·몇 번·어떻게 멈추는지*를
  같이 말한다. 감시(`_watch_notice`)가 이미 그렇게 한다.
- **서버가 내려가면 약속도 사라진다.** 디스크에 저장하지 않는다 —
  🚨 **그래서 약속할 때 그 사실을 말한다.** 저장하는 척하는 것이 더 나쁘다.
- **못 지킨 약속을 성공으로 적지 않는다.** 확인 횟수·경과 시간을 알림에 함께 적는다.

## 상한이 곧 비용 상한이다

- 동시 약속 수(`max_jobs`) — 하나가 스레드 하나다.
- 되풀이 작업(메일 감시)은 **간격에 바닥이 있다**(기본 60초). 모델이 «5초마다»
  라고 해도 바닥까지만 내려간다 — API 할당량이 조용히 타는 것을 막는다.
- 되풀이 작업은 **시간 상한 · 확인 횟수 상한** 중 먼저 닿는 쪽에서 스스로 멈추고,
  멈췄다고 **알린다**.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from core.logger import get_logger

log = get_logger("Worker")


# ── 작업 종류 ──────────────────────────────────────────────────────
#: 한 번 깨어나 실행하고 끝난다. *"30분 뒤에 알려줘"* · *"끝나면 알려줘"*
KIND_ONCE = "once"
#: 주기적으로 확인하다가 **찾으면** 끝난다. *"메일 오면 알려줘"*
KIND_POLL = "poll"

# ── 종료 사유 ──────────────────────────────────────────────────────
REASON_DONE = "done"            # 할 일을 했다 / 찾던 것을 찾았다
REASON_FAILED = "failed"        # 도중에 터졌다
REASON_LIMIT = "limit"          # 시간·횟수 상한에 닿아 스스로 멈췄다
REASON_CANCELLED = "cancelled"  # 사용자가 그만두라고 했다 (알림 없음 — 본인이 시켰다)
REASON_SHUTDOWN = "shutdown"    # 서버가 내려간다

#: 끝났는데 **사용자에게 말해야 하는** 사유. `cancelled` 는 본인이 시킨 것이라 뺀다.
NOTIFY_REASONS = {REASON_DONE, REASON_FAILED, REASON_LIMIT}

# ── 기본 상한 ──────────────────────────────────────────────────────
DEFAULT_MAX_JOBS = 5
#: 스케줄러가 한 번 도는 간격(초). 이 값이 알림 시각의 오차 상한이다.
DEFAULT_TICK = 1.0
#: 알림을 이만큼 뒤로는 못 잡는다. 🚨 **서버가 그렇게 오래 안 산다** —
#: 지킬 수 없는 약속을 받아 두는 것이 거짓말이다.
DEFAULT_MAX_DELAY_MINUTES = 720          # 12시간
#: 되풀이 확인의 **바닥**. 모델이 더 짧게 불러도 여기까지만 내려간다.
DEFAULT_POLL_MIN_INTERVAL = 60
DEFAULT_POLL_MAX_MINUTES = 60
DEFAULT_POLL_MAX_CHECKS = 60


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


class Job:
    """약속 하나. **상태는 워커만 바꾼다** — 밖으로는 `snapshot()` 사본만 나간다."""

    __slots__ = ("id", "kind", "what", "run", "interval", "next_at", "created_at",
                 "expires_at", "max_checks", "checks", "running", "detail")

    def __init__(self, job_id: str, kind: str, what: str, run: Callable[[], Any],
                 next_at: float, created_at: float, interval: float = 0.0,
                 expires_at: Optional[float] = None, max_checks: int = 0,
                 detail: str = ""):
        self.id = job_id
        self.kind = kind
        self.what = what
        self.run = run
        self.interval = interval
        self.next_at = next_at
        self.created_at = created_at
        self.expires_at = expires_at
        self.max_checks = max_checks
        self.checks = 0
        self.running = False
        self.detail = detail

    def snapshot(self, now: float) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "what": self.what,
            "detail": self.detail,
            "checks": self.checks,
            "running": self.running,
            "seconds_left": max(0.0, self.next_at - now),
            "elapsed": max(0.0, now - self.created_at),
        }


class BackgroundWorker:
    """약속을 받아 두고 때가 되면 실행한 뒤 **사용자에게 말을 거는** 스케줄러.

    주입 인자 (전부 mock 가능):
        notify(text, reason, what) -> None:
            사용자에게 말을 건다. 프로덕션은 `/ws` 푸시 + TTS 로 나간다.
        on_state(count) -> None:
            약속 개수가 바뀔 때마다. UI 배지용. 없어도 된다.
        config_provider() -> dict:
            `{"enabled", "max_jobs", "tick"}`. **시작할 때마다 다시 읽는다**
            (`get_settings` 는 `@lru_cache` 다 — 절대규칙 4).
        clock() -> float: 지금(초). 기본 `time.monotonic`.
        sleep(sec) -> None: 기본 `time.sleep`.
        spawn(fn) -> None: 작업 실행 방법. 기본은 데몬 스레드.
            🔑 테스트는 **인라인 실행**을 넣어 스레드 없이 결정적으로 돈다.
    """

    def __init__(
        self,
        *,
        notify: Callable[[str, str, str], None],
        on_state: Optional[Callable[[int], None]] = None,
        config_provider: Optional[Callable[[], dict]] = None,
        clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        spawn: Optional[Callable[[Callable[[], None]], None]] = None,
        autostart: bool = True,
    ):
        self._notify = notify
        self._on_state = on_state
        self._config_provider = config_provider or (lambda: {})
        self._clock = clock or _default_clock
        self._sleep_fn = sleep or _default_sleep
        self._spawn = spawn or _default_spawn
        # 🔑 테스트는 스케줄러 스레드를 안 띄우고 `tick()` 으로 손수 민다.
        #   진짜 시간을 기다리지 않아야 «30분 뒤»를 검증할 수 있다.
        self._autostart = autostart

        self._lock = threading.RLock()
        self._jobs: Dict[str, Job] = {}
        self._seq = 0
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ── 설정 ───────────────────────────────────────────────────────
    def _load_config(self) -> dict:
        try:
            raw = self._config_provider() or {}
        except Exception as e:                                # noqa: BLE001
            log.warning("설정을 못 읽어 기본값을 씁니다: %s", e)
            raw = {}

        def _int(key, default, lo, hi):
            try:
                return _clamp(int(raw.get(key, default)), lo, hi)
            except (TypeError, ValueError):
                return default

        return {
            "enabled": bool(raw.get("enabled", True)),
            "max_jobs": _int("max_jobs", DEFAULT_MAX_JOBS, 1, 20),
            "tick": float(raw.get("tick", DEFAULT_TICK) or DEFAULT_TICK),
        }

    # ── 조회 ───────────────────────────────────────────────────────
    def count(self) -> int:
        with self._lock:
            return len(self._jobs)

    def jobs(self) -> List[dict]:
        """지금 잡혀 있는 약속들. 남은 시간이 가까운 것부터."""
        now = self._clock()
        with self._lock:
            items = [j.snapshot(now) for j in self._jobs.values()]
        items.sort(key=lambda d: d["seconds_left"])
        return items

    def status(self) -> dict:
        return {"count": self.count(), "running": self._thread is not None}

    # ── 등록 ───────────────────────────────────────────────────────
    def add(
        self,
        *,
        kind: str,
        what: str,
        run: Callable[[], Any],
        delay: float = 0.0,
        interval: float = 0.0,
        max_minutes: Optional[float] = None,
        max_checks: int = 0,
        detail: str = "",
    ) -> dict:
        """약속 하나를 잡는다.

        `run()` 의 계약 — 아래 셋 중 하나를 돌려준다:
            `str`                      → 그 문장으로 알리고 **끝난다**
            `{"done": True, "text":…}` → 같음
            `{"done": False, …}`       → 아직이다. `interval` 뒤에 **다시 부른다**
                                         (되풀이 작업만. 한 번짜리는 그래도 끝난다)

        🚨 `run()` 안에서 예외가 나면 **삼키지 않는다** — 실패했다고 알리고 끝낸다.
        조용히 사라지는 것이 이 기능이 고치려는 바로 그 문제다.

        반환: `{"added": bool, "id": str, "reason": str, ...}`
        """
        what = (what or "").strip()
        if not what:
            return {"added": False, "reason": "no_target"}

        cfg = self._load_config()
        if not cfg["enabled"]:
            return {"added": False, "reason": "disabled"}

        now = self._clock()
        delay = max(0.0, float(delay or 0.0))
        max_delay = DEFAULT_MAX_DELAY_MINUTES * 60
        if delay > max_delay:
            # 🚨 잘라서 몰래 받아 두지 않는다. 못 지킬 약속은 **거절**한다.
            return {"added": False, "reason": "too_far",
                    "max_minutes": DEFAULT_MAX_DELAY_MINUTES}

        if kind == KIND_POLL:
            interval = max(DEFAULT_POLL_MIN_INTERVAL, float(interval or 0.0))
            minutes = DEFAULT_POLL_MAX_MINUTES if max_minutes is None else max_minutes
            expires_at = now + max(1.0, float(minutes)) * 60
            checks_cap = int(max_checks or DEFAULT_POLL_MAX_CHECKS)
        else:
            interval = 0.0
            expires_at = None if max_minutes is None else now + float(max_minutes) * 60
            checks_cap = 0

        with self._lock:
            if len(self._jobs) >= cfg["max_jobs"]:
                # 🚨 **가장 오래된 것을 조용히 밀어내지 않는다.** 사용자가 잡아 둔
                #   약속을 우리가 지운 뒤 «했어요»라고 하는 셈이 된다.
                return {"added": False, "reason": "full",
                        "max_jobs": cfg["max_jobs"],
                        "jobs": [j.snapshot(now) for j in self._jobs.values()]}

            self._seq += 1
            job_id = f"job{self._seq}"
            self._jobs[job_id] = Job(
                job_id=job_id, kind=kind, what=what, run=run,
                next_at=now + delay, created_at=now, interval=interval,
                expires_at=expires_at, max_checks=checks_cap, detail=detail,
            )
            count = len(self._jobs)

        log.info("약속 등록 | %s | %s | %.0f초 뒤 | 총 %d건",
                 job_id, what, delay, count)
        self._emit_state(count)
        self._ensure_thread(cfg["tick"])
        return {"added": True, "id": job_id, "what": what, "delay": delay,
                "interval": interval, "count": count}

    # ── 취소 ───────────────────────────────────────────────────────
    def cancel(self, job_id: str = "", what: str = "") -> dict:
        """약속을 지운다. `job_id` 가 있으면 그것만, `what` 이면 문구가 맞는 것만,
        둘 다 비면 **전부**.

        ⚠️ 문구로 지울 때 **여럿이 맞으면 하나를 고르지 않는다** — 되묻게 한다.
        (`read_email` 이 같은 규칙을 진다: 고르는 순간 틀린 것을 지울 수 있다)
        """
        now = self._clock()
        with self._lock:
            if job_id:
                job = self._jobs.get(job_id)
                if job is None:
                    return {"cancelled": 0, "reason": "not_found"}
                targets = [job]
            elif what.strip():
                needle = what.strip().lower()
                targets = [j for j in self._jobs.values()
                           if needle in j.what.lower()]
                if not targets:
                    return {"cancelled": 0, "reason": "not_found"}
                if len(targets) > 1:
                    return {"cancelled": 0, "reason": "ambiguous",
                            "jobs": [j.snapshot(now) for j in targets]}
            else:
                targets = list(self._jobs.values())
                if not targets:
                    return {"cancelled": 0, "reason": "empty"}

            removed = []
            for job in targets:
                self._jobs.pop(job.id, None)
                removed.append(job.snapshot(now))
            count = len(self._jobs)

        log.info("약속 취소 | %d건 | 남은 %d건", len(removed), count)
        self._emit_state(count)
        return {"cancelled": len(removed), "jobs": removed, "count": count}

    def shutdown(self) -> int:
        """서버가 내려간다. 스케줄러를 멈추고 약속을 버린다.

        🚨 **여기서는 알리지 못한다** — 알림을 받을 UI 가 함께 내려가는 중이다.
        그래서 약속을 잡을 때 «서버를 닫으면 사라져요»를 **미리** 말해 둔다.
        """
        self._stop.set()
        with self._lock:
            n = len(self._jobs)
            pending = [j.what for j in self._jobs.values()]
            self._jobs.clear()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        if n:
            log.warning("서버 종료로 약속 %d건을 버립니다: %s", n, ", ".join(pending))
        self._emit_state(0)
        return n

    # ── 스케줄러 ───────────────────────────────────────────────────
    def _ensure_thread(self, tick: float) -> None:
        if not self._autostart:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, args=(tick,), daemon=True, name="pluiz-worker")
            self._thread.start()

    def _loop(self, tick: float) -> None:
        try:
            while not self._stop.is_set():
                self._tick_once()
                # 약속이 없으면 스레드를 놔 준다. 다음 `add` 가 다시 띄운다.
                # ⚠️ **판정과 반납을 같은 락 안에서** 한다 — 나눠 놓으면 그 틈에 들어온
                #   `add` 가 «살아 있는 스레드»를 보고 새로 안 띄우는데 이쪽은 그대로
                #   끝나서, **약속만 남고 돌 사람이 없는** 상태가 된다.
                with self._lock:
                    if not self._jobs:
                        self._thread = None
                        return
                self._sleep_fn(tick)
        except Exception as e:                                # noqa: BLE001
            log.exception("스케줄러가 멈췄습니다: %s", e)
            with self._lock:
                self._thread = None

    def tick(self) -> None:
        """한 번 돌린다. **테스트가 시간을 손으로 미는 입구다.**"""
        self._tick_once()

    def _tick_once(self) -> None:
        now = self._clock()
        due: List[Job] = []
        expired: List[Job] = []
        with self._lock:
            for job in list(self._jobs.values()):
                # 🚨 **돌고 있는 중이어도 상한은 건다.** 안 그러면 안 끝나는 작업
                #   하나가 «아직 하고 있겠지»인 채로 영원히 남는다 — 사용자는
                #   기다리는데 아무도 말을 안 거는 그 상태다.
                #   (버린 뒤 늦게 끝나면 `_execute` 가 조용히 접는다)
                if job.expires_at is not None and now >= job.expires_at:
                    expired.append(job)
                    continue
                if job.running:
                    continue
                if now >= job.next_at:
                    job.running = True
                    due.append(job)

        for job in expired:
            self._finish(job, REASON_LIMIT)
        for job in due:
            self._spawn(lambda j=job: self._execute(j))

    # ── 실행 ───────────────────────────────────────────────────────
    def _execute(self, job: Job) -> None:
        try:
            result = job.run()
        except Exception as e:                                # noqa: BLE001
            log.exception("약속 실행 실패 | %s | %s", job.id, e)
            self._finish(job, REASON_FAILED, detail=f"{type(e).__name__}")
            return

        done, text = _normalize(result, job.kind)

        with self._lock:
            if job.id not in self._jobs:
                # 도는 사이에 취소됐다. **알리지 않는다** — 사용자가 그만두랬다.
                return
            job.checks += 1
            job.running = False
            checks, cap = job.checks, job.max_checks

        if done:
            self._finish(job, REASON_DONE, text=text)
            return

        if cap and checks >= cap:
            self._finish(job, REASON_LIMIT)
            return

        now = self._clock()
        with self._lock:
            if job.id in self._jobs:
                job.next_at = now + job.interval

    def _finish(self, job: Job, reason: str, text: str = "", detail: str = "") -> None:
        with self._lock:
            existed = self._jobs.pop(job.id, None) is not None
            count = len(self._jobs)
        if not existed:
            return

        log.info("약속 종료 | %s | %s | 확인 %d회", job.id, reason, job.checks)
        self._emit_state(count)

        if reason not in NOTIFY_REASONS:
            return
        message = text.strip() if text and text.strip() else self._build_message(
            job, reason, detail)
        try:
            self._notify(message, reason, job.what)
        except Exception as e:                                # noqa: BLE001
            # 🚨 알림이 실패해도 **로그에는 남긴다.** 사용자가 못 들었다면
            #   적어도 어디엔가는 흔적이 있어야 한다.
            log.exception("알림 전달 실패 | %s | %s | 내용=%s", job.id, e, message)

    def _build_message(self, job: Job, reason: str, detail: str) -> str:
        what = job.what
        if reason == REASON_FAILED:
            tail = f" ({detail})" if detail else ""
            return (f"⚠️ '{what}' 을(를) 하다가 문제가 생겨서 멈췄어요{tail}. "
                    "다시 시켜 주시겠어요?")
        if reason == REASON_LIMIT:
            mins = max(1, int(round((self._clock() - job.created_at) / 60)))
            if job.kind == KIND_POLL:
                # 🚨 «없었어요»라고 하지 않는다. **못 본 것과 없는 것은 다르다.**
                return (f"⏹ '{what}' 은(는) {mins}분 동안 {job.checks}번 확인했는데 "
                        "아직 소식이 없어서 그만 봤어요. 계속 보려면 다시 말씀해 주세요.")
            return (f"⏹ '{what}' 이(가) {mins}분이 지나도 안 끝나서 멈췄어요.")
        return f"🔔 '{what}'"

    # ── 상태 배지 ──────────────────────────────────────────────────
    def _emit_state(self, count: int) -> None:
        if self._on_state is None:
            return
        try:
            self._on_state(count)
        except Exception as e:                                # noqa: BLE001
            log.debug("상태 알림 실패: %s", e)


def _normalize(result: Any, kind: str) -> tuple:
    """`run()` 이 돌려준 것을 `(done, text)` 로 맞춘다.

    🔑 **한 번짜리 작업은 무엇을 돌려주든 끝난다.** `done: False` 를 인정하면
      한 번 하기로 한 일이 무한히 되풀이될 수 있다 — 되풀이는 `KIND_POLL` 의 일이다.
    """
    if isinstance(result, dict):
        done = bool(result.get("done", True))
        text = str(result.get("text", "") or "")
    else:
        done = True
        text = "" if result is None else str(result)
    if kind != KIND_POLL:
        done = True
    return done, text


# ── 프로덕션 기본 구현 ─────────────────────────────────────────────
def _default_clock() -> float:
    import time
    return time.monotonic()


def _default_sleep(seconds: float) -> None:
    import time
    time.sleep(seconds)


def _default_spawn(fn: Callable[[], None]) -> None:
    """작업 하나를 **자기 스레드에서** 돌린다.

    🔑 스케줄러 스레드에서 직접 부르면 오래 걸리는 작업 하나가 **다른 모든
      약속을 멈춰 세운다** — 30분 알림이 리서치 뒤로 밀린다.
    """
    threading.Thread(target=fn, daemon=True, name="pluiz-job").start()


# ── UI 로 나가는 통로 ──────────────────────────────────────────────
#
# 🔑 **새 채널을 만들지 않는다.** 화면 감시(`screen_monitor`)와 포인팅(`pointer`)이
#   이미 쓰는 `{"type": "notify"}` 를 그대로 탄다. main.py 가 그 길에 **마스킹과
#   TTS 와 «UI 가 없으면 보관»** 을 이미 걸어 뒀다 — 두 번째 채널을 만들면 그 셋을
#   다시 구현하게 되고, 한쪽만 고쳐진다(BL-64 가 그 모양이었다).
_notifier: Optional[Callable[[dict], None]] = None


def set_notifier(fn: Optional[Callable[[dict], None]]) -> None:
    global _notifier
    _notifier = fn


def _dispatch(payload: dict) -> None:
    if _notifier is None:
        if payload.get("type") == "notify":
            log.warning("알림을 전달할 UI가 없어요(서버 미기동): %s",
                        payload.get("text"))
        else:
            log.debug("UI가 없어 상태 알림 생략: %s", payload)
        return
    try:
        _notifier(payload)
    except Exception as e:                                    # noqa: BLE001
        log.exception("알림 전달 실패: %s", e)


def _prod_notify(text: str, reason: str, what: str) -> None:
    # `source` 를 싣는 이유 — UI 의 알림 처리기가 «감시 배지 끄기»를 같이 한다.
    # 워커 알림이 그걸 끄면 **돌고 있는 감시가 꺼진 것처럼 보인다.**
    _dispatch({"type": "notify", "text": text, "reason": reason,
               "source": "worker", "what": what})


def _prod_state(count: int) -> None:
    _dispatch({"type": "worker_state", "count": int(count)})


def _prod_config() -> dict:
    from config.settings import get_settings
    s = get_settings()
    return {
        "enabled": getattr(s, "worker_enabled", True),
        "max_jobs": getattr(s, "worker_max_jobs", DEFAULT_MAX_JOBS),
        "tick": DEFAULT_TICK,
    }


# ── 싱글톤 ─────────────────────────────────────────────────────────
_instance: Optional[BackgroundWorker] = None
_instance_lock = threading.Lock()


def get_worker() -> BackgroundWorker:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = BackgroundWorker(
                notify=_prod_notify,
                on_state=_prod_state,
                config_provider=_prod_config,
            )
        return _instance


def reset_worker() -> None:
    """약속을 전부 버리고 싱글톤을 놓는다. (서버 종료 · 테스트)"""
    global _instance
    with _instance_lock:
        inst = _instance
        _instance = None
    if inst is not None:
        try:
            inst.shutdown()
        except Exception:                                     # noqa: BLE001
            pass
