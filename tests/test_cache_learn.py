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

    # ── 🚨 캐시 사전 ↔ 실행 사전이 어긋나지 않는가 (2026-09-11 2차 실기) ──
    #
    # **사용자 지적**: *"대충 키워드 메모장/그림판 이런 것들이랑 열어줘/띄워봐/보여줘
    # 같은 것들은 패턴 매칭이라도 해야되는 거 아닌가. 너무 멍청해서 오프라인 이점이
    # 너무 부족함."*
    #
    # 맞는 지적이었다. 구조는 이미 있었고(`_build_intent_index`가 앱마다 open/close를
    # 자동 합성한다) **사전이 얇았다.** 실기에서 «그림판 열어줘»가 네 번 실패한 이유가
    # 그것이다 — 모델이 멍청한 게 아니라 표에 그림판이 없었다.
    #
    # 🚨 **그래서 이 검사가 필요하다.** 캐시에만 앱을 넣으면 **캐시는 히트하는데
    #   실행이 실패한다** — 사용자에게는 «된다고 해놓고 안 되는» 것으로 보이고,
    #   그게 이 저장소가 가장 싫어하는 결함 유형이다(BL-12·19·26·35).
    #   오프라인이 차별점이라면 **이 표의 길이가 차별점의 크기**이므로 앞으로도
    #   계속 늘어날 것이다. 늘릴 때마다 짝을 맞췄는지 여기서 걸린다.
    print("=== 캐시가 아는 앱은 실행 사전도 알아야 한다 ===")
    import core.command_cache as CC
    from tools.app_control import APP_ALIASES, APP_PROCESS_MAP, APP_DISPLAY_NAMES

    # 🔑 **검사할 불변식을 정확히 고른다.** 표면형(«노트패드»)은 캐시가 *알아듣는* 말이고
    #   실행과 무관하다 — 합성 엔트리는 `open_app(app=표시명)`을 부르므로
    #   **«표시명»이 실행 사전에서 같은 키로 풀리는지**만 맞으면 된다.
    #   (이 구분을 틀리면 멀쩡한 동의어가 실패로 잡힌다 — 처음에 그랬다)
    missing_alias, missing_proc, missing_disp = [], [], []
    for _surface, key, display in CC.APP_ENTITIES:
        norm = display.lower().replace(" ", "")
        if APP_ALIASES.get(norm) != key and norm != key:
            missing_alias.append((display, key, APP_ALIASES.get(norm)))
        if key not in APP_PROCESS_MAP:
            missing_proc.append(key)
        if key not in APP_DISPLAY_NAMES:
            missing_disp.append(key)

    check(f"합성에 쓰이는 표시명이 실행 사전에서 같은 키로 풀린다 (어긋난 것: {missing_alias})",
          not missing_alias)
    check(f"앱 키가 전부 APP_PROCESS_MAP에 있다 (빠진 것: {sorted(set(missing_proc))})",
          not missing_proc)
    check(f"앱 키가 전부 APP_DISPLAY_NAMES에 있다 (빠진 것: {sorted(set(missing_disp))})",
          not missing_disp)

    # 실기에서 죽었던 말투가 이제 캐시를 타는가 — 사전 확장의 본체다.
    fresh = CC.CommandCache()
    LIVE = {
        "그림판 열어줘":     "open_app",
        "그림판 열어달라고":  "open_app",
        "그림판 띄워봐":     "open_app",
        "그림판 보여줘":     "open_app",
        "작업관리자 열어줘":  "open_app",
        "제어판 켜줘":       "open_app",
        "돋보기 실행시켜":    "open_app",
        "그림판 꺼줘":       "close_app",
        "메모장을 띄어 보도록 하여라": "open_app",
    }
    for text, want in LIVE.items():
        f = fresh.find(text)
        check(f"{text!r} → {want} (LLM 없이)",
              f is not None and f[0].tool_calls[0]["name"] == want)

    # ── 🚨 S2 퍼지 임계 — 실측으로 0.80 → 0.83 (2026-09-11 2차 실기) ──
    #
    # 사용자가 *"메모장 만들어줘"* 라고 했는데 **«메모장 창을 앞으로 가져왔습니다»**.
    # difflib가 `'메모장 열어줘'`와 **정확히 0.800**이라 임계에 딱 걸려 통과했다.
    # 「만들어」와 「열어」는 다른 뜻이다.
    #
    # 경계가 비어 있어 올릴 수 있었다(실측 17문장):
    #   되어야 하는 것 중 S2 의존 최저 : 0.857  ('볼륨 좀 올려줘')
    #   되면 안 되는 것 중 최고       : 0.800  ('메모장 만들어줘')
    # **이 두 숫자를 여기에 못 박는다** — 한쪽이 움직이면 임계를 다시 정해야 한다.
    print("=== S2 퍼지 임계는 «되는 것»과 «안 되는 것» 사이에 있다 ===")
    import difflib as _dl

    def _best_s2(text):
        n = c._normalize(text)
        return max((_dl.SequenceMatcher(None, n, k).ratio() for k in fresh._cache),
                   default=0.0)

    check(f"임계가 0.83이다 (현재 {CC.SIMILARITY_THRESHOLD})",
          CC.SIMILARITY_THRESHOLD == 0.83)
    check("🚩 원문 재현: '메모장 만들어줘'가 임계 아래다",
          _best_s2("메모장 만들어줘") < CC.SIMILARITY_THRESHOLD)
    check("'메모장 만들어줘' → 캐시가 집지 않는다 (LLM/제안으로 간다)",
          fresh.find("메모장 만들어줘") is None)
    for t in ("볼륨 좀 올려줘", "밝기 좀 올려줘"):
        check(f"회귀: {t!r}는 여전히 임계 위다 ({_best_s2(t):.3f})",
              _best_s2(t) >= CC.SIMILARITY_THRESHOLD)
        check(f"회귀: {t!r}는 캐시를 탄다", fresh.find(t) is not None)

    # 🚨 회귀 — 「보여」를 open에 넣었으므로 이 둘을 빼앗지 않았는지 본다.
    #   ACTION_PATTERNS는 위에서부터 먼저 맞는 것을 쓰므로 show_desktop·recent_file이
    #   open보다 앞에 있어야 한다. 순서가 바뀌면 여기서 깨진다.
    for text, want in (("바탕화면 보여줘", "show_desktop"),
                       ("최근에 열었던 파일 보여줘", "open_recent_file")):
        f = fresh.find(text)
        check(f"회귀: {text!r} → {want} (open이 빼앗지 않는다)",
              f is not None and f[0].tool_calls[0]["name"] == want)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
