"""2단계 확인을 **코드를 안 고치고** 먼저 재 본다 (M7 §4-D).

    conda activate pluiz
    python scripts/sim_two_stage.py data/soak_voice_<날짜>.wav

🔑 **무엇을 재나** — 지금은 KWS 가 깨면 바로 깨운다. 2단계는 그 2초를 **한 번 더**
   Whisper 로 받아적어 「플루이즈」가 실제로 들어 있을 때만 깨우는 것이다.
   그러면 ① 헛깨어남이 얼마나 줄고 ② 놓침이 얼마나 느는가 — **둘 다** 재야 한다.
   하나만 재면 «오탐을 없앴다»면서 아무 때도 안 깨는 모델이 이긴다.

🚨 **왜 먼저 재 보나** — 2단계를 넣는 것은 런타임 변경이고, 학습 자료 배선은
   반나절이다. **어느 쪽이 더 큰지 모르고 반나절을 쓰지 않는다.**
   여기서는 런타임을 한 줄도 안 고치고 숫자만 뽑는다.

🔒 **런타임과 같은 판정기를 쓴다** — `services.wakeword.is_wake()` 를 그대로 부른다.
   여기서 따로 매칭을 짜면 시뮬레이션이 런타임을 예측하지 못한다.
   (`looks_hallucinated` 환각 거르기까지 그 안에 들어 있다.)

⚠️ 2단계는 공짜가 아니다 — 깰 때마다 Whisper 가 한 번 더 돈다. 그 비용은
   **깬 횟수에만** 붙으므로, 오탐이 많을수록 비싸진다. 지금이 바로 그 상황이다.
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

THRESHOLDS = (0.62, 0.80, 0.90)


def _whisper():
    from faster_whisper import WhisperModel
    size = os.getenv("WAKEWORD_WHISPER_SIZE", "base")
    print(f"[2단계] Whisper {size} 로드 중 …")
    return WhisperModel(size, device="cpu", compute_type="int8")


def confirm(wm, chunk):
    """런타임의 `_transcribe` 와 **같은 인자**로 받아적고 같은 판정기를 쓴다."""
    from services.wakeword import is_wake, NOISE_PATTERNS
    segments, _ = wm.transcribe(
        chunk, language="ko", beam_size=1, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 200},
        condition_on_previous_text=False, hotwords=None)
    text = " ".join(s.text for s in segments).strip()
    if not text or NOISE_PATTERNS.match(text):
        return False, text
    return is_wake(text), text


def main(argv=None):
    ap = argparse.ArgumentParser(description="2단계 확인을 시뮬레이션한다")
    ap.add_argument("soak", nargs="+", help="긴 녹음 (오탐 쪽)")
    ap.add_argument("--json", default="", help="결과 저장")
    ap.add_argument("--max-fires", type=int, default=400,
                    help="오탐 쪽에서 확인할 최대 개수 (시간이 너무 오래 걸릴 때)")
    a = ap.parse_args(argv)

    import numpy as np
    from scripts.eval_wakeword import read_wav, scan, replay, load_sessions, SAMPLE_RATE
    from services.wakeword import (
        KwsModel, MODEL_PATH, kws_energy_floor, WINDOW_SECONDS, WAKE_WORDS)

    gate = kws_energy_floor(0.0015)
    model = KwsModel(MODEL_PATH)
    wm = _whisper()
    print(f"[2단계] 감지 대상 {len(WAKE_WORDS)}개 · 창 {WINDOW_SECONDS}s · 관문 {gate}")
    print()

    def window_at(audio, t):
        """깬 시각 t 의 창 = [t-2.0, t]. 런타임이 모델에 넣은 바로 그 구간이다."""
        i1 = int(round(t * SAMPLE_RATE))
        i0 = max(0, i1 - int(WINDOW_SECONDS * SAMPLE_RATE))
        return audio[i0:i1]

    # ── ① 오탐 쪽 — 긴 녹음 ────────────────────────────────────────
    soaks = []
    for rel in a.soak:
        p = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
        audio = read_wav(p)
        soaks.append({"name": os.path.basename(p), "audio": audio,
                      "hours": len(audio) / SAMPLE_RATE / 3600.0,
                      "frames": scan(model, audio, gate)})
        print(f"[소크] {soaks[-1]['name']}  {soaks[-1]['hours']*60:.1f}분")

    # ── ② 놓침 쪽 — 홀드아웃 화자의 실제 호출 ──────────────────────
    sessions, _ = load_sessions(holdout_only=True)
    for s in sessions:
        s["audio"] = read_wav(s["wav"])
        s["frames"] = scan(model, s["audio"], gate)
    n_calls = sum(1 for s in sessions
                  for sg in s["segments"] if sg.get("label") == "positive")
    print(f"[호출] 처음 보는 화자 {len({s['speaker'] for s in sessions})}명 · 호출 {n_calls}회")
    print()

    rows = []
    for th in THRESHOLDS:
        t0 = time.time()

        # 오탐: 깬 것 전부를 Whisper 에 다시 묻는다
        fa_before = fa_after = 0
        heard_kept = []
        for sk in soaks:
            fires = replay(sk["frames"], th, gate)
            fa_before += len(fires)
            for t in fires[:a.max_fires]:
                ok, text = confirm(wm, sk["audio"][
                    max(0, int(round(t * SAMPLE_RATE)) - int(WINDOW_SECONDS * SAMPLE_RATE)):
                    int(round(t * SAMPLE_RATE))])
                if ok:
                    fa_after += 1
                    heard_kept.append(text[:40])
        hours = sum(sk["hours"] for sk in soaks)

        # 놓침: 호출을 맞힌 깨어남만 Whisper 에 묻는다.
        # 🔑 **2단계가 거절하면 그 호출은 놓친 것이 된다.** 그게 2단계의 대가다.
        hit_before = hit_after = 0
        for s in sessions:
            fires = replay(s["frames"], th, gate)
            segs = s["segments"]
            got_before, got_after = set(), set()
            for t in fires:
                w0, w1 = t - WINDOW_SECONDS, t
                best, best_ov = None, 0.0
                for i, sg in enumerate(segs):
                    lo, hi = max(w0, float(sg["start"])), min(w1, float(sg["end"]))
                    ov = max(0.0, hi - lo)
                    if ov > best_ov:
                        best, best_ov = i, ov
                if best is None or segs[best].get("label") != "positive":
                    continue
                got_before.add(best)
                if best in got_after:
                    continue
                ok, _text = confirm(wm, window_at(s["audio"], t))
                if ok:
                    got_after.add(best)
            hit_before += len(got_before)
            hit_after += len(got_after)

        frr_before = (n_calls - hit_before) / n_calls if n_calls else float("nan")
        frr_after = (n_calls - hit_after) / n_calls if n_calls else float("nan")
        rows.append({
            "threshold": th,
            "fa_before": fa_before, "fa_after": fa_after, "hours": hours,
            "fa_hr_before": fa_before / hours, "fa_hr_after": fa_after / hours,
            "hit_before": hit_before, "hit_after": hit_after, "calls": n_calls,
            "frr_before": frr_before, "frr_after": frr_after,
            "kept_samples": heard_kept[:8],
            "sec": round(time.time() - t0, 1),
        })
        r = rows[-1]
        print(f"  임계 {th:.2f}  헛깨어남 {r['fa_hr_before']:7.1f} → {r['fa_hr_after']:6.1f}/시간"
              f"   놓침 {frr_before*100:5.1f}% → {frr_after*100:5.1f}%   ({r['sec']:.0f}초)")

    print()
    head = f"{'임계':>6}{'헛깨어남(전)':>13}{'헛깨어남(후)':>13}{'놓침(전)':>11}{'놓침(후)':>11}"
    print(head)
    print("─" * len(head))
    for r in rows:
        print(f"{r['threshold']:>6.2f}{r['fa_hr_before']:>13.1f}{r['fa_hr_after']:>13.1f}"
              f"{r['frr_before']*100:>10.1f}%{r['frr_after']*100:>10.1f}%")
    print()
    print("   🔴 전시회 목표 — 헛깨어남 ≤ 1회/시간 · 놓침 ≤ 10%")
    print()

    best = min(rows, key=lambda r: r["fa_hr_after"])
    print("🔑 읽는 법")
    print(f"   · 2단계를 걸면 헛깨어남이 가장 낮은 칸은 임계 {best['threshold']:.2f} 에서 "
          f"**{best['fa_hr_after']:.1f}회/시간** (놓침 {best['frr_after']*100:.1f}%)")
    if best["fa_hr_after"] > 1:
        print("   · 🚨 **그래도 목표(1회/시간)에는 못 간다.** 2단계만으로는 모자라고 "
              "학습 자료도 같이 고쳐야 한다")
    else:
        print("   · ✅ 목표 안에 든다 — 놓침이 견딜 만한지만 보면 된다")
    for r in rows:
        if r["kept_samples"]:
            print(f"   · 임계 {r['threshold']:.2f} 에서 2단계를 **통과해 버린** 소리: "
                  f"{r['kept_samples'][:3]}")
            break
    print("   · ⚠️ 2단계는 깰 때마다 Whisper 가 한 번 더 돈다 — "
          "오탐이 많을수록 비싸다. 지금이 그 상황이다")

    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(
            json.dumps(rows, ensure_ascii=False, indent=2))
        print(f"\n   → {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
