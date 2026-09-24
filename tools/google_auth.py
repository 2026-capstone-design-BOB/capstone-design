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

# 🚨 **막힌 이유를 뭉뚱그리지 않는다** (2026-09-24 실기에서 사용자가 여기서 막혔다).
#
#   처음에는 «자격증명 없음»과 «패키지 없음»을 한 문장으로 묶어 두고
#   *"구글 계정 연결이 한 번 필요해요"* 라고만 말했다. 그런데 사용자는 설정을
#   **제대로 끝냈고** 자격증명 파일도 자리에 있었다 — 없던 것은 패키지였다.
#   그래서 **이미 한 일을 다시 하라고 떠밀었다.**
#
# 🔑 이 저장소가 스스로 적어 둔 규칙(«못 읽었다»와 «없다»를 섞지 않는다)을
#   한 층 위에서 어긴 것이다. 막힌 이유마다 **할 일이 다르면 문장도 달라야 한다.**

#: 자격증명 파일이 없다 → 사용자가 구글 콘솔에서 받아 와야 한다.
NO_CREDENTIALS = ("✗ 구글 계정 연결이 한 번 필요해요. 지금은 확인할 수 없어요 — "
                  "연결하는 법은 docs/구글_연결.md 에 적어 뒀어요.")

#: 자격증명은 있는데 패키지가 없다 → **설정 문제가 아니다.** 다시 하라고 하면 안 된다.
NO_PACKAGES = ("✗ 구글 연동에 필요한 프로그램이 빠져 있어요. 설정은 잘 하셨어요 — "
               "터미널에서 'pip install google-auth-oauthlib google-api-python-client' "
               "한 번만 하시면 돼요.")

#: 자격증명은 있는데 아직 로그인을 안 했다 → **대화 중에 브라우저를 열지 않는다**(아래).
NEED_LOGIN = ("✗ 구글 로그인이 아직 안 됐어요. 터미널에서 "
              "'python scripts/connect_google.py' 를 한 번 돌려 주시겠어요? "
              "브라우저가 열리고, 그 뒤로는 안 물어봐요.")


class NotConnected(Exception):
    """자격증명 파일이 없다. 부르는 쪽이 `NO_CREDENTIALS` 를 답한다."""


class MissingPackages(NotConnected):
    """구글 패키지가 없다. 부르는 쪽이 `NO_PACKAGES` 를 답한다.

    🔑 `NotConnected` 를 상속한다 — 기존에 `except NotConnected` 로 잡던 곳이
      그대로 동작하고, 문장만 갈라진다.
    """


class NeedLogin(NotConnected):
    """토큰이 없거나 범위가 모자라다. 부르는 쪽이 `NEED_LOGIN` 을 답한다."""


def message_for(e: Exception) -> str:
    """막힌 이유 → 사용자에게 할 말. 부르는 쪽이 분기를 안 써도 되게."""
    if isinstance(e, MissingPackages):
        return NO_PACKAGES
    if isinstance(e, NeedLogin):
        return NEED_LOGIN
    return NO_CREDENTIALS


#: 예전 이름. 지우면 부르는 쪽이 깨지므로 남긴다.
NOT_CONNECTED = NO_CREDENTIALS


def is_connected() -> bool:
    """설정 파일이 있나. **토큰이 유효한지는 안 본다**(그건 실제로 불러 봐야 안다)."""
    return os.path.exists(CREDS_PATH)


def get_service(api: str, version: str, *, interactive: bool = False):
    """인증된 구글 API 서비스.

    막히면 이유별로 다른 예외를 던진다 — `NotConnected`(자격증명 없음) ·
    `MissingPackages`(패키지 없음) · `NeedLogin`(로그인 안 됨).
    부르는 쪽은 `message_for(e)` 로 문장을 받으면 된다.

    🚨 **`interactive=False` 가 기본인 것이 이 함수의 제일 중요한 성질이다.**

      로그인은 브라우저를 열고 **사용자가 «허용»을 누를 때까지 기다린다.**
      그게 대화 턴 안에서 일어나면 **서버가 거기서 멈춘다** — 말을 걸었는데
      아무 대답이 없고, 사용자는 왜 멈췄는지 모른다.
      [BL-69](../docs/BACKLOG.md) 가 정확히 그 모양이었다(STT 가 안 돌아와 턴이 멈췄다).

      그래서 도구는 **이미 있는 토큰만** 쓰고, 없으면 «터미널에서 한 번 돌려
      주세요»라고 **말하고 끝낸다.** 브라우저를 여는 것은
      `scripts/connect_google.py` 뿐이다(`interactive=True`).

    🚨 **범위가 모자라면 다시 로그인이 필요하다.** 예전 토큰(캘린더만)으로
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
        raise MissingPackages(f"구글 패키지 없음: {e}")

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
            # 갱신은 브라우저가 필요 없다 — 대화 중에도 안전하다.
            creds.refresh(Request())
        elif interactive:
            # 🚨 **여기만 브라우저를 연다.** connect_google.py 에서만 온다.
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            # 🚨 도구에서 왔다 — **멈추지 않고 말하고 끝낸다.**
            raise NeedLogin("토큰이 없거나 범위가 모자람")
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build(api, version, credentials=creds)
