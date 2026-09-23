# -*- coding: utf-8 -*-
"""가입이 필요 없는 대조 — **openWakeWord 공식 모델을 같은 오디오에 올린다**

    python scripts/eval_oww_reference.py --soak data/soak_16k.wav

## 이 자가 답하는 것은 딱 하나다

**«우리 오디오가 원래 이런 것인가, 아니면 우리 모델이 유난한 것인가.»**

우리 모델은 연속 말소리 1.94시간에 **시간당 74.7회** 깨어난다. 그런데 그 숫자만으로는
**둘 중 어느 쪽인지 구별이 안 된다**:

- ⓐ 이 오디오(대선토론 — 사람이 쉬지 않고 말한다)가 **원래 웨이크워드에 가혹**하거나
- ⓑ **우리 모델이 유난히 아무 말에나 깨거나**

같은 오디오에 **잘 학습된 다른 모델**을 올려 보면 갈린다. openWakeWord 가 배포하는
공식 모델(`alexa` · `hey_jarvis` · `hey_mycroft`)은 **우리가 쓰는 바로 그 임베딩 백본**에
얹힌 분류기이고, **대규모 데이터로 학습된 것**이다 — 우리 npz 와 **같은 자리에 있는
같은 종류의 물건**이라는 뜻이다.

## 🚨 이 자가 답하지 **못하는** 것 — 먼저 적는다

1. 🔴 **FRR(놓침)을 못 잰다.** 우리 녹음에서 *"헤이 자비스"* 라고 부른 사람이 없다.
   **이 도구는 오탐 한쪽만 재는 반쪽 자다.**
2. 🔴 **언어가 다르다.** 한국어 말소리가 영어 호출어를 깨울 확률은, 한국어 호출어를
   깨울 확률보다 **원래 낮다.** 그래서 이 숫자를 **«우리도 이만큼 갈 수 있다»로 읽으면
   안 된다.** 낮게 나오는 데에는 «잘 학습돼서»와 «언어가 달라서»가 **섞여 있다.**
3. 그래서 이 값은 **상한선이 아니라 «바닥»** 이다 — 정보가 한쪽으로만 흐른다:

| 결과 | 말할 수 있는 것 |
|---|---|
| 공식 모델도 **높게** 나온다 | 🔑 **ⓐ가 참이다** — 이 오디오가 가혹하다. 목표(≤1)를 이 오디오로 재는 것 자체를 다시 봐야 한다 |
| 공식 모델이 **낮게** 나온다 | ⚠️ ⓑ**일 수 있다**는 정도. 언어 차이가 섞여 있어 **단정하지 않는다** |

> 🔑 **약한 자라는 것을 알면서 만든다.** 지금 74.7 옆에 **아무 숫자도 없어서**
> «이게 얼마나 나쁜 건지»를 말할 근거가 상용 추정치뿐이다. 반쪽이라도 **측정된 것**이
> 하나 있는 쪽이 낫고, **무엇을 못 말하는지 도구가 직접 적으면** 잘못 인용되지 않는다.

## 🔒 자는 하나여야 한다

쿨다운·임계 재생·FA 계산은 [`eval_wakeword.py`](eval_wakeword.py) 것을 **그대로 쓴다.**
여기가 새로 하는 일은 «공식 모델을 돌려 창마다 점수를 얻는 것»뿐이다.

## 격자를 우리 것에 맞춘다

openWakeWord 는 **80ms(1280샘플)마다** 점수를 낸다. 우리 런타임은 **0.6초마다** 한 번이다.
그대로 두면 공식 모델이 **7.5배 많은 기회**를 갖게 되어 오탐이 부풀려진다.
그래서 **0.6초 칸마다 최댓값**을 그 칸의 점수로 삼는다 — 칸의 오른쪽 끝이 시각이고,
이러면 **두 모델이 같은 격자 위에 선다.**

⚠️ **정확히 안 나눠떨어진다.** 0.6초는 80ms **7.5칸**이라 **8칸(0.64초)** 으로 올려 잡았다.
즉 공식 모델 쪽 격자가 **6.7% 성기다** — 깰 기회가 그만큼 적다. 쿨다운 2.5초가
지배적이라 영향은 작지만, **기운다면 공식 모델에 유리한 쪽**이다.
🔑 **유리한 쪽으로 기울여 두는 것이 안전하다** — 이 도구의 위험은 «공식 모델이 낮게
나왔다»를 과하게 읽는 것이고, 그 방향으로 기울어 있으면 **결론이 더 조심스러워진다.**
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import numpy as np
except ImportError as e:                                     # noqa: BLE001
    sys.exit(f"[owwref] FATAL: numpy 없음 ({e})")

from scripts.eval_wakeword import (                          # noqa: E402
    SAMPLE_RATE, HOP_SECONDS, MODEL_PATH, KwsModel,
    read_wav, scan, replay, kws_threshold,
)

#: 공식 사전학습 모델. **우리와 같은 백본**에 얹힌 분류기들이다.
DEFAULT_REFS = ["hey_jarvis_v0.1", "alexa_v0.1", "hey_mycroft_v0.1"]

#: 훑을 임계. 우리 `--sweep` 과 같은 칸이라 표를 나란히 읽을 수 있다.
THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]

OWW_CHUNK = 1280                                  # 80ms — openWakeWord 가 정한 값


def _die(msg, hint=""):
    print(f"\n[owwref] 🚨 {msg}", file=sys.stderr)
    if hint:
        print(hint, file=sys.stderr)
    sys.exit(1)


def ref_model_path(name):
    """공식 모델 파일 경로. **받지 않는다** — 패키지에 들어 있는 것을 쓴다."""
    import openwakeword
    d = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
    p = os.path.join(d, name if name.endswith(".onnx") else name + ".onnx")
    if not os.path.exists(p):
        have = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".onnx"))
        _die(f"그런 공식 모델이 없다: {name}", f"    있는 것: {', '.join(have)}")
    return p


def scan_reference(path, audio):
    """공식 모델을 돌려 **우리 격자(0.6초)** 위의 (시각, 에너지, 점수)를 만든다.

    🔑 80ms 점수를 0.6초 칸의 **최댓값**으로 모은다. 안 그러면 공식 모델이 7.5배 많은
       기회를 갖고, 그건 모델 차이가 아니라 **격자 차이**다.
    ⚠️ 에너지는 1.0 으로 둔다 — 에너지 관문은 **우리 런타임의 장치**이고, 남의 모델에
       씌우면 그 모델을 우리 설정으로 깎는 것이 된다. 여기서 재는 것은 **모델**이다.
    """
    try:
        from openwakeword.model import Model
    except ImportError as e:                                 # noqa: BLE001
        _die(f"openwakeword 가 없다 ({e})", "    `pluiz` 환경인지 확인할 것.")
    m = Model(wakeword_models=[path], inference_framework="onnx")
    key = list(m.models.keys())[0]

    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    per_hop = max(1, int(round(HOP_SECONDS * SAMPLE_RATE / OWW_CHUNK)))   # 0.6s → 8칸(0.64s)
    frames, bucket = [], []
    for k in range(len(pcm) // OWW_CHUNK):
        bucket.append(float(m.predict(pcm[k * OWW_CHUNK:(k + 1) * OWW_CHUNK])[key]))
        if len(bucket) == per_hop:
            t = (k + 1) * OWW_CHUNK / SAMPLE_RATE      # 칸의 오른쪽 끝 = 런타임의 «지금»
            frames.append((t, 1.0, max(bucket)))
            bucket = []
    return frames, key


def main():
    ap = argparse.ArgumentParser(
        description="공식 사전학습 모델을 같은 오디오에 올린다 (가입·키 불필요)")
    ap.add_argument("--soak", nargs="+", required=True, metavar="WAV",
                    help="🔴 라벨 없는 긴 오디오. **이 도구는 오탐만 잰다**")
    ap.add_argument("--refs", nargs="+", default=DEFAULT_REFS,
                    help=f"공식 모델 이름 (기본 {DEFAULT_REFS})")
    a = ap.parse_args()

    print("[owwref] 🔵 «이 오디오가 원래 가혹한가»를 본다 — 가입도 키도 필요 없다")
    print(f"         공식 모델 {len(a.refs)}개 · 임계 {len(THRESHOLDS)}칸")
    print("🚨 **FRR 은 못 잰다** — 우리 녹음에서 «헤이 자비스»라고 부른 사람이 없다.\n")

    audios, hours = [], 0.0
    for p in a.soak:
        au = read_wav(p)
        audios.append((p, au))
        hours += len(au) / SAMPLE_RATE / 3600.0
    print(f"  오디오 {len(audios)}개 · 합계 {hours:.2f}시간\n")

    rows = {}

    # ── ① 우리 모델 (같은 오디오·같은 격자) ──────────────────────
    print("  ① 우리 모델을 훑는다 …", flush=True)
    ours = KwsModel(MODEL_PATH)
    our_frames = [scan(ours, au, 0.0) for _p, au in audios]
    rows[f"우리 ({ours.wake_word})"] = [
        sum(len(replay(fr, th, 0.0)) for fr in our_frames) / hours for th in THRESHOLDS]

    # ── ② 공식 모델들 ───────────────────────────────────────────
    for name in a.refs:
        print(f"  ② 공식 «{name}» 을 훑는다 …", flush=True)
        path = ref_model_path(name)
        fr_all = []
        for _p, au in audios:
            fr, key = scan_reference(path, au)
            fr_all.append(fr)
        rows[f"공식 ({name.split('_v')[0]})"] = [
            sum(len(replay(fr, th, 0.0)) for fr in fr_all) / hours for th in THRESHOLDS]

    # ── 표 ──────────────────────────────────────────────────────
    th_now = kws_threshold()
    print(f"\n── FA/시간 (오탐만 · {hours:.2f}시간 · 쿨다운은 둘 다 씌웠다) ──")
    head = "".join(f"{th:>8.2f}" for th in THRESHOLDS)
    print(f"{'모델':<22}{head}")
    print("-" * (22 + 8 * len(THRESHOLDS)))
    for label, vals in rows.items():
        print(f"{label:<22}" + "".join(f"{v:>8.1f}" for v in vals))
    print(f"\n   (런타임 임계는 {th_now:.2f} · 목표는 **≤ 1회/시간**)")

    # ── 판정 — «못 말하는 것»을 같이 적는다 ───────────────────────
    ref_best = {k: min(v) for k, v in rows.items() if k.startswith("공식")}
    our_best = min(rows[f"우리 ({ours.wake_word})"])
    print("\n── 이 표가 말하는 것 ──────────────────────────")
    print(f"  우리 모델이 낼 수 있는 가장 낮은 FA/시간 : **{our_best:.1f}**")
    for k, v in ref_best.items():
        print(f"  {k:<20} 가장 낮은 FA/시간 : **{v:.1f}**")

    worst_ref = max(ref_best.values()) if ref_best else float("nan")
    print()
    if worst_ref == worst_ref and worst_ref > 5.0:
        print("  🔑 **공식 모델도 이 오디오에서 높게 나온다.**")
        print("     → «이 오디오가 가혹하다»(ⓐ)는 쪽이 살아난다. 목표 ≤1 을 **이 오디오로**")
        print("        재는 것이 맞는지부터 다시 봐야 한다. 소크 2회차(다른 소리)가 그래서 필요하다.")
    else:
        print("  ⚠️ **공식 모델은 이 오디오에서 낮게 나온다.**")
        print("     → «잘 학습된 모델은 이런 오디오에서 안 깬다»는 쪽이지만,")
        print("        🚨 **언어가 다르다는 것이 섞여 있다.** 한국어 말소리가 영어 호출어를")
        print("        깨울 확률은 원래 낮다. **«우리도 갈 수 있다»의 증거로 쓰지 않는다.**")

    print("\n── 🚨 이 표로 하면 안 되는 말 ──────────────────")
    print("  · «공식 모델이 우리보다 낫다» — **FRR 을 안 쟀다.** 한쪽만 보고 낫다고 하지 않는다")
    print("    (그 실수를 막으려고 `--compare` 가 «같은 FA 예산에서» 비교하게 만들어져 있다)")
    print("  · «우리도 이 숫자까지 갈 수 있다» — 언어 불일치가 섞여 있다")
    print("\n── ✅ 할 수 있는 말 ───────────────────────────")
    print("  · «74.7 이라는 값이 이 오디오에서 어느 정도 위치인가» — 그 옆에 놓을 숫자가 생겼다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
