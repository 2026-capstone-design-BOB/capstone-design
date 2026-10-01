"""소크 오디오를 **구간별로** 채점한다 — 「무엇에 깨는가」를 가른다.

    conda activate pluiz
    python scripts/soak_by_phase.py data/soak_voice_<날짜>.wav

🔑 **왜 나눠서 재나** — 섞어서 받으면 «264회/시간» 하나가 나오는데, 그 숫자는
   **무엇을 고쳐야 하는지 말해 주지 않는다.** 조용할 때도 깨는지, 내 목소리에 깨는지,
   음악에 깨는지, 남의 말소리에 깨는지는 손댈 곳이 **각각 다르다**:

     조용히      에 깬다 → 말소리 문제가 아니라 **마이크 잡음**이다. 에너지 관문을 본다
     혼잣말      에 깬다 → 학습 음성에 **내 평소 말**이 모자라다
     음악        에 깬다 → 학습 음성에 **음악**이 모자라다
     남의 말소리  에 깬다 → 학습 음성이 **TTS 에 치우쳐** 있다(실제 사람 목소리 부족)

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
    worst = max(rows, key=lambda r: r["fa"][runtime_th]["per_hour"]
                if r["fa"][runtime_th]["per_hour"] == r["fa"][runtime_th]["per_hour"] else -1)
    quiet = next((r for r in rows if "조용" in r["name"]), None)
    print("🔑 읽는 법")
    print(f"   · 가장 심한 구간은 **{worst['name']}** "
          f"({worst['fa'][runtime_th]['per_hour']:.1f}/시간 @ {runtime_th}) — 여기가 할 일이다")
    if quiet is not None:
        q = quiet["fa"][runtime_th]["per_hour"]
        if q >= 1:
            print(f"   · 🚨 **조용할 때도 {q:.1f}/시간 깬다** — 말소리 문제가 아니라 "
                  "마이크 잡음이다. 에너지 관문부터 본다")
        else:
            print(f"   · 조용할 때는 {q:.1f}/시간 — 🔑 **잡음이 아니라 소리에 반응하는 것**이다")
    print("   · 임계를 올려도 목표에 못 가면, 손댈 곳은 임계가 아니라 "
          "**학습 음성** 또는 **2단계 확인**이다")

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
