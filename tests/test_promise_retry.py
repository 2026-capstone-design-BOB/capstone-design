"""
«앞으로 하겠다»고 말하고 안 하는 것 — BL-35. mock (LLM 없음)
실행: python tests/test_promise_retry.py

## 왜 이 테스트가 생겼나

2026-09-11 실기:

    👤 그래 빨리 좀 해 봐
    🤖 오늘 날씨를 다시 확인하고 있어요. 어제 날씨도 바로 이어서 찾아볼게요!
    로그: 턴 완료 | 도구=없음 | 사유=잡담 | LLM 1회

확인하고 있지 않았다. 사용자는 한 번 더 말해야 했다.

이 저장소가 반복해서 데인 계열의 **세 번째 얼굴**이다 —
BL-12·19·26이 «안 한 걸 했다고», BL-32가 «한 걸 말하지 않는», 이건
**«앞으로 하겠다고 말하고 안 하는»** 것이다.

## 이 파일이 지키는 것

그물의 **최악이 «LLM 호출 1회 낭비»** 여야 한다. 응답을 고쳐 쓰지 않으므로
오탐의 대가가 작지만, 그래도 **평범한 인사말에 걸리면 안 된다**:

  ① 진짜 거짓 약속에는 걸린다
  ② 인사말·설명·정직한 실패 보고에는 **안 걸린다**
  ③ 도구를 부른 턴에는 애초에 안 본다
  ④ **계획 실행 중에는 안 건다** — 거기서 «도구 0개»는 «이 단계 끝»이고,
     강제하면 이미 끝난 단계를 한 번 더 실행할 수 있다(되돌릴 수 없는 동작에서 최악)
"""
import _testenv  # noqa: F401
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from core.graph import (
    needs_promise_retry, with_promise_directive, _PROMISE_RETRY_DIRECTIVE,
)


def ai(text, tool_calls=None):
    m = AIMessage(content=text)
    if tool_calls:
        m.tool_calls = tool_calls
    return m


print("[1] 🚨 실기에서 나온 그 문장에 걸린다")

REAL = [
    # 2026-09-11 실기 — 두 턴 다 이 꼴이었다
    "오늘 날씨를 다시 확인하고 있어요. 어제 날씨도 바로 이어서 찾아볼게요!",
    "오늘 날씨 정보를 가져왔는데, 웹사이트 링크만 있어서 정확한 날씨를 다시 확인해볼게요.",
    "어제 날씨도 이어서 찾아보고 말씀드릴게요!",
    "지금 검색해볼게요.",
    "바로 확인해서 알려드릴게요.",
    "잠시만요, 찾고 있어요.",
]
for t in REAL:
    check(f"걸린다: {t[:32]}…", needs_promise_retry(ai(t)), "→ 안 걸렸다")


print("")
print("[2] 평범한 말에는 안 걸린다 (오탐이 이 그물의 유일한 비용이다)")

SAFE = [
    "메모장을 열었어요.",
    "제 호출어는 '플루이즈'예요. 더 궁금한 게 있으면 알려드릴게요!",
    "안녕하세요! 무엇을 도와드릴까요?",
    "네, 알겠습니다.",
    "그건 제가 할 수 없는 일이에요.",
    "계산기를 닫았어요. 다른 것도 필요하면 말씀해 주세요.",
    "다시 설명드릴게요. 이 기능은 화면을 보고 알려주는 기능이에요.",
    "볼륨을 올렸어요.",
]
for t in SAFE:
    check(f"안 걸린다: {t[:32]}…", not needs_promise_retry(ai(t)), "→ 걸렸다")


print("")
print("[3] 이미 «못 한다»고 말하면 정직한 보고다 — 건드리지 않는다")

HONEST = [
    "죄송해요, 날씨 정보를 가져오지 못했어요.",
    "지금 확인해볼게요. 그런데 인터넷 연결이 없어서 안 돼요.",
    "그 파일을 찾지 못했어요.",
    "한글이 설치되어 있지 않아서 열 수 없어요.",
]
for t in HONEST:
    check(f"안 걸린다(정직): {t[:30]}…", not needs_promise_retry(ai(t)), "→ 걸렸다")


print("")
print("[4] 도구를 부른 턴 · 빈 응답은 애초에 안 본다")

check("도구를 불렀으면 안 건다",
      not needs_promise_retry(
          ai("지금 바로 찾아볼게요!",
             tool_calls=[{"name": "get_weather", "args": {}, "id": "1"}])),
      "도구를 불렀으면 거짓말이 아니다")
check("빈 응답은 안 건다", not needs_promise_retry(ai("")))
check("공백만 있는 응답도 안 건다", not needs_promise_retry(ai("   \n ")))


print("")
print("[5] 🚨 계획 실행 중에는 절대 안 건다")

# M3에서 «도구 0개»는 «이 단계는 더 할 일이 없다»는 뜻이고 커서가 전진한다.
# 여기서 도구를 강제하면 **이미 끝난 단계를 한 번 더 실행**할 수 있다.
check("in_plan이면 같은 문장이어도 안 건다",
      not needs_promise_retry(ai("지금 바로 찾아볼게요!"), in_plan=True),
      "되돌릴 수 없는 동작을 두 번 하는 길이다")
check("in_plan=False면 걸린다(대조군)",
      needs_promise_retry(ai("지금 바로 찾아볼게요!"), in_plan=False))


print("")
print("[6] 재시도 메시지 — 시스템 자리에 둔다 (Gemini 400 · 히스토리 오염 방지)")

msgs = [SystemMessage(content="너는 Pluiz다."), HumanMessage(content="날씨 알려줘"),
        AIMessage(content="지금 찾아볼게요")]
out = with_promise_directive(msgs)

check("메시지 개수가 늘지 않는다(기존 시스템에 덧붙인다)", len(out) == len(msgs),
      f"→ {len(out)} vs {len(msgs)}")
check("SystemMessage가 하나뿐이다",
      sum(1 for m in out if isinstance(m, SystemMessage)) == 1,
      "두 번째 SystemMessage는 Gemini가 무시하거나 400이다")
check("지시가 시스템 프롬프트에 들어갔다",
      _PROMISE_RETRY_DIRECTIVE.strip()[:20] in out[0].content)
check("원래 시스템 프롬프트가 남아 있다", "너는 Pluiz다." in out[0].content)
check("🚨 HumanMessage를 새로 만들지 않는다",
      sum(1 for m in out if isinstance(m, HumanMessage))
      == sum(1 for m in msgs if isinstance(m, HumanMessage)),
      "사용자가 말한 적 없는 문장이 사람 발언으로 남으면 "
      "다음 턴의 _last_human_text가 그걸 읽는다")

# 시스템 메시지가 없는 경우
out2 = with_promise_directive([HumanMessage(content="날씨 알려줘")])
check("시스템 메시지가 없으면 앞에 하나 만든다",
      isinstance(out2[0], SystemMessage) and len(out2) == 2)

check("지시문이 «못 하면 못 한다고 말하라»를 포함한다",
      "할 수 없다" in _PROMISE_RETRY_DIRECTIVE,
      "도구를 강제하기만 하면 «아무 도구나» 부르는 쪽으로 샌다")


print("")
print("[7] 배선 — agent 노드가 BL-19과 같은 기계를 쓴다")

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "core", "graph.py"), encoding="utf-8").read()
agent_src = src[src.find("    def agent(state: PluizState)"):
                src.find("    def output_guard(state: PluizState)")]

check("agent가 needs_promise_retry를 본다", "needs_promise_retry(response" in agent_src)
check("BL-19 재시도와 배타적이다(elif)", "elif needs_promise_retry" in agent_src,
      "한 턴에 재시도를 두 번 하면 지연이 두 배가 된다")
check("in_plan을 넘긴다", "in_plan=in_plan" in agent_src,
      "안 넘기면 계획 단계에서 도구가 강제돼 중복 실행된다")
check("tool_choice를 'any'로 묶는다", '_forced_llm("any")' in agent_src)
check("묶기에 실패하면 설득 재시도로 폴백한다",
      "설득 재시도로 폴백" in agent_src)
check("재시도가 실패해도 턴을 죽이지 않는다",
      "원래 응답을 쓴다" in agent_src)
check("🚨 재시도도 실패하면 응답을 **고쳐 쓰지 않는다**",
      "원래 응답을 그대로 둔다" in agent_src,
      "고쳐 쓰면 오탐이 멀쩡한 답을 망친다 — 그물의 최악은 LLM 1회 낭비여야 한다")
check("재시도를 한 번만 한다", agent_src.count("needs_promise_retry") == 1)
check("로그에 [BL-35]를 남긴다", "[BL-35]" in agent_src)


print("")
print(chr(61) * 60)
print(f"결과: {passed}/{total} 통과")
print(chr(61) * 60)
sys.exit(0 if passed == total else 1)
