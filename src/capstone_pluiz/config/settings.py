# config/settings.py
import os
from dotenv import load_dotenv


# API 키 (환경변수 우선, 없으면 직접 입력)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 로컬 모델 설정
LOCAL_MODEL = "llama3"
OLLAMA_URL = "http://localhost:11434"
# LLM 모드 설정
LLM_MODE = "local"  # 명령 분류용 (llama3)
SUPERVISOR_MODE = "gemini"  # 관리자 에이전트용

# 로컬 모델 설정
LOCAL_MODEL = "llama3"
OLLAMA_URL = "http://localhost:11434"

# API 키 (.env 파일에 저장된 값을 안전하게 불러옵니다)
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Open Interpreter 설정
INTERPRETER_AUTO_RUN = False
INTERPRETER_SAFE_MODE = True
