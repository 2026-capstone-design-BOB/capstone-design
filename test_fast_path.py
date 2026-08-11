"""
P1.5-a fast_path 어댑터 단위 테스트 (동기, mock, OS·API 불필요)
실행: python test_fast_path.py
"""
import sys, os, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

spec = importlib.util.spec_from_file_location(
    "fast_path", os.path.join(os.path.dirname(__file__), "core", "fast_path.py"))
fp = importlib.util.module_from_spec(spec); spec.loader.exec_module(fp)


class MockEntry:
    def __init__(self, pattern, result):
        self.pattern = pattern; self._result = result

class MockCache:
    """'메모장 열어줘'류만 히트로 처리하는 캐시 mock (동기 execute_sync)."""
    def __init__(self): self.executed = []; self.hits = []
    def find(self, text):
        if "메모장" in text and ("열" in text or "켜" in text):
            return (MockEntry("메모장 열어줘", "메모장을 실행했어요."), 0.9)
        return None
    def execute_sync(self, entry): self.executed.append(entry.pattern); return entry._result
    def increment_hit(self, pattern): self.hits.append(pattern)

def mock_router(text):
    if text.startswith("유튜브"):
        return "유튜브를 재생했어요."
    return None


def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    cache = MockCache()
    print("=== fast_path 어댑터 (동기) ===")
    r = fp.resolve_fast_path("메모장 열어줘", cache, mock_router)
    check("캐시 히트 → 결과 반환", r == "메모장을 실행했어요.")
    check("캐시 execute_sync 호출됨", cache.executed == ["메모장 열어줘"])
    check("increment_hit 호출됨", cache.hits == ["메모장 열어줘"])

    r = fp.resolve_fast_path("유튜브 아이유 틀어줘", cache, mock_router)
    check("라우터 히트 → 결과 반환", r == "유튜브를 재생했어요.")

    check("복합('이랑') → None", fp.resolve_fast_path("메모장이랑 계산기 열어줘", cache, mock_router) is None)
    check("문맥참조('방금') → None", fp.resolve_fast_path("방금 연 거 닫아줘", cache, mock_router) is None)
    check("다중 앱(3개) → None", fp.resolve_fast_path("메모장 계산기 탐색기 열어줘", cache, mock_router) is None)
    check("미스 → None", fp.resolve_fast_path("오늘 기분 어때", cache, mock_router) is None)
    check("빈 입력 → None", fp.resolve_fast_path("   ", cache, mock_router) is None)
    check("is_compound_command('빼고')", fp.is_compound_command("계산기 빼고 다 닫아줘"))
    check("is_compound_command('메모장 열어줘')==False", not fp.is_compound_command("메모장 열어줘"))

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
