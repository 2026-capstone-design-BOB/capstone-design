# app/executor/interpreter_exec.py
import time
from app.agents.supervisor_agent import SupervisorAgent
from app.cache.command_cache import CommandCache
from app.security.ast_guard import check_code


class InterpreterExecutor:
    def __init__(self):
        self.supervisor = SupervisorAgent()
        self.cache = CommandCache()
        print("[Executor] 초기화 완료")

    def run_from_cache(self, cached: dict) -> dict:
        """캐시 히트 시 API 호출 없이 바로 실행"""
        start = time.time()
        code = cached.get("code", "")
        result = self._execute_code(code)
        print(f"[시간] 캐시 코드 실행: {time.time()-start:.3f}초")
        msg = "완료됐습니다." if result else "실행 중 오류가 발생했습니다."
        return {"status": "success", "message": msg, "from_cache": True}

    def execute(self, command: dict, original_input: str = "") -> dict:
        start_total = time.time()
        try:
            # Step 1. 캐시 조회
            t = time.time()
            cached = self.cache.get(command)
            print(f"[시간] 캐시 조회: {time.time()-t:.3f}초")

            if cached:
                print(f"[Executor] 캐시 히트! 바로 실행: {self.cache._make_key(command)}")
                t = time.time()
                result = self._execute_code(cached["code"])
                print(f"[시간] 코드 실행: {time.time()-t:.3f}초")
                print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 ✅ (캐시)")

                # SEC-06: blocked 구분
                if result["status"] == "blocked":
                    return result
                msg = "완료됐습니다."
                return {"status": "success", "message": msg, "from_cache": True}

            # Step 2. 캐시 미스 → Gemini 코드 생성
            print("[Executor] 캐시 미스 → Gemini 코드 생성 중...")
            t = time.time()
            code = self.supervisor.generate_code(command, original_input)
            print(f"[시간] Gemini 코드 생성: {time.time()-t:.3f}초")

            if not code:
                return {
                    "status": "error",
                    "message": "AI 서버가 혼잡합니다. 잠시 후 다시 시도해주세요."
                }

            print(f"[Gemini 생성 코드]\n{code}")
            t = time.time()
            result = self._execute_code(code)
            print(f"[시간] 코드 실행: {time.time()-t:.3f}초")

            # SEC-06: blocked면 캐시 저장 안 하고 바로 반환
            if result["status"] == "blocked":
                print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 (차단)")
                return result

            if result["status"] == "success":
                t = time.time()
                self.cache.save(command, code, original_input)
                print(f"[시간] 캐시 저장: {time.time()-t:.3f}초")

            print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 (캐시 미스)")
            msg = self.supervisor.explain_result(original_input, result["status"] == "success")
            print(f"[결과] {msg}")
            return {"status": result["status"], "message": msg, "from_cache": False}

        except Exception as e:
            print(f"[Executor 오류] {e}")
            print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 (오류)")
            return {"status": "error", "message": str(e)}

    def _execute_code(self, code: str) -> dict:
        """SEC-04,06: AST 검사 후 실행, 결과를 dict로 반환"""
        # AST 보안 검사
        guard_result = check_code(code)
        if not guard_result["safe"]:
            return {
                "status": "blocked",
                "message": guard_result["message"]
            }
        try:
            exec(code, {"__builtins__": __builtins__})
            return {"status": "success"}
        except Exception as e:
            print(f"[코드 실행 오류] {e}")
            return {"status": "error", "message": str(e)}