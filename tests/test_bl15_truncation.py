"""
BL-15 — 캐시가 명령을 **조용히 절단**하던 것 검증
실행: python tests/test_bl15_truncation.py

## 무슨 일이 있었나 (2026-09-03 실기)

```
👤 아니 그냥 새로 메모장 열어서 거기에 회의록이라고 써줘
🤖 ✓ 메모장 창을 앞으로 가져왔습니다.        ← "회의록 써줘"가 통째로 증발
```
> *"메모장에 회의록 써달라고 하니까 창을 앞으로 가져왔잖아. 회의록이라고 텍스트
>  작성해달라고 한 거는 씹었어."*

캐시는 문장에서 entity 하나 + action 하나만 집어내고 **나머지는 보지 않는다.**
`(notepad, open)`으로 0.90 확신 히트 → `open_app`만 실행. LLM은 문장을 본 적도 없어
"새로"(=새 탭)도 반영되지 않았다. 로그에는 성공으로 남는다.

## 이 테스트가 지키는 것

**두 방향을 같이 본다** — 한쪽만 보면 반대편으로 넘어간다(이 프로젝트가 이미 두 번 겪었다).
  - 절단되던 명령이 이제 캐시를 **포기**하는가 (LLM으로 가는가)
  - 멀쩡한 명령이 여전히 캐시를 **타는가** ← 여기가 더 중요하다.
    캐시를 못 타면 오프라인 실행이 죽고 응답이 느려진다.

실제로 만들면서 오탐 5건이 나왔고(`"볼륨 좀 올려줘"` · `"음소거 해줘"` ·
`"스크린샷 좀 찍어줘"` …) 전부 아래 ①에 케이스로 남겼다.
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.command_cache import get_cache
from core.fast_path import has_uncovered_command, is_compound_command

passed = total = 0

def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


cache = get_cache()

def uses_cache(text: str) -> bool:
    """이 발화가 캐시로 처리되는가(=LLM을 안 거치는가)."""
    if is_compound_command(text):
        return False
    if cache.find(text) is None:
        return False
    return not cache.has_uncovered_command(text)


# ══════════════════════════════════════════════════════════════════
print("=== ① 멀쩡한 명령은 계속 캐시를 탄다 (오탐 방지) ===")
print("    ※ 여기가 깨지면 오프라인 실행이 죽고 전부 느려진다")

NORMAL = [
    "메모장 열어줘", "메모장 켜줘", "메모장 좀 열어봐", "메모장 띄워줘",
    "메모장 열어줘 빨리", "메모장 열어줘 제발", "메모장 지금 열어줘",
    "크롬 열어줘", "크롬 종료해줘", "계산기 꺼줘", "계산기 실행해줘",
    "탐색기 열어줘 고마워",
    # ↓ entity와 action이 **같은 낱말**인 명령. 동사를 따로 데리고 다닌다.
    #   만들면서 여기서 오탐이 났다 — "해줘"·"찍어줘"가 잔여 명령으로 읽혔다.
    "음소거 해줘", "음소거 좀 해줘",
    "스크린샷 찍어줘", "스크린샷 좀 찍어줘", "스크린샷 다시 찍어줘",
    # ↓ action 트리거가 삽입어 때문에 안 걸려 Stage 2로 가던 것들
    "볼륨 올려줘", "볼륨 좀 올려줘",
    # ↓ 수식어처럼 보이지만 의미를 안 바꾸는 것. 여기가 막히면 안 된다
    "메모장 다시 열어줘",
]
for t in NORMAL:
    check(f"캐시 유지 — {t!r}", uses_cache(t), f"→ 캐시를 못 탄다")


print("\n=== ② 잘려나가던 명령은 캐시를 포기한다 (LLM이 문장 전체를 본다) ===")

TRUNCATED = [
    # 실기에서 실제로 터진 발화
    "아니 그냥 새로 메모장 열어서 거기에 회의록이라고 써줘",
    # BACKLOG BL-15에 적혀 있던 예시
    "메모장 열어서 회의록 적어줘",
    # 같은 계열 — 동사만 바꾼 것. 정규식 땜질이면 여기서 또 터진다
    "메모장 띄워서 회의록 써줘",
    "계산기 실행해서 계산해줘",
    "크롬 열어서 날씨 검색해줘",
    "스크린샷 찍어서 메모장에 붙여줘",
    # 기존 _COMPOUND_CMD가 이미 잡던 것들 (회귀 확인)
    "크롬 켜고 유튜브 틀어줘",
    "메모장 열어줘 그리고 뭐라고 써줘",
]

# ── 파라미터를 바꾸는 수식어 ──────────────────────────────────────
# 캐시 엔트리는 도구 이름만 저장하고 **파라미터를 저장하지 않는다**(P4 오염 방지).
# 그래서 new=True 같은 걸 표현할 수 없다. 2026-09-03 실기에서 사용자가 지적:
#   *"메모장을 새로 열라고 하면 기존 창을 앞으로 가져오는 게 아니라 새 탭을 추가하라는 건데"*
# 그날 이 발화가 우연히 캐시 미스라 통과했을 뿐, "새로 메모장 열어줘"는 깨져 있었다.
MODIFIED = [
    "새로 메모장 열어줘",
    "메모장 새로 열어줘",
    "메모장 하나 더 열어줘",
    "크롬 새 탭 열어줘",
]
for t in MODIFIED:
    check(f"캐시 포기 — {t!r} (new=True를 캐시가 못 담는다)",
          not uses_cache(t), "→ '새로'가 무시된다")
for t in TRUNCATED:
    check(f"캐시 포기 — {t!r}", not uses_cache(t), f"→ 캐시가 삼킨다")


print("\n=== ③ 판정은 Stage 1(intent) 히트에만 적용된다 ===")
# Stage 2는 문장 전체의 문자열 유사도(≥0.80)라 뒷문장이 붙으면 점수가 알아서 떨어진다.
# 이 구분을 빼면 ①이 무더기로 깨진다 — 실제로 그렇게 깨뜨려 봤다.
check("entity가 없으면 검사하지 않는다",
      not cache.has_uncovered_command("오늘 날씨 알려줘"))
check("action이 없으면 검사하지 않는다",
      not cache.has_uncovered_command("메모장이 뭐야 알려줘"))
check("엔티티 없는 시스템 명령을 막지 않는다 — '최대화 해줘'",
      not cache.has_uncovered_command("최대화 해줘"))
# "새로"를 어절 **완전일치**로만 본다. 부분일치면 "새로고침"이 걸린다.
check("'새로고침'을 '새로'로 오인하지 않는다",
      not cache.has_uncovered_command("크롬 새로고침 해줘"))
# ※ "최대화 해줘"는 **이 수정 전에도 캐시 미스**였다(엔티티가 없어 intent가 안 잡힌다).
#   여기서 보는 건 "내가 새로 막지는 않았다"는 것뿐이다. 캐시 히트 여부는 별개 문제다.
check("빈 입력은 False", not cache.has_uncovered_command(""))
check("공백만 있어도 False", not cache.has_uncovered_command("   "))


print("\n=== ④ fast_path 어댑터가 이 판정을 실제로 쓴다 ===")

class _StubEntry:
    pattern = "메모장 열어줘"

class _StubCache:
    """has_uncovered_command를 가진 캐시 — 잔여 명령이면 실행하지 않아야 한다."""
    def __init__(self, uncovered): self._unc = uncovered; self.executed = []
    def find(self, text): return (_StubEntry(), 0.9)
    def has_uncovered_command(self, text): return self._unc
    def execute_sync(self, entry): self.executed.append(entry.pattern); return "실행됨"
    def increment_hit(self, pattern): pass

class _OldCache(_StubCache):
    """메서드가 없는 구버전/mock 캐시 — 예전 동작(그냥 실행)이어야 한다."""
    has_uncovered_command = None

from core.fast_path import resolve_fast_path

c1 = _StubCache(uncovered=True)
check("잔여 명령 → 캐시 실행 안 함", resolve_fast_path("x", c1) is None)
check("잔여 명령 → execute_sync 미호출", c1.executed == [], f"→ {c1.executed}")

c2 = _StubCache(uncovered=False)
check("잔여 없음 → 평소대로 실행", resolve_fast_path("x", c2) == "실행됨")

c3 = _OldCache(uncovered=True)
check("메서드 없는 캐시 → 예전 동작 유지", resolve_fast_path("x", c3) == "실행됨")

check("has_uncovered_command 헬퍼는 예외를 삼킨다",
      has_uncovered_command(object(), "아무거나") is False)


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
