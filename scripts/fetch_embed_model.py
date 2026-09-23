# -*- coding: utf-8 -*-
"""임베딩 모델 내려받기 (M5 §6-2).

    python scripts/fetch_embed_model.py            # int8 양자화본(118MB) — 기본
    python scripts/fetch_embed_model.py --fp32     # fp32(470MB) — §6-3 대조용
    python scripts/fetch_embed_model.py --check    # 받지 않고 상태만 본다

**모델 파일은 git에 올리지 않는다**(`.gitignore`). 저장소가 118MB만큼 무거워지고,
받는 건 한 번이면 되기 때문이다. 시연 전에 미리 받아 두면 오프라인에서도 돈다.

⚠️ 모델이 없어도 **서버는 그대로 뜬다** — `core/embedder.py`가 None을 돌려주고
캐시는 기존 difflib 경로로 돌아간다. 캐시는 핵심 경로라 새 의존성 때문에
기동이 막히면 안 된다. → docs/design/M5_임베딩_캐시.md §5
"""
import argparse
import os
import sys

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_DIR = os.path.join(_BASE_DIR, "models", "embed")

REPO = "Xenova/paraphrase-multilingual-MiniLM-L12-v2"
FILE_INT8 = "onnx/model_quantized.onnx"      # 118MB
FILE_FP32 = "onnx/model.onnx"                # 470MB
TOKENIZER = "tokenizer.json"                 # 17MB


def _human(n: int) -> str:
    return f"{n / 1e6:.0f} MB"


def status() -> dict:
    """받아 둔 것이 무엇인지. (없어도 오류가 아니다)"""
    out = {}
    for label, name in (("int8", "model_quantized.onnx"),
                        ("fp32", "model.onnx"),
                        ("tokenizer", TOKENIZER)):
        p = os.path.join(DEST_DIR, name)
        out[label] = _human(os.path.getsize(p)) if os.path.exists(p) else None
    return out


def fetch(fp32: bool = False) -> int:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("✗ huggingface_hub 가 없습니다. `pip install huggingface_hub`", file=sys.stderr)
        return 1

    os.makedirs(DEST_DIR, exist_ok=True)
    targets = [TOKENIZER, FILE_FP32 if fp32 else FILE_INT8]
    for remote in targets:
        local_name = os.path.basename(remote)
        dest = os.path.join(DEST_DIR, local_name)
        if os.path.exists(dest):
            print(f"  이미 있음  {local_name}  {_human(os.path.getsize(dest))}")
            continue
        print(f"  받는 중    {REPO}/{remote} …")
        try:
            src = hf_hub_download(repo_id=REPO, filename=remote)
        except Exception as e:
            print(f"✗ 실패: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        # hf 캐시는 심볼릭 링크라 Windows에서 다루기 번거롭다 → 실파일로 복사한다
        import shutil
        shutil.copyfile(src, dest)
        print(f"  ✓ {local_name}  {_human(os.path.getsize(dest))}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp32", action="store_true", help="fp32 원본(470MB)도 받는다")
    ap.add_argument("--check", action="store_true", help="받지 않고 상태만 본다")
    args = ap.parse_args()

    print(f"대상 폴더: {DEST_DIR}")
    if args.check:
        for k, v in status().items():
            print(f"  {k:<10} {v or '없음'}")
        sys.exit(0)
    rc = fetch(fp32=args.fp32)
    if rc == 0:
        print("\n완료. 상태:")
        for k, v in status().items():
            print(f"  {k:<10} {v or '없음'}")
    sys.exit(rc)
