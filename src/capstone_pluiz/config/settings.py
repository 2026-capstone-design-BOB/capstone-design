# config/settings.py
import os
from dotenv import load_dotenv

# .env 파일에서 환경 변수를 로드합니다.
load_dotenv()

# LLM 모드 설정
# "local" = Ollama만 사용 (API 키 없어도 됨)
# "claude" = Claude API 사용
# "gpt" = OpenAI API 사용
# "gemini" = Gemini API 사용

# LLM 모드 설정
LLM_MODE = "local"  # 명령 분류용 (llama3)
SUPERVISOR_MODE = "gemini"  # 관리자 에이전트용

# 로컬 모델 설정
LOCAL_MODEL = "llama3"
OLLAMA_URL = "http://localhost:11434"

<<<<<<< Updated upstream
# API 키
CLAUDE_API_KEY = ""
OPENAI_API_KEY = ""
GEMINI_API_KEY = "AIzaSyAi2Zgu5UgGrcGSefp7s-EQRn3D_gyUd80"
=======
# API 키 (.env 파일에 저장된 값을 안전하게 불러옵니다)
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
>>>>>>> Stashed changes

# Open Interpreter 설정
INTERPRETER_AUTO_RUN = False
INTERPRETER_SAFE_MODE = True