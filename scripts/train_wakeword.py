"""
웨이크워드 모델 학습
====================
실행:
    python scripts/train_wakeword.py                      # 실측 증강 (기본 · 말뭉치가 있어야 한다)
    python scripts/train_wakeword.py --augment mimic      # 옛 «흉내» 증강 (말뭉치 없이)
    python scripts/train_wakeword.py --user-audio a.npy   # 실제 녹음 추가 (선택)
    python scripts/train_wakeword.py --jobs 1             # 한 코어만 (기본은 전부)

## 🆕 2026-09-19 — 코어를 전부 쓴다 (M7 §6-1)

예전에는 **전부 `for` 루프**였다. 32코어 서버를 빌려도 31개가 논다.
이제 «클립 하나 → 증강 → 창 → 임베딩»을 **일감**으로 쪼개
[`wakeword_parallel.pmap`](wakeword_parallel.py) 이 코어에 나눠 준다.

🔑 **`--jobs` 가 결과를 안 바꾼다.** 난수를 워커끼리 나눠 쓰면 «어느 일감이 먼저
끝났나»가 데이터셋에 새고, 그러면 노트북에서 만든 후보와 서버에서 만든 후보가
**다른 물건인데 둘 다 «같은 설정»이라고 적힌다.** 그래서 씨앗을 일감마다 미리
박아 둔다(`plan_dataset`) — 왜 이게 이 저장소에서 특히 위험한지는
[`wakeword_parallel.py`](wakeword_parallel.py) 머리에 적어 뒀다.

## 🆕 2026-09-18 — 증강이 «흉내»에서 «실측»으로 바뀌었다 (M7 4단계)

예전 증강은 방을 **흉내** 냈다 — 백색잡음을 더하고 반사를 한 번 섞었다.
그래서 조용한 방에서 만든 자로 재면 검증 95%가 나오고 **실기는 10번 중 2번**이었다.
이제 기본값은 [`wakeword_corpus.Augmenter`](wakeword_corpus.py) 이고, 잡음·잔향이
실제 녹음이다(MUSAN · RIR and Noises). 여기에 **사람이 실제로 말한 한국어**를
음성(negative)으로 넣는다(Zeroth · AI Hub) — 🔴 기준선에서 밝혀진 오탐의 모양이
«발음에 속는 게 아니라 음성이면 깬다» 였고, 그 자리를 직접 치는 것이 이것이다.

🚨 **말뭉치가 없으면 죽는다. 조용히 흉내로 되돌아가지 않는다.**
«실측으로 학습했다»고 적어 놓고 실제로는 옛 흉내로 학습한 모델이 나오는 것이
[BL-59](../docs/BACKLOG.md)로 적어 둔 실패 모양의 가장 비싼 판본이다.
흉내로 돌리려면 `--augment mimic` 을 **명시한다**.
받기: `python scripts/fetch_wakeword_corpora.py --list`

## 구조
    오디오 → melspec → Google 음성 임베딩(96차원 × 16프레임) → 우리가 학습한 분류기

앞의 두 단계는 **openWakeWord가 제공하는 사전학습 ONNX 모델**을 그대로 쓴다.
우리가 만드는 건 마지막 분류기 하나뿐이라 학습이 가볍고 torch가 필요 없다.

## 왜 이렇게 하나 (openWakeWord 공식 파이프라인을 안 쓰는 이유)
공식 학습은 torch·speechbrain·datasets 등 무거운 의존성을 요구한다. 이 프로젝트는
V2에서 **torch를 의도적으로 제거**했다(→ docs/presentation/pluiz_evolution.md).
분류기는 작은 MLP라 scikit-learn으로 충분하고, 추론은 행렬곱 몇 번이라 직접 구현한다.
그래서 런타임에 추가되는 의존성이 없다.

## 산출물
**기본은 `services/wakeword_model_candidate.npz` 다 — 런타임 모델이 아니다.**
평가([`eval_wakeword.py`](eval_wakeword.py))를 통과한 뒤에 `--replace-runtime` 으로 바꾼다.
학습과 교체를 나눠 두지 않으면 **실수로 한 번 돌렸을 때 지금 도는 모델이 사라진다.**
(가중치 + 메타데이터. 작아서 저장소에 커밋한다.)
"""

import argparse
import asyncio
import os
import sys
import time
from collections import namedtuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.wakeword_data import (           # noqa: E402
    SR, POSITIVE_PHRASES, NEGATIVE_PHRASES, COVERED_WAKE_WORDS,
    synthesize_set, augment, to_window, _load,
)
from scripts.wakeword_parallel import (       # noqa: E402
    child_seeds, pmap, resolve_jobs,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "cache", "wakeword_tts")   # 합성음 (재사용)
MODEL_PATH = os.path.join(ROOT, "services", "wakeword_model.npz")
WIN_SEC = 2.0


def make_augmenter(kind, refresh=False):
    """증강기를 고른다. **어느 쪽으로 학습하는지 반드시 찍는다.**

    🚨 «없으면 조용히 흉내로» 를 만들지 않는다. 말뭉치가 모자라면
    `require()` 가 무엇이 없는지 말하고 예외를 던진다 — 그게 이 함수의 전부다.
    나중에 모델 파일만 보고도 알 수 있게 `save()` 가 이 선택을 npz 에 박는다.
    """
    if kind == "mimic":
        print("  ⚠️ 증강: «흉내» (백색잡음 + 반사 1회) — 명시적으로 고른 것이다")
        print("     실측으로 바꾸려면 옵션을 빼면 된다 (기본값이 --augment corpus)")
        return None
    from scripts.wakeword_corpus import Augmenter
    a = Augmenter(refresh=refresh).require()
    print(f"  증강: **실측** — {a.describe()}")
    if a.missing:
        # 있는 것만 세고 넘어가지 않는다. 없는 것도 이름을 부른다.
        print(f"     (없는 것: {', '.join(a.missing)} — 있으면 더 좋다)")
    return a


def extract_features(windows, af, batch_label=""):
    """창 리스트 → 임베딩 행렬 (N × 1536)."""
    feats = []
    for i, w in enumerate(windows):
        pcm = (np.clip(w, -1, 1) * 32767).astype(np.int16)
        emb = af._get_embeddings(pcm)          # (프레임, 96)
        feats.append(emb.flatten())
        if batch_label and (i + 1) % 500 == 0:
            print(f"  {batch_label}: {i+1}/{len(windows)}")
    return np.array(feats, dtype=np.float32)


def _aug(augmenter, a, rng, n):
    """클립 하나 → 변형 n개. **자리는 하나다** — 실측이든 흉내든 여기로만 지나간다.

    🔑 호출부를 네 군데에서 갈아끼우지 않고 여기 한 곳만 갈아끼운다.
       한 군데를 빠뜨리면 «절반만 실측»이 되는데 **오류가 안 난다.**
       (`tests/test_wakeword_corpus.py` 가 이 파일에서 옛 증강 함수를 직접 부르는
       자리가 **딱 여기 하나**인지 센다. 그래서 그 이름을 다른 데 적으면 안 된다 —
       주석에 적어도 걸린다)
    """
    return augmenter.many(a, rng, n) if augmenter else augment(a, rng, n)


# ── 일감 ───────────────────────────────────────────────────────────
#: 일감 하나 — «무엇으로 창을 몇 개 만들고 어느 쪽인가».
#:
#: 🔑 **씨앗이 일감 안에 들어 있다.** 워커는 이것만 보고 일하며 공유 난수를
#:    쓰지 않는다 — 그래서 몇 코어로 돌든 결과가 같다(→ `wakeword_parallel` 머리).
#: ⚠️ `namedtuple` 이라 피클된다(윈도우는 `spawn` 이다). 여기에 열린 파일이나
#:    `Augmenter` 같은 무거운 것을 넣지 말 것 — 일감마다 다시 보내게 된다.
Recipe = namedtuple("Recipe", "kind ref n label seed")

#: 순수 잡음/무음 창 — 없으면 **조용할 때** 오탐이 난다.
NOISE_WINDOWS = 400

#: 잡음 일감 하나가 만드는 창 수. 일감이 너무 잘면 왕복 비용만 는다.
_NOISE_PER_TASK = 50
#: 한국어 말소리 일감 하나가 만드는 창 수.
_SPEECH_PER_TASK = 25


def plan_dataset(pos_paths, neg_paths, loud_starts, aug_per_clip,
                 speech_negatives, seed=0, has_augmenter=True, quiet=False):
    """**무거운 일을 하기 전에 일감 목록을 전부 만든다.**

    예전에는 증강하면서 창을 리스트에 붙이고, 다 붙인 뒤 개수를 보고 «음성이 모자라면
    더 만든다»(`_balance_negatives`)를 했다. 그 모양이면 **다 해 봐야 얼마나 할지
    알 수 있어서** 코어에 나눠 줄 수가 없다.

    개수는 전부 **미리 셀 수 있다** — 클립 수 × 증강 수다. 그래서 계획을 먼저 세우고
    나눠 준다. 덤으로 «이번 학습이 창 몇 개짜리인가»를 **시작할 때** 말할 수 있게 됐다
    (예전에는 7분을 기다려야 나왔다).

    ══════════════════════════════════════════════════════════════
    🚨 2026-09-09 — `--user-audio`만으로는 **모델이 망가진다**. 반드시 읽을 것.

    실제 녹음 143초를 양성으로 넣고 학습했더니, 검증 성적은 멀쩡한데
    (감지 93.6% · 오탐 2.35%) **실기에서 아무 말에나 깨어났다.**
    에너지 관문을 통과한 창의 **86.7%**를 「플루이즈」라고 답했고 대부분 prob=1.000이었다.

    원인은 임계값도 균형도 아니라 **데이터셋 구성**이다:

        실제 마이크 · 양성 : 1,722개  ← 사용자 녹음
        실제 마이크 · 음성 :     0개  ← **여기가 비어 있다**
        TTS 합성음         : 양성 2,100 · 음성 3,822

    학습셋에서 «진짜 마이크 오디오»는 전부 양성이다. 그러면 모델이 단어를 배울
    이유가 없다 — **«합성음이냐 실제 마이크냐»만 구분해도 만점**이기 때문이다.
    지름길을 놔두고 어려운 길로 가지 않는다.

    ⚠️ **검증셋은 이걸 못 잡는다.** 검증셋의 음성 표본도 전부 TTS라 지름길이
      거기서도 통한다. **학습셋과 같은 편향을 공유하는 검증셋은 결함을 볼 수 없는
      눈이다.** 「93.6%」는 아무것도 보증하지 않고 있었다.
      → 실기 확인 없이 이 표를 근거로 «좋아졌다»고 말하지 말 것.

    **고치려면 같은 마이크로 「플루이즈가 아닌 말」을 녹음해 음성에 넣어야 한다.**
    아래 균형 조정은 필요하지만 **충분하지 않다** — 개수를 맞출 뿐 지름길은 그대로다.
    → docs/BACKLOG.md BL-23 · docs/design/M2_웨이크워드_전용모델.md §7
    ══════════════════════════════════════════════════════════════
    """
    neg_aug = max(2, aug_per_clip // 3)
    out = []

    # ── 양성 ──────────────────────────────────────────────────────
    for p in pos_paths:
        out.append(Recipe("clip", p, aug_per_clip, 1, 0))
    # 실제 녹음 (사용자 목소리) — 합성음 과적합을 막는 핵심
    for st in loud_starts:
        out.append(Recipe("user", int(st), aug_per_clip * 2, 1, 0))
    pos_n = sum(r.n for r in out)

    # ── 음성 ──────────────────────────────────────────────────────
    neg = [Recipe("clip", p, neg_aug, 0, 0) for p in neg_paths]
    for i in range(0, NOISE_WINDOWS, _NOISE_PER_TASK):
        neg.append(Recipe("noise", None, min(_NOISE_PER_TASK, NOISE_WINDOWS - i), 0, 0))

    # ── 🔴 사람이 실제로 말한 한국어 (M7 4단계의 핵심) ─────────────
    # 기준선에서 밝혀진 오탐의 모양은 «발음에 속는 게 아니라 **음성이면 깬다**» 였다
    # (자유 발화 214건 > 헷갈리는 말 157건). TTS 음성은 목소리가 14개고 녹음 환경이
    # 하나라 그 분포로는 이 자리를 못 메운다. → docs/research/2026-09_웨이크워드_기준선.md §3
    #
    # 🔑 뽑은 한국어도 **증강을 거친다.** 깨끗한 낭독 그대로 넣으면 모델이
    #    «말인가»가 아니라 «깨끗한 녹음인가»를 배울 수 있다 — 위 ══ 블록과 같은 모양이다.
    if has_augmenter and speech_negatives > 0:
        for i in range(0, speech_negatives, _SPEECH_PER_TASK):
            neg.append(Recipe("speech", None,
                              min(_SPEECH_PER_TASK, speech_negatives - i), 0, 0))
    elif speech_negatives > 0 and not quiet:
        # 흉내 모드에서 조용히 «0개 넣고 넣었다고» 하지 않는다
        print(f"  ⚠️ 한국어 말소리 음성(negative) {speech_negatives}개를 건너뛴다 "
              f"— 흉내 모드라 말뭉치를 안 읽는다")

    # ── 클래스 균형 맞추기 (2026-09-09) ───────────────────────────
    # 🚨 실제 녹음을 넣으면 양성이 급증한다. 2026-09-09 실측:
    #      양성 3,822 : 음성 2,200  →  감지율 95.0 → 97.1%지만
    #      **오탐율 1.82 → 7.05%** (4배). 실사용에서 오탐은 놓침보다 나쁘다 —
    #      놓치면 한 번 더 부르면 되지만, 오탐은 안 부른 창을 띄운다.
    # ⚠️ `MLPClassifier`에는 `class_weight`도 `fit(sample_weight=)`도 **없다.**
    #    가중치로 못 고치므로 **표본 수로** 맞춰야 한다.
    # 여기서는 **양성을 버리지 않고 음성을 늘린다.** 사용자 목소리는 이 학습의
    # 존재 이유이고, TTS 양성을 줄이면 미학습 화자 일반화(98.1%)를 잃는다.
    # 늘리는 쪽도 «순수 잡음»이 아니라 **말소리 음성 클립**이어야 한다 —
    # 경계는 «다른 말»과의 사이에 있지 무음과의 사이에 있지 않다.
    neg_n = sum(r.n for r in neg)
    need = pos_n - neg_n
    if need > 0 and neg_paths:
        if not quiet:
            print(f"  ⚖️  음성 {neg_n} → {pos_n} (양성과 맞춘다)")
        i = 0
        while need > 0:
            neg.append(Recipe("clip", neg_paths[i % len(neg_paths)],
                              min(2, need), 0, 0))
            need -= min(2, need)
            i += 1

    out.extend(neg)

    # 🔑 씨앗은 **마지막에 한꺼번에** 박는다. 일감 순서만으로 정해지므로
    #    코어 수·끝난 순서와 무관하다(→ `wakeword_parallel.child_seeds`).
    seeds = child_seeds(seed, len(out))
    return [r._replace(seed=s) for r, s in zip(out, seeds)]


# ── 워커 ───────────────────────────────────────────────────────────
#: 워커 프로세스가 **한 번만** 차리는 것들. 일감마다 다시 만들면 ONNX 로딩이
#: 일감 수만큼 붙는다. `pmap(initializer=…)` 이 프로세스당 한 번 부른다.
_W = {}


def init_worker(augmenter, user_audio_path=""):
    """워커 하나를 차린다 — ONNX 임베딩 모델 · 증강기 · 사용자 녹음.

    ⚠️ `ncpu=1` 을 **명시한다.** 워커를 16개 띄워 놓고 각자 스레드를 여러 개 쓰면
       서로 코어를 뺏는다(oversubscription) — 병렬화가 **느려지는** 고전적 모양이다.
    """
    from openwakeword.utils import AudioFeatures
    _W["af"] = AudioFeatures(ncpu=1)
    _W["augmenter"] = augmenter
    _W["ua"] = np.load(user_audio_path) if user_audio_path else None


def _windows(rec, rng):
    """일감 하나 → 창 리스트. **증강은 전부 `_aug()` 한 자리를 지난다.**"""
    aug = _W["augmenter"]
    if rec.kind == "clip":
        a = _load(rec.ref)
        return [to_window(v, rng, WIN_SEC) for v in _aug(aug, a, rng, rec.n)]
    if rec.kind == "user":
        # 발화 구간(에너지 높은 곳)만 골라 양성으로 쓴다 — 자리는 계획에서 정해졌다
        seg = _W["ua"][rec.ref:rec.ref + int(SR * WIN_SEC)]
        return [to_window(v, rng, WIN_SEC) for v in _aug(aug, seg, rng, rec.n)]
    if rec.kind == "noise":
        out = []
        for _ in range(rec.n):
            lvl = rng.uniform(0.0002, 0.02)
            out.append(rng.normal(0, lvl, int(SR * WIN_SEC)).astype(np.float32))
        return out
    if rec.kind == "speech":
        out = []
        for _ in range(rec.n):
            seg = aug.speech_negative(rng, WIN_SEC)
            out.append(to_window(aug.one(seg, rng), rng, WIN_SEC))
        return out
    # 🚨 모르는 종류를 조용히 «창 0개» 로 넘기지 않는다. 그러면 학습셋이
    #    말없이 작아지고 오류는 안 난다 — 이 저장소가 반복해서 겪은 모양이다.
    raise ValueError(f"[train] 모르는 일감 종류: {rec.kind!r}")


def cook(rec):
    """일감 하나 → (양성/음성, 임베딩 행렬). **증강부터 임베딩까지 워커 안에서 끝낸다.**

    🔑 창(2초 · 128KB)은 프로세스 경계를 **안 넘는다.** 넘기면 기본 설정에서
       6,300 × 128KB = 800MB 를 직렬화하는데, 그게 병렬로 번 시간을 도로 먹는다.
       넘어가는 것은 일감 한 줄이고 돌아오는 것은 임베딩(1536 float = 6KB)이다.
    """
    rng = np.random.default_rng(rec.seed)
    return rec.label, extract_features(_windows(rec, rng), _W["af"])


def loud_segments(user_audio_path):
    """실제 녹음에서 **발화 구간의 시작 위치**만 고른다 (창은 워커가 뜬다).

    계획을 세우려면 «몇 개인지»를 먼저 알아야 해서 여기만 부모가 한다.
    numpy 슬라이스 몇 번이라 싸다 — 143초에 수십 ms 다.
    """
    ua = np.load(user_audio_path)
    hop, win = int(SR * 0.25), int(SR * WIN_SEC)
    starts = [st for st in range(0, max(1, len(ua) - win), hop)
              if float(np.sqrt(np.mean(ua[st:st + win] ** 2))) > 0.006]
    return len(ua) / SR, starts


def build_dataset(user_audio_path=None, aug_per_clip=3, seed=0,
                  augmenter=None, speech_negatives=0, jobs=1):
    print("① 음성 합성 (이미 있으면 재사용)")
    # 목소리가 14개라 전 조합은 양성 1400 · 음성 12950이다. 표본을 뽑아 쓴다 —
    # `limit_combos`는 **무작위 균등 추출**이라 목소리가 골고루 섞인다(앞에서 자르지 않는다).
    pos_paths = asyncio.run(synthesize_set(
        POSITIVE_PHRASES, os.path.join(CACHE_DIR, "pos"), "pos", limit_combos=700))
    neg_paths = asyncio.run(synthesize_set(
        NEGATIVE_PHRASES, os.path.join(CACHE_DIR, "neg"), "neg", limit_combos=900))
    print(f"  양성 클립 {len(pos_paths)} · 음성 클립 {len(neg_paths)}")

    # ② 실제 녹음 (사용자 목소리) — 합성음 과적합을 막는 핵심.
    #    계획을 세우려면 **몇 개인지 먼저** 알아야 해서 여기만 부모가 훑는다.
    loud_starts = []
    if user_audio_path and os.path.exists(user_audio_path):
        secs, loud_starts = loud_segments(user_audio_path)
        print(f"② 실제 녹음 추가: {secs:.1f}초 · 발화 구간 {len(loud_starts)}개")
    else:
        print("② 실제 녹음 없음 — 목소리 14개로 학습한다 "
              "(2026-09-08 측정: 미학습 화자 98.1%. 녹음은 선택이다)")

    # ③ 일감을 **먼저 전부** 만든다 — 그래야 코어에 나눠 줄 수 있고,
    #    «이번 학습이 창 몇 개짜리인가»를 시작할 때 말할 수 있다.
    recipes = plan_dataset(pos_paths, neg_paths, loud_starts, aug_per_clip,
                           speech_negatives, seed=seed,
                           has_augmenter=augmenter is not None)
    n_pos = sum(r.n for r in recipes if r.label == 1)
    n_neg = sum(r.n for r in recipes if r.label == 0)
    jobs = resolve_jobs(jobs, cap=len(recipes))
    print(f"③ 증강 + 임베딩 — 창 {n_pos + n_neg}개 (양성 {n_pos} · 음성 {n_neg}) "
          f"· 일감 {len(recipes)}개 · **{jobs} 코어**")
    if jobs == 1:
        print("   (한 코어다. `--jobs 0` 이면 전부 쓴다 — 결과는 같다)")

    t0 = time.time()
    # ⚠️ 녹음 구간이 없으면 **경로를 안 넘긴다.** 넘기면 워커 16개가 전부
    #    `np.load` 를 하는데, 파일이 없으면 «일감이 아니라 워커가» 죽는다 —
    #    쓰지도 않을 파일 때문에.
    ua_path = user_audio_path if loud_starts else ""
    done = pmap(cook, recipes, jobs=jobs, initializer=init_worker,
                initargs=(augmenter, ua_path), label="일감")
    el = time.time() - t0
    print(f"  완료 {el:.0f}초 ({(n_pos + n_neg) / max(el, 1e-9):.0f} 창/초)")

    # 🔑 `pmap` 이 **일감 순서**로 돌려주므로 여기서 다시 정렬할 일이 없다 —
    #    X 의 줄 순서가 코어 수에 안 달리는 자리가 그것이다.
    Xp = [f for lab, f in done if lab == 1]
    Xn = [f for lab, f in done if lab == 0]
    X = np.vstack(Xp + Xn)
    y = np.hstack([np.ones(sum(len(f) for f in Xp)),
                   np.zeros(sum(len(f) for f in Xn))])
    return X, y


def train(X, y, seed=0):
    from sklearn.model_selection import train_test_split
    from sklearn.neural_network import MLPClassifier
    from sklearn.metrics import classification_report, confusion_matrix

    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y)

    print(f"④ 학습 (학습 {len(Xtr)} · 검증 {len(Xte)})")
    clf = MLPClassifier(
        hidden_layer_sizes=(96, 32),
        activation="relu",
        alpha=1e-3,                 # 과적합 억제
        max_iter=400,
        early_stopping=True,
        n_iter_no_change=15,
        random_state=seed,
        verbose=False,
    )
    clf.fit(Xtr, ytr)

    prob = clf.predict_proba(Xte)[:, 1]
    print("\n── 임계값별 성능 (검증셋) ──")
    print(f"  {'임계':6} {'감지율':>8} {'오탐율':>8}")
    for th in [0.5, 0.7, 0.8, 0.9, 0.95, 0.99]:
        pred = prob >= th
        tp = int(((pred == 1) & (yte == 1)).sum()); fn = int(((pred == 0) & (yte == 1)).sum())
        fp = int(((pred == 1) & (yte == 0)).sum()); tn = int(((pred == 0) & (yte == 0)).sum())
        rec = tp / max(1, tp + fn); far = fp / max(1, fp + tn)
        print(f"  {th:.2f}   {rec*100:7.1f}% {far*100:7.2f}%   (TP{tp} FN{fn} FP{fp} TN{tn})")

    print("\n" + classification_report(yte, prob >= 0.8, target_names=["음성", "양성"]))
    return clf


def save(clf, path, meta=None):
    """sklearn MLP의 가중치만 저장한다 — 추론은 numpy로 직접 한다.

    sklearn을 런타임 의존성으로 만들지 않기 위해서다. MLP 추론은
    `relu(x@W1+b1) @ W2+b2 …` 로 끝난다.

    🆕 **어떻게 학습됐는지도 같이 박는다**(`augment` · `corpora` · `trained_at`).
    6단계에서 후보 여럿을 나란히 재게 되는데, 그때 «이 npz 가 흉내로 학습된 것인가
    실측으로 학습된 것인가»를 **파일만 보고** 알 수 있어야 한다. 기억이나 DEVLOG 에
    기대면 어긋난다 — 이 저장소가 이미 겪은 실패 모양이다.
    ⚠️ 런타임(`services/wakeword.py`)은 이 키들을 안 읽는다. 읽을 필요도 없다.
    """
    m = meta or {}
    np.savez_compressed(
        path,
        **{f"W{i}": w.astype(np.float32) for i, w in enumerate(clf.coefs_)},
        **{f"b{i}": b.astype(np.float32) for i, b in enumerate(clf.intercepts_)},
        n_layers=np.array(len(clf.coefs_)),
        wake_word=np.array("플루이즈"),
        # 런타임이 «설정된 호출어를 이 모델이 감당하나»를 판단하는 근거.
        # 이게 없으면 호출어를 바꿨을 때 모델이 **조용히 옛 말에만** 반응한다.
        wake_phrases=np.array(COVERED_WAKE_WORDS),
        win_sec=np.array(WIN_SEC),
        sample_rate=np.array(SR),
        augment=np.array(m.get("augment", "")),
        corpora=np.array(m.get("corpora", "")),
        speech_neg=np.array(int(m.get("speech_neg", 0))),
        trained_at=np.array(time.strftime("%Y-%m-%dT%H:%M:%S")),
    )
    size = os.path.getsize(path) / 1024
    print(f"⑤ 저장: {path} ({size:.0f} KB)")


#: 학습 결과의 **기본 저장 위치**. 런타임 모델(`MODEL_PATH`)이 아니다.
#:
#: 🚨 **2026-09-18에 기본값을 바꿨다.** 예전에는 이 스크립트가 `services/wakeword_model.npz`
#:    를 **바로 덮어썼다.** 실수로 한 번 돌리면 지금 도는 모델이 사라진다 —
#:    9/22 시연을 앞두고는 그게 그날을 잃는 것과 같다.
#:    [M7 §6](../docs/design/M7_웨이크워드_재구축.md)도 «7단계: 통과하면 런타임 교체»로
#:    **학습과 교체를 나눠** 놨다. 코드가 그 순서를 따르게 했다.
#:    바꾸려면 `--replace-runtime` 을 **명시적으로** 준다.
CANDIDATE_PATH = os.path.join(ROOT, "services", "wakeword_model_candidate.npz")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-audio", default="", help="실제 녹음 .npy (16kHz float32)")
    ap.add_argument("--aug", type=int, default=3,
                    help="클립당 증강 개수 (목소리 14개로 늘면서 8 → 3. 창 수는 비슷하다)")
    ap.add_argument("--out", default=None,
                    help=f"저장 위치 (기본: {os.path.relpath(CANDIDATE_PATH, ROOT)})")
    ap.add_argument("--augment", choices=("corpus", "mimic"), default="corpus",
                    help="corpus=실측(MUSAN·RIR·Zeroth · 기본) · mimic=옛 흉내(말뭉치 없이)")
    ap.add_argument("--speech-neg", type=int, default=2000,
                    help="🔴 사람이 말한 한국어를 음성(negative)으로 몇 개 넣나 "
                         "(--augment corpus 일 때만). 0 이면 안 넣는다")
    ap.add_argument("--refresh-index", action="store_true",
                    help="말뭉치 파일 목록 캐시를 다시 만든다 (받는 중이었다면 필요하다)")
    ap.add_argument("--jobs", type=int, default=0,
                    help="몇 코어로 나눠 할까 (0=전부 · 1=한 코어). "
                         "🔑 결과는 이 값에 안 달렸다 — 씨앗이 일감마다 따로다")
    ap.add_argument("--replace-runtime", action="store_true",
                    help="⚠️ 런타임 모델을 바로 덮어쓴다. 평가를 통과한 뒤에만 쓸 것")
    args = ap.parse_args()

    out = args.out or (MODEL_PATH if args.replace_runtime else CANDIDATE_PATH)
    if out == MODEL_PATH:
        print("⚠️ 런타임 모델을 덮어쓴다: " + os.path.relpath(out, ROOT))
        print("   되돌리려면: git checkout services/wakeword_model.npz")
    else:
        print("후보로 저장한다: " + os.path.relpath(out, ROOT))
        print("   재려면: python scripts/eval_wakeword.py --model " +
              os.path.relpath(out, ROOT).replace("\\", "/"))

    augmenter = make_augmenter(args.augment, refresh=args.refresh_index)
    X, y = build_dataset(args.user_audio or None, aug_per_clip=args.aug,
                         augmenter=augmenter, speech_negatives=args.speech_neg,
                         jobs=args.jobs)
    clf = train(X, y)
    save(clf, out, meta={
        "augment": args.augment,
        "corpora": augmenter.describe() if augmenter else "",
        "speech_neg": args.speech_neg if augmenter else 0,
    })
