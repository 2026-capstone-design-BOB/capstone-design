# app/server.py
import sys
import os
import subprocess
import time
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agents.local_agent import LocalAgent
from app.router.command_router import CommandRouter

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

class UserRequest(BaseModel):
    text: str

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Pluiz 서버 정상 동작 중"}

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

@app.get("/api/status")
def get_status():
    return {"status": "ready"}