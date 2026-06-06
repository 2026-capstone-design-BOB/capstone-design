# app/main.py
import os
from dotenv import load_dotenv
load_dotenv()

import sys
import subprocess
import time
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.local_agent import LocalAgent
from app.router.command_router import CommandRouter
from app.services.stt import STTService

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

def main():
    start_ollama()
    
    agent = LocalAgent()
    router = CommandRouter()
    stt = STTService(mode="google")
    
    print("Pluiz V2 시작")
    print("1: 음성 입력 | 2: 텍스트 입력 | quit: 종료")
    print("-" * 40)
    
    while True:
        mode = input("입력 방식 선택 (1/2/quit): ").strip()
        
        if mode == "quit":
            break
        elif mode == "1":
            user_input = stt.listen_and_transcribe()
            if not user_input:
                continue
        elif mode == "2":
            user_input = input("명령어: ").strip()
            if not user_input:
                continue
        else:
            continue
        
        print(f"입력: {user_input}")
        print("분석 중...")
        
        command = agent.analyze_command(user_input)
        print(f"분석 결과: {command}")
        
        result = router.route(command, user_input)
        print(f"실행 결과: {result}")
        print("-" * 40)

if __name__ == "__main__":
    main()