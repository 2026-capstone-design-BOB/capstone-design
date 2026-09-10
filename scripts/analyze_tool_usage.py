# -*- coding: utf-8 -*-
"""도구 사용 실측 — «도구가 제대로 주어졌는가»를 로그로 잰다. (3주차)

    python scripts/analyze_tool_usage.py
    python scripts/analyze_tool_usage.py --all      # 테스트 턴까지 포함
    python scripts/analyze_tool_usage.py --log 다른.log

## 무엇에 답하는가

① 등록된 도구 중 **실제로 쓰인 것이 몇 개인가** (안 쓰인 도구는 왜 있는가)
② **도구가 없어서/안 불려서 실패한 턴** ← 가장 중요하다. BL-07·BL-19가 그 사례다
③ **잘못 고른 턴** — 사용자가 바로 정정한 턴을 센다

## ⚠️ 먼저 로그를 걸러야 한다 — 이 로그는 테스트로 오염돼 있다

`thread=` 접두사로 실사용과 테스트가 갈린다(`pluiz_` = UI, 나머지는 대부분 테스트
하네스). 안 거르면 **테스트가 부른 도구가 «실사용»으로 집계된다.**
2026-09-08 동향점검 ⑤가 지적한 바로 그 오염이고, 여기서 처음 정량화한다.

⚠️ `턴 완료` 줄에는 thread가 없다. **바로 앞의 `승인 대기 확인` 줄**에서 물려받는다
(요청마다 그 줄이 먼저 찍힌다). 못 물리면 `미상`으로 두고 **«실사용»에 넣지 않는다** —
모르는 것을 실사용으로 세면 숫자가 낙관적으로 기운다.
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ⚠️ 계측(소요·LLM·토큰)은 **2026-09-08에 들어갔다.** 그 전 턴에는 그 칸이 없다.
# 그래서 뒤쪽 칸은 전부 optional 이다 — 안 그러면 09-08 이전 로그가 통째로 빠지고,
# 도구 집계가 **최근 이틀치만** 보게 된다(처음 돌렸을 때 623턴 중 138턴만 잡혔다).
_TURN = re.compile(
    r"^(?P<ts>[\d-]{10} [\d:]{8}).*?\[Agent\] 턴 완료 \| 입력=(?P<q>'[^']*'|\"[^\"]*\")"
    r" \| 도구=(?P<tools>없음|\[[^\]]*\])"
    r"(?: \| 응답 (?P<rlen>\d+)자)?"
    r"(?: \| 계획 (?P<plan>\d+/\d+))?"
    r"(?: \| 소요 (?P<sec>[\d.]+)s)?"
    r"(?: \| LLM (?P<llm>\d+|\?)회(?P<cached>\(캐시\))?)?"
    r"(?: \| 토큰 (?P<tok>0|미상|in=\d+ out=\d+))?")
_THREAD = re.compile(r"thread=(?P<t>[A-Za-z0-9_]+)")

# 사용자가 «방금 그거 아니야»라고 말한 신호. 앞 턴이 틀렸을 가능성이 높다.
_CORRECTION = re.compile(r"^(아니|아냐|그게 아니|말고|다시|또 |왜 |안 |그거 말고|틀렸)")

# 실사용 thread 접두사. 나머지는 테스트 하네스로 본다.
_REAL_PREFIXES = ("pluiz_",)


def parse(path):
    turns = []
    cur_thread = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _THREAD.search(line)
            if m and "턴 완료" not in line:
                cur_thread = m.group("t")
            m = _TURN.search(line)
            if not m:
                continue
            raw = m.group("tools")
            tools = [] if raw == "없음" else re.findall(r"'([^']+)'", raw)
            turns.append({
                "ts": m.group("ts"),
                "q": m.group("q")[1:-1],
                "tools": tools,
                "sec": float(m.group("sec")) if m.group("sec") else None,
                "llm": m.group("llm"),
                "cached": bool(m.group("cached")),
                "tok": m.group("tok") or "미상",
                "thread": cur_thread,
                "plan": m.group("plan"),
            })
    return turns


def is_real(t):
    return bool(t["thread"]) and t["thread"].startswith(_REAL_PREFIXES)


def registered_tools():
    """등록된 도구 이름. 못 불러오면 None(그러면 ①을 «미상»으로 둔다)."""
    try:
        from core.tool_registry import get_all_tools
        return {getattr(t, "name", str(t)) for t in get_all_tools()}
    except Exception as e:
        print(f"  (도구 목록을 못 불러왔습니다: {type(e).__name__}: {e})")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "pluiz.log"))
    ap.add_argument("--all", action="store_true", help="테스트 턴까지 포함해 집계")
    args = ap.parse_args()

    turns = parse(args.log)
    if not turns:
        print("턴이 없습니다."); return

    real = [t for t in turns if is_real(t)]
    test = [t for t in turns if t["thread"] and not is_real(t)]
    unknown = [t for t in turns if not t["thread"]]
    use = turns if args.all else real

    print("=" * 78)
    print(f"■ 0. 로그 위생 — {os.path.basename(args.log)} · 턴 {len(turns)}개")
    print("=" * 78)
    print(f"  기간          {turns[0]['ts']} ~ {turns[-1]['ts']}")
    print(f"  실사용(UI)    {len(real):>4}턴   ← thread=pluiz_*")
    print(f"  테스트        {len(test):>4}턴")
    print(f"  thread 미상   {len(unknown):>4}턴   ← 실사용에 넣지 않는다")
    by_pref = Counter(re.sub(r"[0-9].*$", "", t["thread"]) for t in test)
    print(f"  테스트 접두사  {dict(by_pref.most_common(8))}")
    print(f"\n  → 아래는 {'전체' if args.all else '**실사용 ' + str(len(real)) + '턴**'} 기준"
          f" ({'--all' if args.all else '--all 로 전체 보기'})")
    if not use:
        print("\n  🚨 집계할 턴이 없습니다."); return

    # ── ① 도구 사용 빈도 ─────────────────────────────────────────
    used = Counter()
    for t in use:
        used.update(t["tools"])
    print()
    print("=" * 78)
    print("■ ① 어떤 도구가 실제로 쓰였나")
    print("=" * 78)
    reg = registered_tools()
    if reg:
        unknown_names = set(used) - reg
        print(f"  등록 {len(reg)}개 중 **{len(set(used) & reg)}개**가 쓰였다 "
              f"(안 쓰인 {len(reg - set(used))}개)")
        if unknown_names:
            print(f"  ⚠️ 등록에 없는 이름이 로그에 있다(테스트 mock 오염): "
                  f"{sorted(unknown_names)}")
    print(f"  도구 호출 총 {sum(used.values())}회 · 서로 다른 도구 {len(used)}종")
    print()
    for name, n in used.most_common():
        bar = "█" * min(40, n)
        print(f"    {name:<24} {n:>4}  {bar}")
    if reg:
        never = sorted(reg - set(used))
        print(f"\n  ⛔ 한 번도 안 쓰인 도구 {len(never)}개:")
        for i in range(0, len(never), 3):
            print("     " + " · ".join(f"{x:<22}" for x in never[i:i + 3]))

    # ── ② 도구 없이 끝난 턴 ──────────────────────────────────────
    print()
    print("=" * 78)
    print("■ ② 도구를 하나도 안 부른 턴 — «못 한 것»이 여기 숨는다")
    print("=" * 78)
    notool = [t for t in use if not t["tools"]]
    cached = [t for t in notool if t["cached"]]
    chat = [t for t in notool if not t["cached"]]
    print(f"  도구 0개인 턴 {len(notool)}/{len(use)}")
    print(f"    - 캐시가 처리 {len(cached)}턴  ← 도구를 «안 부른» 게 아니라 «안 불러도 된» 것이다")
    print(f"    - LLM이 말만  {len(chat)}턴  ← 여기에 «시켰는데 안 된 것»이 섞여 있다")
    print("\n  LLM이 말만 한 턴 중 **명령처럼 보이는 것** (사람이 봐야 확정된다):")
    imperative = re.compile(r"(줘|줄래|해라|해봐|해 봐|보여|알려|켜|꺼|열어|닫아|실행)")
    cand = [t for t in chat if imperative.search(t["q"])]
    for t in cand[:15]:
        print(f"    {t['ts'][5:]}  {t['q'][:44]!r}"
              + (f"  ({t['sec']:.1f}s)" if t['sec'] is not None else ""))
    if len(cand) > 15:
        print(f"    … 외 {len(cand) - 15}개")
    print(f"\n  🔑 후보 {len(cand)}턴 — 이 중 진짜 실패가 몇인지는 **응답 본문이 있어야** 안다.")
    print(f"     ⚠️ 로그에 응답이 «{'{'}자 수{'}'}»로만 남아 실패 사유를 사후에 못 읽는다.")
    print(f"        → 다음에 고칠 것: 도구 미호출로 끝난 턴에 **사유 한 줄**을 남긴다.")

    # ── ③ 사용자가 곧바로 정정한 턴 ──────────────────────────────
    print()
    print("=" * 78)
    print("■ ③ 잘못 고른 턴 — 사용자가 **바로 다음 턴에 정정**한 경우")
    print("=" * 78)
    fixes = []
    for a, b in zip(use, use[1:]):
        if a["thread"] == b["thread"] and _CORRECTION.search(b["q"]):
            fixes.append((a, b))
    print(f"  정정 신호가 붙은 턴 {len(fixes)}/{max(1, len(use) - 1)} "
          f"({100 * len(fixes) / max(1, len(use) - 1):.1f}%)")
    for a, b in fixes[:12]:
        print(f"    {a['ts'][5:]}  {a['q'][:30]!r} → 도구={a['tools'] or '없음'}")
        print(f"       ↳ 사용자: {b['q'][:52]!r}")
    if len(fixes) > 12:
        print(f"    … 외 {len(fixes) - 12}개")

    # ── ④ 덤 — 캐시가 실제로 얼마나 일했나 ───────────────────────
    print()
    print("=" * 78)
    print("■ ④ 캐시 기여도 (차별점을 말이 아니라 로그로)")
    print("=" * 78)
    inst = [t for t in use if t["sec"] is not None]
    if not inst:
        print("  (계측된 턴이 없습니다 — 계측은 2026-09-08에 들어갔다)")
        return
    print(f"  ⚠️ 계측은 2026-09-08에 들어갔다 → 아래는 그 이후 **{len(inst)}턴**만 본다")
    hits = [t for t in inst if t["cached"]]
    llm_turns = [t for t in inst if not t["cached"]]
    tok = 0
    for t in llm_turns:
        m = re.match(r"in=(\d+) out=(\d+)", t["tok"] or "")
        if m:
            tok += int(m.group(1)) + int(m.group(2))

    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else 0.0
    print(f"  캐시 히트  {len(hits):>4}턴 ({100*len(hits)/len(inst):.1f}%) · "
          f"지연 중앙값 {med([t['sec'] for t in hits]):.2f}s · LLM 0회 · 토큰 0")
    print(f"  LLM 경유  {len(llm_turns):>4}턴 · "
          f"지연 중앙값 {med([t['sec'] for t in llm_turns]):.2f}s · 토큰 합계 {tok:,}")
    if hits and llm_turns:
        print(f"  → 캐시가 없었다면 그 {len(hits)}턴도 "
              f"{med([t['sec'] for t in llm_turns]):.1f}초씩 걸렸다는 뜻이다")


if __name__ == "__main__":
    main()
