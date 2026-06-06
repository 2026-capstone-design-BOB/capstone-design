# app/router/command_router.py
from app.executor.interpreter_exec import InterpreterExecutor


class CommandRouter:
    def __init__(self):
        self.interpreter = InterpreterExecutor()
        self.routes = {
            "local":       self._handle_local,
            "web":         self._handle_web,
            "interpreter": self._handle_interpreter,
            "system":      self._handle_system,
            "unknown":     self._handle_unknown,
        }

    def route(self, command: dict | list, original_input: str = "") -> dict | list:
        """
        단일 명령(dict) 또는 복합 명령(list) 모두 처리.
        - list → 각 스텝을 순서대로 실행, 결과 리스트 반환
        - dict → 기존 단일 라우팅
        """
        if isinstance(command, list):
            return self._route_multistep(command, original_input)
        return self._route_single(command, original_input)

    # ── 멀티스텝 ─────────────────────────────────────────────────

    def _route_multistep(self, steps: list[dict], original_input: str) -> list[dict]:
        print(f"[라우터] 복합 명령 {len(steps)}개 스텝 처리")
        results = []
        for i, step in enumerate(steps):
            print(f"[라우터] 스텝 {i+1}/{len(steps)}: {step.get('action')}")
            result = self._route_single(step, original_input)
            results.append(result)
        return results

    # ── 단일 명령 ─────────────────────────────────────────────────

    def _route_single(self, command: dict, original_input: str) -> dict:
        cmd_type = command.get("type", "unknown")
        handler = self.routes.get(cmd_type, self._handle_unknown)
        return handler(command, original_input)

    def _handle_local(self, command: dict, original_input: str) -> dict:
        print(f"[라우터] 로컬 작업 → Executor")
        return self.interpreter.execute(command, original_input)

    def _handle_web(self, command: dict, original_input: str) -> dict:
        print(f"[라우터] 웹 작업 → Gemini + Executor")
        return self.interpreter.execute(command, original_input)

    def _handle_interpreter(self, command: dict, original_input: str) -> dict:
        print(f"[라우터] 파일/시스템 작업 → Executor")
        return self.interpreter.execute(command, original_input)

    def _handle_system(self, command: dict, original_input: str) -> dict:
        print(f"[라우터] 시스템 제어 → Executor")
        return self.interpreter.execute(command, original_input)

    def _handle_unknown(self, command: dict, original_input: str) -> dict:
        print(f"[라우터] 알 수 없는 명령")
        return {"status": "error", "message": "명령을 이해하지 못했습니다"}
