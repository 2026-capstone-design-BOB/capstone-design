# -*- coding: utf-8 -*-
"""구글 인증 — **일정과 메일이 한 자리에서 권한을 받는다** (2026-09-24)

사용자 안내: [`docs/구글_연결.md`](../docs/구글_연결.md)

## 🚨 왜 이 파일이 따로 있나 — **범위가 갈리면 조용히 깨진다**

토큰 파일(`calendar_token.json`)에는 **처음 인증할 때 요청한 권한 목록이 굳는다.**
그래서 캘린더와 메일이 **각자 자기 범위만** 요청하면 이렇게 된다:

    ① 사용자가 "오늘 일정 뭐야" → 캘린더 범위로만 토큰이 생긴다
    ② 사용자가 "메일 있어?"     → 그 토큰에 메일 권한이 없다 → 401
    ③ 그런데 토큰 파일은 «있으므로» 다시 묻지도 않는다

**같은 사실(요청할 권한)이 두 파일에 흩어지면 한쪽만 갱신된다** — 이 저장소가
반복해서 데인 모양이라, 여기 한 곳에만 둔다.

## 🔒 읽기까지만 받는다

| 범위 | 할 수 있는 것 | 할 수 **없는** 것 |
|---|---|---|
| `calendar.events` | 일정 읽기 · 추가 | — |
| `gmail.readonly` | 메일 목록·내용 읽기 | 🔒 **보내기 · 초안 · 지우기** |

🚨 **«초안만 쓰고 발송은 못 하는» 범위는 구글에 없다.** `gmail.compose` 는 이름과 달리
**발송 권한을 포함한다.** 그래서 초안 기능이 실제로 필요해질 때까지 **읽기만** 받는다 —
지금 미리 올려 두면 «쓸 수 있는데 안 쓴다»가 되고, 그건 사고가 한 번의 실수만큼
가까워진다는 뜻이다.

🔑 그리고 경계는 **권한만이 아니라 도구 목록이 같이 진다** — `gmail_send` 라는 도구를
**아예 만들지 않으면** 모델이 부를 수단이 없다(`close_app`/`force_close_app` 을 이름이
다른 도구로 가른 것과 같은 규칙).
"""
import os

#: 🚨 **여기 한 곳에만 적는다.** 범위를 늘리면 기존 토큰은 **무효가 되고**
#   사용자가 한 번 더 로그인해야 한다 — 그래서 늘릴 때는 문서도 같이 고친다.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 🔑 이름이 «calendar»인 것은 캘린더가 먼저 생겼기 때문이고, **메일도 같은 파일을
#   쓴다.** 바꾸면 이미 연결한 사용자가 다시 로그인해야 해서 그대로 둔다.
CREDS_PATH = os.path.join(_ROOT, "calendar_credentials.json")
TOKEN_PATH = os.path.join(_ROOT, "calendar_token.json")

#: 자격증명이 아예 없을 때. 🚨 «없어요»가 아니라 «확인할 수 없어요»라고 말한다 —
#  둘은 완전히 다른 말이고, 뒤엣말이 나가면 사용자가 메일이나 회의를 놓친다.
NOT_CONNECTED = ("✗ 구글 계정 연결이 한 번 필요해요. 지금은 확인할 수 없어요 — "
                 "연결하는 법은 docs/구글_연결.md 에 적어 뒀어요.")


class NotConnected(Exception):
    """자격증명이 없거나 패키지가 없다. 부르는 쪽이 `NOT_CONNECTED` 를 답하면 된다."""


def is_connected() -> bool:
    """설정 파일이 있나. **토큰이 유효한지는 안 본다**(그건 실제로 불러 봐야 안다)."""
    return os.path.exists(CREDS_PATH)


def get_service(api: str, version: str):
    """인증된 구글 API 서비스. 자격증명이 없으면 `NotConnected`.

    🚨 **범위가 모자라면 토큰을 버리고 다시 받는다.** 예전 토큰(캘린더만)으로
      메일을 부르면 401 이 나는데, 그때 «메일이 없어요»로 떨어지면 최악이다.
    """
    if not os.path.exists(CREDS_PATH):
        raise NotConnected("calendar_credentials.json 없음")

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        raise NotConnected(f"구글 패키지 없음: {e}")

    creds = None
    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception:
            creds = None        # 형식이 깨졌으면 새로 받는다

    # 🔑 «유효한가»만 보지 않고 **«범위를 다 갖고 있나»** 도 본다.
    #   `has_scopes` 가 없는 구버전을 대비해 방어적으로 부른다.
    enough = True
    if creds is not None:
        try:
            enough = creds.has_scopes(SCOPES)
        except Exception:
            enough = True

    if not creds or not creds.valid or not enough:
        if creds and creds.expired and creds.refresh_token and enough:
            creds.refresh(Request())
        else:
            # 범위가 모자라면 여기로 온다 — 브라우저가 열리고 사용자가 한 번 더 허용한다.
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build(api, version, credentials=creds)
