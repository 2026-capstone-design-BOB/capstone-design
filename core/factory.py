"""
에이전트 팩토리 (M1-P1.5-d)
===========================
`.env`의 USE_GRAPH 플래그로 신(그래프)/구(기존) 코어를 선택한다.
- USE_GRAPH=false (기본): 기존 PluizAgent — 지금까지와 100% 동일 동작.
- USE_GRAPH=true        : 신규 PluizGraphAgent (그래프 이관본).

두 코어 모두 동일 공개 API(run_async / stream)를 가지므로 호출부(main.py)는 불변.
문제 시 플래그만 false로 되돌리면 즉시 원복.
"""

from __future__ import annotations


def _use_graph() -> bool:
    from config.settings import get_settings
    return bool(getattr(get_settings(), "use_graph", False))


def get_active_agent():
    """설정에 따라 활성 에이전트 싱글톤을 반환."""
    if _use_graph():
        from core.graph_agent import get_graph_agent
        return get_graph_agent()
    from core.agent import get_agent
    return get_agent()


def reset_active_agent():
    """API 키/설정 변경 후 신·구 코어 싱글톤 모두 초기화."""
    try:
        from core.agent import reset_agent
        reset_agent()
    except Exception:
        pass
    try:
        from core.graph_agent import reset_graph_agent
        reset_graph_agent()
    except Exception:
        pass
