# config/settings.py
import os
from dotenv import load_dotenv

load_dotenv()

# API 키 (환경변수 우선, 없으면 직접 입력)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 로컬 모델 설정
LOCAL_MODEL = "llama3"
OLLAMA_URL = "http://localhost:11434"