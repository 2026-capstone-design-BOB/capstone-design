# -*- coding: utf-8 -*-
"""구글 계정 연결 — **한 번만 돌리는 것** (2026-09-24)

    conda activate pluiz
    python scripts/connect_google.py          # 연결한다
    python scripts/connect_google.py --check  # 상태만 본다 (브라우저 안 열림)

안내문: [`docs/구글_연결.md`](../docs/구글_연결.md)

## 🚨 왜 «대화로» 하지 않고 이 파일이 따로 있나

로그인은 브라우저를 열고 **사용자가 «허용»을 누를 때까지 기다린다.**
그게 대화 턴 안에서 일어나면 **서버가 거기서 멈춘다** — 말을 걸었는데 아무 대답이
없고, 사용자는 왜 멈췄는지 모른다. [BL-69](../docs/BACKLOG.md) 가 정확히 그 모양이었다
(STT 가 안 돌아와 턴이 통째로 멈췄다).

🔑 **그래서 브라우저를 여는 곳은 이 파일 하나다.** 도구(`list_emails`·
`list_calendar_events`)는 **이미 있는 토큰만** 쓰고, 없으면 *"터미널에서 한 번
돌려 주세요"* 라고 **말하고 끝낸다.**

📌 2026-09-24 실기에서 사용자가 첫 연결에서 막혔고, 원인은 둘이었다 —
   **패키지가 아예 없었고**(설치된 적이 없다), 오류 문장이 그걸 «설정을 다시 하세요»로
   뭉뚱그렸다. 둘 다 고쳤다.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(description="구글 계정을 한 번 연결한다")
    ap.add_argument("--check", action="store_true",
                    help="상태만 본다 (브라우저를 안 연다)")
    args = ap.parse_args()

    from tools.google_auth import (CREDS_PATH, SCOPES, TOKEN_PATH,
                                   MissingPackages, NeedLogin, NotConnected,
                                   get_service)

    print("=" * 66)
    print("구글 계정 연결 — 일정과 메일이 **같은 인증 한 번**을 씁니다")
    print("=" * 66)

    # ── 1. 자격증명 ────────────────────────────────────────────────
    if not os.path.exists(CREDS_PATH):
        print(f"\n✗ 자격증명 파일이 없어요:\n    {CREDS_PATH}")
        print("\n  구글 클라우드에서 받은 JSON 을 **이 이름으로** 그 자리에 두세요.")
        print("  받는 법은 docs/구글_연결.md §1~4 에 있습니다.")
        return 1
    print(f"\n✓ 자격증명 파일 확인 ({os.path.getsize(CREDS_PATH)} bytes)")

    # ── 2. 패키지 ─────────────────────────────────────────────────
    missing = []
    for mod, pkg in (("google_auth_oauthlib", "google-auth-oauthlib"),
                     ("googleapiclient", "google-api-python-client"),
                     ("google.oauth2", "google-auth")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"\n✗ 필요한 프로그램이 빠져 있어요: {', '.join(missing)}")
        print(f"\n    pip install {' '.join(missing)}")
        print("\n  🔑 설정을 다시 하실 필요는 없어요 — 위 한 줄이면 됩니다.")
        return 1
    print("✓ 필요한 프로그램 확인")

    print(f"\n  받을 권한 {len(SCOPES)}개:")
    for s in SCOPES:
        tail = s.rsplit("/", 1)[-1]
        what = {"calendar.events": "일정 읽기·추가",
                "gmail.readonly": "메일 읽기 (보내기·초안·삭제는 **불가능**)"}.get(tail, "")
        print(f"    · {tail:<20} {what}")

    if args.check:
        state = "있음" if os.path.exists(TOKEN_PATH) else "없음"
        print(f"\n  토큰 파일: {state}")
        print("\n(--check 라서 여기까지만 봤어요. 연결하려면 그냥 돌리세요.)")
        return 0

    # ── 3. 로그인 ─────────────────────────────────────────────────
    print("\n▶ 브라우저가 열립니다. 계정을 고르고 **허용**을 눌러 주세요.")
    print('  ⚠️ "Google에서 확인하지 않은 앱입니다" 는 정상이에요 —')
    print("     [고급] → [Pluiz(안전하지 않음)으로 이동] 을 누르면 됩니다.")
    print("  (창이 안 열리면 터미널에 뜨는 주소를 직접 여세요)\n")

    try:
        service = get_service("calendar", "v3", interactive=True)
    except MissingPackages as e:
        print(f"✗ {e}")
        return 1
    except NotConnected as e:
        print(f"✗ {e}")
        return 1
    except Exception as e:                                    # noqa: BLE001
        print(f"\n✗ 연결하지 못했어요 — {type(e).__name__}: {e}")
        print("\n  자주 막히는 자리:")
        print("   · 403 access_denied  → 동의 화면의 «테스트 사용자»에 본인 계정을 넣으세요")
        print("   · API has not been used → 구글 콘솔에서 Calendar·Gmail API 를 켜세요")
        print("   · 그 밖에는 docs/구글_연결.md §6 을 보세요")
        return 1

    print(f"\n✓ 토큰을 저장했어요: {TOKEN_PATH}")

    # ── 4. 실제로 되는지 본다 ──────────────────────────────────────
    #   🚨 «토큰을 받았다»와 «실제로 읽힌다»는 다르다. 여기서 한 번씩 불러 본다 —
    #     안 그러면 사용자가 대화에서 처음 알게 된다.
    print("\n▶ 실제로 읽히는지 확인합니다 (내용은 안 보여 드립니다)")
    ok = True
    try:
        # 🚨 **도구가 실제로 부르는 호출로 확인한다.** (2026-09-24 실기에서 걸렸다)
        #
        #   처음에는 `calendarList().list()` 로 확인했는데 **403 이 났다.**
        #   `calendar.events` 범위는 «일정 읽기·쓰기»를 주지만 «내 캘린더 목록»은
        #   **안 준다** — 더 넓은 권한이 필요한 별개 자원이고 우리 기능에는 하나도
        #   필요 없다. 그래서 **설정이 멀쩡한데 «캘린더가 안 된다»고 말했다.**
        #
        # 🔑 이 저장소가 측정 도구마다 못 박아 둔 규칙과 같은 자리다 —
        #   «런타임을 다시 구현하지 않는다. 실제로 도는 그 함수를 부른다.»
        #   확인 코드가 대리(proxy)를 부르면 확인이 아니라 **다른 것을 재는 것**이다.
        service.events().list(calendarId="primary", maxResults=1).execute()
        print("  ✓ 일정 읽기")
    except Exception as e:                                    # noqa: BLE001
        ok = False
        print(f"  ✗ 일정 읽기 — {type(e).__name__}: {str(e)[:90]}")
    try:
        gm = get_service("gmail", "v1")
        prof = gm.users().getProfile(userId="me").execute()
        print(f"  ✓ 메일 읽기 ({prof.get('emailAddress', '')})")
    except Exception as e:                                    # noqa: BLE001
        ok = False
        print(f"  ✗ 메일 읽기 — {type(e).__name__}: {str(e)[:90]}")
        print("     (Gmail API 를 안 켰거나, 동의 화면에서 메일 권한을 안 넣으셨을 수 있어요)")

    if not ok:
        print("\n⚠️ 하나가 안 됩니다. docs/구글_연결.md §6 을 보세요.")
        return 1

    print("\n" + "=" * 66)
    print("✅ 끝났습니다. 이제 서버를 띄우고 말을 걸어 보세요.")
    print('   "오늘 일정 뭐야"   ·   "밤새 온 메일 있어?"')
    print("\n⚠️ 동의 화면이 «테스트» 상태면 토큰이 7일마다 끊깁니다.")
    print("   그때는 이 명령을 한 번 더 돌리면 됩니다 (전시회 당일 아침 점검에 넣어 두세요).")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
