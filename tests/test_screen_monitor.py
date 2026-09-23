"""
화면 변화 모니터링(watch_screen) 검증 — mock (실제 화면·API 없음)
실행: python tests/test_screen_monitor.py

## 이 기능에서 무엇을 지켜야 하나

감시는 **사용자가 화면을 보고 있지 않을 때** 도는 유일한 기능이다. 그래서 이 프로젝트가
반복해서 데인 결함(확인하지 않고 됐다고 말하기 — BL-12 · BL-15 · visual_verify 첫 판본)이
여기서 가장 위험하다. 사용자가 못 보는 사이에 일어나기 때문이다.

이 테스트는 네 가지를 본다.

  ① **변화가 없으면 Vision을 부르지 않는다.**
     이게 비용·개인정보 방어의 전부다(OWASP LLM02). 픽셀 비교는 로컬이라 공짜지만
     Vision 호출은 화면 한 장이 외부로 나가는 것이다.
  ② **상한을 넘지 않는다.** 시간·횟수 중 먼저 닿는 쪽에서 멈춘다.
     max_vision_calls가 곧 **밖으로 나가는 화면 장수의 상한**이다.
  ③ **조용히 끝나지 않는다.** 어떤 이유로 멈추든 사용자에게 알린다.
     말없이 사라지면 사용자는 아직 지켜보는 줄 안다.
  ④ **증거 없는 감지는 알리지 않는다.** 못 믿을 답으로 사용자를 부르지 않는다.

⚠️ 실제 화면을 캡처하지 않는다. 캡처·Vision·시계를 전부 가짜로 주입한다.
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
import sys, os, json, types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from core.screen_monitor import (
    ScreenMonitor, signature_changed, SIGNATURE_CELLS,
    REASON_DETECTED, REASON_TIMEOUT, REASON_BUDGET,
    REASON_CAPTURE_FAILED, REASON_UNREADABLE, REASON_STOPPED,
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


# ── 가짜 화면 ─────────────────────────────────────────────────────
def frame(value=100, changed_cells=0, delta=80):
    """균일한 화면 한 장. `changed_cells`개만 밝기를 바꾼다."""
    cells = [value] * SIGNATURE_CELLS
    for i in range(min(changed_cells, SIGNATURE_CELLS)):
        cells[i] = (value + delta) % 256
    return tuple(cells)


class FakeWorld:
    """가짜 캡처·Vision·시계. 루프를 실제 시간 없이 결정적으로 돌린다.

    `frames`를 순서대로 내주고, 다 떨어지면 마지막 프레임을 계속 반복한다.
    `sleep`은 진짜로 자지 않고 가짜 시계만 앞으로 민다.
    """

    def __init__(self, frames, vision_results=None, max_ticks=400):
        self.frames = list(frames)
        self.vision_results = list(vision_results or [])
        self.captures = 0
        self.vision_calls = 0
        self.notifications = []      # (message, reason)
        self.states = []             # (active, what)
        self.clock = 0.0
        self.sleeps = []
        self.max_ticks = max_ticks

    # 감시 엔진이 주입받는 것들 ────────────────────────────────
    def capture(self, window):
        self.captures += 1
        if self.captures > self.max_ticks:
            raise RuntimeError("무한 루프 방지: 캡처 횟수 초과")
        if not self.frames:
            return None
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    def vision(self, window, what):
        self.vision_calls += 1
        if not self.vision_results:
            return {"ok": True, "detected": False, "detail": "", "reason": "없음"}
        return (self.vision_results.pop(0) if len(self.vision_results) > 1
                else self.vision_results[0])

    def notify(self, message, reason):
        self.notifications.append((message, reason))

    def on_state(self, active, what):
        self.states.append((active, what))

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.clock += seconds

    def now(self):
        return self.clock


class ChangingWorld(FakeWorld):
    """캡처할 때마다 화면이 크게 바뀌는 세상 — 매 주기 Vision을 부르게 된다.

    (정적인 화면은 한 번 판정하고 나면 baseline이 갱신돼 더 안 부른다.
     그게 정상 동작이라, 반복 호출을 검증하려면 계속 변해야 한다.)
    """

    def capture(self, window):
        self.captures += 1
        if self.captures > self.max_ticks:
            raise RuntimeError("무한 루프 방지: 캡처 횟수 초과")
        return frame(100, 100 + (self.captures * 37) % 400)


def run_monitor(world, *, what="오류 메시지", window="메모장",
                interval=5, max_minutes=10, max_vision_calls=20, enabled=True):
    """감시를 **동기로** 한 바퀴 끝까지 돌린다(스레드 없이 루프만 호출).

    스레드를 띄우면 테스트가 타이밍에 의존하게 된다. 루프 자체가 검증 대상이므로
    세션 상태만 세팅하고 `_loop()`를 직접 부른다.
    """
    m = ScreenMonitor(
        capture_signature=world.capture, vision_check=world.vision,
        notify=world.notify, on_state=world.on_state,
        config_provider=lambda: {"enabled": enabled, "interval": interval,
                                 "max_minutes": max_minutes,
                                 "max_vision_calls": max_vision_calls},
        sleep=world.sleep, now=world.now)
    m._cfg = m._load_config()
    m._what, m._window = what, window
    m._vision_calls = 0
    m._started_at = world.now()
    m._loop()
    return m


DETECTED = {"ok": True, "detected": True, "detail": "빨간 오류 대화상자: 파일을 찾을 수 없습니다"}
NOTHING = {"ok": True, "detected": False, "detail": "", "reason": "그런 건 안 보임"}
UNREADABLE = {"ok": False, "detected": False, "detail": "", "reason": "JSON이 아님"}


# ── 1. 픽셀 차이 프리필터 ─────────────────────────────────────────
print("\n[1] 픽셀 차이 프리필터 — 변화가 없으면 화면이 밖으로 나가지 않는다")

same = frame(100)
check("같은 화면은 변화가 아니다", not signature_changed(same, frame(100)))
check("1셀 변화는 무시 (시계 초침)", not signature_changed(same, frame(100, 1)))
# 아래 셀 수는 전부 1000x700 창에 실제로 그려 재본 값이다(2026-09-07).
check("2셀(커서 깜빡임)은 무시", not signature_changed(same, frame(100, 2)))
check("10셀(0.98%)은 아직 문턱 아래", not signature_changed(same, frame(100, 10)))
check("13셀(글자 한 줄)은 변화 — 2%였을 땐 이걸 놓쳤다",
      signature_changed(same, frame(100, 13)))
check("21셀(글자 두 줄)은 변화", signature_changed(same, frame(100, 21)))
check("대화상자급(100셀)은 확실히 변화", signature_changed(same, frame(100, 100)))
check("밝기 차이가 작으면(5) 셀이 많아도 무시",
      not signature_changed(same, frame(100, 500, delta=5)))
check("길이가 다르면 변화로 본다(창 크기 변경)",
      signature_changed((1, 2, 3), (1, 2, 3, 4)))

w = FakeWorld([frame(100)], [DETECTED], max_ticks=30)
run_monitor(w, max_minutes=1, interval=5)
check("화면이 안 바뀌면 Vision 호출 0회 ← 이게 전송량 방어의 전부",
      w.vision_calls == 0, f"(호출 {w.vision_calls}회)")
check("변화가 없어도 타임아웃으로 끝난다",
      any(r == REASON_TIMEOUT for _, r in w.notifications))

w = FakeWorld([frame(100), frame(100, 200)], [DETECTED], max_ticks=30)
run_monitor(w)
check("변화가 있으면 Vision을 부른다", w.vision_calls == 1, f"(호출 {w.vision_calls}회)")

w = FakeWorld([frame(100), frame(100, 1)], [DETECTED], max_ticks=30)
run_monitor(w, max_minutes=1)
check("작은 잡음만으로는 Vision을 부르지 않는다", w.vision_calls == 0)


# ── 2. 감지 ───────────────────────────────────────────────────────
print("\n[2] 감지 — 알리고 자동 종료한다")

w = FakeWorld([frame(100), frame(100, 200)], [DETECTED], max_ticks=50)
run_monitor(w)
msgs = [m for m, r in w.notifications if r == REASON_DETECTED]
check("감지하면 알린다", len(msgs) == 1, str(w.notifications))
check("알림에 Vision의 말을 그대로 옮긴다",
      msgs and "빨간 오류 대화상자: 파일을 찾을 수 없습니다" in msgs[0])
check("알림에 '직접 확인해 달라'는 말이 있다(추정임을 숨기지 않는다)",
      msgs and "확인" in msgs[0])
check("감지 뒤에는 Vision을 더 부르지 않는다(자동 종료)", w.vision_calls == 1)
check("감지 뒤 상태가 꺼짐으로 바뀐다", w.states and w.states[-1][0] is False)

w = ChangingWorld([], [NOTHING, NOTHING, DETECTED], max_ticks=60)
run_monitor(w, max_minutes=1)
check("아직 아니면 계속 지켜본다", w.vision_calls >= 2, f"(호출 {w.vision_calls}회)")


# ── 3. 상한 — max_vision_calls가 곧 전송량 상한이다 ───────────────
print("\n[3] 상한 — 시간·횟수 중 먼저 닿는 쪽에서 멈춘다")

w = ChangingWorld([], [NOTHING], max_ticks=200)
run_monitor(w, max_minutes=600, max_vision_calls=5)
check("Vision 상한을 넘지 않는다", w.vision_calls == 5, f"(호출 {w.vision_calls}회)")
check("상한 도달을 사용자에게 알린다",
      any(r == REASON_BUDGET for _, r in w.notifications), str(w.notifications))
check("상한 알림이 '못 봤다'고 분명히 말한다",
      any("못 봤" in m for m, r in w.notifications if r == REASON_BUDGET))

w = FakeWorld([frame(100)], [NOTHING], max_ticks=200)
run_monitor(w, interval=5, max_minutes=1, max_vision_calls=20)
check("시간 상한에서 멈춘다", any(r == REASON_TIMEOUT for _, r in w.notifications))
check("시간 알림에 화면 확인 횟수를 밝힌다(놓쳤을 가능성을 숨기지 않는다)",
      any("화면 확인" in m for m, r in w.notifications if r == REASON_TIMEOUT))

w = ChangingWorld([], [NOTHING], max_ticks=300)
run_monitor(w, interval=5, max_minutes=1, max_vision_calls=100)
check("시간이 먼저 닿으면 횟수가 남아도 멈춘다",
      any(r == REASON_TIMEOUT for _, r in w.notifications) and w.vision_calls < 100)


# ── 4. 정직성 — 못 믿을 답으로 사용자를 부르지 않는다 ─────────────
print("\n[4] 정직성 — 증거 없는 감지는 감지가 아니다")

w = ChangingWorld([],
                  [{"ok": True, "detected": True, "detail": "   "}], max_ticks=60)
run_monitor(w, max_minutes=1, max_vision_calls=3)
check("detected=true인데 근거가 비면 알리지 않는다",
      not any(r == REASON_DETECTED for _, r in w.notifications), str(w.notifications))

w = ChangingWorld([], [UNREADABLE], max_ticks=60)
run_monitor(w, max_minutes=60, max_vision_calls=20)
check("판독 실패가 이어지면 멈춘다",
      any(r == REASON_UNREADABLE for _, r in w.notifications), str(w.notifications))
check("판독 실패 3회에서 멈춘다(무한히 부르지 않는다)", w.vision_calls == 3,
      f"(호출 {w.vision_calls}회)")
check("판독 실패로는 감지 알림을 보내지 않는다",
      not any(r == REASON_DETECTED for _, r in w.notifications))

w = ChangingWorld([],
                  [UNREADABLE, UNREADABLE, DETECTED], max_ticks=60)
run_monitor(w, max_minutes=60)
check("판독 실패 뒤 정상 응답이 오면 카운터가 초기화된다",
      any(r == REASON_DETECTED for _, r in w.notifications), str(w.notifications))


def _vision_raises(window, what):
    raise RuntimeError("네트워크 끊김")


w = ChangingWorld([], [], max_ticks=60)
m = ScreenMonitor(capture_signature=w.capture, vision_check=_vision_raises,
                  notify=w.notify, on_state=w.on_state,
                  config_provider=lambda: {"enabled": True, "interval": 5,
                                           "max_minutes": 60, "max_vision_calls": 20},
                  sleep=w.sleep, now=w.now)
m._cfg = m._load_config()
m._what, m._window, m._started_at = "오류", "메모장", 0.0
m._loop()
check("Vision이 예외를 던져도 감시가 죽지 않고 사유와 함께 끝난다",
      any(r == REASON_UNREADABLE for _, r in w.notifications), str(w.notifications))


# ── 5. 캡처 실패 (창이 닫히거나 최소화됨) ─────────────────────────
print("\n[5] 캡처 실패 — 못 보면 못 본다고 하고 멈춘다")

w = FakeWorld([], [DETECTED], max_ticks=30)
run_monitor(w, max_minutes=60)
check("캡처가 계속 실패하면 멈춘다",
      any(r == REASON_CAPTURE_FAILED for _, r in w.notifications), str(w.notifications))
check("3회에서 포기한다(영원히 재시도하지 않는다)", w.captures == 3, f"({w.captures}회)")
check("사유를 사람 말로 알린다(창이 닫혔거나 최소화)",
      any("최소화" in m or "닫혔" in m
          for m, r in w.notifications if r == REASON_CAPTURE_FAILED))
check("캡처 실패로는 Vision을 부르지 않는다", w.vision_calls == 0)


class FlakyWorld(FakeWorld):
    """첫 두 번만 실패하고 이후 정상인 캡처."""

    def capture(self, window):
        self.captures += 1
        if self.captures > self.max_ticks:
            raise RuntimeError("무한 루프 방지")
        if self.captures <= 2:
            return None
        return frame(100)


w = FlakyWorld([frame(100)], [NOTHING], max_ticks=60)
run_monitor(w, interval=5, max_minutes=1)
check("일시적 캡처 실패(2회)는 견디고 계속한다",
      not any(r == REASON_CAPTURE_FAILED for _, r in w.notifications), str(w.notifications))


# ── 6. 종료는 언제나 알린다 (사용자가 직접 멈춘 것만 제외) ────────
print("\n[6] 조용히 끝나지 않는다")

for label, world, kwargs in [
    ("타임아웃", FakeWorld([frame(100)], [NOTHING], max_ticks=200),
     dict(max_minutes=1, max_vision_calls=20)),
    ("횟수 소진", ChangingWorld([], [NOTHING], max_ticks=200),
     dict(max_minutes=600, max_vision_calls=2)),
    ("캡처 실패", FakeWorld([], [NOTHING], max_ticks=30), dict(max_minutes=60)),
    ("판독 실패", ChangingWorld([], [UNREADABLE], max_ticks=60),
     dict(max_minutes=60)),
    ("감지", FakeWorld([frame(100), frame(100, 200)], [DETECTED], max_ticks=60), dict()),
]:
    run_monitor(world, **kwargs)
    check(f"{label} 종료 → 사용자에게 알림이 간다", len(world.notifications) == 1,
          str(world.notifications))

w = FakeWorld([frame(100)], [NOTHING], max_ticks=30)
m = ScreenMonitor(capture_signature=w.capture, vision_check=w.vision,
                  notify=w.notify, on_state=w.on_state,
                  config_provider=lambda: {"enabled": True, "interval": 5,
                                           "max_minutes": 60, "max_vision_calls": 20},
                  sleep=w.sleep, now=w.now)
m._cfg = m._load_config()
m._what, m._window, m._started_at = "오류", "메모장", 0.0
m._stop_event.set()
m._loop()
check("사용자가 직접 멈춘 경우엔 푸시 알림을 보내지 않는다(도구 응답으로 이미 안다)",
      w.notifications == [], str(w.notifications))
check("직접 멈춰도 상태 변화는 알린다(UI 배지)", w.states and w.states[-1][0] is False)


# ── 7. 스레드 · 단일성 · 시작/중단 API ────────────────────────────
print("\n[7] 한 번에 하나만 — 두 개가 돌면 전송량이 두 배가 된다")


def make_live_monitor(world, **cfg):
    base = {"enabled": True, "interval": 0, "max_minutes": 60, "max_vision_calls": 20}
    base.update(cfg)
    return ScreenMonitor(
        capture_signature=world.capture, vision_check=world.vision,
        notify=world.notify, on_state=world.on_state,
        config_provider=lambda: base, sleep=world.sleep, now=world.now)


w = FakeWorld([frame(100)], [NOTHING], max_ticks=100000)
mon = make_live_monitor(w, max_minutes=600)
r1 = mon.start("오류 메시지", "메모장")
check("start()가 시작 사실을 돌려준다", r1.get("started") is True, str(r1))
check("start() 결과에 설정값이 들어 있다(고지문 재료)",
      {"interval", "max_minutes", "max_vision_calls"} <= set(r1))
check("시작하면 상태를 알린다(UI 배지)", (True, "오류 메시지") in w.states)

r2 = mon.start("다른 것", "크롬")
check("이미 감시 중이면 새로 시작하지 않는다", r2.get("started") is False, str(r2))
check("거절 사유를 정확히 돌려준다", r2.get("reason") == "already_watching")
check("무엇을 지켜보는 중인지 알려준다", r2.get("what") == "오류 메시지")

st = mon.status()
check("status()가 감시 중임을 보고한다", st.get("active") is True, str(st))
check("status()에 대상이 들어 있다", st.get("what") == "오류 메시지")

r3 = mon.stop()
check("stop()이 멈춘 사실을 돌려준다", r3.get("stopped") is True, str(r3))
check("stop() 뒤에는 감시 중이 아니다", mon.is_active() is False)
check("stop() 결과에 화면 확인 횟수가 들어 있다", "vision_calls" in r3)
check("멈춘 뒤 status()는 active=False", mon.status().get("active") is False)

r4 = mon.stop()
check("감시 중이 아닐 때 stop()은 거짓말하지 않는다", r4.get("stopped") is False)

w2 = FakeWorld([frame(100)], [NOTHING], max_ticks=100000)
mon2 = make_live_monitor(w2, max_minutes=600)
mon2.start("첫 번째", "")
mon2.start("두 번째", "")
import threading
alive = [t for t in threading.enumerate() if t.name == "pluiz-screen-monitor"]
check("감시 스레드는 하나뿐이다", len(alive) <= 1, f"({len(alive)}개)")
mon2.stop()

w3 = FakeWorld([frame(100)], [NOTHING])
mon3 = make_live_monitor(w3, enabled=False)
r5 = mon3.start("오류", "")
check("설정이 꺼져 있으면 시작하지 않는다", r5.get("started") is False, str(r5))
check("꺼짐 사유를 돌려준다", r5.get("reason") == "disabled")
check("꺼져 있으면 캡처도 하지 않는다", w3.captures == 0)

r6 = make_live_monitor(FakeWorld([frame(100)])).start("   ", "")
check("무엇을 볼지 없으면 시작하지 않는다", r6.get("started") is False and
      r6.get("reason") == "no_target", str(r6))


# ── 8. Vision 응답 파서 (tools/vision.parse_watch_result) ─────────
print("\n[8] 응답 파서 — 의심스러우면 아무 일도 없던 것으로 본다")

# tools/__init__ 우회 (Linux CI에서 무관한 이유로 깨지지 않게)
if "tools" not in sys.modules:
    _stub = types.ModuleType("tools")
    _stub.__path__ = [os.path.join(_ROOT, "tools")]
    sys.modules["tools"] = _stub

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "tools.vision", os.path.join(_ROOT, "tools", "vision.py"))
_vision = importlib.util.module_from_spec(_spec)
sys.modules["tools.vision"] = _vision
_spec.loader.exec_module(_vision)
parse = _vision.parse_watch_result

r = parse('{"detected": true, "detail": "빨간 오류창"}')
check("정상 감지 응답", r["ok"] and r["detected"] and r["detail"] == "빨간 오류창", str(r))

r = parse('{"detected": false, "reason": "안 보임"}')
check("정상 미감지 응답", r["ok"] and not r["detected"], str(r))

r = parse('```json\n{"detected": true, "detail": "경고"}\n```')
check("코드펜스를 걷어낸다", r["ok"] and r["detected"], str(r))

r = parse('네, 화면을 보니 {"detected": true, "detail": "경고"} 입니다')
check("앞뒤 잡담이 섞여도 객체를 집어낸다", r["ok"] and r["detected"], str(r))

r = parse('[{"detected": true, "detail": "경고"}]')
check("객체 하나짜리 배열은 받아준다", r["ok"] and r["detected"], str(r))

for name, raw in [
    ("빈 응답", ""),
    ("잡담만", "화면에 오류가 있는 것 같아요"),
    ("깨진 JSON", '{"detected": true, '),
    ("detected 없음", '{"detail": "뭔가 있음"}'),
    ("detected가 문자열", '{"detected": "true", "detail": "경고"}'),
    ("detected가 숫자", '{"detected": 1, "detail": "경고"}'),
    ("후보가 여럿", '[{"detected": true}, {"detected": false}]'),
    ("객체가 아님", '"그냥 문자열"'),
]:
    r = parse(raw)
    check(f"못 믿을 답은 ok=False — {name}", r["ok"] is False and r["detected"] is False,
          str(r))

r = parse('{"detected": true}')
check("detail이 없으면 감지는 True지만 detail은 빈 문자열(엔진이 거른다)",
      r["ok"] and r["detected"] and r["detail"] == "", str(r))


# ── 9. 도구 계약 — 고지문에 네 가지가 다 들어 있는가 ──────────────
print("\n[9] 고지 — 승인 대신 받는 것이 이것이다")

notice = _vision._watch_notice(
    {"interval": 5, "max_minutes": 10, "max_vision_calls": 20}, "오류 메시지", "크롬")
check("① 무엇을 보는지 밝힌다", "크롬" in notice and "오류 메시지" in notice, notice)
check("② 얼마나 자주 보는지 밝힌다", "5초" in notice, notice)
check("③ 언제 자동으로 멈추는지 밝힌다", "10분" in notice and "20회" in notice, notice)
check("④ 어떻게 멈추는지 알려준다", "그만 봐" in notice, notice)
check("변화가 있을 때만 화면을 읽는다는 걸 밝힌다", "변화가 있을 때만" in notice, notice)

# ③ 무엇을 **놓칠 수 있는지** (BL-22 잔여, 2026-09-08)
#    프리필터는 글자 한두 자를 커서 깜빡임과 구분하지 못한다. 그런데 고지는
#    "글자 생기면 알려드릴게요"라고 받는다 — 못 하는 것을 할 수 있다고 말한 것이다.
#    이 줄이 사라지면 그 거짓 약속이 되돌아온다.
check("③ 놓칠 수 있는 것을 미리 말한다 (BL-22)",
      "놓칠 수 있" in notice, notice)

notice_full = _vision._watch_notice(
    {"interval": 5, "max_minutes": 10, "max_vision_calls": 20}, "오류", "")
check("창을 지정하지 않으면 '화면 전체'라고 정확히 말한다",
      "화면 전체" in notice_full, notice_full)


# ── 10. 도구 등록 ────────────────────────────────────────────────
print("\n[10] 도구 등록 — 감시는 승인 대상이 아니다(멈추면 끝나므로)")

src = open(os.path.join(_ROOT, "core", "tool_registry.py"), encoding="utf-8").read()
check("watch_screen이 등록돼 있다", "watch_screen" in src)
check("stop_watching이 등록돼 있다", "stop_watching" in src)

gsrc = open(os.path.join(_ROOT, "core", "graph.py"), encoding="utf-8").read()
i = gsrc.index("DANGEROUS_TOOLS = ")
check("watch_screen은 DANGEROUS_TOOLS가 아니다",
      "watch_screen" not in gsrc[i:i + 200], gsrc[i:i + 200])
check("시스템 프롬프트가 '스스로 시작하지 말라'고 못박는다",
      "스스로 감시를 시작하지는 마세요" in gsrc)

# BL-19 — **금지문이 앞에 서면 모델이 아무것도 안 하는 쪽으로 기운다.**
# 2026-09-04 실기: "메모장 지켜보다가 오류 뜨면 알려줘"에 도구를 하나도 부르지 않고
# "지켜보다가 알려드릴게요!"라고 답했다. 아무도 화면을 안 보고 있었다.
# 그래서 **호출하라는 말이 먼저** 오는지를 고정한다.
_i_call = gsrc.find("반드시 watch_screen을 호출하세요")
_i_dont = gsrc.find("스스로 감시를 시작하지는 마세요")
check("프롬프트가 watch_screen 호출을 먼저 지시한다 (BL-19)", _i_call != -1)
check("금지문은 그 뒤에 온다 (BL-19)", _i_call != -1 and _i_dont > _i_call,
      f"호출지시={_i_call} 금지문={_i_dont}")
check("프롬프트가 stop_watching 호출을 지시한다 (BL-19)",
      "반드시 stop_watching을 호출하세요" in gsrc)

# 도구 docstring에도 같은 억제문이 한 번 더 있어 이중으로 눌렀다. 한쪽만 남긴다.
vsrc = open(os.path.join(_ROOT, "tools", "vision.py"), encoding="utf-8").read()
check("watch_screen docstring이 호출을 먼저 지시한다 (BL-19)",
      "이 도구를 호출하세요" in vsrc)
check("watch_screen docstring에 '부르지 않으면 아무것도 지켜보지 않는다'가 있다 (BL-19)",
      "부르지 않으면 아무것도 지켜보지 않습니다" in vsrc)

# 캐시는 **파라미터를 저장하지 않는다**(P4 오염 방지). 감시가 학습되면
# "오류 뜨면 알려줘"가 what 없이 재생돼, 무엇을 보는지도 모르는 감시가 시작된다.
from core.command_cache import LEARNABLE_TOOLS
check("watch_screen은 캐시 학습 대상이 아니다", "watch_screen" not in LEARNABLE_TOOLS)
check("stop_watching은 캐시 학습 대상이 아니다", "stop_watching" not in LEARNABLE_TOOLS)

msrc = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
check("서버가 감시 알림을 UI로 푸시한다", "_push_from_monitor" in msrc)
check("연결된 UI가 없으면 알림을 보관한다", "_pending_notifications" in msrc)
check("서버가 내려갈 때 감시를 멈춘다", "reset_monitor()" in msrc)

rsrc = open(os.path.join(_ROOT, "electron-ui", "renderer", "index.html"),
            encoding="utf-8").read()
check("렌더러가 notify 타입을 처리한다", "'notify'" in rsrc)
check("렌더러가 감시 배지를 표시한다", "watch-badge" in rsrc)
psrc = open(os.path.join(_ROOT, "electron-ui", "preload.js"), encoding="utf-8").read()
check("preload가 showWindow를 노출한다", "showWindow" in psrc)
jsrc = open(os.path.join(_ROOT, "electron-ui", "main.js"), encoding="utf-8").read()
check("main.js가 show-window IPC를 받는다", "'show-window'" in jsrc)


# ── 11. 정직성 그물 — 말이 아니라 상태로 본다 (BL-19) ─────────────
print("")
print("[11] BL-19 — 도구를 안 부르고 '지켜볼게요'라고 말한 경우")

from core.graph import detect_watch_lie, watch_notice_to_deliver
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _turn(ai_text):
    return [HumanMessage(content="메모장 지켜보다가 오류 뜨면 알려줘"),
            AIMessage(content=ai_text)]


# ① 도구 0개 + 모니터 꺼짐 + 감시 주장 → 교정한다
_lie = detect_watch_lie(_turn("메모장을 지켜보다가 오류 메시지가 뜨면 바로 알려드릴게요!"),
                        watching=False)
check("도구 없이 '지켜볼게요'라고 하면 교정한다",
      _lie is not None and "시작하지 못했" in _lie, str(_lie))

# ⚠️ 실제로 새어나간 거짓말은 '지켜보'도 '감시'도 없었다 (2026-09-04 라이브).
#    응답 문구만 보는 검사는 이걸 통과시킨다 → 범위를 **사용자 입력**으로 잡는다.
_leaked = detect_watch_lie(_turn("메모장에서 오류 메시지가 뜨면 바로 알려드릴게요!"),
                           watching=False)
check("'지켜보'가 없는 거짓 약속도 잡는다 (실기에서 샜던 문장)",
      _leaked is not None and "시작하지 못했" in _leaked, str(_leaked))

_stop = detect_watch_lie([HumanMessage(content="그만 봐"),
                          AIMessage(content="알겠습니다, 화면 감시를 중단했어요.")],
                         watching=False)
check("도구 없이 '중단했어요'라고 하면 교정한다",
      _stop is not None and "지켜보고 있는 화면은 없" in _stop, str(_stop))

# ② 진짜 돌고 있으면 거짓말이 아니다 — 손대지 않는다
check("실제로 감시 중이면 손대지 않는다",
      detect_watch_lie(_turn("메모장을 지켜볼게요!"), watching=True) is None)

# ③ 도구가 돌았으면 손대지 않는다 (판정은 도구 결과가 한다)
_with_tool = [HumanMessage(content="메모장 지켜봐"),
              AIMessage(content="",
                        tool_calls=[{"name": "watch_screen", "args": {}, "id": "c1"}]),
              ToolMessage(content="✓ 지켜볼게요", tool_call_id="c1", name="watch_screen"),
              AIMessage(content="메모장을 지켜볼게요!")]
check("이번 턴에 도구가 돌았으면 손대지 않는다",
      detect_watch_lie(_with_tool, watching=False) is None)

# ④ 오탐 — 감시를 요청하지 않은 턴은 건드리지 않는다.
#    범위를 사용자 입력으로 잡으므로, 평범한 명령의 응답은 무슨 말을 하든 통과한다.
for _u, _t in [("메모장 열어줘", "메모장을 열었어요."),
               ("안녕", "네, 안녕하세요!"),
               ("소리 키워줘", "볼륨을 높였어요."),
               ("무슨 기능 있어?", "화면 감시 기능도 있어요. 필요하면 말씀해 주세요."),
               ("오늘 날씨 알려줘", "오늘은 맑아요.")]:
    check("오탐 없음: " + _u,
          detect_watch_lie([HumanMessage(content=_u), AIMessage(content=_t)],
                           watching=False) is None)

# 감시를 요청했더라도 응답이 **해줬다고 말하지 않으면** 손대지 않는다
check("못 한다고 답하면 교정하지 않는다",
      detect_watch_lie(_turn("죄송해요, 지금은 화면을 지켜볼 수 없어요."),
                       watching=False) is None)

# ⑤ 시작 고지는 **원문 그대로** 전달된다
#    LLM이 요약하면 간격·상한·중단법이 사라진다. 감시를 승인이 아니라 고지로
#    하기로 한 근거가 바로 그 고지다(DEVLOG 2026-09-03).
_notice = ("✓ '메모장' 창를 지켜볼게요. '오류'이(가) 보이면 바로 알려드릴게요.\n"
           "5초마다 화면을 확인하고, 변화가 있을 때만 화면을 읽어요.\n"
           "최대 10분(화면 읽기 20회)까지만 보고 자동으로 멈춰요.\n"
           '그만두려면 "그만 봐"라고 말씀해 주세요.')
_started = [HumanMessage(content="메모장 지켜봐"),
            AIMessage(content="",
                      tool_calls=[{"name": "watch_screen", "args": {}, "id": "c1"}]),
            ToolMessage(content=_notice, tool_call_id="c1", name="watch_screen"),
            AIMessage(content="네, 알려드릴게요!")]
_out = watch_notice_to_deliver(_started)
check("시작 고지를 원문 그대로 전달한다", _out == _notice, str(_out)[:80])
check("고지에 간격·상한·중단법이 살아 있다",
      _out is not None and "초마다" in _out and "까지만" in _out and "그만 봐" in _out)

# 거절(✗)은 고지가 아니다 — LLM이 전해도 된다
_refused = [HumanMessage(content="메모장 지켜봐"),
            AIMessage(content="",
                      tool_calls=[{"name": "watch_screen", "args": {}, "id": "c1"}]),
            ToolMessage(content="✗ 이미 '오류'를 지켜보는 중이라 새로 시작하지 않았어요.",
                        tool_call_id="c1", name="watch_screen"),
            AIMessage(content="이미 보고 있어요.")]
check("거절은 고지로 덮어쓰지 않는다", watch_notice_to_deliver(_refused) is None)
check("감시와 무관한 턴은 고지가 없다",
      watch_notice_to_deliver([HumanMessage(content="안녕"),
                               AIMessage(content="안녕하세요!")]) is None)


# ── 12. 도구 미호출 재시도 (BL-19) ────────────────────────────────
print("")
print("[12] BL-19 — 감시 요청인데 도구를 안 불렀으면 한 번 더 묻는다")

from core.graph import needs_watch_retry, with_watch_directive
from langchain_core.messages import SystemMessage


class _Resp:
    def __init__(self, tool_calls=None):
        self.tool_calls = tool_calls or []


check("감시 요청 + 도구 미호출 + 꺼짐 → 재시도한다",
      needs_watch_retry("메모장 지켜보다가 오류 뜨면 알려줘", _Resp(), watching=False))
check("'지켜보'가 없는 요청도 재시도 대상",
      needs_watch_retry("다운로드 끝나면 알려줘", _Resp(), watching=False))
check("도구를 불렀으면 재시도하지 않는다",
      not needs_watch_retry("메모장 지켜봐",
                            _Resp([{"name": "watch_screen"}]), watching=False))
check("이미 감시 중이면 재시도하지 않는다",
      not needs_watch_retry("메모장 지켜봐", _Resp(), watching=True))
check("감시와 무관한 요청은 재시도하지 않는다",
      not needs_watch_retry("메모장 열어줘", _Resp(), watching=False))

# 중단은 **돌고 있을 때만** 다시 묻는다. 이미 꺼져 있으면 결과가 같다.
check("중단 요청 + 감시 중 → 재시도한다",
      needs_watch_retry("그만 봐", _Resp(), watching=True))
check("중단 요청인데 이미 꺼져 있으면 재시도하지 않는다",
      not needs_watch_retry("그만 봐", _Resp(), watching=False))

# 재시도 메시지 — 시스템 메시지를 **교체**한다(두 개면 Gemini가 무시하거나 400)
_m = [SystemMessage(content="원래 프롬프트"), HumanMessage(content="메모장 지켜봐")]
_out = with_watch_directive(_m)
check("재시도 메시지의 SystemMessage는 하나뿐이다",
      sum(1 for x in _out if isinstance(x, SystemMessage)) == 1)
check("재시도 지시가 원래 프롬프트 뒤에 붙는다",
      _out[0].content.startswith("원래 프롬프트") and "반드시 지금 호출" in _out[0].content)
check("사람 발화는 그대로 남는다", _out[-1].content == "메모장 지켜봐")

# agent 노드가 실제로 재시도하는가 — 첫 호출은 말만, 두 번째는 도구
class _FlakyLLM:
    """첫 invoke는 도구를 안 부르고, 두 번째는 부른다."""
    def __init__(self): self.calls = []
    def bind_tools(self, tools): return self
    def invoke(self, msgs):
        self.calls.append(msgs)
        if len(self.calls) == 1:
            return AIMessage(content="오류 뜨면 바로 알려드릴게요!")
        return AIMessage(content="", tool_calls=[
            {"name": "watch_screen", "args": {"what": "오류"}, "id": "c1"}])


from core.graph import build_pluiz_graph
_flaky = _FlakyLLM()
_g = build_pluiz_graph(
    llm=_flaky, tools=[], security_check=lambda t: (False, ""),
    is_watching=lambda: False)
_res = _g.invoke({"messages": [HumanMessage(content="메모장 지켜보다가 오류 뜨면 알려줘")]},
                 {"configurable": {"thread_id": "bl19_retry"}})
check("agent가 도구 미호출을 보고 한 번 다시 묻는다", len(_flaky.calls) == 2,
      f"invoke {len(_flaky.calls)}회")
check("재시도 호출에 지시가 실려 있다",
      len(_flaky.calls) == 2
      and any("반드시 지금 호출" in getattr(m, "content", "") for m in _flaky.calls[1]))
# tools=[] 라 도구 노드가 없어서 실제 실행은 안 된다(그래서 마지막 응답은
# _NOTHING_HAPPENED_MSG다). 여기서 볼 건 **재시도 결과가 채택됐는가**뿐이다.
_adopted = [m for m in _res["messages"]
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)]
check("재시도 결과(도구 호출)가 채택된다", len(_adopted) == 1,
      f"도구호출 AIMessage {len(_adopted)}개")
check("첫 응답(말뿐인 답)은 채택되지 않는다",
      not any("알려드릴게요" in str(getattr(m, "content", ""))
              for m in _res["messages"] if isinstance(m, AIMessage)))



# ── 13. 재시도 패스의 도구 호출 강제 (BL-19 원인 ②) ────────────────
print("")
print("[13] BL-19 원인 ② — 재시도는 설득이 아니라 tool_choice로 강제한다")

# 왜: 2026-09-04 나쁜 구간에서는 첫 패스도 재시도(설득)도 함께 실패했다(0/10).
# 설득은 확률을 올릴 뿐이고, 강제는 구조다. 여기서 보는 것은 세 가지다 —
#   ① 강제가 걸리는가(그리고 **재시도 패스에만** 걸리는가)
#   ② 무엇을 강제하는가(중단 요청이면 stop_watching이어야 한다)
#   ③ 강제를 못 쓰는 LLM에서 **오늘과 똑같이** 동작하는가 (미지원 · 예외 둘 다)
from langchain_core.tools import tool as mktool

_watching = {"on": False}


@mktool
def watch_screen(what: str = "변화") -> str:
    """화면을 지켜본다(가짜)."""
    _watching["on"] = True
    return "지켜볼게요"


@mktool
def stop_watching() -> str:
    """감시를 멈춘다(가짜)."""
    _watching["on"] = False
    return "그만 봤어요"


_FAKE_TOOLS = [watch_screen, stop_watching]


class _ForcedLLM:
    """`tool_choice`를 받아 주는 LLM — **강제당했을 때만** 도구를 부른다.

    설득이 안 통하는 나쁜 구간을 그대로 흉내 낸다. 강제 바인딩은 새 인스턴스로
    돌려주되 기록은 부모에 모은다(제품 코드가 바인딩을 캐시하기 때문).
    """

    def __init__(self, parent=None, forced=None, raise_on_invoke=False):
        self.parent = parent or self
        self.forced = forced
        self.raise_on_invoke = raise_on_invoke
        self.forced_names = []   # 무엇을 강제하려 했나
        self.invoked = []        # 실제로 무엇으로 불렸나 (None = 설득)

    def bind_tools(self, tools, tool_choice=None):
        if tool_choice is None:
            return self
        self.parent.forced_names.append(tool_choice)
        return _ForcedLLM(parent=self.parent, forced=tool_choice,
                          raise_on_invoke=self.parent.raise_on_invoke)

    def invoke(self, msgs):
        self.parent.invoked.append(self.forced)
        if self.forced is None:
            return AIMessage(content="네, 계속 지켜볼게요!")   # 말로만 — 나쁜 구간
        if self.raise_on_invoke:
            raise RuntimeError("tool_choice 거부(가짜)")
        return AIMessage(content="", tool_calls=[
            {"name": self.forced, "args": {}, "id": "f1"}])


def _run13(llm, text, *, watching_start, thread):
    _watching["on"] = watching_start
    g = build_pluiz_graph(llm=llm, tools=_FAKE_TOOLS,
                          security_check=lambda t: (False, ""),
                          is_watching=lambda: _watching["on"])
    return g.invoke({"messages": [HumanMessage(content=text)]},
                    {"configurable": {"thread_id": thread}})


# ① 감시 요청 — watch_screen을 강제하고, 도구가 실제로 돈다
_m13 = _ForcedLLM()
_r13 = _run13(_m13, "메모장 지켜보다가 오류 뜨면 알려줘",
              watching_start=False, thread="bl19_forced_watch")
check("재시도에서 watch_screen 호출을 강제한다",
      _m13.forced_names == ["watch_screen"], f"강제={_m13.forced_names}")
check("첫 패스는 강제하지 않는다(평범한 대화를 망치지 않는다)",
      _m13.invoked and _m13.invoked[0] is None, f"호출={_m13.invoked}")
check("강제된 도구가 실제로 실행된다",
      any(isinstance(m, ToolMessage) and m.name == "watch_screen"
          for m in _r13["messages"]))
check("감시가 켜지면 재시도가 멈춘다(무한 재시도 방지)",
      _m13.invoked.count("watch_screen") == 1, f"호출={_m13.invoked}")

# ② 중단 요청 — stop_watching을 강제해야 한다(엉뚱한 도구를 강제하면 더 나쁘다)
_m13b = _ForcedLLM()
_r13b = _run13(_m13b, "그만 봐", watching_start=True, thread="bl19_forced_stop")
check("중단 요청이면 stop_watching을 강제한다",
      _m13b.forced_names == ["stop_watching"], f"강제={_m13b.forced_names}")
check("중단 도구가 실제로 실행된다",
      any(isinstance(m, ToolMessage) and m.name == "stop_watching"
          for m in _r13b["messages"]))


# ③-a tool_choice를 모르는 LLM — 오늘의 설득 재시도로 폴백한다
class _NoChoiceLLM:
    """`bind_tools(tools)`만 받는 옛 인터페이스(=모든 기존 mock·미지원 provider)."""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, msgs):
        self.calls += 1
        if self.calls == 2:      # 설득 재시도에서만 도구를 부른다
            return AIMessage(content="", tool_calls=[
                {"name": "watch_screen", "args": {}, "id": "n1"}])
        return AIMessage(content="지켜볼게요!")


_m13c = _NoChoiceLLM()
_r13c = _run13(_m13c, "메모장 지켜보다가 오류 뜨면 알려줘",
                watching_start=False, thread="bl19_nochoice")
# 3회 = 첫 패스(말뿐) + 설득 재시도(도구) + 도구 실행 뒤 마무리
check("tool_choice 미지원이면 설득 재시도로 폴백한다(=오늘 경로)",
      _m13c.calls == 3, f"invoke {_m13c.calls}회")
check("폴백 경로에서도 도구가 실행된다",
      any(isinstance(m, ToolMessage) and m.name == "watch_screen"
          for m in _r13c["messages"]))

# ③-b 강제가 예외를 던져도 **턴을 죽이지 않는다** — 설득 재시도로 내려간다
_m13d = _ForcedLLM()
_m13d.raise_on_invoke = True
_r13d = _run13(_m13d, "메모장 지켜보다가 오류 뜨면 알려줘",
                watching_start=False, thread="bl19_forced_boom")
check("강제 호출이 실패해도 턴이 죽지 않는다",
      isinstance(_r13d.get("messages", [])[-1], AIMessage))
check("강제 실패 뒤 설득 재시도가 실제로 돈다",
      _m13d.invoked.count(None) == 2, f"호출={_m13d.invoked}")

# ── 결과 ──────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"결과: {passed}/{total} 통과")
print(f"{'=' * 60}")
sys.exit(0 if passed == total else 1)
