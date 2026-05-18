# config/settings.py

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

# API 키
CLAUDE_API_KEY = ""
OPENAI_API_KEY = ""
GEMINI_API_KEY = "AIzaSyBqC3UPUtcmA5hRLjkSEPJeoryDzpmVqCs"

# Open Interpreter 설정
INTERPRETER_AUTO_RUN = False
INTERPRETER_SAFE_MODE = True