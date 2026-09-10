# -*- coding: utf-8 -*-
"""임베딩 매칭 실측 — 임계를 «정하는» 도구 (M5 §6-3).

    python scripts/eval_embed_threshold.py                    # 기본(int8) + 현행 difflib
    PLUIZ_EMBED_MODEL=model.onnx python scripts/eval_embed_threshold.py   # fp32로
    python scripts/eval_embed_threshold.py --compare          # int8 ↔ fp32 나란히

## 이 스크립트가 답하는 질문

*"임베딩으로 바꾸면 현행보다 나은가."* 말이 아니라 숫자로.

세 가지를 잰다:
  ① **top-1 정확도** — 정답 패턴이 1등인가
  ② **마진** = (긍정 최고점의 최소) − (부정 최고점의 최대)
     **이게 음수면 오매칭 없이 쓸 수 있는 임계가 존재하지 않는다.**
  ③ 임계를 오매칭 0으로 두었을 때 살아남는 긍정 수

## ⚠️ 평가셋을 만들 때의 함정 (이 저장소가 데인 자리)

웨이크워드에서 **검증셋이 학습셋과 같은 편향을 공유해** 93.6%가 아무것도
보증하지 못했다. 그래서 여기서도:

- **부정 문장은 실제 로그에서 가져온다** — 시드 근처에서 지어내면 같은 사고가 난다
- 긍정은 **시드에 없는 표현**만 쓴다. 시드를 그대로 넣으면 1.000이 나와 무의미하다
"""
import argparse
import io
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ── 평가셋 ────────────────────────────────────────────────────────
# 후보 패턴 = 캐시 시드의 대표형. (동적 학습분은 사용자마다 달라 넣지 않는다)
PATTERNS = [
    "메모장 열어줘", "메모장 꺼줘", "계산기 열어줘", "크롬 열어줘", "탐색기 열어줘",
    "바탕화면 보여줘", "창 최대화해줘", "창 최소화해줘", "설정 열어줘", "카카오톡 열어줘",
    "볼륨 올려줘", "볼륨 내려줘", "음소거해줘", "밝기 올려줘", "밝기 내려줘",
    "스크린샷 찍어줘", "지금 몇 시야", "배터리 얼마나 남았어", "지금 뭐 켜져 있어",
    "유튜브 열어줘", "네이버 열어줘", "최근에 열었던 파일 보여줘",
]

# (발화, 정답 패턴 index) — 전부 **시드에 없는** 표현이다.
# 이 중 12개는 2026-09-10 실측에서 현행 매칭이 놓친 것들이다(ADR §2-2).
POSITIVES = [
    ("노트패드 띄워봐", 0), ("메모장 좀 실행시켜줄래", 0), ("계산기 좀 켜봐", 2),
    ("소리 좀 키워봐", 10), ("볼륨 최대로 올려줘", 10), ("소리가 너무 커 좀 줄여", 11),
    ("컴퓨터 소리 안 나게 해줘", 12), ("화면 좀 밝게 해줄래", 13),
    ("모니터 너무 눈부셔 어둡게", 14), ("화면 사진 좀 찍어줘", 15),
    ("지금 몇 시인지 알려줘", 16), ("배터리 몇 퍼센트야", 17), ("충전 얼마나 남았어", 17),
    ("지금 실행 중인 프로그램 뭐 있어", 18), ("창 좀 꽉 채워줘", 6),
    ("바탕화면 좀 보자", 5), ("유튜브 좀 틀어줘", 19),
]

# 캐시가 **잡으면 안 되는** 것. ★ = logs/pluiz.log 에서 그대로 가져온 실제 발화.
NEGATIVES = [
    "뻥카 치냐",                                    # ★ 2026-09-09 18:23 (불평)
    "아니 그 컴퓨터 설정 그거부터 열어야 되는 거 아니니",      # ★ 2026-09-09 18:23
    "안 열려 있는데 설정창",                          # ★ 2026-09-09 18:36
    "블루투스 어디서 켜는지 알려줘",                     # ★ 길안내(포인팅) — 캐시가 아니다
    "내 컴퓨터 업데이트 어떻게 해야 되는지 알려줘",           # ★ 2026-09-09 18:37
    "다시 한 번만 더 해 줄래",                        # ★ 문맥 참조 — 캐시가 못 푼다
    "그래",                                        # ★ 승인 응답 (BL-27)
    "반가워",                                      # ★ 잡담
    "오늘 기분이 어때",
    "메모장에 회의록이라고 써줘",                        # 파라미터가 필요 — 캐시가 못 담는다
    "메모장에서 파일 메뉴 눌러줘",                       # 클릭 — 승인이 필요하다
    "계산기로 3 더하기 5 계산해줘",
    "볼륨 조절하는 법 알려줘",                          # «방법»을 묻는 것이지 명령이 아니다
    "밝기 조절 어디서 해",
    "지금 뭐 하는 중이야",
    "이 파일 어디에 저장했는지 알려줘",
]


def _norm(x):
    return x / np.clip(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12, None)


def measure(score_fn, label: str, verbose: bool = True) -> dict:
    """score_fn(text) -> np.ndarray(len(PATTERNS),) 를 받아 성적을 낸다."""
    top1 = 0
    pos_top, neg_top, wrong = [], [], []
    for text, gold in POSITIVES:
        s = score_fn(text)
        i = int(np.argmax(s))
        if i == gold:
            top1 += 1
        else:
            wrong.append((text, PATTERNS[i], float(s[i]), PATTERNS[gold], float(s[gold])))
        pos_top.append(float(s[i]))
    for text in NEGATIVES:
        neg_top.append(float(np.max(score_fn(text))))

    pos = np.array(pos_top); neg = np.array(neg_top)
    margin = float(pos.min() - neg.max())
    tau = float(neg.max()) + 1e-6
    survive = int((pos >= tau).sum())

    if verbose:
        print("=" * 86)
        print(f"■ {label}")
        print("=" * 86)
        for t, got, gs, gold, gold_s in wrong:
            print(f"    top1오답  {t!r:26} → {got!r} {gs:.3f}  (정답 {gold!r} {gold_s:.3f})")
        print(f"  top-1 정확도   {top1}/{len(POSITIVES)}")
        print(f"  긍정 최고점    중앙값 {np.median(pos):.3f}  최소 {pos.min():.3f}")
        print(f"  부정 최고점    중앙값 {np.median(neg):.3f}  최대 {neg.max():.3f}")
        flag = "🔑" if margin > 0 else "🚨"
        print(f"  {flag} 마진(긍정최소 − 부정최대) = {margin:+.3f}"
              + ("" if margin > 0 else "   ← 음수면 «오매칭 0인 임계»가 없다"))
        print(f"  오매칭 0으로 두면(τ={tau:.3f}) 긍정 {survive}/{len(POSITIVES)} 통과")
        print()
    return {"label": label, "top1": top1, "margin": margin, "survive": survive,
            "pos_min": float(pos.min()), "neg_max": float(neg.max())}


def difflib_scorer():
    from difflib import SequenceMatcher

    def score(text):
        return np.array([SequenceMatcher(None, text, p).ratio() for p in PATTERNS])
    return score


def embed_scorer(centered: bool, q_prefix: str = "", p_prefix: str = ""):
    """`q_prefix`/`p_prefix` — e5 계열은 `query: `/`passage: ` 접두사가 **필수**다.

    ⚠️ 접두사는 «옵션»이 아니다. e5는 그걸 붙여 학습됐고, 빼면 다른 모델이 된다.
    그래서 **붙였을 때와 뺐을 때를 나란히 잰다** — 접두사 효과 자체가 측정 대상이다.
    """
    from core.embedder import get_embedder, reset_embedder
    reset_embedder()
    e = get_embedder()
    if not e.available:
        return None, None
    M = e.encode_many([p_prefix + p for p in PATTERNS])
    mu = M.mean(axis=0)
    Mc = _norm(M - mu)

    def score(text):
        v = e.encode(q_prefix + text)
        if centered:
            return Mc @ _norm(v - mu)
        return M @ v
    return score, e.describe()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", action="store_true",
                    help="int8 ↔ fp32 를 나란히 잰다(둘 다 받아 뒀을 때)")
    ap.add_argument("--e5", action="store_true",
                    help="multilingual-e5-small 을 잰다 (models/embed/e5-small)")
    args = ap.parse_args()

    rows = [measure(difflib_scorer(), "현행 — difflib (임계 0.80)")]

    if args.e5:
        # e5는 별도 폴더에 둔다 — 토크나이저가 달라 섞이면 안 된다
        os.environ["PLUIZ_EMBED_DIR"] = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "models", "embed", "e5-small")
        os.environ["PLUIZ_EMBED_MODEL"] = "model.onnx"
        import core.embedder as _em
        import importlib
        importlib.reload(_em)
        for label, qp, pp in (("접두사 없음", "", ""),
                              ("접두사 있음(query/passage)", "query: ", "passage: ")):
            for centered in (False, True):
                score, _ = embed_scorer(centered, qp, pp)
                if score is None:
                    print("(건너뜀 — e5-small 을 못 엽니다)")
                    break
                tag = "중심화" if centered else "원본"
                rows.append(measure(score, f"e5-small · {label} · {tag}"))
        _summary(rows)
        return

    models = ["model_quantized.onnx", "model.onnx"] if args.compare \
        else [os.environ.get("PLUIZ_EMBED_MODEL") or "model_quantized.onnx"]

    for m in models:
        os.environ["PLUIZ_EMBED_MODEL"] = m
        for centered in (False, True):
            score, desc = embed_scorer(centered)
            if score is None:
                print(f"(건너뜀 — {m} 를 못 엽니다. scripts/fetch_embed_model.py)")
                break
            tag = "중심화" if centered else "원본"
            rows.append(measure(score, f"임베딩 {m} · {tag}"))

    _summary(rows)


def _summary(rows):
    print("=" * 86)
    print("■ 요약 — **마진이 양수인 줄이 하나도 없으면 임베딩으로 바꾸면 안 된다**")
    print("=" * 86)
    print(f"  {'':<42} {'top-1':>7} {'마진':>8} {'오매칭0일때 통과':>16}")
    for r in rows:
        print(f"  {r['label']:<42} {r['top1']:>3}/{len(POSITIVES):<3} "
              f"{r['margin']:>+8.3f} {r['survive']:>10}/{len(POSITIVES)}")


if __name__ == "__main__":
    main()
