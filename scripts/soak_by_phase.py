"""소크 오디오를 **구간별로** 채점한다 — 「무엇에 깨는가」를 가른다.

    conda activate pluiz
    python scripts/soak_by_phase.py data/soak_voice_<날짜>.wav

🔑 **왜 나눠서 재나** — 섞어서 받으면 «264회/시간» 하나가 나오는데, 그 숫자는
   **무엇을 고쳐야 하는지 말해 주지 않는다.** 조용할 때도 깨는지, 내 목소리에 깨는지,
   음악에 깨는지, 남의 말소리에 깨는지는 손댈 곳이 **각각 다르다**:

     조용히      에 깬다 → 말소리 문제가 아니다. **마이크 잡음**을 의심한다
     혼잣말      에 깬다 → 학습 음성에 **내 평소 말**이 모자라다
     음악        에 깬다 → 학습 음성에 **음악**이 모자라다
     남의 말소리  에 깬다 → 학습 음성이 **TTS 에 치우쳐** 있다(실제 사람 목소리 부족)

🚨 **다만 「깬다」를 런타임 임계 하나로 판정하지 않는다.** 임계를 조금 올려 사라지는
   것은 «아슬아슬한 반응»이고, **높은 임계에서도 남는 것**이 진짜 할 일이다.
   2026-10-01 실측에서 「조용히」가 0.62 에 24회/시간이었는데 0.80 에서 **0** 이었다 —
   그걸 «마이크 잡음»으로 읽을 뻔했다. 같은 표에서 「남의 말소리」는 0.99 에서도
   24회/시간이 남았다. **거기가 진짜 자리다.**

🚨 **임계를 하나 골라 비교하지 않는다.** 구간마다 임계 표를 같이 낸다 —
   한 임계에서만 보면 결론이 뒤집힌다(M7 §3 이 업계 표준으로 정한 방식이다).

구간표(`*.phases.json`)가 없으면 통째로 한 덩어리로 잰다.
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

THRESHOLDS = (0.62, 0.80, 0.90, 0.95, 0.99)
TARGET = 1.0            # 🔴 전시회 목표 — FA/시간


def main(argv=None):
    ap = argparse.ArgumentParser(description="소크 오디오를 구간별로 채점한다")
    ap.add_argument("wav", help="녹음 파일 (scripts/record_soak.py 가 만든 것)")
    ap.add_argument("--model", default=None, help="기본은 런타임 모델")
    ap.add_argument("--json", default="", help="결과를 JSON 으로 저장")
    a = ap.parse_args(argv)

    from scripts.eval_wakeword import read_wav, scan, replay, SAMPLE_RATE
    from services.wakeword import (
        KwsModel, MODEL_PATH, kws_threshold, kws_energy_floor)

    wav = a.wav if os.path.isabs(a.wav) else os.path.join(ROOT, a.wav)
    if not os.path.exists(wav):
        print(f"✗ 없는 파일: {wav}")
        return 1

    model_path = a.model or MODEL_PATH
    gate = kws_energy_floor(0.0015)
    runtime_th = kws_threshold()

    side = wav[:-4] + ".phases.json"
    if os.path.exists(side):
        meta = json.load(io.open(side, encoding="utf-8"))
        phases = meta.get("phases", [])
    else:
        phases = []
        print(f"⚠️  구간표가 없어요({os.path.basename(side)}) — 통째로 잽니다.")

    model = KwsModel(model_path)
    audio = read_wav(wav)
    dur = len(audio) / SAMPLE_RATE
    frames = scan(model, audio, gate)

    if not phases:
        phases = [{"name": "전체", "start": 0.0, "end": dur}]

    print()
    print(f"[소크] {os.path.basename(wav)}  {dur/60:.1f}분")
    print(f"[모델] {os.path.basename(model_path)} · 에너지 관문 {gate} · 런타임 임계 {runtime_th}")
    print()

    rows = []
    for ph in phases:
        s0, s1 = float(ph["start"]), float(ph["end"])
        span = max(0.0, s1 - s0) / 3600.0
        r = {"name": ph["name"], "hours": span, "fa": {}}
        for th in THRESHOLDS:
            # 🔑 **전체를 한 번 훑고 구간으로 나눈다.** 구간마다 따로 훑으면
            #   경계에서 쿨다운이 끊겨 깨어남이 더 세진다.
            fires = [t for t in replay(frames, th, gate) if s0 <= t < s1]
            r["fa"][th] = {"n": len(fires),
                           "per_hour": (len(fires) / span) if span > 0 else float("nan")}
        rows.append(r)

    w = max(12, max(len(r["name"]) for r in rows) + 2)
    head = f"{'구간':<{w}}{'길이':>7}" + "".join(f"{th:>10.2f}" for th in THRESHOLDS)
    print(head)
    print("─" * len(head))
    for r in rows:
        line = f"{r['name']:<{w}}{r['hours']*60:>6.1f}분"
        for th in THRESHOLDS:
            line += f"{r['fa'][th]['per_hour']:>10.1f}"
        print(line)

    tot_h = sum(r["hours"] for r in rows)
    tline = f"{'합계':<{w}}{tot_h*60:>6.1f}분"
    for th in THRESHOLDS:
        n = sum(r["fa"][th]["n"] for r in rows)
        tline += f"{(n/tot_h if tot_h else float('nan')):>10.1f}"
    print("─" * len(head))
    print(tline)
    print()
    print(f"   숫자는 **FA/시간**(안 불렀는데 깬 횟수). 🔴 전시회 목표는 ≤ {TARGET:.0f}")
    print(f"   열 제목은 임계다 — 런타임은 지금 {runtime_th} 다.")
    print()

    # ── 읽는 법을 같이 찍는다. 표만 두면 다음 사람이 또 한 임계만 본다. ──
    #
    # 🚨 **한 임계의 값만 보고 결론 내지 않는다.** 처음 이 자리를 「런타임 임계에서
    #   조용히가 24/시간이면 마이크 잡음」으로 적었는데, 바로 옆 칸(0.80)이 0 이었다.
    #   임계를 조금만 올려도 사라지는 것은 **잡음 문제가 아니라 아슬아슬한 반응**이다.
    #   그래서 판단은 **곡선의 모양**으로 한다 — 높은 임계에서 뭐가 남는가.
    hi = THRESHOLDS[-1]
    def _ph(r, th):
        v = r["fa"][th]["per_hour"]
        return v if v == v else 0.0

    print("🔑 읽는 법")

    worst = max(rows, key=lambda r: _ph(r, runtime_th))
    print(f"   · 지금 임계({runtime_th})에서 가장 심한 구간 — **{worst['name']}** "
          f"{_ph(worst, runtime_th):.0f}/시간")

    # 🔑 **진짜 할 일은 「임계를 올려도 안 죽는 것」이다.**
    stubborn = max(rows, key=lambda r: _ph(r, hi))
    if _ph(stubborn, hi) > 0:
        base = _ph(stubborn, runtime_th)
        drop = 100 * (1 - _ph(stubborn, hi) / base) if base > 0 else 0
        print(f"   · 🚨 임계 {hi} 까지 올려도 남는 구간 — **{stubborn['name']}** "
              f"{_ph(stubborn, hi):.0f}/시간 (지금보다 {drop:.0f}% 줄 뿐이다)")
        print(f"        여기가 **임계로 못 푸는 자리**다. 학습 음성이나 2단계 확인이 할 일이다.")
    else:
        print(f"   · 임계 {hi} 에서는 모든 구간이 0 이다 — 임계만으로도 눌리긴 한다")

    # 임계를 올려 사라지는 구간은 «아슬아슬»이지 «잡음»이 아니다.
    gone = [r["name"] for r in rows
            if _ph(r, runtime_th) > 0 and _ph(r, hi) == 0]
    if gone:
        print(f"   · 임계를 올리면 사라지는 구간 — {' · '.join(gone)} "
              "(아슬아슬하게 반응한 것이지 깊은 문제가 아니다)")

    print(f"   · 🚨 **임계는 공짜가 아니다.** 올리면 놓침이 같이 오른다 — "
          "`eval_wakeword.py --sweep --holdout-only` 의 FRR 과 **같은 임계에서** 읽는다")

    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(json.dumps(
            {"wav": os.path.basename(wav), "model": os.path.basename(model_path),
             "energy_gate": gate, "runtime_threshold": runtime_th,
             "thresholds": list(THRESHOLDS), "rows": rows},
            ensure_ascii=False, indent=2))
        print(f"\n   → {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
