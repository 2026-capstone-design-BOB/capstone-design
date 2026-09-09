"""M4 포인팅 · 확대 — 계약 검증 (mock)

    python tests/test_pointing.py

설계: docs/design/M4_포인팅_확대.md

## ⚠️ 이 스위트가 보증하지 **못하는** 것

ADR §8의 확인표에서 ⑤⑥⑦은 **사람만 볼 수 있다**:

  ⑤ 표시된 버튼을 **실제로 누를 수 있는가** (클릭 통과)
  ⑥ 표시가 **다음 캡처에 안 찍히는가**
  ⑦ 라벨이 표시와 같이 보이는가

여기서 초록이 나와도 **«된다»가 아니다.** 2026-09-09에 웨이크워드 검증 성적이
멀쩡한 채로 모델이 망가져 있었다(BL-23) — 같은 실수를 반복하지 않는다.
사람이 볼 절차는 docs/testing/MANUAL_TESTS.md 에 있다.
"""
import _testenv  # noqa: F401
import sys, os, importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load("pluiz_pointer", os.path.join("core", "pointer.py"))
M = _load("pluiz_monitor", os.path.join("core", "screen_monitor.py"))


def run():
    passed = total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    # ═══ ① 못 찾으면 아무것도 그리지 않는다 (ADR §4-3) ═══════════
    print("=== ① 못 찾았으면 표시하지 않는다 ===")
    check("found=False → None", P.point_payload({"found": False, "reason": "없음"}) is None)
    check("빈 dict → None", P.point_payload({}) is None)
    check("None → None", P.point_payload(None) is None)
    check("문자열 → None (타입 방어)", P.point_payload("찾았어요") is None)
    check("found=True인데 좌표가 없으면 None",
          P.point_payload({"found": True, "label": "x"}) is None)

    print("=== ① 찾았으면 payload를 만든다 ===")
    loc = {"found": True, "rect": [10, 20, 110, 60], "center": [60, 40],
           "size": [100, 40], "label": "블루투스"}
    pl = P.point_payload(loc)
    check("type=point", pl and pl["type"] == "point")
    check("rect를 **그대로** 넘긴다(보정하지 않는다)", pl["rect"] == [10, 20, 110, 60])
    check("center도 같이 넘긴다", pl["center"] == [60, 40])
    check("label 유지", pl["label"] == "블루투스")
    check("zoom 기본 False", pl["zoom"] is False)
    # ⚠️ zoom=True인데 확대본(crop)이 없으면 **False로 내려간다** — 없는 확대를
    #   «했다»고 말하지 않기 위해서다. crop이 있는 경우는 ⑤에서 본다.
    check("확대본이 없으면 zoom=True라도 False로 내려간다",
          P.point_payload(loc, zoom=True)["zoom"] is False)
    check("seconds가 실려 나간다(Electron 타이머의 근거)",
          isinstance(pl["seconds"], float) and pl["seconds"] > 0)
    # 좌표를 여기서 보정하면 click_ui_element와 다른 곳을 가리키게 된다
    check("rect가 없고 center만 있어도 그린다",
          P.point_payload({"found": True, "center": [5, 5], "label": "x"}) is not None)

    # ═══ ② 표시 상태 · 해제 ═══════════════════════════════════════
    print("=== ② 표시 상태와 해제 ===")
    P.reset()
    sent = []
    P.set_notifier(lambda p: sent.append(p))
    check("처음엔 표시 없음", P.is_visible() is False)
    check("표시가 없으면 캡처는 아무것도 안 한다",
          P.clear_for_capture("t") is False)

    P.show(pl)
    check("show → 표시 중", P.is_visible() is True)
    check("show → UI로 나간다", sent and sent[-1]["type"] == "point")
    check("남은 시간이 0보다 크다", P.remaining() > 0)

    P.hide("테스트")
    check("hide → 표시 없음", P.is_visible() is False)
    check("hide → point_clear가 나간다", sent[-1]["type"] == "point_clear")

    n = len(sent)
    P.hide("두 번째")
    check("이미 없으면 hide는 조용하다(중복 clear 없음)", len(sent) == n)

    # ⚠️ 8초 자동 해제는 «마지막 방어선»이다. 시계를 흉내 내 만료를 확인한다.
    print("=== ② 시간이 지나면 반드시 사라진다 (ADR §4-2 ①) ===")
    P.reset()
    P.show({**pl, "seconds": 0.15})
    check("띄운 직후엔 보인다", P.is_visible() is True)
    import time as _t
    _t.sleep(0.3)
    check("만료 후 is_visible False", P.is_visible() is False)

    # 🚨 2026-09-09 정정 — 캡처는 «기다리지» 않고 «치운다».
    #    기다리던 시절, 한 턴에 포인팅+화면설명이 같이 오면 8초가 통째로 지연에
    #    얹혀 턴이 28초가 됐다(실측). 아래가 그 회귀를 막는다.
    print("=== ② 캡처는 표시를 «기다리지» 않고 «치운다» (지연 회귀 방지) ===")
    P.reset()
    P.show({**pl, "seconds": 30})     # 오래 남는 표시
    t0 = _t.monotonic()
    cleared = P.clear_for_capture("테스트")
    elapsed = _t.monotonic() - t0
    check("표시가 있으면 치웠다고 답한다", cleared is True)
    check("치운 뒤에는 표시가 없다", P.is_visible() is False)
    check("기다리지 않는다 (0.5초 미만)", elapsed < 0.5)
    check("치울 때 point_clear가 나간다", sent[-1]["type"] == "point_clear")
    P.reset()

    print("=== ② remaining은 주입한 시계로 계산된다 ===")
    check("이미 지났으면 0", P.remaining(now=100.0, until=50.0) == 0.0)
    check("남았으면 그 차이", abs(P.remaining(now=100.0, until=103.5) - 3.5) < 1e-9)

    # ═══ ③ 감시가 표시 구간을 건너뛴다 (ADR §5) ══════════════════
    # **이 스위트에서 가장 중요한 항목이다.** 거르지 않으면 오버레이가 뜨고 지는
    # 것 자체가 «변화»라 우리가 우리를 감시하고, 화면이 밖으로 나간다.
    print("=== ③ 포인팅 표시 중에는 감시가 화면을 내보내지 않는다 ===")

    frames = []          # 감시가 볼 화면 서명들
    vision_calls = []

    def fake_capture(window):
        return frames.pop(0) if frames else (0,) * (M.SIGNATURE_SIDE ** 2)

    def fake_vision(window, what):
        vision_calls.append(what)
        return {"ok": True, "detected": True, "detail": "무언가 보임"}

    flat = (0,) * (M.SIGNATURE_SIDE ** 2)
    other = (255,) * (M.SIGNATURE_SIDE ** 2)

    pointer_on = {"v": False}
    sleeps = {"n": 0}
    clock = {"t": 0.0}

    # ⚠️ **시계를 반드시 주입한다.** 안 하면 `_now`가 진짜 monotonic이고
    #   `_started_at=0.0`이라 **루프가 첫 바퀴에 timeout으로 끝난다.**
    #   그러면 "Vision 0회"가 «잘 걸렀다»가 아니라 «아무것도 안 돌았다»가 되어
    #   테스트가 헛통과한다(만들면서 실제로 그랬다).
    def fake_now():
        return clock["t"]

    def fake_sleep(sec):
        clock["t"] += max(float(sec), 0.01)
        sleeps["n"] += 1
        if sleeps["n"] > 40:
            raise SystemExit  # 무한루프 방지

    def drive(capture, ptr, *, max_vision=3):
        """감시 루프를 **동기로** 한 바퀴 돌린다 (test_screen_monitor.py와 같은 방식).

        스레드를 띄우면 테스트가 타이밍에 의존한다. 세션 상태만 세팅하고
        `_loop()`를 직접 부른다.
        """
        clock["t"] = 0.0
        sleeps["n"] = 0
        m = M.ScreenMonitor(
            capture_signature=capture, vision_check=fake_vision,
            notify=lambda *a: None, sleep=fake_sleep, now=fake_now,
            config_provider=lambda: {"enabled": True, "interval": 0.01,
                                     "max_minutes": 10,
                                     "max_vision_calls": max_vision},
            pointer_visible=ptr)
        m._cfg = m._load_config()
        m._what, m._window = "오류", ""
        m._vision_calls = 0
        m._started_at = fake_now()
        try:
            m._loop()
        except SystemExit:
            pass
        return m

    # 🚨 위 함정이 되살아나지 않게 **여기서 먼저 고정한다** —
    #    거르기가 없을 때 이 세팅이 실제로 Vision을 부르는지 확인한다.
    #    이게 없으면 아래 «Vision 0회» 검사들이 전부 헛통과할 수 있다.
    frames[:] = [flat, other, other]
    vision_calls.clear()
    drive(fake_capture, lambda: False)
    check("[전제] 표시가 없으면 이 세팅은 Vision을 부른다", len(vision_calls) >= 1)

    # (a) 표시 중 — 화면이 완전히 바뀌어도 Vision이 돌면 안 된다
    frames[:] = [flat, other, other, other]
    vision_calls.clear(); sleeps["n"] = 0
    pointer_on["v"] = True
    drive(fake_capture, lambda: pointer_on["v"])
    check("표시 중이면 화면이 바뀌어도 Vision 0회", len(vision_calls) == 0)

    # (b) 표시가 없으면 평소대로 감지한다 (거르기가 기능을 죽이지 않았는지)
    frames[:] = [flat, other, other]
    vision_calls.clear(); sleeps["n"] = 0
    pointer_on["v"] = False
    drive(fake_capture, lambda: pointer_on["v"])
    check("표시가 없으면 평소대로 감지한다(거르기가 기능을 안 죽였다)",
          len(vision_calls) >= 1)

    # (c) 기준 프레임을 갱신하지 않는다 — **사라질 때 또 새면 안 된다**
    #     표시 중에 온 프레임을 baseline으로 삼으면, 표시가 지는 순간이 또 «변화»다.
    #
    # ⚠️ 시나리오를 **반복 횟수**로 몰아야 한다. 캡처 횟수로 표시 구간을 정하면,
    #    올바른 구현이 «표시 중엔 캡처하지 않는» 탓에 카운터가 안 늘어 무한 스킵이
    #    되고 테스트가 헛통과한다(만들면서 실제로 그랬다 — 아래 [전제]가 잡았다).
    print("=== ③ 표시 구간 프레임을 기준으로 삼지 않는다 ===")
    iters = {"n": 0}

    def ptr_on():
        return 2 <= iters["n"] <= 4         # 2~4번째 바퀴에 표시가 떠 있다

    def capture_overlay(window):
        # 표시 중이면 오버레이가 낀 화면. 올바른 구현은 이걸 **보지도 않는다.**
        return other if ptr_on() else flat

    def sleep_iter(sec):
        iters["n"] += 1
        clock["t"] += max(float(sec), 0.01)
        if iters["n"] > 12:
            raise SystemExit

    vision_calls.clear()
    clock["t"] = 0.0
    iters["n"] = 0
    mon = M.ScreenMonitor(
        capture_signature=capture_overlay, vision_check=fake_vision,
        notify=lambda *a: None, sleep=sleep_iter, now=fake_now,
        config_provider=lambda: {"enabled": True, "interval": 0.01,
                                 "max_minutes": 10, "max_vision_calls": 3},
        pointer_visible=ptr_on)
    mon._cfg = mon._load_config()
    mon._what, mon._window = "오류", ""
    mon._vision_calls = 0
    mon._started_at = fake_now()
    try:
        mon._loop()
    except SystemExit:
        pass

    # 표시가 꺼진 뒤 화면은 기준(flat)과 **같다.** 오버레이 프레임(other)을 기준으로
    # 삼았다면 여기서 «변화»가 잡혀 화면이 밖으로 나간다.
    check("표시가 사라진 뒤 «변화»로 잡히지 않는다", len(vision_calls) == 0)
    # ⚠️ 위가 «루프가 안 돌아서» 통과하는 것을 막는다.
    check("[전제] 표시 구간을 지나 그 뒤까지 돌았다", iters["n"] > 5)

    # ═══ ⑤ 확대 = 돋보기 · 2패스 정밀화 (M4 §6, 2026-09-09 사용자 선택) ═══
    print("=== ⑤ 돋보기 — 대상 중심 정사각형을 잘라 확대한다 ===")
    import tempfile as _tf, base64 as _b64, io as _bio
    try:
        from PIL import Image, ImageDraw
        from tools.vision import (loupe_data_uri, refine_box, box_in_crop_to_image,
                                  LOUPE_SRC_PX, LOUPE_OUT_PX)
        cap = os.path.join(_tf.gettempdir(), "pluiz_loupe_regress.png")
        im = Image.new("RGB", (1000, 600), (230, 230, 235))
        ImageDraw.Draw(im).rectangle([440, 290, 540, 330], fill=(60, 90, 200))
        im.save(cap)

        uri = loupe_data_uri(cap, (490, 310))
        check("data URI를 만든다", bool(uri) and uri.startswith("data:image/png;base64,"))
        z = Image.open(_bio.BytesIO(_b64.b64decode(uri.split(",", 1)[1])))
        # ⚠️ 정사각형이어야 한다 — 렌더러가 **원형**으로 그리므로 비율이 어긋나면
        #   돋보기 가운데가 대상에서 밀린다.
        check("정사각형이다(원형 돋보기의 전제)", z.size[0] == z.size[1])
        check("보낼 크기로 키운다", z.size[0] == LOUPE_OUT_PX)

        # 가장자리에 붙은 대상도 **중심과 정사각형**을 유지해야 한다
        edge = loupe_data_uri(cap, (5, 5))
        ze = Image.open(_bio.BytesIO(_b64.b64decode(edge.split(",", 1)[1])))
        check("화면 가장자리여도 정사각형", ze.size[0] == ze.size[1])

        check("없는 파일이면 None (예외 아님)",
              loupe_data_uri("__없는파일__.png", (10, 10)) is None)
        os.unlink(cap)
    except ImportError:
        print("  (PIL 없음 — 돋보기 검사 생략)")

    print("=== ⑤ 2패스 정밀화 — 조각 영역 계산 ===")
    from tools.vision import refine_box, box_in_crop_to_image, REFINE_MIN_PX, REFINE_MAX_PX
    r = refine_box((400, 300, 500, 325), (1000, 600))
    check("조각은 정사각형", (r[2] - r[0]) == (r[3] - r[1]))
    check("작은 요소여도 최소 크기를 지킨다", (r[2] - r[0]) >= REFINE_MIN_PX)
    check("1차 중심을 품는다", r[0] <= 450 <= r[2] and r[1] <= 312 <= r[3])
    # ⚠️ 가장자리 요소에서 조각이 작아지면 배율이 떨어져 정밀화 의미가 없다
    e = refine_box((0, 0, 40, 20), (1000, 600))
    check("가장자리에서도 조각 크기를 유지한다(밀어 넣는다)",
          (e[2] - e[0]) >= REFINE_MIN_PX and e[0] >= 0 and e[1] >= 0)
    big = refine_box((0, 0, 900, 550), (1000, 600))
    check("큰 요소여도 상한을 넘지 않는다", (big[2] - big[0]) <= REFINE_MAX_PX)

    print("=== ⑤ 조각 좌표 → 원본 좌표 되돌리기 ===")
    back = box_in_crop_to_image((250, 250, 750, 750), (100, 100, 300, 300))
    check("조각 한가운데는 원본 한가운데로", [round(v) for v in back] == [150, 150, 250, 250])
    full = box_in_crop_to_image((0, 0, 1000, 1000), (50, 60, 250, 260))
    check("조각 전체는 조각 사각형 그대로", [round(v) for v in full] == [50, 60, 250, 260])

    print("=== ⑤ payload — 못 만들었으면 «확대했다»고 하지 않는다 ===")
    locz = {"found": True, "rect": [400, 300, 500, 340], "center": [450, 320],
            "label": "버튼", "crop": "data:image/png;base64,AAAA",
            "crop_src_px": 150, "crop_mag": 3}
    pz = P.point_payload(locz, zoom=True)
    check("zoom=True면 zoomImage가 실린다", "zoomImage" in pz)
    check("돋보기 크기 근거(zoomSrcPx)가 실린다", pz.get("zoomSrcPx") == 150)
    check("배율도 실린다", pz.get("zoomMag") == 3)
    check("zoom=False면 안 실린다", "zoomImage" not in P.point_payload(locz, zoom=False))
    nocrop = {k: v for k, v in locz.items() if k != "crop"}
    pn = P.point_payload(nocrop, zoom=True)
    check("crop이 없으면 zoom이 False로 내려간다(거짓말 방지)", pn["zoom"] is False)
    check("crop이 없어도 고리는 그린다", pn is not None and pn["rect"] is not None)

    print("=== ⑤ locate_ui_element 기본값 — 기존 호출자는 그대로 ===")
    import inspect
    from tools.vision import locate_ui_element
    sig = inspect.signature(locate_ui_element)
    check("want_crop 기본 False", sig.parameters["want_crop"].default is False)
    # ⚠️ refine도 기본 False다. 2026-09-09 실측에서 **효과가 음수**였다(요소 크기가
    #   75×22 → 13~26px로 무너지고 턴이 9초 → 13~17초). 코드는 남겨 두되 끈다.
    check("refine 기본 False", sig.parameters["refine"].default is False)
    # ⚠️ ensure_visible도 기본 False — click_ui_element는 «클릭» 승인만 받았지
    #   «앱 실행» 승인을 받은 게 아니다. 승인 범위를 넘기지 않는다.
    check("ensure_visible 기본 False", sig.parameters["ensure_visible"].default is False)

    # ═══ ⑥ 창 상태 처리 — 한 일을 반드시 말한다 (2026-09-09) ═══════
    print("=== ⑥ 창을 열거나 앞으로 냈으면 **말한다** ===")
    from tools.vision import prepared_note
    check("열었으면 말한다",
          "먼저 열었어요" in prepared_note({"prepared": {"action": "launched", "label": "메모장"}}))
    check("최소화 복원도 말한다",
          "다시 띄웠어요" in prepared_note({"prepared": {"action": "restored", "label": "메모장"}}))
    check("앞으로 냈어도 말한다",
          "앞으로 가져왔어요" in prepared_note({"prepared": {"action": "fronted", "label": "메모장"}}))
    # ⚠️ 아무 일도 안 했으면 **아무 말도 안 한다** — 매번 붙으면 문구가 소음이 된다
    check("아무 일도 안 했으면 조용하다",
          prepared_note({"prepared": {"action": "", "label": "메모장"}}) == "")
    check("prepared가 없어도 안 죽는다", prepared_note({}) == "")
    check("None이어도 안 죽는다", prepared_note(None) == "")

    print("=== ⑥ ensure_window_ready — 전체화면은 건드리지 않는다 ===")
    from tools.system import ensure_window_ready
    r0 = ensure_window_ready("")
    check("window가 비면 ok이고 아무 동작도 없다",
          r0["ok"] is True and r0["action"] == "")
    r1 = ensure_window_ready("__존재하지않는앱__", launch=False)
    check("launch=False면 열지 않고 실패를 돌려준다",
          r1["ok"] is False and r1["action"] == "")
    check("실패에 이유가 있다", bool(r1["reason"]))

    # ═══ ④ 도구 계약 ═════════════════════════════════════════════
    print("=== ④ 도구가 등록돼 있고 좌표 인자를 받지 않는다 ===")
    from core.tool_registry import get_all_tools
    tools = {t.name: t for t in get_all_tools()}
    check("point_at_element 등록됨", "point_at_element" in tools)
    if "point_at_element" in tools:
        args = set(tools["point_at_element"].args.keys())
        check("인자는 target·window·zoom 뿐", args == {"target", "window", "zoom"})
        # ⚠️ 절대규칙 9의 포인팅판 — 좌표를 받으면 LLM이 지어낸다
        check("좌표 인자(x·y)가 **없다**", not ({"x", "y"} & args))
        doc = tools["point_at_element"].description or ""
        check("설명에 «찾지 못했다»가 있다(없는 걸 가리키지 않는다)", "찾지 못" in doc)

    print("=== ④ 승인 대상이 아니다 (아무것도 바꾸지 않는다) ===")
    G = _load("pluiz_graph2", os.path.join("core", "graph.py"))
    check("DANGEROUS_TOOLS에 없다", "point_at_element" not in G.DANGEROUS_TOOLS)
    check("click_ui_element는 여전히 위험 도구다(회귀 방지)",
          "click_ui_element" in G.DANGEROUS_TOOLS)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
