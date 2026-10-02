# -*- coding: utf-8 -*-
"""**대상이 빈 말이 특정 앱으로 굳지 않는다** — 대상 게이트 ([BL-63](../docs/BACKLOG.md))

실행: python tests/test_bl63_target_gate.py

## 무슨 일이 있었나 (2026-09-20 3차 리허설)

캐시에 이게 박혔다:

    '그냥 닫아줘'  →  close_app(app='설정')

그 뒤로는 **무엇을 보고 있든 「그냥 닫아줘」가 설정을 닫는다.** 캐시는 맥락을 안 본다.

「그냥」은 **지시어가 아니라서** [BL-50](../docs/BACKLOG.md) 게이트를 그냥 지났고,
「닫아」가 action 이라 L1 도, 5글자라 L2 도, 대조가 없어 L3 도 통과했다.

## 🚨 같은 모양이 세 번째였다

| | 발화 | 막은 방법 | 다음에 샌 것 |
|---|---|---|---|
| BL-27 | `'그래'` | 글자수·어휘 목록 | `'그거 꺼줘'` |
| BL-50 | `'그거 꺼줘'` | 지시대명사 **토큰 목록** | `'그냥 닫아줘'` |
| BL-63 | `'그냥 닫아줘'` | ← 여기서 **축을 바꿨다** | — |

**셋 다 «토큰 목록»으로 막았고 셋 다 다음 표현이 샜다.** 「그냥」을 목록에 더하면
다음은 「이제 닫아줘」이고 그 다음은 「됐어 닫아줘」다. 그래서 목록을 안 늘렸다.

## 여기서 고정하는 것

| | 왜 |
|---|---|
| 축은 «지시어가 있나»가 **아니다** | **«대상이 있어야 하는 도구인데 발화가 그 대상을 말했나»** 다. 「그냥 닫아줘」가 위험한 이유는 「그냥」이 아니라 **무엇을 닫는지가 비어서**다 |
| 🔑 **지시어 목록에 없는 표현도 같이 막힌다** | 이게 앞의 둘과 갈리는 자리다. 「닫아줘」·「이제 닫아줘」·「좀 꺼줘」는 지시대명사가 하나도 없는데 같이 막힌다 — 판정이 «대상 자리가 비었나»라서다 |
| 🔴 **사용자 자신의 낱말은 살린다** | `'노트 띄워줘'` → `open_app(메모장)` 은 **학습돼야 맞다**. 캐시 어휘에 있는 엔티티를 요구하면 게이트가 아니라 **기능 삭제**가 된다([BL-65](../docs/BACKLOG.md)) |
| ⚠ **남는 오차를 적어 둔다** | 표에 없는 삽입어(「일단」)는 대상 이름으로 읽힌다 — 「노트」와 구별할 길이 없다. 가르려고 목록을 늘리면 **네 번째로 같은 길**을 걷는다 |
| 도구 **이름**이 아니라 **인자**를 본다 | `close_app(app='설정')` 은 자기가 무엇에 매여 있는지 스스로 말한다. 대상 인자가 없는 도구는 게이트에 **닿지도 않는다** → 도구가 늘어도 고칠 곳이 없다 |
| 🔴 `web_search`·`open_url` 은 **안 본다** | 「날씨 검색해줘」의 「날씨」는 캐시 엔티티 표에 없다. 그것까지 «대상»으로 보면 **멀쩡한 시드가 죽는다** |
| **양방향으로 센다** | «대상이 있는 명령은 그대로 돈다»를 같이 박는다. 없으면 **전부 막는 수정**이 통과한다(BL-64에서 배운 모양) |
| 네 문에 **다 걸린다** | 찾기 두 단계 · 학습 · 제안 · 가져오기. 한 곳만 막으면 다른 입구로 샌다(BL-27·BL-50·BL-60이 같은 값을 치렀다) |

🚨 **이 테스트는 앱을 열거나 닫지 않는다.** 캐시 판정만 본다.
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


def plant(c, pattern, calls):
    """게이트를 **우회해** «과거에 학습된» 상태를 그대로 만든다."""
    import core.command_cache as M
    c._cache[pattern] = M.CacheEntry(
        pattern=pattern, tool_calls=calls, response_template="OK",
        hit_count=1, is_seed=False, source="dynamic")
    c._build_intent_index()


def run():
    c = fresh_cache()
    POISON = [{"name": "close_app", "args": {"app": "설정"}}]

    print("=== ① 재현 — 라이브에서 박혔던 바로 그 줄 ===")
    check("'그냥 닫아줘' 는 **학습되지 않는다**",
          c.learn("그냥 닫아줘", POISON) is False)
    check("그래서 캐시에 없다", "그냥 닫아줘" not in c._cache)
    # 🚨 학습만 막으면 절반이다 — 이미 박힌 것·가져온 것이 그대로 돈다.
    plant(c, "그냥 닫아줘", POISON)
    check("🚨 박혀 있어도 **읽을 때 막힌다**", c.find("그냥 닫아줘") is None,
          f"→ {names_of(c.find('그냥 닫아줘'))}")
    check("걷어내면 목록에 사유가 남는다",
          any(k == "그냥 닫아줘" and "L7" in why
              for k, why in c.prune_unlearnable_dynamic(dry_run=True)))
    c.prune_unlearnable_dynamic()
    check("prune 이 실제로 지운다", "그냥 닫아줘" not in c._cache)

    print(f"{NL}=== ② 🔑 **지시어 목록에 없는 표현도 같이 막힌다** (축이 낱말이 아니다) ===")
    # 여기가 BL-27·BL-50 과 갈리는 자리다. 아래 어느 말도 **지시대명사 목록에 없다** —
    # 그런데 같이 막힌다. 판정이 «어떤 낱말인가»가 아니라 «대상 자리가 비었나»라서다.
    for s in ["닫아줘", "꺼줘", "종료해줘",
              "이제 닫아줘", "지금 꺼줘", "다시 닫아줘",
              "좀 닫아줘", "빨리 꺼줘", "제발 종료해줘", "그냥 좀 닫아줘"]:
        c2 = fresh_cache()
        learned = c2.learn(s, POISON)
        plant(c2, s, POISON)
        check(f"{s!r} → 학습도 히트도 안 된다",
              learned is False and c2.find(s) is None,
              f"→ learn={learned} find={names_of(c2.find(s))}")
    check("🔑 그런데 이 중 어느 것도 지시대명사가 아니다",
          not any(c.has_deixis(s) for s in
                  ["그냥 닫아줘", "이제 닫아줘", "좀 닫아줘", "빨리 꺼줘"]))

    print(f"{NL}=== ②-b ⚠ **남는 오차를 숨기지 않는다** ===")
    # 표에 없는 삽입어(「일단」)는 **대상 이름으로 읽힌다** — `'노트 띄워줘'` 의
    # 「노트」와 구별할 방법이 없기 때문이다(둘 다 캐시가 모르는 낱말이다).
    # 🔑 **여기를 가르려고 목록을 늘리면 BL-27·BL-50 이 걸어간 길을 네 번째로 걷는다.**
    #   그래서 고치지 않고 **적어 둔다** — 이 줄이 깨지면 누군가 목록을 늘린 것이다.
    c2 = fresh_cache()
    check("⚠ '일단 꺼줘' 는 통과한다 (모르는 낱말이 대상 자리에 있다)",
          not c2.target_conflict("일단 꺼줘", POISON))
    check("🔑 그 대신 **아는 대상**을 말하면 ②가 본다",
          c2.target_conflict("일단 크롬 꺼줘", POISON))

    print(f"{NL}=== ③ 🔴 **양방향** — 대상이 있는 명령은 그대로 돈다 ===")
    c = fresh_cache()
    for s, want in [("메모장 열어줘", "open_app"), ("메모장 꺼줘", "close_app"),
                    ("크롬 열어줘", "open_app"), ("카톡 꺼줘", "close_app"),
                    ("파일 탐색기 열어줘", "open_app"), ("설정 열어줘", "open_app"),
                    ("그림판 닫아줘", "close_app"), ("계산기 종료해줘", "close_app")]:
        check(f"{s!r} → {want}", want in names_of(c.find(s)),
              f"→ {names_of(c.find(s))}")
    check("'메모장 그냥 닫아줘' 도 돈다 (「그냥」이 죄가 아니다)",
          "close_app" in names_of(c.find("메모장 그냥 닫아줘")),
          f"→ {names_of(c.find('메모장 그냥 닫아줘'))}")
    check("대상이 있으면 **학습된다**",
          fresh_cache().learn("메모장 띄워봐",
                              [{"name": "open_app", "args": {"app": "메모장"}}]) is True)

    print(f"{NL}=== ④ 대상 인자가 없는 도구는 게이트에 **닿지 않는다** ===")
    # 🔑 `volume_up`·`maximize_window` 는 «무엇을»이 없는 것이 정상이다.
    #    도구 이름 목록으로 만들었다면 여기를 매번 손봐야 했다.
    c = fresh_cache()
    for s, want in [("볼륨 올려줘", "volume_up"), ("소리 내려줘", "volume_down"),
                    ("음소거해줘", "mute"), ("밝기 올려줘", "brightness_up"),
                    ("스크린샷 찍어줘", "take_screenshot"),
                    ("바탕화면 보여줘", "show_desktop"),
                    ("지금 몇 시야", "get_current_time"),
                    ("밝기 알려줘", "get_brightness"),
                    ("최근에 열었던 파일 보여줘", "open_recent_file")]:
        check(f"{s!r} → {want}", want in names_of(c.find(s)),
              f"→ {names_of(c.find(s))}")
    check("'최대화 해줘' 는 **학습된다** (대상이 없는 것이 정상이다)",
          fresh_cache().learn("최대화 해줘",
                              [{"name": "maximize_window", "args": {}}]) is True)

    print(f"{NL}=== ⑤ 🔴 `web_search`·`open_url` 은 **일부러 안 본다** ===")
    # 「날씨」는 캐시 엔티티 표에 없다. 그것까지 «대상»으로 보면 멀쩡한 시드가
    # 죽는다 — 여기서 막고 싶은 것은 «되돌릴 수 없는 대상 지목»(열기·닫기)이다.
    c = fresh_cache()
    check("'날씨 검색해줘' 가 살아 있다", "web_search" in names_of(c.find("날씨 검색해줘")),
          f"→ {names_of(c.find('날씨 검색해줘'))}")
    check("'유튜브 열어줘' 가 살아 있다", "open_url" in names_of(c.find("유튜브 열어줘")),
          f"→ {names_of(c.find('유튜브 열어줘'))}")
    check("'네이버 열어줘' 가 살아 있다", "open_url" in names_of(c.find("네이버 열어줘")),
          f"→ {names_of(c.find('네이버 열어줘'))}")

    print(f"{NL}=== ⑥ ② **다른 대상**을 말한 것도 막는다 ===")
    # Stage 2 는 대상을 **안 보고** 줄을 세운다 — BL-60 이 「알」↔「올」 한 글자에서
    # 샌 것과 같은 자리다. 유사도가 높다는 것이 «같은 앱»을 뜻하지 않는다.
    c = fresh_cache()
    check("'크롬 닫아줘' ↔ close_app(메모장) 은 **짝이 아니다**",
          c.target_conflict("크롬 닫아줘",
                            [{"name": "close_app", "args": {"app": "메모장"}}]))
    check("'크롬 닫아줘' ↔ close_app(크롬) 은 짝이 맞다",
          not c.target_conflict("크롬 닫아줘",
                                [{"name": "close_app", "args": {"app": "크롬"}}]))
    check("표현이 달라도 같은 앱이면 통과한다 ('카톡' ↔ '카카오톡')",
          not c.target_conflict("카톡 꺼줘",
                                [{"name": "close_app", "args": {"app": "카카오톡"}}]))

    print(f"{NL}=== ⑦ ⚠ 대상 값이 **안 풀리면** ①만 본다 ===")
    # 시드·학습분에 영문 키가 박혀 있다(`app='settings'`·`app='notepad'`).
    # 모르는 것을 «틀렸다»고 하면 **멀쩡한 시드를 죽이는** 방향이다.
    c = fresh_cache()
    check("'메모장 띄워봐' ↔ open_app('notepad') 은 통과한다",
          not c.target_conflict("메모장 띄워봐",
                                [{"name": "open_app", "args": {"app": "notepad"}}]))
    check("'설정 열어줘' ↔ open_app('settings') 은 통과한다",
          not c.target_conflict("설정 열어줘",
                                [{"name": "open_app", "args": {"app": "settings"}}]))
    check("그래도 대상이 **비면** 막는다",
          c.target_conflict("그냥 닫아줘",
                            [{"name": "close_app", "args": {"app": "settings"}}]))

    print(f"{NL}=== ⑧ 게이트가 **네 문에 다 걸린다** (소스) ===")
    cache_src = io.open(os.path.join(_ROOT, "core", "command_cache.py"),
                        encoding="utf-8").read()
    port_src = io.open(os.path.join(_ROOT, "core", "portable.py"),
                       encoding="utf-8").read()
    check("찾기 두 단계에 다 걸려 있다",
          cache_src.count("self.target_conflict(normalized") == 2,
          f"→ {cache_src.count('self.target_conflict(normalized')}곳")
    check("학습에도 걸려 있다", "self.target_conflict(key, tool_calls)" in cache_src)
    check("제안에도 걸려 있다",
          "self.target_conflict(text, entries[i].tool_calls)" in cache_src)
    check("가져오기에도 걸려 있다", "cache.target_conflict(pattern, calls)" in port_src)
    check("이미 박힌 것도 걷힌다 (prune)",
          "self.target_conflict(key, entry.tool_calls)" in cache_src)
    check("🔑 도구 **이름 목록**이 아니라 **인자**를 본다",
          "_TARGET_ARG_KEYS" in cache_src and "_TARGETED_TOOLS" not in cache_src)
    check("⚠ `query`·`url` 은 대상으로 보지 않는다",
          '_TARGET_ARG_KEYS = ("app", "window")' in cache_src)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
