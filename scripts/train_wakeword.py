"""
웨이크워드 모델 학습
====================
실행:
    python scripts/train_wakeword.py                      # 합성음만
    python scripts/train_wakeword.py --user-audio a.npy   # 실제 녹음 추가 (권장)

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
`services/wakeword_model.npz` — 가중치 + 메타데이터. 작아서 저장소에 커밋한다.
"""

import argparse
import asyncio
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.wakeword_data import (           # noqa: E402
    SR, POSITIVE_PHRASES, NEGATIVE_PHRASES,
    synthesize_set, augment, to_window, _load,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "cache", "wakeword_tts")   # 합성음 (재사용)
MODEL_PATH = os.path.join(ROOT, "services", "wakeword_model.npz")
WIN_SEC = 2.0


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


def build_dataset(user_audio_path=None, aug_per_clip=8, seed=0):
    from openwakeword.utils import AudioFeatures

    rng = np.random.default_rng(seed)
    print("① 음성 합성 (이미 있으면 재사용)")
    pos_paths = asyncio.run(synthesize_set(
        POSITIVE_PHRASES, os.path.join(CACHE_DIR, "pos"), "pos"))
    neg_paths = asyncio.run(synthesize_set(
        NEGATIVE_PHRASES, os.path.join(CACHE_DIR, "neg"), "neg", limit_combos=600))
    print(f"  양성 클립 {len(pos_paths)} · 음성 클립 {len(neg_paths)}")

    print("② 증강 + 창 배치")
    pos_wins, neg_wins = [], []
    for p in pos_paths:
        a = _load(p)
        for v in augment(a, rng, n=aug_per_clip):
            pos_wins.append(to_window(v, rng, WIN_SEC))
    for p in neg_paths:
        a = _load(p)
        for v in augment(a, rng, n=max(2, aug_per_clip // 3)):
            neg_wins.append(to_window(v, rng, WIN_SEC))

    # 순수 잡음/무음도 음성 샘플이다 — 없으면 조용할 때 오탐이 난다
    for _ in range(400):
        lvl = rng.uniform(0.0002, 0.02)
        neg_wins.append((rng.normal(0, lvl, int(SR * WIN_SEC))).astype(np.float32))

    # 실제 녹음 (사용자 목소리) — 합성음 과적합을 막는 핵심
    if user_audio_path and os.path.exists(user_audio_path):
        ua = np.load(user_audio_path)
        print(f"③ 실제 녹음 추가: {len(ua)/SR:.1f}초")
        # 발화 구간(에너지 높은 곳)만 골라 양성으로 쓴다
        hop = int(SR * 0.25)
        win = int(SR * WIN_SEC)
        loud = []
        for st in range(0, max(1, len(ua) - win), hop):
            seg = ua[st:st + win]
            if float(np.sqrt(np.mean(seg ** 2))) > 0.006:
                loud.append(seg)
        print(f"  발화 구간 {len(loud)}개 → 증강")
        for seg in loud:
            for v in augment(seg, rng, n=aug_per_clip * 2):
                pos_wins.append(to_window(v, rng, WIN_SEC))
    else:
        print("③ 실제 녹음 없음 — ⚠️ 합성음에 과적합될 수 있다 (--user-audio 권장)")

    print(f"④ 임베딩 추출 (양성 {len(pos_wins)} · 음성 {len(neg_wins)})")
    af = AudioFeatures()
    t0 = time.time()
    Xp = extract_features(pos_wins, af, "양성")
    Xn = extract_features(neg_wins, af, "음성")
    print(f"  완료 {time.time()-t0:.0f}초")

    X = np.vstack([Xp, Xn])
    y = np.hstack([np.ones(len(Xp)), np.zeros(len(Xn))])
    return X, y


def train(X, y, seed=0):
    from sklearn.model_selection import train_test_split
    from sklearn.neural_network import MLPClassifier
    from sklearn.metrics import classification_report, confusion_matrix

    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y)

    print(f"⑤ 학습 (학습 {len(Xtr)} · 검증 {len(Xte)})")
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


def save(clf, path):
    """sklearn MLP의 가중치만 저장한다 — 추론은 numpy로 직접 한다.

    sklearn을 런타임 의존성으로 만들지 않기 위해서다. MLP 추론은
    `relu(x@W1+b1) @ W2+b2 …` 로 끝난다.
    """
    np.savez_compressed(
        path,
        **{f"W{i}": w.astype(np.float32) for i, w in enumerate(clf.coefs_)},
        **{f"b{i}": b.astype(np.float32) for i, b in enumerate(clf.intercepts_)},
        n_layers=np.array(len(clf.coefs_)),
        wake_word=np.array("플루이즈"),
        win_sec=np.array(WIN_SEC),
        sample_rate=np.array(SR),
    )
    size = os.path.getsize(path) / 1024
    print(f"⑥ 저장: {path} ({size:.0f} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-audio", default="", help="실제 녹음 .npy (16kHz float32)")
    ap.add_argument("--aug", type=int, default=8, help="클립당 증강 개수")
    args = ap.parse_args()

    X, y = build_dataset(args.user_audio or None, aug_per_clip=args.aug)
    clf = train(X, y)
    save(clf, MODEL_PATH)
