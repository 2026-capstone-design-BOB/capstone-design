"""Pluiz 코어 — 에이전트 엔진 · 보안 · 캐시.

여기서 무거운 모듈을 eager import 하지 않는다. `core.graph_agent`는 langgraph를,
`core.tool_registry`는 Windows 의존 도구를 끌어오므로, 이 패키지를 import 하는 것만으로
그 의존이 따라오면 mock 테스트와 부분 import가 깨진다.
필요한 모듈은 사용하는 쪽에서 직접 import 할 것.

    from core.graph_agent import get_graph_agent
    from core.tool_registry import get_all_tools
"""
