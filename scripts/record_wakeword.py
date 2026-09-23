"""「플루이즈」 실제 녹음 도우미 — 학습에 쓸 목소리를 받는다.

    conda activate pluiz
    python scripts/record_wakeword.py                # 새로 녹음 (기본 35회 · 약 2분 30초)
    python scripts/record_wakeword.py --append       # 다른 사람 목소리를 뒤에 더한다
    python scripts/record_wakeword.py --check-only   # 이미 만든 파일이 쓸 만한지만 본다
    python scripts/record_wakeword.py --slots 20     # 짧게 (연습용)

산출물은 `wake_voice.npy` 하나이고, 다음 단계는 이것뿐이다:

    python scripts/train_wakeword.py --user-audio wake_voice.npy

## 왜 별도 스크립트인가 — 문서의 절차로는 두 번 데인다

docs/TASKS.md ③에 적혀 있던 절차는 `sd.rec(150초)` 한 줄이었다. 두 가지가 빠져 있다.

1. **언제 말해야 하는지 알려주지 않는다.** 150초를 눈감고 녹음하므로 발화 간격이
   들쭉날쭉해지고, 중간에 틀려도 되돌릴 수 없다. → 여기서는 **4초마다 무엇을 말할지
   화면에 띄운다.**

2. 🚨 **쓸 만한 녹음인지 학습을 돌려 봐야 알 수 있었다.** `train_wakeword.py`는
   RMS > 0.006인 **모든** 구간을 「플루이즈」 양성으로 학습한다(`build_dataset` ③).
   기침·"어..."·옆사람 말소리가 섞이면 **그게 전부 호출어로 학습돼 오탐이 된다.**
   → 여기서는 **학습기와 똑같은 규칙**(창 2.0초 · hop 0.25초 · RMS 0.006)으로 세어
   보여주고, 이상하면 **녹음 직후에** 다시 하라고 말한다.

## 규칙 하나만 지키면 된다

**「플루이즈」와 침묵만 녹음한다.** 말을 고르거나 헛기침하는 소리가 들어가면
그것도 호출어로 학습된다. 틀렸으면 그 슬롯은 **그냥 말하지 말고 넘긴다** —
빈 슬롯은 조용해서 자동으로 걸러지지만, 잘못된 소리는 걸러지지 않는다.
"""
import argparse
import os
import sys
import time

import numpy as np

SR = 16000              # scripts/wakeword_data.py 와 같아야 한다
WIN_SEC = 2.0           # scripts/train_wakeword.py 의 WIN_SEC
SEG_RMS = 0.006         # train_wakeword.build_dataset ③ 의 발화 구간 임계
SEG_HOP = 0.25          # 같은 곳의 hop
SLOT_SEC = 4.0          # 한 번 부르고 쉬는 간격
LEAD_SEC = 3.0          # 준비 시간
OUT = "wake_voice.npy"

# 발화 변형 — 한 가지 톤만 녹음하면 그 톤에만 반응한다.
# 2026-09-09 실기에서 10번 중 2번만 깨어난 게 이 문제의 다른 얼굴이다
# (학습이 전부 TTS라 실제 조음이 한 번도 안 들어갔다). → docs/BACKLOG.md BL-23
STYLES = [
    ("플루이즈", "또렷하게, 평소 크기로"),
    ("플루이즈", "평소 말하듯 자연스럽게"),
    ("플루이즈", "조금 빠르게"),
    ("플루이즈", "조금 느리게, 또박또박"),
    ("플루이즈", "작게 (속삭이지는 말고)"),
    ("플루이즈", "평소보다 크게"),
    ("헤이 플루이즈", "앞에 '헤이'를 붙여서"),
    ("플루이즈야", "뒤에 '야'를 붙여서"),
    ("플루이즈", "마이크에서 조금 멀리 떨어져서"),
    ("플루이즈", "평소 크기로 다시"),
]


def make_prompts(slots: int):
    """슬롯 수만큼 발화 지시를 만든다. STYLES를 돌려 쓴다."""
    return [STYLES[i % len(STYLES)] for i in range(slots)]


def loud_segments(audio: np.ndarray):
    """`train_wakeword.py`가 **양성으로 학습할** 구간을 그대로 세어 본다.

    ⚠️ 학습기와 같은 규칙이어야 의미가 있다. 저기 숫자가 바뀌면 여기도 바꾼다.
    """
    hop = int(SR * SEG_HOP)
    win = int(SR * WIN_SEC)
    out = []
    for st in range(0, max(1, len(audio) - win), hop):
        seg = audio[st:st + win]
        if float(np.sqrt(np.mean(seg ** 2))) > SEG_RMS:
            out.append(st / SR)
    return out


def utterances(audio: np.ndarray, frame=0.1, gap=0.4, min_dur=0.2):
    """소리 나는 덩어리를 **발화 단위로** 센다. 반환은 [(시작초, 길이초), ...].

    ⚠️ `loud_segments()`의 결과를 묶어서 세면 안 된다. 저건 **2.0초 창**의 시작
      위치라, 1초쯤 떨어진 두 소리가 같은 창에 들어가 **하나로 뭉친다.** 그래서
      「호출어 10번 + 기침 9번」이 「발화 1번」으로 보이고, 원인과 정반대인
      *"소리가 작다"* 는 안내가 나갔다(만들면서 실제로 겪었다).
      발화 경계는 **짧은 프레임**으로 봐야 한다.
    """
    n = int(SR * frame)
    if n <= 0 or len(audio) < n:
        return []
    frames = len(audio) // n
    loud = np.sqrt(np.mean(audio[:frames * n].reshape(frames, n) ** 2, axis=1)) > SEG_RMS

    out, start, gap_frames = [], None, int(round(gap / frame))
    quiet = 0
    for i, is_loud in enumerate(loud):
        if is_loud:
            if start is None:
                start = i
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet > gap_frames:
                dur = (i - quiet - start) * frame
                if dur >= min_dur:
                    out.append((start * frame, dur))
                start, quiet = None, 0
    if start is not None:
        dur = (frames - start) * frame
        if dur >= min_dur:
            out.append((start * frame, dur))
    return out


def duty_cycle(audio: np.ndarray, frame=0.1) -> float:
    """소리가 나는 시간의 비율. **«조용한 녹음»과 «쉴 새 없는 녹음»을 가른다.**

    발화 수만 세면 안 되는 이유: 소리가 끊이지 않으면 발화가 몇 개 안 되는 긴
    덩어리로 묶여 **적게 부른 것처럼** 보이고, 그러면 「소리가 작다」는 정반대
    안내가 나간다. (실제로 그렇게 틀린 메시지가 나오는 걸 보고 이 함수를 넣었다)

    4초 슬롯에 1초쯤 말하는 계획이므로 정상은 20~30%다.
    """
    n = int(SR * frame)
    if n <= 0 or len(audio) < n:
        return 0.0
    frames = len(audio) // n
    trimmed = audio[:frames * n].reshape(frames, n)
    loud = np.sqrt(np.mean(trimmed ** 2, axis=1)) > SEG_RMS
    return float(np.mean(loud))


def report(audio: np.ndarray, expect: int) -> bool:
    """쓸 만한 녹음인지 **학습을 돌리기 전에** 판정한다. 통과면 True."""
    dur = len(audio) / SR
    rms = float(np.sqrt(np.mean(audio ** 2)))
    starts = loud_segments(audio)
    utts = utterances(audio)
    duty = duty_cycle(audio)

    print()
    print("─" * 58)
    print(f"  길이            {dur:.0f}초")
    print(f"  전체 RMS        {rms:.4f}   (0.005 이상 권장)")
    print(f"  소리 나는 비율    {duty*100:.0f}%      (20~30%가 정상)")
    print(f"  학습에 쓰일 구간  {len(starts)}개 → 발화 {len(utts)}번으로 묶임")
    print("─" * 58)

    ok = True
    if duty > 0.35:
        # 여기가 가장 위험한 실패다 — 표만 보면 «많이 녹음됐다»로 보인다.
        print(f"  🚨 소리가 거의 끊이지 않는다({duty*100:.0f}%).")
        print("      잡음·에어컨·옆사람 말소리가 계속 들어갔을 가능성이 크다.")
        print("      학습기는 소리 나는 구간을 **전부 「플루이즈」로 배우므로**,")
        print("      이대로 학습하면 아무 소리에나 깨어난다.")
        print("      → 조용한 방에서 다시 녹음한다.")
        ok = False
    elif rms < 0.005 or len(utts) < expect * 0.5:
        print(f"  ⚠️  발화가 {len(utts)}번 잡혔다 (부른 건 {expect}번).")
        print("      소리가 작아 학습기가 못 줍는다 — 마이크에 더 가까이, 더 크게.")
        ok = False
    elif len(utts) > expect * 1.6:
        print(f"  🚨 발화가 {len(utts)}번 잡혔다 (부른 건 {expect}번).")
        print("      호출어가 아닌 소리(기침·'어...'·말소리)가 섞였을 가능성이 크다.")
        print("      이대로 학습하면 그 소리들도 「플루이즈」로 배워 오탐이 된다.")
        ok = False

    if ok:
        print("  ✅ 쓸 만하다. 다음 단계로 간다:")
        print(f"     python scripts/train_wakeword.py --user-audio {OUT}")
    else:
        print()
        print("  → 다시 녹음: python scripts/record_wakeword.py")
    print()
    return ok


def record(slots: int) -> np.ndarray:
    import sounddevice as sd

    prompts = make_prompts(slots)
    total = LEAD_SEC + slots * SLOT_SEC

    dev = sd.query_devices(kind="input")
    print()
    print(f"입력 장치 : {dev['name']}")
    print(f"녹음 계획 : {slots}번 × {SLOT_SEC:.0f}초 = 약 {total/60:.1f}분")
    print()
    print("  규칙 — 「플루이즈」와 침묵만 녹음한다.")
    print("  틀렸으면 그 슬롯은 **아무 말도 하지 말고** 넘긴다.")
    print("  (잘못 낸 소리는 그대로 호출어로 학습된다)")
    print()
    try:
        input("  준비되면 Enter... ")
    except (EOFError, KeyboardInterrupt):
        print("\n취소했습니다.")
        sys.exit(1)

    buf = sd.rec(int(SR * total), samplerate=SR, channels=1, dtype="float32")
    t0 = time.time()

    # 카운트다운은 **녹음 시작 시각(t0) 기준**으로 맞춘다. time.sleep(1)을 쌓으면
    # 출력 지연이 누적돼 프롬프트가 실제 오디오와 어긋난다.
    for i in range(int(LEAD_SEC), 0, -1):
        print(f"\r  시작까지 {i}...   ", end="", flush=True)
        while time.time() - t0 < (LEAD_SEC - i + 1):
            time.sleep(0.02)
    print("\r" + " " * 30 + "\r", end="", flush=True)

    for i, (word, how) in enumerate(prompts, 1):
        target = LEAD_SEC + (i - 1) * SLOT_SEC
        while time.time() - t0 < target:
            time.sleep(0.02)
        print(f"  {i:2d}/{slots}   🔴 「{word}」   — {how}")

    while time.time() - t0 < total:
        time.sleep(0.05)
    sd.wait()
    return buf.flatten()


def main():
    ap = argparse.ArgumentParser(description="「플루이즈」 실제 녹음 도우미")
    ap.add_argument("--slots", type=int, default=35, help="부르는 횟수 (기본 35)")
    ap.add_argument("--out", default=OUT, help=f"저장 파일 (기본 {OUT})")
    ap.add_argument("--append", action="store_true",
                    help="기존 파일 뒤에 이어 붙인다 (다른 사람 목소리 추가용)")
    ap.add_argument("--check-only", action="store_true",
                    help="녹음하지 않고 기존 파일만 검사한다")
    args = ap.parse_args()

    if args.check_only:
        if not os.path.exists(args.out):
            print(f"파일이 없습니다: {args.out}")
            sys.exit(1)
        audio = np.load(args.out)
        # 몇 번 불렀는지 모르므로 잡힌 발화 수를 그대로 기대치로 둔다(경고 없이 표만 본다)
        report(audio, expect=max(1, len(utterances(audio))))
        return

    new = record(args.slots)

    # ⚠️ 검사는 **이번에 녹음한 것만** 본다. 이어 붙인 전체를 이번 슬롯 수와 비교하면
    #   두 번째 사람부터 «발화 66번 / 부른 건 35번»이 되어 **멀쩡한 녹음을 잡음이
    #   섞였다고 경고한다.** 판정 대상과 기대치는 같은 세션이어야 한다.
    ok = report(new, expect=args.slots)

    combined = new
    if args.append and os.path.exists(args.out):
        # 덮어쓰기 전에 되돌릴 것을 남긴다. 녹음은 **다시 만들 수 없는 입력**이라
        # (사람을 다시 불러야 한다) 조용히 덮어쓰지 않는다.
        # ⚠️ 이름은 반드시 `.npy`로 끝내야 한다 — np.save는 그렇지 않으면 확장자를
        #   **덧붙여서** `wake_voice.npy.bak.npy` 같은 파일을 만든다(안내한 경로와
        #   실제 파일이 달라져 되돌릴 때 못 찾는다).
        root = args.out[:-4] if args.out.endswith(".npy") else args.out
        bak = root + ".bak.npy"
        np.save(bak, np.load(args.out))
        print(f"\n  백업: {bak}")
        old = np.load(args.out)
        # 사이에 1초 침묵을 넣어 두 세션의 끝/시작이 한 발화로 붙지 않게 한다
        combined = np.concatenate([old, np.zeros(SR, dtype=np.float32), new])
        print(f"  이어 붙임: 기존 {len(old)/SR:.0f}초 + 이번 {len(new)/SR:.0f}초 "
              f"= {len(combined)/SR:.0f}초 "
              f"(목소리 누적 발화 {len(utterances(combined))}번)")
        print()

    np.save(args.out, combined.astype(np.float32))
    print(f"  저장: {args.out}")
    if not ok and args.append:
        # 되돌리는 수단을 알려준다 — 이어 붙인 뒤에는 이번 것만 빼내기 어렵다
        print("  ⚠️ 이번 녹음이 판정을 통과하지 못했다. 다시 하려면 이 파일을 지우고")
        print("     처음부터 녹음하거나, 백업에서 되돌린 뒤 --append 를 다시 한다.")


if __name__ == "__main__":
    main()
