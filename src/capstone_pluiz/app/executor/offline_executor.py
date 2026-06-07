# app/executor/offline_executor.py
# 오프라인 폴백 실행기 — Ollama(llama3) + Open Interpreter
# API 완전 불가 시에만 사용. 어디까지나 보조 수단.

import os
import time

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:latest")

# Open Interpreter에 전달할 경량 시스템 프롬프트
# BRAIN_PROMPT 전체 대신 핵심 규칙만 담아 소형 모델 부담 최소화
OFFLINE_SYSTEM_PROMPT = """You are an AI assistant that controls a Windows PC.
Generate and run Python code to fulfill the user's request.

Critical rules:
- Use subprocess.Popen for launching apps, never os.system
- Use selenium (Options() only, no webdriver_manager) for web tasks
- Never call driver.quit() after browser tasks
- Never use taskkill, wmic, shutdown, restart commands
- Never delete system files
- Wrap all code in try/except and print errors
- Use ctypes for window control (maximize=3, minimize=6)
- App paths: notepad=C:/Windows/System32/notepad.exe
- For Korean input: treat it as the equivalent English action

Respond in Korean when explaining results.
"""


class OfflineExecutor:
    """
    Ollama + Open Interpreter 기반 오프라인 실행기.
    InterpreterExecutor가 API 완전 불가 판정 시 호출.

    Open Interpreter 0.4.x API:
      interpreter.llm.model = "ollama/llama3"
      interpreter.chat(message) → 실행까지 자체 처리
    """

    def __init__(self):
        self._interpreter = None
        self._initialized = False
        print("[OfflineExecutor] 초기화 완료 (지연 로딩)")

    def _init_interpreter(self):
        """첫 실행 시에만 초기화 (무거운 import 지연)"""
        if self._initialized:
            return

        try:
            from interpreter import interpreter
            interpreter.llm.model = f"ollama/{OLLAMA_MODEL}"
            interpreter.llm.api_base = "http://localhost:11434"
            interpreter.auto_run = True          # 코드 실행 자동 승인
            interpreter.verbose = False
            interpreter.system_message = OFFLINE_SYSTEM_PROMPT

            # 불필요한 출력 억제
            interpreter.llm.context_window = 4096
            interpreter.llm.max_tokens = 1000

            self._interpreter = interpreter
            self._initialized = True
            print(f"[OfflineExecutor] Open Interpreter 초기화 완료 (모델: {OLLAMA_MODEL})")

        except Exception as e:
            print(f"[OfflineExecutor] Open Interpreter 초기화 실패: {e}")
            raise

    def run(self, user_input: str) -> dict:
        """
        user_input을 Open Interpreter에 직접 전달.
        코드 생성 + 실행을 Open Interpreter 자체 루프가 처리.

        Returns:
            {"status": "success"|"error", "message": str, "offline": True}
        """
        start = time.time()
        try:
            self._init_interpreter()
            print(f"[OfflineExecutor] 오프라인 실행: {user_input}")

            # Open Interpreter chat() 호출 — 내부적으로 코드 생성+실행 루프
            messages = self._interpreter.chat(user_input, display=False, stream=False)

            # 마지막 assistant 메시지 추출
            result_msg = ""
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and msg.get("type") == "message":
                    result_msg = msg.get("content", "")
                    break

            elapsed = time.time() - start
            print(f"[OfflineExecutor] 완료: {elapsed:.1f}초")
            return {
                "status": "success",
                "message": result_msg or "오프라인 모드로 실행했습니다.",
                "offline": True,
                "from_cache": False,
            }

        except Exception as e:
            print(f"[OfflineExecutor] 실행 실패: {e}")
            return {
                "status": "error",
                "message": f"오프라인 모드 실행 실패: {e}",
                "offline": True,
                "from_cache": False,
            }

    def reset(self):
        """대화 히스토리 초기화 (세션 간 컨텍스트 오염 방지)"""
        if self._interpreter:
            self._interpreter.messages = []