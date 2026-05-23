# app/executor/interpreter_exec.py
from interpreter import interpreter
from app.agents.supervisor_agent import SupervisorAgent
from config.settings import GEMINI_API_KEY

class InterpreterExecutor:
    def __init__(self):
        self.supervisor = SupervisorAgent()
        
        if not GEMINI_API_KEY:
            print("[Executor] [경고] GEMINI_API_KEY가 없습니다!")
        
        interpreter.offline = False
        interpreter.llm.model = "gemini/gemini-2.5-flash-lite"
        interpreter.llm.api_key = GEMINI_API_KEY
        interpreter.auto_run = True
        print("[Executor] 초기화 완료")
    
    def execute(self, command: dict, original_input: str = "") -> dict:
        try:
            if self.supervisor.is_complex(command) and self.supervisor.available:
                print("[Executor] Gemini가 복잡한 작업으로 판단 → 직접 코드 생성 중...")
                code = self.supervisor.generate_code(command, original_input)
                if code:
                    print(f"[Gemini 생성 코드]\n{code}")
                    result = self._execute_code(code)
                    msg = self.supervisor.explain_result(original_input, result)
                    print(f"[결과] {msg}")
                    return {"status": "success", "message": msg}
            
            print("[Executor] Open Interpreter + Gemini API로 처리 중...")
            prompt = self._make_safe_prompt(self._build_prompt(command))
            interpreter.chat(prompt)
            return {"status": "success"}
            
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
    
    def _make_safe_prompt(self, prompt: str) -> str:
        return f"""
다음 작업을 수행해줘. 반드시 아래 규칙을 따라야 해:
1. 파일 삭제, 시스템 파일 수정 절대 금지
2. 웹 작업은 반드시 selenium 사용
3. 절대 새로운 라이브러리 설치 시도 금지
4. 작업 완료 후 결과만 간단히 출력

작업: {prompt}
"""
    
    def _build_prompt(self, command: dict) -> str:
        action = command.get("action", "")
        params = command.get("params", {})
        prompts = {
            "create_file": f"{params.get('location', '바탕화면')}에 {params.get('name', 'new_file.txt')} 파일 만들어줘",
            "create_folder": f"{params.get('location', '바탕화면')}에 {params.get('name', 'new_folder')} 폴더 만들어줘",
            "find_file": f"{params.get('location', '내 PC')}에서 {params.get('extension', '')} 파일 찾아줘",
            "open_app": f"{params.get('app', '')} 열어줘",
            "close_app": f"{params.get('app', '')} 닫아줘",
        }
        return prompts.get(action, str(command))