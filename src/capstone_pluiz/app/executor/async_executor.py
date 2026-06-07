# app/executor/async_executor.py
import threading
from queue import Queue, Empty
from app.router.command_router import CommandRouter
from app.memory.context_memory import ContextMemory


class AsyncExecutor:
    def __init__(self, router: CommandRouter, memory: ContextMemory):
        self.router = router
        self.memory = memory

        self._queue: Queue = Queue()
        self._cancel_flag = threading.Event()
        self._cancel_all_flag = threading.Event()

        self._worker_thread = threading.Thread(
            target=self._queue_worker,
            daemon=True
        )
        self._worker_thread.start()

        print("[AsyncExecutor] 초기화 완료 (큐 기반)")

    # ── 외부 인터페이스 ──────────────────────────────────────────

    def submit(self, user_input: str, command: dict, callback=None):
        """명령을 큐에 추가 (비동기)."""
        self._queue.put((user_input, command, callback))
        print(f"[AsyncExecutor] 큐에 추가: {command.get('action')} (큐 크기: {self._queue.qsize()})")

    def submit_sync(self, user_input: str, command: dict) -> dict:
        """
        명령을 동기적으로 즉시 실행하고 결과 반환.
        되묻기 등 즉각 응답이 필요한 케이스에 사용.
        큐를 거치지 않고 직접 실행.
        """
        try:
            print(f"[AsyncExecutor] 동기 실행: {command.get('action')}")
            result = self.router.route(command, user_input)
            print(f"[AsyncExecutor] 동기 실행 완료: {result.get('status')}")
            return result
        except Exception as e:
            print(f"[AsyncExecutor] 동기 실행 오류: {e}")
            return {"status": "error", "message": str(e)}

    def cancel(self):
        """현재 실행 중인 스텝만 취소."""
        self._cancel_flag.set()
        print("[AsyncExecutor] 현재 스텝 취소 신호 전송")

    def cancel_all(self):
        """현재 스텝 취소 + 큐 전체 비우기."""
        self._cancel_all_flag.set()
        self._cancel_flag.set()

        cleared = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                cleared += 1
            except Empty:
                break

        print(f"[AsyncExecutor] 전체 취소 — 큐 {cleared}개 제거")

    def queue_size(self) -> int:
        return self._queue.qsize()

    # ── 내부 워커 ────────────────────────────────────────────────

    def _queue_worker(self):
        while True:
            try:
                user_input, command, callback = self._queue.get(timeout=0.5)
            except Empty:
                continue

            if self._cancel_all_flag.is_set():
                self._cancel_all_flag.clear()
                self._cancel_flag.clear()
                print("[AsyncExecutor] cancel_all 감지 — 해당 명령 스킵")
                self._queue.task_done()
                continue

            # ── 버그 수정: cancel_all 후 플래그 초기화 ──────────
            # cancel_all_flag가 clear됐으면 cancel_flag도 초기화
            self._cancel_flag.clear()

            self._run_single(user_input, command, callback)
            self._queue.task_done()

    def _run_single(self, user_input: str, command: dict, callback):
        try:
            if self._cancel_flag.is_set():
                print(f"[AsyncExecutor] 실행 전 취소됨: {command.get('action')}")
                return

            print(f"[AsyncExecutor] 실행 시작: {command.get('action')}")
            result = self.router.route(command, user_input)

            if self._cancel_flag.is_set():
                print(f"[AsyncExecutor] 실행 후 취소됨 — 결과 무시: {command.get('action')}")
                return

            self.memory.save(user_input, command, result)
            print(f"[AsyncExecutor] 실행 완료: {result.get('status')}")

            if callback:
                callback(result)

        except Exception as e:
            print(f"[AsyncExecutor] 실행 오류 ({command.get('action')}): {e}")
            if callback and not self._cancel_flag.is_set():
                callback({"status": "error", "message": str(e)})