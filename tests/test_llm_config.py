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

## 🚨 BL-59 — **건너뛴 것을 «통과»라고 말하지 않는다** (2026-09-18 해결)

예전에는 `langchain_google_genai` 가 없으면 §1이 통째로 사라지고 **`2/2 통과` ·
종료코드 0** 이 나왔다. §1은 BL-57의 회귀 방지 **본체**다 — 그게 조용히 없어지면
남는 것은 BL-57과 무관한 두 건뿐인데 화면은 초록이다.
**«도구가 거짓 성공을 보고한다»(BL-58)의 테스트 판본**이고, 이 저장소가 여섯 번
고친 «확인하지 않고 됐다고 말하는 것»과 같은 모양이다.

이제 **건너뛴 건수를 세어 «판정 불가»로 죽는다.** 통과 건수도 올라가지 않는다.
🔑 **CI(ubuntu)는 이 파일을 아예 안 돌린다** — 거긴 `langgraph`·`langchain-core`만
   일부러 설치하는 잡이라 **항상 판정 불가**가 된다. `test_dependencies.py` 와 같은
   이유·같은 방식으로 제외했다(`.github/workflows/tests.yml`).
   **«조용한 초록»을 «명시적 제외»로 바꾼 것이다** — 없던 검사가 생기진 않지만,
   **없다는 사실이 보이게** 됐다.
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
    passed = total = skipped = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    def cannot_judge(names, why):
        """검사하지 못한 것을 **세어서** 남긴다.

        🚨 그냥 `print` 하고 넘어가면 «2/2 통과»가 된다(BL-59). 건너뛴 것은
           통과가 아니라 **판정 불가**다 — 합계에도 넣지 않고, 종료코드로 말한다.
        """
        nonlocal skipped
        for n in names:
            skipped += 1
            print(f"  ⬜ 판정 불가 {n}")
        print(f"     └ {why}")

    try:
        import langchain_google_genai  # noqa: F401
        has_gemini = True
    except ImportError:
        has_gemini = False

    # ── §1 gemini는 thinking을 끄고 만든다 ────────────────────────────
    print("\n§1 thinking 차단 (BL-57 본체)")
    if not has_gemini:
        cannot_judge(
            ["thinking_budget=0 이 걸려 있다",
             "temperature=0",
             "모델명이 설정에서 온다",
             "모델명을 코드에 박지 않았다"],
            "langchain_google_genai 가 없다 — `pluiz` 환경이 아니다. "
            "BL-57 방어가 살아 있는지 **여기서는 알 수 없다**")
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

    # 🚨 여기가 BL-59 의 본체다. **못 잰 것이 있으면 «통과»라는 말을 아예 안 쓴다.**
    #    «2/2 통과»는 훑어보는 사람에게 초록으로 읽힌다 — 그게 이 결함이 한 일이다.
    if skipped:
        print(f"\n결과: {passed}/{total} · 🚨 판정 불가 {skipped}건 — 초록이 아니다")
        print(f"   BL-57 방어 {skipped}건을 못 쟀다. `conda activate pluiz` 로 다시 돌릴 것")
    else:
        print(f"\n결과: {passed}/{total} 통과")
    return passed == total and skipped == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
