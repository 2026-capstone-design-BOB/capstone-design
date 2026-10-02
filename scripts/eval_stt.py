# -*- coding: utf-8 -*-
"""음성 인식률 측정 — «평소에 얼마나 잘 알아듣나». (10월 항목 2-10)

    python scripts/eval_stt.py                    # 우리 녹음 60발화 · google + whisper
    python scripts/eval_stt.py --engines whisper  # 망을 안 탄다
    python scripts/eval_stt.py --zeroth 60        # 중립 대조군을 같이 잰다
    python scripts/eval_stt.py --verbose          # 발화별로 다 본다
    python scripts/eval_stt.py --no-takes         # 반복 발화 보정을 끈다(아래)
    python scripts/eval_stt.py --json out.json    # 숫자를 파일로

## 🚨 첫 실측이 잡은 것은 엔진이 아니라 **정답표였다**

두 화자의 CER 이 92% 로 나왔는데 엔진이 틀린 게 아니었다 — **오디오에 문장이 두 번
들어 있었다**(녹음 페이지가 문장당 4초를 주는데 짧은 문장은 1.5초면 끝난다).
그래서 «몇 번 말했나»를 **오디오 에너지로** 판정해 정답을 그만큼 늘려 채점한다.
가설(엔진이 뱉은 글)로 판정하지 않는 이유까지 `estimate_takes` 위에 적어 뒀다.

## 🚨 **아무것도 실행하지 않는다.** 오디오를 읽고 STT 를 부르는 것이 전부다

`services/stt.py` 의 **엔진 두 개를 그대로 import 해서** 부른다. 여기서 다시 구현하지
않는다 — 복제하면 한쪽만 고쳐지고, 그러면 이 숫자는 **런타임이 아니라 이 파일을**
재게 된다(`offline_coverage.py` 가 라우터 정규식을 import 하는 것과 같은 이유).

## 🚨 표본이 둘인 이유 — **우리 녹음은 «어려우라고 고른» 문장이다**

주 표본 60발화는 `data/wakeword_raw/` 의 **negative 구간**이다. 실제 사람이 실제
마이크에 말한 소리이고 정답 문장이 파일에 적혀 있다 — 여기까지는 더 바랄 게 없다.

🔑 **그런데 그 10문장은 «플루이즈와 헷갈리라고» 만든 것이다** — *"플루트 소리 같은데"* ·
*"풀 사이즈로 해 줘"* · *"플루이즈가 뭐예요"*. 웨이크워드 오탐을 재려고 고른 표본이라
**STT 에게도 유난히 어렵다.** 이걸 그냥 «우리 인식률»이라고 적으면 **실제보다 나쁘게**
적는 것이고, 그건 유리하게 적는 것만큼이나 틀린 것이다.

그래서 **Zeroth-Korean 테스트셋**(`--zeroth N`)을 대조군으로 같이 잰다. 남이 만든
읽기 음성이라 우리 설계와 아무 상관이 없다. 두 숫자가 갈리면 **표본 탓**이고,
같이 나쁘면 **엔진 탓**이다. 하나만 재면 그 둘을 못 가른다.

## 🚨 여기 없는 것 — **«명령»을 마이크에 말한 표본**

우리가 가진 실제 마이크 녹음 중 **PC 제어 명령은 4문장뿐**이다(블루투스 셋 + 풀
사이즈 하나). 나머지는 잡담이고, `offline_coverage.py` 가 쓰는 120발화는 **로그의
텍스트**라 오디오가 없다.

🔑 **그래서 이 파일이 답하는 것은 «한국어를 얼마나 받아 적나»지 «명령을 얼마나
알아듣나»가 아니다.** → `docs/research/2026-09_음성인식률.md` §7

✅ **2026-09-24 — 녹음 페이지에 명령 슬롯을 넣었다**(`CMD_LINES` · 라벨 `command`).
   새로 받는 분들부터 이 칸이 찬다. 그때는

       python scripts/eval_stt.py --labels command

   이 **제품의 숫자**다. 기존 6명 자료에는 없으므로 기본값은 `negative` 로 둔다 —
   기본을 미리 바꾸면 «표본 0개»를 «측정했다»로 착각하게 된다.

## 자(尺)

| | 무엇 | 왜 |
|---|---|---|
| **CER** | 글자 단위 오류율(편집거리 / 정답 길이) | 한국어 주 지표. 어절이 붙었다 떨어졌다 해서 WER 은 흔들린다 |
| WER | 어절 단위 오류율 | 참고. 띄어쓰기 하나에 어절 둘이 같이 틀린다 |
| 정확 일치 | 공백·문장부호를 지우고 완전히 같은 비율 | «고칠 게 없었다»의 비율 |
| 빈 결과 | 아무 글자도 안 나온 비율 | 사용자에게 *"인식하지 못했어요"* 가 나가는 자리 |

CER 은 **공백을 지우고** 잰다. 한국어 띄어쓰기는 STT 마다 다르고, 우리 다음 단계
(캐시·라우터)는 BL-02 이래 공백에 둔감하다. 공백을 살린 값도 같이 찍는다.
"""
import argparse
import glob
import io
import json
import os
import sys
import tempfile
import time
import wave
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import numpy as np

# 🔑 구간 자르기를 **다시 쓰지 않는다** — 학습 쪽과 같은 자를 써야 «같은 소리»다.
from ingest_wakeword import SR, cut, load_pairs, read_wav

ZEROTH = os.path.join(_ROOT, "data", "corpora", "zeroth_korean", "test_data_01")


# ── 자(尺) ───────────────────────────────────────────────────────────

_PUNCT = frozenset(",.!?~…·:;-–—()[]{}" + '"' + "'" + "“”‘’「」")


def _norm(text, keep_space: bool) -> str:
    """채점용 정규화 — 문장부호를 지우고, 필요하면 공백도 지운다."""
    s = "".join(" " if ch in _PUNCT else ch for ch in str(text or ""))
    s = " ".join(s.split())
    return s if keep_space else s.replace(" ", "")


def edit_distance(a, b) -> int:
    """레벤슈타인 거리. 표준 라이브러리만 쓴다(의존성을 늘리지 않는다)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(truth: str, hyp: str, takes: int = 1) -> dict:
    """한 발화의 점수. **비율을 여기서 만들지 않는다** — 오류 수와 분모만 낸다.

    🚨 발화마다 비율을 내서 평균하면 짧은 발화가 과대 대표된다. 코퍼스 CER 은
       «오류 합 / 글자 합» 이라 합칠 때 나눠야 한다 → `aggregate`.

    `takes` 는 **그 오디오에 정답 문장이 실제로 몇 번 들어 있나**다(→ `estimate_takes`).
    2 면 정답을 두 번 이어 붙여 채점한다 — 아래 «반복 발화» 절 참조.
    """
    truth = " ".join([truth] * max(1, int(takes)))
    t_ns, h_ns = _norm(truth, False), _norm(hyp, False)
    t_sp, h_sp = _norm(truth, True), _norm(hyp, True)
    tw, hw = t_sp.split(), h_sp.split()

    return {
        "cer_chars":  len(t_ns),
        "cer_err":    edit_distance(t_ns, h_ns),
        "cers_chars": len(t_sp),
        "cers_err":   edit_distance(t_sp, h_sp),
        "wer_words":  len(tw),
        "wer_err":    edit_distance(tw, hw),
        "exact":      t_ns == h_ns and bool(t_ns),
        "empty":      not h_ns,
    }


# ── 🚨 반복 발화 — **첫 측정이 잡아낸 표본 결함** ────────────────────
#
# 2026-09-24 첫 실측에서 두 화자(화자 B·화자 D)의 CER 이 **92%** 로 나왔다.
# 그런데 출력을 보면 엔진이 틀린 게 아니었다:
#
#     정답    '블루투스 연결해 줄래'
#     google  '블루투스 연결해 줄래 블루투스 연결해 줄래'
#     whisper '블루투스 연결해줄래 블루투스 연결해줄래'
#
# **두 엔진이 독립적으로 같은 반복을 냈다.** 오디오에 문장이 실제로 두 번 들어
# 있었던 것이다 — 녹음 페이지가 문장당 **4초**를 주는데(`SLOT = 4.0`) 짧은
# 문장은 1.5초면 끝나서, *"초록 숫자가 세는 동안 말하면 됩니다"* 를 읽은 분들이
# **남는 시간을 한 번 더 말해서 채웠다.**
#
# 🔑 **틀린 것은 엔진이 아니라 정답표였다.** 웨이크워드 학습에는 아무 해가 없어서
#   (그쪽은 «무슨 말인지»가 아니라 «호출어가 아님»만 쓴다) 지금까지 안 보였다.
#
# 🚨 **그래서 판정을 «출력»이 아니라 «오디오»로 한다.** 가설(=엔진이 뱉은 글)을
#   보고 봐주면 그건 재는 게 아니라 **맞춰 주는 것**이다. 특히 Whisper 는 스스로
#   같은 구절을 되풀이하는 실패 모드가 있어(BL-53 과 이웃한 자리) 출력으로
#   판정하면 **진짜 결함을 용서해 버린다.**
#
# 판정 기준 둘을 **모두** 만족해야 «두 번 말했다»로 본다:
#   ① 에너지 구간이 2개 이상 (문장 사이에 쉼이 있다)
#   ② 글자당 발화 시간이 **1버스트 발화들의 중앙값의 1.6배 이상**
# ②의 기준선을 상수로 적지 않고 **표본에서 구한다** — 마이크·화자가 바뀌어도
# 따라가고, 이 파일에 숫자를 박아 두면 그게 또 낡는다.

_HOP = 160              # 10ms @ 16kHz
_BURST_REL = 0.12       # 최대 에너지 대비 — 절대값으로는 화자마다 음량이 달라 못 쓴다
_BURST_MIN_MS = 200     # 이보다 짧은 소리는 «말»로 안 센다
_BURST_GAP_MS = 180     # 이보다 가까운 두 구간은 한 덩어리다
_TAKE_RATIO = 1.6       # ②의 배수
_TAKE_MAX = 3           # 아무리 봐줘도 세 번까지 — 무한히 늘려 주지 않는다


def speech_bursts(pcm):
    """에너지가 있는 구간 [(시작프레임, 끝프레임)]. 10ms 단위."""
    n = len(pcm) // _HOP
    if n == 0:
        return []
    frames = np.sqrt((pcm[:n * _HOP].reshape(n, _HOP) ** 2).mean(axis=1))
    thr = max(float(frames.max()) * _BURST_REL, 0.002)
    voiced = frames > thr

    runs, i = [], 0
    while i < n:
        if voiced[i]:
            j = i
            while j < n and voiced[j]:
                j += 1
            runs.append([i, j])
            i = j
        else:
            i += 1

    merged = []
    for r in runs:
        if merged and (r[0] - merged[-1][1]) * 10 < _BURST_GAP_MS:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [tuple(r) for r in merged if (r[1] - r[0]) * 10 >= _BURST_MIN_MS]


def estimate_takes(samples):
    """표본 전체를 보고 발화별 «몇 번 말했나»를 정한다 → {표본id: 횟수}.

    🚨 **기준선을 표본에서 구하므로 발화 하나만 따로 판정할 수 없다.** 그게 맞다 —
       «이 사람이 남들보다 오래 말했나»는 남들을 봐야 알 수 있는 값이다.
    """
    rates, info = [], {}
    for sid, truth, pcm, _meta in samples:
        chars = len(_norm(truth, False))
        if not chars:
            continue
        bursts = speech_bursts(pcm)
        rate = sum(b - a for a, b in bursts) * 0.01 / chars   # 초/글자
        info[sid] = (len(bursts), rate)
        if len(bursts) == 1:
            rates.append(rate)

    if not rates:          # 전부 여러 구간이면 기준선을 못 세운다 → 아무것도 안 건드린다
        return {sid: 1 for sid in info}

    base = sorted(rates)[len(rates) // 2]
    out = {}
    for sid, (nb, rate) in info.items():
        if nb >= 2 and base > 0 and rate >= base * _TAKE_RATIO:
            out[sid] = min(_TAKE_MAX, max(2, int(round(rate / base))))
        else:
            out[sid] = 1
    return out


# ── 표본 ─────────────────────────────────────────────────────────────

def samples_ours(labels):
    """우리 녹음 → [(표본id, 정답, float32 PCM, 메타)].

    🚨 `freetalk` 는 **정답이 아니라 «무엇을 말하세요»라는 주제**다
    (*"어제 하루 뭐 하셨는지 쭉 말해 주세요"*). 채점에 쓰면 전부 틀린 것으로 센다.
    기본에서 빠진 것은 실수가 아니라 **그 칸에 정답이 없기 때문**이다.
    """
    out = []
    for js, wav in load_pairs():
        meta = json.load(io.open(js, encoding="utf-8"))
        pcm = read_wav(wav)
        who = meta.get("speaker") or os.path.basename(js)
        for i, seg in enumerate(meta.get("segments", [])):
            if seg.get("label") not in labels:
                continue
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            out.append((
                f"{who}#{i:02d}", text, cut(pcm, seg),
                {"speaker": who, "device": meta.get("device") or "?",
                 "place": meta.get("place") or "?", "label": seg.get("label")},
            ))
    return out


def samples_zeroth(n: int):
    """Zeroth-Korean 테스트셋에서 n개. **화자를 고루** 가져온다.

    🔑 정렬 → 화자 라운드로빈이라 `--zeroth` 값이 같으면 **같은 표본**이 나온다.
    난수를 안 쓰는 이유는 하나다 — 다음에 다시 재서 비교할 수 있어야 한다.
    """
    if not os.path.isdir(ZEROTH):
        print(f"  ⚠️  {ZEROTH} 가 없습니다 — 대조군을 건너뜁니다")
        return []

    by_speaker = defaultdict(list)
    for trans in sorted(glob.glob(os.path.join(ZEROTH, "*", "*", "*.trans.txt"))):
        base = os.path.dirname(trans)
        spk = os.path.basename(base)
        for line in io.open(trans, encoding="utf-8"):
            uttid, _, text = line.strip().partition(" ")
            flac = os.path.join(base, uttid + ".flac")
            if text and os.path.exists(flac):
                by_speaker[spk].append((uttid, text, flac))

    picked, order = [], sorted(by_speaker)
    for k in range(max((len(v) for v in by_speaker.values()), default=0)):
        for spk in order:
            if k < len(by_speaker[spk]) and len(picked) < n:
                picked.append(by_speaker[spk][k])
        if len(picked) >= n:
            break

    out = []
    for uttid, text, flac in picked:
        pcm = _decode_any(flac)
        if pcm is None:
            continue
        out.append((uttid, text, pcm, {"speaker": uttid.split("_")[0],
                                       "device": "zeroth(읽기음성)",
                                       "place": "-", "label": "zeroth"}))
    return out


def _decode_any(path):
    """flac 등 → 16kHz mono float32. PyAV 로 연다(런타임이 이미 쓰는 것)."""
    try:
        import av
    except ImportError:
        print("  ⚠️  PyAV 가 없어 대조군을 못 읽습니다")
        return None
    try:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SR)
        chunks = []
        with av.open(path) as container:
            for frame in container.decode(audio=0):
                for r in resampler.resample(frame):
                    chunks.append(bytes(r.planes[0]))
        for r in resampler.resample(None):
            chunks.append(bytes(r.planes[0]))
        raw = b"".join(chunks)
        if not raw:
            return None
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    except Exception as e:
        print(f"  ⚠️  {os.path.basename(path)} 를 못 읽었습니다: {e}")
        return None


def write_wav(pcm, path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2").tobytes())


# ── 측정 ─────────────────────────────────────────────────────────────

def make_engines(names):
    """런타임 STT 를 그대로 쓴다. **여기서 다시 구현하지 않는다.**

    🚨 Whisper 를 **측정 전에 미리 올린다.** `STTService.__init__` 은 백그라운드로
       모델을 읽는데, 그 로딩이 첫 발화의 지연에 섞이면 «엔진이 느린 건지 모델이
       올라오는 중인 건지» 못 가른다.
    """
    from services.stt import STTService, _postprocess

    svc = STTService()
    if "whisper" in names:
        t0 = time.monotonic()
        svc._get_whisper()
        print(f"  · Whisper 준비 {time.monotonic() - t0:.1f}s (측정에서 뺀다)")

    fns = {}
    if "google" in names:
        fns["google"] = svc._transcribe_google
    if "whisper" in names:
        fns["whisper"] = svc._transcribe_whisper
    return fns, _postprocess


def run(samples, engines, postprocess, verbose=False, use_takes=True):
    rows = []
    takes = estimate_takes(samples) if use_takes else {}
    repeated = sum(1 for v in takes.values() if v > 1)
    if repeated:
        print(f"  🚨 **반복 발화 {repeated}/{len(samples)}** — 오디오에 정답 문장이 "
              f"두 번 이상 들어 있다(녹음 슬롯 4초를 채운 것). 정답을 그만큼 늘려 채점한다")

    tmpdir = tempfile.mkdtemp(prefix="pluiz_stt_")
    try:
        for idx, (sid, truth, pcm, meta) in enumerate(samples, 1):
            n_take = takes.get(sid, 1)
            clip = os.path.join(tmpdir, f"c{idx:04d}.wav")
            write_wav(pcm, clip)
            for name, fn in engines.items():
                t0 = time.monotonic()
                try:
                    raw = fn(clip) or ""
                except Exception as e:           # 엔진이 죽어도 나머지는 계속 잰다
                    raw = ""
                    print(f"  ⚠️  {name} 오류 ({sid}): {e}")
                took = time.monotonic() - t0
                hyp = postprocess(raw)
                rows.append({
                    "id": sid, "engine": name, "truth": truth,
                    "raw": raw, "hyp": hyp, "sec": round(took, 3),
                    "dur": round(len(pcm) / SR, 2), "takes": n_take, **meta,
                    # 🔑 «라벨 그대로» 와 «반복을 반영» 을 **둘 다** 남긴다.
                    #   한쪽만 남기면 다음 사람이 어느 쪽을 본 건지 알 수 없다.
                    "raw_score":   score(truth, hyp, 1),
                    "score":       score(truth, hyp, n_take),
                    "nopost_score": score(truth, raw, n_take),
                })
                if verbose:
                    s = rows[-1]["score"]
                    mark = "✅" if s["exact"] else ("⬜" if s["empty"] else "▵")
                    rep = f" ×{n_take}" if n_take > 1 else ""
                    print(f"  {mark} [{name:7}] {truth!r}{rep} → {hyp!r} "
                          f"({took:.2f}s · CER {_pct(s['cer_err'], s['cer_chars'])})")
            if not verbose and idx % 10 == 0:
                print(f"  … {idx}/{len(samples)}")
    finally:
        for f in glob.glob(os.path.join(tmpdir, "*.wav")):
            try:
                os.unlink(f)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
    return rows


# ── 집계 ─────────────────────────────────────────────────────────────

def _pct(err, total):
    return "—" if not total else f"{100.0 * err / total:.1f}%"


def _ratio(err, total):
    return None if not total else round(100.0 * err / total, 1)


def aggregate(rows, key="score"):
    """행 묶음 → 지표. **합계를 먼저 더하고 나눈다**(발화별 비율의 평균이 아니다).

    🚨 발화별 CER 을 평균하면 짧은 발화가 과대 대표된다 — «켜» 한 글자가 틀리면
       100% 고, 40자 문장의 한 글자는 2.5% 다. 코퍼스 CER 은 «오류 합 / 글자 합» 이다.
    """
    if not rows:
        return {}
    g = lambda f: sum(r[key][f] for r in rows)
    secs = sorted(r["sec"] for r in rows)
    return {
        "n":         len(rows),
        "cer":       _ratio(g("cer_err"), g("cer_chars")),
        "cer_공백":  _ratio(g("cers_err"), g("cers_chars")),
        "wer":       _ratio(g("wer_err"), g("wer_words")),
        "정확일치":  _ratio(sum(r[key]["exact"] for r in rows), len(rows)),
        "빈결과":    _ratio(sum(r[key]["empty"] for r in rows), len(rows)),
        "지연중앙":  round(secs[len(secs) // 2], 2),
        "지연p90":   round(secs[min(len(secs) - 1, int(len(secs) * 0.9))], 2),
    }


def table(title, groups):
    print(f"\n{title}")
    print(f"  {'':22} {'n':>4} {'CER':>7} {'CER(공백)':>10} {'WER':>7} "
          f"{'정확일치':>8} {'빈결과':>7} {'지연중앙':>8} {'p90':>7}")
    for label, m in groups:
        if not m:
            continue
        f = lambda k: "—" if m[k] is None else f"{m[k]}%"
        print(f"  {label:22} {m['n']:>4} {f('cer'):>7} {f('cer_공백'):>10} "
              f"{f('wer'):>7} {f('정확일치'):>8} {f('빈결과'):>7} "
              f"{m['지연중앙']:>7.2f}s {m['지연p90']:>6.2f}s")


def by(rows, field):
    out = defaultdict(list)
    for r in rows:
        out[r[field]].append(r)
    return sorted(out.items())


#: 본인 이름. **이 이름만 그대로 두고 나머지 화자는 「화자 A·B·C…」 로 바꾼다.**
#: `.env` 가 아니라 환경변수로 둔 이유 — 이건 설정이 아니라 **이 저장소의 공개 정책**이다.
SELF_SPEAKER = os.getenv("EVAL_SELF_SPEAKER", "변소윤")


def _anon_label(i: int) -> str:
    """0→'화자 A' … 25→'화자 Z' … 26→'화자 AA'. 26명을 넘겨도 안 겹친다."""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(ord("A") + r) + out
    return f"화자 {out}"


def anonymize_rows(rows, self_name: str = None):
    """결과 아티팩트에서 **남의 실명을 지운다.** 바꾼 rows 를 돌려준다(원본 유지).

    🚨 **왜 이게 코드에 있나** — 2026-09-18 에 «녹음 참여자 3명의 개인별 인식률이
      실명으로» 공개 저장소에 올라간 적이 있다. 그때는 **손으로 고쳤고**,
      2026-10-02 에 **같은 일이 새 파일로 또 일어났다**(이 스크립트의 `--json` 산출물에
      화자별 CER 이 실명으로 200줄). 손으로 고치는 것은 다음 번에 또 샌다.
      🔑 **이 저장소가 세 번 배운 것과 같은 모양이다 — 보장하는 건 구조다.**

    🔑 **대응표를 저장소에 두지 않는다.** 이름 목록을 코드에 적으면 그게 곧 대응표다.
      그래서 **이름을 적지 않고** 자료에 실제로 나온 화자를 가나다순으로 세어
      그 자리에서 A·B·C 를 붙인다.

    ⚠️ Zeroth 코퍼스의 **숫자 화자 id**(`'104'`)는 그대로 둔다 — 공개 코퍼스의
      식별자라 개인을 가리키지 않고, 바꾸면 원자료와 대조할 수 없다.
    """
    self_name = SELF_SPEAKER if self_name is None else self_name
    names = sorted({str(r.get("speaker")) for r in rows
                    if r.get("speaker") and str(r["speaker"]) != self_name
                    and not str(r["speaker"]).isdigit()})
    if not names:
        return list(rows)
    table = {n: _anon_label(i) for i, n in enumerate(names)}
    out = []
    for r in rows:
        r = dict(r)
        who = str(r.get("speaker") or "")
        if who in table:
            r["speaker"] = table[who]
            sid = str(r.get("id") or "")
            if sid.startswith(who):          # 'ㅇㅇㅇ#03' → '화자 A#03'
                r["id"] = table[who] + sid[len(who):]
        out.append(r)
    return out


def report(rows, engines):
    if not rows:
        print("\n측정할 표본이 없습니다.")
        return

    for src, srows in by(rows, "_source"):
        table(f"■ {src} — 엔진별",
              [(e, aggregate([r for r in srows if r["engine"] == e])) for e in engines])

        # 🆕 `label` 이 먼저다 — 녹음 페이지가 2026-09-24 부터 `command`(컴퓨터에게
        #   시키는 말)를 같이 받는다. 그게 들어오면 **«명령을 얼마나 알아듣나»가
        #   여기서 저절로 따로 찍힌다.** 지금은 라벨이 하나뿐이라 이 표가 안 나온다.
        for field, label in (("label", "구간 종류"), ("device", "기기"), ("speaker", "화자")):
            if len({r[field] for r in srows}) < 2:
                continue
            for e in engines:
                erows = [r for r in srows if r["engine"] == e]
                table(f"■ {src} — {label}별 ({e})",
                      [(str(k)[:22], aggregate(v)) for k, v in by(erows, field)])

    # 🚨 반복 발화를 반영하기 전/후 — **둘 다 보여야** 어느 쪽을 본 건지 안다
    # 🚨 **표본별로 나눠 찍는다.** 합쳐 찍었더니 «우리 녹음» 표의 값과 우연히 같은
    #   숫자가 나와, 같은 것을 두 번 말하는 것처럼 보였다(2026-09-24).
    #   반복 발화는 우리 녹음에만 있으므로 합계는 그냥 대조군에 희석된 값이다.
    for src, srows in by(rows, "_source"):
        rep_rows = [r for r in srows if r.get("takes", 1) > 1]
        if not rep_rows:
            continue
        print(f"\n■ 🚨 반복 발화 보정 ({src}) — 라벨 그대로 세면 무엇이 달라지나")
        print("  (오디오에 문장이 두 번 들어 있던 발화. 엔진이 두 번 적은 것은 «맞은» 것이다)")
        for e in engines:
            erows = [r for r in srows if r["engine"] == e]
            if not erows:
                continue
            a, b = aggregate(erows, "raw_score"), aggregate(erows, "score")
            print(f"  {e:8} 라벨 그대로 CER {a['cer']}% → 반복 반영 {b['cer']}% "
                  f"(보정된 발화 {len([r for r in rep_rows if r['engine'] == e])}/{len(erows)})")

    # 교정 사전이 실제로 무엇을 했나 — 런타임은 이걸 항상 통과시킨다
    print("\n■ 후처리 교정 사전(`_postprocess`)의 효과")
    for e in engines:
        erows = [r for r in rows if r["engine"] == e]
        if not erows:
            continue
        before, after = aggregate(erows, "nopost_score"), aggregate(erows, "score")
        changed = sum(1 for r in erows if r["raw"] != r["hyp"])
        print(f"  {e:8} CER {before['cer']}% → {after['cer']}% "
              f"· 문장이 바뀐 발화 {changed}/{len(erows)}")

    # 두 엔진을 같은 오디오로 비교 — 폴백이 «더 나쁘기만 한가»
    if len(engines) > 1:
        print("\n■ 같은 오디오에서 엔진끼리")
        pair = defaultdict(dict)
        for r in rows:
            pair[(r["_source"], r["id"])][r["engine"]] = r
        a, b = engines[0], engines[1]
        both = [p for p in pair.values() if a in p and b in p]
        wins = sum(1 for p in both if p[a]["score"]["cer_err"] < p[b]["score"]["cer_err"])
        ties = sum(1 for p in both if p[a]["score"]["cer_err"] == p[b]["score"]["cer_err"])
        print(f"  {a} 이 더 정확 {wins} · 같음 {ties} · "
              f"{b} 이 더 정확 {len(both) - wins - ties}  (n={len(both)})")

    print("\n🚨 이 숫자를 읽는 법")
    print("  · 우리 녹음은 **웨이크워드 오탐용으로 고른 문장**이다 — STT 에게 유난히 어렵다.")
    print("  · Zeroth 는 남이 만든 읽기 음성이라 **우리 설계와 무관**하다.")
    print("    둘이 갈리면 표본 탓, 같이 나쁘면 엔진 탓이다.")
    print("  · 둘 다 **«명령을 얼마나 알아듣나»는 아니다** — 마이크로 말한 명령 표본이 4문장뿐이다.")


def main():
    ap = argparse.ArgumentParser(description="음성 인식률을 잰다 (2-10)")
    ap.add_argument("--engines", default="google,whisper", help="쉼표로. google|whisper")
    ap.add_argument("--labels", default="negative",
                    help="우리 녹음에서 쓸 구간. negative|positive (쉼표로)")
    ap.add_argument("--zeroth", type=int, default=0,
                    help="Zeroth-Korean 대조군 발화 수 (0이면 안 잰다)")
    ap.add_argument("--limit", type=int, default=0, help="표본을 앞에서 N개만")
    ap.add_argument("--no-takes", action="store_true",
                    help="반복 발화 보정을 끈다 (라벨을 글자 그대로 믿는다)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", default="", help="결과를 JSON 으로 저장할 경로")
    args = ap.parse_args()

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    labels = {s.strip() for s in args.labels.split(",") if s.strip()}

    print("=" * 78)
    print("음성 인식률 측정 (2-10) — 엔진:", ", ".join(engines))
    print("=" * 78)

    ours = samples_ours(labels)
    zero = samples_zeroth(args.zeroth) if args.zeroth > 0 else []
    if args.limit:
        ours, zero = ours[:args.limit], zero[:args.limit]
    print(f"표본 — 우리 녹음 {len(ours)}발화 · Zeroth {len(zero)}발화")
    if not ours and not zero:
        print("표본이 없습니다. data/wakeword_raw/ 를 확인하세요.")
        return 1

    fns, postprocess = make_engines(engines)
    if not fns:
        print(f"알 수 없는 엔진: {args.engines}")
        return 2

    rows = []
    for src, batch in (("우리 녹음(실제 마이크)", ours), ("Zeroth-Korean(대조군)", zero)):
        if not batch:
            continue
        print(f"\n▶ {src} — {len(batch)}발화 × {len(fns)}엔진")
        for r in run(batch, fns, postprocess, args.verbose, not args.no_takes):
            r["_source"] = src
            rows.append(r)

    report(rows, list(fns))

    if args.json:
        with io.open(args.json, "w", encoding="utf-8") as f:
            json.dump({
                "engines": list(fns),
                "요약": {src: {e: aggregate([r for r in rows
                                            if r["_source"] == src and r["engine"] == e])
                              for e in fns}
                        for src, _ in by(rows, "_source")},
                # 🔒 남의 실명은 **파일로 나가지 않는다** (위 anonymize_rows 참조).
                #   화면 출력은 그대로 둔다 — 그건 로컬이고, 누가 누군지 봐야 한다.
                "발화": anonymize_rows(rows),
            }, f, ensure_ascii=False, indent=1)
        print(f"\n💾 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
