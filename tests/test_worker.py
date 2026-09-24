# -*- coding: utf-8 -*-
"""
백그라운드 작업자 검증 — mock (실제 시간·스레드·API 없음)
실행: python tests/test_worker.py

## 이 기능에서 무엇을 지켜야 하나

약속은 **사용자가 보고 있지 않을 때** 지켜진다. 그래서 이 저장소가 반복해서 데인
결함 — «확인하지 않고 됐다고 말하기»(BL-12 · BL-15 · visual_verify 첫 판본) —
이 여기서 가장 위험하다. 사용자는 **기다리는 줄 알고 아무것도 안 하고 있다.**

이 테스트가 보는 것 다섯.

  ① **때가 되기 전에는 안 울리고, 때가 되면 정확히 한 번 울린다.**
  ② **조용히 끝나지 않는다.** 완료·실패·상한 — 어떤 이유로 끝나든 알린다.
     반대로 **사용자가 취소한 것은 안 알린다**(본인이 시켰다).
  ③ **상한이 실제로 먹는다.** 되풀이 확인은 시간·횟수 중 먼저 닿는 쪽에서 멈추고,
     **돌고 있는 중이어도** 시간 상한이 걸린다(안 끝나는 작업이 영원히 남지 않게).
  ④ **못 받으면 못 받았다고 한다.** 자리가 차면 남의 약속을 밀어내지 않고 거절하고,
     너무 먼 약속은 잘라서 받지 않고 거절한다.
  ⑤ **백그라운드 도구 묶음이 사용자의 손을 안 뺏는다.** 승인 대상·입력·화면 도구가
     하나도 없다. (뒤에서 도는 턴이 승인을 걸면 물어볼 사람이 없어 영영 안 끝난다)

⚠️ 진짜 시간을 안 쓴다. 시계·잠·스레드를 전부 가짜로 주입해 «30분 뒤»를 즉시 검증한다.
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.worker as W
from core.worker import (
    BackgroundWorker, KIND_ONCE, KIND_POLL,
    REASON_DONE, REASON_FAILED, REASON_LIMIT,
    DEFAULT_POLL_MIN_INTERVAL, DEFAULT_MAX_DELAY_MINUTES,
)

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


# ── 가짜 세상 ──────────────────────────────────────────────────────
class FakeWorld:
    """시계·잠·스레드·알림 통로를 전부 가짜로. 루프는 `advance()` 가 손으로 민다."""

    def __init__(self, max_jobs=5, enabled=True, defer=False):
        self.t = 1000.0
        self.notices = []          # (text, reason, what)
        self.states = []           # 배지용 개수
        self.pending = []          # defer=True 일 때 미뤄 둔 실행
        self.defer = defer
        self._cfg = {"enabled": enabled, "max_jobs": max_jobs}

    # 주입되는 것들
    def clock(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds

    def spawn(self, fn):
        if self.defer:
            self.pending.append(fn)
        else:
            fn()                    # 인라인 — 스레드 없이 결정적으로 돈다

    def notify(self, text, reason, what):
        self.notices.append((text, reason, what))

    def state(self, count):
        self.states.append(count)

    def config(self):
        return dict(self._cfg)

    # 시험용
    def worker(self):
        return BackgroundWorker(
            notify=self.notify, on_state=self.state, config_provider=self.config,
            clock=self.clock, sleep=self.sleep, spawn=self.spawn, autostart=False,
        )

    def advance(self, seconds, worker, step=10.0):
        """시간을 `seconds` 만큼 밀면서 그 사이 스케줄러를 돌린다."""
        end = self.t + seconds
        worker.tick()
        while self.t < end:
            self.t = min(self.t + step, end)
            worker.tick()

    def flush(self):
        """미뤄 둔 실행을 지금 돌린다."""
        pending, self.pending = self.pending, []
        for fn in pending:
            fn()

    def texts(self):
        return [t for t, _r, _w in self.notices]

    def reasons(self):
        return [r for _t, r, _w in self.notices]


print("\n[1] 알림 — 때가 되기 전엔 안 울리고, 때가 되면 한 번만 울린다")
f = FakeWorld()
w = f.worker()
res = w.add(kind=KIND_ONCE, what="회의", run=lambda: "🔔 회의", delay=1800)
check("약속이 잡힌다", res.get("added") is True, res)
f.advance(1700, w)
check("30분이 안 됐으면 안 울린다", f.notices == [], f.notices)
check("그 동안 목록에 남아 있다", w.count() == 1)
f.advance(200, w)
check("30분이 되면 울린다", f.texts() == ["🔔 회의"], f.notices)
check("사유는 done", f.reasons() == [REASON_DONE])
f.advance(3600, w)
check("두 번 울리지 않는다", len(f.notices) == 1, f.notices)
check("울린 뒤에는 목록에서 빠진다", w.count() == 0)
check("배지 개수가 1 → 0 으로 갔다", f.states == [1, 0], f.states)


print("\n[2] 되풀이 — 찾을 때까지 다시 부르고, 찾으면 알리고 끝난다")
f = FakeWorld()
w = f.worker()
calls = {"n": 0}


def poll_three():
    calls["n"] += 1
    if calls["n"] < 3:
        return {"done": False}
    return {"done": True, "text": "📬 새 메일이 왔어요"}


w.add(kind=KIND_POLL, what="메일", run=poll_three, interval=60, max_minutes=60)
f.advance(30, w)
check("첫 확인은 바로 한다", calls["n"] == 1, calls)
check("못 찾았으면 안 알린다", f.notices == [])
f.advance(60, w)
check("간격 뒤에 다시 확인한다", calls["n"] == 2, calls)
f.advance(60, w)
check("찾으면 알린다", f.texts() == ["📬 새 메일이 왔어요"], f.notices)
check("찾고 나면 멈춘다", w.count() == 0)
f.advance(600, w)
check("멈춘 뒤에는 더 안 부른다", calls["n"] == 3, calls)


print("\n[3] 상한 — 확인 횟수")
f = FakeWorld()
w = f.worker()
never = {"n": 0}


def poll_never():
    never["n"] += 1
    return {"done": False}


w.add(kind=KIND_POLL, what="메일", run=poll_never, interval=60,
      max_minutes=600, max_checks=3)
f.advance(400, w)
check("확인 횟수 상한에서 멈춘다", never["n"] == 3, never)
check("멈췄다고 **알린다**(조용히 안 사라진다)",
      len(f.notices) == 1 and f.reasons() == [REASON_LIMIT], f.notices)
msg = f.texts()[0]
check("몇 번 봤는지 함께 말한다", "3번" in msg, msg)
check("«없었어요»라고 단정하지 않는다",
      "없어요" not in msg and "소식이 없" in msg, msg)


print("\n[4] 상한 — 시간 (되풀이)")
f = FakeWorld()
w = f.worker()
w.add(kind=KIND_POLL, what="메일", run=lambda: {"done": False},
      interval=60, max_minutes=1)
f.advance(120, w)
check("시간 상한에서 멈춘다", w.count() == 0)
check("멈췄다고 알린다", f.reasons() == [REASON_LIMIT], f.notices)


print("\n[5] 상한 — 시간 (**돌고 있는 중이어도** 건다)")
f = FakeWorld(defer=True)
w = f.worker()
w.add(kind=KIND_ONCE, what="자료 조사", run=lambda: "✓ 끝났어요",
      delay=0, max_minutes=1)
f.advance(0, w)
check("작업이 시작됐다", len(f.pending) == 1, f.pending)
f.advance(120, w)
check("안 끝나는 작업도 상한에 걸려 정리된다", w.count() == 0)
check("«안 끝나서 멈췄다»고 알린다",
      f.reasons() == [REASON_LIMIT] and "안 끝나서" in f.texts()[0], f.notices)
f.flush()
check("버린 뒤에 늦게 끝나면 **조용히 접는다**(두 번 말 안 한다)",
      len(f.notices) == 1, f.notices)


print("\n[6] 실패 — 터져도 조용히 사라지지 않는다")
f = FakeWorld()
w = f.worker()


def boom():
    raise RuntimeError("망했다")


w.add(kind=KIND_ONCE, what="자료 조사", run=boom, delay=0)
f.advance(0, w)
check("실패했다고 알린다", f.reasons() == [REASON_FAILED], f.notices)
check("무엇이 실패했는지 말한다", "자료 조사" in f.texts()[0], f.texts())
check("실패하면 목록에서 빠진다", w.count() == 0)


print("\n[7] 취소 — 사용자가 시킨 것은 **안 알린다**")
f = FakeWorld()
w = f.worker()
w.add(kind=KIND_ONCE, what="회의", run=lambda: "🔔 회의", delay=600)
res = w.cancel(what="회의")
check("취소된다", res.get("cancelled") == 1, res)
f.advance(1200, w)
check("취소한 약속은 울리지 않는다", f.notices == [], f.notices)
check("취소를 알림으로 알리지 않는다(본인이 시켰다)", f.notices == [])


print("\n[8] 취소 — 도는 중에 취소하면 결과도 버린다")
f = FakeWorld(defer=True)
w = f.worker()
w.add(kind=KIND_ONCE, what="자료 조사", run=lambda: "✓ 끝났어요", delay=0)
f.advance(0, w)
w.cancel()
f.flush()
check("취소한 뒤 끝난 작업은 말을 안 건다", f.notices == [], f.notices)


print("\n[9] 취소 — 여럿이 맞으면 **아무것도 안 지우고** 되묻는다")
f = FakeWorld()
w = f.worker()
w.add(kind=KIND_ONCE, what="메일 확인", run=lambda: "a", delay=600)
w.add(kind=KIND_ONCE, what="메일 정리", run=lambda: "b", delay=600)
res = w.cancel(what="메일")
check("모호하면 안 지운다", res.get("reason") == "ambiguous" and w.count() == 2, res)
check("무엇이 걸렸는지 보여 준다", len(res.get("jobs", [])) == 2, res)
res = w.cancel(what="없는약속")
check("없으면 없다고 한다", res.get("reason") == "not_found", res)
res = w.cancel()
check("문구를 안 주면 전부 지운다", res.get("cancelled") == 2 and w.count() == 0, res)
check("전부 지운 뒤 또 부르면 «없다»", w.cancel().get("reason") == "empty")


print("\n[10] 자리가 차면 — 남의 약속을 밀어내지 않고 거절한다")
f = FakeWorld(max_jobs=2)
w = f.worker()
w.add(kind=KIND_ONCE, what="첫째", run=lambda: "a", delay=600)
w.add(kind=KIND_ONCE, what="둘째", run=lambda: "b", delay=600)
res = w.add(kind=KIND_ONCE, what="셋째", run=lambda: "c", delay=600)
check("세 번째는 거절된다", res.get("added") is False and res.get("reason") == "full", res)
check("있던 약속은 그대로다", w.count() == 2)
check("무엇이 차 있는지 알려준다", len(res.get("jobs", [])) == 2, res)
f.advance(700, w)
check("거절된 약속은 울리지 않는다", len(f.notices) == 2, f.notices)


print("\n[11] 못 지킬 약속 — 잘라서 받지 않고 거절한다")
f = FakeWorld()
w = f.worker()
res = w.add(kind=KIND_ONCE, what="내일", run=lambda: "a",
            delay=(DEFAULT_MAX_DELAY_MINUTES + 60) * 60)
check("12시간을 넘으면 거절한다", res.get("reason") == "too_far", res)
check("거절했으면 잡아 두지 않는다", w.count() == 0)
res = w.add(kind=KIND_ONCE, what="", run=lambda: "a", delay=60)
check("무엇을 알릴지 없으면 거절한다", res.get("reason") == "no_target", res)


print("\n[12] 꺼져 있으면 — 받은 척하지 않는다")
f = FakeWorld(enabled=False)
w = f.worker()
res = w.add(kind=KIND_ONCE, what="회의", run=lambda: "a", delay=60)
check("꺼져 있으면 거절한다", res.get("reason") == "disabled", res)
check("꺼져 있으면 잡아 두지 않는다", w.count() == 0)


print("\n[13] 한 번짜리는 «아직»을 인정하지 않는다 (무한 되풀이 방지)")
f = FakeWorld()
w = f.worker()
n = {"n": 0}


def once_says_not_done():
    n["n"] += 1
    return {"done": False, "text": "아직"}


w.add(kind=KIND_ONCE, what="한 번", run=once_says_not_done, delay=0, interval=60)
f.advance(600, w)
check("한 번짜리는 한 번만 돈다", n["n"] == 1, n)
check("그래도 알리고 끝난다", f.reasons() == [REASON_DONE], f.notices)


print("\n[14] 되풀이 간격에는 **바닥**이 있다 (API 할당량 방어)")
f = FakeWorld()
w = f.worker()
res = w.add(kind=KIND_POLL, what="메일", run=lambda: {"done": False},
            interval=5, max_minutes=60)
check(f"5초를 요청해도 {DEFAULT_POLL_MIN_INTERVAL}초까지만 내려간다",
      res.get("interval") == DEFAULT_POLL_MIN_INTERVAL, res)


print("\n[15] 서버 종료 — 약속을 버리고, 버렸다고 로그에 남긴다")
f = FakeWorld()
w = f.worker()
w.add(kind=KIND_ONCE, what="회의", run=lambda: "a", delay=600)
w.add(kind=KIND_ONCE, what="점심", run=lambda: "b", delay=600)
dropped = w.shutdown()
check("약속을 버린다", dropped == 2 and w.count() == 0, dropped)
check("내려가면서 알리지 않는다(받을 UI 가 없다)", f.notices == [], f.notices)


print("\n[16] 알림 통로 — 화면 감시와 **같은 길**을 탄다")
sent = []
W.set_notifier(sent.append)
try:
    W._prod_notify("🔔 회의", REASON_DONE, "회의")
    W._prod_state(2)
finally:
    W.set_notifier(None)
check("type 은 notify 다(UI 가 이미 처리하는 그것)",
      sent[0]["type"] == "notify", sent)
check("source=worker 를 싣는다 — UI 가 감시 배지를 잘못 끄지 않게",
      sent[0].get("source") == "worker", sent)
check("개수 변화는 worker_state 로 나간다",
      sent[1]["type"] == "worker_state" and sent[1]["count"] == 2, sent)


# ── 도구 층 ────────────────────────────────────────────────────────
print("\n[17] remind_me — 약속하면서 **지킬 수 있는 것만** 말한다")
import tools.background as BG

f = FakeWorld()
w = f.worker()
W._instance = w                      # 싱글톤 자리에 검사용을 꽂는다
try:
    out = BG.remind_me.invoke({"what": "회의", "minutes": 30})
    check("약속했다고 말한다", out.startswith("✓"), out)
    check("언제인지 말한다", "30분 뒤" in out, out)
    check("🚨 «닫으면 사라진다»를 미리 말한다 (저장하는 척하지 않는다)",
          "닫으면" in out, out)
    check("어떻게 취소하는지 말한다", "취소" in out, out)
    check("실제로 잡혔다", w.count() == 1)

    f.advance(1800, w)
    check("30분 뒤에 그 말을 한다", f.texts() == ["🔔 회의"], f.notices)

    out = BG.remind_me.invoke({"what": "회의", "minutes": 0, "hours": 0})
    check("🚨 시간을 안 주면 «지금 당장»으로 바꾸지 않고 되묻는다",
          out.startswith("✗") and "언제" in out, out)
    out = BG.remind_me.invoke({"what": "", "minutes": 30})
    check("무엇을 알릴지 없으면 되묻는다", out.startswith("✗"), out)

    out = BG.remind_me.invoke({"what": "먼 약속", "hours": 20})
    check("12시간 너머는 거절하고 대안을 준다",
          out.startswith("✗") and "일정" in out, out)

    # 목록 · 취소
    BG.remind_me.invoke({"what": "점심", "minutes": 10})
    out = BG.list_reminders.invoke({})
    check("잡아 둔 것을 보여 준다", "점심" in out, out)
    out = BG.cancel_reminder.invoke({"what": "점심"})
    check("문구로 취소된다", out.startswith("✓") and w.count() == 0, out)
    out = BG.list_reminders.invoke({})
    check("없으면 없다고 한다", "없어요" in out, out)
    out = BG.cancel_reminder.invoke({"what": "없는것"})
    check("없는 걸 취소하면 못 했다고 한다", out.startswith("✗"), out)
finally:
    W._instance = None


print("\n[18] 자리가 찼을 때의 **도구 문구** — «했어요»라고 하지 않는다")
f = FakeWorld(max_jobs=1)
w = f.worker()
W._instance = w
try:
    BG.remind_me.invoke({"what": "첫째", "minutes": 10})
    out = BG.remind_me.invoke({"what": "둘째", "minutes": 10})
    check("못 받았다고 말한다", out.startswith("✗"), out)
    check("무엇이 차 있는지 보여 준다", "첫째" in out, out)
    check("있던 약속은 안 지워졌다", w.count() == 1)
finally:
    W._instance = None


print("\n[19] do_in_background — 맡았다고 말하면서 상한도 같이 말한다")
f = FakeWorld()
w = f.worker()
W._instance = w
try:
    out = BG.do_in_background.invoke({"request": "전기차 보조금 세 군데 찾아줘"})
    check("맡았다고 말한다", out.startswith("✓"), out)
    check("끝나면 알린다고 말한다", "알려" in out, out)
    check("상한(분)을 말한다", str(BG.BACKGROUND_TASK_MINUTES) in out, out)
    check("못 끝내면 못 끝냈다고 알린다는 것까지 말한다", "못 끝내면" in out, out)
    check("실제로 잡혔다", w.count() == 1)
    out = BG.do_in_background.invoke({"request": ""})
    check("빈 요청은 되묻는다", out.startswith("✗"), out)
finally:
    W._instance = None
    w.cancel()


print("\n[20] 🔒 백그라운드 도구 묶음 — 사용자의 손과 눈을 안 뺏는다")
from core.tool_registry import (
    get_all_tools, get_background_tools, BACKGROUND_TOOL_NAMES,
)
from core.graph import DANGEROUS_TOOLS, OVERWRITE_TOOLS

all_names = {t.name for t in get_all_tools()}
bg_names = {t.name for t in get_background_tools()}

check("🚨 적어 둔 이름이 전부 실재한다(오타 하나가 조용히 빠진다)",
      BACKGROUND_TOOL_NAMES <= all_names,
      BACKGROUND_TOOL_NAMES - all_names)
check("적어 둔 것이 전부 들어간다", bg_names == BACKGROUND_TOOL_NAMES,
      BACKGROUND_TOOL_NAMES ^ bg_names)
check("🚨 승인 대상이 하나도 없다(뒤에선 물어볼 사람이 없다)",
      not (bg_names & DANGEROUS_TOOLS), bg_names & DANGEROUS_TOOLS)
check("덮어쓰기도 없다", not (bg_names & OVERWRITE_TOOLS))

_HANDS = {"type_text", "press_key", "click_ui_element", "open_app", "close_app",
          "force_close_app", "switch_window", "maximize_window", "minimize_window",
          "show_desktop", "split_screen", "minimize_others", "open_url",
          "open_file", "open_recent_file", "get_clipboard_text"}
check("🚨 입력·창 조작이 없다 — 사용자가 그 화면에서 일하고 있다",
      not (bg_names & _HANDS), bg_names & _HANDS)

_EYES = {"describe_screen", "find_ui_element", "point_at_element",
         "take_screenshot", "watch_screen", "stop_watching"}
check("🚨 화면을 안 본다 — 남의 일 화면이 외부로 나가면 안 된다(OWASP LLM02)",
      not (bg_names & _EYES), bg_names & _EYES)

_SYSTEM = {"set_volume", "volume_up", "volume_down", "mute", "unmute",
           "set_brightness", "brightness_up", "brightness_down",
           "notifications_off", "notifications_on", "keep_awake", "allow_sleep"}
check("시스템 상태를 안 바꾼다", not (bg_names & _SYSTEM), bg_names & _SYSTEM)

_SELF = {"do_in_background", "remind_me", "watch_inbox", "cancel_reminder",
         "list_reminders"}
check("🚨 자기 자신을 못 부른다(무한 재귀 방지)",
      not (bg_names & _SELF), bg_names & _SELF)
check("그래도 할 일은 할 수 있다(찾기·읽기·파일 남기기)",
      {"web_search", "create_file", "write_excel"} <= bg_names, bg_names)


print("\n[21] 등록 — 새 도구가 실제로 에이전트에게 간다")
for name in ("remind_me", "list_reminders", "cancel_reminder",
             "do_in_background", "watch_inbox"):
    check(f"{name} 이(가) 등록돼 있다", name in all_names)
check("이름이 겹치지 않는다", len(all_names) == len(get_all_tools()))

# 🚨 **문서가 조용히 낡는 것을 막는 자**(2026-09-25 신설).
#   이 표가 «47개»인 채로 발견됐다 — 9/24 에 15개가 늘었는데 안 따라왔다.
#   README 상태표는 같은 날 «46개»였다. 숫자를 손으로 적는 곳이 둘 있으면
#   **언젠가 둘 다 낡는다.** 그래서 숫자가 아니라 **재는 자**를 여기 둔다.
import io, re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ARCH = io.open(os.path.join(_ROOT, "docs", "ARCHITECTURE.md"),
                encoding="utf-8").read()
_m = re.search(r"##\s*도구\s*\((\d+)개\)", _ARCH)
check("ARCHITECTURE 의 도구 개수가 실제와 같다",
      _m is not None and int(_m.group(1)) == len(all_names),
      f"문서 {_m.group(1) if _m else '?'} · 실제 {len(all_names)}")

_README = io.open(os.path.join(_ROOT, "docs", "README.md"), encoding="utf-8").read()
_m2 = re.search(r"\|\s*\*\*도구\*\*\s*\|\s*\*\*(\d+)개\*\*", _README)
check("README 상태표의 도구 개수가 실제와 같다",
      _m2 is not None and int(_m2.group(1)) == len(all_names),
      f"문서 {_m2.group(1) if _m2 else '?'} · 실제 {len(all_names)}")
check("승인 대상이 늘지 않았다(백그라운드 도구는 되돌릴 수 있다)",
      not ({"remind_me", "list_reminders", "cancel_reminder",
            "do_in_background", "watch_inbox"} & DANGEROUS_TOOLS))


print("\n[22] 📬 메일 기다리기 — 지금 있는 메일은 «새 메일»이 아니다")
import tools.gmail as GM

inbox = {"msgs": []}


def _fake_fetch(_service, _query, _limit):
    return list(inbox["msgs"])


def _mail(mid, sender, subject):
    return {"id": mid, "labelIds": ["UNREAD"], "payload": {"headers": [
        {"name": "From", "value": sender}, {"name": "Subject", "value": subject}]}}


_real_fetch, _real_service = GM._fetch, None
import tools.google_auth as GA
_real_service = GA.get_service
GM._fetch = _fake_fetch
GA.get_service = lambda *a, **k: object()
try:
    inbox["msgs"] = [_mail("m1", "김철수 <a@b.com>", "이미 와 있던 메일")]
    watch = GM._InboxWatch()
    r = watch()
    check("🚨 첫 확인은 기준만 잡고 **안 알린다**", r == {"done": False}, r)

    r = watch()
    check("새 게 없으면 계속 기다린다", r == {"done": False}, r)

    inbox["msgs"] = [_mail("m2", "박영희 <c@d.com>", "새로 온 메일"),
                     _mail("m1", "김철수 <a@b.com>", "이미 와 있던 메일")]
    r = watch()
    check("새 메일이 오면 알린다", r.get("done") is True, r)
    check("누가 보냈는지 말한다", "박영희" in r["text"], r)
    check("이미 있던 것은 안 섞는다", "이미 와 있던" not in r["text"], r)
    check("🚨 본문은 안 싣는다 — 이 문장은 소리로도 읽힌다",
          "읽어 드릴까요" in r["text"], r)

    # 연속 실패
    def _boom_fetch(*_a, **_k):
        raise OSError("네트워크")

    GM._fetch = _boom_fetch
    watch2 = GM._InboxWatch()
    r1, r2 = watch2(), watch2()
    check("한두 번 실패는 참는다", r1 == {"done": False} and r2 == {"done": False})
    r3 = watch2()
    check("🚨 계속 실패하면 **포기하고 알린다**(기다리는 척 안 한다)",
          r3.get("done") is True and "멈췄" in r3["text"], r3)

    # 연결 안 됨
    GM._fetch = _fake_fetch
    GA.get_service = lambda *a, **k: (_ for _ in ()).throw(GA.NotConnected())
    r = GM._InboxWatch()()
    check("연결이 안 됐으면 되풀이하지 않고 바로 말한다",
          r.get("done") is True and "막혔" in r["text"], r)
finally:
    GM._fetch = _real_fetch
    GA.get_service = _real_service


print("\n[23] watch_inbox 도구 — 무엇을 어떻게 하는지 다 말한다")
f = FakeWorld()
w = f.worker()
W._instance = w
try:
    out = GM.watch_inbox.invoke({"sender": "김철수", "minutes": 30})
    check("기다리겠다고 말한다", out.startswith("✓"), out)
    check("누구 것을 기다리는지 말한다", "김철수" in out, out)
    check("얼마나 자주 보는지 말한다", "분마다" in out, out)
    check("언제 스스로 멈추는지 말한다", "30분" in out, out)
    check("🚨 지금 와 있는 메일은 안 센다고 미리 말한다", "지금 와 있는" in out, out)
    check("닫으면 멈춘다고 말한다", "닫으면" in out, out)
    check("그만두는 법을 말한다", "기다리지 마" in out, out)
    check("실제로 잡혔다", w.count() == 1)

    out = GM.watch_inbox.invoke({"minutes": 9999})
    check("요청 시간이 터무니없으면 상한으로 줄여서 **줄였다고 말한다**",
          "60분" in out, out)
finally:
    W._instance = None
    w.cancel()


print("\n[24] 절대규칙 1 — 그래프는 한 줄도 async 가 되지 않았다")
import io, inspect
import core.graph as G

_src = io.open(G.__file__, encoding="utf-8").read()
check("graph.py 에 async 노드가 없다", "async def" not in _src)
_wsrc = io.open(W.__file__, encoding="utf-8").read()
check("worker.py 도 async 를 안 쓴다(스레드로 돈다)", "async def" not in _wsrc)
check("워커 도구는 sync 다 — 얹고 즉시 끝난다",
      not inspect.iscoroutinefunction(BG.remind_me.func)
      and not inspect.iscoroutinefunction(BG.do_in_background.func)
      and not inspect.iscoroutinefunction(GM.watch_inbox.func))


print("\n[25] 백그라운드 작업이 **실제로 끝까지 돈다** (가짜 LLM)")
from langchain_core.messages import AIMessage


class FakeLLM:
    """도구 없이 답만 내는 LLM. 백그라운드 경로의 배선을 보는 용도다."""

    def __init__(self):
        self.seen = []
        self.tools = []

    def bind_tools(self, tools, **kw):
        self.tools = [getattr(t, "name", "?") for t in tools]
        return self

    def invoke(self, messages):
        for m in reversed(messages):
            if m.__class__.__name__ == "HumanMessage":
                self.seen.append(str(m.content))
                break
        return AIMessage(content="세 군데 찾아서 정리했어요.")


class FakeSettings:
    agent_timeout = 30
    plan_enabled = False
    vision_verify_enabled = False


import core.graph_agent as GA

_fake_llm = FakeLLM()
bg_agent = GA.PluizGraphAgent(
    llm=_fake_llm,
    tools=get_background_tools(),
    fast_resolve=lambda _t: None,
    session_memory=BG._NullMemory(),
    settings=FakeSettings(),
)
check("백그라운드 도구만 들고 그래프가 세워진다",
      set(_fake_llm.tools) == BACKGROUND_TOOL_NAMES,
      set(_fake_llm.tools) ^ BACKGROUND_TOOL_NAMES)

BG._bg_agent = bg_agent
f = FakeWorld()
w = f.worker()
W._instance = w
try:
    BG.do_in_background.invoke({"request": "전기차 보조금 세 군데 찾아줘"})
    f.advance(1, w)
    check("끝나면 **먼저 말을 건다**",
          len(f.notices) == 1 and "정리했어요" in f.texts()[0], f.notices)
    # 🔑 **앞단의 방어가 그대로 걸린다.** 처음 이 시험을 쓸 때 가짜 LLM 이
    #   도구를 안 부르고 «✓ …» 로 답했더니 BL-61(지어냄 방어)이 막았다 —
    #   백그라운드라고 무르게 도는 별도 경로가 아니라는 증거다.
    check("출력 관문이 백그라운드 턴에도 산다(같은 그래프를 쓴다)",
          "[Graph]" not in f.texts()[0], f.texts())
    check("사유는 done", f.reasons() == [REASON_DONE])
    check("맡긴 말이 그대로 에이전트에게 간다",
          bool(_fake_llm.seen) and "전기차 보조금" in _fake_llm.seen[-1],
          _fake_llm.seen)

    # 🔑 맡은 일마다 **새 대화**여야 한다 — 앞 작업 히스토리가 뒤에 섞이면 안 된다
    t1, t2 = BG._next_thread_id(), BG._next_thread_id()
    check("작업마다 thread_id 가 다르다", t1 != t2, (t1, t2))
finally:
    W._instance = None
    BG._bg_agent = None

check("🚨 백그라운드 턴은 대화 기록에 안 남긴다(사용자가 안 한 말이 생기면 안 된다)",
      BG._NullMemory().get_recent() == [])


# ── 결과 ──────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"결과: {passed}/{total} 통과")
print(f"{'=' * 60}")
sys.exit(0 if passed == total else 1)
