"""긴 녹음을 **학습 음성(negative)** 풀에 더한다.

    conda activate pluiz
    python scripts/add_soak_to_negatives.py data/soak_voice_<날짜>.wav
    python scripts/add_soak_to_negatives.py <wav> --phases 음악만 남의말소리만
    python scripts/add_soak_to_negatives.py <wav> --apply      ← 실제로 쓴다

🔑 **왜 필요한가** — `train_wakeword.py` 는 이미 `--user-neg` 로 «사람이 말한 다른 말»을
   받는다. 그런데 그 풀(`data/wakeword/negative.npy`)은 **녹음 페이지로 받은 1인당
   1.4분짜리 구간**들이다. 조용한 방에서 문장을 읽은 것이라, **실제 쓰는 자리의 긴
   자연 발화·음악·남의 말소리**가 들어 있지 않다.

   2026-10-01 구간별 실측이 그걸 숫자로 보여 줬다(임계 0.62 · FA/시간):

       조용히 24 · 혼잣말 312 · 음악 276 · 남의 말소리 144 · 섞기 204

   🚨 그중 **임계를 0.99 까지 올려도 안 죽는 것은 「남의 말소리」(24회/시간)** 였다.
   혼잣말·조용히는 임계만 올려도 0 이 된다. **그러니 더 넣어야 할 것은 내 목소리가
   아니라 남의 말소리와 음악이다.** (그 전까지 계획은 반대였고, 측정이 뒤집었다.)

🔒 **원본을 덮어쓰지 않는다.** 새 파일(`negative_plus.npy`)로 쓰고 학습할 때
   `--user-neg` 로 가리킨다. 되돌리려면 그 파일을 지우고 예전 명령을 쓰면 된다.

🚨 **「플루이즈」가 섞이면 학습이 망가진다** — 양성을 음성으로 가르치는 꼴이다.
   녹음 때 부르지 않기로 했고, 2단계 시뮬레이션에서 이 파일의 깨어남 **전부가**
   Whisper 확인을 통과하지 못했다(=실제로 그 말이 없다). 그래도 `--check` 로
   한 번 더 볼 수 있다.
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SR = 16000
#: `train_wakeword.loud_segments` 가 쓰는 값과 같다. 이보다 조용한 곳은 학습 창이
#: 되지 않으므로, 여기서 「몇 창이 늘어나는가」를 셀 때도 같은 기준을 써야 한다.
LOUD_RMS = 0.006
WIN_SEC = 1.0


def main(argv=None):
    ap = argparse.ArgumentParser(description="긴 녹음을 학습 음성 풀에 더한다")
    ap.add_argument("wav", help="녹음 파일")
    ap.add_argument("--phases", nargs="*", default=None,
                    help="넣을 구간 이름 (기본: 전부). 공백 대신 아무 표기나 쓴다")
    ap.add_argument("--out", default="", help="기본 data/wakeword/negative_plus.npy")
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다 (없으면 미리보기만)")
    a = ap.parse_args(argv)

    import numpy as np
    from scripts.eval_wakeword import read_wav

    wav = a.wav if os.path.isabs(a.wav) else os.path.join(ROOT, a.wav)
    if not os.path.exists(wav):
        print(f"✗ 없는 파일: {wav}")
        return 1

    base_p = os.path.join(ROOT, "data", "wakeword", "negative.npy")
    out_p = a.out or os.path.join(ROOT, "data", "wakeword", "negative_plus.npy")
    if not os.path.exists(base_p):
        print(f"✗ 기존 음성 풀이 없어요: {base_p}")
        return 1

    base = np.load(base_p)
    audio = read_wav(wav)

    # ── 구간 고르기 ────────────────────────────────────────────────
    side = wav[:-4] + ".phases.json"
    picked, skipped = [], []
    if os.path.exists(side) and a.phases is not None:
        want = {p.replace(" ", "") for p in a.phases}
        for ph in json.load(io.open(side, encoding="utf-8"))["phases"]:
            seg = audio[int(float(ph["start"]) * SR):int(float(ph["end"]) * SR)]
            (picked if ph["name"].replace(" ", "") in want else skipped
             ).append((ph["name"], seg))
    else:
        label = "전체" if not os.path.exists(side) else "전체(구간 안 고름)"
        picked.append((label, audio))

    if not picked:
        print("✗ 고른 구간이 없어요. --phases 이름을 확인하세요.")
        if os.path.exists(side):
            names = [p["name"] for p in json.load(io.open(side, encoding="utf-8"))["phases"]]
            print(f"   있는 구간: {' · '.join(names)}")
        return 1

    def loud_windows(x):
        """이 오디오가 **학습 창을 몇 개 만들어 내는가.** 조용한 곳은 안 센다."""
        hop, win = int(SR * 0.25), int(SR * WIN_SEC)
        return sum(1 for st in range(0, max(1, len(x) - win), hop)
                   if float(np.sqrt(np.mean(x[st:st + win] ** 2))) > LOUD_RMS)

    add = np.concatenate([seg for _n, seg in picked]).astype(np.float32)

    print()
    print(f"[기존] {os.path.relpath(base_p, ROOT)}  {len(base)/SR/60:.1f}분 · "
          f"학습 창 {loud_windows(base):,}개")
    print(f"[더함] {os.path.basename(wav)}")
    for n, seg in picked:
        print(f"         + {n:<12} {len(seg)/SR/60:5.1f}분 · 창 {loud_windows(seg):>5,}개")
    for n, seg in skipped:
        print(f"         - {n:<12} {len(seg)/SR/60:5.1f}분   (안 넣음)")

    merged = np.concatenate([base, add])
    print()
    print(f"[결과] {len(merged)/SR/60:.1f}분 · 학습 창 {loud_windows(merged):,}개 "
          f"(기존 대비 {len(merged)/len(base):.2f}배)")

    # 🚨 조용한 자료만 잔뜩 넣으면 **길이만 늘고 학습 창은 안 는다.** 그걸 말해 준다.
    gain = loud_windows(add)
    if gain == 0:
        print("🚨 더하는 오디오에서 **학습 창이 하나도 안 나옵니다** — 너무 조용합니다.")
        print("   길이만 늘고 학습에는 아무 영향이 없습니다.")
    print()

    if not a.apply:
        print("미리보기만 했어요. 실제로 쓰려면 --apply 를 붙이세요.")
        print()
        print("쓴 뒤 학습은 이렇게 합니다:")
        print(f"   python scripts/train_wakeword.py --jobs 0 \\")
        print(f"          --user-neg {os.path.relpath(out_p, ROOT)}")
        return 0

    np.save(out_p, merged)
    print(f"✓ 저장했어요 — {os.path.relpath(out_p, ROOT)}")
    print("🔒 원본 negative.npy 는 **그대로 둡니다.** 되돌리려면 이 파일만 지우면 돼요.")
    print()
    print("이제 학습:")
    print(f"   python scripts/train_wakeword.py --jobs 0 \\")
    print(f"          --user-neg {os.path.relpath(out_p, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
