# -*- coding: utf-8 -*-
"""평가 문장의 계약 — **도구를 늘리면서 자를 안 늘리면 여기서 깨진다** (BL-71)

실행: python tests/test_tool_eval_cases.py

## 왜 이 테스트가 있나 — 같은 빚을 **세 번** 졌다

| 언제 | 도구 | 평가 문장 | 그때 적은 말 |
|---|---|---|---|
| 2026-09-24 (1) | 47 → 58 | 안 늘림 | 📏 *"다음엔 평가 문장부터 늘린다"* |
| 2026-09-24 (2) | 58 → 62 | 안 늘림 | 📏 같은 말을 또 적음 |
| 2026-09-25 | 62 → 67 | 안 늘림 | 📏 *"다음 세션의 첫 항목"* |

세 번 다 **적어서** 막으려 했고 세 번 다 안 됐다. 이 저장소가 이미 아는 교훈이
그것이다 — **프롬프트(와 메모)는 확률을 올릴 뿐이고 보장하는 건 구조다.**

🔑 그래서 이번엔 말 대신 **자**를 뒀다. ①이 그 자다: `get_all_tools()` 에 이름이
하나 늘면 `scripts/tool_eval_cases.py` 에 문장이 없어서 **이 테스트가 깨진다.**
(`test_worker.py` [21]이 문서의 도구 개수에 대해 한 것과 같은 방식이다.)

## 🚨 여기서 LLM 을 부르지 않는다

이 파일은 **표가 성립하는가**만 본다. 실제로 «그 발화가 그 도구를 부르나»는
`scripts/eval_tool_selection.py` 가 모델을 불러서 재고, 그건 mock 스위트에
안 들어간다(키·돈·비결정성). 둘은 **다른 물건**이다 —
자의 눈금이 맞는지 보는 것과, 그 자로 재 보는 것.
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
import io
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from core.tool_registry import get_all_tools  # noqa: E402
from tool_eval_cases import (  # noqa: E402
    ALL_CASES, MULTI_CASES, NEW_2026_09, covered_tools,
)

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


def _src_of(rel):
    return io.open(os.path.join(_ROOT, rel), encoding="utf-8").read()


NL = ""
TOOL_NAMES = {t.name for t in get_all_tools()}
COVERED = covered_tools()


# ── ① 자 본체 ─────────────────────────────────────────────────────
print("\n[①] 📏 모든 도구에 평가 문장이 있다 — **도구를 늘리면 여기가 깨진다**")

_missing = sorted(TOOL_NAMES - COVERED)
check("문장 없는 도구가 하나도 없다",
      not _missing,
      f"\n        → 문장 없는 도구 {len(_missing)}개: {', '.join(_missing)}"
      f"\n        → scripts/tool_eval_cases.py 에 한 줄씩 더하세요.")

_ghost = sorted(COVERED - TOOL_NAMES)
check("없는 도구를 가리키는 문장이 없다 (오타는 조용히 «안 덮인 도구»를 만든다)",
      not _ghost, f"실재하지 않는 이름: {', '.join(_ghost)}")

check("도구 개수와 덮인 개수가 같다",
      len(TOOL_NAMES) == len(COVERED),
      f"도구 {len(TOOL_NAMES)} · 덮임 {len(COVERED)}")

_texts = [c.text for c in ALL_CASES]
_dup = sorted({t for t in _texts if _texts.count(t) > 1})
check("같은 문장이 두 번 들어 있지 않다 (분모가 조용히 부푼다)",
      not _dup, f"중복: {_dup}")

check("문장이 다 비어 있지 않다", all(c.text.strip() for c in ALL_CASES))
check("갈래 이름이 다 채워져 있다", all(c.group.strip() for c in ALL_CASES))


# ── ② «안 부르기»도 분모에 있다 ──────────────────────────────────
print(f"{NL}\n[②] 🚫 «아무 도구도 안 부르는 것»이 정답인 자리가 있다")

_zero = [c for c in ALL_CASES if not c.expect]
check("expect 가 빈 케이스가 있다 (잡담에 도구를 부르면 그게 결함이다)",
      len(_zero) >= 2, f"{len(_zero)}건")
check("그 중 «되묻기» 갈래가 따로 있다",
      any("되묻기" in c.group for c in _zero))

# 🔑 **«되묻는 것이 정답»이라는 판정을 코드로 확인한다.**
#   2026-09-28 첫 측정에서 셋이 «틀림»으로 나왔는데, 보니 모델이 되묻고 있었고
#   **틀린 것은 내 문장이었다** — 도구가 required 로 받는 값을 발화가 안 담고 있었다.
#   그러면 도구를 부르는 쪽이 오히려 **값을 지어낸 것**이다(BL-61).
#   🚨 나중에 그 인자가 optional 로 바뀌면 이 판정이 낡는다. 그때 여기가 깨진다.
_schema = {t.name: t.args_schema.model_json_schema() for t in get_all_tools()}
check("remind_me 가 what 을 required 로 받는다 — 없이 부르면 지어낸 것이다",
      "what" in _schema["remind_me"].get("required", []))
check("write_excel 이 headers·rows 를 required 로 받는다 — 같은 이유",
      {"headers", "rows"} <= set(_schema["write_excel"].get("required", [])))

# ✅ **2026-09-30 에 셋이 다 막혔다.** 아래 기록은 남긴다 — 왜 required 여야 하는지가
#   여기 적혀 있고, 되돌리면 이 테스트가 깨진다.
# (원래 기록) `overwrite_file.content` 는 기본값이 ""
#   이라 내용 없이 불리면 **파일이 비워진다**(옛 내용은 휴지통). 2026-09-28 측정에서
#   모델이 스스로 되물었지만 그건 **선의**지 보장이 아니다 → BL-76.
#   이 줄은 «지금 상태»를 적어 둔 것이다. 고치면(required 로 바꾸면) 여기가 깨지고,
#   그때는 **더 좋아진 것**이므로 위 두 줄 옆으로 옮기면 된다.
check("✅ overwrite_file.content 도 required 다 (BL-76 · 2026-09-30 닫힘)",
      "content" in _schema["overwrite_file"].get("required", []))


# ── ③ 새 도구 20개 — 이번에 갚은 빚 ──────────────────────────────
print(f"{NL}\n[③] 🆕 2026-09-24~25 에 들어온 도구 20개")

check("스무 개다", len(NEW_2026_09) == 20, f"{len(NEW_2026_09)}개")
check("전부 실재하는 도구다", NEW_2026_09 <= TOOL_NAMES,
      f"없는 이름: {sorted(NEW_2026_09 - TOOL_NAMES)}")
check("전부 평가 문장이 있다", NEW_2026_09 <= COVERED,
      f"빠진 것: {sorted(NEW_2026_09 - COVERED)}")


# ── ④ 🔒 멀티 API 20문장은 얼어 있다 ─────────────────────────────
print(f"{NL}\n[④] 🔒 멀티 API 표의 20문장 — **순서가 계약이다**")

# 🚨 `docs/research/2026-09_멀티API.json` 은 결과를 **인덱스로** 맞춰 놓는다
#   (`results[p]["rows"][i]` ↔ `CASES[i]`). 한 줄만 끼워 넣어도 **옛 gemini 열이
#   통째로 어긋난다** — 키가 나중에 생길 provider 를 위해 남겨 둔 열이다.
check("스무 문장이다", len(MULTI_CASES) == 20, f"{len(MULTI_CASES)}문장")
check("3-튜플이다 (multi_api_equivalence 가 그렇게 푼다)",
      all(len(c) == 3 for c in MULTI_CASES))

_json_path = os.path.join(_ROOT, "docs", "research", "2026-09_멀티API.json")
if os.path.exists(_json_path):
    _saved = json.load(io.open(_json_path, encoding="utf-8")).get("cases", [])
    check("저장된 결과의 문장·순서와 **글자까지** 같다",
          _saved == [c[0] for c in MULTI_CASES],
          "\n        → 순서가 바뀌면 옛 측정 결과가 엉뚱한 문장에 붙는다.")
else:
    check("저장된 결과가 아직 없다 (건너뜀)", True)

check("첫 줄이 «메모장 켜 줘» 다", MULTI_CASES[0][0] == "메모장 켜 줘")
check("마지막 줄이 잡담이다 (도구 없음이 정답)", MULTI_CASES[-1][1] == "")


# ── ⑤ 표가 **한 곳**에만 있다 ────────────────────────────────────
print(f"{NL}\n[⑤] 표를 복제하지 않았다 — «한 사실은 한 문서에만»")

_multi_src = _src_of("scripts/multi_api_equivalence.py")
check("multi_api_equivalence 가 표를 import 한다",
      "from tool_eval_cases import MULTI_CASES as CASES" in _multi_src)
check("   자기 안에 문장 목록을 다시 갖고 있지 않다",
      '("메모장 켜 줘",' not in _multi_src)

_sel_src = _src_of("scripts/eval_tool_selection.py")
check("eval_tool_selection 도 같은 표를 import 한다",
      "from tool_eval_cases import" in _sel_src)


# ── ⑥ 🚨 측정기가 아무것도 실행하지 않는다 ───────────────────────
print(f"{NL}\n[⑥] 🚨 평가셋에 승인 대상이 들어 있다 — **실행하면 안 된다**")

from core.graph import DANGEROUS_TOOLS  # noqa: E402

_danger_in_set = sorted(COVERED & set(DANGEROUS_TOOLS))
check("평가셋이 승인 대상 도구도 덮는다 (거기가 제일 안 재진 자리다)",
      len(_danger_in_set) >= 5, f"{_danger_in_set}")

# 🔑 측정기는 `bind_tools(...).invoke(...)` 의 **tool_calls 만 읽는다.**
#   도구 함수를 부르는 코드가 없어야 파일이 안 지워진다.
check("측정기가 도구를 실행하지 않는다고 적어 뒀다",
      "실행하지 않는다" in _sel_src or "실행 없음" in _sel_src)
check("   ToolNode·invoke 로 도구를 부르는 코드가 없다",
      "ToolNode" not in _sel_src and ".run(" not in _sel_src)
check("   측정기를 복제하지 않고 _ask 를 가져다 쓴다 (실행 안 함이 한 곳이다)",
      "from multi_api_equivalence import" in _sel_src and "_ask" in _sel_src)


# ── ⑦ 도구를 안 불렀을 때 **뭐라고 했는지** 남는다 ───────────────
print(f"{NL}\n[⑦] «(없음)» 에는 성질이 다른 둘이 섞여 있다")

# 되묻는 것(옳다)과 안 했는데 했다고 하는 것(BL-12·15·61)이 표에서 똑같이 보이면
# 자가 **진짜 결함과 내 라벨 실수를 구별하지 못한다.** 2026-09-28 에 실제로 그랬다.
check("측정기가 모델이 말한 글까지 남긴다(say)", '"say"' in _multi_src)
check("   보고서가 도구 없음일 때 그 글을 보여준다", "말한 것" in _sel_src)


# ── ⑧ 부분 측정이 전체 결과를 덮지 않는다 ───────────────────────
print(f"{NL}\n[⑧] --new 로 20문장만 재도 «전체를 쟀다»가 되지 않는다")

check("부분 측정은 다른 칸에 저장한다",
      '"results_new"' in _sel_src)
check("   왜 나누는지 적혀 있다", "덮어쓰면" in _sel_src)


print(f"{NL}\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
