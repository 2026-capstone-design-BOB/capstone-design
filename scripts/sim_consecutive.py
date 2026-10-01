"""연속 N창 확인을 시뮬레이션한다 — **공짜 지렛대**가 남았는지 본다.

    conda activate pluiz
    python scripts/sim_consecutive.py data/soak_voice_<날짜>.wav

🔑 **무엇인가** — 지금은 창 하나가 임계를 넘으면 바로 깨운다. 여기서는
   **연속으로 N 창이 넘을 때만** 깨운다. 창이 2초짜리고 0.6초마다 뜨므로,
   사람이 「플루이즈」라고 부르면 그 소리가 **여러 창에 걸쳐** 들어간다.
   반면 스치는 잡음·말소리는 **한 창만** 건드리기 쉽다.

🔑 **왜 「공짜」인가** — 모델을 다시 돌리지 않는다. 이미 계산한 확률을 **어떻게 읽을지**만
   바꾼다. Whisper 2단계(§4)는 깰 때마다 받아적기를 한 번 더 돌려야 했고, 그래서
   비싸고 느렸다. 이건 비용이 0 이다.

🚨 **공짜가 아닌 것 하나** — 늦어진다. N=2 면 **0.6초**, N=3 이면 1.2초 뒤에 깨운다.
   사용자가 부르고 기다리는 시간이 그만큼 는다.

출력은 언제나 **오탐과 놓침을 같이** 낸다. 하나만 보면 «아무 때도 안 깨는 모델»이 이긴다.
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

THRESHOLDS = (0.50, 0.62, 0.70, 0.80, 0.90, 0.95)
NEEDS = (1, 2, 3)


def fire_times(frames, th, need, cooldown, gate):
    """연속 `need` 창이 임계를 넘으면 깨운다. 쿨다운은 런타임과 같게 적용한다.

    🔑 **관문에 막힌 창은 연속을 끊는다.** 런타임이 그 창을 모델에 넣지 않으므로
      «넘지 못한 것»과 같게 취급해야 시뮬레이션이 런타임을 예측한다.
    """
    out, run, last = [], 0, -1e9
    for (t, e, q) in frames:
        if q is None or e < gate or q < th:
            run = 0
            continue
        run += 1
        if run >= need and (t - last) >= cooldown:
            out.append(t)
            last = t
            run = 0
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="연속 N창 확인을 시뮬레이션한다")
    ap.add_argument("soak", nargs="+", help="긴 녹음 (오탐 쪽)")
    ap.add_argument("--model", default=None, help="비교할 모델 (기본: 런타임)")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)

    from scripts.eval_wakeword import read_wav, scan, load_sessions, SAMPLE_RATE
    from services.wakeword import (
        KwsModel, MODEL_PATH, kws_energy_floor, COOLDOWN_SEC, WINDOW_SECONDS)

    gate = kws_energy_floor(0.0015)
    mp = a.model or MODEL_PATH
    model = KwsModel(mp)

    soaks = []
    for rel in a.soak:
        p = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
        audio = read_wav(p)
        soaks.append({"name": os.path.basename(p),
                      "hours": len(audio) / SAMPLE_RATE / 3600.0,
                      "frames": scan(model, audio, 0.0)})
    sessions, _ = load_sessions(holdout_only=True)
    for s in sessions:
        s["frames"] = scan(model, read_wav(s["wav"]), 0.0)
    n_calls = sum(1 for s in sessions
                  for sg in s["segments"] if sg.get("label") == "positive")

    print()
    print(f"[모델] {os.path.basename(mp)} · 관문 {gate} · 쿨다운 {COOLDOWN_SEC}s")
    print(f"[소크] {' · '.join(sk['name'] for sk in soaks)}  "
          f"{sum(sk['hours'] for sk in soaks)*60:.0f}분")
    print(f"[호출] 처음 보는 화자 {len(sessions)}세션 · {n_calls}회")
    print()

    rows = []
    hours = sum(sk["hours"] for sk in soaks)
    for need in NEEDS:
        for th in THRESHOLDS:
            fa = sum(len(fire_times(sk["frames"], th, need, COOLDOWN_SEC, gate))
                     for sk in soaks)
            hit = 0
            for s in sessions:
                fires = fire_times(s["frames"], th, need, COOLDOWN_SEC, gate)
                got = set()
                for t in fires:
                    w0, w1 = t - WINDOW_SECONDS, t
                    best, best_ov = None, 0.0
                    for i, sg in enumerate(s["segments"]):
                        lo = max(w0, float(sg["start"]))
                        hi = min(w1, float(sg["end"]))
                        ov = max(0.0, hi - lo)
                        if ov > best_ov:
                            best, best_ov = i, ov
                    if best is not None and s["segments"][best].get("label") == "positive":
                        got.add(best)
                hit += len(got)
            rows.append({"need": need, "threshold": th,
                         "fa": fa, "fa_hr": fa / hours,
                         "hit": hit, "calls": n_calls,
                         "frr": (n_calls - hit) / n_calls if n_calls else float("nan"),
                         "delay": round((need - 1) * 0.6, 1)})

    head = f"{'연속':>5}{'임계':>7}{'FA/시간':>10}{'놓침':>9}{'늦어짐':>9}"
    print(head)
    print("─" * len(head))
    for r in rows:
        mark = ""
        if r["fa_hr"] <= 1 and r["frr"] <= 0.10:
            mark = "  ✅ 목표 둘 다"
        elif r["fa_hr"] <= 1:
            mark = "  🟡 오탐은 목표"
        print(f"{r['need']:>5}{r['threshold']:>7.2f}{r['fa_hr']:>10.1f}"
              f"{r['frr']*100:>8.1f}%{r['delay']:>8.1f}s{mark}")
    print()
    print("   🔴 전시회 목표 — 오탐 ≤ 1회/시간 · 놓침 ≤ 10%")
    print("   🚨 놓침은 **조용한 방 30cm** 녹음으로 잰 값이다 — 실제 거리에서는 더 나쁘다")
    print()

    ok = [r for r in rows if r["fa_hr"] <= 1 and r["frr"] <= 0.10]
    if ok:
        b = min(ok, key=lambda r: r["frr"])
        print(f"✅ 목표를 둘 다 만족하는 칸이 있다 — 연속 {b['need']} · 임계 {b['threshold']}")
    else:
        # 오탐 목표만이라도 되는 칸 중 놓침이 가장 작은 것
        near = [r for r in rows if r["fa_hr"] <= 1]
        if near:
            b = min(near, key=lambda r: r["frr"])
            print(f"🟡 오탐 1회/시간 이하는 **연속 {b['need']} · 임계 {b['threshold']}** 에서 되는데, "
                  f"놓침이 {b['frr']*100:.1f}% 다 (목표 10%)")
        else:
            b = min(rows, key=lambda r: r["fa_hr"])
            print(f"🔴 어느 칸도 오탐 1회/시간에 못 간다. 가장 낮은 칸이 "
                  f"연속 {b['need']} · 임계 {b['threshold']} 에서 {b['fa_hr']:.1f}회/시간 "
                  f"(놓침 {b['frr']*100:.1f}%)")

    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(
            json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
