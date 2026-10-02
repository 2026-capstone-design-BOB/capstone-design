# -*- coding: utf-8 -*-
"""메일 읽기의 계약 — **가장 사적인 자료를 다루는 자리다** (페르소나 §3-D)

실행: python tests/test_gmail.py

## 왜 이 테스트가 있나

메일 본문은 화면 캡처보다 민감하다. 그리고 이 저장소의 구조상 도구 결과는
**두 번 밖으로 나간다**:

    도구 결과 → ① LLM 컨텍스트로 올라간다
              → ② 응답이 되어 **TTS 로 소리 내어 읽힌다**

사무실에서 쓰는 도구라는 것을 생각하면 둘 다 위험이다.
🚨 **그래프의 4층 마스킹은 «최종 응답»에만 걸린다** — 그때는 이미 ①이 끝났다.
그래서 마스킹이 **도구 안에** 있어야 한다.

## 여기서 고정하는 것 일곱

1. 🔒 **보내는 도구가 없다.** 권한(`gmail.readonly`)과 도구 목록이 **둘 다** 경계를 진다.
   권한만 조이면 나중에 범위를 넓히는 순간 도구가 생기고, 도구만 없애면 권한이 남는다.
2. 🚨 **마스킹이 도구 안에 있다.** 모델로 올라가기 **전에** 가린다.
3. 🚨 **검색어 문법을 모델에게 안 맡긴다.** `from:`·`newer_than:` 을 LLM 이 직접 쓰면
   조용히 틀린 질의가 나가고, 그러면 **«메일 없어요»가 거짓말이 된다** —
   메일이 없는 것과 질의가 틀린 것은 사용자에게 똑같아 보인다.
4. 🚨 **«못 읽었다»와 «없다»를 섞지 않는다.** 뒤엣말이 나가면 사용자가 메일을 놓친다.
5. 🚨 **여럿이면 고르지 않는다.** 엉뚱한 메일을 읽어 주면 그 내용이 모델로도 가고
   소리로도 나간다 — 되돌릴 수 없다.
6. **분량을 자른다.** 목록은 제목까지, 본문은 앞부분만. 자르면 **잘랐다고 말한다.**
7. 🚨 **내용을 로그에 안 남긴다.** `logs/pluiz.log` 는 공유될 수 있는 파일이다.

## ⚠️ 여기서 실제 메일을 읽지 않는다

구글에 연결하지 않는다. 순수 함수와 **소스의 계약**만 본다.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)

import tools.gmail as G  # noqa: E402

_SRC = io.open(os.path.join(_ROOT, "tools", "gmail.py"), encoding="utf-8").read()
_AUTH = io.open(os.path.join(_ROOT, "tools", "google_auth.py"), encoding="utf-8").read()
_CAL = io.open(os.path.join(_ROOT, "tools", "calendar.py"), encoding="utf-8").read()
_REG = io.open(os.path.join(_ROOT, "core", "tool_registry.py"), encoding="utf-8").read()
_GRAPH_SRC = io.open(os.path.join(_ROOT, "core", "graph.py"), encoding="utf-8").read()

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")


def run():
    from core.tool_registry import get_all_tools
    from core.graph import DANGEROUS_TOOLS, READONLY_RETRY_TOOLS
    names = {t.name for t in get_all_tools()}

    print("=== ① 🔒 보내는 길이 두 겹으로 막혀 있는가 ===")
    check("🚨 send 라는 이름의 도구가 **하나도 없다**",
          not [n for n in names if "send" in n.lower()], sorted(names))
    check("🚨 gmail.py 에 발송 코드가 없다",
          "messages().send" not in _SRC and "drafts()" not in _SRC)
    check("🚨 요청 범위가 readonly 다 (compose·send 가 없다)",
          "gmail.readonly" in _AUTH
          and "gmail.compose" not in _AUTH.split("SCOPES = [")[1].split("]")[0]
          and "gmail.send" not in _AUTH.split("SCOPES = [")[1].split("]")[0])
    check("   왜 compose 를 안 받는지 적혀 있다 (그 범위가 발송을 포함한다)",
          "발송 권한을 포함한다" in _AUTH)
    check("   두 겹이 왜 둘 다 필요한지 적혀 있다",
          "권한만 조이면" in _SRC or "권한만 조이면" in _AUTH)
    check("읽는 도구 둘이 등록돼 있다",
          {"list_emails", "read_email"} <= names)

    print(f"{NL}=== ② 🚨 마스킹이 도구 안에 있는가 ===")
    check("🚨 gmail.py 가 마스킹을 부른다",
          "mask_sensitive_output" in _SRC and "def _mask(" in _SRC)
    check("   목록에 적용한다", "_mask(head" in _SRC)
    check("   본문에도 적용한다", _SRC.count("return _mask(") >= 3)
    check("🚨 마스킹이 실패하면 **조용히 넘어가지 않는다**",
          "안 가린 채로 나간다" in _SRC and "log.error" in _SRC)
    check("왜 도구 안이어야 하는지 적혀 있다 (4층은 최종 응답에만 걸린다)",
          "이미 모델로" in _SRC)
    check("실제로 가린다",
          "990101-*******" in G._mask("990101-1234567"))

    print(f"{NL}=== ③ 🚨 검색어를 모델이 쓰지 않는다 ===")
    q = G._build_query("김철수", "", False, 0)
    check("보낸이를 from: 으로 우리가 만든다", q == "from:(김철수)", q)
    check("안 읽은 것만", "is:unread" in G._build_query("", "", True, 0))
    check("기간도 우리가 만든다", "newer_than:1d" in G._build_query("", "", False, 1))
    check("여러 조건이 합쳐진다",
          "from:(김)" in G._build_query("김", "보고", True, 7)
          and "is:unread" in G._build_query("김", "보고", True, 7))
    check("아무 조건도 없으면 받은편지함", G._build_query("", "", False, 0) == "in:inbox")
    check("🚨 도구가 raw query 인자를 **안 받는다** (모델이 문법을 못 쓴다)",
          "query" not in G.list_emails.args and "query" not in G.read_email.args,
          f"{list(G.list_emails.args)}")
    check("왜 안 맡기는지 적혀 있다 («없어요»가 거짓말이 된다)",
          "거짓말이 된다" in _SRC)

    print(f"{NL}=== ④ 🚨 «못 읽었다»와 «없다»를 섞지 않는가 ===")
    check("연결이 없으면 «확인할 수 없어요»", "확인할 수 없어요" in _AUTH)
    check("🚨 읽기 실패가 «없어요»로 안 떨어진다",
          "메일을 읽지 못했어요" in _SRC and "메일에 연결하지 못했어요" in _SRC)
    check("진짜 없을 때만 «없어요»", "메일이 없어요" in _SRC)
    # 🚨 **사용자 상태에 의존하지 않는다** (2026-09-24 에 여기서 깨졌다).
    #   처음에는 그냥 `list_emails.invoke({})` 를 부르고 «✗ 로 시작한다»를 봤는데,
    #   사용자가 **실제로 구글에 연결하자 진짜 메일이 와서** 테스트가 실패했다.
    #   `_testenv.py` 가 못 박아 둔 규칙 그대로다 — «테스트는 사용자 상태에
    #   의존하면 안 된다». 그래서 자격증명 경로를 없는 곳으로 돌려 **결정적으로** 본다.
    import tools.google_auth as _A
    _keep = _A.CREDS_PATH
    try:
        _A.CREDS_PATH = os.path.join(_ROOT, "__없는파일__.json")
        r = G.list_emails.invoke({})
        check("연결이 없으면 실제로 그 문장이 나간다",
              r.startswith("✗") and "연결" in r, r[:50])
    finally:
        _A.CREDS_PATH = _keep

    print(f"{NL}=== ⑤ 🚨 여럿이면 고르지 않는가 ===")
    check("🚨 후보가 둘 이상이면 되묻는다", "어느 것인가요" in _SRC)
    check("   왜인지 적혀 있다 (모델로도 가고 소리로도 나간다)",
          "소리로도 나간다" in _SRC)
    check("조건이 없으면 읽지 않고 되묻는다",
          G.read_email.invoke({}).startswith("✗") and "어느 메일인지" in G.read_email.invoke({}))

    print(f"{NL}=== ⑥ 분량을 자르고, 자르면 말하는가 ===")
    check("목록 상한이 있다", G.MAX_LIST > 0 and G.MAX_LIST <= 30)
    check("본문 상한이 있다", 500 <= G.MAX_BODY <= 4000)
    check("미리보기 상한이 있다", 20 <= G.MAX_SNIPPET <= 200)
    check("🚨 자르면 **잘랐다고 말한다**", "까지만 읽었어요" in _SRC)
    check("목록은 본문을 안 준다 (metadata 로만 받는다)",
          'format="metadata"' in _SRC)

    print(f"{NL}=== ⑦ 🚨 내용을 로그에 안 남기는가 ===")
    check("목록은 **통수**만 남긴다", "%d통" in _SRC)
    check("본문은 **길이**만 남긴다", "%d자" in _SRC)
    check("🚨 제목·보낸이를 로그에 안 쓴다",
          "log.info" in _SRC and "subj" not in _SRC.split("log.info")[1].split(")")[0])
    check("왜인지 적혀 있다 (로그는 공유될 수 있다)", "공유될 수 있는 파일" in _SRC)

    print(f"{NL}=== ⑧ 승인·재시도 분류 ===")
    check("메일 읽기는 승인 대상이 아니다 (읽기는 되돌릴 게 없다)",
          not ({"list_emails", "read_email"} & DANGEROUS_TOOLS))
    check("🚨 재시도 화이트리스트에도 **없다** (다시 읽으면 또 노출된다)",
          not ({"list_emails", "read_email"} & READONLY_RETRY_TOOLS))

    print(f"{NL}=== ⑨ 🚨 권한 범위가 한 곳에만 있는가 ===")
    check("google_auth 가 범위를 정한다", "SCOPES = [" in _AUTH)
    check("🚨 calendar.py 가 자기 범위를 **안 갖는다**",
          "_READ_SCOPES" not in _CAL and "auth/calendar" not in _CAL)
    check("   calendar 가 공용 인증을 쓴다", "from tools.google_auth import get_service" in _CAL)
    check("   gmail 도 공용 인증을 쓴다", "from tools.google_auth import" in _SRC)
    check("🚨 범위가 모자라면 토큰을 다시 받는다 (401 로 안 떨어진다)",
          "has_scopes" in _AUTH)
    check("왜 한 곳이어야 하는지 적혀 있다 (한쪽만 갱신된다)",
          "한쪽만 갱신된다" in _AUTH)
    check("토큰 파일 이름이 왜 calendar_ 인지 적혀 있다",
          "캘린더가 먼저 생겼기 때문" in _AUTH)

    print(f"{NL}=== ⑩ 🚨 막힌 이유를 뭉뚱그리지 않는가 (2026-09-24 실기) ===")
    # 🚨 사용자가 설정을 **제대로 끝냈는데** «다시 하세요»를 들었다. 없던 것은
    #   패키지였고, 오류 문장이 셋을 한 덩어리로 묶고 있었다.
    import tools.google_auth as A
    check("자격증명 없음 · 패키지 없음 · 로그인 안 됨이 **다른 문장**이다",
          len({A.NO_CREDENTIALS, A.NO_PACKAGES, A.NEED_LOGIN}) == 3)
    check("🚨 패키지 문장이 «설정은 잘 하셨어요»라고 말한다",
          "설정은 잘 하셨어요" in A.NO_PACKAGES)
    check("   그리고 **무엇을 치면 되는지** 알려준다",
          "pip install" in A.NO_PACKAGES)
    # 🔄 **2026-10-02 에 계약이 뒤집혔다**(BL-84). 예전엔 이 줄이
    #   *«터미널 명령을 알려준다»* 를 고정했다 — 그때는 **사용자가 직접 하는 것이
    #   유일한 길**이었기 때문이다. 이제 `connect_google` 이 있으니, 도구 결과가
    #   «직접 하세요»라고 말하면 **모델이 그걸 옮겨서** 도구를 만들어 놓고
    #   안 쓰게 된다. 🔑 그래서 **상태만 말하고 할 일은 안 적는다.**
    check("🚨 로그인 문장이 **«직접 하세요»라고 안 한다** (BL-84)",
          "connect_google.py" not in A.NEED_LOGIN
          and "터미널" not in A.NEED_LOGIN, A.NEED_LOGIN)
    check("   그래도 **무슨 상태인지는** 말한다",
          "로그인이 아직 안 됐어요" in A.NEED_LOGIN)
    # ⚠️ **«열어 드릴게요»라고 쓰면 안 된다** — 모델이 도구를 안 부르면 그건
    #   지키지 못한 약속이고, BL-19·35 가 정확히 그 모양이었다.
    check("⚠️ **지키지 못할 약속을 안 한다**",
          "열어 드릴게요" not in A.NEED_LOGIN and "열게요" not in A.NEED_LOGIN)
    check("🔑 연결은 **도구가** 건다 — 시스템 프롬프트가 그렇게 지시한다",
          "connect_google을 호출해" in _GRAPH_SRC
          and "터미널에서 직접 실행하라고 하지 마세요" in _GRAPH_SRC)
    check("message_for 가 이유별로 갈라 준다",
          A.message_for(A.MissingPackages()) == A.NO_PACKAGES
          and A.message_for(A.NeedLogin()) == A.NEED_LOGIN
          and A.message_for(A.NotConnected()) == A.NO_CREDENTIALS)
    check("세 예외가 모두 NotConnected 로 잡힌다 (기존 호출부가 안 깨진다)",
          issubclass(A.MissingPackages, A.NotConnected)
          and issubclass(A.NeedLogin, A.NotConnected))
    # gmail 의 구글 접점 **전부** + calendar 의 읽기 하나가 이유별 문장을 쓴다.
    # 🔄 2026-09-25 — 「== 2」였다. `watch_inbox` 가 세 번째 접점이 되면서 깨졌는데,
    #   **고쳐야 할 쪽은 이 숫자였다.** 접점이 늘 때마다 여기가 깨지는 게 맞다:
    #   빠뜨리면 새 접점만 «다시 설정하세요»로 뭉뚱그린다.
    _POINTS = _SRC.count("get_service(")
    check("도구가 message_for 를 쓴다 (한 문장으로 안 묶는다)",
          _SRC.count("message_for(e)") >= 3 and "message_for(e)" in _CAL,
          f"gmail {_SRC.count('message_for(e)')}곳")
    check("🚨 구글에 닿는 **모든** 자리가 이유별 문장을 쓴다",
          _SRC.count("message_for(e)") >= _POINTS,
          f"접점 {_POINTS}곳 · message_for {_SRC.count('message_for(e)')}곳")

    print(f"{NL}=== ⑪ 🚨 대화 턴 안에서 브라우저를 안 연다 ===")
    _AUTH2 = io.open(os.path.join(_ROOT, "tools", "google_auth.py"),
                     encoding="utf-8").read()
    _CONN = io.open(os.path.join(_ROOT, "scripts", "connect_google.py"),
                    encoding="utf-8").read()
    check("🚨 기본이 interactive=False 다",
          "interactive: bool = False" in _AUTH2)
    check("🚨 브라우저를 여는 곳이 interactive 안에만 있다",
          _AUTH2.count("flow.run_local_server(") == 1   # 주석의 언급은 안 센다
          and "if interactive:" in _AUTH2)
    check("도구는 interactive 를 안 켠다",
          "interactive=True" not in _SRC and "interactive=True" not in _CAL)
    check("연결 스크립트만 켠다", "interactive=True" in _CONN)
    check("토큰이 없으면 **멈추지 않고** NeedLogin 을 던진다",
          "raise NeedLogin" in _AUTH2)
    check("갱신(refresh)은 대화 중에도 된다 (브라우저가 필요 없다)",
          "_refresh(creds, Request())" in _AUTH2)
    check("왜 그런지 BL-69 를 근거로 적어 뒀다", "BL-69" in _AUTH2)
    check("🚨 연결 스크립트가 «토큰 받음»에서 끝내지 않고 **실제로 읽어 본다**",
          "실제로 읽히는지 확인" in _CONN and "getProfile" in _CONN)

    print(f"{NL}=== ⑬ 🚨 토큰이 **만료됐을 때** 할 일을 말하는가 (BL-74) ===")
    # 🚨 동의 화면이 «테스트» 라 갱신 토큰이 **7일**이다. 만료는 예외가 아니라
    #   **매주 일어나는 일**인데, 2026-10-02 전까지 넷 중 **한 곳도**
    #   «다시 로그인하세요»를 말하지 않았다:
    #
    #     일정      → RefreshError 가 도구 **밖으로 터졌다**
    #     메일      → "✗ 메일에 연결하지 못했어요 (RefreshError)"
    #     기다리기  → "3번 연속으로 확인하지 못해서 멈췄어요"
    #     🚨 고치러 간 길(connect_google.py) → **브라우저를 못 열었다**
    #
    # 🔑 마지막 것이 제일 나빴다 — 안내가 가리키는 스크립트가 **그 상태에서
    #   빠져나오지 못했다.** 즉 고치는 방법 자체가 막혀 있었다.
    #
    # 📌 **소스 대조가 아니라 실제로 밟아 본다**(BL-83) — «그렇게 적혀 있나»는
    #   이번 ② 에서 결함 셋을 초록인 채로 통과시켰다.

    class _Denied(Exception):
        """구글이 갱신을 거부했다 (invalid_grant)."""

    class _NetDown(Exception):
        """인터넷이 끊겼다. **이건 다시 로그인할 일이 아니다.**"""

    class _StaleCreds:
        valid = False
        expired = True
        refresh_token = "stale"
        def has_scopes(self, scopes): return True
        def to_json(self): return "{}"
        def refresh(self, request): raise _Denied("invalid_grant")

    class _NetCreds(_StaleCreds):
        def refresh(self, request): raise _NetDown("connection refused")

    _orig_cls = A._refresh_error_class
    A._refresh_error_class = lambda: _Denied
    try:
        try:
            A._refresh(_StaleCreds(), None)
            _got = None
        except Exception as e:                                # noqa: BLE001
            _got = e
        check("🚨 갱신이 거부되면 NeedLogin 으로 바뀐다",
              isinstance(_got, A.NeedLogin), f"{type(_got).__name__}")
        check("   그래서 사용자가 듣는 말이 «다시 로그인하세요» 다",
              _got is not None and A.message_for(_got) == A.NEED_LOGIN)

        try:
            A._refresh(_NetCreds(), None)
            _net = None
        except Exception as e:                                # noqa: BLE001
            _net = e
        check("🚨 인터넷이 끊긴 것은 **안 바꾼다** (설정을 다시 하라고 떠밀지 않는다)",
              isinstance(_net, _NetDown), f"{type(_net).__name__}")
    finally:
        A._refresh_error_class = _orig_cls

    check("패키지가 없으면 빈 튜플이라 아무것도 안 잡는다 (환경에 안 흔들린다)",
          isinstance(A._refresh_error_class(), (type, tuple)))

    # ── 도구 경로와 «고치러 가는 길»을 한 바퀴 밟는다 ──────────────
    #   가짜 구글 모듈을 끼워 **설치 여부와 무관하게** 같은 수의 검사가 돈다.
    import tempfile
    import types

    def _drive(interactive):
        """만료된 토큰으로 get_service 를 한 번 돌린다. (결과, 브라우저 열림) 반환."""
        opened = {"yes": False}

        class _Flow:
            @staticmethod
            def from_client_secrets_file(path, scopes): return _Flow()
            def run_local_server(self, port=0):
                opened["yes"] = True
                class _Fresh(_StaleCreds):
                    valid = True
                    expired = False
                return _Fresh()

        fakes = {
            "google": types.ModuleType("google"),
            "google.oauth2": types.ModuleType("google.oauth2"),
            "google.oauth2.credentials": types.ModuleType("google.oauth2.credentials"),
            "google.auth": types.ModuleType("google.auth"),
            "google.auth.transport": types.ModuleType("google.auth.transport"),
            "google.auth.transport.requests": types.ModuleType("google.auth.transport.requests"),
            "google.auth.exceptions": types.ModuleType("google.auth.exceptions"),
            "google_auth_oauthlib": types.ModuleType("google_auth_oauthlib"),
            "google_auth_oauthlib.flow": types.ModuleType("google_auth_oauthlib.flow"),
            "googleapiclient": types.ModuleType("googleapiclient"),
            "googleapiclient.discovery": types.ModuleType("googleapiclient.discovery"),
        }
        fakes["google.oauth2.credentials"].Credentials = type(
            "Credentials", (), {"from_authorized_user_file":
                                staticmethod(lambda p, sc: _StaleCreds())})
        fakes["google.auth.transport.requests"].Request = lambda *a, **k: None
        fakes["google.auth.exceptions"].RefreshError = _Denied
        fakes["google_auth_oauthlib.flow"].InstalledAppFlow = _Flow
        fakes["googleapiclient.discovery"].build = lambda *a, **k: "SERVICE"

        saved = {k: sys.modules.get(k) for k in fakes}
        sys.modules.update(fakes)
        _c, _t = A.CREDS_PATH, A.TOKEN_PATH
        tmp = tempfile.mkdtemp()
        A.CREDS_PATH = os.path.abspath(__file__)          # «있다»만 보면 된다
        A.TOKEN_PATH = os.path.join(tmp, "token.json")
        io.open(A.TOKEN_PATH, "w", encoding="utf-8").write("{}")
        try:
            return A.get_service("gmail", "v1", interactive=interactive), opened["yes"]
        except Exception as e:                            # noqa: BLE001
            return e, opened["yes"]
        finally:
            A.CREDS_PATH, A.TOKEN_PATH = _c, _t
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    _tool, _tool_browser = _drive(interactive=False)
    check("🚨 도구에서 오면 NeedLogin 이 된다 (예외가 밖으로 안 터진다)",
          isinstance(_tool, A.NeedLogin), f"{type(_tool).__name__}")
    check("   그리고 **브라우저를 안 연다** (턴이 거기서 멈추면 안 된다)",
          _tool_browser is False)

    _conn, _conn_browser = _drive(interactive=True)
    check("🚨 고치러 간 길(connect_google.py)은 **브라우저를 연다** — "
          "만료에서 빠져나올 길이 있다",
          _conn_browser is True)
    check("   그래서 안내가 **자기 자신을 가리키지 않는다**",
          not isinstance(_conn, A.NeedLogin), f"{type(_conn).__name__}")

    print(f"{NL}=== ⑭ 🚨 연결을 **LLM 이 건다** — 다만 기다리지 않는다 (BL-84) ===")
    # 🙋 2026-10-02 실기 — *"오늘 일정 알려줘"* 에 «터미널에서 직접 돌리세요»가 나갔다.
    #   브라우저의 «허용» 화면이 승인 그 자체라 LLM 이 열어도 된다는 것이 사용자 판단이다.
    #
    # 🚨 **그런데 기다리면 서버가 멈춘다** — `run_local_server()` 는 블로킹이고,
    #   그게 턴 안에서 일어나면 BL-69(말을 걸었는데 아무 대답이 없다)가 재발한다.
    from core.tool_registry import get_all_tools as _all
    _names = {t.name for t in _all()}
    check("연결 도구가 **도구 목록에 있다** (없으면 모델이 못 부른다)",
          "connect_google" in _names)
    from core.graph import DANGEROUS_TOOLS as _DT
    check("🚨 **승인 도구가 아니다** (브라우저의 «허용»이 승인 그 자체다)",
          "connect_google" not in _DT)
    check("🚨 **기다리지 않는다** — 떼어낸 프로세스로 띄운다",
          "subprocess.Popen" in _AUTH2 and "run_local_server" not in
          _AUTH2[_AUTH2.find("def connect_google"):])
    check("   왜 그런지 BL-69 를 근거로 적어 뒀다",
          "BL-69" in _AUTH2[_AUTH2.find("# 연결을 **LLM 이 건다**"):])
    # 🚨 돌려주는 문장이 «띄웠다»여야 한다. **«됐다»로 쓰면 모델이 그대로 옮기고,
    #   사용자는 허용을 안 눌렀는데 연결된 줄 안다** — 이 저장소가 반복해서 데인
    #   «확인하지 않고 됐다고 말한다» 계열이다(BL-12·19·21).
    check("🚨 **«띄웠다»와 «됐다»를 섞지 않는다**",
          '"✓ 구글 연결 창을 띄웠어요' in _AUTH2.replace("(", "").replace("'", '"'),
          "띄웠어요" if "띄웠어요" in _AUTH2 else "없음")
    check("   그리고 도구 설명이 모델에게 **그렇게 말하지 말라**고 못 박는다",
          "«연결됐어요»라고 말하면 안 됩니다" in _AUTH2)
    check("🔑 **지금 서버를 돌리는 그 파이썬**으로 띄운다 (base 는 패키지가 없다)",
          "_sys.executable" in _AUTH2)
    check("같은 창을 두 번 안 띄운다", "_connect_running()" in _AUTH2)
    check("자격증명이 없으면 **브라우저를 안 연다** (빈 창만 뜬다)",
          "return NO_CREDENTIALS" in _AUTH2)

    print(f"{NL}=== ⑫ 사람 이름 다듬기 ===")
    check("'홍길동 <a@b.com>' → '홍길동'",
          G._pretty_sender('홍길동 <a@b.com>') == "홍길동")
    check('따옴표를 벗긴다', G._pretty_sender('"김 팀장" <x@y.z>') == "김 팀장")
    check("이름이 없으면 주소 앞부분", G._pretty_sender("abc@d.com") == "abc")
    check("빈 값도 죽지 않는다", G._pretty_sender("") == "")

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
