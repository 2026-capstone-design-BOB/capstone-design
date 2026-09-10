"""
P4-1 캐시 동적 학습 검증 (mock, OS·API 불필요)
실행: python test_cache_learn.py
"""
import sys, os, importlib.util, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# command_cache.py 직접 로드 (임시 캐시파일로 격리)
tmpdir = tempfile.mkdtemp()
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "command_cache.py"), encoding="utf-8").read()
ns = {"__file__": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "command_cache.py")}
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

    print("=== 5. BL-27 — 발화 쪽 학습 자격 + 부정·대조 게이트 ===")
    c._learning_enabled = True

    # L2 — 승인 응답이 명령으로 학습되던 것. 실제 캐시에 '그래' → close_app 이 박혀 있었다
    check("'그래' 학습 거부(L2)",
          not c.learn("그래", [{"name": "close_app", "args": {"app": "계산기"}}]))
    check("'그래요' 학습 거부(L1)",
          not c.learn("그래요", [{"name": "close_app", "args": {"app": "계산기"}}]))
    # L1 — STT 오인식이 패턴이 되던 것
    check("STT 오인식 학습 거부(L1)",
          not c.learn("오시가 된거야 다시", [{"name": "get_current_time", "args": {}}]))
    # L3 — 대조문
    check("대조문 학습 거부(L3)",
          not c.learn("계산기 말고 메모장 열어줘",
                      [{"name": "open_app", "args": {"app": "메모장"}}]))

    # ⚠️ 필터가 «너무 세지» 않은지 — 여기가 회귀를 잡는 자리다.
    # ADR 초안의 «어절 2개 이상»은 이 줄에서 깨진다(시드 '음소거해줘'가 1어절이다).
    # ⚠️ 시드 패턴은 learn()이 «이미 안다»고 False를 준다 → 시드가 아닌 표현으로 잰다
    check("1어절이어도 아는 낱말이면 학습됨('스크린샷')",
          c.learn("스크린샷", [{"name": "take_screenshot", "args": {}}]))
    check("entity 없이 action만 있어도 학습됨('최대화해줘')",
          c.learn("최대화해줘", [{"name": "maximize_window", "args": {}}]))

    # 거절 사유가 «어느 필터인지» 남는가 (로그로 원인을 못 찾으면 고칠 수 없다)
    check("거절 사유 L2", (c.is_learnable_utterance("그래") or "").startswith("L2"))
    check("거절 사유 L3", (c.is_learnable_utterance("메모장 말고 계산기") or "").startswith("L3"))
    check("거절 사유 L1", (c.is_learnable_utterance("오시가 된거야 다시") or "").startswith("L1"))
    check("통과는 None", c.is_learnable_utterance("메모장 열어줘") is None)

    print("=== 5-1. 대조 게이트는 find()에서 두 단계 모두 막는다 ===")
    check("대조문은 시드가 있어도 캐시를 안 탄다",
          c.find("계산기 말고 메모장 열어줘") is None)
    check("붙여 쓴 '메모장말고'도 잡는다", c.has_contrast_marker("메모장말고 계산기 열어줘"))
    check("정상 명령은 안 걸린다", not c.has_contrast_marker("메모장 열어줘"))
    check("정상 명령은 여전히 히트", c.find("메모장 열어줘") is not None)
    check("'대신'도 대조 표지", c.has_contrast_marker("크롬 대신 엣지 켜줘"))

    print("=== 5-2. 이미 박힌 것 선별 제거 (필터만으로는 안 사라진다) ===")
    # 필터를 우회해 «과거에 학습된» 상태를 그대로 만든다
    CacheEntry = ns["CacheEntry"]
    c._cache["그래"] = CacheEntry(
        pattern="그래", tool_calls=[{"name": "close_app", "args": {"app": "계산기"}}],
        response_template="OK", hit_count=1, is_seed=False, source="dynamic")
    c._build_intent_index()
    check("(전제) 박혀 있으면 '그래'가 캐시를 탄다", c.find("그래") is not None)

    dry = c.prune_unlearnable_dynamic(dry_run=True)
    check("dry_run은 목록만 준다", any(k == "그래" for k, _ in dry))
    check("dry_run은 지우지 않는다", c.find("그래") is not None)

    before_seed = c.stats()["seed"]
    victims = c.prune_unlearnable_dynamic()
    check("선별 제거됨", any(k == "그래" for k, _ in victims))
    check("제거 후 '그래'는 LLM으로 간다", c.find("그래") is None)
    check("시드는 안 건드린다", c.stats()["seed"] == before_seed)
    check("정상 동적은 남는다('스크린샷')", c.find("스크린샷") is not None)
    check("clear_dynamic과 다르다(전부 지우지 않음)", c.stats()["dynamic"] > 0)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
