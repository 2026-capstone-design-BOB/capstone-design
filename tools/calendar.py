"""
캘린더 도구 - Google Calendar 일정 추가
방법 1 (기본): URL 스킴으로 Google Calendar 이벤트 생성 페이지 열기 (저장 버튼 클릭 필요)
방법 2 (자동): Google Calendar API + OAuth2로 완전 자동 등록 (token.json 필요)
"""

import subprocess
import os
import urllib.parse
from datetime import datetime, timedelta
from langchain_core.tools import tool

NL = chr(10)


def _parse_datetime(date_str: str, time_str: str) -> datetime | None:
    """
    날짜/시간 문자열 파싱. LLM이 이미 파싱한 값을 받음.
    date_str: 'YYYY-MM-DD' 형식
    time_str: 'HH:MM' 형식 (24시간)
    """
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _open_url(url: str):
    try:
        os.startfile(url)
    except Exception:
        subprocess.Popen(["start", url], shell=True)


def _create_via_url(title: str, start_dt: datetime, end_dt: datetime, description: str, location: str) -> str:
    """방법 1: Google Calendar URL 스킴으로 일정 생성 페이지 열기."""
    fmt = "%Y%m%dT%H%M%S"
    dates = f"{start_dt.strftime(fmt)}/{end_dt.strftime(fmt)}"
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": dates,
    }
    if description:
        params["details"] = description
    if location:
        params["location"] = location

    url = "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)
    _open_url(url)
    # 🚨 **✓ 가 아니라 ⚠️ 다** (2026-10-02 실기).
    #
    #   예전엔 `✓ … 추가 화면을 열었어요` 였다. 그런데 `✓` 는 *«의도한 일이 됐다»* 는
    #   표시이고, 여기서 된 것은 **창을 연 것**뿐이다 — 일정은 **아직 없다.**
    #   실기에서 모델이 그 `✓` 를 보고 *"일정을 만들었어요!"* 라고 답했다.
    #   🙋 *"내가 직접 일정 만들라고 하질 않나"*
    #
    # 🔑 `⚠️`(core/tool_result.py: *«도구는 돌았지만 목적이 달성되지 않았다»*)로 바꾸면
    #   `output_guard` 의 그물에 걸린다 — 말로 부탁하는 대신 **표시를 바로잡는다.**
    return (f"⚠️ 아직 일정이 만들어지지 않았어요. Google Calendar 에 '{title}' 추가 "
            "화면만 열어 뒀어요 — **저장 버튼을 눌러야** 등록돼요.")


def _create_via_api(title: str, start_dt: datetime, end_dt: datetime, description: str, location: str) -> str:
    """방법 2: Google Calendar API로 직접 일정 등록.

    🚨 **2026-09-24 — 여기에 인증 코드의 «두 번째 사본»이 있었다.** 자기 범위
      (`calendar.events` 하나)를 들고 있어서, 사용자가 *"회의 잡아줘"* 를 **먼저** 하면
      토큰이 **캘린더 전용으로 굳고** 그 뒤 메일을 부르면 401 이 난다. 토큰 파일은
      «있으므로» 다시 묻지도 않는다.

    🔑 `_calendar_service` 를 고칠 때 이 사본은 안 고쳐졌다 — **한쪽만 갱신되는**
      바로 그 모양이고, `tests/test_gmail.py` ⑨ 가 잡았다.
    """
    from tools.google_auth import get_service
    service = get_service("calendar", "v3")

    tz = "Asia/Seoul"
    event = {
        "summary": title,
        "start":   {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz},
        "end":     {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),   "timeZone": tz},
    }
    if description:
        event["description"] = description
    if location:
        event["location"] = location

    result = service.events().insert(calendarId="primary", body=event).execute()
    link = result.get("htmlLink", "")
    return f"✓ '{title}' 일정이 캘린더에 추가됐어요!"


@tool
def create_calendar_event(
    title: str,
    date: str,
    time: str,
    duration_minutes: int = 60,
    description: str = "",
    location: str = "",
) -> str:
    """
    Google Calendar에 일정을 추가합니다.
    title: 일정 제목 (예: 팀 미팅, 병원 예약)
    date: 날짜 (YYYY-MM-DD 형식, 예: 2026-06-15)
    time: 시작 시간 (HH:MM 24시간 형식, 예: 14:00)
    duration_minutes: 일정 길이 (분 단위, 기본값 60)
    description: 일정 설명 (선택)
    location: 장소 (선택)
    """
    start_dt = _parse_datetime(date, time)
    if not start_dt:
        return f"✗ 날짜/시간 형식 오류: date='{date}', time='{time}' (YYYY-MM-DD, HH:MM 형식으로 전달해주세요)"

    end_dt = start_dt + timedelta(minutes=duration_minutes)

    # 방법 2 시도 (calendar_credentials.json 있을 때만)
    try:
        return _create_via_api(title, start_dt, end_dt, description, location)
    except Exception as e:                                    # noqa: BLE001
        # 🚨 **«로그인만 안 된 것»은 URL 로 도망가지 않는다** (2026-10-02 실기).
        #
        #   예전엔 전부 한 덩어리로 URL 폴백이었다. 그래서 토큰이 없을 때
        #   *"내일모레 9시에 미팅 만들어줘"* 가 **브라우저 창을 띄우고 «저장 버튼을
        #   눌러주세요»** 로 끝났다 — 🙋 *"내가 직접 일정 만들라고 하질 않나."*
        #
        # 🔑 **로그인은 우리가 열어 줄 수 있다**(BL-84 `connect_google`). 할 수 있는
        #   일을 두고 사용자에게 떠넘기지 않는다. 막힌 이유마다 할 일이 다르다는
        #   `tools/google_auth.py` 의 규칙이 여기까지 와야 한다.
        from tools.google_auth import NeedLogin, message_for
        if isinstance(e, NeedLogin):
            return message_for(e)
        # 자격증명 자체가 없거나 패키지가 없으면 **URL 말고는 길이 없다** → 폴백.
        if not isinstance(e, (FileNotFoundError, ImportError)):
            print(f"[calendar] API 오류, URL fallback: {e}")

    # 방법 1: URL 스킴 fallback
    return _create_via_url(title, start_dt, end_dt, description, location)


# ══════════════════════════════════════════════════════════════════════
# 일정 읽기 — 2026-09-24 신설 (페르소나 §3-E · §5 🟢 첫 항목)
#
# 🚨 **쓰기만 있고 읽기가 없었다.** *"오늘 일정 뭐 있어?"* 가 갈 곳이 없어 LLM
#   잡담으로 끝났고, 그러면 **없는 일정을 지어낼 수 있다** — BL-60·61 이 밝기·볼륨에서
#   정확히 그 모양이었다(*"지금 밝기 얼마야"* → «✓ 밝기: 40% → 80%» 를 지어냈다).
#   [페르소나 §4-①](../docs/planning/페르소나_직장인.md)이 «새 도구는 읽기·쓰기 한 쌍으로»
#   를 규칙으로 굳혀 둔 자리다.
#
# 🔑 **덤으로 «그 회의 링크 열어줘»가 풀린다.** 그건 도구가 없어서가 아니라
#   (`open_url` 은 있다) **일정을 못 읽어서 링크를 몰랐던** 것이다.
#
# 🚨 **쓰기와 달리 URL 대체 경로가 없다.** 일정 «추가»는 브라우저를 열어 사람이 저장
#   버튼을 누르면 되지만, 「읽기」는 우리가 값을 받아와야 한다. 그래서 자격증명이
#   없으면 **모른다고 말한다** — 브라우저를 열어 놓고 «확인했어요»라고 하지 않는다.
# ══════════════════════════════════════════════════════════════════════

_NO_CREDS = ("✗ 캘린더를 읽으려면 Google 계정 연결이 한 번 필요해요. "
             "지금은 일정을 확인할 수 없어요 — 캘린더를 직접 열어 보시겠어요?")


def _calendar_service():
    """인증된 Calendar 서비스. 자격증명이 없으면 `NotConnected`.

    🚨 **권한 범위를 여기서 정하지 않는다.** 예전에는 이 함수가 자기 범위
      (`calendar.events` 하나)를 들고 있었는데, 그러면 캘린더를 먼저 쓴 사용자의
      토큰에 **메일 권한이 없는 채로 굳는다** — 그 뒤 메일을 부르면 401 이 나고,
      토큰 파일은 «있으므로» 다시 묻지도 않는다.

    🔑 같은 사실(요청할 권한)이 두 파일에 흩어지면 한쪽만 갱신된다.
      그래서 `tools/google_auth.py` 한 곳에만 둔다. (2026-09-24)
    """
    from tools.google_auth import get_service
    return get_service("calendar", "v3")


def _fmt_when(ev: dict) -> str:
    """일정 하나의 «언제». 종일 일정은 시간이 없다."""
    start = ev.get("start", {})
    if "date" in start:                 # 종일 일정
        return "하루 종일"
    raw = start.get("dateTime", "")
    try:
        return datetime.fromisoformat(raw).strftime("%H:%M")
    except Exception:
        return raw[:16].replace("T", " ")


@tool
def list_calendar_events(date: str = "", days: int = 1) -> str:
    """캘린더에서 일정을 읽어 알려줍니다. "오늘 일정 뭐야", "내일 회의 있어?" 같은 질문에 씁니다.

    date: 조회 시작 날짜 (YYYY-MM-DD). 비우면 오늘.
    days: 며칠치를 볼지 (기본 1 = 그 날 하루).
    """
    try:
        base = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
    except ValueError:
        return f"✗ 날짜 형식 오류: '{date}' (YYYY-MM-DD 형식으로 주세요)"

    start = base.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=max(1, days))

    try:
        service = _calendar_service()
    except Exception as e:                                    # noqa: BLE001
        # 🚨 막힌 이유마다 할 일이 다르다 — 자격증명 없음 · 패키지 없음 · 로그인 안 됨.
        from tools.google_auth import NotConnected, message_for
        if isinstance(e, NotConnected):
            return message_for(e)
        if isinstance(e, (FileNotFoundError, ImportError)):
            return _NO_CREDS
        raise
    except Exception as e:
        # 🚨 조용히 «일정이 없어요»로 떨어지지 않는다 — «못 읽었다»와 «없다»는
        #   완전히 다른 말이고, 뒤엣말이 나가면 사용자가 회의를 놓친다.
        return f"✗ 캘린더를 읽지 못했어요 ({type(e).__name__}). 직접 확인해 보시겠어요?"

    try:
        res = service.events().list(
            calendarId="primary",
            timeMin=start.astimezone().isoformat(),
            timeMax=end.astimezone().isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=25,
        ).execute()
        items = res.get("items", [])
    except Exception as e:
        return f"✗ 캘린더를 읽지 못했어요 ({type(e).__name__}). 직접 확인해 보시겠어요?"

    when = "오늘" if not date and days == 1 else f"{start.strftime('%m월 %d일')}부터 {days}일간"
    if not items:
        # 🚨 **«없다»고 단정하지 않는다** (BL-80 · 2026-09-30).
        #   위 `except` 는 «못 읽었다»를 잡지만, 이 경로는 **읽기에 성공했는데 0건**
        #   이다. 그런데 우리가 읽은 것은 `calendarId="primary"` **하나뿐**이고,
        #   구독한 달력·공유받은 달력·팀 달력은 **보지도 않았다.**
        #   그래서 «일정이 없어요»는 우리가 **확인할 수 없는 말**이다.
        #
        # 🔑 무엇을 봤는지 말하면 사용자가 스스로 판단할 수 있다.
        #   2026-09-29 에 실제로 «없어요»라고 답했다가 사용자가 일정을 놓칠 뻔했다.
        #   (그날의 «다른 달력에 있다»는 진단 자체는 09-30 실기에서 재현되지 않았다.
        #    그래도 **말이 확인 범위를 넘어서는 것**은 그대로 남아 있어서 고친다.)
        return (f"✓ {when} 기본 달력에는 일정이 없어요.\n"
                "(다른 달력에 있는 일정은 제가 볼 수 없어요.)")

    lines = []
    for ev in items:
        title = ev.get("summary") or "(제목 없음)"
        piece = f"  • {_fmt_when(ev)} {title}"
        loc = ev.get("location")
        if loc:
            piece += f" ({loc})"
        lines.append(piece)

    return f"✓ {when} 일정 {len(items)}개예요:\n" + "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 일정 고치기 — 2026-10-02 실기 신설 (BL-88)
#
# 🚨 **«수정»할 수단이 없어서 하나 더 생겼다.**
#
#     21:46:00  내일 13시에 캡스톤 미팅 만들어줘  → create  (1시간)
#     21:46:45  1시간이 아니라 3시간으로 수정해 줘 → 되물었다
#     21:47:05  맞아                              → create  ← 두 번째가 생겼다
#
#   모델이 게으른 게 아니었다. 캘린더 도구가 `create` 와 `list` **둘뿐**이라
#   «고치기»를 할 방법이 **원리적으로 없었다.** 할 수 있는 유일한 일을 한 것이다.
#
# 🔑 **지우는 도구는 일부러 안 만든다.** 고칠 수 있으면 «지우고 새로 만들기»가
#   필요 없고, 이 저장소의 규칙이 *«도구 목록이 경계를 같이 진다»* 이다
#   (`gmail_send` 를 아예 안 만든 것과 같은 이유). 지우기는 **요청이 생기면** 만든다.
#
# 🚨 **그리고 이 도구는 «무엇을 어떻게 바꿨는지»를 스스로 말한다**
#   (🙋 2026-10-02 사용자 제안).
#
#     *"모호할 수 있거나 삭제·수정과 관련된 작업을 하면 내가 말한 의도를 따르되
#       작업 수행 이후 고쳐진 것을 말하도록 하는 게 좋지 않을까"*
#
#   그 말을 **프롬프트로 부탁하지 않는다.** 도구가 돌려주는 문장에 전/후가 들어
#   있으면 모델은 그걸 옮길 수밖에 없다 — 이 저장소가 반복해서 적어 둔
#   *«프롬프트는 확률을 올릴 뿐이고 보장하는 건 구조다»* 의 그 자리다.
# ══════════════════════════════════════════════════════════════════════


def _ev_span(ev: dict) -> str:
    """«10월 03일 13:00~14:00 (60분)». 전/후를 말하려면 길이가 보여야 한다."""
    s0, e0 = ev.get("start", {}), ev.get("end", {})
    if "date" in s0:
        return f"{s0.get('date', '')} 하루 종일"
    try:
        a = datetime.fromisoformat(s0.get("dateTime", ""))
        b = datetime.fromisoformat(e0.get("dateTime", ""))
        mins = int((b - a).total_seconds() // 60)
        return f"{a.strftime('%m월 %d일 %H:%M')}~{b.strftime('%H:%M')} ({mins}분)"
    except Exception:
        return s0.get("dateTime", "")[:16].replace("T", " ")


def _find_events(service, title: str, date: str) -> list:
    """제목으로 찾는다. 🚨 **고를 범위를 넓히지 않는다** — 앞뒤 한 달만 본다."""
    try:
        base = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
    except ValueError:
        base = datetime.now()
    lo = (base - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    hi = base + timedelta(days=30 if not date else 1)
    res = service.events().list(
        calendarId="primary",
        timeMin=lo.astimezone().isoformat(), timeMax=hi.astimezone().isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=50,
    ).execute()
    key = (title or "").strip().replace(" ", "")
    if not key:
        return list(res.get("items", []))
    return [e for e in res.get("items", [])
            if key in (e.get("summary") or "").replace(" ", "")]


@tool
def update_calendar_event(
    title: str,
    date: str = "",
    new_title: str = "",
    new_date: str = "",
    new_time: str = "",
    duration_minutes: int = 0,
    location: str = "",
    description: str = "",
) -> str:
    """이미 있는 캘린더 일정을 **고칩니다**. "아까 만든 일정 3시간으로 바꿔줘" 같은 요청에 씁니다.

    🚨 고치는 요청이면 새 일정을 만들지 말고 반드시 이 도구를 쓰세요.
    title: 고칠 일정의 제목 (일부만 맞아도 됩니다. 예: 캡스톤)
    date: 그 일정의 날짜 (YYYY-MM-DD). 비우면 앞뒤 한 달에서 찾습니다.
    new_title / new_date / new_time: 바꿀 값. 안 바꿀 것은 비워 두세요.
    duration_minutes: 새 길이(분). 0이면 안 바꿉니다.
    location / description: 바꿀 값 (선택).
    """
    try:
        service = _calendar_service()
    except Exception as e:                                    # noqa: BLE001
        from tools.google_auth import NotConnected, message_for
        if isinstance(e, NotConnected):
            return message_for(e)
        if isinstance(e, (FileNotFoundError, ImportError)):
            return _NO_CREDS
        return f"✗ 캘린더에 연결하지 못했어요 ({type(e).__name__})."

    try:
        found = _find_events(service, title, date)
    except Exception as e:                                    # noqa: BLE001
        return f"✗ 캘린더를 읽지 못했어요 ({type(e).__name__}). 직접 확인해 보시겠어요?"

    if not found:
        # 🚨 «없다»와 «못 찾았다»를 섞지 않는다 — 못 찾았으면 **안 고친다.**
        return (f"✗ '{title}' 이라는 일정을 못 찾았어요. 제목이나 날짜를 알려 주시겠어요? "
                "(기본 달력만 봤어요)")
    if len(found) > 1:
        # 🚨 **여럿이면 고르지 않는다.** 엉뚱한 일정을 고치면 되돌릴 수 없고,
        #   사용자는 고쳐진 줄 안다. (`read_email` 이 같은 규칙을 쓴다)
        lines = [f"  • {_ev_span(e)} {e.get('summary') or '(제목 없음)'}"
                 for e in found[:5]]
        return (f"✗ '{title}' 로 찾은 일정이 {len(found)}개예요. 어느 것인지 알려 주세요:"
                + NL + NL.join(lines))

    ev = found[0]
    before = _ev_span(ev)
    before_title = ev.get("summary") or "(제목 없음)"

    start_raw = (ev.get("start") or {}).get("dateTime")
    if not start_raw:
        return (f"✗ '{before_title}' 은 하루 종일 일정이라 시간을 못 바꿔요. "
                "캘린더에서 직접 고쳐 보시겠어요?")

    try:
        cur_start = datetime.fromisoformat(start_raw)
        cur_end = datetime.fromisoformat((ev.get("end") or {}).get("dateTime", ""))
    except Exception:
        return f"✗ '{before_title}' 의 시간을 읽지 못했어요. 캘린더에서 직접 고쳐 보시겠어요?"

    new_start = cur_start
    if new_date or new_time:
        parsed = _parse_datetime(new_date or cur_start.strftime("%Y-%m-%d"),
                                 new_time or cur_start.strftime("%H:%M"))
        if not parsed:
            return f"✗ 날짜/시간 형식 오류: new_date='{new_date}', new_time='{new_time}'"
        new_start = parsed.replace(tzinfo=cur_start.tzinfo)

    mins = duration_minutes if duration_minutes > 0 else int(
        (cur_end - cur_start).total_seconds() // 60)
    new_end = new_start + timedelta(minutes=mins)

    tz = "Asia/Seoul"
    body = {
        "start": {"dateTime": new_start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz},
        "end":   {"dateTime": new_end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz},
    }
    if new_title:
        body["summary"] = new_title
    if location:
        body["location"] = location
    if description:
        body["description"] = description

    try:
        service.events().patch(calendarId="primary", eventId=ev.get("id"),
                               body=body).execute()
    except Exception as e:                                    # noqa: BLE001
        # 🚨 **못 고쳤으면 못 고쳤다고 한다.** 여기서 새로 만들지 않는다 —
        #   그게 2026-10-02 에 일정이 둘이 된 길이다.
        return f"✗ '{before_title}' 을 고치지 못했어요 ({type(e).__name__})."

    after = _ev_span({"start": body["start"], "end": body["end"]})
    # 🔑 **전/후를 도구가 말한다.** 모델에게 «바꾼 걸 말해 주세요»라고 부탁하는 대신,
    #   옮길 수밖에 없는 문장을 쥐여 준다. 🚨 «새로 만들지 않았어요»도 같이 말한다 —
    #   사용자가 걱정한 것이 바로 **하나 더 생기는 것**이었다.
    head = f"✓ 기존 '{before_title}' 일정을 고쳤어요 (새로 만들지 않았어요)."
    if new_title and new_title != before_title:
        head = (f"✓ 기존 '{before_title}' 일정을 '{new_title}' 로 고쳤어요 "
                "(새로 만들지 않았어요).")
    return f"{head}{NL}  전: {before}{NL}  후: {after}"
