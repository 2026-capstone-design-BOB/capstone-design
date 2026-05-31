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
from app.cache.command_cache import CommandCache
from app.executor.interpreter_exec import InterpreterExecutor

def start_ollama():
    # TODO: [Ollama 폴백] API 실패 시 Ollama로 자동 전환 로직 필요
    # 현재는 시작만 하고 실제 폴백 없음
    # 구현 위치: base_agent.py _call_llm()에 try/except로 폴백 추가
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

agent    = LocalAgent()
router   = CommandRouter()
cache    = CommandCache()
executor = InterpreterExecutor()

class UserRequest(BaseModel):
    text: str

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Pluiz 서버 정상 동작 중"}

@app.post("/api/execute")
async def execute_command(request: UserRequest):
    try:
        start = time.time()
        user_input = request.text
        print(f"[서버] 수신: {user_input}")

        # Step 1. 분류 먼저 (버그 수정: 기존엔 user_input으로 캐시 조회했음)
        command = agent.analyze_command(user_input)
        print(f"[서버] 분석: {command}")

        # Step 2. 캐시 조회 (command dict 기반)
        cached = cache.get(command)
        if cached:
            print(f"[캐시 히트] API 호출 없이 바로 실행")
            result = executor.run_from_cache(cached)
            print(f"[시간] 총 소요: {time.time()-start:.3f}초 ✅ (캐시)")
            return {"status": "success", "command": command, "result": result, "from_cache": True}

        # Step 3. 캐시 미스 → 라우터로
        result = router.route(command, user_input)
        print(f"[시간] 총 소요: {time.time()-start:.3f}초")
        return {"status": "success", "command": command, "result": result}

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/status")
def get_status():
    return {"status": "ready"}