# app/server.py
import sys
import os
import subprocess
import time
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from app.agents.local_agent import LocalAgent
from app.router.command_router import CommandRouter
from app.services.stt import STTService
# from app.services.tts import TTSService  # OpenAI API 키 필요 — 추후 활성화

def start_ollama():
    try:
        requests.get("http://localhost:11434/api/tags", timeout=2)
        print("[Ollama] 이미 실행 중")
    except:
        print("[Ollama] 시작 중...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        print("[Ollama] 시작 완료")

start_ollama()

app = FastAPI(title="Pluiz Backend Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent  = LocalAgent()
router = CommandRouter()
stt    = STTService(mode="google")  # OpenAI 키 없이 동작하는 기본 모드

# tts = TTSService(voice="nova")  # OpenAI API 키 필요 — 추후 활성화

class UserRequest(BaseModel):
    text: str

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Pluiz 서버 정상 동작 중"}

@app.get("/api/status")
def get_status():
    return {"status": "ready"}

@app.post("/api/execute")
async def execute_command(request: UserRequest):
    try:
        print(f"[서버] 수신: {request.text}")
        command = agent.analyze_command(request.text)
        print(f"[서버] 분석: {command}")
        result = router.route(command, request.text)
        return {"status": "success", "command": command, "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    try:
        audio_bytes = await audio.read()
        filename    = audio.filename or "audio.webm"
        text        = stt.transcribe_audio_bytes(audio_bytes, filename)
        if not text:
            return {"status": "error", "message": "음성 인식 실패"}
        return {"status": "success", "text": text}
    except Exception as e:
        print(f"[STT 오류] {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/tts")
async def text_to_speech(request: UserRequest):
    # OpenAI API 키 필요 — 추후 활성화
    # try:
    #     audio_bytes = tts.synthesize(request.text)
    #     if not audio_bytes:
    #         return Response(status_code=500)
    #     return Response(content=audio_bytes, media_type="audio/mpeg")
    # except Exception as e:
    #     return Response(status_code=500)
    return Response(status_code=204)  # No Content — TTS 비활성화 상태

@app.post("/api/voice-execute")
async def voice_execute(audio: UploadFile = File(...)):
    try:
        audio_bytes = await audio.read()
        filename    = audio.filename or "audio.webm"
        user_text   = stt.transcribe_audio_bytes(audio_bytes, filename)
        if not user_text:
            return {"status": "error", "message": "음성 인식 실패"}

        print(f"[Voice] STT 결과: {user_text}")
        command    = agent.analyze_command(user_text)
        result     = router.route(command, user_text)
        speak_text = result if isinstance(result, str) else "명령을 실행했습니다."

        # TTS 비활성화 상태 — 텍스트로만 반환
        return {"status": "success", "text": user_text, "result": speak_text}
    except Exception as e:
        print(f"[Voice 오류] {e}")
        return {"status": "error", "message": str(e)}