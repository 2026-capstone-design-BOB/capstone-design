# -*- coding: utf-8 -*-
"""로컬 문장 임베딩 (M5 §6-2) — 캐시의 의미 검색용.

    from core.embedder import get_embedder
    emb = get_embedder()
    if emb.available:
        v = emb.encode("메모장 열어줘")        # np.ndarray(384,), L2 정규화됨
        m = emb.encode_many(["a", "b"])       # np.ndarray(2, 384)

## 왜 이렇게 만들었나

**캐시와 분리한다.** `command_cache.py`는 이 모듈이 없어도, 모델 파일이 없어도,
로드에 실패해도 그대로 돈다. 캐시는 **핵심 경로**라 새 의존성 때문에 서버가
못 뜨는 일이 있으면 안 된다. 그래서 실패는 전부 `available = False`로 흡수하고
**예외를 밖으로 내보내지 않는다.** → docs/design/M5_임베딩_캐시.md §5

**새 pip 의존성이 없다.** `onnxruntime`·`tokenizers`는 `faster-whisper`가 이미
끌고 와 설치돼 있다(2026-09-10 확인: 1.26.0 · 0.23.1). `torch`를 얹지 않은 이유는
졸업작품 배포에 2GB를 더할 수 없기 때문이다 → ADR §4 대안 비교.

**지연 로딩이다.** 첫 `encode()` 때 모델을 연다. 서버 기동을 늦추지 않는다.

## 모델

`Xenova/paraphrase-multilingual-MiniLM-L12-v2` (XLM-R 계열, 384차원).
`python scripts/fetch_embed_model.py` 로 `models/embed/`에 받는다(git 추적 안 함).
⚠️ int8 양자화본이 한국어 유사도를 얼마나 깎는지는 **아직 모른다** —
fp32와 나란히 재는 것이 ADR §6-3이다.
"""
import os
import threading
from typing import Optional, Sequence

import numpy as np

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ⚠️ 환경변수로 덮어쓸 수 있다 (`PLUIZ_CACHE_FILE`·`PLUIZ_LOG_DIR`과 같은 패턴).
#   테스트가 임시 경로를 가리키거나, 모델을 다른 곳에 두고 쓸 때 필요하다.
MODEL_DIR = os.environ.get("PLUIZ_EMBED_DIR") or os.path.join(_BASE_DIR, "models", "embed")

# int8을 먼저 본다. 둘 다 있으면 int8이 이긴다 — 기본은 «가볍고 빠른 쪽»이고,
# fp32는 §6-3 대조 측정용이다. `PLUIZ_EMBED_MODEL=model.onnx` 로 바꿔 잰다.
_MODEL_CANDIDATES = ("model_quantized.onnx", "model.onnx")
_TOKENIZER_FILE = "tokenizer.json"

# 캐시 패턴은 짧은 명령문이다. 길게 잡을 이유가 없고, 짧을수록 빠르다.
MAX_TOKENS = 64


def _model_path() -> Optional[str]:
    override = os.environ.get("PLUIZ_EMBED_MODEL")
    names = (override,) if override else _MODEL_CANDIDATES
    for name in names:
        p = os.path.join(MODEL_DIR, name)
        if os.path.exists(p):
            return p
    return None


class Embedder:
    """ONNX 문장 임베더. **실패해도 예외를 던지지 않는다.**

    `available`이 False면 호출자는 기존 경로(difflib)로 돌아가면 된다.
    """

    def __init__(self, model_path: Optional[str] = None,
                 tokenizer_path: Optional[str] = None):
        self._model_path = model_path or _model_path()
        self._tokenizer_path = tokenizer_path or os.path.join(MODEL_DIR, _TOKENIZER_FILE)
        self._session = None
        self._tokenizer = None
        self._input_names: tuple = ()
        self._dim: Optional[int] = None
        self._load_failed = False
        self._lock = threading.Lock()          # 첫 호출이 겹쳐도 두 번 열지 않는다

    # ── 상태 ──────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """쓸 수 있는가. **여기서 실제로 로드한다**(지연 로딩)."""
        if self._session is not None:
            return True
        if self._load_failed:
            return False
        return self._ensure_loaded()

    @property
    def dim(self) -> Optional[int]:
        return self._dim

    def describe(self) -> dict:
        """무엇이 로드됐는지 — 로그·진단용."""
        return {
            "model": os.path.basename(self._model_path) if self._model_path else None,
            "dir": MODEL_DIR,
            "loaded": self._session is not None,
            "failed": self._load_failed,
            "dim": self._dim,
        }

    # ── 로딩 ──────────────────────────────────────────────────────

    def _ensure_loaded(self) -> bool:
        with self._lock:
            if self._session is not None:
                return True
            if self._load_failed:
                return False
            try:
                self._load()
                return True
            except Exception as e:
                # ⚠️ 삼키는 것이 의도다. 임베딩이 안 되는 것은 «캐시가 조금 덜 똑똑한 것»
                # 이지 «서버가 안 뜨는 것»이 아니다. 다만 **왜** 안 되는지는 남긴다 —
                # 조용히 폴백하면 «켰는데 안 켜졌다»를 아무도 모른다.
                self._load_failed = True
                print(f"[Embedder] 로드 실패 → 임베딩 없이 진행합니다: "
                      f"{type(e).__name__}: {e}")
                return False

    def _load(self):
        if not self._model_path:
            raise FileNotFoundError(
                f"모델이 없습니다: {MODEL_DIR} "
                f"(python scripts/fetch_embed_model.py 로 받으세요)")
        if not os.path.exists(self._tokenizer_path):
            raise FileNotFoundError(f"토크나이저가 없습니다: {self._tokenizer_path}")

        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(self._tokenizer_path)
        self._tokenizer.enable_truncation(max_length=MAX_TOKENS)
        # 🚨 **패딩을 켜지 않는다.** 켜고 배치로 넣으면 같은 문장인데도 벡터가 달라진다
        # (2026-09-10 실측: 배치 ↔ 단건 코사인 **0.993~0.997**, 최대차 1.6e-2).
        # `attention_mask`를 넘기고 평균 풀링에서도 빼는데 **그래도** 틀어진다.
        #
        # 보통은 무시할 오차지만 여기서는 아니다 — 한국어 짧은 명령의 판별 폭이
        # 0.02~0.03이라(ADR §6-3) 0.007이 **정답과 오답을 뒤집는다.**
        # 그래서 문장을 **하나씩** 넣는다. 캐시 패턴 44개 × 4ms = 0.2초, 기동 때 한 번뿐이다.

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1      # 짧은 문장 1개다. 스레드를 늘리면 되레 느리다
        opts.log_severity_level = 3        # 경고 소음 억제
        self._session = ort.InferenceSession(
            self._model_path, sess_options=opts, providers=["CPUExecutionProvider"])
        self._input_names = tuple(i.name for i in self._session.get_inputs())
        print(f"[Embedder] 로드: {os.path.basename(self._model_path)} "
              f"· 입력={list(self._input_names)}")

    # ── 인코딩 ────────────────────────────────────────────────────

    def encode(self, text: str) -> Optional[np.ndarray]:
        """문장 하나 → L2 정규화된 384차원 벡터. 못 하면 None."""
        out = self.encode_many([text])
        return None if out is None else out[0]

    def encode_many(self, texts: Sequence[str]) -> Optional[np.ndarray]:
        """문장 여러 개 → (n, 384). 못 하면 None.

        캐시 패턴 전체를 한 번에 넣어 행렬을 만들 때 쓴다.
        """
        if not texts:
            return None
        if not self.available:
            return None
        try:
            out = [self._encode_one(t or "") for t in texts]
            vecs = np.vstack(out)
            self._dim = int(vecs.shape[1])
            return vecs
        except Exception as e:
            print(f"[Embedder] 인코딩 실패(무시): {type(e).__name__}: {e}")
            return None

    def _encode_one(self, text: str) -> np.ndarray:
        """문장 **하나**를 패딩 없이 인코딩한다. 패딩을 쓰지 않는 이유는 `_load()` 주석 참조."""
        enc = self._tokenizer.encode(text)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.array([enc.attention_mask], dtype=np.int64)

        # ⚠️ 입력 이름은 **모델이 말하게 한다.** XLM-R 계열은 token_type_ids가
        # 없지만 내보내기에 따라 있는 것도 있다. 이름을 박아 두면 모델을
        # 바꾸는 순간 조용히 깨진다.
        feed = {}
        for name in self._input_names:
            if name == "input_ids":
                feed[name] = ids
            elif name == "attention_mask":
                feed[name] = mask
            elif name == "token_type_ids":
                feed[name] = np.zeros_like(ids)
            else:
                raise ValueError(f"모르는 입력: {name}")

        hidden = self._session.run(None, feed)[0]        # (1, seq, dim)
        return self._mean_pool(hidden, mask)

    @staticmethod
    def _mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """어텐션 마스크를 쓴 평균 풀링 → L2 정규화.

        ⚠️ 패딩을 빼지 않고 평균 내면 **짧은 문장일수록 패딩에 희석된다.**
        캐시 패턴은 길이가 제각각(2~13어절)이라 그대로 두면 길이가 유사도를
        지배한다. 마스크를 곱하는 이유가 그것이다.

        L2 정규화를 여기서 하므로 **코사인 유사도가 내적 한 번**이 된다
        (44×384 행렬곱 하나 — ADR §2-5의 «무시할 수준»이 이것이다).
        """
        m = mask.astype(np.float32)[..., None]               # (n, seq, 1)
        summed = (hidden.astype(np.float32) * m).sum(axis=1)  # (n, dim)
        counts = np.clip(m.sum(axis=1), 1e-9, None)           # 0으로 나누지 않는다
        vecs = summed / counts
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.clip(norms, 1e-12, None)


# ── 싱글턴 ────────────────────────────────────────────────────────
_embedder: Optional[Embedder] = None
_singleton_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        with _singleton_lock:
            if _embedder is None:
                _embedder = Embedder()
    return _embedder


def reset_embedder():
    """테스트용 — 싱글턴을 버린다(환경변수를 바꾼 뒤 다시 열 때)."""
    global _embedder
    _embedder = None


def cosine_matrix(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """L2 정규화된 벡터들 사이의 코사인 = 내적. (m,) ← (dim,) · (m, dim)"""
    return matrix @ query
