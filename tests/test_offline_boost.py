"""오프라인 보강 — 삽입어·음소거·앱 사전 (계획 2-4 · 2026-09-24)

    python tests/test_offline_boost.py

## 왜 이 스위트가 있나

[오프라인 커버리지 측정](../docs/research/2026-09_오프라인_커버리지.md) §5 가
2-4 에 세 자리를 그대로 넘겼다. 셋 다 **도구는 이미 있는데 표현이 없는** 자리였다.

| | 무엇 | 뿌리 |
|---|---|---|
| ① | *"화면 밝기 좀 올려줘"* 가 제안까지만 갔다 | 🔑 **삽입어가 트리거를 두 동강 냈다** |
| ② | *"소리 꺼줘"* 가 미스 | 엔티티는 volume 인데 동작이 `close` 로 잡혀 **없는 조합** |
| ③ | *"한글 실행해 줘"* 가 미스 | 앱 사전에 없었다 |

①이 가장 크다. `ACTION_PATTERNS` 의 트리거는 「밝기 올」처럼 **두 어절에 걸친 것**이
많은데 매칭은 공백만 지운 문자열에서 한다 — 사이에 「좀」이 끼면 못 맞힌다.
📌 **이미 알고 있던 결함이다**: `has_uncovered_command` 주석에 실측 오탐으로
*"볼륨 좀 올려줘"* 가 적혀 있었다. 그때는 게이트가 안 막도록 처리했을 뿐이다.

## 🚨 양방향으로 박는다

«삽입어를 무시한다»만 고정하면 **1차 매칭까지 삽입어를 빼는 수정이 통과한다.**
그러면 「지금 시간」처럼 **삽입어를 품은 트리거가 죽는다**(「지금」도 삽입어다).
그래서 «원문으로 먼저 훑는다»를 같이 못 박는다.

## 🔑 ③이 남긴 불변식 — **사전은 짝이 맞아야 한다**

`APP_ENTITIES`(캐시)에만 넣고 `APP_ALIASES`(실행)에 안 넣으면
**캐시는 히트하는데 실행이 실패한다** — 거짓 약속이다. 코드 주석이 경고만 하고
있던 것을 여기서 **검사로** 바꾼다. 다음에 앱을 늘릴 때 한쪽만 넣으면 여기서 깨진다.
"""
import _testenv  # noqa: F401
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["PLUIZ_CACHE_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="pluiz_off_"), "c.json")


def run():
    passed = total = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}"
              + ("" if cond or not detail else f"   → {detail}"))

    from core.command_cache import (CommandCache, APP_ENTITIES,
                                    _strip_fillers_ns, _FILLER_TOKENS)
    c = CommandCache()

    def intent(q):
        return c._extract_intent(c._normalize(q))

    def hit(q):
        r = c.find(q)
        return [t["name"] for t in r[0].tool_calls] if r else None

    # ═══ ① 삽입어가 트리거를 끊지 않는다 ═════════════════════════
    print("=== ① 삽입어(「좀」…)가 두 어절 트리거를 끊지 않는다 ===")
    for q, want in [
        ("화면 밝기 좀 올려줘", ("brightness", "brightness_up")),   # 측정에서 잡힌 그 문장
        ("볼륨 좀 올려줘",     ("volume", "volume_up")),          # 주석에 적혀 있던 실측 오탐
        ("소리 좀 줄여줘",     ("volume", "volume_down")),
        ("밝기 좀 내려줘",     ("brightness", "brightness_down")),
        ("밝기 그냥 올려줘",   ("brightness", "brightness_up")),
        ("볼륨 빨리 내려줘",   ("volume", "volume_down")),
    ]:
        got = intent(q)
        check(f"   {q!r} → {want}", got == want, got)

    check("   실제로 캐시까지 간다 ('화면 밝기 좀 올려줘')",
          hit("화면 밝기 좀 올려줘") == ["brightness_up"],
          hit("화면 밝기 좀 올려줘"))
    check("   실제로 캐시까지 간다 ('볼륨 좀 올려줘')",
          hit("볼륨 좀 올려줘") == ["volume_up"], hit("볼륨 좀 올려줘"))

    # 🔑 조회도 같이 살아난다 — 「밝기 알려」도 두 어절 트리거다
    check("   🔑 조회도 같이 산다 ('밝기 좀 알려줘')",
          intent("밝기 좀 알려줘") == ("brightness", "brightness_get"),
          intent("밝기 좀 알려줘"))

    # ═══ ② 🚨 반대 방향 — 1차는 **원문으로** 훑는다 ═══════════════
    #   「지금」도 삽입어다. 먼저 빼 버리면 「지금 시간」 트리거가 죽는다.
    print("=== ② 🚨 삽입어를 품은 트리거가 죽지 않는다 ===")
    check("🚨 '지금 시간 알려줘' → (time, time)",
          intent("지금 시간 알려줘") == ("time", "time"), intent("지금 시간 알려줘"))
    check("   '지금 몇 시야' 는 그대로 히트",
          hit("지금 몇 시야") == ["get_current_time"], hit("지금 몇 시야"))
    check("   헬퍼는 어절 단위로만 뺀다('지금' 어절만)",
          _strip_fillers_ns("지금 시간 알려줘") == "시간알려줘",
          _strip_fillers_ns("지금 시간 알려줘"))
    check("   어절 안에 든 글자는 안 뺀다('지금요')",
          _strip_fillers_ns("지금요 밝기 올려줘") == "지금요밝기올려줘",
          _strip_fillers_ns("지금요 밝기 올려줘"))
    check("   삽입어가 없으면 원문과 같다",
          _strip_fillers_ns("밝기 올려줘") == "밝기올려줘")

    # 🔑 흡수 규칙(absorb_next)이 안 깨졌다 — 삽입어를 covered 에 미리 넣으면
    #   여기가 깨진다(「해줘」가 잔여 명령으로 읽힌다).
    print("=== ②-b 🔑 뒤에 붙은 삽입어가 동사 흡수를 깨지 않는다 ===")
    for q in ["음소거 해줘 좀 빨리", "스크린샷 좀 찍어줘", "음소거 해줘"]:
        check(f"   {q!r} → 잔여 명령 없음", c.has_uncovered_command(q) is False)

    # ═══ ③ 「소리 꺼줘」 — 없던 조합을 만든다 ══════════════════════
    print("=== ③ '소리 꺼줘' → mute ===")
    for q in ["소리 꺼줘", "볼륨 꺼줘", "소리 꺼 줘", "소리 좀 꺼줘"]:
        check(f"   {q!r} → (volume, mute)", intent(q) == ("volume", "mute"), intent(q))
    check("   실제로 mute 가 나온다", hit("소리 꺼줘") == ["mute"], hit("소리 꺼줘"))

    # ═══ ③-bis 🚨 되돌릴 수 있어야 한다 (2026-09-24 실기) ═════════
    #   실기에서 *"소리 다시 켜 줘"* 가 **갈 곳이 없었다** — 캐시에도 없고 LLM 도 실패.
    #   토글 하나로는 방향을 표현할 수 없어서 도구를 `mute`·`unmute` 로 갈랐다.
    print("=== ③-bis 🚨 음소거를 **되돌릴 수 있다** ===")
    for q in ["소리 다시 켜 줘", "소리 켜줘", "볼륨 켜줘", "음소거 해제해 줘",
              "음소거 풀어줘", "소리 좀 켜줘"]:
        check(f"   {q!r} → unmute", hit(q) == ["unmute"], hit(q))
    # 🚨 「음소거 해제」는 「음소거」를 품고 있다 — 순서가 뒤집히면 **음소거를 건다**
    check("🚨 '음소거 해제해 줘' 가 음소거를 걸지 않는다",
          hit("음소거 해제해 줘") == ["unmute"], hit("음소거 해제해 줘"))

    # 🚨 묻는 말은 토글하지 않는다 — 「음소거됐어?」와 정확히 같은 자리
    print("=== ③-b 🚨 묻는 말이 음소거를 **토글하지 않는다** ===")
    for q in ["소리 꺼졌어", "볼륨 꺼졌어", "소리 껐어"]:
        got = intent(q)
        check(f"   {q!r} → mute_get (토글 아님)",
              got is not None and got[1] == "mute_get", got)

    # 🔑 볼륨 올리기·내리기를 뺏지 않는다 (mute 가 volume_* 보다 뒤에 있어야 한다)
    print("=== ③-c 🔑 볼륨 조작을 뺏지 않는다 ===")
    for q, want in [("소리 줄여줘", "volume_down"), ("소리 올려줘", "volume_up"),
                    ("소리 키워줘", "volume_up"), ("소리 낮춰줘", "volume_down")]:
        got = intent(q)
        check(f"   {q!r} → {want}", got is not None and got[1] == want, got)

    # ═══ ④ 「한글」 앱 ═══════════════════════════════════════════
    print("=== ④ '한글 실행해 줘' → open_app ===")
    for q in ["한글 실행해 줘", "한글 열어줘", "한컴 켜줘"]:
        got = intent(q)
        check(f"   {q!r} → (hwp, open)", got == ("hwp", "open"), got)
    check("   실제로 open_app 이 나온다",
          hit("한글 실행해 줘") == ["open_app"], hit("한글 실행해 줘"))
    # 📌 동작이 없는 말은 잡지 않는다 — 「한글」은 보통명사이기도 하다
    check("📌 '한글로 써줘' 는 intent 가 없다(LLM 으로 간다)",
          intent("한글로 써줘") is None, intent("한글로 써줘"))

    # ═══ ⑤ 🔑 불변식 — 캐시 사전과 실행 사전의 **짝** ═════════════
    #   한쪽만 넣으면 «캐시는 히트하는데 실행이 실패한다» = 거짓 약속.
    print("=== ⑤ 🔑 불변식: 캐시 앱 사전 ⊆ 실행 앱 사전 ===")
    from tools.app_control import APP_ALIASES, APP_PROCESS_MAP
    exec_keys = set(APP_ALIASES.values())
    cache_keys = {key for _, key, _ in APP_ENTITIES}
    missing = sorted(cache_keys - exec_keys)
    check("🚨 캐시가 아는 앱은 실행 사전에도 있다", not missing,
          f"실행 사전에 없는 키: {missing}")
    no_proc = sorted(k for k in cache_keys if k not in APP_PROCESS_MAP)
    check("🚨 캐시가 아는 앱은 프로세스 이름도 있다(종료·확인에 필요)",
          not no_proc, f"APP_PROCESS_MAP 에 없는 키: {no_proc}")

    # ═══ ⑥ 기존 히트가 그대로다 (회귀 방지) ══════════════════════
    print("=== ⑥ 기존 명령이 **여전히** 히트한다 ===")
    for q, want in [("메모장 열어줘", "open_app"), ("메모장 꺼줘", "close_app"),
                    ("볼륨 올려줘", "volume_up"), ("밝기 내려줘", "brightness_down"),
                    ("음소거 해줘", "mute"), ("스크린샷 찍어줘", "take_screenshot"),
                    ("지금 몇 시야", "get_current_time"),
                    ("배터리 얼마나 남았어", "get_battery_status")]:
        got = hit(q)
        check(f"   {q!r} → {want}", got == [want], got)

    # 🚨 게이트가 여전히 막는다 — 지시대명사·부정·격상은 `find()` 안에서 막힌다
    print("=== ⑥-b 🚨 게이트는 여전히 막는다 ===")
    for q in ["그거 꺼 줘", "메모장 말고 계산기 열어줘", "그림판 강제로 꺼 줘"]:
        check(f"   {q!r} → 캐시 포기", hit(q) is None, hit(q))

    # 📌 **복합 게이트는 `find()` 가 아니라 `fast_path` 에 있다.**
    #   캐시는 「메모장 열어줘」를 알고 있으므로 `find()` 만 보면 히트한다 —
    #   그걸 «캐시가 샌다»로 읽지 않도록 판정 함수를 직접 부른다.
    from core.fast_path import is_compound_command
    for q in ["메모장 열고 계산기도 열어줘", "메모장 열고 계산기 열어줘"]:
        check(f"   {q!r} → 복합 게이트가 막는다", is_compound_command(q) is True)
    check("   🔑 평범한 명령은 복합으로 안 본다",
          is_compound_command("화면 밝기 좀 올려줘") is False)

    check("삽입어 집합은 그대로다(다른 곳에서도 쓴다)", "좀" in _FILLER_TOKENS)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
