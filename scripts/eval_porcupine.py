# -*- coding: utf-8 -*-
"""상용 대조 — **Porcupine 을 «제품»이 아니라 «자»로 쓴다**

    python scripts/eval_porcupine.py --keyword 플루이즈_ko_windows.ppn
           --model-params porcupine_params_ko.pv --soak data/soak_16k.wav

## 이 스크립트가 답하는 질문은 «무엇을 쓸까»가 아니다

**«시간당 오탐 1회 이하»가 도달 가능한 값이긴 한가.**

지금 우리 목표는 [M7](../docs/design/M7_웨이크워드_재구축.md)에 «FA ≤ 1회/시간»으로 적혀
있는데, 그게 **이 방·이 마이크·이 오디오에서 실제로 닿는 값인지는 아무도 안 재 봤다.**
현행 모델은 74.7회이고, 임계도 에너지 관문도 전부 목표 밖이라는 것까지만 안다
(→ [기준선](../docs/research/2026-09_웨이크워드_기준선.md)).

그래서 **상용 엔진을 같은 자에 올려 상한선을 본다.** 재학습 후보가 나왔을 때
«잘 나왔다/못 나왔다»를 **무엇에 대고** 말할지가 생긴다.

## 🚨 채택 판단이 아니다

여기서 나오는 표는 **품질의 상한선**이지 «Porcupine 을 쓰자»가 아니다. 전시에 쓰려면
라이선스(무료 티어의 범위 · 공개 시연 가능 여부 · 키워드 만료)가 먼저 확인돼야 하고,
그건 이 스크립트가 답할 수 있는 것이 아니다. → 출력 맨 끝에도 같은 말을 적는다.

## 🔒 자는 하나여야 한다 — 그래서 여기엔 채점 코드가 없다

`eval_wakeword.py` 에서 **채점·판정을 그대로 import** 한다(`score` · `replay` ·
`print_compare_table`). 베껴 적으면 언젠가 한쪽만 고쳐지고, 그러면 **어느 쪽이 나은가가
도구에 따라 달라진다.** 여기가 새로 하는 일은 딱 하나다 — Porcupine 을 돌려
**«깬 시각 목록»** 을 만드는 것.

## 두 엔진을 어떻게 «같은 조건»에 놓았나

| | 우리 모델 | Porcupine |
|---|---|---|
| 운용점 | 임계 0~1 (**올리면 덜 깬다**) | 민감도 0~1 (**올리면 더 깬다**) |
| 한 번에 보는 것 | 2.0초 창을 0.6초마다 | 512샘플 프레임을 **연속 스트리밍** |
| 쿨다운 | 2.5초 | **같은 2.5초를 씌운다** ← 여기 |
| 귀속 규칙 | 깬 시각 t → 창 [t-2.0, t] 와 가장 많이 겹치는 구간 | **같은 규칙** |

🔑 **쿨다운과 귀속 규칙을 같게 맞춘 것이 이 비교의 전부다.** Porcupine 원본 검출을
그대로 세면 우리 쪽만 쿨다운으로 오탐이 줄어든 상태가 되어 **자가 기운다.**
그래서 Porcupine 의 검출도 `eval_wakeword.replay()` 에 통과시킨다 — 우리 모델이 쓰는
**바로 그 함수**다.

⚠️ **귀속 창 [t-2.0, t] 는 우리 모델의 창 길이에서 온 값**이라 Porcupine 에는 조금
후한 쪽이다(늦게 깬 것도 앞 구간에 붙을 수 있다). **둘에 같은 규칙을 쓰는 것**이
기울기를 없애는 유일한 길이라 그대로 두고, 대신 여기 적어 둔다.

## 민감도는 «공짜로 훑을» 수 없다

우리 모델은 창마다 확률을 한 번 구해 두면 임계 훑기가 공짜다. **Porcupine 은 민감도가
생성 시점에 박히고 확률을 안 준다.** 그래서 민감도 하나당 오디오를 한 번씩 봐야 한다.

🔑 그래서 **인스턴스를 민감도 수만큼 띄워 같은 프레임을 한 번에 먹인다.** 오디오는
한 번만 읽고, 각 인스턴스는 **완전히 같은 프레임 순서**를 본다 — 즉 민감도를 몇 개
주든 **결과가 안 바뀐다.** (`--jobs` 가 학습 결과를 바꾸면 안 되는 것과 같은 이유다.
→ [M7 §6-2](../docs/design/M7_웨이크워드_재구축.md))

## ⚠️ 건너뛰지 않는다

`pvporcupine` 이 없거나 키가 없으면 **조용히 건너뛰고 «통과»라고 말하지 않는다.**
무엇이 없는지 말하고 죽는다.

## 준비물 — **사람이 해야 하는 것은 하나뿐이다**

🔴 **AccessKey** — console.picovoice.ai 에서 무료로 받는다(가입 필요).
   `PICOVOICE_ACCESS_KEY` 환경변수 또는 `--access-key`.

나머지는 이 스크립트가 한다:

| | 무엇 | 어떻게 |
|---|---|---|
| ✅ | `pvporcupine` | 2026-09-21 에 `pluiz` 환경에 깔았다. ⚠️ **`requirements.txt` 에는 안 넣었다** — 런타임이 아니라 대조 측정용이다 |
| ✅ | 한국어 모델 `porcupine_params_ko.pv` | `data/porcupine/` 에 받아 뒀다(986KB). 없으면 **여기서 받는다** |
| ✅ | 커스텀 키워드 «플루이즈» `.ppn` | 🔑 **콘솔에 안 들어가도 된다** — SDK v4 의 `train_wake_word_from_phrase` 가 문구에서 만들어 준다. 한 번 만들면 `data/porcupine/` 에 두고 다시 쓴다 |

> 🔑 **처음엔 «콘솔에서 만들어 오세요»라고 적었다. 확인해 보니 틀렸다.**
> 설치하고 나서 `dir(pvporcupine)` 를 보니 `train_wake_word_from_phrase` 가 있었고
> `VALID_LANGUAGES` 에 `ko` 가 있다. **사람 손이 필요한 자리가 셋에서 하나로 줄었다.**

⚠️ **`.pv` 와 SDK 의 판(version)이 맞아야 한다.** 안 맞으면 오류 메시지가 «파일이
깨졌다»처럼 나와 엉뚱한 곳을 보게 되므로, 여기서 **먼저 보고 분명히 말한다.**

"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import numpy as np
except ImportError as e:                                     # noqa: BLE001
    sys.exit(f"[porc] FATAL: numpy 없음 ({e})")

from scripts.eval_wakeword import (                          # noqa: E402
    SAMPLE_RATE, COOLDOWN_SEC, MODEL_PATH, KwsModel,
    load_sessions, read_wav, score, replay, _curve, print_compare_table,
)

#: 받아 둔 것·만든 것을 두는 자리. `data/` 는 `.gitignore` 가 막는다
#: (모델 파일 986KB 와 키워드는 **저장소에 올릴 물건이 아니다**).
NL = chr(10)

PORC_DIR   = os.path.join(ROOT, "data", "porcupine")
KO_PARAMS  = os.path.join(PORC_DIR, "porcupine_params_ko.pv")
KO_URL = ("https://raw.githubusercontent.com/Picovoice/porcupine/master/"
          "lib/common/porcupine_params_ko.pv")

#: 기본 민감도 격자. **11칸이면 곡선 모양이 보이고**, 더 촘촘한 값이 필요하면
#: `--sensitivities` 로 좁혀서 다시 돈다 (오디오를 그만큼 더 본다).
DEFAULT_SENSITIVITIES = [round(0.1 * i, 2) for i in range(11)]


def _die(msg, hint=""):
    print(f"\n[porc] 🚨 {msg}", file=sys.stderr)
    if hint:
        print(hint, file=sys.stderr)
    sys.exit(1)


def ensure_ko_params(path):
    """한국어 모델 파라미터를 준비한다. 없으면 받는다 (키가 필요 없는 공개 파일이다)."""
    if os.path.exists(path):
        return path
    import urllib.request
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"[porc] 한국어 모델이 없다 → 받는다 ({KO_URL})", flush=True)
    tmp = path + ".part"                       # 🔑 받다 만 것을 «있다»로 두지 않는다
    try:
        urllib.request.urlretrieve(KO_URL, tmp)
        os.replace(tmp, path)
    except Exception as e:                                   # noqa: BLE001
        if os.path.exists(tmp):
            os.remove(tmp)
        _die(f"한국어 모델을 못 받았다: {e}",
             f"    손으로 받아 {path} 에 두면 된다:" + NL + f"    {KO_URL}")
    print(f"       받았다 — {os.path.getsize(path)/1024:.0f}KB")
    return path


def check_params_version(path):
    """`.pv` 의 판과 SDK 의 판이 맞는지 **먼저** 본다.

    🚨 안 맞으면 Porcupine 이 내는 말은 «파일이 깨졌다» 쪽이라, 판이 문제라는 것을
       모르면 엉뚱한 데를 파게 된다. 파일 머리에 «porcupine4.0.0» 처럼 적혀 있다.
    """
    try:
        head = open(path, "rb").read(16).decode("ascii", "ignore")
        from importlib.metadata import version
        sdk = version("pvporcupine")
    except Exception:                                        # noqa: BLE001
        return
    file_major = head[len("porcupine"):].split(".")[0] if head.startswith("porcupine") else ""
    if file_major and file_major != sdk.split(".")[0]:
        _die(f"모델 파일과 SDK 의 판이 다르다 — 파일 {head.strip()} · pvporcupine {sdk}",
             "    같은 판의 파일을 받아야 한다. Porcupine 저장소에서 SDK 와 같은 major 태그를 볼 것.")


def ensure_keyword(access_key, phrase, out_dir, language="ko"):
    """커스텀 키워드(.ppn)를 준비한다. **있으면 다시 만들지 않는다.**

    🔑 콘솔 UI 가 필요 없다 — SDK v4 가 문구를 받아 만들어 준다(REST 호출 1회).
    ⚠️ 만들어진 파일은 **플랫폼별**이라 파일명에 플랫폼을 적어 둔다. 리눅스 서버로
       옮겨 돌릴 때 «왜 안 열리나»를 파일명이 먼저 답하게 하려는 것이다.
    """
    import pvporcupine
    plat = pvporcupine.pv_get_platform()
    out = os.path.join(out_dir, f"{phrase}_{language}_{plat}.ppn")
    if os.path.exists(out):
        print(f"[porc] 키워드 재사용 — {os.path.relpath(out, ROOT)}")
        return out
    if not access_key:
        _die("AccessKey 가 없다 (키워드를 만들려면 필요하다)",
             "    Picovoice Console(console.picovoice.ai)에서 무료로 받는다." + NL +
             "    set PICOVOICE_ACCESS_KEY=...  또는  --access-key ...")
    os.makedirs(out_dir, exist_ok=True)
    print(f"[porc] 키워드 «{phrase}» 를 만든다 (language={language} · platform={plat}) …", flush=True)
    try:
        pvporcupine.train_wake_word_from_phrase(
            access_key=access_key, output_path=out, language=language, phrase=phrase)
    except Exception as e:                                   # noqa: BLE001
        _die(f"키워드 생성 실패: {e}",
             "    자주 나오는 원인 —" + NL +
             "    · AccessKey 가 틀렸거나 만료됐다" + NL +
             "    · 무료 티어의 생성 한도를 넘었다 (콘솔에서 확인)" + NL +
             "    · 망이 안 된다 (이 호출은 Picovoice 서버로 간다)")
    print(f"       만들었다 — {os.path.relpath(out, ROOT)} ({os.path.getsize(out)}바이트)")
    return out


def open_handles(access_key, keyword_path, model_params, sensitivities):
    """민감도 하나당 인스턴스 하나. **같은 프레임을 전부에게 먹이기 위해서**다."""
    try:
        import pvporcupine
    except ImportError as e:                                 # noqa: BLE001
        _die(f"pvporcupine 이 없다 ({e})",
             "    pip install pvporcupine\n"
             "    ⚠️ requirements.txt 에는 일부러 안 넣었다 — 런타임이 아니라 대조 측정용이다.")
    if not access_key:
        _die("AccessKey 가 없다",
             "    Picovoice Console(console.picovoice.ai)에서 무료로 받는다.\n"
             "    set PICOVOICE_ACCESS_KEY=...  또는  --access-key ...")
    for p, what in ((keyword_path, "키워드(.ppn)"), (model_params, "한국어 모델(.pv)")):
        if p and not os.path.exists(p):
            _die(f"{what} 파일이 없다: {p}")
    try:
        return [pvporcupine.create(
            access_key=access_key,
            keyword_paths=[keyword_path],
            model_path=model_params,
            sensitivities=[s],
        ) for s in sensitivities]
    except Exception as e:                                   # noqa: BLE001
        _die(f"Porcupine 생성 실패: {e}",
             "    자주 나오는 원인 —\n"
             "    · .ppn 을 **다른 플랫폼**(linux/mac)으로 받았다 → Windows 용으로 다시 받는다\n"
             "    · .ppn 이 한국어인데 --model-params 를 안 줬다 (영어 모델로 돌리려 한 것)\n"
             "    · AccessKey 가 만료됐거나 오타다")


def fires_per_sensitivity(handles, audio, label=""):
    """오디오를 **한 번** 훑으며 인스턴스 전부에게 같은 프레임을 먹인다.

    돌려주는 것은 민감도별 **원본 검출 시각** 목록이다. 쿨다운은 여기서 안 씌운다 —
    우리 모델과 **같은 함수**(`eval_wakeword.replay`)로 씌워야 자가 안 기운다.
    """
    n = handles[0].frame_length
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    total = len(pcm) // n
    out = [[] for _ in handles]
    t0 = time.time()
    for k in range(total):
        frame = pcm[k * n:(k + 1) * n].tolist()
        t = (k + 1) * n / SAMPLE_RATE          # 프레임의 오른쪽 끝 = 런타임의 «지금»
        for j, h in enumerate(handles):
            if h.process(frame) >= 0:
                out[j].append(t)
        if label and k and k % 20000 == 0:
            print(f"    {label} {k/total*100:5.1f}%  ({time.time()-t0:.0f}초)", flush=True)
    dropped = len(pcm) - total * n
    if dropped:
        print(f"    (끝의 {dropped}샘플 = {dropped/SAMPLE_RATE*1000:.0f}ms 는 프레임이 안 차 버렸다)")
    return out


def as_frames(fires):
    """깬 시각 목록 → `replay()` 가 먹는 (시각, 에너지, 확률) 꼴.

    🔑 확률이 없는 엔진을 확률 기반 채점기에 **거짓말로 끼워 넣는 것이 아니다.**
       `replay` 가 하는 일은 «임계를 넘은 것에 쿨다운을 씌우는 것»이고, Porcupine 은
       이미 «넘었다»만 주므로 확률 1.0·에너지 1.0 으로 두면 **쿨다운만 남는다.**
       그래야 두 엔진이 같은 쿨다운을 통과한다.
    """
    return [(t, 1.0, 1.0) for t in fires]


def porcupine_curve(handles, sensitivities, sessions, soak_paths):
    """민감도별 (FRR · FA/시간) 행 — `print_compare_table` 이 먹는 꼴로 만든다."""
    print("  ② Porcupine 을 훑는다 …", flush=True)
    sess_fires = []
    for i, s in enumerate(sessions):
        sess_fires.append(fires_per_sensitivity(handles, read_wav(s["wav"])))
        print(f"    녹음 {i+1}/{len(sessions)} — {s['speaker']}", flush=True)

    soak_fires, soak_hours = [], 0.0
    for sp in soak_paths or []:
        audio = read_wav(sp)
        soak_hours += len(audio) / SAMPLE_RATE / 3600.0
        print(f"    긴 오디오 {os.path.basename(sp)} ({len(audio)/SAMPLE_RATE/60:.1f}분) "
              f"× 민감도 {len(handles)}개 …", flush=True)
        soak_fires.append(fires_per_sensitivity(handles, audio, label=os.path.basename(sp)))

    rows = []
    for j, sens in enumerate(sensitivities):
        for s, fires in zip(sessions, sess_fires):
            s["frames"] = as_frames(fires[j])
        # 임계 0.5 는 «확률 1.0 을 통과시키는 아무 값»이다. 여기서 실제로 도는 것은 쿨다운뿐.
        r = score(sessions, 0.5, 0.0)
        fa_soak = (sum(len(replay(as_frames(f[j]), 0.5, 0.0)) for f in soak_fires) / soak_hours
                   if soak_hours > 0 else float("nan"))
        rows.append({"threshold": sens, "frr": r["frr"], "fa_rec": r["fa_per_hour"],
                     "fa_soak": fa_soak, "pos_hit": r["pos_hit"], "pos_total": r["pos_total"]})
    return rows, soak_hours


def main():
    ap = argparse.ArgumentParser(
        description="상용(Porcupine) 대조 — «목표가 도달 가능한 값인가»를 잰다")
    ap.add_argument("--keyword", metavar="플루이즈.ppn",
                    help="커스텀 키워드 파일. **안 주면 --phrase 로 만든다**(data/porcupine/)")
    ap.add_argument("--phrase", default="플루이즈",
                    help="키워드가 없을 때 이 문구로 만든다 (기본 «플루이즈»)")
    ap.add_argument("--language", default="ko", help="키워드 언어 (기본 ko)")
    ap.add_argument("--model-params", metavar="porcupine_params_ko.pv",
                    help="🔴 한국어 모델 파라미터. 기본은 data/porcupine/ 것을 쓰고, 없으면 받는다")
    ap.add_argument("--access-key", default=os.environ.get("PICOVOICE_ACCESS_KEY", ""))
    ap.add_argument("--soak", nargs="+", metavar="WAV",
                    help="라벨 없는 긴 오디오 — **이게 있어야 전시회 값이다**")
    ap.add_argument("--holdout-only", action="store_true", help="학습에 안 들어간 화자만")
    ap.add_argument("--sensitivities", metavar="0.1,0.3,…",
                    help=f"기본 {DEFAULT_SENSITIVITIES}")
    ap.add_argument("--check", action="store_true",
                    help="🔑 **재료만 마련하고 끝낸다** — 키가 되는지 10초 만에 본다. "
                         "본 측정은 10~30분이라 «키가 틀렸다»를 그 끝에서 알면 안 된다")
    a = ap.parse_args()

    sens = ([float(x) for x in a.sensitivities.split(",")] if a.sensitivities
            else list(DEFAULT_SENSITIVITIES))
    if not all(0.0 <= s <= 1.0 for s in sens):
        _die(f"민감도는 0~1 이다: {sens}")

    # ── 재료를 마련한다. **사람 손이 필요한 것은 AccessKey 하나뿐이다** ──
    if a.language == "ko":
        params = a.model_params or ensure_ko_params(KO_PARAMS)
    else:
        params = a.model_params
    if not params:
        print(f"[porc] ⚠️ language={a.language} 인데 --model-params 가 없다 — "
              "**영어 모델**로 돈다. 한국어 키워드라면 이 측정은 무효다.")
    else:
        check_params_version(params)
    keyword = a.keyword or ensure_keyword(a.access_key, a.phrase, PORC_DIR, a.language)

    sessions, _have = load_sessions(a.holdout_only)
    if not sessions and not a.check:
        _die("잴 녹음이 없다 — FRR 을 못 재면 비교가 안 된다",
             "    data/wakeword_raw/ 에 (wav, json) 쌍이 있어야 한다.")

    print("[porc] 🔵 상용 대조 — «시간당 1회»가 닿는 값인지 본다")
    print(f"       키워드 {os.path.basename(keyword)}"
          f"{' · 모델 ' + os.path.basename(params) if params else ''}")
    print(f"       민감도 {len(sens)}칸 {sens}")
    print(f"       녹음 {len(sessions)}개 · 쿨다운 {COOLDOWN_SEC}s "
          f"(우리 모델과 **같은 값을 씌운다**)")
    if not a.soak:
        print("\n🚨 `--soak` 가 없다 — FA/시간이 **라벨 녹음**에서 나온다.")
        print("   그 분모는 몇 분이고 절반이 오탐을 유도하려고 만든 문장이다. **참고값이다.**")
    print()

    if a.check:
        # 🔑 «파일이 생겼다»에서 멈추지 않는다 — **실제로 열어 본다.**
        #    키가 틀리면 생성 때가 아니라 여는 때에 드러나는 경우가 있다.
        h = open_handles(a.access_key, keyword, params, [0.5])
        print(f"{NL}  ✅ 열린다 — 프레임 {h[0].frame_length}샘플 · {h[0].sample_rate}Hz")
        for x in h:
            x.delete()
        print("  🔑 키·모델·키워드가 전부 준비됐다. 이제 본 측정을 돌리면 된다:")
        print("     python scripts/eval_porcupine.py --soak data/soak_16k.wav")
        return 0

    print("  ① 우리 모델을 훑는다 …", flush=True)
    base_rows, hours = _curve(KwsModel(MODEL_PATH), sessions, a.soak)

    handles = open_handles(a.access_key, keyword, params, sens)
    try:
        porc_rows, _h = porcupine_curve(handles, sens, sessions, a.soak)
    finally:
        for h in handles:
            h.delete()

    fa_key = "fa_soak" if a.soak else "fa_rec"
    src = f"긴 오디오 {hours:.2f}시간" if a.soak else "라벨 녹음(참고)"
    rc = print_compare_table(
        base_rows, porc_rows, fa_key, src,
        n_calls=base_rows[0]["pos_total"],
        base_name="우리", cand_name="포큐파인",
        point_label="임계(우리) / 민감도(포큐파인)",
        is_soak=bool(a.soak),
        revert_hint=None,
    )

    print("\n── 🚨 이 표로 하면 안 되는 말 ──────────────────")
    print("  · «포큐파인을 쓰자» — 이건 **품질의 상한선**이지 채택 판단이 아니다.")
    print("    라이선스(무료 티어 범위 · 공개 시연 · 키워드 만료)가 먼저다.")
    print("  · «우리 모델이 형편없다» — 지금 비교되는 것은 **데이터 규모**다.")
    print("    상용은 수천 시간·수만 화자로 학습했다(M7 §7).")
    print("\n── ✅ 이 표로 할 수 있는 말 ────────────────────")
    print("  · «FA ≤ 1회/시간이 이 오디오에서 도달 가능한가» — 위 표 첫 줄이 답한다.")
    print("  · 재학습 후보가 나왔을 때 **무엇에 대고** 잘 나왔다고 할지의 기준.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
