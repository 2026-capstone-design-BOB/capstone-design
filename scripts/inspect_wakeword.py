"""받은 녹음을 **재 보고 들어 본다** — 「소리가 작다」가 뭔지 눈과 귀로 확인한다.

    conda activate pluiz
    python scripts/inspect_wakeword.py                  # 전원 · 라벨별 RMS 표
    python scripts/inspect_wakeword.py --play 황순현     # 그 사람 «플루이즈»만 모아 듣기
    python scripts/inspect_wakeword.py --play 황순현 --label negative
    python scripts/inspect_wakeword.py --play 황순현 --gain 6   # 6배 키워서 (원본은 안 건드린다)

## 왜 필요한가

녹음 페이지가 「소리가 작아요」라고만 말한다. 그런데 **작다가 얼마나 작은지**,
그게 **마이크 문제인지 말소리 문제인지**는 숫자와 소리로만 갈린다.

🚨 **2026-09-16 실측 — 기기에 따라 12배가 차이 났다.**

    휴대폰    RMS 0.088  피크 0.49
    헤드셋    RMS 0.021  피크 0.15
    노트북    RMS 0.0072 피크 0.05

⚠️ **그런데 «작다»는 판정 자체가 틀렸었다.** 이 도구를 만들 때 임계를 0.006 으로
잡아 노트북을 «아슬»로 찍었는데, **실제로 모델에 닿는 관문은
`services/wakeword.py` 의 0.0015 다.** 노트북도 관문의 **4.8배**라 멀쩡했다.
0.006 은 학습기가 **통짜 녹음에서 발화 구간을 찾을 때** 쓰는 값이고,
지금은 슬롯마다 라벨이 있어 **구간을 찾을 필요가 없다.** → 전부 0.0025 로 맞췄다.

📌 **기기를 보여 주는 이유는 «게인»이 아니라 «분포»다.** 학습은 기기가
다양할수록 좋다(화자 다양성과 같은 이치). 다만 **홀드아웃에는 실서비스와 같은
환경(노트북 마이크)이 들어가야** «실제로 얼마나 되나»를 잴 수 있다(M7 §5-2).
그래서 «몇 명»만이 아니라 «어떤 기기로»를 같이 본다.

## 🔒 듣기용 파일은 임시다

`--play` 가 만드는 파일은 스크래치에 두고, **`data/` 에 남기지 않는다.**
학습 입력과 섞이면 «이건 원본인가 증폭본인가»를 나중에 못 푼다.
"""
import argparse
import glob
import io
import json
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(_ROOT, "data", "wakeword_raw")
SR = 16000
RMS_MIN = 0.0025         # 녹음 페이지·ingest 와 같은 값 (런타임 관문 0.0015 보다 약간 위)
GAP = 0.35               # 듣기용으로 이어 붙일 때 사이 간격(초)


def load(jp: str):
    meta = json.load(io.open(jp, encoding="utf-8"))
    wp = jp[:-5] + ".wav"
    with wave.open(wp, "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return meta, pcm


def clip_of(pcm, seg):
    return pcm[int(seg["start"] * SR):int(seg["end"] * SR)]


def rms(x):
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def write_wav(path, pcm):
    a = np.clip(pcm, -1.0, 1.0)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((a * 32767).astype("<i2").tobytes())


def table(sessions):
    """사람별·라벨별 RMS 표. **기기를 같이 보여 준다** — 위 주석의 이유."""
    print(f"\n{'화자':<10} {'기기':<16} {'라벨':<9} {'개수':>4} {'RMS중앙':>9} {'피크중앙':>9}  판정")
    print("─" * 78)
    for meta, pcm in sessions:
        first = True
        for lab in ("positive", "negative", "freetalk"):
            segs = [s for s in meta.get("segments", []) if s["label"] == lab]
            if not segs:
                continue
            rs = [rms(clip_of(pcm, s)) for s in segs]
            pks = [float(np.max(np.abs(clip_of(pcm, s))) or 0) for s in segs]
            med, pk = float(np.median(rs)), float(np.median(pks))
            # 🚨 «통과/실패»가 아니라 **여유**를 보여 준다. 임계를 겨우 넘는 것과
            #    넉넉히 넘는 것은 학습에서 완전히 다르다.
            mult = med / RMS_MIN
            mark = "✅ 넉넉" if mult >= 5 else ("🟡 빠듯" if mult >= 2 else "🔴 아슬")
            print(f"{(meta['speaker'] if first else ''):<10} "
                  f"{((meta.get('device') or '?')[:15] if first else ''):<16} "
                  f"{lab:<9} {len(segs):>4} {med:>9.4f} {pk:>9.3f}  {mark} (임계×{mult:.1f})")
            first = False
    print("─" * 78)
    print(f"임계 {RMS_MIN} · 런타임 관문은 0.0015 (services/wakeword.py) · 피크는 1.0 이 최대.")
    print("🔑 «아슬»이어도 런타임 관문은 넉넉히 넘는다 — 버릴 이유가 아니다.")
    print("   피크가 0.03 미만이면 그때는 마이크 입력 볼륨을 올리는 게 좋다.")


def play(sessions, who, label, gain, no_open):
    hit = [(m, p) for m, p in sessions if who in m["speaker"]]
    if not hit:
        print(f"✗ '{who}' 로 시작하는 화자가 없습니다.")
        return 1
    meta, pcm = hit[0]
    segs = [s for s in meta.get("segments", []) if label in ("all", s["label"])]
    if not segs:
        print(f"✗ '{label}' 구간이 없습니다.")
        return 1

    gap = np.zeros(int(GAP * SR), dtype=np.float32)
    out = np.concatenate([np.concatenate([clip_of(pcm, s), gap]) for s in segs])
    if gain != 1.0:
        out = out * gain
        over = float(np.mean(np.abs(out) > 1.0))
        if over > 0.001:                       # 조용히 자르지 않는다
            print(f"⚠️  증폭 {gain}배에서 {over*100:.1f}% 가 잘립니다(클리핑). 더 낮춰 보세요.")

    dst = os.path.join(tempfile.gettempdir(),
                       f"pluiz_듣기_{meta['speaker']}_{label}{'_x'+str(gain) if gain!=1 else ''}.wav")
    write_wav(dst, out)
    print(f"\n{meta['speaker']} · {label} {len(segs)}개 · {len(out)/SR:.0f}초"
          + (f" · {gain}배 증폭" if gain != 1.0 else ""))
    print(f"  {dst}")
    print(f"  원본 RMS 중앙 {np.median([rms(clip_of(pcm,s)) for s in segs]):.4f}")
    if not no_open:
        try:
            os.startfile(dst)                  # 기본 재생기로 연다 (Windows)
        except Exception as e:
            print(f"  (자동 재생 실패: {e} — 위 경로를 직접 열어 주세요)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="받은 녹음을 재 보고 들어 본다")
    ap.add_argument("--play", metavar="화자", help="그 사람 구간을 이어 붙여 재생한다")
    ap.add_argument("--label", default="positive",
                    choices=["positive", "negative", "freetalk", "all"],
                    help="어떤 구간을 들을지 (기본: positive)")
    ap.add_argument("--gain", type=float, default=1.0, help="듣기용 증폭 배수 (원본 불변)")
    ap.add_argument("--no-open", action="store_true", help="파일만 만들고 열지 않는다")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(RAW, "*.json")))
    if not files:
        print(f"✗ {RAW} 에 받은 녹음이 없습니다. 먼저 `npm run pull` 을 돌리세요.")
        return 1
    sessions = []
    for jp in files:
        if not os.path.exists(jp[:-5] + ".wav"):
            print(f"  ⚠️  {os.path.basename(jp)} — 짝이 되는 .wav 가 없습니다")
            continue
        sessions.append(load(jp))

    if args.play:
        return play(sessions, args.play, args.label, args.gain, args.no_open)
    table(sessions)
    print("\n들어보려면:  python scripts/inspect_wakeword.py --play <이름> [--gain 6]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
