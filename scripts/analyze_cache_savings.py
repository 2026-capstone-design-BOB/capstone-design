# -*- coding: utf-8 -*-
"""캐시 절감액 실측 — «캐시가 무엇을 얼마나 아꼈나»를 로그로 잰다. (계획 1-5)

    python scripts/analyze_cache_savings.py
    python scripts/analyze_cache_savings.py --all          # 테스트 턴까지 포함
    python scripts/analyze_cache_savings.py --log logs/a.log --log logs/b.log
    python scripts/analyze_cache_savings.py --in-price 0.30 --out-price 2.50

## 무엇에 답하는가

① **히트율** — 실사용 턴 중 몇 %가 `LLM 0회(캐시)`로 끝났나
② **아낀 토큰** — 히트 턴이 LLM을 탔다면 얼마나 썼을까 (같은 로그의 실측 평균으로 환산)
③ **아낀 돈** — ②에 단가를 곱한 값
④ **아낀 시간** — 히트 턴 소요 vs LLM 턴 소요

## ⚠️ ②는 «측정»이 아니라 «환산»이다 — 이 스크립트는 그 경계를 지킨다

히트한 턴이 **LLM을 탔다면 썼을 토큰은 관측할 수 없다.** 안 탔으니까.
그래서 같은 로그의 **LLM 턴 평균**을 곱한다. 이건 추정이고, 리포트가 그렇게 말한다.

🚨 **그리고 이 추정은 낙관적으로 기운다.** 캐시가 잡는 문장(«메모장 열어줘»)은
LLM 턴 평균보다 **짧고 단순한 쪽**이다 — 계획·승인·Vision이 낀 긴 턴이 평균을 올린다.
그래서 **중앙값도 같이 찍는다.** 발표에 쓸 숫자는 보수적인 쪽(중앙값)이다.

## ⚠️ 로그 필터는 `analyze_tool_usage.py`와 **같은 규약**을 쓴다

`thread=pluiz_*` 만 실사용. 안 거르면 테스트 하네스가 히트율을 통째로 흔든다.
(→ docs/research/2026-09_도구사용_실측.md §0)
"""
import argparse
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 파싱은 이미 있는 것을 그대로 쓴다. **정규식을 복제하지 않는다** —
# `턴 완료` 줄 형식은 BL-52에서 한 번 바뀌었고(도구= → 요청=/실행=), 두 벌을 두면
# 다음에 또 바뀔 때 한쪽만 고쳐진다. 이 저장소가 반복해서 데인 모양이다.
from analyze_tool_usage import parse, is_real  # noqa: E402

_TOK = re.compile(r"in=(?P<i>\d+) out=(?P<o>\d+)")

#: 기본 단가 (USD / 1M tokens). ⚠️ **모델과 시점에 따라 바뀐다.**
#: 근거와 확인 날짜는 docs/research/2026-09_캐시_절감액.md §2에 적는다.
#: 값을 고칠 땐 **문서도 같이 고친다** — 여기만 고치면 슬라이드가 옛 숫자를 말한다.
DEFAULT_IN_PRICE = 0.30
DEFAULT_OUT_PRICE = 2.50
DEFAULT_MODEL = "gemini-2.5-flash"


def _tokens(t):
    """턴의 (in, out). 계측 이전(2026-09-08 전) 턴이면 None."""
    m = _TOK.search(t.get("tok") or "")
    return (int(m.group("i")), int(m.group("o"))) if m else None


def _fmt_usd(v):
    return f"${v:,.4f}" if v < 1 else f"${v:,.2f}"


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="append", default=None,
                    help="여러 번 줄 수 있다. 생략하면 logs/*.log 전부")
    ap.add_argument("--all", action="store_true", help="테스트 턴까지 포함")
    ap.add_argument("--in-price", type=float, default=DEFAULT_IN_PRICE)
    ap.add_argument("--out-price", type=float, default=DEFAULT_OUT_PRICE)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    logs = args.log or sorted(
        os.path.join(here, "logs", f)
        for f in os.listdir(os.path.join(here, "logs")) if f.endswith(".log"))

    turns = []
    for p in logs:
        turns.extend(parse(p))

    total = len(turns)
    used = turns if args.all else [t for t in turns if is_real(t)]

    print(f"\n{'='*66}")
    print(f" 캐시 절감액 실측 — {args.model}  (in ${args.in_price}/1M · out ${args.out_price}/1M)")
    print(f"{'='*66}")
    print(f" 로그 {len(logs)}개 · 턴 완료 {total}개 "
          f"→ {'전체' if args.all else '실사용(thread=pluiz_*)'} **{len(used)}턴**")
    if not args.all:
        unknown = sum(1 for t in turns if not t["thread"])
        print(f"   (테스트·미상 {total - len(used)}턴 제외 — 그중 thread 미상 {unknown}턴)")
    if not used:
        print("\n ⚠️ 셀 턴이 없다. --all 로 다시 보거나 로그를 확인할 것.\n")
        return

    hits = [t for t in used if t["cached"]]
    llm = [t for t in used if not t["cached"]]
    rate = len(hits) / len(used) * 100

    print(f"\n── ① 히트율 ───────────────────────────────────────────")
    print(f"  캐시 히트 : {len(hits):>4}턴  ({rate:.1f}%)")
    print(f"  LLM 경유  : {len(llm):>4}턴")

    # ── ② 토큰 ─────────────────────────────────────────────────
    tok = [x for x in (_tokens(t) for t in llm) if x]
    print(f"\n── ② 토큰 — LLM 턴 실측 ───────────────────────────────")
    if not tok:
        print("  ⚠️ 토큰이 기록된 LLM 턴이 없다(계측은 2026-09-08에 들어갔다). "
              "②③을 낼 수 없다.")
        ins = outs = []
    else:
        ins = [a for a, _ in tok]
        outs = [b for _, b in tok]
        print(f"  토큰이 남은 LLM 턴 : {len(tok)} / {len(llm)}")
        print(f"  입력  합계 {sum(ins):>9,}  평균 {statistics.mean(ins):>8,.0f}  "
              f"중앙값 {statistics.median(ins):>7,.0f}")
        print(f"  출력  합계 {sum(outs):>9,}  평균 {statistics.mean(outs):>8,.0f}  "
              f"중앙값 {statistics.median(outs):>7,.0f}")

    # ── ③ 돈 ───────────────────────────────────────────────────
    if tok and hits:
        def cost(i, o):
            return i / 1e6 * args.in_price + o / 1e6 * args.out_price

        spent = cost(sum(ins), sum(outs))
        mean_c = cost(statistics.mean(ins), statistics.mean(outs))
        med_c = cost(statistics.median(ins), statistics.median(outs))
        print(f"\n── ③ 돈 ───────────────────────────────────────────────")
        print(f"  실제 쓴 돈(LLM 턴 {len(tok)}개)     : {_fmt_usd(spent)}")
        print(f"  턴당 평균 {_fmt_usd(mean_c)} · 중앙값 {_fmt_usd(med_c)}")
        print(f"\n  ⚠️ 아래는 **환산**이다 — 히트 턴이 LLM을 탔다면 썼을 값.")
        print(f"  아낀 돈 (평균 기준)  : {_fmt_usd(mean_c * len(hits))}"
              f"   ← 낙관적")
        print(f"  아낀 돈 (중앙값 기준): {_fmt_usd(med_c * len(hits))}"
              f"   ← **발표엔 이 쪽**")
        print(f"  아낀 토큰(중앙값 기준): "
              f"in {statistics.median(ins) * len(hits):,.0f} · "
              f"out {statistics.median(outs) * len(hits):,.0f}")

    # ── ④ 시간 ─────────────────────────────────────────────────
    hs = [t["sec"] for t in hits if t["sec"] is not None]
    ls = [t["sec"] for t in llm if t["sec"] is not None]
    print(f"\n── ④ 시간 ─────────────────────────────────────────────")
    if hs and ls:
        print(f"  캐시 히트 : 중앙 {statistics.median(hs):>6.2f}s  "
              f"(평균 {statistics.mean(hs):.2f}s · n={len(hs)})")
        print(f"  LLM 경유  : 중앙 {statistics.median(ls):>6.2f}s  "
              f"(평균 {statistics.mean(ls):.2f}s · n={len(ls)})")
        if statistics.median(hs) > 0:
            print(f"  → 중앙값 기준 **{statistics.median(ls)/statistics.median(hs):,.0f}배**")
    else:
        print("  ⚠️ 소요가 기록된 턴이 부족하다.")

    print(f"\n{'='*66}")
    print(" ⚠️ ②③은 환산이다. «히트 턴이 LLM을 탔다면»을 관측할 방법은 없다.")
    print("    캐시가 잡는 문장은 평균보다 짧은 쪽이라 **평균 기준은 부풀려진다.**")
    print(f"{'='*66}\n")


if __name__ == "__main__":
    main()
