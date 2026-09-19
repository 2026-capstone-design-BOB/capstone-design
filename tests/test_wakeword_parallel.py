# -*- coding: utf-8 -*-
"""병렬 학습의 계약 — **`--jobs` 가 결과를 안 바꾼다** (M7 §6-1)

실행: python tests/test_wakeword_parallel.py

## 왜 이 테스트가 있나

`scripts/train_wakeword.py` 는 2026-09-19에 «코어 하나»에서 «코어 전부»로 바뀌었다.
병렬화에서 조용히 틀리는 방식은 **속도가 아니라 재현성**이다.

난수 하나를 여러 워커가 나눠 쓰면 **어느 일감이 먼저 끝났느냐가 데이터셋에 샌다.**
그러면 노트북(16코어)에서 만든 후보와 학교 서버(32코어)에서 만든 후보가
**다른 물건인데 둘 다 «같은 설정으로 학습했다»고 적힌다.** 6단계에서 둘을 나란히 재면
«바꾼 설정 때문인지 코어 수 때문인지»를 못 가린다 — 그리고 **아무 오류도 안 난다.**

이 저장소가 같은 모양을 이미 두 번 겪었다: 낡은 목록으로 **조용히 적게** 학습한 것,
증강 호출부 하나를 빠뜨려 **«절반만 실측»** 으로 학습한 것. 둘 다 숫자만 달라졌다.

## 여기서 고정하는 것

| | 왜 |
|---|---|
| 같은 씨앗 · 다른 코어 수 → **같은 결과** | 위의 실패 모양을 구조로 막는다 |
| 결과 순서가 **일감 순서**다 | 끝난 순서로 쌓이면 X 의 줄 순서가 코어 수에 달린다 |
| 씨앗이 **일감마다 따로**이고 안 겹친다 | 공유 난수를 되살리면 여기서 걸린다 |
| 계획이 **코어 수를 모른다** | 알면 언젠가 코어 수에 따라 갈라진다 |
| 워커가 죽으면 **멈춘다** | 조용히 모자란 데이터로 학습하지 않는다 |
| 모르는 일감은 **예외** | 조용히 «창 0개»면 학습셋이 말없이 작아진다 |
| 균형 맞추기가 **양성을 안 버린다** | 사용자 목소리는 이 학습의 존재 이유다 |

⚠️ **CI(ubuntu)에는 numpy 가 없을 수 있다.** 그때는 건너뛴 것을 건너뛰었다고 말하고
   개수는 그대로 센다 — [`test_wakeword_corpus.py`](test_wakeword_corpus.py) 와 같은 방식이다.

🚨 **이 파일은 프로세스를 띄운다.** 윈도우는 `spawn` 이라 자식이 이 파일을 다시 읽는다.
   그래서 워커로 넘기는 함수는 **모듈 최상단에** 있어야 하고(람다·클로저는 피클이 안 된다),
   무거운 일을 최상단에서 하면 **워커마다 다시 한다.**
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import _testenv  # noqa: F401,E402

NL = chr(10)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0
_SKIP = None


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if _SKIP:
        passed += 1
        print(f"  ~ {name}   ({_SKIP} — 건너뜀)")
        return
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")


try:
    import numpy as np
    # 🔑 `train_wakeword` 가 쓰는 것과 **같은 이름**으로 들인다. `wakeword_parallel` 로
    #    들이면 파이썬이 같은 파일을 두 모듈로 따로 갖는다 — 2026-09-18에 이걸로
    #    테스트가 조용히 통과한 적이 있다(→ test_wakeword_corpus.py ⑪).
    import scripts.wakeword_parallel as P
    import scripts.train_wakeword as T
except Exception as e:                                        # noqa: BLE001
    _SKIP = f"{type(e).__name__}(numpy 없음 — CI)"
    np = None
    P = T = None


# ── 워커로 넘기는 것들 (최상단이어야 피클된다) ──────────────────────
def seeded_draw(item):
    """일감 안의 씨앗으로만 난수를 만든다 — `cook()` 과 **같은 모양**이다."""
    idx, seed = item
    rng = np.random.default_rng(seed)
    return idx, float(rng.random()), int(rng.integers(1000))


def slow_first(item):
    """앞쪽 일감이 더 오래 걸린다 — «끝난 순서»로 쌓으면 순서가 뒤집힌다."""
    idx, seed = item
    s = 0
    for i in range((20 - idx) * 20000):
        s += i % 3
    return idx


def boom(item):
    idx, _seed = item
    if idx == 3:
        raise ValueError("워커가 터졌다(일부러)")
    return idx


_INIT = {}


def mark_init(tag):
    _INIT["tag"] = tag


def read_init(item):
    return _INIT.get("tag")


def run():
    print("=== ① resolve_jobs — «0 은 전부 · 음수는 오류» ===")
    if not _SKIP:
        cpu = os.cpu_count() or 1
        check("None 이면 코어 전부", P.resolve_jobs(None) == cpu)
        check("0 이면 코어 전부", P.resolve_jobs(0) == cpu)
        check("1 이면 한 코어", P.resolve_jobs(1) == 1)
        check("숫자를 주면 그 수", P.resolve_jobs(5) == 5)
        check("일감보다 많은 워커는 안 만든다 (cap)",
              P.resolve_jobs(0, cap=3) == 3, f"실제 {P.resolve_jobs(0, cap=3)}")
        check("cap 이 커도 요청을 안 늘린다", P.resolve_jobs(2, cap=100) == 2)
        check("cap 이 0 이어도 최소 1", P.resolve_jobs(0, cap=0) == 1)
        # 🚨 sklearn 은 «-1 = 전부» 지만 여기서는 오류다. 0 과 -1 이 둘 다 «전부» 면
        #    «1을 주려다 -1을 준» 실수가 **안 걸린다.**
        try:
            P.resolve_jobs(-1)
            ok = False
        except ValueError:
            ok = True
        check("🚨 음수는 예외다 («-1=전부» 관례를 흉내 내지 않는다)", ok)
    else:
        for n in ("None 이면 코어 전부", "0 이면 코어 전부", "1 이면 한 코어",
                  "숫자를 주면 그 수", "일감보다 많은 워커는 안 만든다 (cap)",
                  "cap 이 커도 요청을 안 늘린다", "cap 이 0 이어도 최소 1",
                  "🚨 음수는 예외다 («-1=전부» 관례를 흉내 내지 않는다)"):
            check(n, True)

    print(f"{NL}=== ② child_seeds — 씨앗은 (seed, 순번) 만으로 정해진다 ===")
    if not _SKIP:
        a = P.child_seeds(0, 10)
        check("요청한 수만큼 준다", len(a) == 10)
        check("같은 seed 면 같은 씨앗", P.child_seeds(0, 10) == a)
        check("다른 seed 면 다른 씨앗", P.child_seeds(1, 10) != a)
        check("서로 안 겹친다", len(set(a)) == 10)
        # 일감을 뒤에 더 붙여도 앞은 안 바뀐다 — 계획을 늘려도 이미 만든 부분이 그대로다
        check("뒤에 더 붙여도 앞 씨앗이 그대로다", P.child_seeds(0, 5) == a[:5])
        check("0개를 달라면 빈 목록", P.child_seeds(0, 0) == [])
        # 🔑 `seed + i` 로 만들면 이웃 seed 의 스트림이 겹칠 수 있다. spawn 은 안 겹친다
        check("이웃 seed 와도 안 겹친다",
              not (set(P.child_seeds(0, 50)) & set(P.child_seeds(1, 50))))
        try:
            P.child_seeds(0, -1)
            ok = False
        except ValueError:
            ok = True
        check("개수가 음수면 예외", ok)
    else:
        for n in ("요청한 수만큼 준다", "같은 seed 면 같은 씨앗", "다른 seed 면 다른 씨앗",
                  "서로 안 겹친다", "뒤에 더 붙여도 앞 씨앗이 그대로다",
                  "0개를 달라면 빈 목록", "이웃 seed 와도 안 겹친다", "개수가 음수면 예외"):
            check(n, True)

    print(f"{NL}=== ③ pmap — 🚨 «--jobs 가 결과를 안 바꾼다» ===")
    if not _SKIP:
        items = list(enumerate(P.child_seeds(42, 24)))
        one = P.pmap(seeded_draw, items, jobs=1)
        check("빈 일감은 빈 결과 (풀도 안 만든다)", P.pmap(seeded_draw, [], jobs=8) == [])
        check("한 코어로 다 돈다", len(one) == 24)
        four = P.pmap(seeded_draw, items, jobs=4)
        check("🚨 4코어 결과가 1코어와 **완전히 같다**", four == one,
              f"실제 첫 불일치 {[i for i, (x, y) in enumerate(zip(one, four)) if x != y][:3]}")
        check("🚨 8코어도 같다", P.pmap(seeded_draw, items, jobs=8) == one)
        check("일감마다 다른 값이 나온다 (씨앗이 진짜 다르다)",
              len({r[1] for r in one}) == 24)

        # 순서 — 앞쪽이 느린 일감으로 «끝난 순서»가 아님을 본다
        slow = list(enumerate(P.child_seeds(1, 12)))
        check("결과 순서가 **일감 순서**다 (끝난 순서가 아니다)",
              P.pmap(slow_first, slow, jobs=4) == list(range(12)))

        check("initializer 가 워커에서 불린다",
              set(P.pmap(read_init, items[:8], jobs=4,
                         initializer=mark_init, initargs=("깔렸다",))) == {"깔렸다"})
        check("한 코어일 때도 initializer 를 부른다 (같은 길을 탄다)",
              set(P.pmap(read_init, items[:4], jobs=1,
                         initializer=mark_init, initargs=("깔렸다",))) == {"깔렸다"})

        # 🚨 워커가 터지면 «결과가 적게 나온다»가 아니라 **여기서 멈춘다.**
        for jobs in (1, 4):
            try:
                P.pmap(boom, items[:8], jobs=jobs)
                ok = False
            except Exception:                                 # noqa: BLE001
                ok = True
            check(f"🚨 워커 예외가 조용히 안 빠진다 (jobs={jobs})", ok)
    else:
        for n in ("빈 일감은 빈 결과 (풀도 안 만든다)", "한 코어로 다 돈다",
                  "🚨 4코어 결과가 1코어와 **완전히 같다**", "🚨 8코어도 같다",
                  "일감마다 다른 값이 나온다 (씨앗이 진짜 다르다)",
                  "결과 순서가 **일감 순서**다 (끝난 순서가 아니다)",
                  "initializer 가 워커에서 불린다",
                  "한 코어일 때도 initializer 를 부른다 (같은 길을 탄다)",
                  "🚨 워커 예외가 조용히 안 빠진다 (jobs=1)",
                  "🚨 워커 예외가 조용히 안 빠진다 (jobs=4)"):
            check(n, True)

    print(f"{NL}=== ④ plan_dataset — 개수는 **미리** 셀 수 있다 ===")
    if not _SKIP:
        pos = [f"p{i}.mp3" for i in range(10)]
        neg = [f"n{i}.mp3" for i in range(10)]
        plan = T.plan_dataset(pos, neg, [], aug_per_clip=3, speech_negatives=100,
                              seed=0, has_augmenter=True, quiet=True)

        def wins(p, kind=None, label=None):
            return sum(r.n for r in p
                       if (kind is None or r.kind == kind)
                       and (label is None or r.label == label))

        check("양성 창 = 클립 × 증강", wins(plan, label=1) == 30, f"실제 {wins(plan, label=1)}")
        check("잡음 창이 정확히 NOISE_WINDOWS 개",
              wins(plan, "noise") == T.NOISE_WINDOWS, f"실제 {wins(plan, 'noise')}")
        check("한국어 말소리 창이 정확히 요청한 수",
              wins(plan, "speech") == 100, f"실제 {wins(plan, 'speech')}")
        check("씨앗이 일감마다 다르다",
              len({r.seed for r in plan}) == len(plan))
        check("같은 입력이면 같은 계획 (재현된다)",
              T.plan_dataset(pos, neg, [], 3, 100, seed=0, has_augmenter=True,
                             quiet=True) == plan)
        check("seed 를 바꾸면 씨앗이 갈린다",
              [r.seed for r in T.plan_dataset(pos, neg, [], 3, 100, seed=1,
                                              has_augmenter=True, quiet=True)]
              != [r.seed for r in plan])

        # 흉내 모드 — 말뭉치를 안 읽으므로 말소리 일감이 **생기면 안 된다**
        mimic = T.plan_dataset(pos, neg, [], 3, 100, seed=0, has_augmenter=False,
                               quiet=True)
        check("흉내 모드엔 말소리 일감이 없다", wins(mimic, "speech") == 0)

        # 균형 — 양성이 많을 때만 음성을 채운다. **양성은 안 버린다.**
        many_pos = [f"p{i}.mp3" for i in range(600)]
        bal = T.plan_dataset(many_pos, neg, [], 3, 0, seed=0, has_augmenter=True,
                             quiet=True)
        check("양성이 많으면 음성을 **정확히** 그만큼 채운다",
              wins(bal, label=0) == wins(bal, label=1),
              f"양성 {wins(bal, label=1)} · 음성 {wins(bal, label=0)}")
        check("균형이 양성을 안 버린다 (양성 수가 그대로다)",
              wins(bal, label=1) == 600 * 3)
        check("음성이 이미 많으면 균형이 아무 일도 안 한다",
              len(T.plan_dataset(pos, neg, [], 3, 100, seed=0, has_augmenter=True,
                                 quiet=True)) == len(plan))

        # 사용자 녹음 — 발화 구간은 **양성**이고 증강이 2배다
        ua = T.plan_dataset([], [], [0, 4000, 8000], 3, 0, seed=0,
                            has_augmenter=True, quiet=True)
        check("사용자 녹음 구간은 양성이다",
              all(r.label == 1 for r in ua if r.kind == "user"))
        check("사용자 녹음은 증강이 2배다 (합성음 과적합을 막는 핵심)",
              wins(ua, "user") == 3 * 3 * 2, f"실제 {wins(ua, 'user')}")

        # 🚨 모르는 종류를 조용히 «창 0개»로 넘기면 학습셋이 말없이 작아진다
        T._W["augmenter"] = None
        try:
            T._windows(T.Recipe("있지도 않은 것", None, 1, 0, 7),
                       np.random.default_rng(0))
            ok = False
        except ValueError:
            ok = True
        check("🚨 모르는 일감은 예외다 (조용히 창 0개가 아니다)", ok)
        check("잡음 일감은 요청한 만큼 창을 만든다",
              len(T._windows(T.Recipe("noise", None, 7, 0, 7),
                             np.random.default_rng(0))) == 7)
        w1 = T._windows(T.Recipe("noise", None, 3, 0, 99), np.random.default_rng(99))
        w2 = T._windows(T.Recipe("noise", None, 3, 0, 99), np.random.default_rng(99))
        check("같은 씨앗이면 같은 창이 나온다",
              all(bool(np.array_equal(a_, b_)) for a_, b_ in zip(w1, w2)))
    else:
        for n in ("양성 창 = 클립 × 증강", "잡음 창이 정확히 NOISE_WINDOWS 개",
                  "한국어 말소리 창이 정확히 요청한 수", "씨앗이 일감마다 다르다",
                  "같은 입력이면 같은 계획 (재현된다)", "seed 를 바꾸면 씨앗이 갈린다",
                  "흉내 모드엔 말소리 일감이 없다",
                  "양성이 많으면 음성을 **정확히** 그만큼 채운다",
                  "균형이 양성을 안 버린다 (양성 수가 그대로다)",
                  "음성이 이미 많으면 균형이 아무 일도 안 한다",
                  "사용자 녹음 구간은 양성이다",
                  "사용자 녹음은 증강이 2배다 (합성음 과적합을 막는 핵심)",
                  "🚨 모르는 일감은 예외다 (조용히 창 0개가 아니다)",
                  "잡음 일감은 요청한 만큼 창을 만든다",
                  "같은 씨앗이면 같은 창이 나온다"):
            check(n, True)

    print(f"{NL}=== ⑤ 소스 계약 — 주석이 아니라 구조로 ===")
    src = io.open(os.path.join(_ROOT, "scripts", "train_wakeword.py"),
                  encoding="utf-8").read()
    par = io.open(os.path.join(_ROOT, "scripts", "wakeword_parallel.py"),
                  encoding="utf-8").read()

    check("학습 스크립트에 --jobs 가 있다", '"--jobs"' in src)
    # 🔑 계획이 코어 수를 **모른다.** 알면 언젠가 코어 수에 따라 갈라진다.
    sig = re.search(r"def plan_dataset\(([^)]*)\)", src, re.S)
    check("🚨 plan_dataset 이 jobs 를 인자로 안 받는다 (계획은 코어 수를 모른다)",
          bool(sig) and "jobs" not in sig.group(1),
          f"실제 {sig.group(1) if sig else '없음'}")
    check("🚨 워커가 **일감 안의 씨앗**으로 난수를 만든다 (공유 rng 가 아니다)",
          "default_rng(rec.seed)" in src)
    check("워커의 ONNX 가 ncpu=1 이다 (서로 코어를 안 뺏는다)",
          "AudioFeatures(ncpu=1)" in src)
    check("창이 워커 밖으로 안 나간다 (돌려주는 것은 임베딩이다)",
          "return rec.label, extract_features(" in src)
    check("병렬 층이 표준 라이브러리만 쓴다 (새 의존성 없음)",
          "ProcessPoolExecutor" in par and "import joblib" not in par
          and "import multiprocess" not in par)
    check("워커가 죽으면 멈춘다 (조용히 모자란 데이터로 안 간다)",
          "BrokenProcessPool" in par and "raise RuntimeError" in par)

    # 🚨 런타임은 이 파일을 안 읽는다 — `scripts/` 전용이다(M7 «런타임 0줄»)
    hits = []
    for d in ("services", "core", "tools"):
        p = os.path.join(_ROOT, d)
        for dirpath, _dirs, files in os.walk(p) if os.path.isdir(p) else []:
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                if "wakeword_parallel" in io.open(os.path.join(dirpath, fn),
                                                  encoding="utf-8").read():
                    hits.append(fn)
    check("🚨 런타임(services·core·tools)이 병렬 층을 안 읽는다 (런타임 0줄)",
          not hits, f"실제 {hits}")

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
