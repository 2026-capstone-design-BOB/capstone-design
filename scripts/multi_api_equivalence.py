# -*- coding: utf-8 -*-
"""멀티 API 동등성 측정 — «provider를 바꿔도 같게 도는가». (계획 2-3)

    python scripts/multi_api_equivalence.py                  # 키가 있는 provider 전부
    python scripts/multi_api_equivalence.py --providers gemini
    python scripts/multi_api_equivalence.py --report         # 안 재고 저장된 결과만 표로
    python scripts/multi_api_equivalence.py --verbose        # 문장별로 다 본다

## 🚨 **아무것도 실행하지 않는다.** `offline_coverage.py`와 같은 성질이다

`bind_tools(...).invoke(...)` 는 **모델이 무엇을 부르겠다고 했는지**만 돌려준다.
여기서는 그 `tool_calls` 를 읽을 뿐 **도구를 실행하지 않는다.** 20문장에는
`delete_file`·`create_file` 처럼 승인이 필요한 것도 들어 있는데, 실행하지 않으므로
파일이 지워지거나 앱이 켜지지 않는다.

## 무엇을 «동등하다»로 세는가

| 지표 | 뜻 | 누가 정하나 |
|---|---|---|
| **3사 일치율** | 같은 문장에 **세 provider가 같은 도구 묶음**을 골랐나 | 아무도 — 서로 비교할 뿐 |
| 기대 도구 일치율 | 내가 적어 둔 «이게 맞다»와 같나 | 🚨 **내가 라벨을 붙였다** |
| 인자 일치 | 도구가 같을 때 **인자까지** 같나 | 아무도 |
| 지연 · 토큰 | 한 번 호출에 걸린 시간과 토큰 | 측정값 |

🔑 **주 지표는 «3사 일치율»이다.** *"특정 API에 종속되지 않는다"* 가 요구하는 것은
«내 정답과 맞다»가 아니라 **«바꿔 끼워도 같게 돈다»** 이기 때문이다.
기대 도구는 참고로만 같이 싣는다 — 셋이 **똑같이** 틀릴 수도 있어서다.

## 결과는 합쳐서 쌓인다

`--providers` 로 한 곳만 재도 `research/2026-09_멀티API.json` 의 나머지 열은 남는다.
키가 나중에 생기는 provider를 **그때 채워 넣기 위해서**다.
"""
import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT = os.path.join(_ROOT, "docs", "research", "2026-09_멀티API.json")

PROVIDERS = ("gemini", "claude", "openai")


# ── 20문장 ────────────────────────────────────────────────────────
#
# 🚨 **오프라인 측정(`offline_coverage.py`)의 20문장을 그대로 쓰지 않았다.**
#   그쪽은 «망이 끊기면 뭐가 되나»를 재려고 고른 표본이라 **파일 조작이 한 건도 없다**.
#   도구 47개 중 앱·시스템에만 몰려 있어 «provider를 바꿔도 같나»의 분모로는 좁다.
#
# 그래서 여기서는 **도구 표면을 갈래별로 덮도록** 다시 골랐다. 갈래를 먼저 정하고
# 갈래마다 채웠고, 안 될 것이 뻔한 것(잡담)도 그대로 넣는다.
# 🔑 **어려운 것을 일부러 남겨 뒀다** — 실기가 잡았던 셋이 들어 있다:
#   ③ «강제로» (캐시가 삼켰던 것) · ⑩ 소리 나는 대로 부른 파일명(D-01a) ·
#   ⑭ target 없는 입력(BL-12).
#
# `expect` 는 **내가 붙인 라벨**이다. 보조 지표로만 쓴다(위 표 참조).
#
# 📌 **2026-09-28 — 문장 자체는 `tool_eval_cases.py` 로 옮겼다.** 여기 그대로 두면
#   표가 두 곳이 되고, 이 저장소가 반복해서 데인 결함이 정확히 그 모양이다
#   («한 사실은 한 문서에만» — 한쪽만 갱신된다). 🔒 **스무 줄과 그 순서는 안 바뀌었다** —
#   `2026-09_멀티API.json` 이 결과를 인덱스로 맞춰 놓아서 순서가 계약이다.
#   `tests/test_tool_eval_cases.py` ④가 글자까지 지킨다.
from tool_eval_cases import MULTI_CASES as CASES  # noqa: E402

#: 인자까지 비교할 때 **무시하는** 키. provider마다 기본값을 채우는 습관이 달라
#: 그대로 비교하면 «도구는 같은데 인자가 다르다»가 과하게 잡힌다.
_ARG_IGNORE = frozenset(["new"])

#: 1M 토큰당 단가 (USD). 🚨 **확인한 것만 적는다.**
#:   claude — 번들 레퍼런스(claude-api 스킬, 2026-06-24 캐시) 확인값.
#:   gemini · openai — **미확인이라 비워 둔다.** 벤더 가격 페이지를 보고 채운다.
#:   여기 숫자를 지어내면 «특정 API에 종속되지 않는다»의 근거가 아니라 거짓말이 된다.
PRICING = {
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
    "claude-haiku-4-5":          {"in": 1.00, "out": 5.00},
}


# ── 측정 ──────────────────────────────────────────────────────────
def _available(provider: str) -> str:
    """이 provider로 잴 수 있나. 못 재면 **이유**를 문자열로 돌려준다."""
    from config.settings import get_settings
    s = get_settings()
    if not {"gemini": s.gemini_api_key,
            "claude": s.claude_api_key,
            "openai": s.openai_api_key}[provider].strip():
        return "API 키 없음(.env)"
    pkg = {"gemini": "langchain_google_genai",
           "claude": "langchain_anthropic",
           "openai": "langchain_openai"}[provider]
    try:
        __import__(pkg)
    except ImportError:
        return f"패키지 없음({pkg})"
    return ""


def _bind(provider: str):
    """그 provider의 LLM에 **실물과 같은 도구 전부**를 묶어 돌려준다."""
    from config.settings import get_settings
    from core.llm import build_llm
    from core.tool_registry import get_all_tools

    settings = get_settings().model_copy(update={"llm_provider": provider})
    llm = build_llm(settings)
    return llm.bind_tools(get_all_tools()), settings.active_model


def _ask(bound, text: str) -> dict:
    """한 문장을 물어보고 **무엇을 부르겠다고 했는지**만 읽는다. 실행하지 않는다."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from core.graph import build_system_prompt

    msgs = [SystemMessage(content=build_system_prompt()), HumanMessage(content=text)]
    t0 = time.perf_counter()
    resp = bound.invoke(msgs)
    ms = int((time.perf_counter() - t0) * 1000)

    calls = getattr(resp, "tool_calls", None) or []
    usage = getattr(resp, "usage_metadata", None) or {}
    # 🚨 **도구를 안 불렀을 때 무엇을 말했는지까지 남긴다**(2026-09-28 신설).
    #   «도구 없음»에는 성질이 다른 둘이 섞여 있다 — **되묻는 것**(인자가 모자라면
    #   옳은 행동이다)과 **안 했는데 했다고 말하는 것**(BL-12·15·61 계열의 결함).
    #   글을 안 남기면 표에서 둘이 똑같이 «x» 로 보이고, 그러면 자가 **진짜 결함과
    #   내 라벨 실수를 구별하지 못한다.** 실제로 2026-09-28 첫 측정의 «틀린 4건» 중
    #   셋이 이것 때문에 판정 불가였다.
    #   📌 열을 **더하기만** 했다 — 멀티 API JSON 은 인덱스로 맞춰 놓은 계약이라
    #      기존 열을 건드리면 옛 결과가 어긋난다.
    say = getattr(resp, "content", "")
    if isinstance(say, list):                       # provider 마다 블록 리스트로 온다
        say = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in say)
    return {
        "tools": sorted(c.get("name", "") for c in calls),
        "say": (say or "").strip()[:300],
        "args": {c.get("name", ""): {k: v for k, v in (c.get("args") or {}).items()
                                     if k not in _ARG_IGNORE}
                 for c in calls},
        "ms": ms,
        "in": usage.get("input_tokens", 0),
        "out": usage.get("output_tokens", 0),
    }


def measure(provider: str, verbose: bool = False) -> dict:
    bound, model = _bind(provider)
    rows = []
    for i, (text, expect, cat) in enumerate(CASES, 1):
        try:
            r = _ask(bound, text)
            r["error"] = ""
        except Exception as e:                      # 한 문장이 실패해도 나머지는 잰다
            r = {"tools": [], "say": "", "args": {}, "ms": 0, "in": 0, "out": 0,
                 "error": f"{type(e).__name__}: {e}"[:200]}
        r["text"] = text
        rows.append(r)
        if verbose:
            mark = "!" if r["error"] else ("=" if r["tools"] == ([expect] if expect else []) else "x")
            print(f"  {mark} [{i:2}] {text[:26]:<28} → {','.join(r['tools']) or '(없음)'}"
                  f"  {r['ms']}ms  in={r['in']} out={r['out']}")
        else:
            print(".", end="", flush=True)
    if not verbose:
        print()
    return {"model": model, "rows": rows}


# ── 집계 ──────────────────────────────────────────────────────────
def _load() -> dict:
    if os.path.exists(_OUT):
        with open(_OUT, encoding="utf-8") as f:
            return json.load(f)
    return {"cases": [c[0] for c in CASES], "results": {}}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _cost(model: str, tin: int, tout: int):
    p = PRICING.get(model)
    if not p:
        return None
    return (tin * p["in"] + tout * p["out"]) / 1_000_000


def report(data: dict) -> None:
    results = data.get("results", {})
    have = [p for p in PROVIDERS if p in results]
    if not have:
        print("아직 잰 provider가 없습니다.")
        return

    print("\n" + "=" * 72)
    # 도구 개수는 **세어서** 적는다 — 손으로 적어 두면 도구가 늘 때마다 낡는다
    try:
        from core.tool_registry import get_all_tools
        n_tools = f"도구 {len(get_all_tools())}개"
    except Exception:                                   # noqa: BLE001
        n_tools = "도구"
    print(f"멀티 API 동등성 (계획 2-3)  —  같은 20문장 · {n_tools} · 실행 없음")
    print("=" * 72)

    # ── ① provider별 요약
    print(f"\n{'provider':<9} {'모델':<28} {'기대일치':>8} {'지연중앙':>9} {'입력':>7} {'출력':>6} {'비용':>10}")
    print("-" * 82)
    for p in have:
        rows = results[p]["rows"]
        ok = sum(1 for r, (_, e, _c) in zip(rows, CASES)
                 if not r["error"] and r["tools"] == ([e] if e else []))
        lat = [r["ms"] for r in rows if not r["error"]]
        tin = sum(r["in"] for r in rows)
        tout = sum(r["out"] for r in rows)
        c = _cost(results[p]["model"], tin, tout)
        cs = f"${c:.4f}" if c is not None else "미확인"
        med = int(statistics.median(lat)) if lat else 0
        print(f"{p:<9} {results[p]['model']:<28} {ok:>5}/{len(CASES)} "
              f"{med:>8}ms {tin:>7} {tout:>6} {cs:>10}")

    errs = [(p, r) for p in have for r in results[p]["rows"] if r["error"]]
    if errs:
        print(f"\n🚨 호출 실패 {len(errs)}건 — 위 숫자의 분모에서 빠져 있다")
        for p, r in errs[:5]:
            print(f"   {p}: {r['text'][:24]} — {r['error'][:60]}")

    # ── ② 주 지표: 3사 일치율
    if len(have) >= 2:
        same_tool = same_args = comparable = 0
        diffs = []
        for i, (text, expect, _cat) in enumerate(CASES):
            rs = [results[p]["rows"][i] for p in have]
            if any(r["error"] for r in rs):
                continue
            comparable += 1
            if all(r["tools"] == rs[0]["tools"] for r in rs):
                same_tool += 1
                if all(r["args"] == rs[0]["args"] for r in rs):
                    same_args += 1
                else:
                    diffs.append((text, "인자", [f"{p}:{rs[j]['args']}" for j, p in enumerate(have)]))
            else:
                diffs.append((text, "도구", [f"{p}:{','.join(rs[j]['tools']) or '(없음)'}"
                                             for j, p in enumerate(have)]))

        label = "·".join(have)
        print(f"\n▣ 주 지표 — {label} 일치 ({comparable}문장 비교 가능)")
        if comparable:
            print(f"   도구까지 같다  {same_tool}/{comparable} ({same_tool/comparable*100:.1f}%)")
            print(f"   인자까지 같다  {same_args}/{comparable} ({same_args/comparable*100:.1f}%)")
        if diffs:
            print(f"\n   갈린 {len(diffs)}건:")
            for text, kind, detail in diffs:
                print(f"   · [{kind}] {text}")
                for d in detail:
                    print(f"       {d}")
    else:
        print(f"\n▣ 주 지표(3사 일치율)는 **2곳 이상 재야 나온다.** 지금은 {have[0]} 하나뿐이다.")

    # ── ③ 기대 도구와 갈린 것 (보조)
    print("\n▣ 보조 — 내가 적어 둔 기대 도구와 갈린 것")
    any_miss = False
    for i, (text, expect, _cat) in enumerate(CASES):
        for p in have:
            r = results[p]["rows"][i]
            if r["error"]:
                continue
            if r["tools"] != ([expect] if expect else []):
                any_miss = True
                print(f"   {p:<7} {text[:26]:<28} 기대={expect or '(없음)'} "
                      f"→ {','.join(r['tools']) or '(없음)'}")
    if not any_miss:
        print("   없음")

    missing = [p for p in PROVIDERS if p not in results]
    if missing:
        print(f"\n⏸️ 아직 못 잰 provider: {', '.join(missing)}")
        for p in missing:
            print(f"   {p}: {_available(p) or '잴 수 있다 — 아직 안 돌렸다'}")

    print(f"\n원본: {os.path.relpath(_OUT, _ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="멀티 API 동등성 측정 (계획 2-3)")
    ap.add_argument("--providers", nargs="*", choices=PROVIDERS,
                    help="생략하면 키가 있는 곳 전부")
    ap.add_argument("--report", action="store_true", help="안 재고 저장된 결과만 표로")
    ap.add_argument("--verbose", action="store_true", help="문장별로 다 본다")
    args = ap.parse_args()

    data = _load()

    if not args.report:
        targets = args.providers if args.providers else list(PROVIDERS)
        ran = 0
        for p in targets:
            why = _available(p)
            if why:
                print(f"⏭️ {p} 건너뜀 — {why}")
                continue
            print(f"▶ {p} 측정 중 ({len(CASES)}문장) …")
            data.setdefault("results", {})[p] = measure(p, verbose=args.verbose)
            _save(data)
            ran += 1
        if not ran:
            print("\n🚨 잴 수 있는 provider가 하나도 없습니다.")

    report(data)


if __name__ == "__main__":
    main()
