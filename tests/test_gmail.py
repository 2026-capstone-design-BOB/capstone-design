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
    check("로그인 문장이 터미널 명령을 알려준다",
          "connect_google.py" in A.NEED_LOGIN)
    check("message_for 가 이유별로 갈라 준다",
          A.message_for(A.MissingPackages()) == A.NO_PACKAGES
          and A.message_for(A.NeedLogin()) == A.NEED_LOGIN
          and A.message_for(A.NotConnected()) == A.NO_CREDENTIALS)
    check("세 예외가 모두 NotConnected 로 잡힌다 (기존 호출부가 안 깨진다)",
          issubclass(A.MissingPackages, A.NotConnected)
          and issubclass(A.NeedLogin, A.NotConnected))
    # gmail 의 도구 둘 + calendar 의 읽기 하나 = 셋이 이유별 문장을 쓴다
    check("도구가 message_for 를 쓴다 (한 문장으로 안 묶는다)",
          _SRC.count("message_for(e)") == 2 and "message_for(e)" in _CAL,
          f"gmail {_SRC.count('message_for(e)')}곳")

    print(f"{NL}=== ⑪ 🚨 대화 턴 안에서 브라우저를 안 연다 ===")
    _AUTH2 = io.open(os.path.join(_ROOT, "tools", "google_auth.py"),
                     encoding="utf-8").read()
    _CONN = io.open(os.path.join(_ROOT, "scripts", "connect_google.py"),
                    encoding="utf-8").read()
    check("🚨 기본이 interactive=False 다",
          "interactive: bool = False" in _AUTH2)
    check("🚨 브라우저를 여는 곳이 interactive 안에만 있다",
          _AUTH2.count("run_local_server") == 1
          and "elif interactive:" in _AUTH2)
    check("도구는 interactive 를 안 켠다",
          "interactive=True" not in _SRC and "interactive=True" not in _CAL)
    check("연결 스크립트만 켠다", "interactive=True" in _CONN)
    check("토큰이 없으면 **멈추지 않고** NeedLogin 을 던진다",
          "raise NeedLogin" in _AUTH2)
    check("갱신(refresh)은 대화 중에도 된다 (브라우저가 필요 없다)",
          "creds.refresh(Request())" in _AUTH2)
    check("왜 그런지 BL-69 를 근거로 적어 뒀다", "BL-69" in _AUTH2)
    check("🚨 연결 스크립트가 «토큰 받음»에서 끝내지 않고 **실제로 읽어 본다**",
          "실제로 읽히는지 확인" in _CONN and "getProfile" in _CONN)

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
