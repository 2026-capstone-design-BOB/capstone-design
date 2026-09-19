"""
Fast Path 어댑터 (M1-P1.5-a)
============================
그래프의 `fast_path` 노드가 사용할, LLM 없이 명령을 즉시 처리하는 통합 해석기.

기존 agent.py의 run_async에 흩어져 있던 다음 3가지를 하나의 순수 함수로 묶는다:
  1. 복합 명령 감지 → 빠른 경로 스킵(=LLM로)  (_COMPOUND_CMD, 다중 앱)
  2. 커맨드 캐시 조회·실행
  3. 결정론적 라우터 (youtube/map/folder/volume 등)

설계: 의존성 주입(DI). cache / router_resolve 를 인자로 받으므로
      Windows·LLM API 없이 mock으로 단위 테스트 가능. (agent.py 원본은 불변)

반환:
  - str  : 캐시/라우터가 처리한 결과 텍스트 (그래프는 이걸 messages에 기록)
  - None : 처리 불가 → 그래프는 agent(LLM) 노드로 진행

## 🚨 이 경로에는 **그물이 없다** — 여기서 지어낸 말은 아무도 안 잡는다 (감사 G-03)

여기가 문자열을 돌려주면 그래프는 그걸 그대로 `AIMessage` 로 만들고
`decision = "fast_hit"` 으로 턴을 끝낸다. 그 턴에 `output_guard` 의 방어 넷은 이렇다:

| 그물 | 캐시/라우터 히트 턴에서 | 왜 |
|---|---|---|
| `watch_notice_to_deliver` | 해당 없음 | 감시 도구는 빠른 경로 대상이 아니다 |
| `detect_watch_lie` | ❌ **명시적으로 제외** | 도구를 그래프 **밖에서** 돌려 «도구 0개»로 보인다 — 안 거르면 멀쩡히 실행된 응답을 거짓말로 몬다 |
| `verify_output` ① 빈 응답 | ❌ 무력 | 응답이 비지 않는다 |
| `verify_output` ② 도구 오류 | ❌ **구조적으로 무력** | `ToolMessage` 가 없어 `tool_errors` 가 **항상 빈 리스트**다 |

누가 빠뜨린 게 아니라 **절대규칙 2**(캐시 결과도 `messages` 에 누적한다)의 그림자다 —
AIMessage 하나만 남기기로 한 설계가 «검사할 재료»도 같이 없앤다. 그물을 새로 치려면
그 규칙을 건드려야 하고, 거기가 **맥락 붕괴 버그가 났던 자리**다.

## 📜 그래서 계약으로 못 박는다 — 진실을 아는 자리는 **정확히 둘**

| # | 자리 | 무엇을 지는가 |
|---|---|---|
| ① | `CommandCache._verdict` | 돌린 도구들의 **다 됨 / 일부 / 전부 실패**를 사실대로 말한다 (감사 G-01) |
| ② | 각 도구의 반환값 (`core/tool_result.py` 의 ✓/✗) | **라우터는 그걸 그대로 돌려준다** |

🚫 **이 파일도 `router.py` 도 결과 문장을 만들지 않는다.** 여기서 «✓ …했어요»를
지어내는 순간 그걸 검사할 그물이 **하나도 없다.**
→ [`tests/test_fast_hit_contract.py`](../tests/test_fast_hit_contract.py) 가 이 계약을 지킨다.

🔑 **감사가 «유일하게 진실을 아는 자리는 `execute_sync` 자신»이라고 적었는데 둘이었다** —
라우터가 같은 `fast_hit` 을 만든다. 2026-09-19에 바로잡았다.

⚠️ **실패는 전부 로그로 간다**(`logs/pluiz.log`). 2026-09-18까지 이 파일의 실패는
`print` 라 한 줄도 안 남았다 — 감사 G-02를 `command_cache.py` 에서만 메웠기 때문이다.
**빈도를 모르면 «고칠까»를 판단할 수 없다**(BL-23의 교훈).
"""

from __future__ import annotations

import re
from typing import Optional, Callable, Any

from core.logger import get_logger

# BL-15는 "고치기 전에 빈도부터 재라"가 원칙이었다. 고치면서 **함께** 잰다 —
# 이 로그가 임베딩 캐시(10월)의 "좋아졌다"를 숫자로 말할 근거가 된다.
_log = get_logger("FastPath")


# ── 복합 명령 감지 패턴 ────────────────────────────────────────────
# "닫고/열고" 동사 연결형 + 문맥 참조형("방금","빼고" 등) → 캐시 바이패스
_COMPOUND_CMD = re.compile(
    r'이랑|랑\s|하고\s|그리고\s|그리고$|,\s*그리고|,\s*그다음|다음에\s'
    r'|닫고\s|열고\s|켜고\s|끄고\s|보내고\s|저장하고\s|검색하고\s|만들고\s'
    r'|방금|아까|빼고|제외하고|것들|이것|그것|다\s*닫|전부\s*닫|모두\s*닫'
)

# ── 부정어 감지 (BL-02) ────────────────────────────────────────────
# 캐시는 entity(계산기) + action(열어)만 보고 매칭하므로 부정어를 무시한다.
# 그래서 "계산기 말고 다른거 열어"가 `계산기 열어줘`로 오매칭돼 계산기를 열었다.
# 부정어가 있으면 의미가 뒤집히므로 캐시를 건너뛰고 LLM이 문장 전체를 해석하게 한다.
#
# ※ 어절 경계를 요구한다(뒤에 공백 또는 문장 끝). "말고"를 무조건 찾으면
#   "말고기 검색해줘" 같은 정상 입력이 캐시를 못 타게 된다.
_NEGATION_CMD = re.compile(
    r'말고(?=\s|$)|말구(?=\s|$)|아니라(?=\s|$)|아니고(?=\s|$)'
    r'|대신(?=\s|$)|대신에(?=\s|$)|이외(?=\s|$)|외에(?=\s|$)'
    r'|하지\s*말|하지마|열지\s*마|끄지\s*마'
)


def has_negation(text: str) -> bool:
    """부정어가 있어 캐시 매칭을 신뢰할 수 없는 입력인지. (BL-02)"""
    return bool(_NEGATION_CMD.search(text))

# 단어 하나짜리 앱 이름 — 2개 이상이면 다중 앱 명령
_MULTI_APP_NAMES = frozenset([
    '크롬', '메모장', '계산기', '탐색기', '카카오', '엣지', '스팀',
    '디스코드', '슬랙', '노트패드', '워드', '엑셀', '파워포인트',
])


def is_multi_app_command(text: str) -> bool:
    """두 개 이상의 앱 이름이 포함된 다중 앱 명령인지."""
    return sum(1 for app in _MULTI_APP_NAMES if app in text) >= 2


def is_compound_command(text: str) -> bool:
    """복합/문맥참조/부정 명령인지(=빠른 경로를 건너뛰고 LLM으로 보내야 하는지)."""
    return (bool(_COMPOUND_CMD.search(text))
            or has_negation(text)
            or is_multi_app_command(text))


def has_uncovered_command(cache: Any, text: str) -> bool:
    """캐시가 문장의 **일부만** 이해했는가. (BL-15)

    판정 자체는 캐시가 한다 — entity/action 어휘를 가진 쪽이 거기이기 때문이다.
    여기서 다시 구현하면 두 벌이 되어 한쪽만 고쳐진다.
    메서드가 없는 mock/구버전 캐시면 False(=예전 동작).
    """
    fn = getattr(cache, "has_uncovered_command", None)
    if fn is None:
        return False
    try:
        return bool(fn(text))
    except Exception as e:
        _log.error("[잔여명령 검사] 실패(무시) | %r | %s: %s", text, type(e).__name__, e)
        return False


# 라우터 타입: user_input -> (결과 텍스트 | None)
RouterResolve = Callable[[str], Optional[str]]


def resolve_fast_path(
    user_input: str,
    cache: Any = None,
    router_resolve: Optional[RouterResolve] = None,
) -> Optional[str]:
    """빠른 경로 통합 해석 (동기 — 그래프 sync 경로용, P2).

    Args:
        user_input: 사용자 발화.
        cache: `find(text) -> (entry, score)|None`, `execute_sync(entry)->str`,
               `increment_hit(pattern)` 를 갖는 커맨드 캐시(또는 mock).
        router_resolve: 결정론적 라우터 동기 함수(또는 mock). 없으면 생략.

    Returns:
        처리 결과 문자열, 또는 None(=LLM로 진행).
    """
    text = (user_input or "").strip()
    if not text:
        return None

    # 1. 복합/문맥참조 명령 → 빠른 경로 스킵 (LLM이 맥락으로 처리)
    if is_compound_command(text):
        return None

    # 2. 커맨드 캐시
    if cache is not None:
        try:
            hit = cache.find(text)
            if hit and has_uncovered_command(cache, text):
                # 캐시가 문장의 일부만 이해했다. 실행하면 나머지 명령이 조용히 사라진다.
                # → LLM이 문장 전체를 보게 한다. (BL-15)
                _log.info("[BL-15] 잔여 명령 감지 → 캐시 포기, LLM으로: %r "
                          "(캐시가 잡은 패턴=%r)", text, getattr(hit[0], "pattern", "?"))
                return None
            if hit:
                entry, _score = hit
                result = cache.execute_sync(entry)
                # BL-28 곁들여 — **캐시가 어떤 도구를 돌렸는지 남긴다.**
                #
                # 캐시 히트는 `턴 완료`에 `도구=없음`으로 찍힌다(도구를 그래프 밖에서
                # 돌리므로 messages에 tool_calls가 없다). 그래서 2026-09-10 도구 사용
                # 실측에서 **볼륨·밝기·스크린샷·시간·배터리가 «한 번도 안 쓰인 도구»로
                # 집계됐다** — 실제로는 캐시가 그것들을 돌리고 있었는데도.
                # 이 줄이 있으면 분석기가 캐시 실행분을 되찾아 합칠 수 있다.
                # → docs/research/2026-09_도구사용_실측.md §1
                try:
                    names = [c.get("name", "?") for c in (entry.tool_calls or [])]
                    _log.info("[캐시 실행] 패턴=%r | 도구=%s",
                              entry.pattern, names or "없음")
                except Exception:
                    pass
                try:
                    cache.increment_hit(entry.pattern)
                except Exception:
                    pass
                return str(result)
        except Exception as e:
            # ⚠️ 여기로 오면 **라우터가 같은 발화에 다시 행동할 수 있다**(감사 G-18).
            #   지금은 흐름을 그대로 두고 **세기만 한다** — 빈도를 모르는 채
            #   빠른 경로의 제어 흐름을 바꾸는 것이 더 위험하다(BL-23).
            _log.error("[캐시] 실행=실패(라우터로 계속) | %r | %s: %s",
                       text, type(e).__name__, e)

    # 3. 결정론적 라우터
    if router_resolve is not None:
        try:
            routed = router_resolve(text)
            if routed is not None:
                return str(routed)
        except Exception as e:
            _log.error("[라우터] 실행=실패(LLM으로 계속) | %r | %s: %s",
                       text, type(e).__name__, e)

    return None
