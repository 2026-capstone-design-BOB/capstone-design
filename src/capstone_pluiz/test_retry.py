# test_retry.py — Phase 1-3 재시도 로직 테스트
# 실행: python test_retry.py
# TC-7, TC-8을 순서대로 자동 실행합니다.

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ── 패치 적용 ────────────────────────────────────────────────────
from app.executor import interpreter_exec as ie

_original_execute_code = ie.InterpreterExecutor._execute_code

# TC-7용 카운터
_tc7_counter = {"count": 0}

def _tc7_execute_code(self, code: str) -> dict:
    _tc7_counter["count"] += 1
    if _tc7_counter["count"] == 1:
        print(f"[TC7 패치] 첫 번째 실행 강제 실패")
        return {"status": "error", "message": "TC7 강제 실패 — 첫 번째 시도"}
    return _original_execute_code(self, code)

# TC-8용 항상 실패
def _tc8_execute_code(self, code: str) -> dict:
    print(f"[TC8 패치] 강제 실패")
    return {"status": "error", "message": "TC8 강제 실패"}


# ── TC-7 실행 ────────────────────────────────────────────────────
print("=" * 60)
print("TC-7: 1회 실패 후 재시도 성공 테스트")
print("기대: 1회 실패 → error_context 주입 → 재생성 → 성공 → 캐시 저장")
print("=" * 60)

_tc7_counter["count"] = 0
ie.InterpreterExecutor._execute_code = _tc7_execute_code

from app.router.command_router import CommandRouter
from app.memory.context_memory import ContextMemory
from app.executor.async_executor import AsyncExecutor

router = CommandRouter()
memory = ContextMemory()
async_executor = AsyncExecutor(router, memory)

history = memory.get_recent()
command = {
    "type": "interpreter",
    "action": "natural_language",
    "params": {"input": "볼륨 올려줘"},
    "_history": history,
}

print("\n[TC-7 실행 시작]")
result = async_executor.submit_sync("볼륨 올려줘", command)
print(f"\n[TC-7 결과] {result}")
print()

# ── TC-8 실행 ────────────────────────────────────────────────────
print("=" * 60)
print("TC-8: 3회 모두 실패 테스트")
print("기대: 3회 시도 후 루프 정상 종료 → 에러 반환 (무한루프 없음)")
print("=" * 60)

ie.InterpreterExecutor._execute_code = _tc8_execute_code

# 새 executor 인스턴스 (캐시 히트 방지)
router2 = CommandRouter()
memory2 = ContextMemory()
async_executor2 = AsyncExecutor(router2, memory2)

history2 = memory2.get_recent()
command2 = {
    "type": "interpreter",
    "action": "natural_language",
    "params": {"input": "메모장 열어줘"},
    "_history": history2,
}

print("\n[TC-8 실행 시작]")
result2 = async_executor2.submit_sync("메모장 열어줘", command2)
print(f"\n[TC-8 결과] {result2}")
print()

# ── 패치 복원 ────────────────────────────────────────────────────
ie.InterpreterExecutor._execute_code = _original_execute_code
print("패치 복원 완료")