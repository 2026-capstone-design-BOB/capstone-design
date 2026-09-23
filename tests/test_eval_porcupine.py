# -*- coding: utf-8 -*-
"""상용 대조 도구(`scripts/eval_porcupine.py`)의 계약을 고정한다.

## 여기서 지키는 것은 «숫자»가 아니라 «자가 안 기우는가»다

Porcupine 은 확률을 안 주고 스트리밍으로 «깼다»만 준다. 우리 모델은 2초 창마다
확률을 준다. **둘을 맞대려면 조건을 손으로 맞춰야 하는데, 그 맞춤이 한쪽에 유리하면
표는 멀쩡해 보이면서 틀린 답을 낸다.** 이 파일이 세는 것이 그 맞춤이다:

① 쿨다운을 **같은 함수**로 씌우는가 (우리만 2.5초를 먹으면 오탐이 우리 쪽만 준다)
② 채점·판정을 **베껴 적지 않고 import** 하는가 (자가 둘이 되면 도구마다 답이 다르다)
③ 민감도를 몇 개 주든 **결과가 안 바뀌는가** (한 번에 먹이는 최적화가 결과를 바꾸면
   «11칸으로 잰 표»와 «1칸으로 잰 표»가 다른 물건이 된다)
④ 의존성이 없을 때 **조용히 건너뛰지 않는가**

⚠️ `scripts/eval_porcupine.py` 는 최상위에서 `scripts/eval_wakeword.py` → `services/wakeword.py`
   를 import 하므로 그냥 import 하면 `openwakeword` 가 필요하다. 그래서
   `test_eval_wakeword.py` 와 **같은 방식**으로 순수 구간만 떼어내 실행한다.
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


_src = io.open(os.path.join(_ROOT, "scripts", "eval_porcupine.py"), encoding="utf-8").read()
_eval_src = io.open(os.path.join(_ROOT, "scripts", "eval_wakeword.py"), encoding="utf-8").read()

# ── 순수 구간만 떼어내 실행한다 ────────────────────────────────────
P = types.ModuleType("porc_pure")
P.SAMPLE_RATE = 16000
import time as _time                                         # noqa: E402
import numpy as _np                                          # noqa: E402
P.np, P.time = _np, _time
exec(compile(_src[_src.index("def fires_per_sensitivity("):_src.index("def porcupine_curve(")],
             "porc_pure", "exec"), P.__dict__)
# 🆕 재료 준비 구간(모델 받기 · 키워드 만들기)도 같은 방식으로 떼어낸다.
#    여기가 틀리면 **측정이 시작되기도 전에** 엉뚱한 파일로 돌게 된다.
R = types.ModuleType("porc_ready")
R.os, R.sys, R.NL = os, sys, NL
R.KO_URL = re.search(r'KO_URL = \("([^"]+)"' + NL + r'\s*"([^"]+)"\)', _src).group(1)
R.ROOT = _ROOT
exec(compile(_src[_src.index("def _die("):_src.index("def open_handles(")],
             "porc_ready", "exec"), R.__dict__)


# 쿨다운은 **하네스 것을 그대로** 가져온다 — 여기에 베껴 적으면 이 테스트가 거짓말을 한다
E = types.ModuleType("eval_pure")
E.COOLDOWN_SEC = float(re.search(r"^COOLDOWN_SEC\s*=\s*([0-9.]+)",
                                 io.open(os.path.join(_ROOT, "services", "wakeword.py"),
                                         encoding="utf-8").read(), re.M).group(1))
exec(compile(_eval_src[_eval_src.index("def replay("):_eval_src.index("# ── 출력")],
             "eval_pure", "exec"), E.__dict__)


class FakePorcupine:
    """정해진 프레임 번호에서만 깨는 가짜 엔진. **민감도가 높을수록 더 깬다.**"""

    frame_length = 512

    def __init__(self, fire_frames):
        self.fire_frames = set(fire_frames)
        self.seen = 0
        self.frames = []

    def process(self, pcm):
        self.frames.append(tuple(pcm[:4]))       # 무엇을 봤는지 기록 (순서 비교용)
        self.seen += 1
        return 0 if (self.seen - 1) in self.fire_frames else -1


def _has_sdk():
    try:
        import importlib.metadata as md
        md.version("pvporcupine")
        return True
    except Exception:                                        # noqa: BLE001
        return False


def run():
    np = _np
    COOL = E.COOLDOWN_SEC

    print("=== ① 🚨 쿨다운을 «우리 모델과 같은 함수»로 씌우는가 ===")
    # 여기가 안 맞으면 표는 멀쩡해 보이면서 한쪽에 유리해진다.
    fires = [10.0, 10.0 + COOL / 2, 10.0 + COOL + 0.1]
    kept = E.replay(P.as_frames(fires), 0.5, 0.0)
    check("쿨다운 안의 두 번째 검출은 안 센다", kept == [10.0, 10.0 + COOL + 0.1])
    check("쿨다운 값을 스크립트에 베껴 적지 않았다",
          not re.search(r"COOLDOWN_SEC\s*=\s*[0-9]", _src))
    check("as_frames 는 확률 1.0 · 에너지 1.0 으로 둔다 (관문·임계가 안 끼어든다)",
          P.as_frames([1.0]) == [(1.0, 1.0, 1.0)])

    print("=== ② 🔒 채점·판정을 베껴 적지 않고 import 한다 ===")
    imported = re.search(r"from scripts\.eval_wakeword import \(([^)]+)\)", _src)
    names = set(re.findall(r"[A-Za-z_]+", imported.group(1))) if imported else set()
    for fn in ("score", "replay", "print_compare_table", "read_wav", "load_sessions", "_curve"):
        check(f"{fn} 를 하네스에서 가져온다", fn in names)
    check("🚨 스크립트 안에 제 채점기를 새로 정의하지 않았다",
          not re.search(r"^def (score|replay|_best_under)\(", _src, re.M))
    check("🚨 판정 문구도 제가 안 적는다 (print_compare_table 하나만 쓴다)",
          "곡선이 교차한다" not in _src and "되돌림 권고" not in _src)
    check("하네스 쪽에 공용 판정 함수가 실제로 있다",
          "def print_compare_table(" in _eval_src)
    # 문서(설명)에 한 번 더 나오는 것은 괜찮다. **실행되는 줄**이 둘이면 안 된다.
    check("🔑 판정을 내리는 줄이 하네스에 **한 벌만** 있다",
          _eval_src.count('print(f"  🔴 도달 가능한 가장 낮은 FA') == 1)

    print("=== ③ 🚨 민감도를 몇 개 주든 결과가 안 바뀌는가 ===")
    # 한 번에 먹이는 최적화가 결과를 바꾸면 «11칸 표»와 «1칸 표»가 다른 물건이 된다.
    audio = np.zeros(512 * 30, dtype=np.float32)
    plan = {0.2: [3, 9], 0.5: [3, 9, 17], 0.9: [1, 3, 9, 17, 25]}
    together = P.fires_per_sensitivity([FakePorcupine(f) for f in plan.values()], audio)
    apart = [P.fires_per_sensitivity([FakePorcupine(f)], audio)[0] for f in plan.values()]
    check("한꺼번에 먹인 것과 하나씩 돌린 것이 같다", together == apart)

    print("=== ④ 시각을 프레임 오른쪽 끝으로 찍는가 ===")
    # 런타임의 «지금»이 창의 오른쪽 끝이라 그쪽에 맞춘다. 왼쪽 끝으로 찍으면
    # 귀속 구간이 통째로 한 칸 밀린다 (기준선 문서 §1 의 채점 규칙과 같은 실수).
    one = P.fires_per_sensitivity([FakePorcupine([0, 4])], audio)[0]
    check("0번 프레임의 검출 시각 = 512/16000초",
          abs(one[0] - 512 / 16000) < 1e-9)
    check("4번 프레임의 검출 시각 = 5*512/16000초",
          abs(one[1] - 5 * 512 / 16000) < 1e-9)

    print("=== ⑤ 같은 프레임을 **모두**에게 먹이는가 ===")
    hs = [FakePorcupine([]), FakePorcupine([])]
    P.fires_per_sensitivity(hs, np.linspace(-0.5, 0.5, 512 * 10, dtype=np.float32))
    check("두 인스턴스가 완전히 같은 프레임 순서를 봤다", hs[0].frames == hs[1].frames)
    check("프레임 수가 오디오 길이에 맞는다", len(hs[0].frames) == 10)

    print("=== ⑥ ⚠️ 건너뛰지 않는다 ===")
    check("pvporcupine 이 없으면 죽는다 (조용히 통과가 아니다)",
          "pvporcupine 이 없다" in _src and "_die(" in _src)
    check("AccessKey 가 없으면 죽는다", "AccessKey 가 없다" in _src)
    check("한국어 모델(.pv)을 안 주면 «이 측정은 무효»라고 말한다",
          "영어 모델" in _src and "무효" in _src)
    check("🚨 requirements.txt 에 pvporcupine 을 넣지 않았다 (런타임 의존성이 아니다)",
          "pvporcupine" not in io.open(os.path.join(_ROOT, "requirements.txt"),
                                       encoding="utf-8").read())

    print("=== ⑧ 🆕 재료를 스스로 마련하되, 사람 몫은 분명히 말하는가 ===")
    import tempfile
    tmp = tempfile.mkdtemp()

    # 가짜 SDK — 망도 키도 안 쓴다. 우리가 보는 것은 «어떻게 부르는가»다.
    fake = types.ModuleType("pvporcupine")
    fake.calls = []
    fake.pv_get_platform = lambda: "windows"

    def _train(access_key, output_path, language, phrase):
        fake.calls.append((access_key, language, phrase))
        io.open(output_path, "w").write("ppn")
    fake.train_wake_word_from_phrase = _train
    sys.modules["pvporcupine"] = fake
    try:
        made = R.ensure_keyword("KEY", "플루이즈", tmp, "ko")
        check("키워드를 문구에서 만든다 (콘솔 UI 없이)", fake.calls == [("KEY", "ko", "플루이즈")])
        check("🔑 파일명이 언어·플랫폼을 말한다 (서버로 옮길 때 파일명이 먼저 답한다)",
              os.path.basename(made) == "플루이즈_ko_windows.ppn")
        again = R.ensure_keyword("", "플루이즈", tmp, "ko")
        check("이미 있으면 다시 안 만든다 (키 없이도 된다)",
              again == made and len(fake.calls) == 1)
        try:
            R.ensure_keyword("", "다른말", tmp, "ko")
            check("🚨 키가 없는데 만들어야 하면 죽는다", False)
        except SystemExit:
            check("🚨 키가 없는데 만들어야 하면 죽는다 (조용히 건너뛰지 않는다)", True)
    finally:
        del sys.modules["pvporcupine"]

    print("=== ⑨ 🚨 모델 파일과 SDK 의 판이 다르면 «먼저» 말하는가 ===")
    # 안 맞으면 Porcupine 은 «파일이 깨졌다» 쪽으로 말한다 — 엉뚱한 데를 파게 된다.
    def _pv(head):
        q = os.path.join(tmp, head + ".pv")
        io.open(q, "wb").write(head.encode())
        return q
    import importlib.metadata as _md
    sdk_major = _md.version("pvporcupine").split(".")[0] if _has_sdk() else None
    if sdk_major:
        R.check_params_version(_pv("porcupine" + sdk_major + ".0.0"))
        check(f"같은 판(major {sdk_major})이면 통과한다", True)
        other = "3" if sdk_major != "3" else "4"
        try:
            R.check_params_version(_pv("porcupine" + other + ".0.0"))
            check("🚨 다른 판이면 죽는다", False)
        except SystemExit:
            check("🚨 다른 판이면 죽는다 (오류가 나기 전에)", True)
    else:
        check("pvporcupine 이 없어 판 검사는 건너뛴다 (설치하면 돈다)", True)
    check("받다 만 파일을 «있다»로 두지 않는다 (.part 로 받고 옮긴다)",
          '".part"' in _src and "os.replace(tmp, path)" in _src)

    print("=== ⑦ 이 표로 하면 안 되는 말을 도구가 직접 적는가 ===")
    check("«채택 판단이 아니다»라고 말한다", "채택 판단이 아니다" in _src)
    check("라이선스가 먼저라고 말한다", "라이선스" in _src)
    check("«우리 모델이 형편없다»로 읽지 말라고 말한다", "데이터 규모" in _src)
    check("귀속 창이 우리 창 길이에서 왔다는 한계를 적어 뒀다",
          "조금" in _src and "후한" in _src)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
