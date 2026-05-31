# app/main.py
import sys
import os
import subprocess
import time
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.local_agent import LocalAgent
from app.router.command_router import CommandRouter
from app.services.stt import STTService
from app.cache.command_cache import CommandCache
from app.executor.interpreter_exec import InterpreterExecutor

from app.cache.preset_cache import init_preset_cache


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
    init_preset_cache() 
    agent = LocalAgent()
    router = CommandRouter()
    stt = STTService(mode="google")
    cache = CommandCache()
    executor = InterpreterExecutor()

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
        start = time.time()

        # Step 1. 분류 먼저
        print("분석 중...")
        command = agent.analyze_command(user_input)
        print(f"분석 결과: {command}")

        # Step 2. 캐시 조회 (command 기준)
        cached = cache.get(command)
        if cached:
            print(f"[캐시 히트] 코드 생성 없이 바로 실행")
            result = executor.run_from_cache(cached)
            print(f"[시간] 총 소요: {time.time()-start:.3f}초 ✅ (캐시)")
            print(f"실행 결과: {result}")
            print("-" * 40)
            continue

        # Step 3. 캐시 미스 → 실행
        result = router.route(command, user_input)
        print(f"[시간] 총 소요: {time.time()-start:.3f}초")
        print(f"실행 결과: {result}")
        print("-" * 40)

if __name__ == "__main__":
    main()