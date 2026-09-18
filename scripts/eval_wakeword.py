# -*- coding: utf-8 -*-
"""웨이크워드 평가 하네스 — **자를 먼저 만든다** (M7 1단계)

    python scripts/eval_wakeword.py                 # 라벨 녹음 전체 (FRR + FA)
    python scripts/eval_wakeword.py --holdout-only  # 학습에 안 들어간 화자만
    python scripts/eval_wakeword.py --sweep         # 임계 훑기 (FA/시간 ↔ FRR)
    python scripts/eval_wakeword.py --soak a.wav    # 라벨 없는 긴 오디오 → FA/시간만
    python scripts/eval_wakeword.py --energy-sweep  # 에너지 관문 훑기 (BL-23 완화책 ①)
    python scripts/eval_wakeword.py --compare 후보.npz          # 🔴 되돌림 판단 (M7 6단계)
    python scripts/eval_wakeword.py --compare 후보.npz --soak 긴오디오.wav   # ← 이게 진짜 판정이다

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

## 🔴 `--compare` — **한 임계에서 비교하면 틀린 결론이 나온다** (M7 6단계)

2026-09-18에 실제로 겪었다. 후보 모델을 런타임 임계(0.80) 한 지점에서 재니
**FRR 19.2% → 6.7%** 였다. 거기서 멈췄으면 *«개선»* 이라고 적었을 것이다.
그런데 임계를 훑으니 **곡선이 교차했고**, 정작 우리가 필요한 쪽(FA 가 낮은 쪽)에서는
후보가 낫지 않았다.

🔑 **임계는 모델의 성질이 아니라 «운용점»이다.** 두 모델의 임계 0.80은 서로 다른
운용점이고, 임계 하나를 고르면 **어느 쪽이든 이기게 만들 수 있다.** 그건 비교가 아니다.
그래서 이 모드는 **FA/시간을 맞춰 놓고 그때의 FRR 을 비교한다.**

⚠️ **`--soak` 를 같이 주는 것이 진짜 판정이다.** 라벨 녹음의 FA/시간은 분모가 몇 분이고
절반이 **오탐을 유도하려고 만든 문장**이라 전시회 값이 아니다. 긴 오디오가 없으면
이 모드는 **그렇게 적고**, 판정을 «참고»라고 부른다.

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

#: `--compare` 가 훑는 임계. 9칸짜리 `--sweep` 보다 촘촘하다 —
#: **FA/시간을 맞추려면** 그 값에 닿는 임계를 찾아야 하기 때문이다.
COMPARE_THRESHOLDS = [round(0.30 + 0.01 * i, 2) for i in range(70)] + [0.995, 0.999]

#: 맞춰 놓고 비교할 FA/시간. **1회가 맨 앞인 것이 이 표의 요점이다** — 전시회 목표다.
COMPARE_FA_TARGETS = [1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 200.0]


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


def _curve(model, sessions, soak_paths):
    """모델 하나의 곡선. **프레임을 모델마다 새로 뜬다** — 확률이 다르기 때문이다."""
    for sess in sessions:
        sess["frames"] = scan(model, read_wav(sess["wav"]), 0.0)
    soak_frames, soak_hours = [], 0.0
    for sp in soak_paths or []:
        audio = read_wav(sp)
        soak_frames.append(scan(model, audio, 0.0))
        soak_hours += len(audio) / SAMPLE_RATE / 3600.0
    rows = []
    for th in COMPARE_THRESHOLDS:
        r = score(sessions, th, 0.0)
        fa_soak = (sum(len(replay(fr, th, 0.0)) for fr in soak_frames) / soak_hours
                   if soak_hours > 0 else float("nan"))
        rows.append({"threshold": th, "frr": r["frr"], "fa_rec": r["fa_per_hour"],
                     "fa_soak": fa_soak, "pos_hit": r["pos_hit"],
                     "pos_total": r["pos_total"]})
    return rows, soak_hours


def _best_under(rows, target, fa_key):
    """FA/시간이 `target` 이하인 운용점 중 **FRR 이 가장 낮은 것**.

    🔑 «임계를 올리면 FA 가 준다»가 대체로 맞지만 **단조롭지 않다** — 그래서
       «가장 높은 임계»가 아니라 **실제로 가장 좋은 점**을 고른다.
    못 가면 None 이다. 그 경우 «그 예산으로는 못 간다»고 적어야 한다.
    """
    ok = [r for r in rows if r[fa_key] == r[fa_key] and r[fa_key] <= target]
    return min(ok, key=lambda r: r["frr"]) if ok else None


def cmd_compare(base_model, cand_path, sessions, soak_paths, th_default):
    """두 모델을 **같은 FA/시간에서** 비교한다 (M7 6단계 · 되돌림 판단)."""
    print(f"[eval] 🔴 되돌림 판단 — 두 모델을 **같은 FA/시간에서** 비교한다")
    print(f"       기준 {os.path.relpath(base_model.path if hasattr(base_model, 'path') else MODEL_PATH, ROOT)}")
    print(f"       후보 {os.path.relpath(cand_path, ROOT)}")
    cand = KwsModel(cand_path)
    if cand.wake_word != base_model.wake_word:
        print(f"  ⚠️ 학습된 말이 다르다 — 기준 «{base_model.wake_word}» · 후보 «{cand.wake_word}»")

    # 🔑 후보가 «어떻게 학습됐는지»를 파일에서 읽어 찍는다. 기억이나 파일명에 안 기댄다.
    try:
        with np.load(cand_path, allow_pickle=False) as z:
            meta = {k: str(z[k]) for k in ("augment", "corpora", "speech_neg", "trained_at")
                    if k in z.files}
        if meta:
            print(f"       후보 학습 정보 — " + " · ".join(f"{k}={v}" for k, v in meta.items()))
        else:
            print("       ⚠️ 후보 npz 에 학습 정보가 없다 (예전 형식이다)")
    except Exception:                                        # noqa: BLE001
        pass

    if soak_paths:
        print(f"\n[eval] 긴 오디오 {len(soak_paths)}개를 **두 모델로 각각** 돈다 (그만큼 걸린다)")
    else:
        print("\n🚨 `--soak` 가 없다 — FA/시간이 **라벨 녹음**에서 나온다.")
        print("   그 분모는 몇 분이고 절반이 오탐을 유도하려고 만든 문장이다.")
        print("   **이 판정은 «참고»다.** 되돌림을 정하려면 긴 오디오를 같이 줘라.")

    print("\n  ① 기준 모델을 훑는다 …", flush=True)
    base_rows, hours = _curve(base_model, sessions, soak_paths)
    print("  ② 후보 모델을 훑는다 …", flush=True)
    cand_rows, _ = _curve(cand, sessions, soak_paths)

    fa_key = "fa_soak" if soak_paths else "fa_rec"
    src = f"긴 오디오 {hours:.2f}시간" if soak_paths else f"라벨 녹음(참고)"
    n_calls = base_rows[0]["pos_total"]

    print(f"\n── 같은 FA/시간에서의 FRR — FA 출처: {src} · 호출 {n_calls}회 ──")
    print(f"{'FA/시간':>8} | {'기준 FRR':>12} | {'후보 FRR':>12} | 판정")
    print("-" * 62)
    wins = {"cand": 0, "base": 0, "tie": 0}
    low_fa_verdict = None
    any_row = False
    for tgt in COMPARE_FA_TARGETS:
        b = _best_under(base_rows, tgt, fa_key)
        c = _best_under(cand_rows, tgt, fa_key)
        if b is None and c is None:
            print(f"{tgt:>8.0f} | {'못 간다':>12} | {'못 간다':>12} | 둘 다 이 예산으로 못 간다")
            continue
        any_row = True
        # 🔑 소수 셋째 자리까지 — 0.999 를 «1.00» 으로 적으면 **없는 임계**를 말하게 된다
        bs = f"{pct(b['frr'])} ({b['threshold']:.3f})" if b else "못 간다"
        cs = f"{pct(c['frr'])} ({c['threshold']:.3f})" if c else "못 간다"
        if b is None:
            verdict, who = "🟢 후보만 간다", "cand"
        elif c is None:
            verdict, who = "🔴 후보는 못 간다", "base"
        elif abs(b["frr"] - c["frr"]) < 1e-9:
            verdict, who = "= 같다", "tie"
        elif c["frr"] < b["frr"]:
            verdict, who = "🟢 후보가 낫다", "cand"
        else:
            verdict, who = "🔴 기준이 낫다", "base"
        wins[who] += 1
        if low_fa_verdict is None:
            low_fa_verdict = (tgt, who)          # 도달 가능한 **가장 낮은 FA** 에서의 판정
        print(f"{tgt:>8.0f} | {bs:>12} | {cs:>12} | {verdict}")

    print("\n── 판정 ──────────────────────────────────────")
    if not any_row:
        print("  ❌ **두 모델 다 어떤 FA 예산에도 못 간다.** 표를 넓히거나 자를 의심할 것")
        return 1
    goal = _best_under(cand_rows, 1.0, fa_key)
    goal_b = _best_under(base_rows, 1.0, fa_key)
    print(f"  전시회 목표(FA ≤ 1회/시간): "
          f"기준 {'FRR ' + pct(goal_b['frr']) if goal_b else '**못 간다**'} · "
          f"후보 {'FRR ' + pct(goal['frr']) if goal else '**못 간다**'}")
    print(f"  칸 수 — 후보 우세 {wins['cand']} · 기준 우세 {wins['base']} · 같음 {wins['tie']}")
    tgt, who = low_fa_verdict
    말 = {"cand": "**후보가 낫다**", "base": "**기준이 낫다**", "tie": "**둘이 같다**"}[who]
    print(f"  🔴 도달 가능한 가장 낮은 FA({tgt:.0f}회/시간)에서는 {말}.")
    if wins["cand"] and wins["base"]:
        print("  ⚠️ **곡선이 교차한다.** «전체적으로 낫다»고 적지 않는다 —")
        print("     우리가 필요한 쪽은 **FA 가 낮은 쪽**이고, 위 한 줄이 그 답이다.")

    # ── 🔴 권고 — 이 도구가 존재하는 이유다. «누가 나은가»에서 멈추지 않는다 ──
    #    M7 § 되돌림 기준: «FA/시간이 현행보다 나쁘면 즉시 되돌린다».
    #    그 기준에 **어느 임계에서 비교하는지가 없었고**, 그래서 여기서 정한다 —
    #    같은 FA 예산에 맞춰 놓고 FRR 이 나쁘면 나쁜 것이다.
    print()
    if wins["base"] and not wins["cand"]:
        print("  🚨 **되돌림 권고: 후보를 버린다.** 도달 가능한 모든 FA 예산에서 기준이 낫다.")
        print("     `git checkout services/wakeword_model.npz` (아직 안 바꿨다면 바꾸지 않는다)")
    elif wins["cand"] and not wins["base"]:
        print("  ✅ **채택 권고: 후보가 낫다.** 도달 가능한 모든 FA 예산에서 후보가 낫다.")
        print("     ⚠️ 그래도 **목표(FA ≤ 1)에 닿았는지는 따로 본다** — 위 첫 줄이 그 답이다.")
    else:
        print("  ⏸️ **자동으로 못 정한다.** 곡선이 교차하거나 판정이 엇갈린다 —")
        print("     **사람이 운용점을 먼저 고르고**(FA 예산을 정하고) 그 줄만 본다.")
    if not soak_paths:
        print("\n  🚨 **이 판정으로 되돌림을 정하지 않는다.** FA 출처가 라벨 녹음이다.")
        print("     `--soak <긴 오디오>` 를 같이 줘야 전시회 값이 나온다.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="웨이크워드 평가 하네스 (M7 1단계)")
    ap.add_argument("--model", default=MODEL_PATH)
    ap.add_argument("--threshold", type=float, default=None, help="기본값은 .env 의 런타임 임계")
    ap.add_argument("--holdout-only", action="store_true", help="학습에 안 들어간 화자만")
    ap.add_argument("--sweep", action="store_true", help="임계 훑기 — FA/시간 ↔ FRR")
    ap.add_argument("--soak", nargs="+", metavar="WAV", help="라벨 없는 긴 오디오 → FA/시간만")
    ap.add_argument("--energy-sweep", action="store_true",
                    help="에너지 관문 훑기 — 관문을 올리면 오탐이 주는가 (BL-23 완화책 ①)")
    ap.add_argument("--compare", metavar="후보.npz",
                    help="🔴 두 모델을 **같은 FA/시간에서** 비교한다 (M7 6단계 되돌림 판단). "
                         "--soak 를 같이 주는 것이 진짜 판정이다")
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

    # ── 비교 모드: 되돌림 판단. **FRR 은 라벨 녹음에서만 나온다** ──
    if a.compare:
        sessions, _have = load_sessions(a.holdout_only)
        if not sessions:
            sys.exit("[eval] FATAL: 잴 녹음이 없다 — FRR 을 못 재면 비교가 안 된다")
        model.path = a.model
        return cmd_compare(model, a.compare, sessions, a.soak, th_default)

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
