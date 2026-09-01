"""
P4-1 캐시 동적 학습 검증 (mock, OS·API 불필요)
실행: python test_cache_learn.py
"""
import sys, os, importlib.util, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# command_cache.py 직접 로드 (임시 캐시파일로 격리)
tmpdir = tempfile.mkdtemp()
src = open(os.path.join(os.path.dirname(__file__), "core", "command_cache.py"), encoding="utf-8").read()
ns = {"__file__": os.path.join(os.path.dirname(__file__), "core", "command_cache.py")}
exec(src, ns)
CommandCache = ns["CommandCache"]
# 캐시 파일을 임시 경로로 (실제 seed json 오염 방지)
ns["CACHE_FILE"] = os.path.join(tmpdir, "test_cache.json")


def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    c = CommandCache()
    c._max_dynamic = 3   # 상한 테스트용 작게

    print("=== 1. 학습 자격(오염 차단) ===")
    # 파라미터 없는 화이트리스트 → 학습 O
    ok = c.learn("메모장 띄워봐", [{"name": "open_app", "args": {"app": "메모장"}}])
    check("파라미터없는 앱열기 → 학습됨", ok)
    check("학습 후 find로 히트", c.find("메모장 띄워봐") is not None)
    # 자유 파라미터(폴더명) → 학습 거부
    no = c.learn("바탕화면에 새폴더 만들어줘",
                 [{"name": "create_folder", "args": {"name": "새폴더", "location": "desktop"}}])
    check("폴더생성(파라미터) → 학습 거부", not no)
    # set_volume 숫자 → 거부
    no = c.learn("볼륨 30으로", [{"name": "set_volume", "args": {"level": 30}}])
    check("set_volume 숫자 → 학습 거부", not no)
    # 볼륨 기본량 → 허용
    ok = c.learn("소리 크게 해줘", [{"name": "volume_up", "args": {"amount": 10}}])
    check("볼륨 기본량 → 학습됨", ok)
    # 복수 도구 → 거부
    no = c.learn("메모장 계산기 열어",
                 [{"name": "open_app", "args": {"app": "메모장"}},
                  {"name": "open_app", "args": {"app": "계산기"}}])
    check("복수 도구 → 학습 거부", not no)

    print("=== 2. source 분리 + 관리 ===")
    st = c.stats()
    check("동적 2개 학습됨", st["dynamic"] == 2)
    check("시드는 dynamic과 분리", st["seed"] > 0)
    check("개별 삭제(동적)", c.delete_entry("메모장 띄워봐"))
    check("시드 삭제는 거부", not c.delete_entry("메모장 열어줘"))
    n = c.clear_dynamic()
    check("동적 전체 초기화", n >= 1 and c.stats()["dynamic"] == 0)
    check("초기화 후에도 시드 유지", c.stats()["seed"] > 0)
    check("시드 명령은 여전히 히트", c.find("메모장 열어줘") is not None)

    print("=== 3. 상한 LRU 정리 ===")
    for i in range(5):
        c.learn(f"테스트명령 {i} 실행해봐", [{"name": "take_screenshot", "args": {}}])
    # 상한 3 → 3개만 남아야 (모두 같은 도구지만 pattern 다름)
    check("상한 초과분 정리됨(≤3)", c.stats()["dynamic"] <= 3)

    print("=== 4. 학습 스위치 ===")
    c._learning_enabled = False
    off = c.learn("스크린샷 찍어봐", [{"name": "take_screenshot", "args": {}}])
    check("학습 off면 학습 안 함", not off)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
