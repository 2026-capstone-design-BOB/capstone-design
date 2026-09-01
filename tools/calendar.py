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
