# -*- coding: utf-8 -*-
"""도구 결과 문자열의 «계약» — 실패를 실패로 읽는 **단 하나의 자리**.

→ ADR: `docs/design/BL-29_도구_결과_계약.md`

**왜 이 파일이 따로 있는가.**
도구가 반환하는 문자열의 접두사는 장식이 아니라 **코드가 파싱하는 계약**이다.
세 곳이 이걸 읽어 서로 다른 결정을 내린다:

    A  core/graph_agent.py  _maybe_learn      →  캐시에 학습할 것인가
    B  core/graph.py        verify_output     →  AI가 성공처럼 답한 걸 덮을 것인가 (T04)
    C  core/graph.py        _tool_reported_failure →  화면을 봐서 확인할 것인가 (8초)

2026-09-10에 재 보니 **세 곳의 규칙이 서로 달랐다.** 그 결과:

  - `✗`(도구가 가장 많이 쓰는 실패 표시, 52회)를 **B가 못 봤다** →
    도구가 "✗ 메모장을 찾을 수 없습니다"를 반환해도 LLM이 "메모장 열었어요!"라고
    답하면 **그대로 사용자에게 나갔다.** BL-12·BL-19·BL-26과 같은 계열이다.
  - `web.py`의 넷은 `✗`(U+2717)가 아니라 **알파벳 x**라 A·B·C 전부를 빠져나갔다 →
    실패한 검색이 **캐시에 학습될 수 있었다**(BL-27·BL-21 계열).

**그래서 판정 규칙을 여기 하나에만 둔다.** 쓰는 쪽 135곳을 오늘 통일해도 내일 새
도구가 어긋나면 같은 구멍이 다시 생긴다 — `web.py`가 정확히 그렇게 됐고, 누구도
틀리려고 하지 않았다. 규율은 확률을 올릴 뿐이고 **보장하는 건 구조다.**
(어긋남 자체는 `tests/test_tool_result.py`가 소스를 전수 스캔해 잡는다)

⚠️ **A·B·C를 한 함수로 합치지 말 것.** 통일하는 건 *"이 문자열이 실패인가"* 하나뿐이고,
   실패일 때 무엇을 할지는 각자의 몫이다. 8초 절약과 거짓말 차단은 다른 문제다.
"""

from __future__ import annotations

import re
from typing import Any

# ── 마커 3종 (ADR §5-1) ──────────────────────────────────────────
#
# 판정 기준은 «예외가 났는가»가 아니라 **«사용자가 원한 일이 일어났는가»** 다.
# 그래서 ⚠️(도구는 돌았지만 창이 안 나타났다)는 실패 쪽에 있고,
# "클립보드가 비어있어요"(도구는 제 일을 했고 결과가 빈 것)는 성공 쪽에 있다.

MARK_OK = "✓"        # 성공 — 의도한 일이 됐다
MARK_WARN = "⚠️"     # 부분 실패 — 도구는 돌았지만 목적이 달성되지 않았다
MARK_FAIL = "✗"      # 실패 — 아무 일도 못 했다 (예외 포함)

#: 도구가 새로 쓸 때 골라야 하는 것. (테스트가 이 목록으로 소스를 검사한다)
VALID_MARKERS = (MARK_OK, MARK_WARN, MARK_FAIL)

#: 쓰면 안 되는 것. `x`는 ✗(U+2717)와 **눈으로 구별되지 않는다** — 그래서 금지다.
BANNED_MARKERS = ("x", "X", "❌", "[오류]")

_FAIL_RE = re.compile(
    # 마커. ⚠️는 U+26A0 뒤에 이모지 셀렉터(U+FE0F)가 붙기도 하고 안 붙기도 한다.
    r'^(?:✗|❌|⚠️?)'
    # 예전 형식 — `[오류]` · `[type_text 오류]` · `[error]`.
    # ⚠️ 안전망이지 하위호환이 아니다. 쓰는 쪽은 ✗로 옮긴다(ADR §5-1).
    r'|^\[(?:오류|error|[가-힣A-Za-z_]+\s*오류)\]'
    r'|^오류\s*[:：]'
    r'|^Error\s*:',
    re.IGNORECASE,
)
_OK_RE = re.compile(r'^✓')


def as_text(content: Any) -> str:
    """ToolMessage의 content를 문자열로. (Gemini는 블록 리스트로 줄 때가 있다)"""
    if isinstance(content, list):
        return " ".join(str(b) for b in content)
    return str(content)


def tool_failed(content: Any) -> bool:
    """도구가 **실패를 자백했는가.**

    ✗(실패)와 ⚠️(부분 실패)를 **둘 다** True로 본다 — 읽는 쪽 셋이 전부
    *"사용자가 원한 일이 안 일어났다"* 를 알고 싶어 하기 때문이다.
    둘을 갈라야 하는 자리가 생기면 그때 `tool_partial()`을 따로 만든다.
    """
    return bool(_FAIL_RE.match(as_text(content).strip()))


def tool_succeeded(content: Any) -> bool:
    """도구가 성공을 보고했는가.

    ⚠️ **성공을 «보고»했다는 뜻이지 실제로 됐다는 뜻이 아니다.**
    거짓 ✓는 텍스트로 알 수 없어 `visual_verify`가 따로 본다(BL-12).
    """
    return bool(_OK_RE.match(as_text(content).strip()))
