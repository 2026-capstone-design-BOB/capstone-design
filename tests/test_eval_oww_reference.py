# -*- coding: utf-8 -*-
"""공식 모델 대조 도구(`scripts/eval_oww_reference.py`)의 계약을 고정한다.

## 이 도구는 **약한 자**다. 그래서 «약하다는 말»이 코드에 붙어 있어야 한다

FRR 을 못 재고(우리 녹음에서 «헤이 자비스»라고 부른 사람이 없다) 언어도 다르다.
그런데 표는 **깔끔하게 나온다** — 공식 모델 0.0, 우리 74.7. 이대로 슬라이드에 가면
«상용급 모델은 0인데 우리는 74»가 되고, **그건 이 측정이 말한 것이 아니다.**

그래서 여기서 세는 것은 숫자가 아니라 **말**이다:
① 격자를 우리 것에 맞췄는가(안 맞추면 공식 모델이 7.5배 많은 기회를 갖는다)
② 자(쿨다운·재생)를 하네스에서 가져오는가
③ **못 말하는 것**을 도구가 직접 적는가
"""
import io
import os
import re
import sys
import types

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


_src = io.open(os.path.join(_ROOT, "scripts", "eval_oww_reference.py"), encoding="utf-8").read()
_rt = io.open(os.path.join(_ROOT, "services", "wakeword.py"), encoding="utf-8").read()

# 런타임 값은 **소스에서** 읽는다 (여기 베껴 적으면 이 테스트가 거짓말을 한다)
HOP = float(re.search(r"^HOP_SECONDS\s*=\s*([0-9.]+)", _rt, re.M).group(1))
SR = int(re.search(r"^SAMPLE_RATE\s*=\s*([0-9]+)", _rt, re.M).group(1))

# ── 순수 구간(scan_reference)만 떼어내 실행한다 ────────────────────
import numpy as _np                                          # noqa: E402

S = types.ModuleType("owwref_pure")
S.np, S.os, S.sys = _np, os, sys
S.HOP_SECONDS, S.SAMPLE_RATE = HOP, SR
S.OWW_CHUNK = int(re.search(r"^OWW_CHUNK\s*=\s*([0-9]+)", _src, re.M).group(1))
exec(compile(_src[_src.index("def _die("):_src.index("def main(")],
             "owwref_pure", "exec"), S.__dict__)


class FakeOww:
    """80ms 프레임마다 미리 정한 점수를 돌려주는 가짜 공식 모델."""

    def __init__(self, scores):
        self.scores = list(scores)
        self.models = {"fake_v0.1": object()}
        self.seen = 0

    def predict(self, chunk):
        v = self.scores[self.seen] if self.seen < len(self.scores) else 0.0
        self.seen += 1
        return {"fake_v0.1": v}


def run():
    print("=== ① 🚨 격자를 우리 것에 맞추는가 ===")
    per_hop = max(1, int(round(HOP * SR / S.OWW_CHUNK)))
    check(f"칸당 프레임 수를 런타임 홉에서 계산한다 ({HOP}s → {per_hop}칸)",
          per_hop == 8 and "HOP_SECONDS * SAMPLE_RATE / OWW_CHUNK" in _src)
    check("🚨 홉을 스크립트에 베껴 적지 않았다",
          not re.search(r"HOP_SECONDS\s*=\s*[0-9]", _src))
    check("⚠️ 안 나눠떨어진다는 것과 **어느 쪽으로 기우는지**를 적어 뒀다",
          "7.5" in _src and "유리한 쪽" in _src)

    print("=== ② 칸의 «최댓값»을 쓰고, 시각은 칸의 오른쪽 끝인가 ===")
    # 평균을 쓰면 짧은 봉우리가 묻혀 오탐이 실제보다 적게 나온다.
    scores = [0.1] * per_hop + [0.0] * (per_hop - 1) + [0.9]
    fake = FakeOww(scores)
    sys.modules["openwakeword.model"] = types.SimpleNamespace(Model=lambda **kw: fake)
    try:
        audio = _np.zeros(S.OWW_CHUNK * len(scores), dtype=_np.float32)
        frames, key = S.scan_reference("ignored", audio)
    finally:
        del sys.modules["openwakeword.model"]
    check("칸 수가 맞는다", len(frames) == 2, f"(실제 {len(frames)})")
    check("첫 칸은 최댓값 0.1", abs(frames[0][2] - 0.1) < 1e-6)
    check("🔑 둘째 칸은 **최댓값 0.9**다 (평균이 아니다)", abs(frames[1][2] - 0.9) < 1e-6)
    check("시각이 칸의 오른쪽 끝이다",
          abs(frames[0][0] - per_hop * S.OWW_CHUNK / SR) < 1e-9)
    check("⚠️ 에너지는 1.0 — 남의 모델에 우리 관문을 안 씌운다",
          frames[0][1] == 1.0 and "에너지 관문은 **우리 런타임의 장치**" in _src)

    print("=== ③ 🔒 자를 하네스에서 가져오는가 ===")
    imported = re.search(r"from scripts\.eval_wakeword import \(([^)]+)\)", _src)
    names = set(re.findall(r"[A-Za-z_]+", imported.group(1))) if imported else set()
    for fn in ("replay", "scan", "read_wav", "KwsModel", "kws_threshold"):
        check(f"{fn} 를 하네스에서 가져온다", fn in names)
    check("🚨 제 채점기를 새로 정의하지 않았다",
          not re.search(r"^def (replay|score|scan)\(", _src, re.M))

    print("=== ④ 🚨 «못 말하는 것»을 도구가 직접 적는가 ===")
    # 표는 깔끔하게 나온다. 그대로 인용되면 이 측정이 말하지 않은 것이 말해진다.
    check("FRR 을 못 잰다고 **출력에** 적는다", "FRR 은 못 잰다" in _src)
    check("언어가 다르다는 것을 출력에 적는다", "언어가 다르다는 것이 섞여 있다" in _src)
    check("«우리도 갈 수 있다»의 증거로 쓰지 말라고 적는다",
          "증거로 쓰지 않는다" in _src)
    check("«공식이 우리보다 낫다»고 말하지 말라고 적는다",
          "한쪽만 보고 낫다고 하지 않는다" in _src)
    check("🔑 상한선이 아니라 «바닥»이라고 적어 뒀다", "상한선이 아니라" in _src)

    print("=== ⑤ 결과가 어느 쪽이든 «무엇이 참인가»를 다르게 말하는가 ===")
    # 한쪽 결말만 적어 두면, 반대 결과가 나왔을 때 도구가 침묵한다.
    check("공식도 높게 나오는 경우의 해석이 있다", "이 오디오가 가혹하다" in _src)
    check("공식이 낮게 나오는 경우의 해석이 있다", "낮게 나온다" in _src)
    check("전자라면 **목표 자체를 다시 보라**고 말한다", "소크 2회차" in _src)

    print("=== ⑥ ⚠️ 건너뛰지 않는다 ===")
    check("openwakeword 가 없으면 죽는다", "openwakeword 가 없다" in _src)
    check("없는 공식 모델 이름을 부르면 **있는 것 목록**을 보여 준다",
          "있는 것:" in _src)
    check("--soak 이 필수다 (이 도구는 오탐만 잰다)", 'required=True' in _src)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
