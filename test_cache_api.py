"""
P4-3 캐시 관리 로직 검증 (API가 호출하는 캐시 메서드, mock 캐시파일)
실행: python test_cache_api.py
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
ns = {"__file__": os.path.join(os.path.dirname(__file__), "core", "command_cache.py")}
exec(open(os.path.join(os.path.dirname(__file__), "core", "command_cache.py"), encoding="utf-8").read(), ns)
ns["CACHE_FILE"] = os.path.join(tmp, "c.json")
CommandCache = ns["CommandCache"]


def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    c = CommandCache()
    # 학습 2개
    c.learn("메모장 띄워봐", [{"name": "open_app", "args": {"app": "메모장"}}])
    c.learn("화면 좀 찍어봐", [{"name": "take_screenshot", "args": {}}])

    print("=== GET /cache (stats + list) ===")
    st = c.stats()
    check("stats: dynamic 2", st["dynamic"] == 2)
    check("stats: seed 존재", st["seed"] > 0)
    check("stats: max_dynamic/learning 필드", "max_dynamic" in st and "learning_enabled" in st)
    lst = c.list_dynamic()
    check("list_dynamic 2개 + 필드", len(lst) == 2 and "pattern" in lst[0] and "learned_at" in lst[0])

    print("=== DELETE /cache/entry (개별, 시드보호) ===")
    check("동적 개별 삭제", c.delete_entry("메모장 띄워봐"))
    check("삭제 후 1개", c.stats()["dynamic"] == 1)
    check("시드 삭제 거부", not c.delete_entry("메모장 열어줘"))
    check("없는 항목 삭제 → False", not c.delete_entry("존재안함123"))

    print("=== DELETE /cache (동적 전체 초기화) ===")
    n = c.clear_dynamic()
    check("초기화 개수 반환", n == 1)
    check("동적 0개", c.stats()["dynamic"] == 0)
    check("시드 유지", c.stats()["seed"] > 0)
    check("시드 명령 여전히 히트", c.find("메모장 열어줘") is not None)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
