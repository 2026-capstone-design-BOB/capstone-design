# -*- coding: utf-8 -*-
"""오프라인 커버리지 측정 — «인터넷이 끊기면 무엇이 되나». (계획 1-3)

    python scripts/offline_coverage.py            # 고정 20문장 + 로그 실제 발화
    python scripts/offline_coverage.py --fixed    # 고정 20문장만 (Windows 대조군용)
    python scripts/offline_coverage.py --verbose  # 문장별로 다 본다

## 🚨 **아무것도 실행하지 않는다.** 이게 이 파일의 제일 중요한 성질이다

`resolve_fast_path`는 히트하면 **도구를 진짜로 돌린다** — 앱을 열고 볼륨을 바꾼다.
120문장을 그대로 먹이면 **측정이 아니라 난장판**이 된다.
그래서 여기서는 **판정에 필요한 함수만** 부르고 `execute_sync`는 **절대 안 부른다.**

⚠️ 대신 «판정 경로가 실물과 같은가»가 위험해진다. 그래서 게이트를 **다시 구현하지 않고
`core.fast_path`에서 그대로 import** 한다(`is_compound_command`·`has_uncovered_command`).
라우터도 마찬가지로 **모듈 상수인 정규식**을 그대로 쓴다 — 복제하면 한쪽만 고쳐진다.

## 무엇을 «오프라인에서 된다»로 세는가

[BL-46](../docs/BACKLOG.md) 이후 오프라인 턴은 **LLM을 아예 안 부른다.**
그러므로 오프라인에서 되는 것은 정확히 **`fast_path`가 잡는 것** 뿐이다:

| 단계 | 무엇 |
|---|---|
| ⛔ 게이트 | 복합·부정·다중앱이면 **캐시를 건너뛴다**(BL-02·BL-27) → 오프라인에선 곧 실패 |
| ✅ **캐시** | `(entity, action)` 인텐트 + 유사도 |
| ⛔ BL-15 | 캐시가 문장의 **일부만** 이해했으면 포기한다 |
| ✅ **라우터** | 파라미터형 정규식 9종 (유튜브·지도·폴더·볼륨·최대/최소화) |
| 🟡 **제안** | 위가 다 미스여도 «혹시 이 말씀인가요?»는 할 수 있다(M5 §5-2). **실행은 아니다** |

🔑 **«제안»을 «된다»에 넣지 않는다.** 되묻는 것과 해 주는 것은 다르다.
따로 세고 따로 보고한다.
"""
import argparse
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 고정 20문장 ────────────────────────────────────────────────────
#
# 🚨 **유리하게 고르지 않았다.** 이 저장소가 스스로 «오프라인에선 캐시가 아는 표현만
#   된다»고 적어 뒀으므로([BL-46 문구 수정](../docs/BACKLOG.md)), 표본을 캐시 시드에서
#   고르면 100%가 나온다 — 그건 재는 게 아니라 베끼는 것이다.
#
# 그래서 **여섯 갈래를 미리 정하고 갈래마다 채웠다.** 안 될 것이 뻔한 것(날씨·잡담)도
# 그대로 넣는다. 그게 «차별점 주장»의 정직한 분모다.
# 대부분은 **실제 로그에서 가져왔다**(2026-09-11~14 실사용 발화).
FIXED = [
    # ① 앱 제어 — 캐시가 가장 강한 자리
    ("메모장 켜 줘",                     "앱"),
    ("계산기 열어줘",                    "앱"),
    ("그림판 열어줘",                    "앱"),
    ("한글 실행해 줘",                   "앱"),
    # ② 시스템 — 라우터·캐시가 나눠 맡는다
    ("볼륨 올려줘",                      "시스템"),
    ("볼륨 30으로 맞춰줘",               "시스템"),
    ("소리 꺼줘",                        "시스템"),
    ("화면 밝기 좀 올려줘",              "시스템"),
    # ③ 창 — 라우터 정규식
    ("메모장 최대화해줘",                "창"),
    ("크롬 최소화해줘",                  "창"),
    # ④ 정보 — 로컬에서 답할 수 있는 것 vs 아닌 것
    ("지금 몇 시야",                     "정보(로컬)"),
    ("배터리 얼마나 남았어",             "정보(로컬)"),
    ("지금 켜져 있는 앱 목록 알려줘",    "정보(로컬)"),
    # ⑤ 🚫 인터넷이 필요한 것 — **안 되는 게 정상이다**
    ("오늘 날씨 어때",                   "🚫 온라인"),
    ("유튜브에서 아이유 노래 틀어줘",    "🚫 온라인"),
    ("파이썬 리스트 정렬하는 법 검색해줘", "🚫 온라인"),
    # ⑥ 🚫 맥락·복합·잡담 — LLM이 필요하다
    ("메모장 열고 계산기도 열어줘",      "🚫 복합"),
    ("그거 꺼 줘",                       "🚫 지시대명사"),
    ("오늘 저녁 뭐 먹지",                "🚫 잡담"),
    ("아까 만든 파일 다시 열어줘",       "🚫 맥락"),
]


# 🚨 **«fast_path가 잡는다»와 «오프라인에서 된다»는 다르다.** (2026-09-16에 걸렸다)
#
# 첫 판에서 *"유튜브에서 아이유 노래 틀어줘"* 가 **라우터 히트 → ✅ 된다**로 집계됐다.
# 그런데 `youtube_search`는 **브라우저를 열고 인터넷을 탄다.** 오프라인에서는
# 안 될 뿐 아니라 **«✓ 검색했어요»라고 성공을 보고한다**(감사 G-17과 같은 모양).
#
# 그래서 «fast_path가 잡았는가»와 «그 도구가 망 없이 도는가»를 **따로** 본다.
_NET_TOOLS = frozenset([
    "youtube_search", "web_search", "open_url", "map_search",
    "fetch_web_info", "get_weather", "add_calendar_event", "create_calendar_event",
])
#: 라우터 정규식 중 **네트워크가 필요한** 갈래
_NET_ROUTES = frozenset(["yt", "map_route", "map_simple"])


def _load_cache():
    from core.command_cache import get_cache
    return get_cache()


def _router_hit(text: str) -> str:
    """라우터 정규식 9종 중 어디에 걸리나. 안 걸리면 ''.

    ⚠️ `route_deterministic`을 **부르지 않는다** — 그건 도구를 실제로 실행한다.
       패턴은 모듈 상수라 그대로 쓸 수 있다(복제 아님).
    """
    import core.router as R
    for name in ("_ROUTER_YT", "_ROUTER_MAP_ROUTE", "_ROUTER_MAP_SIMPLE",
                 "_ROUTER_FOLDER", "_ROUTER_VOLUME", "_ROUTER_VOL_UP",
                 "_ROUTER_VOL_DOWN", "_ROUTER_MAXIMIZE", "_ROUTER_MINIMIZE"):
        pat = getattr(R, name, None)
        if pat is not None and pat.search(text.strip()):
            return name.replace("_ROUTER_", "").lower()
    return ""


def classify(text: str, cache) -> tuple[str, str]:
    """(판정, 근거). 판정 ∈ 캐시 · 라우터 · 제안만 · 못함

    ⚠️ `resolve_fast_path`의 **순서를 그대로** 따른다. 게이트 → 캐시 → BL-15 → 라우터.
    """
    from core.fast_path import is_compound_command, has_uncovered_command

    text = (text or "").strip()
    gated = is_compound_command(text)

    if not gated:
        try:
            hit = cache.find(text)
        except Exception:
            hit = None
        if hit and not has_uncovered_command(cache, text):
            names = [c.get("name", "") for c in (getattr(hit[0], "tool_calls", None) or [])]
            pat = getattr(hit[0], "pattern", "?")
            if any(n in _NET_TOOLS for n in names):
                return "온라인필요", f"{pat} → {[n for n in names if n in _NET_TOOLS]}"
            return "캐시", pat
        if hit:
            return "못함", "BL-15 게이트(문장 일부만 이해)"

    r = _router_hit(text)
    if r:
        if r in _NET_ROUTES:
            return "온라인필요", f"라우터 {r} — 망이 필요한 도구다"
        return "라우터", r

    # 🟡 여기부터는 «실행»이 아니라 «되묻기»다. 따로 센다.
    try:
        sug = cache.suggest(text)
    except Exception:
        sug = None
    if sug:
        return "제안만", f"{getattr(sug[0], 'pattern', '?')} (cos={sug[1]:.2f})"
    return "못함", ("게이트(복합·부정·다중앱)" if gated else "미스")


def _log_corpus():
    """로그의 **실사용 발화**(중복 제거). 실제 분모다."""
    from analyze_tool_usage import parse, is_real
    seen, out = set(), []
    logs = os.path.join(_ROOT, "logs")
    for f in sorted(os.listdir(logs)):
        if not f.endswith(".log"):
            continue
        for t in parse(os.path.join(logs, f)):
            if is_real(t) and t["q"] not in seen:
                seen.add(t["q"])
                out.append(t["q"])
    return out


def report(title, rows, verbose=False, by_cat=False):
    print(f"\n── {title} ({len(rows)}문장) " + "─" * max(0, 40 - len(title)))
    c = Counter(r[1] for r in rows)
    ok = c["캐시"] + c["라우터"]
    if verbose:
        mark = {"캐시": "✅", "라우터": "✅", "제안만": "🟡",
                "온라인필요": "🌐", "못함": "⛔"}
        for text, verdict, why, cat in rows:
            print(f"  {mark[verdict]} {verdict:<4} {text[:38]:<40} {why[:36]}")
    print(f"\n  ✅ 오프라인에서 **된다**  : {ok:>3} / {len(rows)}  "
          f"({ok/len(rows)*100:.1f}%)   캐시 {c['캐시']} · 라우터 {c['라우터']}")
    print(f"  🟡 되묻기만 가능         : {c['제안만']:>3}        "
          f"(실행은 못 한다 — «된다»에 안 넣는다)")
    print(f"  🌐 잡히지만 망이 필요    : {c['온라인필요']:>3}        "
          f"🚨 오프라인에서 **성공이라고 답할 위험**")
    print(f"  ⛔ 못한다                : {c['못함']:>3}")
    if by_cat:
        print()
        for cat in dict.fromkeys(r[3] for r in rows):
            sub = [r for r in rows if r[3] == cat]
            n = sum(1 for r in sub if r[1] in ("캐시", "라우터"))
            print(f"    {cat:<14} {n}/{len(sub)}")
    return ok / len(rows) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixed", action="store_true", help="고정 20문장만")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cache = _load_cache()
    print("=" * 66)
    print(" 오프라인 커버리지 (계획 1-3) — 🚨 아무것도 실행하지 않는다")
    print("=" * 66)

    fixed = [(t, *classify(t, cache), cat) for t, cat in FIXED]
    report("고정 20문장", fixed, verbose=True, by_cat=True)

    if not args.fixed:
        corpus = _log_corpus()
        rows = [(t, *classify(t, cache), "로그") for t in corpus]
        report("로그 실제 발화 (2026-09-11~14 · 중복 제거)", rows,
               verbose=args.verbose)
        print("\n  ⚠️ 로그 쪽 분모에는 «그래»·«어»·«음» 같은 **대답·맞장구**가 섞여 있다.")
        print("     명령이 아닌 것까지 분모에 넣은 값이라 **보수적인 숫자**다.")

    print("\n" + "=" * 66)
    print(" 다음: Windows 음성 액세스로 **같은 20문장**을 돌려 대조표를 채운다.")
    print(" → docs/research/2026-09_오프라인_커버리지.md §4 (사람이 해야 한다)")
    print("=" * 66 + "\n")


if __name__ == "__main__":
    main()
