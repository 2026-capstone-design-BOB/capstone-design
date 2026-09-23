# -*- coding: utf-8 -*-
"""코어를 다 쓰게 하는 층 — **결과는 코어 수에 안 달렸다** (M7 §6-1)

    python scripts/train_wakeword.py               # 코어 전부
    python scripts/train_wakeword.py --jobs 1      # 한 코어 (예전과 같은 길)

## 이 파일이 있는 이유

[M7 §6-1](../docs/design/M7_웨이크워드_재구축.md)을 쓰면서 잰 것: 이 파이프라인에
**GPU 를 쓰는 자리가 한 군데도 없다.** 비싼 것은 학습이 아니라 «재료를 만드는 일»이고
전부 CPU 다 — 임베딩 추출 29ms · 증강 40ms · 말소리 읽기 7ms.

    그런데 **전부 `for` 루프였다.** 32코어 서버를 빌려도 31개가 논다.

서버가 사 주는 것은 «한 번»이 아니라 **«여러 번»** 이다(`--speech-neg` 를 10배로 키운
후보, 증강을 바꾼 후보를 나란히 만들어 §5-2의 자로 재는 일). 그 «여러 번»이
코어 하나로 직렬이면 서버를 빌릴 이유가 없다. 그래서 여기가 **선행**이다.

## 🔑 이 층이 지키는 것 하나 — «`--jobs` 가 결과를 안 바꾼다»

병렬화에서 조용히 틀리는 방식은 **속도가 아니라 재현성**이다.
난수 하나를 여러 워커가 나눠 쓰면 **일감이 어느 순서로 끝나느냐에 따라 데이터셋이
달라진다.** 그러면 이렇게 된다:

- 노트북(16코어)에서 만든 후보와 서버(32코어)에서 만든 후보가 **다른 물건**인데
  둘 다 «같은 설정으로 학습했다»고 적힌다.
- 6단계에서 둘을 나란히 재면 **무엇 때문에 차이가 났는지 못 가린다** —
  바꾼 설정 때문인지 코어 수 때문인지.
- **아무 오류도 안 난다.** 이 저장소가 반복해서 겪은 실패 모양 그대로다
  (낡은 목록으로 조용히 적게 학습한 것 · «절반만 실측»으로 학습한 것).

그래서 **난수를 나눠 쓰지 않는다.** 일감마다 `(seed, 순번)` 만으로 정해지는 씨앗을
미리 박아 두고(`child_seeds`), 워커는 그 씨앗으로 자기 난수를 만든다.
그러면 몇 코어로 돌든 · 어느 순서로 끝나든 **같은 데이터셋**이 나온다.

> ⚠️ **이건 부르는 쪽과의 계약이다.** `pmap` 은 «일감만 보고 결과가 정해지는 함수»에만
> 이 성질을 준다. 일감 밖의 난수(공유 `rng`)나 전역 상태를 읽는 함수를 넘기면
> **여기서 막아 줄 수 없다.** 일감에 씨앗을 넣어 보내라.

## 창은 프로세스 경계를 안 넘는다

2초 창 하나가 `float32` 32,000개 = **128KB** 다. 기본 설정이 6,300창이니
부모에서 증강해 워커로 보내면 **800MB 를 직렬화**하는데, 그게 병렬로 번 시간을
도로 먹는다. 그래서 워커가 **증강부터 임베딩까지 한 번에** 한다 —
넘어가는 것은 일감 한 줄이고 돌아오는 것은 임베딩(1536 float = 6KB)이다.

## 새 의존성을 안 쓴다

`concurrent.futures` 는 표준 라이브러리이고 `numpy.random.SeedSequence` 도
numpy 안에 있다. 런타임(`services/`)은 이 파일을 **안 읽는다** — `scripts/` 전용이다.
"""
from __future__ import annotations

import os
import time

import numpy as np

__all__ = ["resolve_jobs", "child_seeds", "pmap"]


def resolve_jobs(requested=None, cap=None):
    """`--jobs` 를 실제 워커 수로 바꾼다.

    | 받은 값 | 뜻 |
    |---|---|
    | `None` · `0` | **코어 전부** (기본값) |
    | `1` | 한 코어 — 풀을 아예 안 만든다 |
    | `n` | n개 |

    `cap` 은 «일감보다 많은 워커를 만들지 않는다»를 위한 것이다. 일감이 3개인데
    워커를 32개 띄우면 29개는 태어나서 아무것도 안 하고 죽는다(윈도우에서는
    프로세스 하나 띄우는 데 1~2초다 — 병렬화가 **느려지는** 구간이 생긴다).
    """
    if requested is None or requested == 0:
        n = os.cpu_count() or 1
    elif requested < 0:
        # 🚨 «-1 = 전부» 같은 관례를 흉내 내지 않는다. sklearn 은 그렇게 하지만
        #    여기서 0 과 -1 이 둘 다 «전부» 면 «1을 주려다 -1을 준» 실수가 안 걸린다.
        raise ValueError(f"[parallel] --jobs 는 음수가 될 수 없다 (받은 값: {requested}). "
                         f"0 이 «코어 전부» 다")
    else:
        n = int(requested)
    if cap is not None:
        n = min(n, max(1, int(cap)))
    return max(1, n)


def child_seeds(seed, n):
    """일감 n개에 **각자의 씨앗**을 준다.

    🔑 씨앗이 `(seed, 순번)` 만으로 정해진다 — **몇 코어로 도는지가 안 섞인다.**
       `SeedSequence.spawn` 은 순번을 해시에 넣으므로 서로 겹치지 않는 것도 보장된다
       (`default_rng(seed + i)` 로 만들면 이웃한 씨앗의 스트림이 겹칠 수 있다).

    일감을 더 만들어 뒤에 붙여도 **앞의 씨앗은 그대로다** — `spawn(5)` 의 결과는
    `spawn(10)` 의 앞 5개와 같다. 계획을 늘려도 이미 만든 부분이 안 바뀐다.
    """
    if n < 0:
        raise ValueError(f"[parallel] 일감 수가 음수다 ({n})")
    ss = np.random.SeedSequence(int(seed))
    return [int(c.generate_state(1, dtype=np.uint64)[0]) for c in ss.spawn(int(n))]


def _tick(label, done, total, every, t0):
    if not label or every <= 0:
        return
    if done % every and done != total:
        return
    el = time.time() - t0
    rate = done / el if el > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else 0.0
    print(f"  {label}: {done}/{total}  ({el:.0f}초 · 남은 {eta:.0f}초)", flush=True)


def pmap(fn, items, jobs=1, initializer=None, initargs=(), label="", every=200):
    """일감을 코어에 나눠 주고 **순서를 지켜** 결과를 모은다.

    - `jobs <= 1` 이면 **풀을 아예 안 만든다.** 대신 `initializer` 를 이 프로세스에서
      부르고 그냥 돈다 — 그래서 한 코어 경로와 여러 코어 경로가 **같은 `fn` 을 탄다.**
      («빠른 길에만 있는 버그»를 만들지 않는다. 테스트가 둘을 비교할 수 있는 것도
      이 때문이다.)
    - 결과 순서는 **일감 순서**다(끝난 순서가 아니다). `X` 의 줄 순서가 코어 수에
      안 달리게 하는 자리가 여기다.

    ⚠️ `fn` 과 `items` 는 **피클 가능**해야 한다(윈도우는 `spawn` 이라 모듈을 다시
       읽는다). 모듈 최상단에 정의된 함수와 `namedtuple` 이면 된다 —
       람다·클로저·열린 파일은 안 된다.
    """
    items = list(items)
    total = len(items)
    if total == 0:
        return []

    jobs = resolve_jobs(jobs, cap=total)
    t0 = time.time()
    out = []

    if jobs == 1:
        if initializer is not None:
            initializer(*initargs)
        for i, it in enumerate(items):
            out.append(fn(it))
            _tick(label, i + 1, total, every, t0)
        return out

    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    # 한 번에 보내는 덩어리. 너무 작으면 왕복 비용이 커지고, 너무 크면 마지막에
    # 워커 하나만 남아 꼬리가 길어진다. 워커당 8덩어리면 둘 다 피한다.
    chunk = max(1, total // (jobs * 8))
    try:
        with ProcessPoolExecutor(max_workers=jobs, initializer=initializer,
                                 initargs=initargs) as ex:
            for i, r in enumerate(ex.map(fn, items, chunksize=chunk)):
                out.append(r)
                _tick(label, i + 1, total, every, t0)
    except BrokenProcessPool as e:
        # 🚨 워커가 죽으면 «결과가 적게 나온다»가 아니라 **여기서 멈춘다.**
        #    조용히 모자란 데이터로 학습하지 않는다.
        #
        # ⚠️ 여기서는 **죽은 이유를 모른다.** 자식이 통째로 사라지면 예외가 안 건너온다
        #    (일감 안에서 난 예외는 그대로 올라오니 이 길로 안 온다). 그래서 «메모리다»
        #    라고 단정하지 않고 **짚어 볼 곳 둘을 말한다.**
        raise RuntimeError(
            f"[parallel] 워커가 통째로 죽었다 ({jobs}개로 돌던 중). "
            f"흔한 원인은 둘이다 — ① 메모리(`--jobs {max(1, jobs // 2)}` 로 줄여 봐라) "
            f"② 워커를 차리는 단계(initializer)에서의 실패. "
            f"②인지 보려면 `--jobs 1` 로 돌려라 — 그 길은 이 프로세스에서 차리므로 "
            f"**진짜 예외가 그대로 보인다.** 원인: {type(e).__name__}") from e
    return out
