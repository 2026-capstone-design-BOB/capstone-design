"""홀드아웃을 **이름으로** 고정한다 — 회귀 자물쇠 (2026-10-03).

🚨 **왜 있나** — 홀드아웃을 제비뽑기로 고르면 **사람이 늘 때 다른 사람이 뽑힌다.**
   2026-10-03 에 실제로 났다: 9/28 에 `--seed 2` 로 뽑은 네 명
   (녹음자1·녹음자3·녹음자5·녹음자9)이, 녹음이 둘 늘자 **녹음자3 대신 녹음자4**이 됐다.

   🔑 녹음자4은 **그때 모델이 학습한 사람**이다. 홀드아웃에 넣으면 «전» 모델이
   자기가 배운 사람으로 채점받아 부당하게 좋아 보이고, 그러면 후보가 나빠 보인다 —
   **좋아진 모델을 버릴 수 있다.** 그리고 **오류가 안 난다.** 숫자만 틀린다.

🔒 그래서 이 테스트는 둘을 **같이** 고정한다.
   ① 이름으로 주면 **사람이 늘어도 안 바뀐다**
   ② 제비뽑기는 **바뀐다** — 이게 ① 이 존재하는 이유다

    conda activate pluiz
    python tests/test_ingest_holdout.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed = total = 0


def check(label, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ FAIL {label}" + (f"   → {detail}" if detail else ""))


def _src(rel):
    # ⚠️ 절대규칙 7 — 한글이 든 소스는 utf-8 로 연다.
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


import scripts.ingest_wakeword as ing                              # noqa: E402

SR = ing.SR


# ═══ ① 인자가 있고, 왜 있는지가 소스에 적혀 있다 ═══════════════════
print("=== ① 인자 ===")
_s = _src("scripts/ingest_wakeword.py")
check("`--holdout-names` 인자가 있다", '"--holdout-names"' in _s)
check("🚨 **왜** 제비뽑기로는 안 되는지가 주석에 있다",
      "녹음자3 대신 녹음자4" in _s)
check("제비뽑기를 쓸 때는 **바뀔 수 있다고 경고**한다",
      "녹음이 늘면 다른 사람이 뽑힙니다" in _s)


# ═══ ② 이름 읽기 — 쉼표도 공백도 같게 ═════════════════════════════
print("\n=== ② 이름 읽기 ===")
check("공백으로 준 것을 읽는다",
      ing._split_names(["녹음자1", "녹음자3"]) == ["녹음자1", "녹음자3"])
check("쉼표로 준 것도 **같게** 읽는다",
      ing._split_names(["녹음자1,녹음자3"]) == ["녹음자1", "녹음자3"])
check("섞여 있어도 읽는다",
      ing._split_names(["녹음자1, 녹음자3", "녹음자5"]) == ["녹음자1", "녹음자3", "녹음자5"])
check("빈 것은 버린다", ing._split_names(["녹음자1,,", " "]) == ["녹음자1"])

check("🔑 괄호 이름은 **같은 사람**으로 모인다 (김예은 ← 김예은(다시))",
      ing._speaker_key("김예은(다시)") == "김예은")


# ═══ ③ 가짜 녹음으로 실제로 돌려 본다 ═════════════════════════════
#
# 🔑 **진짜 데이터에 기대지 않는다** — `data/` 는 git 밖이라 CI 에 없다.
#   여기서 만들고 여기서 지운다.
print("\n=== ③ 실제로 돌려 본다 (가짜 녹음) ===")


def _make(dirpath, speaker, n_seg=4, stamp="20260101000000"):
    """wav + json 한 쌍을 만든다. 구간 수 0 이면 «구간이 없는 화자»가 된다."""
    wp = os.path.join(dirpath, f"pluiz_{speaker}_{stamp}.wav")
    w = wave.open(wp, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    # 🔑 무음이면 «너무 조용한 구간»으로 버려진다 — 들리는 크기로 채운다.
    w.writeframes(bytes(bytearray([0x00, 0x20] * (SR * 8))))
    w.close()
    segs = []
    for i in range(n_seg):
        segs.append({"start": i * 1.5, "end": i * 1.5 + 1.2,
                     "label": "positive" if i % 2 == 0 else "negative",
                     "text": "플루이즈", "style": "또렷하게"})
    meta = {"speaker": speaker, "place": "조용한 방", "device": "노트북 · PC 마이크",
            "distance": "가까이 (30cm 정도)", "consent": True,
            "recordedAt": "2026-01-01T00:00:00.000Z", "sampleRate": SR,
            "durationSec": 8.0, "segments": segs}
    with io.open(wp[:-4] + ".json", "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False))


def _run(raw, out, argv):
    """ingest 를 임시 폴더에 대고 돌린다. (종료코드, 홀드아웃 목록) 을 준다."""
    old_raw, old_out, old_argv = ing.RAW, ing.OUT, sys.argv
    ing.RAW, ing.OUT = raw, out
    sys.argv = ["ingest_wakeword.py"] + argv
    try:
        rc = ing.main()
    finally:
        ing.RAW, ing.OUT, sys.argv = old_raw, old_out, old_argv
    mf = os.path.join(out, "manifest.json")
    held = []
    if rc == 0 and os.path.exists(mf):
        held = json.load(io.open(mf, encoding="utf-8")).get("holdout", [])
    return rc, sorted(held)


tmp = tempfile.mkdtemp(prefix="pluiz_ingest_")
try:
    raw = os.path.join(tmp, "raw")
    out = os.path.join(tmp, "out")
    os.makedirs(raw)
    os.makedirs(out)

    SIX = ["가영", "나영", "다영", "라영", "마영", "바영"]
    for nm in SIX:
        _make(raw, nm)

    NAMES = ["가영", "다영"]
    rc, held = _run(raw, out, ["--holdout-names"] + NAMES)
    check("이름으로 주면 **그 사람들이** 홀드아웃이 된다",
          rc == 0 and held == sorted(NAMES), f"rc={rc} → {held}")

    rc, seed_before = _run(raw, out, ["--holdout", "2", "--seed", "2"])
    check("제비뽑기 경로도 그대로 돈다", rc == 0 and len(seed_before) == 2,
          f"rc={rc} → {seed_before}")

    # ── 🚨 핵심: 사람이 늘었을 때 ──────────────────────────────
    _make(raw, "사영")
    _make(raw, "아영")

    rc, held_after = _run(raw, out, ["--holdout-names"] + NAMES)
    check("🔒 **사람이 늘어도 이름으로 준 홀드아웃은 안 바뀐다**",
          rc == 0 and held_after == sorted(NAMES), f"rc={rc} → {held_after}")

    rc, seed_after = _run(raw, out, ["--holdout", "2", "--seed", "2"])
    check("🚨 **제비뽑기는 바뀐다** — 같은 seed 인데 다른 사람이 뽑힌다 "
          "(이 기능이 존재하는 이유다)",
          rc == 0 and seed_after != seed_before,
          f"{seed_before} → {seed_after}  ← 같으면 이 표본으로는 못 보인 것이다")

    # ── 조용히 넘어가지 않는다 ────────────────────────────────
    rc, _ = _run(raw, out, ["--holdout-names", "가영", "없는사람"])
    check("🚨 없는 이름을 주면 **1 로 죽는다** (조용히 빼고 돌지 않는다)", rc == 1,
          f"rc={rc}")

    _make(raw, "빈영", n_seg=0)
    rc, _ = _run(raw, out, ["--holdout-names", "가영", "빈영"])
    check("🚨 **구간이 0인 사람**을 지정해도 거부한다 (분모가 조용히 준다)", rc == 1,
          f"rc={rc}")

    # ── 괄호 이름은 한 사람으로 묶여 **둘 다** 빠진다 ──────────
    _make(raw, "자영", stamp="20260102000000")
    _make(raw, "자영(다시)", stamp="20260103000000")
    rc, held = _run(raw, out, ["--holdout-names", "자영"])
    check("🔑 괄호 이름이 묶여 **세션 둘 다** 홀드아웃으로 빠진다",
          rc == 0 and {"자영", "자영(다시)"} <= set(held), f"rc={rc} → {held}")

    rc, held = _run(raw, out, ["--holdout-names", "자영(다시)"])
    check("괄호를 붙여 적어도 같은 사람으로 읽는다",
          rc == 0 and {"자영", "자영(다시)"} <= set(held), f"rc={rc} → {held}")

    rc, held = _run(raw, out, ["--holdout-names", "가영,다영"])
    check("쉼표로 적어도 똑같이 동작한다", rc == 0 and held == sorted(NAMES),
          f"rc={rc} → {held}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
