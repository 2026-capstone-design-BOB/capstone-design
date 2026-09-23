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
            # 🚨 thinking을 끈다. 2026-09-15 라이브에서 **빈 응답**이 났다.
            #
            #   턴 완료 | 입력='a.txt 지워 줘' | 요청=없음 | 실행=없음
            #           | 사유=못함 | LLM 1회 | 토큰 in=5934 out=0
            #
            # 재현 결과가 명확했다(같은 질문·같은 도구 41개):
            #   · 도구만 바인딩            → delete_file 정상
            #   · + 시스템 프롬프트        → **out=0 · content 없음 · 도구 호출 없음**
            #   · + 시스템 프롬프트 + 이 줄 → 정상
            #
            # ⚠️ **코드는 그대로인데 같은 날 12:23엔 되고 18:27엔 안 됐다.**
            #    `gemini-2.5-flash`는 버전이 굴러가는 **별칭**이라 서버 쪽이 바뀐 것이다.
            #    우리가 고를 수 있는 건 «별칭을 바꾸는 것»(또 굴러간다)이 아니라
            #    **«흔들리는 경로를 안 쓰는 것»** 이라고 판단했다.
            #
            # 덤으로 thinking 토큰이 사라져 응답이 빨라지고 비용도 준다.
            # (단순 호출에서 출력 35토큰 중 33이 reasoning이었다)
            #
            # 📌 `gemini-2.0-flash`는 **이미 404**다 — 문서의 «2.0 Flash» 표기는 낡았다.
            thinking_budget=0,
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
