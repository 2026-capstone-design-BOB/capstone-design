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
def _ev(eid, title, start, end):
    return {"id": eid, "summary": title,
            "start": {"dateTime": start}, "end": {"dateTime": end}}


class FakeEvents:
    def __init__(self, items):
        self.items = items
        self.patched = []
        self.inserted = []

    def list(self, **kw):
        items = self.items
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


ONE = [_ev("e1", "캡스톤 미팅",
           "2026-10-03T13:00:00+09:00", "2026-10-03T14:00:00+09:00")]


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
                 "2026-10-05T10:00:00+09:00", "2026-10-05T11:00:00+09:00")]
out2, ev2 = drive(TWO, title="캡스톤", duration_minutes=180)
check("🚨 여럿이면 **고르지 않는다**", ev2.patched == [], str(ev2.patched))
check("   후보를 보여 주고 묻는다",
      "2개" in out2 and "캡스톤 미팅" in out2 and "캡스톤 발표" in out2, out2)

ALLDAY = [{"id": "e3", "summary": "휴가",
           "start": {"date": "2026-10-09"}, "end": {"date": "2026-10-10"}}]
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


print(f"{NL}결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
