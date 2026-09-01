"""
LLM Provider 추상화
-------------------
설정(`config/settings.py`)의 `llm_provider`에 따라 채팅 모델 인스턴스를 만든다.

원래 `core/agent.py`(구 엔진) 안에 `_build_llm`으로 있었으나, 신 엔진
(`core/graph_agent.py`)이 이 함수 하나 때문에 구 엔진 모듈을 import 해야 했다.
엔진 단일화(M1-P5) 때 독립 모듈로 분리했다.
→ 배경: docs/design/M1_P5_엔진단일화.md

provider별 패키지는 **함수 안에서 lazy import** 한다. 셋 다 설치돼 있지 않아도
이 모듈 자체는 import 되므로, mock 테스트가 LLM 패키지 없이 동작한다.
"""

from __future__ import annotations

from typing import Any


def build_llm(settings: Any = None):
    """설정에 따라 LLM 인스턴스 반환.

    Args:
        settings: `Settings` 객체. 생략하면 `get_settings()`로 가져온다.

    Raises:
        ValueError: 지원하지 않는 provider인 경우.
    """
    if settings is None:
        from config.settings import get_settings
        settings = get_settings()

    provider = settings.llm_provider

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=0,
        )
    elif provider == "claude":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.claude_api_key,
            temperature=0,
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0,
        )
    else:
        raise ValueError(f"지원하지 않는 LLM provider: {provider}")
