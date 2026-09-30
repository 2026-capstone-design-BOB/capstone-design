"""웨이크워드 실기 계수기 — MANUAL_TESTS §17 이 쓴다.

«잘 되는 것 같다»로 적지 않기 위한 도구다. 로그에서 **깬 횟수**를 세고,
그중 몇 번이 실제로 말까지 이어졌는지를 갈라 준다.

    python scripts/count_wake.py            전체
    python scripts/count_wake.py 1280       1280번째 줄 이후만 (실기 구간)

🚨 **«부른 횟수»는 세지 못한다.** 그건 사람만 안다 — §17 표에 손으로 적는다.
   분모가 없으면 놓침률도 없다.

🚨 로그의 «(놓침)» 줄은 세지 않는다. 그 말은 확률 0.31~0.62 인 **모든 구간**에
   붙어서(`services/wakeword.py` 496행) 부르지도 않은 말소리가 대부분이다.
   2026-09-29 실기에서 410줄이 나왔는데 실제 호출은 25번이었다.
"""
import io
import os
import re
import sys

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "logs", "pluiz.log")

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_WAKE = re.compile(r"prob=([0-9.]+) ≥ [0-9.]+ → WAKE")


def _stamp(line):
    m = _TS.match(line)
    return m.group(1) if m else None


def _listening_hours(stamps, gap_limit=60):
    """실제로 듣고 있던 시간만 더한다.

    로그는 서버를 껐다 켜도 한 파일에 이어 붙는다. 첫 줄~끝 줄로 재면 꺼져 있던
    시간이 분모에 들어가 **오탐률이 좋아 보인다.** 웨이크워드는 도는 동안
    0.6초마다 줄을 남기므로 `gap_limit` 초를 넘는 공백은 «꺼져 있었다»로 본다.
    """
    from datetime import datetime
    fmt = "%Y-%m-%d %H:%M:%S"
    total = 0.0
    prev = None
    for s in stamps:
        try:
            t = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if prev is not None:
            d = (t - prev).total_seconds()
            if 0 <= d <= gap_limit:
                total += d
        prev = t
    return total / 3600


def main(argv):
    start = int(argv[1]) if len(argv) > 1 else 0
    if not os.path.exists(LOG):
        print(f"로그가 없다: {LOG}")
        return 1

    with io.open(LOG, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()[start:]

    wakes = [(_stamp(l), float(m.group(1)))
             for l in lines for m in [_WAKE.search(l)] if m]
    heard = [l for l in lines if "google 성공" in l or "whisper 성공" in l]
    empty = [l for l in lines if "빈 결과" in l]
    started = [l for l in lines if "인식 시작" in l]

    stamps = [s for s in (_stamp(l) for l in lines) if s]
    ear = [s for s in (_stamp(l) for l in lines if "[wakeword]" in l) if s]
    span = f"{ear[0]} ~ {ear[-1]}" if ear else "(웨이크워드가 안 돌았다)"

    print(f"듣던 구간   {span}   (로그 {start}행 이후 {len(lines)}줄)")
    print()
    print(f"🔔 깸(WAKE)          {len(wakes):4d}")
    print(f"   ㄴ 인식까지 감     {len(started):4d}")
    print(f"   ㄴ 말을 알아들음   {len(heard):4d}")
    print(f"   ㄴ 인식 못 함      {len(empty):4d}   ← 헛깨어남 후보")
    print()

    if wakes:
        hi = [p for _, p in wakes if p >= 0.9]
        lo = [p for _, p in wakes if p < 0.9]
        print(f"확률 0.9 이상 {len(hi):3d}회 · 0.62~0.9 {len(lo):3d}회")
        print("  " + " ".join(f"{p:.2f}" for _, p in wakes))
        print()

    if empty and wakes:
        # 시간으로 나눠 «시간당 몇 번»을 만든다 — 전시회 목표가 그 단위다(≤1회/시간).
        #
        # 🚨 **첫 줄과 끝 줄의 차이를 쓰면 안 된다.** 로그는 서버를 껐다 켜도 이어
        #    붙으므로, 꺼져 있던 밤이 통째로 분모에 들어간다. 2026-09-29 에 실제로
        #    그렇게 나왔다 — 헛깨어남 7회가 22.8시간으로 나뉘어 «0.3회/시간»이라는
        #    **목표를 통과한 것처럼 보이는 거짓 숫자**가 찍혔다. 실제로는 18분이다.
        #    (9/28 에 FRR 분모를 틀린 것과 **같은 모양**이다.)
        #
        # 🔑 웨이크워드는 도는 동안 0.6초마다 로그를 남긴다. 그래서 **60초 넘는 빈
        #    구간은 «꺼져 있었다»** 로 보고 분모에서 뺀다.
        # 🔑 분모는 «로그가 있던 시간»이 아니라 **«웨이크워드가 듣고 있던 시간»** 이다.
        #    서버만 떠 있고 웨이크워드 프로세스는 안 뜬 구간이 실제로 있었다
        #    (2026-09-29 16:07~16:33 — 타자로 친 턴들). 그것도 분모에서 뺀다.
        hours = _listening_hours(ear)
        if hours > 0:
            print(f"헛깨어남 후보 {len(empty)}회 ÷ {hours:.2f}시간(실제로 듣고 있던 시간) "
                  f"= 약 {len(empty) / hours:.1f}회/시간")
            print("   🔴 전시회 목표는 ≤1회/시간 · 9/28 실측 예측은 25회/시간")

    print()
    print("🙋 «부른 횟수»는 사람이 센다 — MANUAL_TESTS §17 표에 적는다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
