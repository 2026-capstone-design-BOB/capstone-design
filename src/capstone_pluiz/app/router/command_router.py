# app/router/command_router.py
from app.executor.interpreter_exec import InterpreterExecutor

class CommandRouter:
    def __init__(self):
        self.interpreter = InterpreterExecutor()
        self.routes = {
            "local": self._handle_local,
            "web": self._handle_web,
            "interpreter": self._handle_interpreter,
            "system": self._handle_system,  # 추가
            "unknown": self._handle_unknown
        }

    def route(self, command: dict, original_input: str = "") -> dict:
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