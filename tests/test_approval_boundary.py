"""승인의 경계 — 계약 여섯 (mock)

    python tests/test_approval_boundary.py

설계: docs/design/G-05-19_승인의_경계.md §7-3
감사: G-05(말없이 덮어쓴다) · G-06(save_excel 도 같다) · G-19(강제 종료가 저장 안 한 내용을 지운다)

## 🔑 왜 «반대 방향»을 같이 잡나

§7-3이 계약마다 반대 방향을 적어 뒀다. 그게 없으면 이런 수정이 **통과한다**:

  · "항상 ⚠️ 라고 말한다"        → 계약 4의 앞면만 만족
  · "무조건 휴지통으로 보낸다"    → 계약 1의 앞면만 만족 (빈 파일에도 휴지통이 생긴다)
  · "전부 승인을 받는다"          → 계약 5의 앞면만 만족 (승인 피로 = ADR §3-1이 막은 것)

`_await_gone()` 테스트 20건이 양방향인 것과 같은 이유다.

## ⚠️ 이 스위트가 보증하지 **못하는** 것

**저장 대화상자가 실제로 뜨는지는 사람만 볼 수 있다.** 여기서는 «`WM_CLOSE` 를 보내고
창이 남아 있으면 ✓ 를 안 쓴다»까지만 잡는다.

🚨 그리고 ADR §7-2 — **메모장으로 재면 틀린 답이 나온다.** Windows 11 메모장은 탭
세션을 자동 저장해서, 강제 종료해도 내용이 살아 있을 수 있다. 그걸 «결함이 없다»로
읽으면 안 된다. 실기는 **그림판**처럼 자동 저장이 없는 앱으로 한다.
"""
import _testenv  # noqa: F401
import sys, os, importlib.util, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _src(relpath):
    """소스를 글자로 읽는다. 🚨 `encoding='utf-8'` — 한글 소스를 cp949로 읽으면 터진다."""
    with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def run():
    passed = total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    G = _load("pluiz_graph_ab", os.path.join("core", "graph.py"))
    FS = _load("pluiz_fs_ab", os.path.join("tools", "filesystem.py"))

    tmp = tempfile.mkdtemp(prefix="pluiz_ab_")
    try:
        # ═══ 계약 1 — 내용이 있는 파일을 덮어쓰면 옛 것이 휴지통에 있다 ═══
        #   반대: 빈 파일 · 없는 파일엔 휴지통이 안 생긴다
        print("=== 계약 1 · 덮어쓰기는 옛 것을 치우고, 안 그런 경우엔 안 치운다 ===")
        trashed = []
        real_to_trash = FS._to_trash
        FS._to_trash = lambda p: (trashed.append(p), os.remove(p), "trash")[2]

        new_path = os.path.join(tmp, "새파일.txt")
        how = FS._write_preserving(new_path, lambda t: open(t, "w", encoding="utf-8").write("가"))
        check("없던 파일 → 'created'", how == "created")
        check("없던 파일엔 휴지통이 **안** 생긴다", trashed == [])
        check("내용이 실제로 쓰였다", open(new_path, encoding="utf-8").read() == "가")

        empty = os.path.join(tmp, "빈파일.txt")
        open(empty, "w", encoding="utf-8").close()
        how = FS._write_preserving(empty, lambda t: open(t, "w", encoding="utf-8").write("나"))
        check("빈 파일 → 'created' (잃을 게 없다)", how == "created")
        check("빈 파일엔 휴지통이 **안** 생긴다", trashed == [])

        full = os.path.join(tmp, "내용있음.txt")
        with open(full, "w", encoding="utf-8") as f:
            f.write("옛 내용")
        how = FS._write_preserving(full, lambda t: open(t, "w", encoding="utf-8").write("새 내용"))
        check("내용 있는 파일 → 'overwritten'", how == "overwritten")
        check("옛 것이 휴지통으로 갔다", trashed == [full])
        check("새 내용이 남았다", open(full, encoding="utf-8").read() == "새 내용")

        # ═══ 계약 2 — 쓰기가 실패하면 옛 파일이 그대로 있다 ═══════════
        print("=== 계약 2 · 실패해도 옛 것을 잃지 않는다 (순서가 계약이다) ===")
        trashed.clear()
        keep = os.path.join(tmp, "지켜야함.txt")
        with open(keep, "w", encoding="utf-8") as f:
            f.write("소중한 내용")

        def _boom(target):
            raise OSError("디스크가 꽉 찼다")

        try:
            FS._write_preserving(keep, _boom)
            raised = False
        except OSError:
            raised = True
        check("쓰기 실패는 예외로 올라간다", raised)
        check("🔑 옛 파일이 **그대로 있다**", os.path.exists(keep))
        check("내용도 그대로다", open(keep, encoding="utf-8").read() == "소중한 내용")
        check("🚨 휴지통을 **먼저** 부르지 않았다", trashed == [])
        check("임시 파일이 안 남았다", not os.path.exists(keep + ".pluiz_tmp"))

        FS._to_trash = real_to_trash

        # ═══ 계약 3 — 휴지통을 못 쓰면 승인을 받는다 / 쓸 수 있으면 안 묻는다 ═══
        print("=== 계약 3 · 휴지통을 못 쓰면 3층으로 내려간다 ===")
        real_trash_ok = FS.trash_is_available
        FS.trash_is_available = lambda: False
        blocked = os.path.join(tmp, "막혀야함.txt")
        with open(blocked, "w", encoding="utf-8") as f:
            f.write("잃으면 안 되는 것")
        how = FS._write_preserving(blocked, lambda t: open(t, "w", encoding="utf-8").write("새것"))
        check("휴지통 없음 + 내용 있음 → OVERWRITE_BLOCKED", how == FS.OVERWRITE_BLOCKED)
        check("🔑 **덮어쓰지 않았다**", open(blocked, encoding="utf-8").read() == "잃으면 안 되는 것")

        gone = os.path.join(tmp, "휴지통없어도된다.txt")
        how = FS._write_preserving(gone, lambda t: open(t, "w", encoding="utf-8").write("ㄱ"))
        check("휴지통이 없어도 **새 파일**은 그냥 쓴다", how == "created")
        FS.trash_is_available = real_trash_ok

        real_recoverable = G._deletion_is_recoverable
        G._deletion_is_recoverable = lambda: False
        danger_no_trash = G.dangerous_tools_now()
        G._deletion_is_recoverable = lambda: True
        danger_trash = G.dangerous_tools_now()
        G._deletion_is_recoverable = real_recoverable

        check("휴지통 없으면 create_file 이 승인 대상이 된다",
              "create_file" in danger_no_trash and "write_excel" in danger_no_trash)
        check("🔑 휴지통이 있으면 **안 묻는다** (승인 피로 · ADR §3-1)",
              "create_file" not in danger_trash and "write_excel" not in danger_trash)
        check("어느 쪽이든 삭제·클릭·강제종료는 항상 승인 대상이다",
              G.DANGEROUS_TOOLS <= danger_trash and G.DANGEROUS_TOOLS <= danger_no_trash)
        check("DANGEROUS_TOOLS 상수 자체는 안 바뀐다(테스트가 그 이름에 걸려 있다)",
              "create_file" not in G.DANGEROUS_TOOLS)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ═══ 계약 4 — 안 닫히면 ✓ 를 안 쓴다 / 닫혔으면 ⚠️ 를 안 쓴다 ═══
    #   🚨 실제 창을 열지 않는다 — 소스가 «무엇을 보고 답하는가»를 고정한다.
    print("=== 계약 4 · close_app 은 곱게 닫고, 본 대로 말한다 ===")
    APP = _src(os.path.join("tools", "app_control.py"))
    close_src = APP[APP.index("def close_app("):APP.index("def force_close_app(")]
    check("close_app 이 WM_CLOSE 를 보낸다", "_WM_CLOSE" in close_src)
    check("🔑 close_app 이 **terminate() 를 안 부른다**", ".terminate()" not in close_src)
    check("창이 남았는지 확인한다", "_await_windows_gone" in close_src)
    check("남았으면 «저장할지 묻는 창»을 말한다", "저장할지 묻는 창" in close_src)
    check("창을 못 찾으면 강제로 끄지 않고 말한다", "닫을 창을 찾지 못했어요" in close_src)
    check("✓ 는 창이 다 사라진 경우에만 쓴다",
          close_src.count("✓") == 1 and "if not left:" in close_src)
    check("explorer 예외는 그대로다", "파일 탐색기는 Windows 시스템 프로세스" in close_src)

    force_src = APP[APP.index("def force_close_app("):]
    force_src = force_src[:force_src.index("# ── 창 상태 바꾸기")]
    check("force_close_app 은 terminate() 를 쓴다", ".terminate()" in force_src)
    check("force_close_app 도 죽었는지 확인한다(_await_gone)", "_await_gone(" in force_src)

    # ═══ 계약 5 — force_close_app 은 승인을 지나고 close_app 은 안 지난다 ═══
    print("=== 계약 5 · 승인은 강제 종료에만 붙는다 ===")
    check("force_close_app 이 DANGEROUS_TOOLS 에 있다",
          "force_close_app" in G.DANGEROUS_TOOLS)
    check("🔑 close_app 은 **없다** (*'계산기 꺼줘'* 마다 묻지 않는다)",
          "close_app" not in G.DANGEROUS_TOOLS)
    check("승인 대상은 넷이다", len(G.DANGEROUS_TOOLS) == 4)

    REG = _src(os.path.join("core", "tool_registry.py"))
    check("force_close_app 이 실제로 등록돼 있다", "force_close_app," in REG)

    # 🚨 절대규칙 9와 같은 모양 — `force` 를 인자로 주면 LLM 이 언젠가 지어낸다
    check("🚨 close_app 에 force 인자가 **없다**",
          "def close_app(app: str) -> str:" in APP)
    check("🚨 force_close_app 도 앱 이름만 받는다",
          "def force_close_app(app: str) -> str:" in APP)

    print("=== 계약 5-b · 승인 질문이 도구마다 다른 말을 한다 ===")
    q_force = G._confirm_question([{"name": "force_close_app", "args": {"app": "메모장"}}])
    check("강제 종료 질문에 «저장하지 않은 내용»이 있다", "저장하지 않은 내용" in q_force)
    check("🔑 강제 종료 질문에 «휴지통»이 **없다** (거짓이 된다)", "휴지통" not in q_force)
    check("무엇을 끄는지 이름을 부른다", "메모장" in q_force)

    q_del = G._confirm_question([{"name": "delete_file", "args": {"file_path": "a.txt"}}])
    check("삭제 질문은 여전히 «삭제할까요»다(회귀 방지)", "삭제할까요" in q_del)
    check("삭제 질문에 «강제로 종료»가 섞이지 않는다", "강제로 종료" not in q_del)

    q_click = G._confirm_question([{"name": "click_ui_element", "args": {"target": "저장"}}])
    check("클릭 질문은 여전히 «되돌릴 수 없어요»다(회귀 방지)", "되돌릴 수 없어요" in q_click)

    q_write = G._confirm_question([{"name": "create_file", "args": {"name": "메모.txt"}}])
    check("덮어쓰기 질문이 파일 이름을 부른다", "메모.txt" in q_write)
    check("덮어쓰기 질문이 «덮어쓸까요»다", "덮어쓸까요" in q_write)
    check("🔑 덮어쓰기 질문에 «휴지통으로 갑니다»가 **없다**",
          "휴지통으로 갑니다" not in q_write)

    q_two = G._confirm_question([
        {"name": "delete_file", "args": {"file_path": "a.txt"}},
        {"name": "force_close_app", "args": {"app": "그림판"}},
    ])
    check("둘이 같이 오면 둘 다 말한다", "a.txt" in q_two and "그림판" in q_two)

    # ═══ 계약 6 — 덮어쓴 응답이 덮어썼다고 말한다 / 새 파일은 그 말을 안 한다 ═══
    print("=== 계약 6 · 덮어썼으면 그렇게 말한다 ===")
    FS_SRC = _src(os.path.join("tools", "filesystem.py"))
    cf = FS_SRC[FS_SRC.index("def create_file("):FS_SRC.index("def create_folder(")]
    check("덮어쓴 응답에 «휴지통으로 옮겼어요»가 있다", "휴지통으로 옮겼어요" in cf)
    check("🔑 새로 만든 응답은 **그 말을 안 한다**",
          cf.count("휴지통으로 옮겼어요") == 1 and "'{name}' 파일을 {location}에 만들었어요" in cf)
    check("막힌 경우엔 «쓰지 않았어요»라고 말한다", "쓰지 않았어요" in cf)
    check("막힌 경우엔 ✓ 를 쓰지 않는다",
          "OVERWRITE_BLOCKED" in cf and cf.index("OVERWRITE_BLOCKED") < cf.index("✓ '{name}'"))

    we = FS_SRC[FS_SRC.index("def write_excel("):FS_SRC.index("# ── 위험 동작: 삭제")]
    check("write_excel 도 같은 길을 쓴다(사본 둘이 안 된다)", "_write_preserving" in we)
    check("🚨 write_excel 에 비밀 파일 검사가 생겼다 (감사 G-06)", "_is_secret_path" in we)
    check("write_excel 도 덮어썼다고 말한다", "휴지통으로 옮겼어요" in we)

    # ═══ 안전망 — 승인 대상인데 등록이 안 되면 «못 하게» 된다 ═══════
    print("=== 안전망 · 승인 대상은 전부 실제 도구여야 한다 ===")
    for name in sorted(G.DANGEROUS_TOOLS):
        check(f"{name} 가 tool_registry 에 있다", f"{name}," in REG or f"{name}]" in REG)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
