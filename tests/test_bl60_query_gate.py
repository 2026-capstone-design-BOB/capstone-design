# -*- coding: utf-8 -*-
"""묻는 말이 **실행되지 않는다** — 조회 게이트와 읽는 도구 ([BL-60](../docs/BACKLOG.md))

실행: python tests/test_bl60_query_gate.py

## 무슨 일이 있었나 (2026-09-19 라이브 점검)

*"밝기 알려줘"* 라고만 했는데 **화면이 70%로 바뀌었다.**

    '밝기 알려줘'  ↔  '밝기 올려줘'    ← 한 글자 차이. 유사도 **0.83**

그리고 `SIMILARITY_THRESHOLD` 가 **정확히 0.83** 이다. 「알」과 「올」 하나로 조회가
조작이 됐다. 볼륨도 같았고, 여기 와서 **하나가 더 나왔다**:

    '음소거됐어?'  → `mute_toggle`    ← 상태를 물었는데 **소리가 꺼진다**

셋 중 이게 가장 나쁘다 — 사용자는 **묻기만 했다.**

## 여기서 고정하는 것

| | 왜 |
|---|---|
| 묻는 말 + **조작 도구** → 캐시 포기 | 발화만 보면 *"시간 알려줘"* 가 같이 죽고, 도구만 보면 *"밝기 올려줘"* 가 막힌다. **둘이 같이** 성립할 때만이다 |
| 모르는 도구는 **조작으로 본다** | 여집합으로 두면 도구가 늘 때마다 샌다. 빠뜨렸을 때 안전한 방향이 이쪽이다 |
| 🔴 «바꾸라는 말»이 있으면 **안 막는다** | *"소리 얼마나 줄여줘"* — 「얼마」가 있지만 명령이다. 막으면 **오프라인에서 죽는다** |
| 읽는 도구가 **있다** | 게이트만 있으면 «안 바뀌지만 답도 못 하는» 상태가 된다. **한 쌍이다** |
| 읽는 도구가 **기억을 «지금 값»이라고 안 한다** | `_last_brightness` 는 «우리가 쓴 값»이지 측정치가 아니다 ([BL-61](../docs/BACKLOG.md)과 같은 종류의 거짓말) |
| 게이트가 **세 문에 다 걸린다** | 찾기·학습·가져오기. 한 곳만 막으면 다른 입구로 샌다(BL-27·BL-50이 같은 값을 치렀다) |

🚨 **이 테스트는 실제 화면·소리를 바꾸지 않는다.** 읽는 도구만 부르고,
   `set_brightness` 는 **범위 밖 값**으로만 부른다(그 경로는 장치를 안 건드린다).
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

NL = chr(10)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


def fresh_cache():
    """시드만 든 새 캐시. 학습 검사는 **매번 새것**이어야 한다 —
    이미 아는 패턴은 `learn()` 이 False 를 돌려주므로 거절과 구별이 안 된다."""
    import core.command_cache as M
    M.CACHE_FILE = os.path.join(tempfile.mkdtemp(), "c.json")
    return M.CommandCache()


def names_of(hit):
    return [] if hit is None else [t.get("name") for t in hit[0].tool_calls]


def run():
    import core.command_cache as M
    c = fresh_cache()

    print("=== ① 재현 — 이 셋이 라이브에서 났다 ===")
    # 🚨 셋 다 «묻기만 했는데 상태가 바뀐» 것이다.
    check("'밝기 알려줘' 가 밝기를 **안 바꾼다**",
          "brightness_up" not in names_of(c.find("밝기 알려줘")),
          f"→ {names_of(c.find('밝기 알려줘'))}")
    check("'볼륨 알려줘' 가 볼륨을 **안 바꾼다**",
          "volume_up" not in names_of(c.find("볼륨 알려줘")),
          f"→ {names_of(c.find('볼륨 알려줘'))}")
    check("🚨 '음소거됐어?' 가 **음소거를 토글하지 않는다**",
          "mute_toggle" not in names_of(c.find("음소거됐어?")),
          f"→ {names_of(c.find('음소거됐어?'))}")

    print(f"{NL}=== ② 그리고 **답을 한다** — 막기만 하면 반쪽이다 ===")
    for q, want in [("밝기 알려줘", "get_brightness"),
                    ("지금 밝기 얼마야", "get_brightness"),
                    ("밝기 몇 퍼센트야", "get_brightness"),
                    ("밝기 어때", "get_brightness"),
                    ("볼륨 알려줘", "get_volume"),
                    ("지금 볼륨 얼마야", "get_volume"),
                    ("소리 얼마나 돼", "get_volume"),
                    ("음소거됐어?", "get_volume")]:
        got = names_of(c.find(q))
        check(f"{q!r} → {want}", got == [want], f"→ {got}")

    print(f"{NL}=== ③ 🔴 반대 방향 — 멀쩡한 명령이 안 죽는다 ===")
    for q, want in [("밝기 올려줘", "brightness_up"),
                    ("밝기 내려줘", "brightness_down"),
                    ("화면 밝게 해줘", "brightness_up"),
                    ("볼륨 올려줘", "volume_up"),
                    ("볼륨 좀 올려줘", "volume_up"),
                    ("소리 줄여", "volume_down"),
                    ("음소거해줘", "mute_toggle"),
                    ("메모장 열어줘", "open_app"),
                    ("스크린샷 찍어줘", "take_screenshot")]:
        got = names_of(c.find(q))
        check(f"{q!r} → {want} (그대로 돈다)", got == [want], f"→ {got}")

    # 🚨 **이게 없으면 오프라인에서 명령이 죽는다.** 「얼마」가 들어 있지만 명령이다.
    #   온라인이면 LLM 이 받아 주지만, 오프라인은 캐시 미스에서 그냥 끝난다(BL-46).
    check("🔴 '소리 얼마나 줄여줘' 는 **명령이다** (「얼마」가 있어도 막지 않는다)",
          names_of(c.find("소리 얼마나 줄여줘")) == ["volume_down"],
          f"→ {names_of(c.find('소리 얼마나 줄여줘'))}")
    # 🚨 **조회가 명령을 가로채지 않는다.** 「밝기얼마」를 품고 있어서 그냥 두면
    #   밝기를 **읽어 주고 만다** — 올려 달라고 했는데. 캐시가 못 정하면 LLM 이
    #   받으므로(이 발화는 원래도 캐시 미스였다) «읽어 주는 것»만 막으면 된다.
    check("🔴 '밝기 얼마나 올려줘' 를 **읽기로 처리하지 않는다**",
          "get_brightness" not in names_of(c.find("밝기 얼마나 올려줘")),
          f"→ {names_of(c.find('밝기 얼마나 올려줘'))}")
    # 조회 표지가 있어도 **읽는 도구**로 가는 것은 원래 잘 되고 있었다. 막으면 안 된다.
    check("'지금 몇 시야' 가 그대로 시간을 읽는다",
          names_of(c.find("지금 몇 시야")) == ["get_current_time"])
    check("'배터리 얼마나 남았어' 가 그대로 배터리를 읽는다",
          names_of(c.find("배터리 얼마나 남았어")) == ["get_battery_status"])

    print(f"{NL}=== ④ query_conflict — 판정의 계약 ===")
    Q = [{"name": "brightness_up", "args": {}}]
    R = [{"name": "get_brightness", "args": {}}]
    check("묻는 말 + 조작 도구 → 막는다", c.query_conflict("밝기 알려줘", Q))
    check("묻는 말 + 읽는 도구 → 안 막는다", not c.query_conflict("밝기 알려줘", R))
    check("묻는 말이 아니면 → 안 막는다", not c.query_conflict("밝기 올려줘", Q))
    check("도구가 없으면 → 안 막는다", not c.query_conflict("밝기 알려줘", []))
    # 🚨 목록을 «조회 도구»로 적은 이유가 이 한 줄이다. 새 도구가 늘어도 안 샌다.
    check("🚨 **모르는 도구는 조작으로 본다** (빠뜨렸을 때 안전한 쪽)",
          c.query_conflict("밝기 알려줘", [{"name": "아직_없는_도구", "args": {}}]))
    check("여러 도구 중 하나라도 조작이면 막는다",
          c.query_conflict("밝기 알려줘", R + Q))
    check("has_query_marker 가 묻는 말을 본다",
          c.has_query_marker("밝기 얼마야") and c.has_query_marker("볼륨 알려줘"))
    check("has_query_marker 가 명령에 안 걸린다",
          not c.has_query_marker("밝기 올려줘") and not c.has_query_marker("메모장 열어줘"))
    # ⚠️ 요청 어미는 묻는 말이 아니다 — 넣으면 *"볼륨 30으로 맞춰 줄래"* 가 죽는다
    check("⚠️ 「줄래」는 묻는 말이 아니다 (부탁이다)",
          not c.has_query_marker("볼륨 30으로 맞춰 줄래"))

    print(f"{NL}=== ⑤ 학습(L5) — 묻는 말을 조작으로 **굳히지 않는다** ===")
    c2 = fresh_cache()
    check("'밝기 알려줘' → brightness_up 은 학습 거부",
          not c2.learn("밝기 알려줘", [{"name": "brightness_up", "args": {}}]))
    # 🔑 **같은 발화라도 도구가 맞으면 학습해야 한다.** 발화만 보는 게이트였다면
    #    이 줄이 깨진다 — 그래서 L5 는 `is_learnable_utterance()` 안에 없다.
    # ⚠️ 시드에 없는 표현으로 본다 — 이미 아는 패턴은 `learn()` 이 False 를
    #   돌려주므로 «거절»과 구별이 안 된다.
    check("🔑 '밝기 지금 얼마임' → get_brightness 는 **학습한다**",
          c2.learn("밝기 지금 얼마임", [{"name": "get_brightness", "args": {}}]))
    check("'밝기 올려봐' → brightness_up 은 그대로 학습한다",
          c2.learn("밝기 올려봐", [{"name": "brightness_up", "args": {}}]))
    # 기존 L1~L4 가 살아 있는지 (BL-27·BL-50)
    check("L2(너무 짧음)가 그대로다",
          (c2.is_learnable_utterance("그래") or "").startswith("L2"))
    check("L3(대조)가 그대로다",
          (c2.is_learnable_utterance("메모장 말고 계산기") or "").startswith("L3"))
    check("L4(지시대명사)가 그대로다",
          (c2.is_learnable_utterance("그거 꺼줘") or "").startswith("L4"))

    print(f"{NL}=== ⑥ 가져오기도 같은 게이트를 지난다 ===")
    # 🚨 여기가 없으면 zip 하나로 오늘 고친 게 되돌려진다 (BL-27이 치른 값과 같다).
    from core.portable import merge_cache_entries
    c3 = fresh_cache()
    # ⚠️ 인자 순서는 (current, incoming, cache) 다.
    res = merge_cache_entries(
        {},
        {"밝기 알려줘": {"tool_calls": [{"name": "brightness_up", "args": {}}],
                        "response_template": "✓ 밝기를 높였습니다."},
         "밝기 세게 올려": {"tool_calls": [{"name": "brightness_up", "args": {}}],
                          "response_template": "✓ 밝기를 높였습니다."}},
        c3)
    why = dict((p, w) for p, w in res["rejected"])
    check("오염된 «묻는 말 → 조작» 항목은 거절된다", "밝기 알려줘" in why,
          f"→ {res}")
    check("거절 사유가 L5 라고 적힌다", why.get("밝기 알려줘", "").startswith("L5"),
          f"→ {why}")
    check("멀쩡한 명령 항목은 들어온다", res["added"] == 1, f"→ {res}")

    print(f"{NL}=== ⑦ 읽는 도구 — 있고, 아무것도 안 바꾼다 ===")
    from core.tool_registry import get_all_tools
    import tools.system as S
    reg = {t.name for t in get_all_tools()}
    for n in ("get_brightness", "get_volume", "set_brightness"):
        check(f"{n} 이 등록돼 있다", n in reg)

    # 🚨 읽는 도구가 설정 함수를 부르면 «묻기만 했는데 바뀐다»가 도구 안으로 옮겨간 것이다.
    src = io.open(os.path.join(_ROOT, "tools", "system.py"), encoding="utf-8").read()
    for fn in ("get_brightness", "get_volume"):
        body = src.split(f"def {fn}()", 1)[1].split(f"{NL}@tool", 1)[0]
        check(f"🚨 {fn} 가 설정 함수를 안 부른다",
              "_set_brightness(" not in body and "_set_volume_level(" not in body
              and "keybd_event" not in body)

    check("범위 밖 밝기는 ✗ 로 막는다 (장치를 안 건드린다)",
          str(S.set_brightness.invoke({"level": 120})).startswith("✗"))
    check("음수도 막는다", str(S.set_brightness.invoke({"level": -1})).startswith("✗"))

    # 🚨 **기억을 «지금 값»이라고 말하지 않는다.** `_last_brightness` 는 우리가 쓴
    #   값이지 측정치가 아니다 — 그걸 «지금 60%예요» 라고 하면 BL-61과 같은 거짓말이다.
    keep_get, keep_last = S._get_brightness, S._last_brightness
    try:
        S._get_brightness = lambda: -1
        S._last_brightness = 60
        out = str(S.get_brightness.invoke({}))
        check("🚨 못 읽으면 ✗ 로 자백한다", out.startswith("✗"), f"→ {out}")
        check("🚨 기억을 «지금 값»이라고 말하지 않는다",
              "지금 값이라고는 못" in out or "지금 60%" not in out, f"→ {out}")
        check("그래도 아는 것은 말해 준다 (기억이라고 이름 붙여서)",
              "60" in out, f"→ {out}")
        S._last_brightness = None
        out = str(S.get_brightness.invoke({}))
        check("기억도 없으면 그냥 못 읽는다고 한다", out.startswith("✗"), f"→ {out}")
    finally:
        S._get_brightness, S._last_brightness = keep_get, keep_last

    print(f"{NL}=== ⑧ 라우터 — 숫자 밝기는 받고 **조회는 안 받는다** ===")
    from core.router import _ROUTER_BRIGHTNESS, _ROUTER_VOLUME, _LEVEL_TAIL
    for t in ("밝기 50으로 해줘", "밝기 50%로 맞춰줘", "밝기 0으로",
              "밝기 100으로 설정해줘", "밝기 30 퍼센트로", "밝기 70"):
        check(f"{t!r} 는 라우터가 받는다", bool(_ROUTER_BRIGHTNESS.search(t)))
    for t in ("밝기 알려줘", "밝기 얼마야", "밝기 몇 퍼센트야", "밝기 올려줘",
              "밝기 내려줘", "밝기 어때", "밝기 50으로 올려줘"):
        check(f"🚨 {t!r} 는 라우터가 **안 받는다**",
              not _ROUTER_BRIGHTNESS.search(t))
    # 🔑 둘이 **같은 꼬리**를 쓴다. 따로 적어 두면 한쪽만 고쳐진다 —
    #    실제로 «볼륨 30 퍼센트로» 가 볼륨에서만 빠져 있었다.
    check("🔑 볼륨과 밝기가 같은 꼬리를 쓴다 (한쪽만 고쳐지지 않게)",
          _ROUTER_BRIGHTNESS.pattern.endswith(_LEVEL_TAIL)
          and _ROUTER_VOLUME.pattern.endswith(_LEVEL_TAIL))
    check("그래서 '볼륨 30 퍼센트로' 도 받는다",
          bool(_ROUTER_VOLUME.search("볼륨 30 퍼센트로")))

    print(f"{NL}=== ⑨ 게이트가 **세 문에 다 걸린다** (소스) ===")
    cache_src = io.open(os.path.join(_ROOT, "core", "command_cache.py"),
                        encoding="utf-8").read()
    port_src = io.open(os.path.join(_ROOT, "core", "portable.py"),
                       encoding="utf-8").read()
    # Stage 1 · Stage 2 · learn — 셋 다. 한 곳만 막으면 다른 입구로 샌다.
    check("찾기 두 단계에 다 걸려 있다",
          cache_src.count("self.query_conflict(normalized") == 2,
          f"→ {cache_src.count('self.query_conflict(normalized')}곳")
    check("학습에도 걸려 있다", "self.query_conflict(key, tool_calls)" in cache_src)
    check("가져오기에도 걸려 있다", "cache.query_conflict(pattern, calls)" in port_src)
    check("🚨 «조회 도구» 화이트리스트다 (조작 도구 목록이 아니다)",
          "_QUERY_SAFE_TOOLS" in cache_src and "_MUTATING_TOOLS" not in cache_src)
    check("mute_get 이 mute 보다 **앞에** 있다",
          cache_src.index('("mute_get"') < cache_src.index('("mute",'))

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
