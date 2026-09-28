# -*- coding: utf-8 -*-
"""도구 선택 정확도 — «**새로 만든 도구가 실제로 불리나**» ([BL-71](../docs/BACKLOG.md))

    conda activate pluiz
    python scripts/eval_tool_selection.py                 # 키가 있는 provider 전부
    python scripts/eval_tool_selection.py --providers gemini
    python scripts/eval_tool_selection.py --new           # 새 도구 20개만
    python scripts/eval_tool_selection.py --report        # 안 재고 저장된 결과만
    python scripts/eval_tool_selection.py --verbose       # 문장별로 다 본다

## 이 스크립트가 답하는 질문 — 멀티 API 표와 **다른 질문**이다

[멀티 API 표](../docs/research/2026-09_멀티API.md)는 *«provider를 바꿔도 같게 도는가»*
를 묻고, 그래서 주 지표가 **3사 일치율**이다(내 라벨은 보조).

여기는 정반대다. *«내가 만든 도구가 내가 의도한 자리에서 불리는가»* 를 묻고,
그래서 **내 라벨이 주 지표다.** 🚨 그 말은 **이 숫자가 내 라벨만큼만 믿을 만하다**는
뜻이다 — 보고서 머리에 매번 그 문장을 찍는 이유다.

이 질문이 필요한 이유는 [구조 점검 §5](../docs/research/2026-09_구조점검.md)가
*«토큰도 지연도 아니고 **선택 정확도**가 진짜 제약»* 이라고 결론지었는데,
정작 그 축을 안 늘린 채로 도구만 47 → 67 로 늘렸기 때문이다.

## 🚨 **아무것도 실행하지 않는다**

`multi_api_equivalence._ask` 를 **그대로 가져다 쓴다.** 그쪽이 `bind_tools(...)`
결과의 `tool_calls` 만 읽고 도구를 실행하지 않으므로 여기도 같다. 평가셋에는
`delete_file` · `overwrite_file` · `force_close_app` 처럼 승인 대상도 들어 있는데,
**부르겠다는 말만 읽으므로** 파일이 지워지거나 앱이 죽지 않는다.
🔑 측정기를 복제하지 않은 이유이기도 하다 — 복제하면 «실행 안 함»이 두 곳이 되고,
언젠가 한쪽만 고쳐진다.

## 무엇을 세나

| 지표 | 뜻 |
|---|---|
| **전체 일치** | 69문장 중 기대한 도구를 **정확히** 부른 비율 |
| 🆕 **새 도구 20개** | 2026-09-24~25 에 들어온 것들만 따로 — **이번에 답하려던 질문** |
| 갈래별 | 어느 칸이 약한가(앱·파일·메일·약속 …) |
| «안 부르기» | 잡담에 도구를 안 부르나 (`expect=""`) |

🚨 **«정확히»의 뜻**: 기대 도구 **하나만** 부른 것을 맞다고 센다. 둘 이상 부르면
   갈라서 따로 센다(«기대 + 덤»). 덤이 늘 나쁜 것은 아니지만(*"찾아서 알려줘"* 에
   검색을 둘 부르는 식), **숫자를 후하게 주면 자가 아니게 된다.** 그래서 나눠서 보여준다.

## ⚠️ 한 번 돌린 결과는 결정적이지 않다

모델 호출이라 같은 문장이 다음에 다르게 나올 수 있다. 그래서 **원자료를 전부 남긴다**
(`docs/research/2026-09_도구선택.json`). 숫자 하나만 옮겨 적지 말고 그 파일을 볼 것.
"""
import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from multi_api_equivalence import _available, _bind, _ask, PROVIDERS  # noqa: E402
from tool_eval_cases import ALL_CASES, NEW_2026_09  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT = os.path.join(_ROOT, "docs", "research", "2026-09_도구선택.json")


# ── 측정 ──────────────────────────────────────────────────────────
def measure(provider: str, cases, verbose: bool = False) -> dict:
    bound, model = _bind(provider)
    rows = []
    for i, c in enumerate(cases, 1):
        try:
            r = _ask(bound, c.text)
            r["error"] = ""
        except Exception as e:                      # 한 문장이 실패해도 나머지는 잰다
            r = {"tools": [], "say": "", "args": {}, "ms": 0, "in": 0, "out": 0,
                 "error": f"{type(e).__name__}: {e}"[:200]}
        r["text"] = c.text
        r["expect"] = c.expect
        r["group"] = c.group
        rows.append(r)
        if verbose:
            print(f"  {_mark(r)} [{i:2}] {c.text[:30]:<32} 기대={c.expect or '(없음)':<22}"
                  f" → {','.join(r['tools']) or '(없음)'}")
        else:
            print(".", end="", flush=True)
    if not verbose:
        print()
    return {"model": model, "rows": rows}


def _mark(row: dict) -> str:
    """= 정확히 맞음 · + 기대 도구는 부르고 **덤이 있음** · x 틀림 · ! 호출 실패

    🚨 «+» 를 «=» 에 섞지 않는다. 섞으면 숫자가 후해지고, 후한 자는 자가 아니다.
    """
    if row.get("error"):
        return "!"
    want = [row["expect"]] if row["expect"] else []
    if row["tools"] == want:
        return "="
    if row["expect"] and row["expect"] in row["tools"]:
        return "+"
    return "x"


# ── 집계 ──────────────────────────────────────────────────────────
def _load() -> dict:
    if os.path.exists(_OUT):
        with open(_OUT, encoding="utf-8") as f:
            return json.load(f)
    return {"results": {}}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _tally(rows, keep=None):
    """(정확 일치, 기대+덤, 비교한 건수)"""
    exact = plus = n = 0
    for r in rows:
        if r["error"]:
            continue
        if keep is not None and not keep(r):
            continue
        n += 1
        want = [r["expect"]] if r["expect"] else []
        if r["tools"] == want:
            exact += 1
        elif r["expect"] and r["expect"] in r["tools"]:
            plus += 1
    return exact, plus, n


def _pct(a: int, b: int) -> str:
    return f"{a/b*100:.1f}%" if b else "—"


def report(data: dict) -> None:
    results = data.get("results", {})
    have = [p for p in PROVIDERS if p in results]
    if not have:
        print("아직 잰 provider가 없습니다.")
        return

    print("\n" + "=" * 78)
    print("도구 선택 정확도 (BL-71)  —  «새 도구가 제대로 불리나» · 실행 없음")
    print("=" * 78)
    print("🚨 주 지표가 **내가 붙인 라벨**이다. 이 숫자는 라벨만큼만 믿을 만하다.")
    print("🚨 모델 호출이라 결정적이지 않다 — 원자료를 같이 볼 것.")

    for p in have:
        rows = results[p]["rows"]
        model = results[p]["model"]
        ex, pl, n = _tally(rows)
        print(f"\n▣ {p}  ({model})  —  {len(rows)}문장")
        print(f"   전체 정확 일치   {ex}/{n} ({_pct(ex, n)})"
              f"   · 기대+덤 {pl}건 → 합 {_pct(ex + pl, n)}")

        # 🆕 이번에 답하려던 질문
        nx, npl, nn = _tally(rows, lambda r: r["expect"] in NEW_2026_09)
        ox, opl, on = _tally(rows, lambda r: r["expect"] and r["expect"] not in NEW_2026_09)
        print(f"   🆕 새 도구 20개   {nx}/{nn} ({_pct(nx, nn)})"
              f"   · 기대+덤 {npl}건 → 합 {_pct(nx + npl, nn)}")
        print(f"   기존 도구        {ox}/{on} ({_pct(ox, on)})")

        zx, _zp, zn = _tally(rows, lambda r: not r["expect"])
        print(f"   🚫 안 부르기     {zx}/{zn}  (잡담에 도구를 안 불렀나)")

        lat = [r["ms"] for r in rows if not r["error"]]
        if lat:
            print(f"   지연 중앙값      {int(statistics.median(lat))}ms")

        # ── 갈래별
        groups = []
        for g in dict.fromkeys(r["group"] for r in rows):
            gx, gp, gn = _tally(rows, lambda r, g=g: r["group"] == g)
            groups.append((g, gx, gp, gn))
        print(f"\n   {'갈래':<8} {'정확':>8} {'덤':>4}")
        for g, gx, gp, gn in groups:
            print(f"   {g:<8} {gx:>3}/{gn:<4} {_pct(gx, gn):>6} {gp:>3}")

        # ── 갈린 것 전부 (숨기지 않는다)
        miss = [r for r in rows if not r["error"] and _mark(r) in "x+"]
        errs = [r for r in rows if r["error"]]
        print(f"\n   갈린 {len(miss)}건:")
        for r in miss:
            print(f"   [{_mark(r)}] {r['text'][:34]:<36} 기대={r['expect'] or '(없음)':<22}"
                  f" → {','.join(r['tools']) or '(없음)'}")
            # 🚨 도구를 안 불렀으면 **무슨 말을 했는지 반드시 보여준다.**
            #   «되묻는 것»과 «안 했는데 했다고 하는 것»은 같은 «(없음)» 으로 보이는데
            #   앞은 옳은 행동이고 뒤는 이 저장소가 제일 크게 데인 결함이다.
            if not r["tools"] and r.get("say"):
                print(f"        ↳ 말한 것: {r['say'][:120]}")
        if errs:
            print(f"\n   🚨 호출 실패 {len(errs)}건 — 위 숫자의 분모에서 빠져 있다")
            for r in errs:
                print(f"       {r['text'][:28]} — {r['error'][:60]}")

    missing = [p for p in PROVIDERS if p not in results]
    if missing:
        print(f"\n⏸️ 아직 못 잰 provider: {', '.join(missing)}")
        for p in missing:
            print(f"   {p}: {_available(p) or '잴 수 있다 — 아직 안 돌렸다'}")

    print(f"\n원본: {os.path.relpath(_OUT, _ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="도구 선택 정확도 (BL-71)")
    ap.add_argument("--providers", nargs="*", choices=PROVIDERS,
                    help="생략하면 키가 있는 곳 전부")
    ap.add_argument("--new", action="store_true",
                    help="2026-09-24~25 에 들어온 새 도구 20개만 잰다")
    ap.add_argument("--report", action="store_true", help="안 재고 저장된 결과만")
    ap.add_argument("--verbose", action="store_true", help="문장별로 다 본다")
    args = ap.parse_args()

    cases = [c for c in ALL_CASES if c.expect in NEW_2026_09] if args.new else ALL_CASES
    data = _load()

    if not args.report:
        # 🚨 부분 측정(--new)은 **전체 결과를 덮어쓰지 않는다.** 덮어쓰면 «69문장을
        #   쟀다»로 보이는 파일이 20문장짜리가 된다. 따로 저장한다.
        slot = "results_new" if args.new else "results"
        targets = args.providers if args.providers else list(PROVIDERS)
        ran = 0
        for p in targets:
            why = _available(p)
            if why:
                print(f"⏭️ {p} 건너뜀 — {why}")
                continue
            print(f"▶ {p} 측정 중 ({len(cases)}문장) …")
            data.setdefault(slot, {})[p] = measure(p, cases, verbose=args.verbose)
            _save(data)
            ran += 1
        if not ran:
            print("\n🚨 잴 수 있는 provider가 하나도 없습니다.")
        if args.new:
            report({"results": data.get("results_new", {})})
            return

    report(data)


if __name__ == "__main__":
    main()
