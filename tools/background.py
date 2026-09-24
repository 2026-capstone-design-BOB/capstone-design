"""
백그라운드 약속 도구 — *"30분 뒤에 알려줘"* · *"끝나면 알려줘"*
================================================================
엔진은 [`core/worker.py`](../core/worker.py) 에 있다. 여기는 **말과 엔진 사이의
얇은 층**이다(`tools/vision.py` 의 `watch_screen` 이 `core/screen_monitor.py` 를
부르는 것과 같은 모양).

## 이 파일이 지키는 것 둘

1. **약속할 때 지킬 수 있는 것만 말한다.** 언제·어떻게 멈추는지·서버를 닫으면
   사라진다는 것까지 한 번에 말한다. 나중에 «몰랐다»가 되면 그건 거짓 약속이었다.
2. **절대 시각을 모델에게 계산시키지 않는다.** 인자는 «몇 분 뒤»다.
   *"내일 3시에"* 는 `get_current_time` 으로 지금을 알고 나서 환산해야 한다 —
   모델이 지금 몇 시인지 모르는 채로 계산하면 **틀린 시각에 조용히 울린다.**
   (`gmail._build_query` 가 검색어 문법을 모델에게 안 맡기는 것과 같은 이유다)
"""

from __future__ import annotations

from langchain_core.tools import tool

from core.logger import get_logger

log = get_logger("Background")

#: 백그라운드 작업 하나에 주는 시간(분). 이 시간이 지나면 **멈췄다고 알린다.**
BACKGROUND_TASK_MINUTES = 10


def _fmt_left(seconds: float) -> str:
    total = int(round(seconds))
    if total < 60:
        return f"{max(total, 1)}초 뒤"
    mins = total // 60
    if mins < 60:
        return f"{mins}분 뒤"
    return f"{mins // 60}시간 {mins % 60}분 뒤"


def _job_lines(jobs: list) -> str:
    out = []
    for j in jobs:
        when = "지금 하는 중" if j.get("running") else _fmt_left(j["seconds_left"])
        tail = f" ({j['detail']})" if j.get("detail") else ""
        out.append(f"  · {j['what']}{tail} — {when}")
    return "\n".join(out)


# ── 알림 ──────────────────────────────────────────────────────────
@tool
def remind_me(what: str, minutes: int = 0, hours: int = 0) -> str:
    """정해진 시간이 지난 뒤에 먼저 말을 걸어 알려줍니다.
    "30분 뒤에 알려줘", "10분 있다가 회의라고 말해줘", "한 시간 뒤에 스트레칭하라고 해줘"처럼
    나중에 알려달라는 요청에 사용하세요.

    what: 그때 알려줄 말 (예: "회의 시간", "약 먹기")
    minutes: 몇 분 뒤인지
    hours: 몇 시간 뒤인지 (minutes 와 더해집니다)

    ⚠️ "내일 3시에" 처럼 **시각**으로 말한 경우에는 먼저 get_current_time 으로
    지금 시각을 확인한 뒤 몇 분 뒤인지 계산해서 넣으세요.
    """
    from core.worker import KIND_ONCE, get_worker

    what = (what or "").strip()
    if not what:
        return '✗ 무엇을 알려드릴지 알려주세요. (예: "30분 뒤에 회의라고 알려줘")'

    total_min = max(0, int(minutes or 0)) + max(0, int(hours or 0)) * 60
    if total_min <= 0:
        # 🚨 «지금 당장»으로 바꿔 울리지 않는다. 시간을 못 알아들은 것이므로 되묻는다.
        return '✗ 언제 알려드릴까요? (예: "30분 뒤에", "한 시간 뒤에")'

    message = f"🔔 {what}"
    res = get_worker().add(
        kind=KIND_ONCE,
        what=what,
        run=lambda: message,
        delay=total_min * 60,
        detail=f"{total_min}분 알림",
    )
    if res.get("added"):
        left = _fmt_left(total_min * 60)
        return (f"✓ {left}에 '{what}' 라고 알려드릴게요.\n"
                "⚠️ Pluiz 를 닫으면 이 알림도 사라져요.\n"
                '취소하려면 "알림 취소해줘" 라고 말씀해 주세요.')
    return _add_failed(res)


@tool
def list_reminders() -> str:
    """나중에 알려주기로 해 둔 것들을 모두 알려줍니다.
    "뭐 알려주기로 했지?", "예약한 거 뭐 있어?", "지금 뭐 하고 있어?" 에 사용하세요.
    (시간 알림, 메일 기다리기, 백그라운드로 맡긴 일이 전부 여기 나옵니다.)
    """
    from core.worker import get_worker

    jobs = get_worker().jobs()
    if not jobs:
        return "✓ 지금 알려드리기로 한 건 없어요."
    return f"✓ 알려드리기로 한 게 {len(jobs)}개 있어요:\n" + _job_lines(jobs)


@tool
def cancel_reminder(what: str = "") -> str:
    """알려주기로 해 둔 것을 취소합니다.
    "알림 취소해줘", "그 알림 안 해도 돼", "기다리는 거 그만해" 에 사용하세요.

    what: 어떤 것을 취소할지 (일부만 말해도 됩니다). 비워두면 **전부** 취소합니다.
    """
    from core.worker import get_worker

    res = get_worker().cancel(what=what)
    reason = res.get("reason")

    if reason == "empty":
        return "✓ 지금 알려드리기로 한 게 없어요."
    if reason == "not_found":
        return f"✗ '{what.strip()}' 에 해당하는 건 없어요. 무엇을 취소할까요?"
    if reason == "ambiguous":
        # 🚨 **고르지 않는다.** 고르는 순간 사용자가 살려 두려던 약속을 지울 수 있다.
        return ("✗ 어느 걸 말씀하시는지 몰라서 그대로 뒀어요:\n"
                + _job_lines(res.get("jobs", []))
                + "\n어느 것을 취소할까요?")

    n = res.get("cancelled", 0)
    if n == 1:
        return f"✓ '{res['jobs'][0]['what']}' 은(는) 안 알려드릴게요."
    return f"✓ {n}개 다 취소했어요."


# ── 백그라운드 작업 ────────────────────────────────────────────────
@tool
def do_in_background(request: str) -> str:
    """오래 걸리는 찾기·정리 일을 뒤에서 하고 **끝나면 먼저 알려줍니다.**
    "세 군데 찾아서 표로 만들어줘", "이거 알아보고 끝나면 알려줘" 처럼
    시간이 걸리는 조사·정리를 맡길 때 사용하세요. 사용자는 기다리지 않고 하던 일을 합니다.

    request: 맡길 일을 한 문장으로 (예: "전기차 보조금 세 군데 찾아서 엑셀로 정리")

    ⚠️ 뒤에서 도는 동안에는 **찾아보고 파일로 남기는 일만** 합니다.
    앱을 켜거나 글자를 입력하거나 화면을 누르는 일은 하지 않습니다
    (사용자가 그 화면에서 다른 일을 하고 있기 때문입니다).
    그런 일은 이 도구에 맡기지 말고 지금 바로 하세요.
    """
    from core.worker import KIND_ONCE, get_worker

    request = (request or "").strip()
    if not request:
        return '✗ 무엇을 맡길지 알려주세요. (예: "전기차 보조금 알아보고 알려줘")'

    res = get_worker().add(
        kind=KIND_ONCE,
        what=request,
        run=lambda: _run_background_request(request),
        delay=0.0,
        max_minutes=BACKGROUND_TASK_MINUTES,
        detail="백그라운드 작업",
    )
    if res.get("added"):
        return (f"✓ '{request}' 은(는) 뒤에서 할게요. 끝나면 바로 알려드릴게요.\n"
                f"하시던 일 보고 계셔도 돼요. 최대 {BACKGROUND_TASK_MINUTES}분까지 해보고, "
                "그때까지 못 끝내면 못 끝냈다고 알려드릴게요.\n"
                "⚠️ Pluiz 를 닫으면 하던 것도 사라져요.")
    return _add_failed(res)


def _run_background_request(request: str) -> str:
    """맡은 일을 **제한된 도구만 가진 에이전트**에게 시키고 결과 문장을 돌려준다.

    🚨 **승인이 필요한 도구는 아예 안 준다.** 뒤에서 도는 턴이 `interrupt` 를 걸면
      물어볼 사람이 그 자리에 없어서 **영영 안 끝난다.** 권한을 좁히는 것이
      «안 하기로 약속»보다 강하다 — `gmail_send` 를 만들지 않은 것과 같은 규칙이다.
      → core/tool_registry.py `get_background_tools()`
    """
    import asyncio

    agent = _background_agent()
    try:
        return asyncio.run(agent.run_async(request, thread_id=_next_thread_id()))
    except RuntimeError:
        # 이미 이벤트 루프가 도는 스레드였다면(프로덕션에선 안 그렇다) 새 루프를 판다.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                agent.run_async(request, thread_id=_next_thread_id()))
        finally:
            loop.close()


_bg_agent = None
_bg_seq = 0


def _next_thread_id() -> str:
    """맡은 일마다 **새 대화**를 준다. 앞 작업의 히스토리가 뒤 작업에 섞이지 않게."""
    global _bg_seq
    _bg_seq += 1
    return f"background-{_bg_seq}"


class _NullMemory:
    """백그라운드 턴은 **대화 기록에 안 남긴다.**

    `memory/session.py` 는 UI 가 보여 주는 «내가 한 말 / 받은 답»이다. 여기에
    백그라운드 요청이 들어가면 사용자가 **하지 않은 말**이 대화 기록에 생긴다.
    결과는 알림으로 화면에 그대로 나오므로 잃는 것도 없다.
    """

    def save(self, user_msg: str, agent_msg: str) -> None:
        log.info("[백그라운드] 완료 | 요청=%r", user_msg)

    def get_recent(self, n: int = 10) -> list:
        return []


class _BackgroundSettings:
    """앞단 설정을 그대로 쓰되 **셋만 덮는다.**

    - `agent_timeout` — 뒤에서 도는 일은 45초로 안 끝난다. 상한은 워커가 따로 건다.
    - `vision_verify_enabled` — 백그라운드는 화면을 안 본다. 켜 두면 사용자가
      보고 있는 **다른 일 화면**이 외부로 나간다(OWASP LLM02).
    """

    def __init__(self, base, timeout_seconds: int):
        self._base = base
        self.agent_timeout = timeout_seconds
        self.vision_verify_enabled = False

    def __getattr__(self, name):
        return getattr(self._base, name)


def _background_agent():
    """백그라운드 전용 에이전트(한 번만 만든다)."""
    global _bg_agent
    if _bg_agent is not None:
        return _bg_agent

    from config.settings import get_settings
    from core.graph_agent import PluizGraphAgent
    from core.tool_registry import get_background_tools

    _bg_agent = PluizGraphAgent(
        tools=get_background_tools(),
        # 🔑 **캐시를 끈다.** ① 뒤에서 돈 턴을 학습하면 앞단 캐시가 «뒤에서 할게요»를
        #   즉답으로 내놓게 된다. ② 반대로 캐시가 먼저 채 가면 맡긴 일이 **실제로는
        #   안 돌고** 옛 답만 돌아온다. 둘 다 조용히 틀린다.
        fast_resolve=lambda _text: None,
        session_memory=_NullMemory(),
        settings=_BackgroundSettings(get_settings(), BACKGROUND_TASK_MINUTES * 60),
    )
    return _bg_agent


def reset_background_agent() -> None:
    """테스트·설정 변경용. (`.env` 를 고치면 `get_settings.cache_clear()` 와 함께)"""
    global _bg_agent
    _bg_agent = None


# ── 공통 ──────────────────────────────────────────────────────────
def _add_failed(res: dict) -> str:
    reason = res.get("reason")
    if reason == "disabled":
        return ("✗ 백그라운드 기능이 꺼져 있어서 예약하지 않았어요. "
                "(.env 의 WORKER_ENABLED=true 로 켤 수 있어요)")
    if reason == "full":
        # 🚨 **«했어요»라고 하지 않는다.** 하나를 몰래 밀어내고 받는 것보다,
        #   안 받았다고 말하고 무엇이 차 있는지 보여 주는 쪽이 맞다.
        return (f"✗ 이미 {res.get('max_jobs')}개를 기다리는 중이라 더 못 받았어요:\n"
                + _job_lines(res.get("jobs", []))
                + '\n하나를 취소하고 다시 말씀해 주세요. ("○○ 알림 취소해줘")')
    if reason == "too_far":
        return (f"✗ {res.get('max_minutes', 0) // 60}시간 뒤까지만 알려드릴 수 있어요. "
                "그보다 먼 건 달력에 일정으로 넣어 드릴까요?")
    if reason == "no_target":
        return "✗ 무엇을 알려드릴지 알려주세요."
    return "✗ 예약하지 못했어요."
