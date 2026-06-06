# app/server.py
import sys
import os
import subprocess
import time
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from app.agents.local_agent import LocalAgent
from app.router.command_router import CommandRouter
from app.services.stt import STTService
from app.services.tts import TTSService

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

agent = LocalAgent()
router = CommandRouter()
stt   = STTService(mode="openai")   # 웹 업로드용 OpenAI Whisper
tts   = TTSService(voice="nova")    # 한국어 친화적 voice

# ── 기존 텍스트 실행 엔드포인트 ───────────────────────────────
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
    """텍스트 명령 실행 (기존 기능 유지)"""
    try:
        print(f"[서버] 수신: {request.text}")
        command = agent.analyze_command(request.text)
        print(f"[서버] 분석: {command}")
        result = router.route(command, request.text)
        return {"status": "success", "command": command, "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ── 신규: STT 엔드포인트 ──────────────────────────────────────
@app.post("/api/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    """
    웹에서 녹음한 오디오 파일을 받아 텍스트로 변환.
    Content-Type: multipart/form-data, 필드명: audio
    지원 포맷: webm, wav, mp4, m4a, ogg 등 (Whisper API 지원 포맷)
    """
    try:
        audio_bytes = await audio.read()
        filename    = audio.filename or "audio.webm"
        text        = stt.transcribe_audio_bytes(audio_bytes, filename)

        if not text:
            return {"status": "error", "message": "음성 인식 실패"}
        return {"status": "success", "text": text}
    except Exception as e:
        print(f"[STT 엔드포인트 오류] {e}")
        return {"status": "error", "message": str(e)}

# ── 신규: TTS 엔드포인트 ──────────────────────────────────────
@app.post("/api/tts")
async def text_to_speech(request: UserRequest):
    """
    텍스트를 받아 MP3 오디오 바이트를 반환.
    프론트엔드에서 Audio 객체로 바로 재생 가능.
    """
    try:
        audio_bytes = tts.synthesize(request.text)
        if not audio_bytes:
            return Response(status_code=500)
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
        )
    except Exception as e:
        print(f"[TTS 엔드포인트 오류] {e}")
        return Response(status_code=500)

# ── 신규: STT → 명령실행 → TTS 통합 엔드포인트 ───────────────
@app.post("/api/voice-execute")
async def voice_execute(audio: UploadFile = File(...)):
    """
    음성 업로드 한 번으로 STT → 명령실행 → TTS 결과 MP3 반환.
    프론트엔드에서 이 엔드포인트 하나만 호출하면 됨.
    """
    try:
        # 1) STT
        audio_bytes = await audio.read()
        filename    = audio.filename or "audio.webm"
        user_text   = stt.transcribe_audio_bytes(audio_bytes, filename)

        if not user_text:
            return {"status": "error", "message": "음성 인식 실패"}

        print(f"[Voice] STT 결과: {user_text}")

        # 2) 명령 실행
        command = agent.analyze_command(user_text)
        result  = router.route(command, user_text)
        print(f"[Voice] 실행 결과: {result}")

        # 3) TTS (결과 요약 문장)
        speak_text  = result if isinstance(result, str) else "명령을 실행했습니다."
        audio_out   = tts.synthesize(speak_text)

        # 4) 텍스트 정보는 헤더에, 오디오는 body로 반환
        headers = {
            "X-User-Text": user_text,
            "X-Command":   str(command),
            "X-Result":    speak_text[:200],   # 헤더 길이 제한
        }
        return Response(
            content=audio_out or b"",
            media_type="audio/mpeg",
            headers=headers,
        )
    except Exception as e:
        print(f"[Voice 오류] {e}")
        return {"status": "error", "message": str(e)}