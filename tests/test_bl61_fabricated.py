# -*- coding: utf-8 -*-
"""도구를 안 부르고 **도구 결과처럼** 답하는 것을 막는다 (BL-61)

실행: python tests/test_bl61_fabricated.py

## 🚨 라이브에서 실제로 난 것 (2026-09-19)

```
🎤 밝기 80% 해 줘
🤖 ✓ 밝기: 40% → 80%          ← 도구를 안 불렀다. 밝기는 40% 그대로였다
🎤 지금 밝기 알려줘
🤖 ✓ 현재 밝기는 80%입니다.     ← 기기를 읽은 적이 없다. 방금 제가 한 말을 되풀이했다
```

로그가 증인이다 — 두 턴 다 `요청=없음 | 실행=없음 | 사유=잡담` 이다.
**LLM 이 도구 결과 문장을 통째로 지어냈다.** 사용자는 실제 밝기가 40%인 채로
«80%입니다» 를 세 번 들었다.

## 🔑 문구를 판정하지 않는다 — **마커와 도구 수**만 본다

`✓` 는 장식이 아니라 **계약**이다([`core/tool_result.py`](../core/tool_result.py)) —
«도구가 의도한 일을 해냈다»는 뜻이고 **도구만 쓸 수 있는 표시**다.
그러니 *«이번 턴에 도구가 0개인데 응답이 `✓` 로 시작한다»* 는 **지어낸 것**이다.

말투로 잡으려는 시도는 이미 실패한 적이 있다 — `_SUCCESS_LIKE_RE` 는 **동사
화이트리스트**라 «볼륨 올렸어요»를 성공으로 읽지도 못한다(감사 G-12).
**여기는 어휘에 기대지 않는다.**

## 🚨 양방향

- «도구 0개면 막는다»만 고정하면 **평범한 대답까지 막는 수정**이 통과한다 →
  §2가 잡담·질문·`✗` 보고가 **그대로 나가는지** 본다.
- **캐시 히트는 제외해야 한다** — 빠른 경로는 도구를 그래프 **밖에서** 돌려
  (절대규칙 2) 여기서는 «도구 0개»로 보인다. 안 거르면 **멀쩡히 실행된 캐시 응답을
  전부 «지어낸 것»으로 몬다** → §3이 그 제외를 못 박는다.

## ⚠️ 이 그물이 대신하지 못하는 것

거짓말을 **막을** 뿐 **답을 주지는 않는다.** *"지금 밝기 얼마야"* 에 답하려면
읽는 도구가 있어야 한다 → [BL-60](../docs/BACKLOG.md).
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run():
    passed = total = skipped = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}"
              + ("" if cond or not detail else f"   → {detail}"))

    def cannot_judge(names, why):
        """못 잰 것을 **세어서** 남긴다 — 건너뛴 것은 통과가 아니다 (BL-59)."""
        nonlocal skipped
        for n in names:
            skipped += 1
            print(f"  ⬜ 판정 불가 {n}")
        print(f"     └ {why}")

    try:
        from core.graph import detect_fabricated_result, _NOTHING_HAPPENED_MSG
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        has_mod = True
    except Exception as e:                                    # noqa: BLE001
        detect_fabricated_result = _NOTHING_HAPPENED_MSG = None
        has_mod = False
        _why = f"{type(e).__name__}: {e}"

    gr_src = io.open(os.path.join(_ROOT, "core", "graph.py"), encoding="utf-8").read()

    def turn(*msgs):
        return list(msgs)

    # ── §1 라이브에서 난 것이 막힌다 ───────────────────────────────
    print("\n§1 🚨 도구 0개인데 «✓» 로 시작하면 지어낸 것이다")
    if not has_mod:
        cannot_judge(["«✓ 밝기: 40% → 80%» 가 막힌다",
                      "«✓ 현재 밝기는 80%입니다» 도 막힌다",
                      "🔑 대신 «못 했다»고 말한다",
                      "앞에 공백이 있어도 잡는다"],
                     f"core.graph 를 못 불러왔다 ({_why}) — `conda activate pluiz` 로 다시 돌릴 것")
    else:
        got = detect_fabricated_result(turn(
            HumanMessage(content="밝기 80% 해 줘"),
            AIMessage(content="✓ 밝기: 40% → 80%")))
        check("«✓ 밝기: 40% → 80%» 가 막힌다", got is not None, f"→ {got!r}")
        check("🔑 대신 «못 했다»고 말한다", got == _NOTHING_HAPPENED_MSG, f"→ {got!r}")

        got = detect_fabricated_result(turn(
            HumanMessage(content="지금 밝기 알려줘"),
            AIMessage(content="✓ 현재 밝기는 80%입니다.")))
        check("«✓ 현재 밝기는 80%입니다» 도 막힌다", got is not None, f"→ {got!r}")

        got = detect_fabricated_result(turn(
            HumanMessage(content="x"), AIMessage(content="  ✓ 했어요")))
        check("앞에 공백이 있어도 잡는다", got is not None, f"→ {got!r}")

    # ── §2 🚨 반대 방향 — 멀쩡한 말을 막지 않는다 ──────────────────
    print("\n§2 🚨 반대 방향 — 평범한 대답까지 막으면 안 된다")
    if not has_mod:
        cannot_judge(["잡담은 그대로 나간다", "질문 되묻기도 그대로",
                      "✗ 실패 보고는 그대로 (막으면 실패를 숨긴다)",
                      "⚠️ 부분 실패도 그대로",
                      "🔑 도구를 불렀으면 ✓ 를 써도 된다",
                      "빈 응답은 여기 몫이 아니다 (`verify_output` 이 복구한다)"],
                     "core.graph 를 못 불러왔다")
    else:
        check("잡담은 그대로 나간다",
              detect_fabricated_result(turn(
                  HumanMessage(content="안녕"),
                  AIMessage(content="안녕하세요! 무엇을 도와드릴까요?"))) is None)
        check("질문 되묻기도 그대로",
              detect_fabricated_result(turn(
                  HumanMessage(content="인사말 써 줘"),
                  AIMessage(content="어느 창에 쓸까요?"))) is None)
        check("✗ 실패 보고는 그대로 (막으면 실패를 숨긴다)",
              detect_fabricated_result(turn(
                  HumanMessage(content="x"),
                  AIMessage(content="✗ 'Please'이(가) 실행 중이지 않습니다."))) is None)
        check("⚠️ 부분 실패도 그대로",
              detect_fabricated_result(turn(
                  HumanMessage(content="x"),
                  AIMessage(content="⚠️ 창이 없어요."))) is None)
        check("🔑 도구를 불렀으면 ✓ 를 써도 된다",
              detect_fabricated_result(turn(
                  HumanMessage(content="밝기 올려줘"),
                  AIMessage(content="", tool_calls=[
                      {"name": "brightness_up", "args": {}, "id": "1"}]),
                  ToolMessage(content="✓ 밝기: 40% → 50%", tool_call_id="1"),
                  AIMessage(content="✓ 밝기: 40% → 50%"))) is None)
        check("빈 응답은 여기 몫이 아니다 (`verify_output` 이 복구한다)",
              detect_fabricated_result(turn(
                  HumanMessage(content="x"), AIMessage(content=""))) is None)

    # ── §3 턴 경계 · 캐시 히트 ────────────────────────────────────
    #
    # 🚨 `state["messages"]` 는 **thread 전체 히스토리**다(절대규칙 6).
    #   지난 턴에 도구를 불렀다고 이번 턴의 거짓말이 면제되면 안 된다.
    print("\n§3 턴 경계와 캐시 히트")
    if not has_mod:
        cannot_judge(["🚨 지난 턴의 도구 호출이 이번 턴을 구제하지 않는다"],
                     "core.graph 를 못 불러왔다")
    else:
        got = detect_fabricated_result(turn(
            HumanMessage(content="밝기 올려줘"),
            AIMessage(content="", tool_calls=[
                {"name": "brightness_up", "args": {}, "id": "1"}]),
            ToolMessage(content="✓ 밝기: 40% → 50%", tool_call_id="1"),
            AIMessage(content="✓ 밝기: 40% → 50%"),
            HumanMessage(content="지금 밝기 알려줘"),        # ← 새 턴이 여기서 시작한다
            AIMessage(content="✓ 현재 밝기는 50%입니다.")))
        check("🚨 지난 턴의 도구 호출이 이번 턴을 구제하지 않는다",
              got is not None, f"→ {got!r}")

    check("🚨 캐시 히트는 제외된다 (안 거르면 멀쩡한 캐시 응답을 전부 «거짓»으로 몬다)",
          'else detect_fabricated_result(state["messages"])' in gr_src
          and gr_src.count('state.get("decision") == "fast_hit"') >= 2)
    check("`output_guard` 가 실제로 이 그물을 부른다", "detect_fabricated_result(" in gr_src)
    check("막을 때 로그를 남긴다 (빈도를 셀 수 있어야 한다)", "[BL-61]" in gr_src)

    # ── §4 구조 — 어휘에 기대지 않는다 ────────────────────────────
    #
    # 🔑 말투로 잡으려는 시도는 이미 실패했다 — `_SUCCESS_LIKE_RE` 는 동사
    #   화이트리스트라 «볼륨 올렸어요»를 성공으로 읽지도 못한다(감사 G-12).
    print("\n§4 구조 — 문구가 아니라 계약을 본다")
    body = gr_src[gr_src.index("def detect_fabricated_result"):
                  gr_src.index("def verify_output")]
    check("🔑 어휘 목록(`_SUCCESS_LIKE_RE`)에 기대지 않는다", "_SUCCESS_LIKE_RE" not in body)
    check("도구 수를 세서 판단한다", "turn_tool_call_count(" in body)
    check("«이번 턴»만 본다 (절대규칙 6)", "current_turn_messages(" in body)
    check("마커는 계약에서 가져온다 (`✓` 를 여기 또 적지 않는다)",
          "MARK_OK" in body and "MARK_OK" in gr_src.split("def ")[0])

    if skipped:
        print(f"\n결과: {passed}/{total} · 🚨 판정 불가 {skipped}건 — 초록이 아니다")
        print("   지어낸 도구 결과를 다 못 쟀다. `conda activate pluiz` 로 다시 돌릴 것")
    else:
        print(f"\n결과: {passed}/{total} 통과")
    return passed == total and skipped == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
