from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal
from functools import lru_cache


class Settings(BaseSettings):
    # LLM
    llm_provider: Literal["gemini", "claude", "openai"] = "gemini"
    gemini_api_key: str = ""
    claude_api_key: str = ""
    openai_api_key: str = ""

    # YouTube Data API v3
    youtube_api_key: str = ""

    # 모델 (비워두면 provider별 기본값 사용)
    gemini_model: str = "gemini-2.5-flash"
    claude_model: str = "claude-haiku-4-5-20251001"
    openai_model: str = "gpt-4o-mini"

    # 서버
    server_port: int = 8765
    server_host: str = "127.0.0.1"

    # 로컬 API 접근 제어 (BL-14)
    # 서버가 기동할 때마다 토큰을 발급해 cache/.auth_token 에 적고, Electron과 라이브
    # 테스트가 그 파일을 읽는다. 웹페이지는 로컬 파일을 못 읽으므로 명령을 넣을 수 없다.
    # ⚠️ false로 두면 아무 웹사이트가 PC 제어 명령을 넣을 수 있다. 디버깅용 탈출구다.
    auth_enabled: bool = True

    # 에이전트
    agent_max_iterations: int = 10   # 무한루프 방지
    agent_timeout: int = 30          # 초
    # ※ use_graph 플래그는 M1-P5(엔진 단일화)에서 제거됨.
    #   PluizGraphAgent가 유일한 엔진이다. → docs/design/M1_P5_엔진단일화.md

    # 커맨드 캐시 (P4)
    cache_learning: bool = True      # 동적 학습 on/off 스위치
    cache_max_dynamic: int = 200     # 동적 학습 상한(초과 시 LRU 정리)

    # STT
    whisper_model: str = "base"      # tiny / base / small / medium
    whisper_language: str = "ko"

    # TTS
    tts_voice: str = "ko-KR-SunHiNeural"   # 자연스러운 한국어 여성 음성

    # 웨이크워드 — 사용자가 직접 정한다
    # 쉼표로 구분. 비워두면 services/wakeword.py 의 기본값("플루이즈" 계열)을 쓴다.
    # 예: WAKE_WORDS=플루이즈,헤이 플루이즈,pluiz
    wake_words: str = ""
    wake_word_enabled: bool = True
    # 인식 튜닝 — 마이크/환경마다 달라서 코드 수정 없이 조절할 수 있게 뺐다
    wakeword_model: str = "base"          # tiny / base. ⚠️ base가 오히려 **5배 빠르다** —
                                          # tiny는 환각으로 수백 토큰을 뱉느라 시간을 다 쓴다
                                          # (2026-09-02 실측: tiny 61초 vs base 12.9초, 같은 오디오)
    wakeword_energy: float = 0.008        # 무음 스킵 임계. 낮출수록 작은 소리도 처리
                                          # (기본 0.015는 조용한 마이크에서 발화를 버렸다)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def active_model(self) -> str:
        return {
            "gemini": self.gemini_model,
            "claude": self.claude_model,
            "openai": self.openai_model,
        }[self.llm_provider]

    @property
    def wake_word_list(self) -> list[str]:
        """설정된 웨이크워드를 리스트로. 비어 있으면 빈 리스트(→ 호출부가 기본값 사용)."""
        return [w.strip() for w in self.wake_words.split(",") if w.strip()]

    @property
    def active_api_key(self) -> str:
        return {
            "gemini": self.gemini_api_key,
            "claude": self.claude_api_key,
            "openai": self.openai_api_key,
        }[self.llm_provider]


@lru_cache
def get_settings() -> Settings:
    return Settings()
