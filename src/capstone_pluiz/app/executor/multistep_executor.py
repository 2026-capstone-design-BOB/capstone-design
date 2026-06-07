# app/executor/multistep_executor.py
import threading
from app.executor.async_executor import AsyncExecutor
from app.cache.command_cache import CommandCache
from app.cache.multistep_cache import MultiStepCache


class MultistepExecutor:
    """
    복합 명령(멀티스텝)을 처리하는 실행기.

    실행 순서:
    1. MultiStepCache에서 복합 명령 전체 키로 조회
       → 히트: 각 스텝의 code를 AsyncExecutor 큐에 즉시 제출
       → 미스: 개별 스텝별 CommandCache 조회 후 실행,
               모든 스텝 성공 확인 후 MultiStepCache에 저장

    지원 범위:
    - 독립적인 PC 제어 명령들의 순차 실행
      예) "크롬 열고 유튜브 검색해줘"
          "메모장이랑 계산기 둘 다 열어줘"
          "볼륨 올리고 화면 캡처해줘"

    미지원 (TODO):
    - 스텝 간 데이터 전달이 필요한 명령
      예) "파일 찾아서 열어줘" (find → open 결과 전달)
      → 나중에 StepContext 구조로 확장 가능하도록 설계
    """

    def __init__(
        self,
        executor: AsyncExecutor,
        command_cache: CommandCache,
        multistep_cache: MultiStepCache,
    ):
        self.executor = executor
        self.command_cache = command_cache
        self.multistep_cache = multistep_cache

        print("[MultistepExecutor] 초기화 완료")

    def execute(self, user_input: str, steps: list[dict], callback=None):
        """
        복합 명령 실행 진입점.

        Args:
            user_input: 원본 사용자 입력 (캐시 저장용)
            steps: LLM이 반환한 명령 리스트
            callback: 각 스텝 완료 시 호출 (result: dict) -> None
        """
        if not steps:
            print("[MultistepExecutor] 스텝 없음 — 실행 스킵")
            return

        print(f"[MultistepExecutor] {len(steps)}개 스텝 처리 시작")

        # 1. MultiStepCache 조회
        cached = self.multistep_cache.get(steps)
        if cached:
            print(f"[MultistepExecutor] 멀티스텝 캐시 히트 — {len(cached)}개 스텝 즉시 제출")
            self._submit_all(user_input, cached, callback)
            return

        # 2. 캐시 미스 — 개별 스텝 처리 + 완료 추적
        print("[MultistepExecutor] 멀티스텝 캐시 미스 — 개별 스텝 처리")
        self._execute_steps_with_tracking(user_input, steps, callback)

    def _execute_steps_with_tracking(
        self, user_input: str, steps: list[dict], callback
    ):
        """
        개별 스텝을 순서대로 AsyncExecutor 큐에 제출.
        모든 스텝 실행 완료 후 성공한 것만 MultiStepCache에 저장.
        실패 스텝이 있어도 나머지 스텝은 계속 실행.
        """
        total = len(steps)
        results = [None] * total        # 인덱스 순서 보장
        lock = threading.Lock()
        counter = {"done": 0}

        enriched_steps = []

        for i, step in enumerate(steps):
            cached_cmd = self.command_cache.get(step)
            if cached_cmd:
                print(f"[MultistepExecutor] 스텝 {i+1} 캐시 히트: {step.get('action')}")
                step_with_code = {**step, "code": cached_cmd["code"]}
            else:
                print(f"[MultistepExecutor] 스텝 {i+1} 캐시 미스: {step.get('action')}")
                step_with_code = step

            enriched_steps.append(step_with_code)

            # 스텝별 input 생성 — natural_language는 params.input이 사용자 자연어
            action = step.get("action", "")
            params = step.get("params", {})
            if action == "natural_language" and "input" in params:
                step_input = params["input"]
            else:
                param_str = " ".join(str(v) for v in params.values() if v)
                step_input = f"{action} {param_str}".strip() if param_str else action

            # 클로저에서 i 캡처
            def make_cb(idx, s):
                def on_done(result):
                    with lock:
                        results[idx] = result
                        counter["done"] += 1
                        status = result.get("status", "error")
                        print(f"[MultistepExecutor] 스텝 {idx+1}/{total} 완료: {status}")

                        # 모든 스텝 완료 시 캐시 저장 판단
                        if counter["done"] == total:
                            success_all = all(
                                r.get("status") == "success" for r in results if r
                            )
                            if success_all:
                                self.multistep_cache.save(
                                    enriched_steps, original_input=user_input
                                )
                            else:
                                failed = [
                                    i+1 for i, r in enumerate(results)
                                    if r and r.get("status") != "success"
                                ]
                                print(f"[MultistepExecutor] 실패 스텝 {failed} — 캐시 저장 스킵")

                    if callback:
                        callback(result)
                return on_done

            self.executor.submit(
                user_input=step_input,
                command=step_with_code,
                callback=make_cb(i, step_with_code),
            )

    def _submit_all(self, user_input: str, cached_steps: list[dict], callback):
        """캐시된 스텝들을 모두 큐에 제출."""
        for i, step in enumerate(cached_steps):
            print(f"[MultistepExecutor] 스텝 {i+1} 제출: {step.get('action')}")
            action = step.get("action", "")
            params = step.get("params", {})
            if action == "natural_language" and "input" in params:
                step_input = params["input"]
            else:
                param_str = " ".join(str(v) for v in params.values() if v)
                step_input = f"{action} {param_str}".strip() if param_str else action
            self.executor.submit(
                user_input=step_input,
                command=step,
                callback=callback,
            )

    def cancel_all(self):
        """진행 중인 멀티스텝 전체 취소."""
        self.executor.cancel_all()
        print("[MultistepExecutor] 전체 취소 완료")