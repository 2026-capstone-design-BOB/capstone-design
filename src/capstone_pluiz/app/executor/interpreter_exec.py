# app/executor/interpreter_exec.py
from app.agents.supervisor_agent import SupervisorAgent

class InterpreterExecutor:
    def __init__(self):
        self.supervisor = SupervisorAgent()
        print("[Executor] 초기화 완료")

    def execute(self, command: dict, original_input: str = "") -> dict:
        try:
            # TODO: 추후 캐싱 시스템 구현 시 여기서 캐시 조회 먼저 수행
            # 캐시 히트 → 저장된 코드 바로 실행
            # 캐시 미스 → Gemini 코드 생성 → 실행 → 캐시 저장

            print("[Executor] Gemini 코드 생성 중...")
            code = self.supervisor.generate_code(command, original_input)

            if not code:
                return {
                    "status": "error",
                    "message": "AI 서버가 혼잡합니다. 잠시 후 다시 시도해주세요."
                }

            print(f"[Gemini 생성 코드]\n{code}")
            result = self._execute_code(code)
            msg = self.supervisor.explain_result(original_input, result)
            print(f"[결과] {msg}")
            return {"status": "success", "message": msg}

        except Exception as e:
            print(f"[Executor 오류] {e}")
            return {"status": "error", "message": str(e)}

    def _execute_code(self, code: str) -> bool:
        try:
            exec(code, {"__builtins__": __builtins__})
            return True
        except Exception as e:
            print(f"[코드 실행 오류] {e}")
            return False