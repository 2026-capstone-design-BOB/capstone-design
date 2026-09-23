"""캐시가 승인 층을 우회하지 않는다 — 격상 게이트 (2026-09-23)

    python tests/test_cache_escalation.py

## 왜 이 스위트가 있나

승인의 경계를 구현한 날 저녁, 실기에서 이렇게 나왔다:

    '그림판 강제로 꺼 줘' | 요청=없음 | 실행=['캐시'] | 사유=캐시 | LLM 0회(캐시)

`force_close_app` 은 **불려 본 적이 없다.** `ACTION_PATTERNS` 의 "close" 에
「꺼 줘」가 있어 그냥 `close_app` 으로 잡혔고, **「강제로」는 캐시가 모르는 낱말**
이었다. 사용자는 두 번 말했고 두 번 다 같은 답을 받았다.

🚨 **문제의 본체는 «캐시가 승인 층을 통째로 우회한다»는 것이다.** 캐시는 `hitl`
노드를 안 지난다(감사 G-03 «빠른 경로에는 그물이 없다»). 그래서 두 가지를 다 막는다:

  ① **센 말인데 약한 도구로 답하는 것** — 게이트로 캐시를 포기시킨다
  ② **캐시가 센 도구를 직접 실행하는 것** — 불변식으로 «캐시에 없다»를 못 박는다

②가 깨지면 ①의 근거도 같이 무너진다(게이트가 «캐시엔 센 도구가 없다»를 전제한다).

## 🚨 양방향으로 박는다

«강제로면 캐시를 포기한다»만 고정하면 **캐시를 통째로 끄는 수정이 통과한다.**
캐시는 이 제품의 차별점이고 오프라인에서는 유일한 경로다(BL-46 — 미스는 LLM 을
못 부른다). 그래서 «평범한 명령은 **여전히** 히트한다»를 같이 못 박는다.
"""
import _testenv  # noqa: F401
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["PLUIZ_CACHE_FILE"] = os.path.join(tempfile.mkdtemp(prefix="pluiz_esc_"), "c.json")


def run():
    passed = total = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}"
              + ("" if cond or not detail else f"   → {detail}"))

    from core.command_cache import CommandCache, LEARNABLE_TOOLS, SEED_DATA
    from core.graph import DANGEROUS_TOOLS
    c = CommandCache()

    def hit(q):
        r = c.find(q)
        return [t["name"] for t in r[0].tool_calls] if r else None

    # ═══ ① 실기에서 샌 그 발화 ════════════════════════════════════
    print("=== ① 2026-09-23 실기에서 샌 발화 ===")
    check("🚨 '그림판 강제로 꺼 줘' → 캐시를 포기한다", hit("그림판 강제로 꺼 줘") is None,
          hit("그림판 강제로 꺼 줘"))
    check("   같은 말을 두 번 해도 같다(캐시가 안 굳는다)",
          hit("그림판 강제로 꺼 줘") is None)
    for q in ["메모장 억지로 종료해줘", "계산기 그냥 꺼줘", "a.txt 덮어써 줘",
              "메모 덮어쓰고 저장해줘", "무시하고 지워줘"]:
        check(f"   {q!r} → 캐시 포기", hit(q) is None, hit(q))

    # ═══ ② 🔑 반대 방향 — 평범한 명령은 여전히 히트한다 ════════════
    #   캐시를 통째로 끄는 수정이 여기서 깨진다. 오프라인에서는 캐시가 유일한
    #   경로라 «느려질 뿐»이 성립하지 않는다(BL-46).
    print("=== ② 🔑 평범한 명령은 **여전히** 캐시가 잡는다 ===")
    for q, want in [("메모장 꺼줘", "close_app"), ("그림판 꺼 줘", "close_app"),
                    ("메모장 열어줘", "open_app"), ("볼륨 올려줘", "volume_up"),
                    ("밝기 내려줘", "brightness_down"), ("지금 몇 시야", "get_current_time")]:
        got = hit(q)
        check(f"   {q!r} → {want}", got == [want], got)

    # 🔑 «강제»가 **다른 뜻으로** 들어간 말까지 막지는 않는지 — 지금은 막는다.
    #   막는 쪽이 안전하고(LLM 왕복 2.5초), 이 낱말이 평범한 명령에 들어갈 일이
    #   거의 없다. ⚠️ 여기가 시끄러워지면 그때 좁힌다 — **지금 좁히지 않는다.**
    check("   (참고) «강제»가 든 말은 무조건 포기한다 — 지금은 이게 맞다",
          hit("강제 종료 어떻게 해") is None)

    # ═══ ③ 불변식 — 캐시에 승인 대상 도구가 **없다** ═══════════════
    print("=== ③ 🚨 캐시는 승인 대상 도구를 갖지 않는다 ===")
    #   캐시는 hitl 노드를 안 지난다. 하나라도 새면 **승인 없이 실행**된다.
    overlap = sorted(DANGEROUS_TOOLS & set(LEARNABLE_TOOLS))
    check("학습 화이트리스트에 승인 대상이 없다", not overlap, overlap)

    seed_tools = {t.get("name") for _p, calls, _r in SEED_DATA for t in calls}
    seed_bad = sorted(DANGEROUS_TOOLS & seed_tools)
    check("시드에도 승인 대상이 없다", not seed_bad, seed_bad)

    live = {t.get("name") for e in c._cache.values() for t in (e.tool_calls or [])}
    live_bad = sorted(DANGEROUS_TOOLS & live)
    check("지금 캐시에 올라와 있는 것에도 없다", not live_bad, live_bad)

    # ═══ ④ 학습이 격상 표현을 굳히지 않는다 ═══════════════════════
    #   굳으면 그 말이 **영영 LLM 에 안 간다 = 영영 승인 노드에도 안 간다.**
    print("=== ④ 격상 표현은 학습되지 않는다 ===")
    before = len(c._cache)
    c.save("그림판 강제로 꺼줘", [{"name": "close_app", "args": {"app": "그림판"}}],
           "✓ 그림판을 종료했어요.")
    check("🚨 '강제로' 가 든 말은 **안 굳는다**", len(c._cache) == before,
          f"{before} → {len(c._cache)}")

    # 🔑 반대 방향 — 평범한 말은 여전히 학습된다(캐시의 존재 이유다)
    c.save("그림판 켜줘", [{"name": "open_app", "args": {"app": "그림판"}}],
           "✓ 그림판을 실행했어요.")
    check("🔑 평범한 말은 **여전히** 학습된다", len(c._cache) > before,
          f"{before} → {len(c._cache)}")

    # ═══ ⑤ 판정 함수 자체 ════════════════════════════════════════
    print("=== ⑤ 판정 함수 (has_escalation_marker) ===")
    check("'강제로' 를 본다", c.has_escalation_marker("그림판 강제로 꺼줘"))
    check("띄어쓰기가 달라도 본다", c.has_escalation_marker("그 림 판 강 제 로 꺼줘") is False
          or c.has_escalation_marker("그림판 강제 로 꺼줘"))
    check("🔑 평범한 말에는 **안** 걸린다", not c.has_escalation_marker("그림판 꺼줘"))
    check("🔑 '강하게' 같은 다른 말에는 안 걸린다",
          not c.has_escalation_marker("소리 강하게 올려줘"))
    check("도구가 없으면 판정하지 않는다", c.escalation_conflict("강제로 꺼줘", []) is False)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
