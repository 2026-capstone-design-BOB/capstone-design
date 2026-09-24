# -*- coding: utf-8 -*-
"""화면 짚기 접근성 경로의 계약 — **빨라지려다 새 거짓말을 만들지 않는다** (10월 항목 A)

실행: python tests/test_uia_locate.py

## 왜 이 테스트가 있나

2026-09-24 측정에서 지금 방식(Vision)이 **12개 중 4개를 «틀린 자리에 정확히» 짚었다**
(오답률 33.3%) → [실측](../docs/research/2026-09_화면조작_성공률.md).
접근성 API 로 바꾸면 그게 0%가 되고 3.18초가 0.22초가 된다.

🚨 **그런데 바꾸면서 같은 병을 새로 만들 수 있다.** 사용자는 *"블루투스"* 라고 하는데
컨트롤 이름은 *"Bluetooth"* 거나 *"블루투스 켜기/끄기"* 다. 이름 맞추기를 느슨하게
하면 **찾는 비율은 오르지만 엉뚱한 컨트롤을 «정확한 좌표»로** 짚는다.

## 여기서 고정하는 것 여섯

1. 🚨 **같은 단계에서 후보가 둘 이상이면 포기한다.** 그리고 **다음 단계로도 안 간다** —
   완전일치가 둘이면 «포함»은 더 느슨해서 더 많이 걸린다. 느슨한 쪽으로 내려가
   하나를 고르는 것이 «지어내기»다.
2. 🚨 **못 찾으면 `None` 이지 `{"found": False}` 가 아니다.** 여기서 «없다»고 단정하면
   부르는 쪽이 Vision 을 안 부른다. UIA 는 그림·아이콘을 못 보므로
   «내가 못 찾았다»와 «화면에 없다»는 **다른 말**이다.
3. 🚨 **상한이 있다.** 폴백은 «있다»가 아니라 **«갈 수 있다»** 여야 한다 —
   [BL-69](../docs/BACKLOG.md) 가 정확히 그 자리였다(STT 가 안 돌아와 Whisper 로 못 갔다).
4. **크기가 0인 노드를 버린다.** 트리에 같은 이름의 숨은 노드가 있고, 그걸 쓰면
   `(0,0)` 이 답이 된다(2026-09-24 첫 측정에서 실제로 그랬다).
5. **끌 수 있다.** `PLUIZ_UIA=0` 이면 예전 경로만 쓴다 — 안 그러면 교체한 뒤에
   **«개선 전»을 다시 못 재고** 전/후 비교가 영영 불가능해진다.
6. **반환 모양이 Vision 과 같다.** 부르는 쪽이 둘을 구별하지 않아야
   `find_ui_element`·`click_ui_element` 가 한 경로를 쓴다는 계약이 유지된다.

## ⚠️ 여기서 실제 화면을 읽지 않는다

`uiautomation` 이 없어도 돈다. 순수 함수와 **소스의 계약**만 본다.
실제 트리 읽기는 `python scripts/eval_ui_ops.py --run` 이 한다.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)

import tools.uia_locate as U  # noqa: E402

_SRC = io.open(os.path.join(_ROOT, "tools", "uia_locate.py"), encoding="utf-8").read()
_VIS = io.open(os.path.join(_ROOT, "tools", "vision.py"), encoding="utf-8").read()

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")


def C(norm, name, rect=(10, 20, 110, 60)):
    return (norm, name, rect)


def run():
    print("=== ① 이름 정규화 ===")
    check("공백을 지운다", U._norm("블루투스 및 장치") == "블루투스및장치")
    check("소문자로 만든다", U._norm("Bluetooth") == "bluetooth")
    check("None 도 빈 문자열", U._norm(None) == "")

    print(f"{NL}=== ② 🚨 고르기 — 애매하면 포기한다 ===")
    one = [C("게임", "게임"), C("계정", "계정")]
    got = U._pick(one, "게임")
    check("완전일치가 하나면 고른다", got is not None and got[0] == "게임")
    check("   어느 단계로 골랐는지 같이 준다", got[2] == "완전일치")

    two = [C("게임", "게임"), C("게임", "게임 ")]
    check("🚨 완전일치가 둘이면 **포기한다**", U._pick(two, "게임") is None)
    check("🚨 그리고 «포함»으로 내려가서 하나를 고르지 **않는다**",
          U._pick(two + [C("게임설정", "게임 설정")], "게임") is None)

    pre = [C("블루투스및장치", "Bluetooth 및 장치"), C("계정", "계정")]
    got = U._pick(pre, "블루투스")
    # 반환은 (원본이름, 사각형, 단계) 순이다
    check("완전일치가 없으면 앞부분으로 내려간다",
          got is not None and got[0] == "Bluetooth 및 장치" and got[2] == "앞부분")

    inc = [C("설정에서블루투스켜기", "설정에서 블루투스 켜기")]
    got = U._pick(inc, "블루투스")
    check("그것도 없으면 «포함»까지 본다", got is not None and got[2] == "포함")

    check("아무것도 안 맞으면 None", U._pick(one, "없는것") is None)
    check("후보가 비어도 죽지 않는다", U._pick([], "게임") is None)

    print(f"{NL}=== ③ 🚨 «못 찾았다»와 «화면에 없다»를 섞지 않는다 ===")
    # 🚨 문자열 검사가 아니라 **실제 반환값**으로 본다 — docstring 에 «{"found": False}
    #   가 아니다» 라는 설명이 들어 있어서 소스 검색으로는 구별이 안 된다.
    check("🚨 못 찾으면 None 을 돌려준다 (found:False 가 아니다)",
          U.locate("있을리없는이름zzz", "없는창zzz") is None)
    check("   왜 그런지 코드 옆에 적혀 있다",
          "«내가 못 찾았다»와 «화면에 없다»는 **다른 말**" in _SRC)
    check("대체가 아니라 «먼저 시도»라고 못 박는다",
          "대체가 아니라" in _SRC and "먼저 시도" in _SRC)

    print(f"{NL}=== ④ 🚨 폴백이 «갈 수 있는» 길인가 (BL-69 의 교훈) ===")
    check("상한이 있다", isinstance(U.UIA_TIMEOUT, (int, float)) and U.UIA_TIMEOUT > 0)
    check("   그 상한이 실측(0.09s)보다 넉넉하다", 0.5 <= U.UIA_TIMEOUT <= 5)
    check("🚨 훑는 중에도 상한을 본다 (다 모은 뒤가 아니라)",
          "time.monotonic() > deadline" in _SRC and _SRC.count("deadline") >= 4)
    check("깊이 상한도 있다", U.MAX_DEPTH > 0 and "depth > MAX_DEPTH" in _SRC)
    check("후보 개수 상한도 있다", "len(out) > 600" in _SRC)
    check("BL-69 를 근거로 적어 뒀다", "BL-69" in _SRC)

    print(f"{NL}=== ⑤ 🚨 첫 측정에서 배운 것 둘 ===")
    check("🚨 크기가 0인 노드를 버린다 ((0,0) 이 답으로 나왔던 자리)",
          "r.right > r.left and r.bottom > r.top" in _SRC)
    check("   왜인지 적혀 있다 (같은 이름의 숨은 노드)", "숨은\n    #                   노드" in _SRC
          or "숨은" in _SRC)
    check("누를 수 있는 것만 본다 (텍스트 라벨을 짚어도 소용없다)",
          "CLICKABLE" in _SRC and "ButtonControl" in U.CLICKABLE)

    print(f"{NL}=== ⑥ 🚨 끌 수 있는가 — «개선 전»을 다시 잴 수 있어야 한다 ===")
    old = os.environ.get("PLUIZ_UIA")
    try:
        os.environ["PLUIZ_UIA"] = "0"
        check("PLUIZ_UIA=0 이면 꺼진다", not U.uia_enabled())
        check("   그리고 locate 가 바로 None 을 준다", U.locate("게임", "설정") is None)
        os.environ["PLUIZ_UIA"] = "1"
        check("PLUIZ_UIA=1 이면 켜진다", U.uia_enabled())
        del os.environ["PLUIZ_UIA"]
        check("기본은 켜짐", U.uia_enabled())
    finally:
        if old is None:
            os.environ.pop("PLUIZ_UIA", None)
        else:
            os.environ["PLUIZ_UIA"] = old
    check("왜 끌 수 있어야 하는지 적혀 있다", "개선 전" in _SRC and "다시 잴" in _SRC)

    print(f"{NL}=== ⑦ 창을 안 주면 전체를 훑지 않는다 ===")
    check("🚨 window 가 없으면 바로 Vision 으로",
          "창이 지정되지 않았다" in _SRC)
    check("   왜인지 적혀 있다 (사용자가 안 시킨 창을 들여다보는 셈)",
          "안 시킨 창" in _SRC)
    check("빈 target 도 바로 None", U.locate("", "설정") is None)

    print(f"{NL}=== ⑧ 🚨 vision.py 와의 접합 ===")
    check("UIA 를 **먼저** 부른다", "from tools.uia_locate import locate" in _VIS)
    check("🚨 못 찾으면 그대로 아래로 내려간다 (조기 return 이 _hit 있을 때만)",
          "if _hit:" in _VIS and "return _hit" in _VIS)
    check("🚨 UIA 가 터져도 Vision 이 돈다 (예외를 삼키고 계속)",
          "호출 자체가 실패" in _VIS)
    check("   조용히 삼키지 않는다 (로그를 남긴다)",
          "log.warning" in _VIS and "Vision 으로" in _VIS)
    check("🚨 want_crop·refine 이면 건너뛴다 (그 둘은 이미지가 있어야 성립한다)",
          "if not want_crop and not refine:" in _VIS)
    check("실측 근거를 접합부에 적어 뒀다",
          "화면조작_성공률" in _VIS and "33.3%" in _VIS)

    print(f"{NL}=== ⑨ 반환 모양이 Vision 과 같은가 ===")
    for k in ("found", "center", "rect", "size", "label", "window_rect"):
        check(f"   {k} 를 돌려준다", f'"{k}"' in _SRC)
    check("어느 경로로 왔는지 표시한다 (via)", '"via": "uia"' in _SRC)
    check("걸린 시간도 남긴다", '"sec"' in _SRC)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
