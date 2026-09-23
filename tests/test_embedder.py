# -*- coding: utf-8 -*-
"""임베딩 로더 계약 검증 (M5 §6-2).

실행: python tests/test_embedder.py

**모델 파일 없이도 전부 돈다.** 그게 이 테스트의 요점이다 — `core/embedder.py`의
계약은 *"모델이 없어도 서버가 뜬다"* 이고, 그 계약은 모델이 **없을 때만** 검증된다.
모델이 있으면 실제 추론 몇 개를 덤으로 더 본다(없으면 건너뛴다).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401  (로그·캐시 오염 방지 — BL-11)

import numpy as np


def run():
    passed = total = skipped = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    # ⚠️ 모듈을 부르기 **전에** 환경변수를 맞춘다. MODEL_DIR은 import 시점에 정해진다.
    empty = tempfile.mkdtemp(prefix="pluiz_embed_none_")
    os.environ["PLUIZ_EMBED_DIR"] = empty
    os.environ.pop("PLUIZ_EMBED_MODEL", None)

    import core.embedder as em
    import importlib
    importlib.reload(em)

    print("=== 1. 모델이 없을 때 — 서버가 죽으면 안 된다 ===")
    e = em.Embedder()
    check("available은 False", e.available is False)
    check("예외를 던지지 않는다", True)          # 위 줄이 안 터진 것이 곧 통과다
    check("encode는 None", e.encode("메모장 열어줘") is None)
    check("encode_many도 None", e.encode_many(["a", "b"]) is None)
    d = e.describe()
    check("describe가 실패를 보고한다", d["failed"] is True and d["loaded"] is False)
    check("두 번째 호출도 조용하다(재시도 안 함)", e.available is False)

    print("=== 2. 빈 입력·경계 ===")
    check("빈 리스트는 None", e.encode_many([]) is None)

    print("=== 3. 평균 풀링 — 패딩을 빼는가 (짧은 문장이 희석되면 안 된다) ===")
    # 2번째 토큰이 패딩(mask=0)이고 값이 100이다. 빼지 않으면 평균이 오염된다.
    hidden = np.array([[[1.0, 0.0], [100.0, 100.0]]], dtype=np.float32)
    mask = np.array([[1, 0]], dtype=np.int64)
    v = em.Embedder._mean_pool(hidden, mask)
    check("패딩 위치를 무시한다", np.allclose(v[0], [1.0, 0.0], atol=1e-6))
    check("L2 정규화돼 있다", abs(float(np.linalg.norm(v[0])) - 1.0) < 1e-6)

    hidden2 = np.array([[[3.0, 4.0], [3.0, 4.0]]], dtype=np.float32)
    mask2 = np.array([[1, 1]], dtype=np.int64)
    v2 = em.Embedder._mean_pool(hidden2, mask2)
    check("노름이 1이 되도록 나눈다", abs(float(np.linalg.norm(v2[0])) - 1.0) < 1e-6)

    zero = em.Embedder._mean_pool(np.zeros((1, 2, 2), dtype=np.float32),
                                  np.zeros((1, 2), dtype=np.int64))
    check("전부 패딩이어도 0으로 나누지 않는다", np.all(np.isfinite(zero)))

    print("=== 4. 코사인 = 내적 (정규화해 뒀으므로) ===")
    M = np.array([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]], dtype=np.float32)
    q = np.array([1.0, 0.0], dtype=np.float32)
    s = em.cosine_matrix(q, M)
    check("행렬곱 한 번으로 전부 나온다", np.allclose(s, [1.0, 0.0, 0.6], atol=1e-6))

    print("=== 5. 싱글턴 ===")
    em.reset_embedder()
    a = em.get_embedder()
    check("같은 객체를 돌려준다", a is em.get_embedder())
    em.reset_embedder()
    check("reset하면 새 객체", a is not em.get_embedder())

    print("=== 6. 실제 모델 (있을 때만) ===")
    os.environ.pop("PLUIZ_EMBED_DIR", None)
    importlib.reload(em)
    real = em.Embedder()
    if not real.available:
        print("  … 모델이 없어 건너뜁니다 (scripts/fetch_embed_model.py)")
        skipped += 1
    else:
        v = real.encode("메모장 열어줘")
        check("384차원", v is not None and v.shape == (384,))
        check("정규화됨", abs(float(np.linalg.norm(v)) - 1.0) < 1e-4)
        check("자기 자신과의 코사인은 1", abs(float(v @ v) - 1.0) < 1e-4)
        M2 = real.encode_many(["메모장 열어줘", "볼륨 올려줘"])
        check("배치 shape", M2 is not None and M2.shape == (2, 384))
        check("배치와 단건이 같다", np.allclose(M2[0], v, atol=1e-4))
        # ⚠️ 품질은 **여기서 재지 않는다.** 계약(모양·정규화)만 본다.
        #   품질 판정은 scripts/eval_embed_threshold.py 의 일이고,
        #   2026-09-10 실측에서 이 모델은 **기준 미달**이었다 → ADR §6-3
        check("서로 다른 문장은 1이 아니다", float(M2[0] @ M2[1]) < 0.9999)

    print(f"\n결과: {passed}/{total} 통과" + (f" (건너뜀 {skipped})" if skipped else ""))
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
