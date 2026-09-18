# -*- coding: utf-8 -*-
"""웨이크워드 평가 하네스 — **자를 먼저 만든다** (M7 1단계)

    python scripts/eval_wakeword.py                 # 라벨 녹음 전체 (FRR + FA)
    python scripts/eval_wakeword.py --holdout-only  # 학습에 안 들어간 화자만
    python scripts/eval_wakeword.py --sweep         # 임계 훑기 (FA/시간 ↔ FRR)
    python scripts/eval_wakeword.py --soak a.wav    # 라벨 없는 긴 오디오 → FA/시간만
    python scripts/eval_wakeword.py --energy-sweep  # 에너지 관문 훑기 (BL-23 완화책 ①)

## 왜 이 스크립트가 학습보다 먼저인가

2026-09-08에 **검증 95.0%** 를 보고 «끝났다»고 적었는데 실기는 **10번 중 2번**이었다.
자가 틀렸기 때문이다 — 검증셋도 전부 TTS라 **같은 편향을 공유하는 눈으로 채점**했다.
→ [design/M7_웨이크워드_재구축.md](../docs/design/M7_웨이크워드_재구축.md) §2-4

**기준선이 없으면 나아졌는지도 모른다.** 그래서 데이터를 모으기 전에 자부터 만든다.

## 🚨 이 자는 런타임과 **같은 것**이어야 한다

`services/wakeword.py`에서 **상수와 모델 클래스를 그대로 import** 한다. 여기에 값을
베껴 적으면 언젠가 한쪽만 바뀌고, 그러면 **런타임이 아닌 것을 재는 자**가 된다.
복제한 것은 감지 루프의 «순서»뿐이다 — 창 밀기 → 홉 → **에너지 관문** → **쿨다운** → 추론.

## 정확도(%)를 쓰지 않는다

웨이크워드는 클래스 불균형이 극단적이라 정확도는 언제나 99%가 나온다(95.0%가 20%였던
이유다). 업계 표준대로 **FA/시간을 고정하고 그때의 FRR** 로 적는다.

| 지표 | 뜻 | 전시회 목표 |
|---|---|---|
| FA / 시간 | 안 불렀는데 깨어난 횟수 | ≤ 1회 |
| FRR | 불렀는데 안 깨어난 비율 | ≤ 10% |

## ⚠️ 건너뛰지 않는다

의존성이 없으면 **조용히 건너뛰고 «통과»라고 말하지 않는다.** 분명히 말하고 죽는다
— 그게 [BL-59](../docs/BACKLOG.md)로 적어 둔 실패 모양이다.
"""
import argparse
import io
import json
import os
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import numpy as np
except ImportError as e:                                     # noqa: BLE001
    sys.exit(f"[eval] FATAL: numpy 없음 ({e})")

try:
    from services.wakeword import (
        KwsModel, MODEL_PATH, SAMPLE_RATE,
        WINDOW_SAMPLES, HOP_SAMPLES, WINDOW_SECONDS, HOP_SECONDS,
        COOLDOWN_SEC, kws_threshold, kws_energy_floor, rms,
    )
except SystemExit:
    # services/wakeword.py 는 의존성이 없으면 _die() 로 죽는다. 그 메시지가 이미 떴다.
    sys.exit("[eval] FATAL: services/wakeword.py 를 불러오지 못했다. "
             "`pluiz` 환경으로 돌리고 있는지 확인할 것 (base 에는 없다)")

RAW_DIR  = os.path.join(ROOT, "data", "wakeword_raw")
MANIFEST = os.path.join(ROOT, "data", "wakeword", "manifest.json")

# 양성으로 세지 않는 라벨 — 이 구간에서 깨면 오탐이다
NEGATIVE_LABELS = ("negative", "freetalk", "quiet")

#: 에너지 관문 후보 ([BL-23](../docs/BACKLOG.md) 완화책 ① — «관문을 올리면 오탐이 주는가»)
#:
#: 🔑 0.008 을 반드시 넣는다. **그 값이 옛 Whisper 관문**이고, 2026-09-08 실기에서
#:    «무음 스킵» 620번이 찍히는 동안 통과한 2번이 **둘 다 성공**했다 —
#:    모델이 못 알아들은 게 아니라 **들어볼 기회가 없었다**(services/wakeword.py 의 주석).
#:    올리는 쪽만 재고 그 대가를 안 재면 그 사고를 그대로 되풀이한다.
ENERGY_FLOORS = [0.0, 0.0015, 0.003, 0.005, 0.008, 0.012, 0.02, 0.03]


# ── 입력 ────────────────────────────────────────────────────────

def read_wav(path):
    """16kHz mono float32 로 읽는다. 다른 형식이면 **고치지 않고 거부한다.**

    리샘플링을 몰래 해 주면 «무엇을 쟀는지»가 흐려진다. 학습 파이프라인이
    16kHz를 전제하므로 여기서도 같은 전제를 지킨다.
    """
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1:
            raise ValueError(f"{os.path.basename(path)}: 채널 {w.getnchannels()} (모노가 아니다)")
        if w.getsampwidth() != 2:
            raise ValueError(f"{os.path.basename(path)}: {w.getsampwidth()*8}bit (16bit가 아니다)")
        if w.getframerate() != SAMPLE_RATE:
            raise ValueError(f"{os.path.basename(path)}: {w.getframerate()}Hz ({SAMPLE_RATE}Hz가 아니다)")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def trained_speakers():
    """학습에 들어간 화자 집합. manifest 에 없는 녹음은 **한 번도 안 들어간 것**이다."""
    if not os.path.exists(MANIFEST):
        return set(), False
    m = json.load(io.open(MANIFEST, encoding="utf-8"))
    names = set()
    for s in m.get("sessions", []):
        if not s.get("holdout", False):          # holdout=true 는 학습에서 뺀 것이다
            names.add(s.get("speaker", ""))
    return names, True


def load_sessions(holdout_only):
    """`data/wakeword_raw/` 의 (wav, json) 쌍을 모은다."""
    trained, have_manifest = trained_speakers()
    out = []
    for fn in sorted(os.listdir(RAW_DIR)) if os.path.isdir(RAW_DIR) else []:
        if not fn.endswith(".wav"):
            continue
        meta_path = os.path.join(RAW_DIR, fn[:-4] + ".json")
        if not os.path.exists(meta_path):
            print(f"[eval] 건너뜀 — 라벨 없음: {fn}")
            continue
        meta = json.load(io.open(meta_path, encoding="utf-8"))
        speaker = meta.get("speaker", "?")
        is_holdout = speaker not in trained
        if holdout_only and not is_holdout:
            continue
        out.append({
            "wav": os.path.join(RAW_DIR, fn),
            "speaker": speaker,
            "place": meta.get("place", ""),
            "holdout": is_holdout,
            "segments": meta.get("segments", []),
            "duration": float(meta.get("durationSec", 0.0)),
        })
    return out, have_manifest


# ── 감지 루프 복제 ──────────────────────────────────────────────

def scan(model, audio, energy_gate):
    """런타임과 **같은 순서**로 훑으며 창마다 (시각, 에너지, 확률)을 모은다.

    🔑 임계는 여기서 적용하지 않는다. 확률을 한 번만 계산해 두면
    임계 훑기가 공짜가 된다 — 쿨다운은 임계마다 다시 재생하면 된다
    (추론을 건너뛰는 것은 오디오를 바꾸지 않으므로 결과가 같다).
    """
    window = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
    frames = []
    pos = 0
    n = len(audio)
    while pos < n:
        take = min(HOP_SAMPLES, n - pos)
        chunk = audio[pos:pos + take]
        window[:-take] = window[take:]
        window[-take:] = chunk
        pos += take
        t = pos / SAMPLE_RATE                       # 창의 오른쪽 끝 = 런타임의 «지금»
        e = rms(window)
        if e < energy_gate:
            frames.append((t, e, None))             # 관문에서 막혔다 — 깰 수 없다
            continue
        frames.append((t, e, model.probability(window)))
    return frames


def replay(frames, threshold, floor=0.0):
    """임계 하나로 쿨다운까지 재생해 «깬 시각» 목록을 만든다.

    `floor` 는 **에너지 관문을 사후에 올려 보는 것**이다. 순서가 런타임과 같아야 하므로
    (창 → 관문 → 쿨다운 → 추론) **관문에서 막힌 창은 쿨다운도 건드리지 않는다.**
    관문을 올리면 그만큼 창이 사라질 뿐 남은 창의 확률은 바뀌지 않는다 —
    추론을 건너뛰는 것은 오디오를 바꾸지 않기 때문이다. 그래서 훑기가 공짜다.
    """
    fires, last = [], -1e9
    for t, e, pr in frames:
        if pr is None or e < floor:
            continue
        if t - last < COOLDOWN_SEC:                 # 런타임은 여기서 추론 자체를 건너뛴다
            continue
        if pr >= threshold:
            fires.append(t)
            last = t
    return fires


# ── 채점 ────────────────────────────────────────────────────────

def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def score(sessions_frames, threshold, floor=0.0):
    """FRR 과 FA 를 센다.

    깬 시각 t 의 창은 [t-2.0, t] 다. 그 창과 **가장 많이 겹치는 구간**에 귀속시킨다 —
    창이 구간 경계를 넘나들기 때문에 «t 가 어느 구간에 있나»로 세면 한 칸씩 밀린다.
    """
    pos_total = pos_hit = fa = 0
    neg_seconds = 0.0
    fa_by = {k: 0 for k in NEGATIVE_LABELS}
    sec_by = {k: 0.0 for k in NEGATIVE_LABELS}
    per = []
    for s in sessions_frames:
        fires = replay(s["frames"], threshold, floor)
        segs = s["segments"]
        hit = set()
        sess_fa = 0
        for t in fires:
            w0, w1 = t - WINDOW_SECONDS, t
            best, best_ov = None, 0.0
            for i, sg in enumerate(segs):
                ov = overlap(w0, w1, float(sg["start"]), float(sg["end"]))
                if ov > best_ov:
                    best, best_ov = i, ov
            if best is not None and segs[best].get("label") == "positive":
                hit.add(best)
            else:
                sess_fa += 1                        # 음성 구간이거나, 어느 구간도 아닌 곳
                lab = segs[best].get("label") if best is not None else None
                if lab in fa_by:
                    fa_by[lab] += 1
        p_total = sum(1 for sg in segs if sg.get("label") == "positive")
        n_sec = sum(float(sg["end"]) - float(sg["start"])
                    for sg in segs if sg.get("label") in NEGATIVE_LABELS)
        for sg in segs:
            if sg.get("label") in sec_by:
                sec_by[sg["label"]] += float(sg["end"]) - float(sg["start"])
        pos_total += p_total
        pos_hit += len(hit)
        fa += sess_fa
        neg_seconds += n_sec
        per.append({
            "speaker": s["speaker"], "holdout": s["holdout"],
            "pos_total": p_total, "pos_hit": len(hit),
            "fa": sess_fa, "neg_sec": n_sec,
        })
    frr = (pos_total - pos_hit) / pos_total if pos_total else float("nan")
    fa_hr = fa / (neg_seconds / 3600.0) if neg_seconds > 0 else float("nan")
    return {
        "threshold": threshold, "energy_floor": floor,
        "pos_total": pos_total, "pos_hit": pos_hit,
        "frr": frr, "fa": fa, "neg_sec": neg_seconds, "fa_per_hour": fa_hr,
        "fa_by_label": fa_by, "sec_by_label": sec_by,
        "fa_per_hour_by_label": {
            k: (fa_by[k] / (sec_by[k] / 3600.0) if sec_by[k] > 0 else float("nan"))
            for k in NEGATIVE_LABELS
        },
        "per_session": per,
    }


# ── 출력 ────────────────────────────────────────────────────────

def pct(x):
    return "—" if x != x else f"{x*100:.1f}%"


def num(x):
    return "—" if x != x else f"{x:.1f}"


def main():
    ap = argparse.ArgumentParser(description="웨이크워드 평가 하네스 (M7 1단계)")
    ap.add_argument("--model", default=MODEL_PATH)
    ap.add_argument("--threshold", type=float, default=None, help="기본값은 .env 의 런타임 임계")
    ap.add_argument("--holdout-only", action="store_true", help="학습에 안 들어간 화자만")
    ap.add_argument("--sweep", action="store_true", help="임계 훑기 — FA/시간 ↔ FRR")
    ap.add_argument("--soak", nargs="+", metavar="WAV", help="라벨 없는 긴 오디오 → FA/시간만")
    ap.add_argument("--energy-sweep", action="store_true",
                    help="에너지 관문 훑기 — 관문을 올리면 오탐이 주는가 (BL-23 완화책 ①)")
    ap.add_argument("--json", metavar="OUT", help="결과를 JSON 으로 저장")
    a = ap.parse_args()

    th_default = kws_threshold() if a.threshold is None else a.threshold
    gate = kws_energy_floor(0.008)

    print(f"[eval] 모델 {os.path.relpath(a.model, ROOT)}")
    model = KwsModel(a.model)
    print(f"[eval] 학습된 말 «{model.wake_word}» · 창 {WINDOW_SECONDS}s · 홉 {HOP_SECONDS}s "
          f"· 쿨다운 {COOLDOWN_SEC}s")
    print(f"[eval] 에너지 관문 {gate:.4f} · 임계 {th_default:.2f}  ← 런타임에서 그대로 가져왔다")

    # 🔑 관문을 훑으려면 **관문에 막히지 않은 상태**의 확률이 필요하다. 그래서 스캔은 0으로
    #    돌려 전부 계산해 두고, 관문은 재생할 때 적용한다(`replay` 의 `floor`). 추론이 늘지만
    #    훑기가 공짜가 되고, **지금 관문에서의 값이 기준선과 같은지로 검산도 된다.**
    scan_gate = 0.0 if a.energy_sweep else gate
    if a.energy_sweep:
        print(f"[eval] 🔍 관문 훑기 — 스캔은 관문 0 으로 돈다(그만큼 느리다). "
              f"재생할 때 {', '.join(f'{f:.4f}' for f in ENERGY_FLOORS)} 를 적용한다")
    print()

    # ── 소크 모드: 라벨이 없다. 전부 «안 불렀다»로 보고 FA/시간만 센다 ──
    if a.soak:
        total_sec = 0.0
        frames_all = []
        for p in a.soak:
            audio = read_wav(p)
            fr = scan(model, audio, scan_gate)
            dur = len(audio) / SAMPLE_RATE
            total_sec += dur
            frames_all.append(fr)
            print(f"  {os.path.basename(p):40s} {dur/60:6.1f}분  "
                  f"깬 횟수 {len(replay(fr, th_default, gate if a.energy_sweep else 0.0)):3d}")
        if total_sec <= 0:
            sys.exit("[eval] FATAL: 오디오가 비어 있다")
        hours = total_sec / 3600.0

        # 🔑 훑기 모드에서는 스캔을 관문 0 으로 돌았으므로, **기준 숫자는 런타임 관문을
        #    다시 씌워서** 낸다. 안 그러면 «지금 값»이 아닌 것을 기준선이라고 부르게 된다.
        base_floor = gate if a.energy_sweep else 0.0

        def fa_at(th, floor=None):
            f = base_floor if floor is None else floor
            return sum(len(replay(fr, th, f)) for fr in frames_all)

        n = fa_at(th_default)
        print(f"\n  합계 {hours:.2f}시간 · 오탐 {n}회 → **FA/시간 {n/hours:.1f}**  (목표 ≤ 1)")
        print("\n🚨 이것이 «전시회에서 쓸 수 있는가»를 결정하는 숫자다.")

        out = {"mode": "soak", "files": list(a.soak), "hours": hours,
               "energy_gate": gate, "threshold_default": th_default,
               "fa": n, "fa_per_hour": n / hours}

        if a.sweep:
            # 확률은 이미 창마다 계산돼 있다 — 임계만 바꿔 재생하면 되므로 공짜다.
            print(f"\n── 임계 훑기 (긴 오디오 {hours:.2f}시간) ─────────────")
            print(f"{'임계':>6} {'오탐':>6} {'FA/시간':>9}")
            rows = []
            for th in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]:
                k = fa_at(th)
                rows.append({"threshold": th, "fa": k, "fa_per_hour": k / hours})
                mark = "  ← 지금" if abs(th - th_default) < 1e-9 else ""
                print(f"{th:>6.2f} {k:>6} {k/hours:>9.1f}{mark}")
            out["sweep"] = rows
            print("\n🔑 FRR(놓침)은 이 오디오로 못 잰다 — **부른 적이 없기 때문이다.**")
            print("   운용점을 고르려면 이 표를 `--sweep`(호출 모드)의 FRR 표와 **같은 임계에서** 읽는다.")

        if a.energy_sweep:
            print(f"\n── 에너지 관문 훑기 (긴 오디오 {hours:.2f}시간 · 임계 {th_default:.2f} 고정) ──")
            print("   «관문을 올리면 오탐이 주는가» — BL-23 완화책 ①")
            print(f"{'관문':>8} {'막힌 창':>9} {'오탐':>6} {'FA/시간':>9}")
            rows = []
            n_win = sum(len(fr) for fr in frames_all)
            for fl in ENERGY_FLOORS:
                blocked = sum(1 for fr in frames_all for (_t, e, _p) in fr if e < fl)
                k = fa_at(th_default, fl)
                rows.append({"energy_floor": fl, "blocked_windows": blocked,
                             "windows": n_win, "fa": k, "fa_per_hour": k / hours})
                mark = "  ← 지금" if abs(fl - gate) < 1e-9 else ""
                print(f"{fl:>8.4f} {blocked*100.0/n_win:>8.1f}% {k:>6} "
                      f"{k/hours:>9.1f}{mark}")
            out["energy_sweep"] = rows
            print("\n🔑 **이 표만 보고 관문을 올리면 안 된다.** 여기엔 «놓침»이 없다 —")
            print("   부른 적이 없는 오디오라 FRR 을 못 잰다. 대가는 라벨 녹음 쪽 표에 있다")
            print("   (`--soak` 없이 `--energy-sweep` 만 주면 그 표가 나온다).")

        if a.json:
            io.open(a.json, "w", encoding="utf-8").write(
                json.dumps(out, ensure_ascii=False, indent=2))
            print(f"\n[eval] 저장 → {a.json}")
        return 0

    # ── 호출 모드: 라벨 녹음 ──
    sessions, have_manifest = load_sessions(a.holdout_only)
    if not sessions:
        sys.exit("[eval] FATAL: 잴 녹음이 없다. data/wakeword_raw/ 에 (wav, json) 쌍이 필요하다"
                 + (" — --holdout-only 를 뺀다면 있을 수 있다" if a.holdout_only else ""))
    if not have_manifest:
        print("⚠️  manifest.json 이 없다 — 어느 화자가 학습에 들어갔는지 모른다. "
              "전부 «미학습»으로 표시된다\n")

    for s in sessions:
        audio = read_wav(s["wav"])
        s["frames"] = scan(model, audio, scan_gate)

    n_hold = sum(1 for s in sessions if s["holdout"])
    print(f"[eval] 녹음 {len(sessions)}개 · 그중 **미학습 화자 {n_hold}명**"
          f"{' ← 이 숫자가 0이면 자가 거울이다' if n_hold == 0 else ''}\n")

    # 훑기 모드는 관문 0 으로 스캔했으니 기준 표에는 런타임 관문을 다시 씌운다 (소크와 같다)
    base_floor = gate if a.energy_sweep else 0.0
    base = score(sessions, th_default, base_floor)

    print(f"── 임계 {th_default:.2f} (런타임 값) ─────────────────────────")
    print(f"{'화자':<10} {'학습':<6} {'부름':>5} {'깸':>5} {'FRR':>8} {'오탐':>5} {'음성(초)':>9}")
    for r in base["per_session"]:
        r_frr = (r["pos_total"] - r["pos_hit"]) / r["pos_total"] if r["pos_total"] else float("nan")
        print(f"{r['speaker']:<10} {'미학습' if r['holdout'] else '학습됨':<6} "
              f"{r['pos_total']:>5} {r['pos_hit']:>5} {pct(r_frr):>8} "
              f"{r['fa']:>5} {r['neg_sec']:>9.1f}")
    print("-" * 58)
    print(f"{'합계':<10} {'':<6} {base['pos_total']:>5} {base['pos_hit']:>5} "
          f"{pct(base['frr']):>8} {base['fa']:>5} {base['neg_sec']:>9.1f}")
    print(f"\n  FRR        {pct(base['frr'])}   (목표 ≤ 10%)")
    print(f"  FA / 시간  {num(base['fa_per_hour'])}   (목표 ≤ 1회)")

    # 🚨 라벨을 안 쪼개고 이 숫자 하나만 적으면 그게 «숫자가 거짓말하는» 자리다.
    #    negative 는 «블루투스»·«플루트»처럼 **일부러 헷갈리게 만든 말**이고,
    #    freetalk 는 그냥 자유 발화다. 둘을 섞으면 어느 쪽도 아닌 값이 나온다.
    lbl_ko = {"negative": "헷갈리는 말", "freetalk": "자유 발화", "quiet": "무음"}
    print(f"\n  ── 오탐을 라벨별로 쪼갠다 ──────────────────")
    print(f"  {'구간':<12} {'길이(초)':>9} {'오탐':>5} {'FA/시간':>9}")
    for k in NEGATIVE_LABELS:
        print(f"  {lbl_ko[k]:<12} {base['sec_by_label'][k]:>9.1f} "
              f"{base['fa_by_label'][k]:>5} {num(base['fa_per_hour_by_label'][k]):>9}")
    print(f"\n  🚨 위의 «FA/시간 {num(base['fa_per_hour'])}»를 그대로 인용하지 말 것 —"
          f" 표본이 {base['neg_sec']/60:.1f}분이고,")
    print("     «헷갈리는 말» 구간은 오탐을 유도하려고 만든 것이라 실제 생활 소리가 아니다.")
    print("     ⚠️ 전시회에서 쓸 수 있는가를 결정하는 숫자는 --soak(긴 오디오)로만 나온다.")

    out = {"threshold_default": th_default, "energy_gate": gate, "baseline": base}

    if a.sweep:
        print(f"\n── 임계 훑기 — «FA/시간을 고정하고 그때의 FRR» ──────────")
        print(f"{'임계':>6} {'FRR':>8} {'깸/부름':>10} {'오탐':>5} {'FA/시간':>9}")
        rows = []
        for th in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]:
            r = score(sessions, th)
            rows.append({k: v for k, v in r.items() if k != "per_session"})
            mark = "  ← 지금" if abs(th - th_default) < 1e-9 else ""
            print(f"{th:>6.2f} {pct(r['frr']):>8} "
                  f"{str(r['pos_hit']) + '/' + str(r['pos_total']):>10} "
                  f"{r['fa']:>5} {num(r['fa_per_hour']):>9}{mark}")
        out["sweep"] = rows

    if a.energy_sweep:
        # 🚨 여기가 «관문을 올리자»의 대가를 재는 자리다. 소크 쪽 표에는 놓침이 없다.
        print(f"\n── 에너지 관문 훑기 — **대가까지 같이 본다** (임계 {th_default:.2f} 고정) ──")
        print(f"{'관문':>8} {'막힌 창':>9} {'FRR':>8} {'깸/부름':>10} {'오탐':>5} {'FA/시간':>9}")
        n_win = sum(len(s["frames"]) for s in sessions)
        rows = []
        for fl in ENERGY_FLOORS:
            blocked = sum(1 for s in sessions for (_t, e, _p) in s["frames"] if e < fl)
            r = score(sessions, th_default, fl)
            r["blocked_windows"] = blocked
            r["windows"] = n_win
            rows.append({k: v for k, v in r.items() if k != "per_session"})
            mark = "  ← 지금" if abs(fl - gate) < 1e-9 else ""
            print(f"{fl:>8.4f} {blocked*100.0/n_win:>8.1f}% {pct(r['frr']):>8} "
                  f"{str(r['pos_hit']) + '/' + str(r['pos_total']):>10} "
                  f"{r['fa']:>5} {num(r['fa_per_hour']):>9}{mark}")
        out["energy_sweep"] = rows
        print("\n🚨 **0.008 줄을 반드시 볼 것.** 그게 2026-09-08까지 쓰던 옛 관문이고,")
        print("   그때 실기에서 «무음 스킵» 620번 동안 통과한 2번이 **둘 다 성공**했다 —")
        print("   모델이 못 알아들은 게 아니라 **들어볼 기회가 없었다.** 관문은 그래서 내려갔다.")
        print("   🔑 이 표의 FRR 은 **조용한 방에서 30cm 거리로 녹음한 것**이라,")
        print("      실제 거리·목소리 크기에서는 더 나쁘다. 낙관적인 쪽 숫자다.")

    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(
            json.dumps(out, ensure_ascii=False, indent=2))
        print(f"\n[eval] 저장 → {a.json}")

    print("\n🔑 이 숫자는 **지금 모델에 대해서만** 잴 수 있다. "
          "모델을 바꾸고 나면 «개선 전»을 다시 못 잰다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
