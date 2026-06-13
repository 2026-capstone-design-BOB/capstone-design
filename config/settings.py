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

    # 에이전트
    agent_max_iterations: int = 10   # 무한루프 방지
    agent_timeout: int = 30          # 초

    # STT
    whisper_model: str = "base"      # tiny / base / small / medium
    whisper_language: str = "ko"

    # TTS
    tts_voice: str = "ko-KR-SunHiNeural"   # 자연스러운 한국어 여성 음성

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
    def active_api_key(self) -> str:
        return {
            "gemini": self.gemini_api_key,
            "claude": self.claude_api_key,
            "openai": self.openai_api_key,
        }[self.llm_provider]


@lru_cache
def get_settings() -> Settings:
    return Settings()
