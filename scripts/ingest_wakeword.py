"""받아 온 녹음(wav + json)을 학습용 배열로 모은다 — M7 ②③

    conda activate pluiz
    python scripts/ingest_wakeword.py                  # data/wakeword_raw/ 를 읽는다
    python scripts/ingest_wakeword.py --list           # 누가 몇 개 보냈는지만 본다
    python scripts/ingest_wakeword.py --holdout 4      # 미학습 화자 4명을 떼어 둔다

입력 — `scripts/플루이즈_녹음.html` 이 만든 파일 쌍을 `data/wakeword_raw/` 에 넣는다.

    data/wakeword_raw/
      pluiz_오다영_20260918T142301.wav
      pluiz_오다영_20260918T142301.json   ← 언제 무엇을 말했는지

출력 — `data/wakeword/` (git 밖)

    positive.npy    「플루이즈」 구간만 이어 붙인 것
    negative.npy    🚨 **같은 마이크로 녹음한 «플루이즈가 아닌 말»**
    manifest.json   어느 화자가 어디에 들어갔는지 + 홀드아웃 지정
    wake_voice.npy  현행 `train_wakeword.py --user-audio` 가 먹는 형식(양성만)

## 🚨 왜 음성(negative)을 따로 모으는가 — 이 스크립트의 존재 이유

2026-09-09에 실제 녹음 143초를 **양성으로만** 넣고 학습했다. 검증은 멀쩡했는데
(감지 93.6% · 오탐 2.35%) **실기에서 아무 말에나 깨어났다.** 에너지 관문을 통과한
창의 86.7%를 「플루이즈」라고 답했다.

원인은 임계값이 아니라 **데이터셋 구성**이었다. 학습셋에서 «진짜 마이크 오디오»가
전부 양성이면 모델은 단어를 배울 이유가 없다 — **«합성음이냐 실제 마이크냐»만
구분해도 만점**이기 때문이다. 지름길을 놔두고 어려운 길로 가지 않는다.

**그래서 같은 마이크·같은 경로로 «플루이즈가 아닌 말»을 받아야 한다.**
녹음 페이지가 ②(비슷한 말)와 ③(자유 발화)을 함께 받는 이유이고,
이 스크립트가 라벨을 보고 둘을 갈라 주는 이유다.
→ [M7 §5-1](../docs/design/M7_웨이크워드_재구축.md) · docs/BACKLOG.md BL-23

## 🔒 홀드아웃은 «화자 단위»로 뗀다

M7 §5-2: *"홀드아웃은 학습과 «생성 과정»을 공유하지 않는다."*
같은 사람의 녹음이 학습과 검증에 나눠 들어가면 그건 검증이 아니라
**같은 편향의 거울**이다. `--holdout N` 은 **사람을 통째로** 뗀다.

## ⚠️ 이 스크립트는 판단하지 않는다

품질 판정은 녹음 페이지가 **녹음 직후에** 한다(사람이 그 자리에 있을 때만 다시 받을
수 있기 때문이다). 여기서는 **너무 조용한 구간만 버리고** 나머지는 그대로 싣는다.
버린 양은 항상 출력한다 — 조용히 버리면 «왜 데이터가 줄었지»를 나중에 못 푼다.
"""
import argparse
import json
import os
import sys
import wave

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(_ROOT, "data", "wakeword_raw")
OUT = os.path.join(_ROOT, "data", "wakeword")

SR = 16000          # scripts/wakeword_data.py · train_wakeword.py 와 같아야 한다
RMS_MIN = 0.006     # train_wakeword.build_dataset ③ 의 발화 구간 임계와 같은 값
PAD = 0.25          # 슬롯 경계에서 잘리지 않게 앞뒤로 조금 더 준다(초)


def read_wav(path: str) -> np.ndarray:
    """16bit PCM WAV → float32 [-1, 1]. 표준 라이브러리만 쓴다."""
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"16bit PCM이 아니다: {path}")
        n, ch, sr = w.getnframes(), w.getnchannels(), w.getframerate()
        raw = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        raw = raw.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        # 녹음 페이지가 16kHz로 내보내므로 정상 경로에서는 오지 않는다.
        # 다른 경로로 들어온 파일을 조용히 틀리게 쓰지 않으려고 막아 둔다.
        raise ValueError(f"샘플레이트가 {sr}다. {SR}만 받는다: {path}")
    return raw


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def cut(pcm: np.ndarray, seg: dict) -> np.ndarray:
    a = max(0, int((seg["start"] - PAD) * SR))
    b = min(len(pcm), int((seg["end"] + PAD) * SR))
    return pcm[a:b]


def load_pairs():
    """(json경로, wav경로) 쌍. 짝이 없으면 건너뛰고 **말한다.**"""
    if not os.path.isdir(RAW):
        print(f"✗ {RAW} 가 없습니다. 받은 파일을 여기에 넣어 주세요.")
        return []
    out, lonely = [], []
    for f in sorted(os.listdir(RAW)):
        if not f.endswith(".json"):
            continue
        wav = os.path.join(RAW, f[:-5] + ".wav")
        if os.path.exists(wav):
            out.append((os.path.join(RAW, f), wav))
        else:
            lonely.append(f)
    for f in lonely:
        print(f"  ⚠️  {f} — 짝이 되는 .wav 가 없습니다 (건너뜁니다)")
    return out


def main():
    ap = argparse.ArgumentParser(description="녹음본을 학습용 배열로 모은다")
    ap.add_argument("--list", action="store_true", help="누가 몇 개 보냈는지만 본다")
    ap.add_argument("--holdout", type=int, default=0,
                    help="미학습 화자 N명을 떼어 둔다 (M7 §5-2)")
    ap.add_argument("--seed", type=int, default=0, help="홀드아웃 선택 난수")
    args = ap.parse_args()

    pairs = load_pairs()
    if not pairs:
        print("받은 녹음이 없습니다.")
        return 1

    sessions = []
    for jp, wp in pairs:
        with open(jp, encoding="utf-8") as f:
            meta = json.load(f)
        sessions.append((meta, wp))

    # ── 사람별 현황 ────────────────────────────────────────────
    by_speaker: dict[str, list] = {}
    for meta, wp in sessions:
        by_speaker.setdefault(meta.get("speaker", "?"), []).append((meta, wp))

    print(f"\n받은 녹음 {len(sessions)}개 · 화자 {len(by_speaker)}명")
    for name, items in sorted(by_speaker.items()):
        places = {m.get("place", "?") for m, _ in items}
        total = sum(m.get("durationSec", 0) for m, _ in items)
        print(f"  · {name:<12} {len(items)}회 · {total/60:.1f}분 · {' / '.join(sorted(places))}")

    # 🔑 M7 §5-1 의 목표는 «20~30명»이다. 진행률을 항상 보여 준다 —
    #    임계 경로가 사람이라, 숫자를 봐야 더 모을지 말지 판단할 수 있다.
    n = len(by_speaker)
    print(f"\n  목표 20~30명 대비 **{n}명** " +
          ("✅ 충분합니다" if n >= 20 else f"— {20 - n}명 더 필요합니다"))
    if args.list:
        return 0

    # ── 홀드아웃: 사람을 통째로 뗀다 ──────────────────────────
    names = sorted(by_speaker)
    holdout: set[str] = set()
    if args.holdout > 0:
        if args.holdout >= len(names):
            print(f"\n✗ 화자가 {len(names)}명인데 {args.holdout}명을 떼려 합니다.")
            return 1
        rng = np.random.default_rng(args.seed)
        holdout = set(rng.choice(names, size=args.holdout, replace=False).tolist())
        print(f"\n🔒 홀드아웃(미학습 화자): {', '.join(sorted(holdout))}")
        print("   이 사람들은 학습에 **한 번도** 안 들어갑니다 (M7 §5-2)")

    # ── 자르기 ────────────────────────────────────────────────
    bins: dict[str, list] = {"positive": [], "negative": [], "holdout_pos": [], "holdout_neg": []}
    dropped = {"quiet": 0, "kept": 0}
    manifest = {"sessions": [], "holdout": sorted(holdout), "sampleRate": SR}

    for meta, wp in sessions:
        try:
            pcm = read_wav(wp)
        except Exception as e:                       # 조용히 넘기지 않는다
            print(f"  ✗ {os.path.basename(wp)} — {e}")
            continue
        who = meta.get("speaker", "?")
        held = who in holdout
        counts = {"positive": 0, "negative": 0, "freetalk": 0, "quiet": 0}

        for seg in meta.get("segments", []):
            lab = seg.get("label")
            clip = cut(pcm, seg)
            if rms(clip) <= RMS_MIN:                 # 아무 말도 안 한 슬롯
                counts["quiet"] += 1
                dropped["quiet"] += 1
                continue
            # 🚨 freetalk 은 **음성으로 간다.** 호출어가 아닌 실제 대화이고,
            #    이게 전시회 부스 앞 분포에 가장 가깝다.
            key = "positive" if lab == "positive" else "negative"
            bins[("holdout_" + key[:3]) if held else key].append(clip)
            counts[lab if lab in counts else "negative"] += 1
            dropped["kept"] += 1

        manifest["sessions"].append({
            "file": os.path.basename(wp), "speaker": who,
            "place": meta.get("place"), "distance": meta.get("distance"),
            "recordedAt": meta.get("recordedAt"), "holdout": held, "segments": counts,
        })

    os.makedirs(OUT, exist_ok=True)

    def dump(name: str, clips: list) -> float:
        if not clips:
            return 0.0
        a = np.concatenate(clips).astype(np.float32)
        np.save(os.path.join(OUT, name), a)
        return len(a) / SR

    sec = {
        "positive.npy":     dump("positive.npy", bins["positive"]),
        "negative.npy":     dump("negative.npy", bins["negative"]),
        "holdout_pos.npy":  dump("holdout_pos.npy", bins["holdout_pos"]),
        "holdout_neg.npy":  dump("holdout_neg.npy", bins["holdout_neg"]),
    }
    # 현행 학습기 호환 — `--user-audio` 는 양성만 받는다
    if bins["positive"]:
        np.save(os.path.join(OUT, "wake_voice.npy"),
                np.concatenate(bins["positive"]).astype(np.float32))

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n구간 {dropped['kept']}개 사용 · {dropped['quiet']}개 버림(소리 없음)")
    for k, v in sec.items():
        if v:
            print(f"  {OUT}{os.sep}{k:<18} {v:6.1f}초")
    print(f"  {OUT}{os.sep}manifest.json")

    print("\n다음 단계")
    print("  python scripts/train_wakeword.py --user-audio data/wakeword/wake_voice.npy")
    print("  ⚠️ 현행 학습기는 **양성만** 받습니다. negative.npy 를 쓰려면")
    print("     train_wakeword.py 를 고쳐야 합니다 — M7 ④ (9/23~) 입니다.")
    print("     그때까지는 negative.npy 가 쌓이기만 합니다. **버리지 마세요.**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
