# -*- coding: utf-8 -*-
"""평가 하네스의 계약 — **자가 틀리면 모든 판단이 틀린다** (M7 1·2단계)

실행: python tests/test_eval_wakeword.py

## 왜 이 테스트가 있나

`scripts/eval_wakeword.py` 가 내는 숫자는 **«재학습이 답이다»라는 결론의 근거 전부**다
(FRR 20.3% · FA/시간 74.7 · 임계로도 관문으로도 목표에 못 간다).
그런데 이 종류의 코드는 [`analyze_cache_savings.py`](test_cache_savings.py) 와 같은 자리에 있다 —
**틀려도 오류가 안 난다. 그냥 다른 숫자가 나온다.**

2026-09-08에 «검증 95.0%»를 보고 끝났다고 적은 것이 정확히 그 사고였다.
**자를 만들었으면 자를 검사해야 한다.**

## 여기서 고정하는 것 넷

1. **관문에 막힌 창은 쿨다운도 건드리지 않는다.** 순서가 런타임과 같아야 한다
   (창 → 관문 → 쿨다운 → 추론). 뒤집히면 «막힌 소리»가 다음 진짜 호출을 잡아먹는다.
2. 🚨 **관문을 사후에 씌운 것 == 관문을 켜고 스캔한 것.** `--energy-sweep` 전체가
   이 동치성 위에 서 있다. 깨지면 관문 훑기 표가 **재지 않은 것을 말한다.**
3. **FA/시간의 분모는 «음성 구간 초»**이지 녹음 전체 길이가 아니다.
   전체로 나누면 오탐이 **조용히 작아 보인다.**
4. **한 양성 구간을 두 번 깨도 한 번으로 센다.** 안 그러면 «깸»이 «부름»을 넘는다.

## ⚠️ 런타임 값을 베껴 적지 않는다

쿨다운·창 길이는 `services/wakeword.py` **소스에서 그대로 읽는다.** 여기 숫자를 적으면
언젠가 한쪽만 바뀌고, 그러면 **런타임이 아닌 것을 재는 자를 검사하는 테스트**가 된다.
(하네스 자신이 `import` 로 지키는 규칙을, 테스트도 같은 이유로 지킨다.)

⚠️ `scripts/eval_wakeword.py` 는 최상위에서 `services/wakeword.py` 를 import 하고,
   그건 sounddevice 를 요구한다. CI(ubuntu)에는 없다. 그래서
   [`test_wakeword_kws.py`](test_wakeword_kws.py) 와 **같은 방식**으로 소스에서
   순수 판정 구간만 떼어내 실행한다.
"""
import io
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

NL = chr(10)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")


# ── 런타임 상수를 **소스에서** 읽는다 (베껴 적지 않는다) ──────────────
_rt_src = io.open(os.path.join(_ROOT, "services", "wakeword.py"), encoding="utf-8").read()
_consts = {}
for _name in ("SAMPLE_RATE", "WINDOW_SECONDS", "WINDOW_SAMPLES",
              "HOP_SECONDS", "HOP_SAMPLES", "COOLDOWN_SEC"):
    _m = re.search(rf"^{_name}\s*=\s*([^#\n]+)", _rt_src, re.M)
    if not _m:
        sys.exit(f"[test] FATAL: services/wakeword.py 에서 {_name} 를 못 찾았다 "
                 f"— 상수가 옮겨졌다면 이 테스트를 고쳐야 한다")
    _consts[_name] = eval(_m.group(1).strip(), dict(_consts))

# ── 하네스의 순수 판정 구간만 떼어내 실행한다 ─────────────────────────
_src = io.open(os.path.join(_ROOT, "scripts", "eval_wakeword.py"), encoding="utf-8").read()
E = types.ModuleType("eval_pure")
E.__dict__.update(_consts)
E.NEGATIVE_LABELS = eval(
    re.search(r"^NEGATIVE_LABELS\s*=\s*(\(.*?\))", _src, re.M | re.S).group(1))
E.ENERGY_FLOORS = eval(
    re.search(r"^ENERGY_FLOORS\s*=\s*(\[.*?\])", _src, re.M | re.S).group(1))
exec(compile(_src[_src.index("def replay("):_src.index("# ── 출력")],
             "eval_pure", "exec"), E.__dict__)


def frames(*triples):
    """(시각, 에너지, 확률) 목록을 그대로 만든다. None 은 «관문에 막힘»."""
    return list(triples)


def run():
    COOL = E.COOLDOWN_SEC
    WIN = E.WINDOW_SECONDS

    print("=== ① 쿨다운 — 연속으로 깨지 않는다 ===")
    f = frames((10.0, 0.1, 0.99), (10.0 + COOL / 2, 0.1, 0.99), (10.0 + COOL + 0.1, 0.1, 0.99))
    check("쿨다운 안의 두 번째는 안 깬다", E.replay(f, 0.8) == [10.0, 10.0 + COOL + 0.1])
    check("임계 미만은 애초에 안 깬다", E.replay(f, 0.995) == [])

    print("=== ② 🚨 관문에 막힌 창은 쿨다운을 건드리지 않는다 ===")
    # 막힌 창이 쿨다운을 밀면 **그 뒤의 진짜 호출을 잡아먹는다.** 런타임은 관문에서
    # 추론 자체를 건너뛰므로 «깬 적»이 없고, 따라서 쿨다운 시계도 안 움직인다.
    f = frames((10.0, 0.0001, None), (10.5, 0.1, 0.99))
    check("막힌 창 직후의 진짜 창이 깬다", E.replay(f, 0.8) == [10.5])
    f2 = frames((10.0, 0.1, 0.99), (10.5, 0.1, 0.99))
    check("(대조) 안 막힌 창이었다면 뒤가 쿨다운에 먹힌다", E.replay(f2, 0.8) == [10.0])

    print("=== ③ 🚨 관문을 «사후에» 올린 것과 «켜고 스캔한 것»이 같은가 ===")
    # --energy-sweep 전체가 이 동치성 위에 서 있다.
    raw = frames((1.0, 0.0005, 0.99), (2.0, 0.004, 0.99), (3.0, 0.02, 0.99),
                 (4.0, 0.0005, 0.99), (20.0, 0.004, 0.99))
    for fl in (0.0, 0.001, 0.005, 0.01, 0.05):
        # «켜고 스캔한 것» = 관문 미만이면 확률이 아예 없다(None)
        gated = [(t, e, (pr if e >= fl else None)) for (t, e, pr) in raw]
        check(f"관문 {fl:.3f} — 사후 적용과 스캔 시 적용이 같다",
              E.replay(raw, 0.8, fl) == E.replay(gated, 0.8))
    check("관문을 올릴수록 깨는 횟수가 늘지 않는다 (단조)",
          all(len(E.replay(raw, 0.8, a)) >= len(E.replay(raw, 0.8, b))
              for a, b in zip(E.ENERGY_FLOORS, E.ENERGY_FLOORS[1:])))

    print("=== ④ 훑을 관문 목록 — 옛 값 0.008 이 들어 있는가 ===")
    # 🚨 0.008 은 2026-09-08까지 쓰던 관문이고, 그때 발화가 **모델에 도달조차 못 했다.**
    #    목록에서 빠지면 «관문을 올리자»의 대가를 재는 줄이 사라진다.
    check("지금 관문(0.0015)이 들어 있다", 0.0015 in E.ENERGY_FLOORS)
    check("🚨 옛 Whisper 관문(0.008)이 들어 있다", 0.008 in E.ENERGY_FLOORS)
    check("관문 0(관문 없음)도 잰다 — 관문이 얼마나 막고 있는지의 분모다",
          0.0 in E.ENERGY_FLOORS)
    check("오름차순이다", E.ENERGY_FLOORS == sorted(E.ENERGY_FLOORS))

    print("=== ⑤ 채점 — 깬 시각은 «가장 많이 겹치는 구간»에 귀속된다 ===")
    # 창은 [t-2.0, t] 다. t 만 보면 한 칸씩 밀린다 — 그게 이 규칙의 존재 이유다.
    sess = [{
        "speaker": "가", "holdout": False,
        "segments": [{"start": 0.0, "end": 3.0, "label": "positive"},
                     {"start": 3.0, "end": 60.0, "label": "freetalk"}],
        "frames": frames((3.4, 0.1, 0.99)),      # t=3.4 는 freetalk 안이지만
    }]                                            # 창 [1.4, 3.4] 는 positive 와 1.6초 겹친다
    r = E.score(sess, 0.8)
    check("t 가 다음 구간에 있어도 창이 더 겹치는 쪽으로 센다 (양성 적중)",
          r["pos_hit"] == 1 and r["fa"] == 0)

    print("=== ⑥ 같은 양성 구간을 두 번 깨도 한 번이다 ===")
    sess = [{
        "speaker": "가", "holdout": False,
        "segments": [{"start": 0.0, "end": 30.0, "label": "positive"}],
        "frames": frames((5.0, 0.1, 0.99), (5.0 + COOL + 0.1, 0.1, 0.99)),
    }]
    r = E.score(sess, 0.8)
    check("깸(1) 이 부름(1) 을 넘지 않는다", r["pos_hit"] == 1 and r["pos_total"] == 1)
    check("FRR 이 음수가 되지 않는다", r["frr"] == 0.0)

    print("=== ⑦ 🚨 FA/시간의 분모는 «음성 구간 초»다 (전체 길이가 아니다) ===")
    # 전체 길이로 나누면 양성 구간까지 분모에 들어가 **오탐이 조용히 작아 보인다.**
    sess = [{
        "speaker": "가", "holdout": False,
        "segments": [{"start": 0.0, "end": 3600.0, "label": "positive"},
                     {"start": 3600.0, "end": 5400.0, "label": "freetalk"}],   # 0.5시간
        "frames": frames((3700.0, 0.1, 0.99)),
    }]
    r = E.score(sess, 0.8)
    check("음성 구간 0.5시간에 오탐 1회 → FA/시간 2.0",
          r["fa"] == 1 and abs(r["fa_per_hour"] - 2.0) < 1e-9)
    check("전체 1.5시간으로 나눈 0.67 이 아니다", abs(r["fa_per_hour"] - 0.667) > 0.1)

    print("=== ⑧ 라벨을 쪼갠 오탐 — 섞으면 어느 쪽도 아닌 값이 된다 ===")
    sess = [{
        "speaker": "가", "holdout": False,
        "segments": [{"start": 0.0, "end": 1800.0, "label": "negative"},
                     {"start": 1800.0, "end": 5400.0, "label": "freetalk"}],
        "frames": frames((100.0, 0.1, 0.99), (2000.0, 0.1, 0.99), (3000.0, 0.1, 0.99)),
    }]
    r = E.score(sess, 0.8)
    check("«헷갈리는 말» 오탐 1 · 0.5시간 → 2.0/시간",
          r["fa_by_label"]["negative"] == 1
          and abs(r["fa_per_hour_by_label"]["negative"] - 2.0) < 1e-9)
    check("«자유 발화» 오탐 2 · 1.0시간 → 2.0/시간",
          r["fa_by_label"]["freetalk"] == 2
          and abs(r["fa_per_hour_by_label"]["freetalk"] - 2.0) < 1e-9)
    check("합계는 3회다 (라벨별 합과 같다)", r["fa"] == 3)

    print("=== ⑨ 관문이 결과에 실제로 반영되는가 (score 까지) ===")
    sess = [{
        "speaker": "가", "holdout": False,
        "segments": [{"start": 0.0, "end": 3.0, "label": "positive"},
                     {"start": 3.0, "end": 3600.0, "label": "freetalk"}],
        "frames": frames((2.0, 0.002, 0.99), (100.0, 0.002, 0.99)),
    }]
    lo = E.score(sess, 0.8, 0.0)
    hi = E.score(sess, 0.8, 0.005)          # 둘 다 관문에 막히는 높이
    check("관문이 낮으면 양성도 잡고 오탐도 난다", lo["pos_hit"] == 1 and lo["fa"] == 1)
    check("🚨 관문을 올리면 오탐이 줄지만 **양성도 놓친다**",
          hi["fa"] == 0 and hi["pos_hit"] == 0)
    check("«놓침»이 FRR 에 그대로 나타난다 (대가를 숨기지 않는다)", hi["frr"] == 1.0)
    check("결과에 어느 관문으로 쟀는지가 남는다", hi["energy_floor"] == 0.005)

    print("=== ⑩ 하네스가 런타임 값을 베껴 적지 않았는가 ===")
    # 여기가 «자가 런타임과 같은 것인가»를 지키는 자리다.
    check("상수를 services/wakeword.py 에서 import 한다",
          "from services.wakeword import" in _src and "COOLDOWN_SEC" in _src)
    check("🚨 하네스 안에 쿨다운 숫자를 직접 적어 두지 않았다",
          not re.search(r"COOLDOWN_SEC\s*=\s*[0-9]", _src))
    check("🚨 창 길이도 직접 적어 두지 않았다",
          not re.search(r"WINDOW_SECONDS\s*=\s*[0-9]", _src))
    check(f"읽어 온 런타임 값이 말이 된다 (창 {WIN}s · 쿨다운 {COOL}s)",
          WIN > 0 and COOL > 0 and E.SAMPLE_RATE == 16000)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
