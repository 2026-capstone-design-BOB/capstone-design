"""도구 결과 «계약» 회귀 — BL-29
실행: python tests/test_tool_result.py

→ ADR: docs/design/BL-29_도구_결과_계약.md

## 이 테스트가 왜 있나

도구가 반환하는 문자열의 접두사는 장식이 아니라 **코드 세 곳이 파싱하는 계약**이다
(캐시 학습 금지 · T04 거짓성공 차단 · 시각검증 스킵). 2026-09-10에 재 보니
세 곳의 규칙이 서로 달랐고, 그 결과:

  - `✗`(가장 많이 쓰는 실패 표시, 52곳)를 **T04가 못 봤다** → 도구가 실패해도
    LLM이 "메모장 열었어요!"라고 하면 그대로 사용자에게 나갔다.
  - `web.py`의 넷은 `✗`(U+2717)가 아니라 **알파벳 x**라 셋 다 빠져나갔다 →
    실패한 검색이 **캐시에 학습될 수 있었다.**

**그 구멍은 §1~§3이 메운다. 이 파일의 존재 이유는 §4다.**
쓰는 쪽 135곳을 오늘 통일해도 **내일 새 도구가 어긋나면 같은 일이 다시 난다** —
`web.py`가 정확히 그렇게 됐고, 누구도 틀리려고 하지 않았다.
그래서 **소스를 전수 스캔해서, 어긋나면 여기서 깨진다.**

⚠️ 이 테스트가 실패하면 «테스트를 고친다»가 아니라 **«도구를 고친다»** 가 답이다.
   정말 예외라면 §4의 `_ALLOW`에 **이유와 함께** 등록한다. 이유를 못 적으면 등록도 못 한다.
"""
import _testenv  # noqa: F401  ← 반드시 먼저 (로그·캐시 오염 차단)

import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from core.tool_result import (  # noqa: E402
    BANNED_MARKERS, MARK_FAIL, MARK_OK, MARK_WARN, VALID_MARKERS,
    as_text, tool_failed, tool_succeeded,
)


# ── §4의 allowlist ───────────────────────────────────────────────
#
# «실패처럼 보이는데 마커가 없는» return 중 **정말 실패가 아닌 것**.
# 반드시 (파일, 함수, 이유)를 적는다 — 이유 없이 조용히 늘어나면
# 이 테스트는 자기가 막으려던 바로 그 드리프트를 허용하게 된다.
_ALLOW = {
    ("input_control.py", "get_clipboard_text"):
        "클립보드가 빈 것은 실패가 아니다 — 도구는 제 일을 했고 결과가 비었다 (ADR §5-2)",
    ("input_control.py", "_click_guard"):
        "도구가 아니라 내부 헬퍼. 호출자가 f'✗ {problem}…'로 감싼다 (ADR §5-2-1)",
    ("filesystem.py", "list_directory"):
        "'✓ …표시할 항목이 없습니다'는 빈 결과지 실패가 아니다",
    ("vision.py", "stop_watching"):
        "'✓ 지금 지켜보고 있는 건 없어요'는 정상 응답이다",
}

# 실패 문장을 알아보는 휴리스틱. 넓게 잡는다 —
# 여기 걸려서 사람이 한 번 보는 비용보다, 놓쳐서 캐시가 오염되는 비용이 크다.
_NEG = re.compile(r"(못|없|실패|불가|오류|에러|않)")


def _const_str(node):
    """문자열 리터럴 / f-string의 앞부분을 뽑는다. (리터럴만 본다 — ADR §7)"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
            for v in node.values
        )
    return ""


def _scan_tools():
    """tools/*.py 의 모든 «문자열 return»을 (파일, 줄, 함수, 문자열)로."""
    rows = []
    tools_dir = os.path.join(_ROOT, "tools")
    for fn in sorted(os.listdir(tools_dir)):
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        path = os.path.join(tools_dir, fn)
        # ⚠️ 한글 소스를 cp949로 읽으면 UnicodeDecodeError (절대규칙 7)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Return) and node.value is not None:
                    s = _const_str(node.value)
                    if s:
                        rows.append((fn, node.lineno, func.name, s))
    return rows


def run():
    passed = total = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")
        if not cond and detail:
            for line in str(detail).splitlines():
                print(f"       {line}")

    # ── §1. 판정 함수 자체 ────────────────────────────────────
    print("=== §1. tool_failed / tool_succeeded ===")

    for marker, label in ((MARK_FAIL, "✗ 실패"), (MARK_WARN, "⚠️ 부분 실패")):
        check(f"{label} → 실패로 읽는다", tool_failed(f"{marker} 메모장을 열지 못했습니다."))
    check("✓ 성공 → 실패가 아니다", not tool_failed("✓ 메모장을 열었습니다."))
    check("✓ 성공 → 성공으로 읽는다", tool_succeeded("✓ 메모장을 열었습니다."))

    # 안전망 — 쓰는 쪽에서 없앴지만 읽는 쪽은 계속 안다 (ADR §5-1)
    for s in ("[오류] pyautogui 없음", "[type_text 오류] ValueError: x",
              "[error] boom", "오류: 파일 없음", "Error: not found"):
        check(f"예전 형식도 실패로 읽는다: {s[:22]!r}", tool_failed(s))

    # ⚠️ 는 U+FE0F(이모지 셀렉터)가 붙기도 하고 안 붙기도 한다
    check("⚠ (셀렉터 없음)도 실패로 읽는다", tool_failed("⚠ 창이 나타나지 않았습니다."))

    check("빈 문자열은 실패가 아니다", not tool_failed(""))
    check("평범한 성공 문장은 실패가 아니다", not tool_failed("메모장을 열었습니다."))
    # 오탐 방어 — 문장 '안'에 있는 실패 어휘까지 잡으면 성공이 실패가 된다
    check("문장 중간의 '오류'는 안 잡는다", not tool_failed("✓ 오류 로그를 열었습니다."))

    # Gemini가 content를 블록 리스트로 줄 때가 있다
    check("리스트 content도 판정한다", tool_failed(["✗ 못 찾았습니다.", "추가"]))
    check("as_text가 리스트를 합친다", as_text(["a", "b"]) == "a b")

    # ── §2. ASCII x 는 마커가 아니다 (읽는 쪽이 인정하면 마커가 두 벌이 된다)
    print("\n=== §2. 눈으로 구별되지 않는 마커는 마커가 아니다 ===")
    check("ASCII 'x'는 실패로 읽지 않는다 (금지가 답이다 — §4가 잡는다)",
          not tool_failed("x URL 열기 실패: timeout"))
    check("✗(U+2717)와 x(U+0078)는 다른 글자다", MARK_FAIL != "x")

    # ── §3. 읽는 쪽 셋이 정말 이 함수를 쓰는가 ─────────────────
    #
    # 소스 대조다. 함수를 만들어 놓고 한 곳이 옛 규칙을 그대로 쓰면
    # 아무도 안 알려 준다 — 이 프로젝트가 이미 겪은 모양이다(BL-13).
    print("\n=== §3. 읽는 쪽 3곳이 tool_result를 쓴다 ===")

    with open(os.path.join(_ROOT, "core", "graph.py"), encoding="utf-8") as f:
        src_graph = f.read()
    with open(os.path.join(_ROOT, "core", "graph_agent.py"), encoding="utf-8") as f:
        src_agent = f.read()

    check("graph.py 가 tool_failed를 import 한다",
          "from core.tool_result import tool_failed" in src_graph)
    check("graph_agent.py 가 tool_failed를 import 한다",
          "from core.tool_result import tool_failed" in src_agent)
    check("A 캐시 학습 금지가 tool_failed를 쓴다",
          "tool_failed(m.content)" in src_agent)
    check("B T04(verify_output)가 tool_failed를 쓴다",
          "if tool_failed(c):" in src_graph)
    check("C _tool_reported_failure가 tool_failed를 쓴다",
          "return tool_failed(content)" in src_graph)
    check("옛 _TOOL_ERROR_RE는 사라졌다 (규칙이 두 벌이면 또 어긋난다)",
          "_TOOL_ERROR_RE = re.compile(" not in src_graph)

    # 실제 동작 — T04가 ✗를 잡는가. **이게 BL-29의 본체다.**
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from core.graph import verify_output

    def _turn(tool_out, answer="메모장 열었어요!"):
        return [HumanMessage(content="메모장 열어줘"),
                AIMessage(content="", tool_calls=[
                    {"name": "open_app", "args": {}, "id": "1"}]),
                ToolMessage(content=tool_out, tool_call_id="1"),
                AIMessage(content=answer)]

    r = verify_output(_turn("✗ '메모장' 앱을 찾을 수 없습니다."))
    check("🚨 ✗ 실패 + 성공처럼 답함 → 보정된다 (BL-29의 본체)", bool(r), f"반환={r!r}")
    check("보정 문구에 마커가 새지 않는다", bool(r) and MARK_FAIL not in r, f"반환={r!r}")
    check("보정 문구가 원래 이유를 담는다", bool(r) and "찾을 수 없습니다" in r, f"반환={r!r}")

    r2 = verify_output(_turn("⚠️ 메모장은 실행 중이지만 열려 있는 창이 없어요."))
    check("⚠️ 부분 실패 + 성공처럼 답함 → 보정된다", bool(r2), f"반환={r2!r}")
    check("⚠️ 마커도 새지 않는다", bool(r2) and "⚠" not in r2, f"반환={r2!r}")

    check("정상 성공은 건드리지 않는다",
          verify_output(_turn("✓ 메모장을 열었습니다.")) is None)

    # ── §4. 소스 전수 스캔 — **내일의 구멍을 막는다** ──────────
    print("\n=== §4. 도구 소스 전수 스캔 (이 파일의 존재 이유) ===")

    rows = _scan_tools()
    check(f"스캔이 실제로 돌았다 (문자열 return {len(rows)}개)", len(rows) > 100,
          f"{len(rows)}개밖에 못 찾았다 — 스캐너가 깨졌을 수 있다")

    # 4-a. 금지된 마커
    banned = []
    for fn, ln, func, s in rows:
        t = s.lstrip()
        for b in BANNED_MARKERS:
            # 'x 검색 실패' 처럼 마커 자리에 온 것만. 'xml…' 같은 낱말은 아니다.
            if t == b or t.startswith(b + " ") or t.startswith(b + " "):
                banned.append(f"{fn}:{ln} {func}()  {s[:52]!r}  ← 금지 마커 {b!r}")
    check("금지된 마커를 쓰는 도구가 없다 (ASCII x · ❌ · [오류])",
          not banned,
          "\n".join(banned) + "\n  → ✗(U+2717) · ⚠️ · ✓ 중 하나를 쓴다 (ADR §5-1)")

    # 4-b. 실패처럼 보이는데 마커가 없는 것
    unmarked = []
    for fn, ln, func, s in rows:
        t = s.lstrip()
        if any(t.startswith(m) for m in VALID_MARKERS):
            continue
        if not _NEG.search(t[:45]):
            continue                      # 실패로 안 보인다 — 성공 문장은 마커 자유
        if (fn, func) in _ALLOW:
            continue
        unmarked.append(f"{fn}:{ln} {func}()  {s[:52]!r}")
    check("실패처럼 보이는데 마커가 없는 도구가 없다",
          not unmarked,
          "\n".join(unmarked)
          + "\n  → 실패면 ✗/⚠️ 를 붙이고, 실패가 아니면 _ALLOW에 **이유와 함께** 등록한다")

    # 4-c. 마커가 붙은 실패는 전부 읽는 쪽에 걸려야 한다.
    #      **이 프로젝트가 실제로 데인 자리다** — 마커는 있는데 안 걸렸다(✗ 52곳).
    missed = [f"{fn}:{ln} {func}()  {s[:52]!r}"
              for fn, ln, func, s in rows
              if s.lstrip().startswith((MARK_FAIL, MARK_WARN)) and not tool_failed(s)]
    check("마커가 붙은 실패는 전부 tool_failed()에 걸린다", not missed,
          "\n".join(missed))

    # 4-d. allowlist 위생 — 죽은 항목이 쌓이면 다음 사람이 못 믿는다
    live = {(fn, func) for fn, _, func, _ in rows}
    dead = [f"{k}  (이유: {v[:40]}…)" for k, v in _ALLOW.items() if k not in live]
    check("_ALLOW에 죽은 항목이 없다", not dead,
          "\n".join(dead) + "\n  → 그 함수가 사라졌다. _ALLOW에서도 지운다")
    check("_ALLOW의 모든 항목에 이유가 적혀 있다",
          all(len(v.strip()) > 15 for v in _ALLOW.values()))

    # 4-e. 실측 요약 — 숫자를 눈에 보이게 남긴다(WORKFLOW: 검증에 숫자를 적는다)
    kinds = {"✓": 0, "✗": 0, "⚠️": 0, "기타": 0}
    for _, _, _, s in rows:
        t = s.lstrip()
        if t.startswith(MARK_OK):
            kinds["✓"] += 1
        elif t.startswith(MARK_FAIL):
            kinds["✗"] += 1
        elif t.startswith(MARK_WARN):
            kinds["⚠️"] += 1
        else:
            kinds["기타"] += 1
    print(f"       실측: ✓{kinds['✓']} · ✗{kinds['✗']} · ⚠️{kinds['⚠️']} "
          f"· 마커없음 {kinds['기타']} (총 {len(rows)})")

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
