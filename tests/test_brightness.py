"""밝기 조절 — **읽을 수 없는 PC에서도 상대 조절이 되는가** (mock)
실행: python tests/test_brightness.py

## 왜 이 파일이 생겼나

**2026-09-11 3차 실기 — 사용자 지적:**
*"밝기 조절은 세기가 되게 확확 바뀌어서 조금 불편해."*

이 PC에서 `_get_brightness()`가 **-1**(WMI 읽기 실패)이다. 외부 모니터·데스크톱에서
흔하다. 그런데 예전 코드는 읽기에 실패하면 **상대 조절을 포기하고 절대값으로 점프**했다:

    brightness_up   → _set_brightness(70)   "✓ 밝기를 올렸습니다."
    brightness_down → _set_brightness(30)   "✓ 밝기를 내렸습니다."

즉 «올려/내려»를 번갈아 하면 **70 ↔ 30을 왕복**한다 — **한 번에 40%**다.
사용자가 본 응답에 **퍼센트가 없었던 것**이 이 경로였다는 증거다
(읽기가 됐다면 `✓ 밝기: 50% → 60%`가 나왔다).

## 이 파일이 지키는 것

  ① 읽기가 **안 되는** PC에서도 **10%씩** 움직인다 (40% 점프가 아니다)
  ② 읽기가 **되는** PC의 동작은 그대로다 (회귀)
  ③ 0%·100%에서 멈추고, **멈췄다고 말한다** (조용히 «올렸어요»라고 하지 않는다)

⚠️ **실제 밝기를 바꾸지 않는다.** `_get_brightness`/`_set_brightness`를 갈아 끼워
  **판정 논리만** 본다 — 테스트가 사용자 화면을 어둡게 만들면 안 된다.
"""
import _testenv  # noqa: F401
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.system as S

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


class _Fake:
    """`_get_brightness`/`_set_brightness`를 갈아 끼운다. 실제 화면은 안 건드린다."""

    def __init__(self, readable: "int | None"):
        self.readable = readable          # None이면 «읽을 수 없는 PC»
        self.written: list = []

    def __enter__(self):
        self._g, self._s = S._get_brightness, S._set_brightness
        self._last = S._last_brightness
        S._last_brightness = None
        S._get_brightness = lambda: (self.readable if self.readable is not None else -1)
        def _set(level):
            level = max(0, min(100, level))
            self.written.append(level)
            S._last_brightness = level
            if self.readable is not None:     # 읽히는 PC는 실제로 값이 따라간다
                self.readable = level
            # 🆕 2026-09-19 — `_set_brightness` 는 이제 **성공 여부를 돌려준다**
            #   (감사 G-11). 대역도 계약을 따라야 한다 — None 을 돌려주면
            #   제품 코드가 «설정 실패»로 읽는다. 실패 쪽은
            #   `tests/test_setting_truth.py` §4가 따로 본다.
            return True
        S._set_brightness = _set
        return self

    def __exit__(self, *a):
        S._get_brightness, S._set_brightness = self._g, self._s
        S._last_brightness = self._last


print("[1] 🚨 읽을 수 없는 PC — 40% 점프가 아니라 10%씩")

with _Fake(readable=None) as f:
    r1 = S.brightness_up.invoke({})
    r2 = S.brightness_up.invoke({})
    r3 = S.brightness_down.invoke({})
    check("첫 조절은 중앙값에서 출발한다 (50 → 60)", f.written[0] == 60, f"→ {f.written}")
    check("두 번째도 10%만 움직인다 (60 → 70)", f.written[1] == 70, f"→ {f.written}")
    check("반대로도 10%만 움직인다 (70 → 60)", f.written[2] == 60, f"→ {f.written}")
    check("🚩 원문 재현: 70 ↔ 30 왕복이 없다",
          30 not in f.written and set(f.written) == {60, 70},
          f"→ {f.written}")
    check("퍼센트를 말해 준다 (예전엔 '밝기를 올렸습니다'뿐이었다)",
          "60" in r1 and "%" in r1, f"→ {r1!r}")
    check("내릴 때도 퍼센트를 말한다", "%" in r3, f"→ {r3!r}")
    # 🆕 2026-09-19 (감사 G-11) — **여기서 화살표가 사라진 것은 의도다.**
    #   `✓ 밝기: 50% → 60%` 의 50% 는 «기억한 값», 60% 는 «시키려는 값»이라
    #   **둘 다 읽은 적이 없다.** 읽을 수 없는 PC에서 읽은 것처럼 말하는 것이
    #   G-11 의 본체였다. 퍼센트(체감 — BL-45가 요구한 것)는 그대로 남는다.
    check("🆕 못 읽는 PC에서는 «읽은 것처럼» 말하지 않는다",
          "→" not in r1 and "확인" in r1, f"→ {r1!r}")

with _Fake(readable=None) as f:
    # 🔑 기억이 이어지는가 — 이게 없으면 매번 중앙값에서 다시 출발한다.
    for _ in range(4):
        S.brightness_up.invoke({})
    check("여러 번 올리면 누적된다 (50 → 90)", f.written == [60, 70, 80, 90],
          f"→ {f.written}")


print("")
print("[2] 읽을 수 있는 PC — 동작이 그대로다 (회귀)")

with _Fake(readable=55) as f:
    r = S.brightness_up.invoke({})
    check("실제값에서 출발한다 (55 → 65)", f.written == [65], f"→ {f.written}")
    check("실제값을 응답에 쓴다", "55" in r and "65" in r, f"→ {r!r}")

with _Fake(readable=55) as f:
    S.brightness_down.invoke({})
    check("내릴 때도 실제값 기준 (55 → 45)", f.written == [45], f"→ {f.written}")

with _Fake(readable=40) as f:
    S.brightness_up.invoke({"amount": 25})
    check("amount를 주면 그만큼 (40 → 65)", f.written == [65], f"→ {f.written}")


print("")
print("[3] 상·하한에서 멈추고 **멈췄다고 말한다**")

with _Fake(readable=100) as f:
    r = S.brightness_up.invoke({})
    check("100%에서 더 올리지 않는다", f.written == [], f"→ {f.written}")
    check("🚨 «올렸어요»라고 하지 않는다 — 안 한 걸 했다고 말하면 BL-12 계열이다",
          "⚠️" in r and "밝" in r, f"→ {r!r}")

with _Fake(readable=0) as f:
    r = S.brightness_down.invoke({})
    check("0%에서 더 내리지 않는다", f.written == [], f"→ {f.written}")
    check("«내렸어요»라고 하지 않는다", "⚠️" in r, f"→ {r!r}")

with _Fake(readable=95) as f:
    S.brightness_up.invoke({})
    check("상한을 넘지 않게 자른다 (95 → 100)", f.written == [100], f"→ {f.written}")


print("")
print("=" * 60)
print(f"결과: {passed}/{total} 통과")
print("=" * 60)
sys.exit(0 if passed == total else 1)
