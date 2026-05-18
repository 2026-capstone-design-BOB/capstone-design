# app/executor/interpreter_exec.py
from interpreter import interpreter
from app.agents.supervisor_agent import SupervisorAgent
import subprocess

class InterpreterExecutor:
    def __init__(self):
        self.supervisor = SupervisorAgent()
        
        interpreter.offline = True
        interpreter.llm.model = "ollama/llama3"
        interpreter.llm.api_base = "http://localhost:11434"
        interpreter.llm.api_key = "ollama"
        interpreter.auto_run = True
        
        print("[Executor] 초기화 완료")
    
    def execute(self, command: dict, original_input: str = "") -> dict:
        try:
            # 복잡한 명령 + Gemini 사용 가능 → Gemini가 코드 직접 생성
            if self.supervisor.is_complex(command) and self.supervisor.available:
                print("[Executor] Gemini가 코드 생성 중...")
                code = self.supervisor.generate_code(command, original_input)
                
                if code:
                    print(f"[Gemini 생성 코드]\n{code}")
                    result = self._execute_code(code)
                    msg = self.supervisor.explain_result(original_input, result)
                    print(f"[결과] {msg}")
                    return {"status": "success", "message": msg}
            
            # 단순 명령 또는 Gemini 없음 → Open Interpreter + llama3
            print("[Executor] llama3로 처리 중...")
            prompt = self._make_safe_prompt(self._build_prompt(command))
            interpreter.chat(prompt)
            return {"status": "success"}
            
        except Exception as e:
            print(f"[Executor 오류] {e}")
            return {"status": "error", "message": str(e)}
    
    def _execute_code(self, code: str) -> bool:
        """Gemini가 생성한 코드 직접 실행"""
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
2. 웹 작업은 반드시 selenium + webdriver_manager 사용
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