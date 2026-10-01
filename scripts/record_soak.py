"""소크 오디오 녹음 — 「안 불렀는데 깨는가」를 재려고 모으는 자료.

    conda activate pluiz
    python scripts/record_soak.py                 20분 (기본)
    python scripts/record_soak.py --minutes 30
    python scripts/record_soak.py --list          마이크 목록만 보고 끝낸다

🚨 **녹음 중에 「플루이즈」를 부르지 않는다.** 이 자료의 쓸모가 거기 달려 있다.
   평소처럼 쓰면 된다 — 혼잣말, 통화, 영상 보기, 아무것도 안 하기.

🔑 **왜 또 녹음하나** — 지금 오탐을 잰 `data/soak_16k.wav` 1.94시간이 **대선토론**이다.
   방송 마이크로 잡은, 또박또박 말하는, **남의 목소리**다. 그런데 실제 사용 환경은
   **이 PC 마이크로 들어오는 변소윤의 평소 말**이고, 그 목소리는 **학습셋에 들어가 있다**
   (홀드아웃은 녹음자1·녹음자3·녹음자5·녹음자9). 2026-09-30 실기에서 10분에 34번 깼다.
   → docs/testing/실기_사용자몫_20260929.md §3

🔒 **왜 녹음기를 따로 만들었나** — `scripts/eval_wakeword.py` 는 16kHz·모노·16bit 가
   아니면 **고치지 않고 거부한다**(리샘플링을 몰래 해 주면 무엇을 쟀는지 흐려진다).
   그래서 휴대폰이나 녹음기 앱으로 받으면 변환 단계가 하나 더 생기고, 더 나쁜 것은
   **마이크가 달라진다.** 여기서는 `services/wakeword.py` 와 **같은 장치·같은 설정**으로
   받는다 — 재는 조건과 쓰는 조건이 같아야 숫자가 뜻을 가진다.

다 녹음하면:

    python scripts/eval_wakeword.py --compare services/wakeword_model.npz \\
           --soak data/soak_voice_<날짜>.wav --holdout-only
"""
import argparse
import io
import json
import os
import sys
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAMPLE_RATE = 16000          # services/wakeword.py 와 같다. 바꾸면 평가가 거부한다.
CHANNELS = 1
OUT_DIR = os.path.join(ROOT, "data")

# ── 구간을 나눠 받는다 (2026-10-01) ────────────────────────────────
#
# 🔑 **한 번 받아서 네 가지를 잰다.** 20분을 섞어서 받으면 «264회/시간» 하나가
#   나오는데, 그 숫자는 **무엇을 고쳐야 하는지 말해 주지 않는다.**
#   구간을 나눠 두면 「내 목소리에 깨는가 · 음악에 깨는가 · 남의 말소리에 깨는가」가
#   따로 나오고, 그게 곧 **학습 음성에 무엇을 더 넣어야 하는지**다.
#
# 🚨 조용한 구간을 **반드시 넣는다.** 조용할 때도 깬다면 문제는 말소리가 아니라
#   마이크 잡음이고, 그러면 손댈 곳이 완전히 다르다.
#
# ⚠️ 장소를 바꿀 필요는 없다. 필요한 것은 «학습에 안 쓴 자료»이지 «다른 방»이 아니다.
DEFAULT_PHASES = [
    ("조용히",        "아무 말도 하지 마세요. 타자·마우스는 괜찮아요"),
    ("혼잣말만",      "평소처럼 혼잣말하세요. 음악·영상은 끄고"),
    ("음악만",        "노래를 트세요. 사람 말이 없는 걸로. 본인은 말하지 않기"),
    ("남의 말소리만",  "유튜브·뉴스 등 사람이 말하는 걸 트세요. 본인은 말하지 않기"),
    ("섞기",          "영상 틀고 혼잣말도 하고 — 평소 쓰는 모습 그대로"),
]

#: 말소리로 칠 최소 세기. services/wakeword.py 의 «무음 스킵» 임계와 같은 값이다 —
#: 그보다 조용한 구간은 런타임이 **모델에 넣지도 않으므로** 소크 분모로도 의미가 없다.
SPEECH_RMS = 0.0015


def _fmt(sec):
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="소크 오디오 녹음 (16kHz 모노 16bit)")
    ap.add_argument("--minutes", type=float, default=20.0, help="몇 분 녹음할지 (기본 20)")
    ap.add_argument("--out", default="", help="저장할 파일 (기본 data/soak_voice_<날짜>.wav)")
    ap.add_argument("--device", default=None, help="마이크 번호 (--list 로 확인)")
    ap.add_argument("--list", action="store_true", help="마이크 목록만 보고 끝낸다")
    ap.add_argument("--plain", action="store_true",
                    help="구간을 나누지 않고 통째로 받는다 (예전 방식)")
    a = ap.parse_args(argv)

    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as e:
        print(f"✗ {e.name} 이 없어요. conda activate pluiz 를 먼저 하세요.")
        return 1

    if a.list:
        print("입력 장치:")
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                mark = " ← 기본" if i == sd.default.device[0] else ""
                print(f"  [{i}] {d['name']}{mark}")
        return 0

    dev = int(a.device) if a.device not in (None, "") else None
    try:
        name = sd.query_devices(dev if dev is not None else sd.default.device[0])["name"]
    except Exception:                                         # noqa: BLE001
        name = "(알 수 없음)"

    os.makedirs(OUT_DIR, exist_ok=True)
    out = a.out or os.path.join(
        OUT_DIR, f"soak_voice_{time.strftime('%Y%m%d_%H%M')}.wav")

    total = max(1.0, a.minutes * 60)
    print()
    print("🎙  소크 녹음")
    print(f"    마이크   {name}")
    print(f"    형식     {SAMPLE_RATE}Hz · 모노 · 16bit")
    print(f"    길이     {a.minutes:g}분")
    print(f"    저장     {os.path.relpath(out, ROOT)}")
    print()
    print("🚨 녹음하는 동안 「플루이즈」를 부르지 마세요. 그게 이 녹음의 전부입니다.")
    phases = [] if a.plain else list(DEFAULT_PHASES)
    if phases:
        each = total / len(phases)
        print(f"   {len(phases)}구간으로 나눠 받습니다 — 각 {each/60:.1f}분.")
        print("   🔑 나눠 두면 «무엇에 깨는가»가 따로 나옵니다. 장소는 안 바꾸셔도 됩니다.")
        print()
        for i, (nm, how) in enumerate(phases, 1):
            print(f"     {i}. {nm:<9} — {how}")
        print()
        print("   구간이 바뀔 때 화면이 알려 줍니다. 그때만 바꿔 주시면 됩니다.")
    else:
        print("   평소처럼 쓰시면 됩니다 — 혼잣말, 통화, 영상, 아무것도 안 하기.")
    print()
    print("   멈추려면 Ctrl+C — 그때까지 녹음한 것은 그대로 저장됩니다.")
    print()
    try:
        input("   준비되면 Enter ... ")
    except (EOFError, KeyboardInterrupt):
        print("\n   취소했어요.")
        return 1

    # 🔑 **끝날 때 한 번에 쓰지 않는다.** 20분을 메모리에 들고 있다가 떨어뜨리면
    #   20분이 통째로 날아간다. 들어오는 대로 파일에 붙인다.
    wf = wave.open(out, "wb")
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(2)
    wf.setframerate(SAMPLE_RATE)

    frames = 0
    loud = 0           # 말소리로 친 블록 수
    blocks = 0
    peak = 0.0
    started = time.time()
    stopped_early = False
    # 구간 경계는 **녹음 시작 기준 초**로 적는다. 평가가 이 값으로
    # 「이 깨어남이 어느 구간에서 났나」를 귀속시킨다.
    marks = []
    cur = -1

    def _meter(rms):
        n = min(20, int(rms / 0.02 * 20))
        return "█" * n + "·" * (20 - n)

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                            dtype="float32", blocksize=1600, device=dev) as stream:
            while True:
                elapsed = time.time() - started
                if elapsed >= total:
                    break
                chunk, overflowed = stream.read(1600)       # 0.1초
                if overflowed:
                    pass                                    # 한 블록 밀린 것 — 버리지 않는다
                mono = chunk[:, 0]
                rms = float(np.sqrt(np.mean(mono ** 2)))
                peak = max(peak, rms)
                blocks += 1
                if rms >= SPEECH_RMS:
                    loud += 1
                wf.writeframes((np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
                frames += len(mono)

                # 구간이 바뀌면 줄을 바꿔 크게 알린다 — 지나치면 자료가 섞인다.
                if phases:
                    idx = min(int(elapsed / (total / len(phases))), len(phases) - 1)
                    if idx != cur:
                        cur = idx
                        nm, how = phases[idx]
                        marks.append({"name": nm, "start": round(elapsed, 2)})
                        sys.stdout.write("\r" + " " * 78 + "\r\n")
                        sys.stdout.write(f"   ── {idx + 1}/{len(phases)}  「{nm}」 {how}\n")
                        sys.stdout.flush()

                if blocks % 5 == 0:
                    left = total - elapsed
                    pctv = (loud / blocks * 100) if blocks else 0
                    tag = f"  [{phases[cur][0]}]" if phases and cur >= 0 else ""
                    sys.stdout.write(
                        f"\r   {_fmt(elapsed)} / {_fmt(total)}   남은 {_fmt(left)}   "
                        f"[{_meter(rms)}]  소리 {pctv:4.1f}%{tag}   ")
                    sys.stdout.flush()
    except KeyboardInterrupt:
        stopped_early = True
    finally:
        wf.close()

    dur = frames / SAMPLE_RATE
    ratio = (loud / blocks * 100) if blocks else 0.0

    # 🔑 **오디오만 남기면 어느 구간이 어디였는지 영영 모른다.** 옆에 표를 둔다.
    if marks:
        for k, mk in enumerate(marks):
            mk["end"] = round(marks[k + 1]["start"] if k + 1 < len(marks) else dur, 2)
        side = out[:-4] + ".phases.json"
        io.open(side, "w", encoding="utf-8").write(json.dumps(
            {"wav": os.path.basename(out), "durationSec": round(dur, 2), "phases": marks},
            ensure_ascii=False, indent=2))
    print("\n")
    if stopped_early:
        print("⏹  중간에 멈췄어요. 거기까지는 저장됐습니다.")
    print(f"✓ 저장했어요 — {os.path.relpath(out, ROOT)}")
    print(f"   길이 {_fmt(dur)} ({dur / 3600:.2f}시간) · 소리 있는 구간 {ratio:.1f}% · 최대 세기 {peak:.4f}")
    if marks:
        print(f"   구간표  {os.path.relpath(out[:-4] + '.phases.json', ROOT)}")
        for mk in marks:
            print(f"     {_fmt(mk['start'])}~{_fmt(mk['end'])}  {mk['name']}")
    print()

    # 🚨 **조용한 녹음은 오탐을 좋아 보이게 만든다.** 아무 소리도 없는 20분으로 재면
    #   헛깨어남 0회가 나오고, 그 숫자는 아무것도 보증하지 않는다.
    #   2026-09-28 에 분모를 잘못 잡아 성적이 좋아 보였던 것과 같은 모양이다.
    if ratio < 10:
        print("🚨 **소리 있는 구간이 너무 적습니다.** 이대로 재면 헛깨어남이 적게 나오는데,")
        print("   그건 모델이 좋아서가 아니라 **들을 게 없어서**입니다.")
        print("   평소처럼 말하거나 영상을 틀어 놓고 다시 받아 주세요.")
    elif dur < 600:
        print("⚠️  10분이 안 됩니다. 시간당 횟수로 환산하면 오차가 큽니다 — 20분 이상 권합니다.")
    else:
        print("🔑 이제 이걸로 오탐만 다시 잽니다:")
        print()
        print("   python scripts/eval_wakeword.py --compare services/wakeword_model.npz \\")
        print(f"          --soak {os.path.relpath(out, ROOT)} --holdout-only")
        print()
        print("   대선토론에서 25회/시간이던 것이 여기서 몇 회로 나오는지가 답입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
