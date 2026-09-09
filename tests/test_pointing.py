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
    check("zoom=True 반영", P.point_payload(loc, zoom=True)["zoom"] is True)
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
