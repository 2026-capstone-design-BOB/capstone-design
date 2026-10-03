# -*- coding: utf-8 -*-
"""일정 **고치기** — 그리고 «무엇을 어떻게 바꿨나»를 말한다 (BL-88 · 2026-10-02 실기)

실행: python tests/test_calendar_update.py

## 왜 이 테스트가 있나

```
21:46:00  내일 13시에 캡스톤 미팅 만들어줘  → create_calendar_event  (1시간)
21:46:45  1시간이 아니라 3시간으로 수정해 줘 → 요청=없음 (되물었다)
21:47:05  맞아                              → create_calendar_event  ← 🚨 둘이 됐다
```

🔑 **모델이 게으른 게 아니었다.** 캘린더 도구가 `create` 와 `list` **둘뿐**이라
«고치기»를 할 방법이 **원리적으로 없었다.** 할 수 있는 유일한 일을 한 것이다.

🙋 그리고 사용자가 더 큰 규칙을 하나 제안했다:

> *"모호할 수 있거나 삭제·수정과 관련된 작업을 하면 내가 말한 의도를 따르되
>   **작업 수행 이후 고쳐진 것을 말하도록** 하는 게 좋지 않을까"*

🚨 **그걸 프롬프트로 부탁하지 않는다.** 도구가 돌려주는 문장에 전/후가 들어 있으면
모델은 **그걸 옮길 수밖에 없다** — *«프롬프트는 확률을 올릴 뿐이고 보장하는 건
구조다»* 의 그 자리다.

## ⚠️ 구글에 연결하지 않는다

가짜 `service` 를 끼워 **도구를 실제로 한 바퀴 돌린다.** 소스 대조가 아니다(BL-83).
"""
import io
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

import tools.calendar as C  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)
_SRC = io.open(os.path.join(_ROOT, "tools", "calendar.py"), encoding="utf-8").read()

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name}" + (f"   → {detail}" if detail else ""))


# ── 가짜 캘린더 ───────────────────────────────────────────────────
#
# 🚨 **`timeMin`/`timeMax` 를 실제로 지킨다.** 예전 가짜는 창을 무시하고 전부
#   돌려줬는데, 그래서 «날짜를 주면 하나로 좁혀진다»를 **한 번도 안 쟀다** —
#   BL-92 ① 이 그 틈으로 들어왔다. 안 고르는 쪽만 세고 **좁히는 쪽을 안 센 것**이다.
def _ev(eid, title, start, end):
    return {"id": eid, "summary": title,
            "start": {"dateTime": start}, "end": {"dateTime": end}}


def _start_of(ev):
    s = ev.get("start", {})
    if "date" in s:
        return datetime.strptime(s["date"], "%Y-%m-%d").astimezone()
    return datetime.fromisoformat(s["dateTime"])


class FakeEvents:
    def __init__(self, items):
        self.items = items
        self.patched = []
        self.inserted = []
        self.windows = []

    def list(self, timeMin=None, timeMax=None, **kw):
        self.windows.append((timeMin, timeMax))
        lo = datetime.fromisoformat(timeMin) if timeMin else None
        hi = datetime.fromisoformat(timeMax) if timeMax else None
        items = [e for e in self.items
                 if (lo is None or _start_of(e) >= lo)
                 and (hi is None or _start_of(e) < hi)]
        return type("R", (), {"execute": lambda s=None: {"items": items}})()

    def patch(self, calendarId=None, eventId=None, body=None):
        self.patched.append((eventId, body))
        return type("R", (), {"execute": lambda s=None: {"id": eventId}})()

    def insert(self, calendarId=None, body=None):
        self.inserted.append(body)
        return type("R", (), {"execute": lambda s=None: {"id": "new"}})()


class FakeService:
    def __init__(self, items):
        self._ev = FakeEvents(items)

    def events(self):
        return self._ev


def drive(items, **kwargs):
    """가짜 캘린더를 끼우고 `update_calendar_event` 를 실제로 돌린다."""
    svc = FakeService(items)
    orig = C._calendar_service
    C._calendar_service = lambda: svc
    try:
        return C.update_calendar_event.invoke(kwargs), svc._ev
    finally:
        C._calendar_service = orig


def _day(n: int) -> str:
    """오늘로부터 n일. 🚨 **날짜를 못 박지 않는다** — 가짜가 이제 `timeMin/timeMax` 를
    실제로 지켜서, 고정 날짜를 쓰면 그 날이 지나는 순간 테스트가 저절로 깨진다."""
    return (datetime.now() + timedelta(days=n)).strftime("%Y-%m-%d")


ONE = [_ev("e1", "캡스톤 미팅",
           f"{_day(0)}T13:00:00+09:00", f"{_day(0)}T14:00:00+09:00")]


# ═══ ① 고치는 도구가 **있다** ══════════════════════════════════════
print(f"{NL}=== ① 고치는 도구가 있다 (BL-88) ===")
check("update_calendar_event 가 있다", hasattr(C, "update_calendar_event"))
check("🚨 **지우는 도구는 일부러 없다** (고칠 수 있으면 필요 없다)",
      "delete_calendar_event" not in _SRC)
check("왜 안 만들었는지 적어 뒀다", "지우는 도구는 일부러 안 만든다" in _SRC)
from core.tool_registry import get_all_tools  # noqa: E402
_names = {t.name for t in get_all_tools()}
check("도구 목록에 **올라가 있다** (안 올리면 모델이 못 부른다)",
      "update_calendar_event" in _names)


# ═══ ② 🚨 **새로 만들지 않는다** ═══════════════════════════════════
#
#   이게 BL-88 의 전부다. 고치랬는데 하나 더 생기면 사용자가 직접 지워야 한다.
print(f"{NL}=== ② \U0001f6a8 고치랬으면 고친다 (새로 안 만든다) ===")
out, ev = drive(ONE, title="캡스톤", duration_minutes=180)
check("🚨 **insert 를 한 번도 안 부른다**", ev.inserted == [], str(ev.inserted))
check("   대신 patch 를 부른다", len(ev.patched) == 1, str(ev.patched))
check("   그 일정을 고친다 (id 가 맞다)",
      ev.patched and ev.patched[0][0] == "e1")
_body = ev.patched[0][1] if ev.patched else {}
check("길이가 3시간이 된다 (13:00 → 16:00)",
      _body.get("end", {}).get("dateTime", "").endswith("16:00:00"), str(_body))
check("시작 시각은 안 건드린다 (안 바꾸라고 한 것은 그대로)",
      _body.get("start", {}).get("dateTime", "").endswith("13:00:00"), str(_body))


# ═══ ③ 🚨 **무엇을 어떻게 바꿨는지 말한다** (🙋 사용자 제안) ════════
print(f"{NL}=== ③ \U0001f6a8 전/후를 도구가 말한다 ===")
check("기존 일정을 고쳤다고 말한다", "기존" in out and "고쳤어요" in out, out)
check("🚨 **«새로 만들지 않았어요»를 못 박는다** (사용자가 걱정한 것이 그것이다)",
      "새로 만들지 않았어요" in out, out)
check("**전**이 들어 있다 (60분)", "전:" in out and "(60분)" in out, out)
check("**후**가 들어 있다 (180분)", "후:" in out and "(180분)" in out, out)
check("제목을 바꾸면 **뭐에서 뭐로** 바꿨는지 말한다",
      "'캡스톤 미팅'" in drive(ONE, title="캡스톤", new_title="졸작 미팅")[0]
      and "'졸작 미팅'" in drive(ONE, title="캡스톤", new_title="졸작 미팅")[0])


# ═══ ④ 🚨 모르면 **안 고친다** ══════════════════════════════════════
#
#   엉뚱한 일정을 고치면 되돌릴 수 없고, 사용자는 고쳐진 줄 안다.
#   `read_email` 이 *«여럿이면 고르지 않는다»* 로 세워 둔 규칙과 같은 자리다.
print(f"{NL}=== ④ \U0001f6a8 모르면 안 고친다 ===")
out0, ev0 = drive([], title="없는일정")
check("못 찾으면 **아무것도 안 고친다**", ev0.patched == [] and ev0.inserted == [])
check("   그리고 못 찾았다고 말한다 (없다고 단정하지 않는다)",
      "못 찾았어요" in out0, out0)
check("   기본 달력만 봤다고 **범위를 밝힌다**", "기본 달력" in out0, out0)

TWO = ONE + [_ev("e2", "캡스톤 발표",
                 f"{_day(2)}T10:00:00+09:00", f"{_day(2)}T11:00:00+09:00")]
out2, ev2 = drive(TWO, title="캡스톤", duration_minutes=180)
check("🚨 여럿이면 **고르지 않는다**", ev2.patched == [], str(ev2.patched))
check("   후보를 보여 주고 묻는다",
      "2개" in out2 and "캡스톤 미팅" in out2 and "캡스톤 발표" in out2, out2)

ALLDAY = [{"id": "e3", "summary": "휴가",
           "start": {"date": _day(6)}, "end": {"date": _day(7)}}]
out3, ev3 = drive(ALLDAY, title="휴가", duration_minutes=180)
check("하루 종일 일정은 **안 건드리고 그렇게 말한다**",
      ev3.patched == [] and "하루 종일" in out3, out3)


# ═══ ⑤ 못 고쳤으면 **못 고쳤다고 한다** ════════════════════════════
#
#   🚨 여기서 «그럼 새로 만들자»로 빠지는 것이 2026-10-02 에 일정이 둘이 된 길이다.
print(f"{NL}=== ⑤ \U0001f6a8 못 고치면 새로 만들지 않는다 ===")


class Boom(FakeEvents):
    def patch(self, **kw):
        raise RuntimeError("quota")


svc = FakeService(ONE)
svc._ev = Boom(ONE)
_orig = C._calendar_service
C._calendar_service = lambda: svc
try:
    out4 = C.update_calendar_event.invoke({"title": "캡스톤", "duration_minutes": 180})
finally:
    C._calendar_service = _orig
check("실패하면 ✗ 로 말한다", out4.startswith("✗"), out4)
check("🚨 **실패해도 insert 로 도망가지 않는다**", svc._ev.inserted == [])


# ═══ ⑥ 연결이 막히면 **이유별로** 말한다 ════════════════════════════
print(f"{NL}=== ⑥ 막힌 이유마다 할 말이 다르다 ===")
import tools.google_auth as A  # noqa: E402

_orig = C._calendar_service


def _raise(e):
    def f():
        raise e
    return f


C._calendar_service = _raise(A.NeedLogin("x"))
try:
    out5 = C.update_calendar_event.invoke({"title": "캡스톤"})
finally:
    C._calendar_service = _orig
check("로그인이 안 됐으면 **다시 로그인하라고** 한다 (BL-74 와 같은 길)",
      out5 == A.NEED_LOGIN, out5)


# ═══ ⑦ 🚨 **«그 하나»를 집을 수 있다** (BL-92 · 3차 실기) ═══════════
#
#   👤 아까 만든 일정 3시간으로 바꿔 줘    🤖 여러 개 있어요. 3일 캡스톤? 4일 미팅?
#   👤 4일                                🤖 4일 미팅이 여러 개 검색되네요      ← 🚨
#   👤 10월 4일 미팅 9시 한 개밖에 없지 않아 🤖 여전히 여러 개…                  ← 🚨
#
#   🔑 모델이 게으른 게 아니었다. **넘길 자리가 없었다** — BL-88 에서 배운 것과
#     같은 모양을, 그걸 고치면서 한 칸 옮겨 만들었다.
#
#   📌 여기서는 **날짜를 항상 넘긴다.** 그래야 창이 «오늘»에 안 묶이고,
#     이 테스트가 내년에도 같은 것을 잰다.
print(f"{NL}=== ⑦ \U0001f6a8 날짜·시각을 주면 하나로 좁혀진다 (BL-92) ===")

D3, D4 = "2026-10-03", "2026-10-04"
MANY = [
    _ev("x1", "캡스톤 미팅", f"{D3}T13:00:00+09:00", f"{D3}T14:00:00+09:00"),
    _ev("x2", "캡스톤 미팅", f"{D4}T11:00:00+09:00", f"{D4}T12:00:00+09:00"),
    _ev("x3", "미팅",       f"{D4}T09:00:00+09:00", f"{D4}T10:00:00+09:00"),
    _ev("x4", "미팅",       f"{D4}T15:00:00+09:00", f"{D4}T16:00:00+09:00"),
]

# 🔒 이 줄이 없으면 아래 전부가 **아무것도 안 재는 테스트**가 된다.
_win = FakeService(MANY).events().list(
    timeMin=f"{D4}T00:00:00+09:00", timeMax=f"{D4}T23:59:00+09:00").execute()["items"]
check("🔒 가짜 캘린더가 **timeMin/timeMax 를 실제로 지킨다** (안 지키면 아래가 공테스트)",
      len(_win) == 3, str([e["id"] for e in _win]))

# ── ① 날짜를 주면 **그 날만** 본다 ─────────────────────────────────
#   예전엔 `lo` 를 하루 앞으로 당겨서 10월 3일이 통째로 같이 들어왔다.
outA, evA = drive(MANY, title="캡스톤", date=D4, duration_minutes=180)
check("🚨 **하루 앞을 끌고 오지 않는다** — 10월 4일 '캡스톤' 은 하나뿐이다",
      len(evA.patched) == 1 and evA.patched[0][0] == "x2", outA)
check("   그래서 실제로 고쳐진다 (예전엔 '2개예요'로 막혔다)",
      outA.startswith("✓"), outA)

# ── ② 정확히 같은 제목이 있으면 **그쪽이 먼저** ────────────────────
outB, evB = drive(MANY, title="미팅", date=D4, duration_minutes=180)
check("🚨 '미팅' 이 '캡스톤 미팅' 을 **끌고 오지 않는다**",
      "캡스톤 미팅" not in outB, outB)
check("   같은 이름 둘만 후보로 남는다 (09:00 · 15:00)",
      "2개" in outB and evB.patched == [], outB)
_part = drive(MANY, title="캡스톤", date=D4, duration_minutes=180)[1].patched
check("   부분 일치는 **그대로 둔다** ('캡스톤' 만 말해도 '캡스톤 미팅' 을 찾는다)",
      len(_part) == 1 and _part[0][0] == "x2", str(_part))

# ── ③ 🚨 **시각으로 좁힐 자리가 생겼다** — 이게 핵심이다 ────────────
outC, evC = drive(MANY, title="미팅", date=D4, time="09:00", duration_minutes=180)
check("🚨 **'9시 거' 를 넘길 자리가 있다** (time 인자)",
      len(evC.patched) == 1 and evC.patched[0][0] == "x3", outC)
_bodyC = evC.patched[0][1] if evC.patched else {}
check("   그 일정이 3시간이 된다 (09:00 → 12:00)",
      _bodyC.get("end", {}).get("dateTime", "").endswith("12:00:00"), str(_bodyC))
check("   🚨 time 은 **찾을 시각**이다 — 시작 시각을 안 바꾼다",
      _bodyC.get("start", {}).get("dateTime", "").endswith("09:00:00"), str(_bodyC))
check("사람 말이 그대로 와도 읽는다 ('9시')",
      drive(MANY, title="미팅", date=D4, time="9시",
            duration_minutes=180)[1].patched[0][0] == "x3")
check("오후도 읽는다 ('오후 3시' → 15:00)",
      drive(MANY, title="미팅", date=D4, time="오후 3시",
            duration_minutes=180)[1].patched[0][0] == "x4")
check("🚨 **못 읽는 시각이면 좁히지 않는다** (엉뚱한 하나를 고르느니 되묻는다)",
      drive(MANY, title="미팅", date=D4, time="아무때나")[1].patched == [])
check("🚨 하나뿐인데 시각이 어긋나도 **0개로 만들지 않는다**",
      drive(ONE, title="캡스톤", time="23:00", duration_minutes=180)[1].patched != [])

# ── ④ 후보를 줄 때 **무엇을 더 말해야 집히는지** 알려준다 ──────────
#   목록만 주고 «어느 것인지»만 물으면 모델은 같은 호출을 반복한다.
check("🚨 후보와 함께 **좁히는 법**을 말한다", "좁혀져요" in outB, outB)
check("   그 값을 **어디에 넣는지**까지 말한다 (time='09:00')",
      "time='09:00'" in outB and "다시 부르세요" in outB, outB)

SAMEDAY = [_ev("y1", "주간 회의", f"{_day(0)}T10:00:00+09:00", f"{_day(0)}T11:00:00+09:00"),
           _ev("y2", "주간 회의", f"{_day(1)}T10:00:00+09:00", f"{_day(1)}T11:00:00+09:00")]
outE, _ = drive(SAMEDAY, title="주간 회의", duration_minutes=180)
check("   날짜만 다르면 **날짜를** 짚어 준다",
      "날짜" in outE and f"date='{_day(0)}'" in outE, outE)
check("   시각이 같으면 시각을 짚지 않는다 (쓸모없는 조언을 안 한다)",
      "time=" not in outE, outE)

# ── 도구가 그 손잡이를 **선언하고 있나** ───────────────────────────
_args = set(C.update_calendar_event.args.keys())
check("도구 시그니처에 **time 이 있다**", "time" in _args, str(sorted(_args)))
check("   new_time 과 **섞이지 않게** 적어 뒀다",
      "바꿀 시각이 아니라 **찾을 시각**입니다" in _SRC)


print(f"{NL}결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
