"""받아 온 녹음(wav + json)을 학습용 배열로 모은다 — M7 ②③

    conda activate pluiz
    python scripts/ingest_wakeword.py                  # data/wakeword_raw/ 를 읽는다
    python scripts/ingest_wakeword.py --list           # 누가 몇 개 보냈는지만 본다
    python scripts/ingest_wakeword.py --holdout 4      # 미학습 화자 4명을 «제비뽑기»로
    python scripts/ingest_wakeword.py --holdout-names "$(cat data/wakeword/holdout_names.txt)"
                                                      # 🔒 실명은 저장소에 두지 않는다
                                                      #    (그 파일은 data/ 안 — .gitignore)
                                                      # 🔑 이름으로 직접 — 녹음이 늘어도 안 바뀐다

입력 — `scripts/플루이즈_녹음.html` 이 만든 파일 쌍을 `data/wakeword_raw/` 에 넣는다.

    data/wakeword_raw/
      pluiz_홍길동_20260918T142301.wav
      pluiz_홍길동_20260918T142301.json   ← 언제 무엇을 말했는지

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
import datetime
import json
import os
import re
import sys
import wave

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(_ROOT, "data", "wakeword_raw")
OUT = os.path.join(_ROOT, "data", "wakeword")

SR = 16000          # scripts/wakeword_data.py · train_wakeword.py 와 같아야 한다
RMS_MIN = 0.0025    # 🚨 2026-09-16: 0.006 이었다. 그건 «통짜 녹음에서 구간 찾기» 값인데
                    #   여기는 라벨이 있어 찾을 필요가 없다. 런타임 관문(0.0015)보다
                    #   약간 위면 «말을 했나»를 가르기에 충분하다. 페이지와 같은 값.
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


def _speaker_key(name: str) -> str:
    """홀드아웃에서 «같은 사람»을 가리는 열쇠. 뒤에 붙은 괄호를 뗀다.

    `김예은` 과 `김예은(다시)` 는 **한 사람**이다(첫 녹음이 끊겨 다시 했다).
    문자열 그대로 세면 두 사람이 되고, 한쪽이 학습·한쪽이 홀드아웃에 들어가면
    검증이 **같은 편향의 거울**이 된다 → M7 §5-2.
    """
    return re.sub(r"\s*[（(].*?[)）]\s*$", "", name).strip() or name


def _split_names(items):
    """«녹음자1,녹음자3» 도 «녹음자1 녹음자3» 도 같게 읽는다.

    쉼표를 찍을지 띄어쓸지를 사람이 기억하게 만들지 않는다 — 둘 다 받는다.
    """
    out = []
    for it in items:
        out += [x.strip() for x in str(it).split(",")]
    return [x for x in out if x]


def _pull_note() -> str:
    """🚨 **이 숫자는 로컬 폴더를 센 것이다** — 그 사실을 숫자 옆에 붙인다.

    `pull.mjs` 가 남기는 `.last_pull` 을 읽어 «언제 가져온 것인가»를 같이 말한다.
    없거나 오래됐으면 **먼저 가져오라고 말한다.**

    ## 왜 있나 — 2026-09-28 에 이것 때문에 사고가 났다

    서버(Blob)에 26명이 있는데 `--list` 가 **6명**을 찍었다. 틀린 게 아니라
    «마지막으로 가져왔을 때 6명이었다»가 맞는 답이었는데, **출력이 그 둘을
    구분해 주지 않았다.** 그 숫자로 «14명 더 필요»가 사용자 몫 1순위에 올라갔고
    현황판 대문에 «D-8 녹음 마감»이 박혔다 — **이미 채워진 목표였다.**

    🔑 이 저장소가 반복해서 배운 것과 같은 모양이다 — **재는 자가 무엇을 재는지
    말하지 않으면, 읽는 사람이 다른 것을 잰 줄 안다.**
    """
    stamp = os.path.join(RAW, ".last_pull")
    if not os.path.exists(stamp):
        return ("\n  🚨 **아직 한 번도 서버에서 가져온 적이 없습니다**(또는 기록이 없습니다).\n"
                "     이 숫자는 로컬 폴더만 센 것입니다 — 서버에 더 있을 수 있습니다.\n"
                "     → cd scripts/collect-server && npm run pull")
    try:
        with open(stamp, encoding="utf-8") as f:
            when = datetime.datetime.fromisoformat(f.read().strip().replace("Z", "+00:00"))
    except Exception:                                   # noqa: BLE001
        return "\n  ⚠️ .last_pull 을 읽지 못했습니다 — 서버에서 먼저 가져오세요."

    now = datetime.datetime.now(datetime.timezone.utc)
    hours = (now - when).total_seconds() / 3600
    local = when.astimezone().strftime("%Y-%m-%d %H:%M")
    if hours < 1:
        return f"\n  (서버에서 가져온 때: {local} — 방금)"
    if hours < 24:
        return f"\n  (서버에서 가져온 때: {local} — {int(hours)}시간 전)"
    return (f"\n  🚨 **마지막으로 가져온 때가 {local}({int(hours/24)}일 전)입니다.**\n"
            f"     그 뒤에 들어온 녹음은 이 숫자에 **안 들어 있습니다.**\n"
            f"     → cd scripts/collect-server && npm run pull")


def main():
    ap = argparse.ArgumentParser(description="녹음본을 학습용 배열로 모은다")
    ap.add_argument("--list", action="store_true", help="누가 몇 개 보냈는지만 본다")
    ap.add_argument("--holdout", type=int, default=0,
                    help="미학습 화자 N명을 떼어 둔다 (M7 §5-2)")
    ap.add_argument("--seed", type=int, default=0, help="홀드아웃 선택 난수")
    ap.add_argument("--holdout-names", nargs="+", default=None, metavar="이름",
                    help="홀드아웃을 이름으로 직접 지정한다 (쉼표·공백 둘 다 됨). "
                         "주면 --holdout/--seed 는 안 쓴다")
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

    print(f"\n받은 녹음 {len(sessions)}개 · 화자 {len(by_speaker)}명{_pull_note()}")
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
    #
    # 🚨 **이름 문자열로 사람을 세면 같은 사람이 둘이 된다** (2026-09-28 에 실제로 났다).
    #   26명 중에 `김예은` 과 `김예은(다시)` 가 있었다 — 첫 녹음이 중간에 끊겨 다시 한
    #   것이다. 문자열로 보면 두 사람이라 **한쪽은 학습, 한쪽은 홀드아웃**에 들어갈 수
    #   있었고, 그러면 M7 §5-2 가 막으려던 바로 그것이 된다 —
    #   **«검증이 아니라 같은 편향의 거울».**
    #   그래서 뒤에 붙은 괄호를 떼고 **같은 사람으로 묶는다.** 묶인 것은 말한다.
    #
    # 🚨 그리고 **구간이 0인 화자를 홀드아웃으로 뽑지 않는다.** `나나` 가 0구간인데
    #   뽑히면 «4명 뗐다»고 적히고 실제로는 3명이다 — 분모가 조용히 줄어든다.
    groups: dict[str, set] = {}
    for nm in by_speaker:
        groups.setdefault(_speaker_key(nm), set()).add(nm)
    merged = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    if merged:
        print("\n🔗 같은 사람으로 묶었습니다(괄호를 뗀 이름이 같습니다):")
        for k, v in sorted(merged.items()):
            print(f"   · {k} ← {' · '.join(v)}")
        print("   이렇게 안 묶으면 한 사람이 학습과 홀드아웃에 나뉘어 들어갑니다(M7 §5-2).")

    n_segs = {k: sum(len(m.get("segments") or []) for nm in v for m, _ in by_speaker[nm])
              for k, v in groups.items()}
    empty = sorted(k for k, c in n_segs.items() if c == 0)
    if empty:
        print(f"\n⚠️ 구간이 0인 화자 {len(empty)}명 — 홀드아웃 후보에서 뺍니다: {', '.join(empty)}")

    # 🚨 **제비뽑기는 사람이 늘면 다른 사람을 뽑는다** (2026-10-03 에 실제로 났다).
    #   9/28 에 `--seed 2` 로 뽑은 네 명(녹음자1·녹음자3·녹음자5·녹음자9)이, 그 뒤 녹음이
    #   둘 늘자 **같은 seed 에서 녹음자3 대신 녹음자4**이 됐다.
    #
    #   🔑 녹음자4은 **지금 런타임 모델이 학습한 사람**이다. 홀드아웃에 넣으면
    #   «전» 모델이 **자기가 배운 사람으로 채점받아** 부당하게 좋아 보이고, 그러면
    #   후보가 상대적으로 나빠 보인다 — **좋아진 모델을 버릴 수 있다.**
    #   그리고 이것은 **오류를 내지 않는다.** 그냥 틀린 숫자가 나온다.
    #
    #   → 그래서 `--holdout-names` 로 **이름을 직접 적을 수 있게** 한다. 녹음이 더
    #   들어와도 안 바뀐다. seed 를 매번 다시 찾는 «마법의 숫자»를 만들지 않는다.
    holdout: set[str] = set()
    pool = sorted(k for k in groups if n_segs[k] > 0)
    keys: list[str] = []
    by_name = bool(args.holdout_names)

    if by_name:
        if args.holdout > 0:
            print("\n⚠️ --holdout-names 를 줬으므로 --holdout 숫자는 쓰지 않습니다.")
        want = [_speaker_key(x) for x in _split_names(args.holdout_names)]
        missing = [w for w in want if w not in pool]
        if missing:
            # 🚨 **조용히 건너뛰지 않는다.** 이름이 하나 틀렸는데 그냥 넘어가면
            #   «5명 뗐다»고 적히고 실제로는 4명이다 — 분모가 조용히 줄어든다.
            #   (구간 0 인 화자를 홀드아웃에서 빼는 것과 같은 이유다.)
            print(f"\n✗ 홀드아웃으로 지정한 이름 중 쓸 수 없는 것: {', '.join(missing)}")
            zero = [w for w in missing if w in groups]
            if zero:
                print(f"   ㄴ {', '.join(zero)} 는 **구간이 0** 이라 홀드아웃이 될 수 없습니다.")
            print(f"   쓸 수 있는 이름 {len(pool)}개 — {', '.join(pool)}")
            return 1
        keys = sorted(dict.fromkeys(want))
    elif args.holdout > 0:
        if args.holdout >= len(pool):
            print(f"\n✗ 쓸 수 있는 화자가 {len(pool)}명인데 {args.holdout}명을 떼려 합니다.")
            return 1
        rng = np.random.default_rng(args.seed)
        keys = rng.choice(pool, size=args.holdout, replace=False).tolist()

    if keys:
        holdout = {nm for k in keys for nm in groups[k]}
        print(f"\n🔒 홀드아웃(미학습 화자) {len(keys)}명: {', '.join(sorted(keys))}")
        if by_name:
            print("   🔑 이름으로 직접 지정했습니다 — **녹음이 더 들어와도 안 바뀝니다.**")
        else:
            print(f"   ⚠️ 제비뽑기입니다(seed={args.seed}) — **녹음이 늘면 다른 사람이 뽑힙니다.**")
        if holdout != set(keys):
            print(f"   ㄴ 실제로 떼는 세션 이름: {', '.join(sorted(holdout))}")
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
        # 🚨 **새 라벨을 여기 안 넣으면 매니페스트가 거짓이 된다.** 아래에서
        #   `counts[lab if lab in counts else "negative"]` 로 떨어지므로 **소리는
        #   제대로 실리는데 기록만 «negative» 로 적힌다** — 나중에 «명령 구간이 몇 개
        #   들어갔나»를 물으면 답할 수가 없다.
        counts = {"positive": 0, "negative": 0, "command": 0, "freetalk": 0, "quiet": 0}

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
    print("  python scripts/train_wakeword.py")
    print("  🔑 인자가 없습니다 — 학습기가 이 폴더의 positive.npy 와 negative.npy 를")
    print("     **둘 다 자동으로** 읽습니다 (2026-09-23 배선).")
    print("     그 전에는 양성만 받았고, `--user-audio` 를 명시하지 않으면")
    print("     녹음이 **통째로 빠진 채** 학습이 돌았습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
