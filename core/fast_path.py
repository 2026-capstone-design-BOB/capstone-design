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
"""

from __future__ import annotations

import re
from typing import Optional, Callable, Any


# ── 복합 명령 감지 패턴 (agent.py와 동일 규칙) ──────────────────────
# "닫고/열고" 동사 연결형 + 문맥 참조형("방금","빼고" 등) → 캐시 바이패스
_COMPOUND_CMD = re.compile(
    r'이랑|랑\s|하고\s|그리고\s|그리고$|,\s*그리고|,\s*그다음|다음에\s'
    r'|닫고\s|열고\s|켜고\s|끄고\s|보내고\s|저장하고\s|검색하고\s|만들고\s'
    r'|방금|아까|빼고|제외하고|것들|이것|그것|다\s*닫|전부\s*닫|모두\s*닫'
)

# 단어 하나짜리 앱 이름 — 2개 이상이면 다중 앱 명령
_MULTI_APP_NAMES = frozenset([
    '크롬', '메모장', '계산기', '탐색기', '카카오', '엣지', '스팀',
    '디스코드', '슬랙', '노트패드', '워드', '엑셀', '파워포인트',
])


def is_multi_app_command(text: str) -> bool:
    """두 개 이상의 앱 이름이 포함된 다중 앱 명령인지."""
    return sum(1 for app in _MULTI_APP_NAMES if app in text) >= 2


def is_compound_command(text: str) -> bool:
    """복합/문맥참조 명령인지(=빠른 경로를 건너뛰고 LLM으로 보내야 하는지)."""
    return bool(_COMPOUND_CMD.search(text)) or is_multi_app_command(text)


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
            if hit:
                entry, _score = hit
                result = cache.execute_sync(entry)
                try:
                    cache.increment_hit(entry.pattern)
                except Exception:
                    pass
                return str(result)
        except Exception as e:
            print(f"[fast_path] 캐시 오류(무시): {type(e).__name__}: {e}")

    # 3. 결정론적 라우터
    if router_resolve is not None:
        try:
            routed = router_resolve(text)
            if routed is not None:
                return str(routed)
        except Exception as e:
            print(f"[fast_path] 라우터 오류(무시): {type(e).__name__}: {e}")

    return None
