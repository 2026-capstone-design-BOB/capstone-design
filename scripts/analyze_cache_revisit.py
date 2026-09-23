#!/usr/bin/env python
"""캐시 히트율을 «세션»과 «반복»으로 분해한다. (docs/research/2026-09_캐시_절감액.md §9)

🚨 **왜 필요한가.** `analyze_cache_savings.py` 가 내는 히트율 하나는
**캐시의 성질이 아니라 «그 세션에 무슨 말을 했는가»의 성질**이다. 실제로 로그 4개를
세션별로 가르면 **15.8% ~ 38.6%** 로 벌어지는데 코드는 같다. 단일 숫자로 말하면
시스템의 속성처럼 들린다 — 그게 이 지표의 결함이고, 이 도구가 그걸 드러낸다.

내는 것 넷:
  ① **세션별 히트율** — 폭이 크면 그 숫자는 시스템이 아니라 세션을 잰 것이다
  ② **히트 분해** — «처음 본 말»(시드가 낸 몫) vs «이미 나온 말»(동적 학습이 낸 몫)
  ③ **재방문 포착률** — 같은 말을 또 했을 때 잡아 주는 비율.
     **명령 구성비와 무관**해서 캐시 품질에 가장 가깝다
  ④ **게이트 증거** — 많이 나온 발화별 히트 수. «막아야 할 것»이 0인지 눈으로 본다

⚠️ **재방문은 «문자열이 같은 것»으로 센다.** 캐시는 (대상, 동작)으로 매칭하므로
  «메모장 켜 줘»↔«메모장 열어줘»도 같은 명령으로 잡는다. 실제 재방문은 이보다 많고,
  따라서 ③은 **후하게 잡힌 값**일 수 있다. 정밀히 재려면 인텐트 단위로 세야 한다.

🚨 **아직 못 재는 것 — 오매칭률.** 히트율은 재는데 «그 히트가 옳았는지»는 안 잰다.
  높은 히트율은 오매칭으로도 만들 수 있다. 로그만으로는 갈 수 없고 라벨링이 필요하다.

필터는 `analyze_cache_savings.py` 와 **같은 것을 쓴다**(`thread=pluiz_*`).
정규식을 복제하지 않는다 — `턴 완료` 줄 형식은 한 번 바뀐 적이 있고,
두 벌을 두면 다음에 또 바뀔 때 한쪽만 고쳐진다.
"""
import argparse
import collections
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyze_tool_usage import parse, is_real  # noqa: E402

_STRIP = re.compile(r"[\s.,!?~\-—…\"'·]+")


def norm(s: str) -> str:
    """공백·문장부호를 걷어낸 표기. «같은 말의 다른 적기»를 한 덩어리로 본다."""
    return _STRIP.sub("", unicodedata.normalize("NFKC", s))


def _repeat(turns):
    """(고유 발화 수, 재방문 턴 수)."""
    seen, rep = set(), 0
    for t in turns:
        k = norm(t["q"])
        if k in seen:
            rep += 1
        seen.add(k)
    return len(seen), rep


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="append", default=None,
                    help="여러 번 줄 수 있다. 생략하면 logs/*.log 전부")
    ap.add_argument("--all", action="store_true", help="테스트 턴까지 포함")
    ap.add_argument("--ablate", action="store_true",
                    help="동적 학습을 «지웠다 쳤을 때» 히트가 몇 개 줄어드는지 잰다")
    args = ap.parse_args()

    logdir = os.path.join(here, "logs")
    logs = args.log or sorted(os.path.join(logdir, f)
                              for f in os.listdir(logdir) if f.endswith(".log"))

    print(f"\n{'='*78}")
    print(" 캐시 히트율 분해 — 세션별 · 반복별  (docs/research/2026-09_캐시_절감액.md §9)")
    print(f"{'='*78}")
    print(f"\n{'세션':<44}{'턴':>5}{'히트':>6}{'히트율':>8}{'재방문율':>9}")
    print("-" * 78)

    allt, rates = [], []
    for p in logs:
        ts = [t for t in parse(p) if args.all or is_real(t)]
        if not ts:
            continue
        h = sum(1 for t in ts if t["cached"])
        _, rep = _repeat(ts)
        rate = h / len(ts) * 100
        rates.append(rate)
        print(f"{os.path.basename(p):<44}{len(ts):>5}{h:>6}"
              f"{rate:>7.1f}%{rep/len(ts)*100:>8.1f}%")
        allt += ts

    if not allt:
        print("\n ⚠️ 셀 턴이 없다. --all 로 다시 보거나 로그를 확인할 것.\n")
        return

    n = len(allt)
    hits = sum(1 for t in allt if t["cached"])
    uniq, rep = _repeat(allt)
    print("-" * 78)
    print(f"{'합계':<44}{n:>5}{hits:>6}{hits/n*100:>7.1f}%{rep/n*100:>8.1f}%")

    if len(rates) > 1:
        print(f"\n🚨 세션별 히트율이 {min(rates):.1f}% ~ {max(rates):.1f}% "
              f"({max(rates)/max(min(rates), 0.1):.1f}배)로 갈린다 — 같은 코드다.")
        print("   → 이 값은 캐시의 성질이 아니라 «그 세션에 무슨 말을 했는가»의 성질이다.")

    # ── ② 히트 분해 ────────────────────────────────────────────────
    seen = set()
    fh = rh = fm = rm = 0
    for t in allt:
        k = norm(t["q"])
        first = k not in seen
        seen.add(k)
        if t["cached"]:
            fh, rh = fh + first, rh + (not first)
        else:
            fm, rm = fm + first, rm + (not first)

    print(f"\n── ② 히트 {hits}턴을 가르면 ─────────────────────────────")
    if hits:
        print(f"  처음 본 말인데 히트   : {fh:>4}턴 ({fh/hits*100:5.1f}%)  "
              f"← 시드 · 인텐트 일반화가 낸 몫")
        print(f"  이미 나온 말이라 히트 : {rh:>4}턴 ({rh/hits*100:5.1f}%)  "
              f"← «쓸수록 빨라진다»가 낸 몫 (전체의 {rh/n*100:.1f}%)")

    # ── ③ 재방문 포착률 ────────────────────────────────────────────
    print(f"\n── ③ 재방문 포착률 ───────────────────────────────────")
    if rep:
        print(f"  재방문 {rep}턴 중 {rh}턴 히트 → **{rh/rep*100:.1f}%**")
        print(f"  (두 번째인데도 못 잡은 것: {rm}턴)")
        print("  🔑 명령 구성비와 무관하다 — 캐시 품질에 가장 가까운 숫자다.")
    else:
        print("  재방문이 0턴이라 낼 수 없다.")
    once = sum(1 for c in collections.Counter(norm(t["q"]) for t in allt).values() if c == 1)
    print(f"  딱 한 번만 나온 발화: {once} / {uniq} 고유 "
          f"— 전체 턴의 {once/n*100:.1f}%는 캐시가 구조적으로 못 잡는다")

    # ── ④ 게이트 증거 ──────────────────────────────────────────────
    cnt = collections.Counter(norm(t["q"]) for t in allt)
    hitcnt = collections.Counter(norm(t["q"]) for t in allt if t["cached"])
    orig = {}
    for t in allt:
        orig.setdefault(norm(t["q"]), t["q"])
    print(f"\n── ④ 많이 나온 발화 — 그중 몇 번이 히트였나 ───────────")
    for k, c in cnt.most_common(12):
        if c < 2:
            break
        print(f"  {c:>3}회 중 히트 {hitcnt.get(k, 0):>2}   {orig[k][:52]}")
    print("  🔑 승인 응답·지시대명사·위험 도구가 0이고 평범한 명령이 전부 히트면 "
          "게이트가 도는 것이다.")

    if args.ablate:
        _ablate([t["q"] for t in allt])

    print(f"\n{'='*78}")
    print(" 🚨 오매칭률(잘못 잡은 비율)은 여기서 못 낸다 — 로그만으로는 갈 수 없다.")
    print("    히트율만 높이는 수정은 이 도구를 통과한다. 10/31 실사용에서 라벨링한다.")
    print(f"{'='*78}\n")


def _ablate(utts):
    """동적 학습을 «지웠다 쳤을 때» 히트가 몇 개 줄어드나. (§10)

    🔒 **메모리에서만 지운다.** `_persist()` 를 절대 부르지 않으므로
    `cache/command_cache.json` 은 한 바이트도 안 바뀐다.
    """
    import contextlib
    import io

    from core.command_cache import get_cache

    with contextlib.redirect_stdout(io.StringIO()):
        c = get_cache()
    c._learning_enabled = False          # 재는 동안 학습 금지

    def sweep():
        s1 = s2 = 0
        got = set()
        for u in utts:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = c.find(u)
            if r:
                got.add(u)
                s1 += "[S1-intent]" in buf.getvalue()
                s2 += "[S2-sim]" in buf.getvalue()
        return s1 + s2, s1, s2, got

    dyn = {k: e for k, e in c._cache.items() if e.source == "dynamic"}
    print(f"\n── ⑤ 제거 실험 — 동적 학습 {len(dyn)}개를 지웠다 치면 ──────")
    dead = [k for k in dyn if c._extract_intent(k) is not None]
    if dead:
        print(f"  ⚠️ 그중 {len(dead)}개는 **인텐트가 이미 잡는다**(있으나 마나): "
              + ", ".join(repr(k) for k in dead))

    before, b1, b2, hb = sweep()
    for k in dyn:
        del c._cache[k]
    with contextlib.redirect_stdout(io.StringIO()):
        c._build_intent_index()
    after, a1, a2, ha = sweep()
    c._cache.update(dyn)                 # 메모리 복원
    with contextlib.redirect_stdout(io.StringIO()):
        c._build_intent_index()

    print(f"  지금 그대로   : 히트 {before:>3}  (인텐트 {b1} · 유사도 {b2})")
    print(f"  학습분 제거   : 히트 {after:>3}  (인텐트 {a1} · 유사도 {a2})")
    d = before - after
    print(f"  🚨 **동적 학습이 만든 히트 : {d}턴** "
          f"— 히트의 {d/max(before,1)*100:.1f}% · 전체 {len(utts)}턴의 {d/len(utts)*100:.1f}%")
    for u in sorted(hb - ha):
        print(f"     잃은 발화: {u!r}")
    print("  🔑 잃은 발화가 «동작 표에 트리거가 없는 말»이라면, 학습이 하는 일은")
    print("     «습관 학습»이 아니라 **«손으로 쓴 표의 빈칸 메우기»** 다. 표를 고치는 게 맞다.")


if __name__ == "__main__":
    main()
