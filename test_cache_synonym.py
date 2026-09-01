"""
P4-4 경량 의미 매칭(동의어 확장) 검증
실행: python test_cache_synonym.py
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ns = {"__file__": os.path.join(os.path.dirname(__file__), "core", "command_cache.py")}
exec(open(os.path.join(os.path.dirname(__file__), "core", "command_cache.py"), encoding="utf-8").read(), ns)
ns["CACHE_FILE"] = os.path.join(tempfile.mkdtemp(), "c.json")
CommandCache = ns["CommandCache"]


def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    c = CommandCache()
    def hits(text, tool):
        h = c.find(text)
        return h is not None and h[0].tool_calls[0]["name"] == tool

    print("=== 새 동의어 → 인텐트 히트 (원래 LLM 갔던 것) ===")
    check("'메모장 띄워봐' → open_app", hits("메모장 띄워봐", "open_app"))
    check("'노트패드 열어' → open_app", hits("노트패드 열어", "open_app"))
    check("'카톡 오픈' → open_app", hits("카톡 오픈", "open_app"))
    check("'소리 키워봐' → volume_up", hits("소리 키워봐", "volume_up"))
    check("'볼륨 줄여줘' → volume_down", hits("볼륨 줄여줘", "volume_down"))
    check("'화면 찍어봐' → take_screenshot", hits("화면 찍어봐", "take_screenshot"))

    print("=== 기존 시드 회귀 (안 깨졌나) ===")
    for t, tool in [("메모장 열어줘", "open_app"), ("계산기 꺼줘", "close_app"),
                    ("볼륨 올려줘", "volume_up"), ("볼륨 내려줘", "volume_down"),
                    ("스크린샷 찍어줘", "take_screenshot"), ("실행 중인 앱 알려줘", "get_running_apps")]:
        check(f"'{t}' → {tool}", hits(t, tool))

    print("=== 오작동 방지 (엉뚱하게 안 잡히나) ===")
    check("'실행 중인 앱 알려줘'는 open 아님", c.find("실행 중인 앱 알려줘")[0].tool_calls[0]["name"] == "get_running_apps")
    check("'안녕 반가워' → 미스", c.find("안녕 반가워") is None)

    print("=== Stage-2 교체점(_similarity) 존재 ===")
    check("_similarity 메서드 있음", hasattr(c, "_similarity") and abs(c._similarity("메모장", "메모장") - 1.0) < 1e-6)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
