# -*- coding: utf-8 -*-
"""**작업 진행판이 낡을 수 없게** 한다 — 생성물 ↔ 원본 대조

실행: python tests/test_board.py

## 왜 이 테스트가 생겼나

보드(여러 문서의 요약을 한 장에 모은 것)는 **이 저장소가 가장 자주 데인 모양**이다 —
한 사실이 두 곳에 있으면 한쪽만 갱신된다:

    2026-09-12  BL-35 요약이 «미해결»인 채로 상세 절만 갱신돼 있었다
    2026-09-17  CLAUDE.md 의 «48파일 1718» 이 낡은 채 발견됐다 (실제 49/1738)
    2026-09-18  같은 합계가 **네 문서에 박혀 있다가 하루에 넷이 동시에 어긋났다**
    2026-10-02  어필 재료에 «놓침 약 80%» 가 남아 있었다 — 실제 15.2%, **다섯 배**

🚨 **네 번 다 «다음엔 잘 갱신하자»로는 못 막혔다.** 그래서 보드를 **손으로 쓰지 않고**
`scripts/build_board.py` 가 원본에서 만들게 했고, 여기서 **어긋났는지를 센다.**

🔑 **생성이 결정적이라 바이트로 셀 수 있다**(시각·난수를 안 넣는다).
원본을 고치고 보드를 다시 안 만들면 **이 줄이 깨진다** — 낡을 수가 없다.

## 여기서 고정하는 것

| | 왜 |
|---|---|
| 커밋된 보드 == 지금 원본 | 이게 전부다. 어긋나면 깨진다 |
| 🚨 표시를 못 찾으면 **죽는다** | 빈 칸이 난 보드는 «할 일이 없다»로 읽혀 **낡은 것보다 나쁘다** |
| 숫자가 **README 상태표에서 온다** | 합계의 유일한 출처다. 스크립트에 숫자를 적으면 그게 복사본이다 |
| 해결된 결함은 **안 담는다** | ✅ 줄까지 담으면 «남은 것»이 아니라 목록이 된다 |
"""
import _testenv  # noqa: F401
import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import build_board as B  # noqa: E402

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


def run():
    print("=== ① 🚨 커밋된 보드가 **지금 원본과 같은가** ===")
    # 🔑 이 한 줄이 이 파일의 존재 이유다. 원본을 고치고 보드를 다시 안 만들면 깨진다.
    built = B.build()
    exists = os.path.exists(B.OUT)
    check("보드 파일이 있다", exists, B.OUT)
    if exists:
        cur = io.open(B.OUT, encoding="utf-8").read()
        check("🚨 보드가 낡지 않았다 (`python scripts/build_board.py` 로 다시 만드세요)",
              cur == built,
              f"→ 길이 {len(cur)} vs {len(built)}")

    print("")
    print("=== ② 🚨 표시를 못 찾으면 **조용히 비우지 않고 죽는다** ===")
    # 빈 칸이 난 보드는 «할 일이 없다»로 읽힌다 — 낡은 것보다 나쁘다.
    def dies(fn, text, label):
        try:
            fn(text)
        except B.Missing:
            return True
        except Exception:
            return False
        return False

    check("TASKS 의 「지금 하는 중」이 없으면 죽는다",
          dies(B.now_block, "# 아무것도 없다", "tasks"))
    check("🚩 블록의 끝 표시가 없으면 죽는다",
          dies(B.now_block, "## 🔵 지금 하는 중\n> # 🚩 시작만 있고 끝이 없다", "tasks"))
    check("README 에 합계가 없으면 죽는다", dies(B.numbers, "| 테스트 | 많음 |", "readme"))
    check("BACKLOG 에 미해결 줄이 없으면 죽는다",
          dies(B.open_defects, "**✅ BL-01 — 해결됨.**", "backlog"))
    check("CLAUDE 에 절대 규칙이 없으면 죽는다", dies(B.hard_rules, "# 아무것도", "claude"))
    check("CLAUDE 에 실행 블록이 없으면 죽는다", dies(B.how_to_run, "# 아무것도", "claude"))

    print("")
    print("=== ③ 숫자가 **README 상태표에서 온다** (스크립트에 안 적혀 있다) ===")
    readme = B.read("docs", "README.md")
    nums = B.numbers(readme)
    check("mock 합계와 도구 수를 가져온다", len(nums) == 2, str(nums))
    src = io.open(os.path.join(_ROOT, "scripts", "build_board.py"),
                  encoding="utf-8").read()
    # 🚨 스크립트에 합계를 적으면 **그 순간 복사본이 하나 더 생긴다.**
    #    이 저장소가 네 번 데인 자리라 코드로 막는다.
    body = src[src.index("def read("):]          # 윗부분은 사고 기록(숫자가 나온다)
    check("🚨 스크립트 **본문에 합계가 하드코딩돼 있지 않다**",
          "3295" not in body and "83파일" not in body,
          "적는 순간 복사본이 하나 더 생긴다")

    print("")
    print("=== ④ «남은 결함»에 **해결된 것이 안 들어간다** ===")
    backlog = B.read("docs", "BACKLOG.md")
    defects = B.open_defects(backlog)
    check("미해결만 담는다 (✅ 는 안 담는다)",
          all(m in ("🔴", "🟡", "🔵") for m, _, _ in defects),
          str({m for m, _, _ in defects}))
    check("번호가 전부 BL-숫자다", all(n.startswith("BL-") for _, n, _ in defects))
    check("하나 이상 있다", len(defects) >= 1, f"→ {len(defects)}개")

    print("")
    print("=== ⑤ 보드가 **읽을 수 있는 한 장**인가 ===")
    html = built
    for part in ("작업 진행판", "지금 하는 중", "남은 결함", "절대 규칙", "돌리는 법"):
        check(f"«{part}» 칸이 있다", part in html)
    check("⚠️ 손으로 고치지 말라고 적혀 있다", "손으로 고치지 마세요" in html)
    check("어디서 왔는지 적혀 있다 (출처를 숨기지 않는다)",
          "docs/TASKS.md" in html and "docs/README.md" in html)
    check("🚨 Git Bash 경고가 들어 있다 (거짓 실패로 하루를 잃지 않게)",
          "Git Bash" in html)
    # 🔑 생성이 결정적이어야 ①이 성립한다 — 시각이 들어가면 매번 달라진다.
    check("🔑 생성이 **결정적이다** (두 번 만들면 같다)", B.build() == built)

    print("")
    print(f"결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
