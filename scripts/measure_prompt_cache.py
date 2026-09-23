# -*- coding: utf-8 -*-
"""고정 접두가 캐시되고 있나 — **한 줄짜리 미지수를 닫는 도구** (M8 §6-1).

    conda activate pluiz
    python scripts/measure_prompt_cache.py

## 왜 이 스크립트가 있나

[M8](../docs/design/M8_도구_라우팅.md)이 잰 것: 우리 입력의 **94%가 매 호출 똑같이 올라가는
고정 접두**이고, 그중 **92.5%가 도구 44개의 스키마**다.

도구 라우팅(2-9)은 그 고정 접두를 **줄이는** 수단이고, Gemini 컨텍스트 캐싱은 그것을
**싸게 만드는**(1/10) 수단이다. 🚨 **둘은 같은 토큰을 두고 싸운다** — 라우팅을 켜면
접두가 매 턴 달라져 캐싱이 안 먹는다.

그래서 2-9를 켤지 말지가 질문 하나로 좁혀졌다:

> **캐시되는 접두에 도구 선언(`tools`)이 들어가는가.**

문서로는 절반만 닫혔다(2026-09-23 확인):
  · 명시적 캐싱 — `CachedContent` 가 `tools[]`·`systemInstruction` 을 **정식 필드로 받는다**(확정)
  · 암시적 캐싱 — 2.5 기본 활성 · flash 최소 2,048토큰까지만 적혀 있고 **접두 구성은 안 적혀 있다**

남은 절반은 **응답 메타데이터 한 번**으로 닫힌다. 이 스크립트가 그것만 한다.

## 무엇을 하나

**같은 요청을 두 번** 보낸다(실제 시스템 프롬프트 + 실제 도구 44개 + 짧은 사용자 말).
두 번째 응답에 캐시 읽기 토큰이 잡히면 암시적 캐싱이 **도는 것**이고,
그 값이 도구 몫(약 5,500토큰)에 가까우면 **도구 선언까지 덮는 것**이다.

## ⚠️ 읽기 전에

- **실제 API 를 부른다.** 2회 × 약 6,000 입력 토큰 ≈ $0.004. 도구는 **하나도 실행되지 않는다**
  (응답의 도구 호출 요청을 읽기만 하고 버린다).
- **0 이 나와도 «캐싱이 안 된다»가 아니다** — 암시적 캐싱은 앞선 요청이 있어야 붙는다.
  그래서 두 번 보내고 **두 번째 값**을 본다. 그래도 0이면 `--repeat 4` 로 늘려 본다.
- `.env` 의 `LLM_PROVIDER` 가 gemini 가 아니면 그냥 그 provider 의 메타데이터를 찍는다.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _dump(obj, indent=4):
    try:
        return json.dumps(obj, ensure_ascii=False, indent=indent, default=str)
    except Exception:
        return repr(obj)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=2,
                    help="같은 요청을 몇 번 보낼지 (기본 2 — 두 번째부터 캐시가 붙는다)")
    ap.add_argument("--text", default="안녕", help="보낼 사용자 발화 (도구를 부르지 않는 말로 둔다)")
    ap.add_argument("--no-tools", action="store_true",
                    help="도구를 빼고 같은 것을 잰다 — **도구 몫을 빼서 확인하는 대조군**")
    args = ap.parse_args()

    from langchain_core.messages import HumanMessage, SystemMessage
    from core.llm import build_llm
    from core.graph import build_system_prompt
    from core.tool_registry import get_all_tools

    system = build_system_prompt()
    tools = [] if args.no_tools else get_all_tools()
    llm = build_llm()
    bound = llm.bind_tools(tools) if tools else llm

    print("=" * 78)
    print("■ 고정 접두 캐시 측정 (M8 §6-1)")
    print("=" * 78)
    print(f"  시스템 프롬프트 {len(system):,}자 · 도구 {len(tools)}개 · 발화 {args.text!r}")
    print(f"  같은 요청을 {args.repeat}회 보낸다 — **두 번째부터**의 값이 답이다.")
    print()

    msgs = [SystemMessage(content=system), HumanMessage(content=args.text)]
    for i in range(1, args.repeat + 1):
        resp = bound.invoke(msgs)
        um = getattr(resp, "usage_metadata", None) or {}
        raw = getattr(resp, "response_metadata", None) or {}
        cached = 0
        details = um.get("input_token_details") or {}
        for key in ("cache_read", "cache_read_input_tokens", "cached_content"):
            if details.get(key):
                cached = details[key]
                break
        print(f"  [{i}회차] 입력 {um.get('input_tokens', '?')} · 출력 {um.get('output_tokens', '?')}"
              f" · **캐시 읽기 {cached}**")
        if i == args.repeat:
            print("\n  ── usage_metadata 원본 ─────────────────────────────")
            print(_dump(um))
            if raw:
                print("  ── response_metadata 원본 ──────────────────────────")
                print(_dump(raw))

    print()
    print("  📌 읽는 법")
    print("     캐시 읽기 = 0            → 암시적 캐싱이 **안 붙는다.** 2-9(라우팅)의 토큰 근거가 살아 있다")
    print("     캐시 읽기 ≈ 5,000~6,000  → **도구 선언까지 덮는다.** 2-9는 더 작은 이득을 위해")
    print("                                 더 큰 이득을 막는 일이 된다 → M8 §6")
    print("     캐시 읽기가 작다(수백)   → 시스템 프롬프트만 덮는다. `--no-tools` 로 대조해 확인한다")


if __name__ == "__main__":
    main()
