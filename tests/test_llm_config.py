"""
LLM 구성 계약 — 흔들리는 경로를 다시 밟지 않는다 (BL-57)
실행: python tests/test_llm_config.py

2026-09-15 라이브에서 **모든 명령이 죽었다.** 원인은 우리 코드가 아니라
`gemini-2.5-flash`(버전이 굴러가는 **별칭**)의 thinking 경로였다:

    · 도구 41개만 바인딩                  → delete_file 정상
    · + 시스템 프롬프트                   → **out=0 · content 없음 · 도구 호출 없음**
    · + 시스템 프롬프트 + thinking_budget=0 → 정상

🚨 **코드는 그대로인데 같은 날 12:23엔 되고 18:27엔 안 됐다.**
그래서 이 파일이 지키는 것은 «동작»이 아니라 **«우리가 내린 결정»** 이다 —
`thinking_budget=0`을 누군가 «불필요해 보인다»며 지우면 여기서 먼저 깨진다.

⚠️ 실제 API를 부르지 않는다(mock 스위트에 들어가야 한다). **인자만 검사한다.**
   라이브 확인은 D-1 점검 목록의 «모델 호출 한 번»이 담당한다.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import build_llm


class FakeSettings:
    """build_llm이 읽는 최소 설정."""

    def __init__(self, provider="gemini", gemini_model="gemini-2.5-flash"):
        self.llm_provider = provider
        self.gemini_model = gemini_model
        self.gemini_api_key = "test-key"
        self.claude_model = "claude-sonnet-4-5"
        self.claude_api_key = "test-key"
        self.openai_model = "gpt-4o"
        self.openai_api_key = "test-key"


def run():
    passed = total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    try:
        import langchain_google_genai  # noqa: F401
        has_gemini = True
    except ImportError:
        has_gemini = False

    # ── §1 gemini는 thinking을 끄고 만든다 ────────────────────────────
    print("\n§1 thinking 차단 (BL-57 본체)")
    if not has_gemini:
        print("  · langchain_google_genai 미설치 — §1 건너뜀")
    else:
        llm = build_llm(FakeSettings())
        check("thinking_budget=0 이 걸려 있다 (없으면 모든 호출이 out=0)",
              getattr(llm, "thinking_budget", None) == 0)
        check("temperature=0 (시연에서 같은 말이 같은 결과를 내야 한다)",
              getattr(llm, "temperature", None) == 0)

        # 🔑 별칭이 또 굴러가면 `.env`의 GEMINI_MODEL로 날짜 고정 버전을 지정해
        #   피한다. 그 탈출구가 코드 상수로 막히면 안 된다.
        other = build_llm(FakeSettings(gemini_model="gemini-flash-latest"))
        check("모델명이 설정에서 온다 (.env로 되돌릴 수 있다)",
              "gemini-flash-latest" in getattr(other, "model", ""))
        check("모델명을 코드에 박지 않았다",
              "gemini-2.5-flash" not in getattr(other, "model", ""))

    # ── §2 provider 분기는 그대로다 ──────────────────────────────────
    print("\n§2 provider 분기")
    try:
        build_llm(FakeSettings(provider="없는provider"))
        check("모르는 provider는 ValueError", False)
    except ValueError:
        check("모르는 provider는 ValueError", True)
    except Exception as e:
        check(f"모르는 provider는 ValueError (실제: {type(e).__name__})", False)

    # ── §3 근거가 코드에 남아 있다 ───────────────────────────────────
    #
    # 🔑 이 검사가 §1과 겹쳐 보이지만 다르다. §1은 «값»을, §3은 «왜»를 지킨다.
    #   근거 없이 남은 인자는 다음 사람이 «정리»해 버린다 — 이 저장소가
    #   반복해서 데인 모양이다.
    print("\n§3 결정의 근거가 주석으로 남아 있다")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "core", "llm.py"), encoding="utf-8").read()
    check("thinking_budget 옆에 BL-57 근거가 적혀 있다",
          "thinking_budget" in src and "out=0" in src)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
