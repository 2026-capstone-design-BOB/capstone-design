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
    return f"✓ Google Calendar에서 '{title}' 일정 추가 화면을 열었어요. 저장 버튼을 눌러주세요!"


def _create_via_api(title: str, start_dt: datetime, end_dt: datetime, description: str, location: str) -> str:
    """방법 2: Google Calendar API로 직접 일정 등록 (token.json 필요)."""
    token_path = os.path.join(os.path.dirname(__file__), "..", "calendar_token.json")
    creds_path = os.path.join(os.path.dirname(__file__), "..", "calendar_credentials.json")

    token_path  = os.path.abspath(token_path)
    creds_path  = os.path.abspath(creds_path)

    if not os.path.exists(creds_path):
        raise FileNotFoundError("calendar_credentials.json 없음")

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)

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
    except FileNotFoundError:
        pass  # credentials 없으면 URL 방식으로 fallback
    except ImportError:
        pass  # google 패키지 미설치 시 fallback
    except Exception as e:
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

#: 읽기 전용 권한. 🔑 쓰기 scope(`calendar.events`)와 **다르다** — 읽기만 필요한 곳에
#  쓰기 권한을 달지 않는다. 다만 이미 쓰기 토큰이 있으면 그것으로도 읽힌다.
_READ_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

_NO_CREDS = ("✗ 캘린더를 읽으려면 Google 계정 연결이 한 번 필요해요. "
             "지금은 일정을 확인할 수 없어요 — 캘린더를 직접 열어 보시겠어요?")


def _calendar_service():
    """인증된 Calendar 서비스. 자격증명이 없으면 FileNotFoundError."""
    token_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                              "calendar_token.json"))
    creds_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                              "calendar_credentials.json"))
    if not os.path.exists(creds_path):
        raise FileNotFoundError("calendar_credentials.json 없음")

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, _READ_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, _READ_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


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
    except FileNotFoundError:
        return _NO_CREDS
    except ImportError:
        return _NO_CREDS
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
        return f"✓ {when} 일정이 없어요."

    lines = []
    for ev in items:
        title = ev.get("summary") or "(제목 없음)"
        piece = f"  • {_fmt_when(ev)} {title}"
        loc = ev.get("location")
        if loc:
            piece += f" ({loc})"
        lines.append(piece)

    return f"✓ {when} 일정 {len(items)}개예요:\n" + "\n".join(lines)
