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

from langchain_core.tools import tool

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

#: 자격증명은 있는데 아직 로그인을 안 했다.
#
# 🚨 **2026-10-02 — 여기가 BL-84 와 정면으로 모순이었다.**
#   원래 이 문장은 *"터미널에서 'python scripts/connect_google.py' 를 한 번 돌려
#   주시겠어요?"* 였다. 그런데 BL-84 가 **그 일을 LLM 이 하게** 만들었는데도 이
#   문장은 그대로였다 — 도구 결과로 모델에게 올라가는 문장이 **«사용자가 직접
#   하세요»라고 말하고 있으면**, 모델은 그걸 옮긴다. 도구를 만들어 놓고
#   **쓰지 말라고 적어 둔 꼴**이다.
#
# 🔑 그래서 **할 일을 지시하지 않고 상태만 말한다.** 무엇을 할지는
#   `connect_google` 도구와 시스템 프롬프트가 정한다.
# ⚠️ **«열어 드릴게요»라고 쓰지 않는다** — 모델이 도구를 안 부르면 그건
#   지키지 못한 약속이 된다(BL-19·35 가 그 모양이었다).
NEED_LOGIN = ("✗ 구글 로그인이 아직 안 됐어요. "
              "연결 창에서 한 번 로그인하면 그 뒤로는 안 물어봐요.")


class NotConnected(Exception):
    """자격증명 파일이 없다. 부르는 쪽이 `NO_CREDENTIALS` 를 답한다."""


class MissingPackages(NotConnected):
    """구글 패키지가 없다. 부르는 쪽이 `NO_PACKAGES` 를 답한다.

    🔑 `NotConnected` 를 상속한다 — 기존에 `except NotConnected` 로 잡던 곳이
      그대로 동작하고, 문장만 갈라진다.
    """


class NeedLogin(NotConnected):
    """토큰이 없거나 · 범위가 모자라거나 · **만료돼 갱신이 거부됐다.**
    부르는 쪽이 `NEED_LOGIN` 을 답한다.

    🚨 **세 번째를 2026-10-02 에 더했다**(BL-74). 동의 화면이 «테스트» 상태라
      갱신 토큰이 **7일**인데, 만료되면 `creds.refresh()` 가 `RefreshError` 를
      던지고 부르는 쪽이 그걸 **일반 오류로** 받았다. 그래서 셋 다
      «다시 로그인하세요»를 **한 번도 말하지 않았다** — 일정은 예외가 도구
      밖으로 터졌고, 메일은 *"✗ 메일에 연결하지 못했어요 (RefreshError)"*,
      기다리기는 *"3번 연속으로 확인하지 못해서 멈췄어요"* 로 끝났다.

    🔑 **사용자가 할 일은 «토큰이 없을 때»와 똑같다** — 터미널에서
      `connect_google.py` 를 한 번 돌리는 것. 할 일이 같으면 문장도 같아야 한다
      (이 파일 머리에 적힌 규칙의 뒷면이다).
    """


def _refresh_error_class():
    """구글이 갱신을 **거부**할 때의 예외. 패키지가 없으면 빈 튜플(= 아무것도 안 잡는다).

    🔑 함수로 둔 것은 **import 가 실패해도 이 모듈이 뜨게** 하기 위해서다.
      패키지가 없는 상황은 `MissingPackages` 가 이미 따로 말한다.
    """
    try:
        from google.auth.exceptions import RefreshError
        return RefreshError
    except ImportError:
        return ()


def _refresh(creds, request) -> None:
    """토큰을 갱신한다. **거부당하면 `NeedLogin` 으로 바꿔 던진다.**

    🚨 **`RefreshError` 만 바꾼다. 네트워크 오류는 그대로 올려 보낸다.**

      인터넷이 끊겼을 때 *"다시 로그인하세요"* 라고 하면, 2026-09-24 에
      **설정을 끝낸 사람에게 다시 하라고 떠민** 사고와 같은 짓이 된다.
      `TransportError` 는 `RefreshError` 의 하위가 아니라 형제라 안 잡힌다.
    """
    try:
        creds.refresh(request)
    except _refresh_error_class() as e:
        raise NeedLogin(f"토큰 갱신이 거부됐다(만료·취소): {e}") from e


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
        refreshed = False
        if creds and creds.expired and creds.refresh_token and enough:
            # 갱신은 브라우저가 필요 없다 — 대화 중에도 안전하다.
            try:
                _refresh(creds, Request())
                refreshed = True
            except NeedLogin:
                # 🚨 **여기서 interactive 를 돌려보내면 안 된다**(BL-74, 2026-10-02).
                #   `NEED_LOGIN` 은 *"connect_google.py 를 한 번 돌려 주세요"* 인데,
                #   돌려보내는 상대가 **바로 그 스크립트**다. 그러면 안내가
                #   자기 자신을 가리키고 **만료된 토큰에서 빠져나올 길이 없어진다.**
                #   🔑 만료는 interactive 에겐 «막힌 것»이 아니라 **«할 일»** 이다.
                if not interactive:
                    raise

        if not refreshed:
            if interactive:
                # 🚨 **여기만 브라우저를 연다.** connect_google.py 에서만 온다.
                flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
            else:
                # 🚨 도구에서 왔다 — **멈추지 않고 말하고 끝낸다.**
                raise NeedLogin("토큰이 없거나 범위가 모자람")

        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build(api, version, credentials=creds)


# ══════════════════════════════════════════════════════════════════════
# 연결을 **LLM 이 건다** — 2026-10-02 실기 신설 (BL-84)
#
# 🙋 *"필요할 때는 스크립트를 사용자에게 실행하라고 하는 게 아니라 **LLM 이 실행하는
#   게** 실제 사용에서는 맞는 동작 (어차피 그 스크립트 실행하면 **사용자 HITL 부분이
#   있어서** 괜찮음)."*
#
#   맞다. 브라우저의 «허용» 화면이 **승인 절차 그 자체**다. 그래서 이 도구는
#   `DANGEROUS_TOOLS` 에 **넣지 않는다** — 넣으면 승인을 두 번 받는 꼴이고,
#   *«승인 피로는 승인을 무력화시킨다»*(BL-40) 가 이 저장소의 기록이다.
#
# 🚨 **그런데 그냥 부르면 서버가 멈춘다.**
#
#   `get_service(interactive=True)` 의 `run_local_server()` 는 **사용자가 «허용»을
#   누를 때까지 블로킹**한다. 턴 안에서 그걸 부르면 말을 걸었는데 아무 대답이 없고,
#   사용자는 왜 멈췄는지 모른다 — **[BL-69] 가 정확히 그 모양이었다**(STT 가 안
#   돌아와 턴이 멈췄다). `get_service` 머리에 *«도구는 이미 있는 토큰만 쓴다»* 라고
#   적혀 있는 이유다.
#
# 🔑 **그래서 기다리지 않는다.** 스크립트를 **떼어낸 프로세스**로 띄우고 곧바로
#   돌아온다. 턴은 *"브라우저를 띄웠어요"* 로 끝나고, 결과는 **다음 턴에** 안다.
#   «허용»을 누르는 데 걸리는 시간은 사람의 시간이지 턴의 시간이 아니다.
#
# ⚠️ **이 도구는 토큰이 생겼는지 확인하지 않는다.** 확인하려면 기다려야 하고,
#   기다리면 위의 그 사고가 난다. **«띄웠다»와 «됐다»를 섞지 않는다** —
#   이 저장소가 반복해서 적어 둔 규칙이다.
# ══════════════════════════════════════════════════════════════════════

#: 같은 창을 두 번 띄우지 않는다. 🚨 포트가 겹쳐 **둘 다 실패**할 수 있고,
#  사용자 화면에 똑같은 콘솔이 두 개 뜨면 어느 쪽을 봐야 할지 모른다.
_connect_proc = None


def _connect_running() -> bool:
    return _connect_proc is not None and _connect_proc.poll() is None


@tool
def connect_google() -> str:
    """구글 계정 연결을 **시작합니다**(브라우저가 열립니다).

    일정이나 메일을 쓰려는데 «구글 로그인이 아직 안 됐어요»가 나오면 이 도구를 부르세요.
    사용자에게 터미널에서 직접 하라고 떠넘기지 마세요.
    ⚠️ 이 도구는 **브라우저를 띄우기만** 합니다. 사용자가 «허용»을 누른 뒤에야 연결이
    끝나므로, 이 도구가 성공했다고 «연결됐어요»라고 말하면 안 됩니다.
    """
    import subprocess
    import sys as _sys

    global _connect_proc

    if not os.path.exists(CREDS_PATH):
        # 🚨 여기서 브라우저를 띄우면 **빈 창만 뜨고 실패한다.** 할 일이 다르다.
        return NO_CREDENTIALS

    if _connect_running():
        return ("✓ 연결 창을 이미 띄워 뒀어요. 브라우저에서 «허용»을 눌러 주세요. "
                "(창이 안 보이면 작업 표시줄을 봐 주세요)")

    script = os.path.join(_ROOT, "scripts", "connect_google.py")
    if not os.path.exists(script):
        return "✗ 연결 스크립트를 못 찾았어요. docs/구글_연결.md 를 봐 주시겠어요?"

    # 🔑 **지금 서버를 돌리는 그 파이썬**으로 띄운다. `python` 을 쓰면 Windows 에서
    #   보통 anaconda base 로 잡히는데 거기엔 구글 패키지가 없다 —
    #   웨이크워드가 **한 번도 실행된 적이 없던** 2026-09-02 사고와 같은 모양이다.
    flags = 0
    if os.name == "nt":
        # 새 콘솔을 준다 — 스크립트가 «[고급] → 안전하지 않음으로 이동» 같은
        # 안내를 글로 찍는데, 창이 없으면 그 안내가 아무 데도 안 보인다.
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        _connect_proc = subprocess.Popen(
            [_sys.executable, script], cwd=_ROOT, creationflags=flags)
    except Exception as e:                                    # noqa: BLE001
        return (f"✗ 연결 창을 띄우지 못했어요 ({type(e).__name__}). "
                "터미널에서 'python scripts/connect_google.py' 를 돌려 주시겠어요?")

    # ⚠️ **«연결됐어요»라고 쓰지 않는다.** 아직 아무 일도 안 끝났다.
    return ("✓ 구글 연결 창을 띄웠어요. 브라우저에서 계정을 고르고 «허용»을 눌러 주세요. "
            "«확인하지 않은 앱입니다»가 뜨면 [고급] → [Pluiz(안전하지 않음)으로 이동] 이에요. "
            "다 누르신 뒤에 다시 말씀해 주시면 그때 확인할게요.")
