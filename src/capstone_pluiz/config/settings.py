# config/settings.py
import os
from dotenv import load_dotenv


GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
CLAUDE_API_KEY  = os.getenv("CLAUDE_API_KEY", "")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")

# 로컬 모델 설정
LOCAL_MODEL = "llama3"
OLLAMA_URL = "http://localhost:11434"

# LLM 모드 설정
LLM_MODE = "local"  # 명령 분류용 (llama3)
SUPERVISOR_MODE = "gemini"  # 관리자 에이전트용

# API 키 (.env 파일에 저장된 값을 안전하게 불러옵니다)
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Open Interpreter 설정
INTERPRETER_AUTO_RUN = False
INTERPRETER_SAFE_MODE = True

# .env에 API_PROVIDER=gemini / claude / openai 중 하나만 적으면 됨
# 기본값은 gemini
ACTIVE_PROVIDER = os.getenv("API_PROVIDER", "gemini").lower()

# provider별 기본 모델 (필요하면 .env에서 MODEL_ID로 오버라이드 가능)
DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash-lite",
    "claude": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
}
ACTIVE_MODEL = os.getenv("MODEL_ID", DEFAULT_MODELS.get(ACTIVE_PROVIDER, ""))
