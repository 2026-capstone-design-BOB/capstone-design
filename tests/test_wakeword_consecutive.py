"""연속 N창 확인의 **회귀 자물쇠** (2026-10-01).

🔑 이것이 이번 라운드에서 가장 큰 지렛대였다 — 같은 모델·같은 확률을
   **어떻게 읽을지**만 바꿔서 헛깨어남을 **264 → 15회/시간**으로 내렸다.
   추론을 더 돌리지 않으므로 비용이 0 이다.

🚨 **되돌아가기 쉬운 자리다.** 「연속이 뭐 하는 거지」 하고 지우면 숫자가 통째로
   돌아간다. 그래서 동작을 테스트로 박는다.

    conda activate pluiz
    python tests/test_wakeword_consecutive.py
"""
import io
import os
import sys

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


# ═══ ① 설정이 있고 기본값이 실측 운용점이다 ═══════════════════════
print("=== ① 운용점 — 실측으로 고른 값이 코드 기본값이다 ===")
from config.settings import get_settings                       # noqa: E402

get_settings.cache_clear()
st = get_settings()
check("`wakeword_consecutive` 설정이 있다", hasattr(st, "wakeword_consecutive"))
check("기본이 **2** 다 (연속 2 · 임계 0.80 = 15회/시간 · 놓침 15.2%)",
      st.wakeword_consecutive == 2, f"→ {getattr(st, 'wakeword_consecutive', None)}")
check("임계 기본이 **0.80** 이다", abs(st.wakeword_threshold - 0.80) < 1e-9,
      f"→ {st.wakeword_threshold}")

# 🔑 **`.env` 가 아니라 코드가 기본값을 들고 있어야 한다** — 2026-09-28 에 같은 이유로
#   한 번 옮겼다. `.env` 는 사람마다 다르고 저장소에 안 올라간다.
_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    body = io.open(_env, encoding="utf-8", errors="replace").read()
    check("🔒 `.env` 가 운용점을 덮어쓰고 있지 않다",
          "WAKEWORD_THRESHOLD" not in body and "WAKEWORD_CONSECUTIVE" not in body,
          "`.env` 에 적혀 있으면 코드 기본값이 무의미해진다")

_cfg = _src("config/settings.py")
check("왜 그 값인지 **숫자로** 적혀 있다",
      "연속 2 · 0.80" in _cfg and "15.2%" in _cfg)
check("🚨 목표에 아직 못 간다는 사실도 적혀 있다",
      "아직 못 간다" in _cfg)


# ═══ ② 런타임이 설정을 읽는다 ═════════════════════════════════════
print("\n=== ② 런타임 ===")
from services.wakeword import kws_consecutive, kws_threshold    # noqa: E402

check("`kws_consecutive()` 가 있다", callable(kws_consecutive))
check("설정값을 읽는다", kws_consecutive() == st.wakeword_consecutive)
check("🔑 임계처럼 **매번 다시 읽는다** (재시작 없이 바꿀 수 있다)",
      "get_settings.cache_clear()" in _src("services/wakeword.py"))
check("🔒 최소 1 로 바닥을 둔다 (0 이나 음수면 연속 조건이 사라진다)",
      "max(1, int(" in _src("services/wakeword.py"))

_ws = _src("services/wakeword.py")
check("깨울 때 **연속 몇 창이었는지** 로그에 남는다", "연속 %d/%d" in _ws)
check("🚨 **끊기면 0 으로 돌아간다** — 띄엄띄엄 넘은 것을 연속으로 세지 않는다",
      "run_hits = 0" in _ws and "끊기면 처음부터다" in _ws)
check("한 창만 넘고 안 깬 경우도 로그에 남는다 (조건이 센지 판단하려면 필요하다)",
      "아직" in _ws)


# ═══ ③ 판정 논리 — 실제로 걸러지는가 ══════════════════════════════
#
# 🔑 **모델도 마이크도 없이** 판정만 떼어 본다. `scripts/sim_consecutive.py` 의
#   `fire_times` 가 런타임과 같은 규칙을 구현하고, 측정이 그걸로 나왔다.
print("\n=== ③ 판정 논리 ===")
from scripts.sim_consecutive import fire_times                  # noqa: E402

GATE, CD = 0.0015, 2.5


def frames(probs, dt=0.6, energy=0.01):
    return [(i * dt, energy, p) for i, p in enumerate(probs)]


check("연속 1 — 한 창만 넘어도 깬다",
      len(fire_times(frames([0.9]), 0.8, 1, CD, GATE)) == 1)
check("🚨 연속 2 — **한 창만 넘으면 안 깬다**",
      len(fire_times(frames([0.9, 0.1]), 0.8, 2, CD, GATE)) == 0)
check("연속 2 — 두 창 연속이면 깬다",
      len(fire_times(frames([0.9, 0.9]), 0.8, 2, CD, GATE)) == 1)
check("🚨 연속 2 — **끊긴 두 번은 안 깬다** (0.9 / 0.1 / 0.9)",
      len(fire_times(frames([0.9, 0.1, 0.9]), 0.8, 2, CD, GATE)) == 0)
check("연속 3 — 두 번으로는 모자라고 세 번이면 깬다",
      len(fire_times(frames([0.9, 0.9]), 0.8, 3, CD, GATE)) == 0
      and len(fire_times(frames([0.9, 0.9, 0.9]), 0.8, 3, CD, GATE)) == 1)
check("🔑 **에너지 관문에 막힌 창은 연속을 끊는다** (런타임이 모델에 안 넣으므로)",
      len(fire_times([(0.0, 0.01, 0.9), (0.6, 0.0001, 0.9), (1.2, 0.01, 0.9)],
                     0.8, 2, CD, GATE)) == 0)
check("🔑 **확률이 없는 창(관문에 막힘)도 연속을 끊는다**",
      len(fire_times([(0.0, 0.01, 0.9), (0.6, 0.01, None), (1.2, 0.01, 0.9)],
                     0.8, 2, CD, GATE)) == 0)
# 🚨 처음에 «8창 = 1회»로 적었는데 **틀렸다.** 8창 × 0.6초 = 4.2초라 쿨다운 2.5초
#   안에 두 번 깨는 것이 맞다. 횟수를 박지 말고 **간격을 본다** — 그게 쿨다운의 뜻이다.
_fires = fire_times(frames([0.9] * 20), 0.8, 2, CD, GATE)
check("쿨다운이 그대로 걸린다 — 깬 간격이 모두 쿨다운 이상이다",
      len(_fires) >= 2 and all(b - a >= CD for a, b in zip(_fires, _fires[1:])),
      f"→ {[round(t,1) for t in _fires]}")
check("🔑 연속 조건이 쿨다운을 **더 느슨하게 만들지 않는다** "
      "(연속 1 일 때보다 많이 깨면 안 된다)",
      len(_fires) <= len(fire_times(frames([0.9] * 20), 0.8, 1, CD, GATE)))


# ═══ ④ 쓰던 모델이 바뀌었다 ═══════════════════════════════════════
print("\n=== ④ 모델 ===")
check("런타임 모델이 있다", os.path.exists(os.path.join(ROOT, "services", "wakeword_model.npz")))
check("🔒 **되돌릴 수 있다** — 직전 모델을 백업해 뒀다",
      os.path.exists(os.path.join(ROOT, "services", "wakeword_model_2026-09-28.npz.bak")))

_train = _src("scripts/train_wakeword.py")
check("학습 창 기준이 **양성과 음성으로 갈려 있다**",
      "LOUD_RMS_POS" in _train and "LOUD_RMS_NEG" in _train)
check("🔑 음성 기준이 런타임 에너지 관문과 **같다** (0.0015)",
      "LOUD_RMS_NEG = 0.0015" in _train)
check("🚨 양성은 안 내린다는 근거가 적혀 있다 (무음을 호출로 배운다)",
      "무음을 호출로 배운다" in _train)


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
