"""2026-09-29 · 09-30 실기가 잡은 결함 일곱의 **회귀 자물쇠**.

🔑 이 파일은 «고쳤다»를 문서가 아니라 **테스트로** 붙잡는다.
   실기가 잡은 것들은 **자동 검사 3024건이 전부 초록인 채로** 살아 있던 것들이다.
   같은 일이 또 나지 않으려면 그 자리마다 자를 대야 한다.

⚠️ 여기 있는 것은 **구조 점검**이다. 실제로 도는지는 여전히 사람이 눌러 봐야 안다
   (→ docs/testing/실기_할것_20260929.md). 이 파일은 «되돌아가는 것»만 막는다.

돌리는 법:
    conda activate pluiz
    python tests/test_live_fixes_20260930.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed = total = 0


def check(label, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ FAIL {label}" + (f"   → {detail}" if detail else ""))


def _src(rel):
    # ⚠️ 절대규칙 7 — 한글이 든 소스는 반드시 utf-8 로 연다(cp949 면 깨진다).
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ═══ ① BL-77 — 승인 문구가 «삭제»로 떨어지지 않는다 ═══════════════════
#
# 🚨 2026-09-29 실기: *"회의록.txt 이름을 주간보고.txt 로 바꿔줘"* 에
#   «'회의록.txt' 파일을 정말 삭제할까요? (휴지통으로 갑니다)» 라고 물었다.
#   동작은 맞았고 **문구만** 틀렸는데, 사용자는 문구를 보고 승인한다.
print("=== ① BL-77 — 승인 문구는 도구마다 다르다 ===")
_g = _src("core/graph.py")

check("`deletes` 가 **여집합이 아니라 목록**이다",
      "DELETE_TOOLS = {" in _g
      and 'c.get("name") in DELETE_TOOLS' in _g)
check("옮기기·이름변경에 **각자의 문구**가 있다",
      "MOVE_TOOLS" in _g and "RENAME_TOOLS" in _g
      and "이름을 바꿀까요" in _g and "옮길까요" in _g)
check("🔑 분류 안 된 위험 도구가 «삭제»로 안 떨어진다",
      "others = [c for c in calls if c.get(\"name\") not in known]" in _g)
# ⚠️ 소스에서 줄바꿈으로 쪼개져 있어 **조각으로** 본다.
check("🚨 이름변경 문구가 «휴지통»이 아니라 «이름만 바뀐다»고 말한다",
      "이름을 바꿀까요" in _g and "파일은 그대로 있고 이름만 바뀌어요" in _g)

try:
    from core.graph import DELETE_TOOLS, MOVE_TOOLS, RENAME_TOOLS, DANGEROUS_TOOLS, OVERWRITE_TOOLS
    known = ({"click_ui_element", "force_close_app"}
             | OVERWRITE_TOOLS | DELETE_TOOLS | MOVE_TOOLS | RENAME_TOOLS)
    check("🔒 **모든 위험 도구가 문구를 가진다** — 새로 추가하면 여기서 걸린다",
          DANGEROUS_TOOLS <= known, f"문구 없는 것: {sorted(DANGEROUS_TOOLS - known)}")
except Exception as e:                                        # noqa: BLE001
    check("core.graph 를 읽는다", False, f"{type(e).__name__}: {e}")


# ═══ ② BL-78 — 감시 재시도가 «이번 턴»만 본다 ════════════════════════
#
# 🚨 앞 단계에서 `do_in_background` 가 이미 돌았는데도, 뒤따르는 «말로만 하는»
#   응답을 보고 *"감시 요청인데 도구 미호출"* 로 판정해 `watch_screen` 을
#   **요청하지 않았는데 덧붙였다.** 절대규칙 6 이 가리키는 바로 그 자리다.
print("\n=== ② BL-78 — 감시 재시도는 이번 턴에 도구가 돌았으면 안 건다 ===")
check("`needs_watch_retry` 가 `acted_this_turn` 을 받는다",
      "acted_this_turn" in _g)
check("판정이 `current_turn_messages()` 를 거친다 (절대규칙 6)",
      "_tools_ran_this_turn" in _g
      and "for m in current_turn_messages(messages):" in _g)
check("호출부가 실제로 그 값을 넘긴다",
      "acted_this_turn=acted" in _g)

try:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from core.graph import needs_watch_retry, _tools_ran_this_turn

    class _Plain:
        tool_calls = None
        content = "메모장을 지켜볼게요"

    check("🔑 이번 턴에 도구가 돌았으면 **재시도하지 않는다**",
          needs_watch_retry("메모장 지켜보다 글자 생기면 알려줘", _Plain(),
                            watching=False, acted_this_turn=True) is False)
    check("🔑 안 돌았으면 예전처럼 **재시도한다** (그물을 없앤 게 아니다)",
          needs_watch_retry("메모장 지켜보다 글자 생기면 알려줘", _Plain(),
                            watching=False, acted_this_turn=False) is True)

    ran = [HumanMessage(content="앞 턴"),
           AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}]),
           ToolMessage(content="ok", tool_call_id="1", name="x"),
           HumanMessage(content="이번 턴"),
           AIMessage(content="말만 함")]
    check("🚨 **지난 턴의 도구 실행은 안 센다** — 그게 절대규칙 6 이다",
          _tools_ran_this_turn(ran) is False)
except Exception as e:                                        # noqa: BLE001
    check("needs_watch_retry 를 실제로 부른다", False, f"{type(e).__name__}: {e}")


# ═══ ③ 약속 고지가 요약에 안 지워진다 (2026-09-30 실기 7번) ═══════════
#
# 🚨 `remind_me` 는 세 가지를 다 돌려주는데 사용자에게 나간 답은 **매번 23자**였다.
#   모델이 요약하면서 ②「닫으면 사라져요」와 ③ 취소법을 버렸다.
print("\n=== ③ 약속 고지는 원문 그대로 나간다 ===")
check("`promise_notice_to_deliver` 가 있다", "def promise_notice_to_deliver" in _g)
check("감시 고지와 **같은 기계**를 쓴다 (output_guard 안에서 _emit)",
      "promise = promise_notice_to_deliver(state[\"messages\"])" in _g)
check("세 도구가 다 걸린다",
      all(t in _g for t in ('"remind_me"', '"watch_inbox"', '"do_in_background"')))

_bg = _src("tools/background.py")
_gm = _src("tools/gmail.py")
check("🔑 `remind_me` 의 답에 **세 가지가 다 있다**",
      "Pluiz 를 닫으면" in _bg and "취소하려면" in _bg)
check("🔒 한계 고지 문구가 도구와 판정자에서 **같다**",
      "Pluiz 를 닫으면" in _bg and "Pluiz 를 닫으면" in _gm
      and '_PROMISE_NOTICE_MARK = "Pluiz 를 닫으면"' in _g)

try:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from core.graph import promise_notice_to_deliver
    turn = [HumanMessage(content="1분 뒤에 물 마시라고 알려줘"),
            AIMessage(content="", tool_calls=[{"name": "remind_me", "args": {}, "id": "1"}]),
            ToolMessage(content="✓ 1분 뒤에 '물 마시기' 라고 알려드릴게요.\n"
                                "⚠️ Pluiz 를 닫으면 이 알림도 사라져요.\n"
                                '취소하려면 "알림 취소해줘" 라고 말씀해 주세요.',
                        tool_call_id="1", name="remind_me"),
            AIMessage(content="1분 뒤에 알려드릴게요.")]
    got = promise_notice_to_deliver(turn)
    check("🚨 고지 **원문**이 나온다 (23자로 줄지 않는다)",
          got is not None and "Pluiz 를 닫으면" in got and "취소하려면" in got,
          repr(got)[:60])

    reject = [HumanMessage(content="알려줘"),
              AIMessage(content="", tool_calls=[{"name": "remind_me", "args": {}, "id": "1"}]),
              ToolMessage(content='✗ 언제 알려드릴까요? (예: "30분 뒤에")',
                          tool_call_id="1", name="remind_me")]
    check("🔑 **되묻는 말은 가로채지 않는다** — 그대로 내보내면 대화가 끊긴다",
          promise_notice_to_deliver(reject) is None)
except Exception as e:                                        # noqa: BLE001
    check("promise_notice_to_deliver 를 실제로 부른다", False, f"{type(e).__name__}: {e}")


# ═══ ④ BL-76 — 내용 없이 덮어쓰면 파일이 비워지지 않는다 ══════════════
print("\n=== ④ BL-76 — 내용 없는 덮어쓰기를 막는다 ===")
_fs = _src("tools/filesystem.py")
check("`content` 가 **기본값 없는 인자**다",
      "def overwrite_file(name: str, content: str, location: str" in _fs)
check("🔑 함수 안에서도 **한 번 더** 막는다 (스키마만 믿지 않는다)",
      'if not (content or "").strip():' in _fs)
check("막을 때 **되묻는다** — 조용히 실패하지 않는다",
      "무슨 내용으로 덮어쓸까요" in _fs)
check("🚨 빈 파일을 일부러 만들려던 경우의 길도 알려준다",
      "빈 파일로 만들려던 거라면" in _fs)

try:
    from tools.filesystem import overwrite_file
    out = overwrite_file.invoke({"name": "회의록.txt", "content": "   "})
    check("🔒 실제로 불러도 **안 쓴다**", out.startswith("✗"), repr(out)[:80])
except Exception as e:                                        # noqa: BLE001
    check("overwrite_file 을 실제로 부른다", False, f"{type(e).__name__}: {e}")


# ═══ ⑤ BL-79 — 백그라운드가 되묻고 끝나지 않는다 ══════════════════════
print("\n=== ⑤ BL-79 — 뒤에서 도는 일은 되묻지 않는다 ===")
check("지시문이 «되물을 수 없다»를 말한다", "되물을 수 없어요" in _bg)
check("«가정하고 진행하라»고 말한다", "합리적으로 가정하고 진행한 뒤" in _bg)
check("🔑 **지시만으로 안 막는다** — 되물으면 1회 재시도한다", "_BG_RETRY" in _bg)
check("🚨 두 번째도 되물으면 **성공으로 안 닫는다**",
      "맡기신 일을 끝내지 못했어요" in _bg)
check("판정이 **문장부호만** 본다 (정규식에 해석을 안 맡긴다)",
      'return t.endswith("?") or t.endswith("？")' in _bg)

try:
    from tools.background import _is_question
    check("되물음 판정이 실제로 돈다",
          _is_question("어떤 지역의 전기차 보조금을 찾아드릴까요?") is True
          and _is_question("서울·부산·대구 보조금을 정리했어요.") is False)
except Exception as e:                                        # noqa: BLE001
    check("_is_question 을 실제로 부른다", False, f"{type(e).__name__}: {e}")


# ═══ ⑥ 달력이 «확인할 수 없는 말»을 하지 않는다 (BL-80 ⓑ) ═════════════
#
# 🔑 09-30 실기에서 «다른 달력에 있다»는 진단 자체는 **재현되지 않았다.**
#   그래도 우리가 읽는 것은 `primary` 하나뿐이라, «일정이 없어요»는
#   **확인 범위를 넘어서는 말**이다. 그 부분만 고쳤다.
print("\n=== ⑥ 달력은 자기가 본 것만 말한다 ===")
_cal = _src("tools/calendar.py")
check("«일정이 없어요» 라고 단정하지 않는다",
      '✓ {when} 일정이 없어요.' not in _cal)
check("🔑 **무엇을 봤는지** 말한다", "기본 달력에는 일정이 없어요" in _cal)
check("못 본 것이 있다는 것도 말한다", "다른 달력에 있는 일정은 제가 볼 수 없어요" in _cal)
check("🔒 «못 읽었다»와 «없다»를 가르던 기존 그물은 그대로다",
      "캘린더를 읽지 못했어요" in _cal)


# ═══ ⑦ 감시가 창의 «원래 있던 것»을 세지 않는다 (09-30 실기 8번) ══════
#
# 🚨 *"메모장 지켜보다 글자 생기면 알려줘"* 에 Vision 이 상태 표시줄
#   (`줄 1, 열 1` · `Windows (CRLF)` · `UTF-8`)과 탭 이름을 「글자」로 셌다.
print("\n=== ⑦ 감시는 프로그램이 원래 달고 있는 것을 안 센다 ===")
_vis = _src("tools/vision.py")
for name in ("상태 표시줄", "제목 표시줄", "탭 이름", "메뉴", "스크롤바", "작업 표시줄"):
    check(f"«{name}» 를 세지 말라고 **이름으로** 적혀 있다", name in _vis)
check("🔑 실제로 헷갈렸던 문구가 예시로 들어 있다",
      "Windows (CRLF)" in _vis and "UTF-8" in _vis and "줄 1, 열 1" in _vis)
check("봐야 할 곳을 **내용 영역**으로 못 박는다",
      "사용자가 내용을 넣는 영역" in _vis)
check("🚨 근거가 그 목록뿐이면 false 라고 한 번 더 못 박는다",
      "세지 마세요» 목록에 있는 것뿐이라면 그것도 false" in _vis)
check("🔒 기존 정직성 규칙은 그대로다 (근거 없는 true 는 true 가 아니다)",
      "detected가 true인데 무엇을 봤는지 말할 수 없다면 그건 false" in _vis)


# ═══ ⑧ 거부 응답도 **무엇을 취소했는지** 말한다 (09-30 확인 2번) ═══════
#
# 🚨 승인 질문은 09-30 에 도구별로 갈랐는데 **거부 응답은 안 갈랐다.**
#       👤 주간보고.txt 를 문서 폴더로 옮겨줘
#       🤖 '주간보고.txt' 파일을 옮길까요? (원래 자리에서는 없어져요)   ← 맞다
#       👤 (거부)  →  🤖 네, 삭제를 취소했어요.                       ← 🚨 거짓
#   사용자: *"내가 언제 삭제하라고 했어."* — **하지도 않은 일을 취소했다**고 말한 것이다.
print("\n=== ⑧ 거부 응답이 «삭제»로 못 박혀 있지 않다 ===")
check("`cancel_noun` 이 있다", "def cancel_noun(calls)" in _g)
check("🚨 «네, 삭제를 취소했어요.» 가 **사라졌다**",
      '"네, 삭제를 취소했어요."' not in _g)
check("취소 명사를 **상태로 나른다** (플래그만으로는 «무엇이»를 모른다)",
      "cancelled_noun: str" in _g and 'state.get("cancelled_noun")' in _g)
check("🔒 턴을 넘어 새지 않게 초기화한다", _g.count('"cancelled_noun": ""') >= 8)

try:
    from core.graph import cancel_noun
    check("옮기기를 거부하면 «옮기기»라고 한다",
          cancel_noun([{"name": "move_file"}]) == "옮기기")
    check("이름변경은 «이름 바꾸기»",
          cancel_noun([{"name": "rename_file"}]) == "이름 바꾸기")
    check("🔑 삭제는 **예전 그대로** «삭제» (말을 바꾼 게 아니다)",
          cancel_noun([{"name": "delete_file"}]) == "삭제")
    check("덮어쓰기·클릭·강제종료도 각자 이름이 있다",
          cancel_noun([{"name": "overwrite_file"}]) == "덮어쓰기"
          and cancel_noun([{"name": "click_ui_element"}]) == "클릭"
          and cancel_noun([{"name": "force_close_app"}]) == "강제 종료")
    check("모르는 것은 «실행» — 지어내지 않는다",
          cancel_noun([{"name": "무언가_새_도구"}]) == "실행" and cancel_noun([]) == "실행")
except Exception as e:                                        # noqa: BLE001
    check("cancel_noun 을 실제로 부른다", False, f"{type(e).__name__}: {e}")

check("🚨 이름변경 문구에 조사가 겹치지 않는다 («파일을 이름을»)",
      "의 이름을 바꿀까요" in _g and "_join_targets(renames)" not in _g)


# ═══ ⑨ 메일 본문에 CSS 가 섞이지 않는다 (09-30 확인 4번) ══════════════
#
# 🚨 태그만 걷어내던 한 줄 때문에 `<style>` **속 내용**이 본문으로 남았다.
#   «'테스트다' 메일 내용은 "p{margin-top:0px;margin-bottom:0px;}" 입니다»
#   🔑 메일 읽기는 **소리로 나가는** 기능이라 CSS 를 귀로 듣게 된다.
print("\n=== ⑨ 메일 본문은 사람이 읽을 것만 남는다 ===")
_gm2 = _src("tools/gmail.py")
check("`<style>`·`<script>` 를 **통째로** 버린다",
      "_DROP_BLOCKS" in _gm2 and "style|script|head|title" in _gm2)
check("줄바꿈을 살린다 (문단이 한 줄로 안 붙는다)", "_BREAKS" in _gm2)
check("HTML 기호를 풀어 준다 (&nbsp; &amp;)", "unescape" in _gm2)

try:
    from tools.gmail import _html_to_text
    got = _html_to_text(
        "<html><head><style>p{margin-top:0px;margin-bottom:0px;}</style></head>"
        "<body><p>테스트다</p></body></html>")
    check("🚨 실기에서 나갔던 그 CSS 가 **안 남는다**", got == "테스트다", repr(got))
    check("본문이 여러 줄이면 줄이 살아 있다",
          _html_to_text("<div>안녕하세요<br>반갑습니다</div>") == "안녕하세요\n반갑습니다")
    check("&nbsp; · &amp; 가 글자로 바뀐다",
          _html_to_text("<p>A&nbsp;B &amp; C</p>") == "A B & C")
except Exception as e:                                        # noqa: BLE001
    check("_html_to_text 를 실제로 부른다", False, f"{type(e).__name__}: {e}")


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
