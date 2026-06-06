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
from app.memory.context_memory import ContextMemory
from app.executor.async_executor import AsyncExecutor
from app.executor.multistep_executor import MultistepExecutor
from app.cache.command_cache import CommandCache
from app.cache.multistep_cache import MultiStepCache


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
    memory = ContextMemory()
    cache = CommandCache()
    multistep_cache = MultiStepCache()
    async_executor = AsyncExecutor(router, memory)
    multistep_executor = MultistepExecutor(async_executor, cache, multistep_cache)

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

        # 취소 명령 먼저 체크
        CANCEL_KEYWORDS = {
            "취소", "취소해", "취소해줘", "취소해주세요",
            "중단", "중단해", "중단해줘", "중단해주세요",
            "스톱", "stop", "멈춰", "멈춰줘", "그만", "그만해", "그만해줘",
            "취소할게", "그냥 취소", "그냥 취소해줘", "됐어", "됐습니다",
        }
        if user_input.strip() in CANCEL_KEYWORDS or \
           any(k in user_input for k in ("취소", "중단", "멈춰", "그만해", "스톱")):
            async_executor.cancel_all()
            print("실행 중단됨")
            print("-" * 40)
            continue

        # Step 1. 맥락 해석 / LLM 분류
        print("분석 중...")
        resolved = memory.resolve(user_input)
        command = resolved if resolved else agent.analyze_command(user_input)
        if resolved:
            print(f"[맥락 해석] {resolved}")

        # Step 2. history_response — list일 리 없으므로 먼저 체크
        if isinstance(command, dict) and command.get("action") == "history_response":
            msg = command.get("params", {}).get("message", "이전 명령이 없습니다.")
            print(f"[히스토리] {msg}")
            memory.save(user_input, command, {"status": "success"})
            print("-" * 40)
            continue

        print(f"분석 결과: {command}")

        # Step 3. 멀티스텝 분기
        if isinstance(command, list):
            def on_step_complete(result):
                print(f"[스텝 완료] {result}")
            multistep_executor.execute(user_input, command, callback=on_step_complete)
            print(f"[시간] 멀티스텝 제출 완료: {time.time()-start:.3f}초")
            print("-" * 40)
            continue

        # Step 4. 단일 명령 — 비동기 실행 (캐시 조회는 InterpreterExecutor 내부에서 처리)
        def on_complete(result):
            print(f"[시간] 총 소요: {time.time()-start:.3f}초")
            print(f"실행 결과: {result}")
            print("-" * 40)

        async_executor.submit(user_input, command, callback=on_complete)

if __name__ == "__main__":
    main()