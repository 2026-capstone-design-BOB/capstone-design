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
        code = cached.get("code", "")
        start = time.time()
        result = self._execute_code(code)
        print(f"[시간] 캐시 코드 실행: {time.time()-start:.3f}초")
        msg = "완료됐습니다." if result["status"] == "success" else "실행 중 오류가 발생했습니다."
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
                if result["status"] == "blocked":
                    return result
                msg = "완료됐습니다."
                return {"status": "success", "message": msg, "from_cache": True}

            # Step 2. 캐시 미스 → 코드 생성 (최대 3회 시도)
            code = None
            result = None
            for attempt in range(3):
                print(f"[Executor] {'캐시 미스 → ' if attempt == 0 else f'재시도 {attempt} → '}Gemini 코드 생성 중...")
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

                # 문법 오류면 재시도
                if result["status"] == "syntax_error":
                    print(f"[재시도 {attempt+1}] 코드 문법 오류 감지, 재생성 중...")
                    continue

                # 보안 차단이나 성공/오류면 루프 종료
                break

            # 3회 다 문법 오류면
            if result["status"] == "syntax_error":
                print(f"[Executor] 3회 재시도 후에도 문법 오류 지속")
                return {
                    "status": "error",
                    "message": "코드 생성에 실패했습니다. 다시 시도해주세요."
                }

            # 보안 차단이면 캐시 저장 안 함
            if result["status"] == "blocked":
                print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 (차단)")
                return result

            # 성공이면 캐시 저장
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
            return {"status": "error", "message": str(e)}

    def _execute_code(self, code: str) -> dict:
        # AST 보안 검사
        guard_result = check_code(code)

        # 문법 오류는 재시도 가능하도록 별도 상태로 반환
        if not guard_result["safe"]:
            if "문법 오류" in guard_result["message"] or "파싱 오류" in guard_result["message"]:
                return {
                    "status": "syntax_error",
                    "message": guard_result["message"]
                }
            # 보안 차단
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