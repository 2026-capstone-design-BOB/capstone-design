"""
Pluiz Graph (M1-P1.5) — 명시적 LangGraph StateGraph
===================================================
기존 core/agent.py(create_react_agent + 수동 if/return 전처리)를 대체할
차세대 파이프라인. 모든 경로(보안·캐시·라우터·LLM)가 **단일 상태(messages)**를
공유·갱신하므로 맥락이 근본적으로 통합된다.

설계 원칙:
- 의존성 주입(DI): llm / tools / 보안검사 / fast_path 해석기를 인자로 받는다.
  → Windows·LLM API 없이도 mock으로 그래프 로직을 단위 테스트할 수 있다.
  → 기존 agent.py는 건드리지 않고 병행 제작(점진 전환·롤백 가능).
- 동기 노드(sync): langgraph interrupt가 sync invoke에서만 안정 동작하므로 노드는 동기.
  오케스트레이터가 graph.invoke를 워커 스레드(asyncio.to_thread)로 실행해 루프를 막지 않음.

노드 구성:
    START → input_guard → fast_path ─(hit)→ output_guard → END
                              │
                            (miss)
                              ▼
                            agent ⇄ tools → output_guard → END
                                     └─(못 믿을 도구)→ visual_verify ─┐
                                                                     └→ agent
    input_guard 차단 시 → output_guard → END (사유 응답만)

    visual_verify는 type_text·open_app처럼 **거짓 성공이 실측된 도구**의 결과를
    화면으로 확인해 증거를 붙인다(Phase 2). visual_check 미주입 시 노드 자체가 없다.

핵심(맥락 버그 해결):
    fast_path가 캐시/라우터로 명령을 처리해도, 그 결과를 AIMessage로
    state.messages에 append 한다. 따라서 다음 턴의 LLM이 이전 명령을 볼 수 있다.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional, Any
from datetime import datetime

from core.logger import get_logger
# 복합 명령 감지는 fast_path에 이미 있다(BL-15 때 만든 것). 여기서 다시 쓰지 않는다 —
# 두 벌이 되면 한쪽만 고쳐진다. (core.fast_path는 core.logger 외에 아무것도 끌어오지 않는다)
from core.fast_path import has_negation, is_compound_command
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage, AnyMessage, trim_messages,
)


# ── HITL: 위험 도구 정의 & 승인 해석 (P2) ─────────────────────────
# 이 도구 호출은 실행 전 hitl 노드에서 사용자 승인을 받는다.
_log = get_logger("Graph")

# click_ui_element: 클릭은 되돌릴 수 없고, 좌표는 Vision의 **추정**이다.
# 무엇을 어디서 누를지 사용자가 보고 승인해야 한다. (2026-09-03)
DANGEROUS_TOOLS = {"delete_file", "delete_folder", "click_ui_element"}

# ── 실행 결과 시각적 검증: **못 믿을 도구** 정의 (Phase 2) ─────────
# 위가 "위험해서 멈추는 도구"라면 여기는 **못 믿어서 확인하는 도구**다.
# 실행 직후 visual_verify 노드가 화면을 실제로 보고, 그 증거를 도구 결과에 붙인다.
#
# **거짓 성공이 실측됐고, 화면으로만 확인 가능한 것**만 넣는다:
#   type_text : BL-12 — pyautogui가 예외만 안 내면 "✓ 텍스트 입력 완료"를 반환한다.
#               2026-09-02 실측에서 도구는 "✓ 입력 완료", Vision은 "본문 0자"였다.
#
# ⚠️ describe_screen을 넣지 말 것 — 자기 자신을 검증하는 재귀가 된다.
# ⚠️ **open_app을 뺐다** (2026-09-03). 넣어 봤는데 물음에 답할 수 없는 검증이었다 —
#    `take_screenshot(window=앱)`은 그 창**만** 찍으므로, 이미지만 봐서는 그 창이
#    맨 앞인지 뒤에 가려져 있는지 Vision이 알 수 없다. "앞에 있나요?"라고 물어놓고
#    답할 수 없는 그림을 준 셈이다. 창이 앞에 있는지는 Win32로 즉시·정확히 알 수 있고
#    (`open_app`이 이미 `_focus_window()` 결과로 판단한다) 8초도 안 든다.
#    **Vision은 Win32로 알 수 없는 것에만 쓴다.**
# ⚠️ 하나 늘릴 때마다 그 도구를 쓴 **모든 턴이 Vision 1회(약 8초) 느려진다.**
#    실측 근거 없이 늘리지 말 것.
VISUAL_VERIFY_TOOLS = {"type_text"}

_REJECT_RE = re.compile(r'아니|취소|하지\s*마|하지마|싫|안\s*돼|안돼|관둬|그만|멈춰|ㄴㄴ|말아')

# 승인으로 인정하는 어휘. **부분 문자열 검사를 하지 않는다.**
#
# ⚠️ 예전에는 r'응|네|예|그래|해\s*줘|진행|…' 을 search() 로 훑었는데, 그러면
#    승인 대기 중에 사용자가 말한 **평범한 명령이 승인으로 읽혔다**:
#      "네이버 열어줘"(네) · "음소거 해줘"(해 줘) · "그래프 그려줘"(그래)
#      "진행 상황 알려줘"(진행) · "응용 프로그램 목록"(응) · "예약 확인해줘"(예)
#    실측 결과 일상 명령 10개 중 6개가 오승인 → 삭제가 그대로 실행됐다.
#    "애매하면 취소"라는 안전 기본값이 무력화된 것이다.
#
# 그래서 지금은 **발화를 어절로 쪼개, 모든 어절이 긍정어일 때만** 승인으로 본다.
#   "응" · "네 삭제해줘" · "오케이 지워"        → 승인
#   "네이버 열어줘" · "음소거 해줘"             → 승인 아님(→ other_command)
_AFFIRM_WORDS = frozenset([
    "응", "어", "네", "넵", "예", "옙", "그래", "그럼", "좋아", "좋아요",
    "오케이", "콜", "ok", "okay", "yes", "y", "ㅇㅇ", "알겠어", "알았어",
    "알겠습니다", "맞아", "맞어", "그렇게", "해", "해줘", "해주세요", "돼", "된다",
    "삭제", "삭제해", "삭제해줘", "지워", "지워줘", "진행", "진행해", "승인",
    # 삭제 승인의 변형들. STT는 "지워 버려"·"삭제해 봐"처럼 띄어서 적어 오는데,
    # _JOIN_AUX_RE가 붙여 준 뒤 여기서 걸린다.
    "지워버려", "지워버려요", "지워봐", "삭제해버려", "삭제해봐", "해버려",
    "없애", "없애줘", "치워", "치워줘", "웅", "네네", "응응", "그래그래",
    "삭제해주세요", "지워주세요", "없애주세요", "삭제하세요", "지우세요",
])
_TOKEN_SPLIT_RE = re.compile(r'[\s,.!?~…·]+')

# 보조용언 앞의 띄어쓰기를 붙인다. 사람은 "지워 줘"라고 말하고 STT도 그렇게 적는데,
# 어절로 쪼개면 "지워" + "줘"가 되어 "줘"가 긍정어 목록에 없다는 이유로 승인이 깨졌다.
#
# ⚠️ 실기에서 이것 때문에 **승인이 무한 루프**를 돌았다 (2026-09-02):
#     "응 지워 줘"        → other_command 로 오분류 → 삭제 취소 후 재실행
#     "그래 정말 삭제해 줘" → 같은 이유로 또 취소
#   사용자는 네 번을 말하고 나서야 삭제됐다. ("내 말이 말 같지가 않아")
_JOIN_AUX_RE = re.compile(r'(\S)\s+(줘|줄래|주라|주세요|주시겠어요|봐|버려|버려요|둬)\b')

# 승인의 세기를 더할 뿐 의미를 바꾸지 않는 말. **이것만 있으면 승인이 아니다.**
# ("정말?" 한 마디를 승인으로 읽으면 안 되므로, 걷어낸 뒤 핵심 긍정어가 남아야 한다)
_FILLER_WORDS = frozenset([
    "정말", "진짜", "그냥", "빨리", "당장", "어서", "얼른", "좀", "다",
    "지금", "제발", "이제", "그", "저", "음", "아", "일단", "그리고",
])

# 명령형 어미. "승인도 거부도 아닌데 **명백히 다른 명령**"을 가려내는 데 쓴다.
#
# ⚠️ 왜 필요한가 — 오승인을 막으려다 반대편으로 넘어갔던 흔적이다.
#    승인 대기 중에 "네이버 열어줘"라고 하면 옛날엔 승인으로 읽혀 **삭제됐고**,
#    그걸 고친 뒤에는 unclear로 처리돼 **재질문만 하고 명령을 삼켰다.**
#    실기에서 사용자가 같은 말을 두 번 해야 했다:
#      "네이버 열어줘"      → (삭제할까요? 다시 질문)
#      "네이버 열어 달라니까" → ✓ 네이버 열림
#    승인도 거부도 아니면서 **명령의 꼴을 갖췄으면** 삭제를 취소하고 그 명령을 실행한다.
#
# 오분류의 방향이 안전하다: 명령으로 잘못 봐도 **삭제는 취소되는 쪽**이다.
# 그래서 조금 느슨해도 된다. 다만 STT 잡음("베이", "지호 맘몬")까지 명령으로 보면
# 재질문 기회를 잃으므로, **2어절 이상 + 명령형 어미**를 함께 요구한다.
_COMMAND_TAIL_RE = re.compile(
    r'(줘|줄래|주라|주세요|주실래|줄레|달라|달라니까|다오|해라|하렴|보여|알려|'
    r'봐|봐라|보자|틀어|찾아|열어|닫아|켜라|꺼라|실행|시작|종료|검색)\s*$'
)


def _looks_like_command(tokens: list[str], text: str) -> bool:
    """승인 응답이 아니라 **새 명령**으로 보이는가."""
    if len(tokens) < 2:
        return False
    return bool(_COMMAND_TAIL_RE.search(text))


def classify_confirmation(text: Any) -> str:
    """승인 응답을 4분류한다: 'approve' | 'reject' | 'other_command' | 'unclear'.

    - 'other_command'는 승인도 거부도 아니지만 **명백히 다른 명령**이다.
      hitl 노드가 삭제를 취소하고 **그 명령을 실행**한다. 재질문하면 사용자가
      같은 말을 두 번 해야 한다(실기에서 실제로 겪었다).
    - 'unclear'는 알아들을 수 없는 답이다 — hitl 노드가 다시 물어본다.
      예전처럼 bool 두 갈래로 강제하면 삭제가 실행되거나 명령이 조용히 사라진다.
    """
    t = str(text).strip().lower()
    if not t:
        return "unclear"
    if _REJECT_RE.search(t):          # 거부어 우선 (모순 시 안전한 쪽)
        return "reject"

    # "지워 줘" → "지워줘" 로 붙인 뒤 어절을 나눈다 (위 _JOIN_AUX_RE 주석 참조)
    t = _JOIN_AUX_RE.sub(r'\1\2', t)
    tokens = [w for w in _TOKEN_SPLIT_RE.split(t) if w]

    # 강조어("정말"·"그냥"…)를 걷어내고 **남은 말이 전부 긍정어일 때만** 승인.
    core = [w for w in tokens if w not in _FILLER_WORDS]
    if core and all(w in _AFFIRM_WORDS for w in core):
        return "approve"
    if _looks_like_command(tokens, t):
        return "other_command"
    return "unclear"


def interpret_confirmation(text: Any) -> bool:
    """승인 여부(bool). 승인이 **명확할 때만** True. 애매하면 False(안전).

    4분류가 필요하면 `classify_confirmation`을 쓴다.
    """
    return classify_confirmation(text) == "approve"


def _deletion_is_recoverable() -> bool:
    """삭제가 휴지통으로 가는지(복구 가능) 여부.

    `tools/filesystem.py`의 `_to_trash()`는 send2trash 가 없으면 조용히
    os.remove / shutil.rmtree 로 폴백해 **영구 삭제**한다. 사용자는 승인 시점에
    그 차이를 알아야 하므로 여기서 미리 확인한다. (P3-3 정직 보고)
    """
    try:
        import send2trash  # noqa: F401
        return True
    except Exception:
        return False


def _target_name(dcall: Optional[dict]) -> str:
    """위험 도구 호출에서 사용자에게 보여줄 대상 이름(경로의 마지막 조각)."""
    if not dcall:
        return ""
    args = dcall.get("args", {}) or {}
    target = args.get("file_path") or args.get("folder_path") or ""
    return os.path.basename(str(target).rstrip("/\\")) or str(target)


def _confirm_question(dcall: Optional[dict]) -> str:
    """위험 도구 호출로부터 승인 질문 문구 생성.

    승인 '전에' 되돌릴 수 있는지를 알려준다. 휴지통이면 복구 가능하다고,
    영구 삭제면 복구 불가라고 명확히 구분한다.
    """
    if _deletion_is_recoverable():
        consequence = "휴지통으로 갑니다"
    else:
        consequence = "⚠️ 휴지통을 거치지 않고 영구 삭제돼요. 복구할 수 없어요"

    if not dcall:
        return f"정말 실행할까요? ({consequence})"
    name = dcall.get("name", "")
    args = dcall.get("args", {}) or {}

    # 클릭은 삭제와 결과가 달라 문구도 달라야 한다. "휴지통으로 갑니다"는 거짓이 된다.
    # 좌표는 아직 모른다 — 도구가 실행될 때 화면을 보고 정하기 때문이다.
    # 그래서 **무엇을 어디서** 누를지만 알린다.
    if name == "click_ui_element":
        what = str(args.get("target", "")).strip() or "화면의 어떤 것"
        where = str(args.get("window", "")).strip()
        place = f"'{where}' 창에서 " if where else ""
        return (f"{place}'{what}'을(를) 찾아서 클릭할까요? "
                "(클릭은 되돌릴 수 없어요)")

    target = args.get("file_path") or args.get("folder_path") or ""
    # 조사 하드코딩('을(를)') 금지 — 대상이 둘뿐이라 각각 맞는 조사를 쓴다.
    # ("파일"은 ㄹ 받침 → 을 / "폴더"는 받침 없음 → 를)
    kind = "폴더를" if name == "delete_folder" else "파일을"
    return f"'{_target_name(dcall)}' {kind} 정말 삭제할까요? ({consequence})"


# 승인 대기 중 애매한 답이 왔을 때 다시 묻는 최대 횟수(첫 질문 포함).
# 2를 넘기면 사용자를 붙잡아 두는 꼴이라, 그 다음은 취소로 끝낸다.
_MAX_CONFIRM_ASKS = 2


def _reask_question(dcall: Optional[dict]) -> str:
    """애매한 답이 왔을 때의 재질문. 무엇을 물었는지 다시 알려준다."""
    return (f"{_confirm_question(dcall)} "
            "진행하려면 '네', 그만두려면 '아니오'라고 말씀해 주세요.")


# ── 상태 정의 ──────────────────────────────────────────────────────
class PluizState(MessagesState):
    """messages(add_messages reducer) + 라우팅 결정 필드.

    decision: input_guard/fast_path가 다음 경로를 지시하는 임시 신호.
              'blocked' | 'fast_hit' | 'to_agent'
    """
    decision: str
    # 승인 대기 중에 다른 명령이 들어와 삭제를 취소했을 때 세운다.
    # output_guard가 최종 응답 앞에 "삭제는 취소했어요"를 붙인다 — 이걸 안 알리면
    # 사용자는 삭제가 어떻게 됐는지 모른 채 새 명령의 결과만 보게 된다.
    deletion_cancelled: bool
    # 이번 턴에 화면 검증(visual_verify)을 이미 한 번 했는지.
    # Vision 1회가 약 8초라 **턴당 1회**로 묶는다. deletion_cancelled와 같은 이유로
    # input_guard가 새 턴 시작 시 끈다 — 플래그가 턴을 넘어 새면, 다음 턴의 type_text가
    # 검증 없이 통과한다(앞선 R-2 사고와 같은 계열).
    visual_verified: bool
    # 이번 턴에 실행하기로 한 단계들(M3). [] = 계획 없음 = 오늘과 완전히 같은 단일 루프.
    # plan_cursor >= len(plan) 이면 계획이 끝난 것이다.
    #
    # ⚠️ **리듀서(Annotated[..., operator.add])를 붙이지 말 것.** 붙이면 planner의 쓰기가
    #   '교체'가 아니라 '누적'이 되어 **지난 턴 계획이 이번 턴 뒤에 이어 붙는다.**
    #   messages 외의 필드는 기존 셋과 같이 마지막 쓰기가 이긴다.
    plan: list[str]
    plan_cursor: int


# ── 시스템 프롬프트 (날짜 갱신) ───────────────────────────────────
_MAX_HISTORY_MSGS = 20


def build_system_prompt() -> str:
    now = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    date_str = f"{now.year}년 {now.month}월 {now.day}일 ({weekdays[now.weekday()]})"
    time_str = f"{now.hour:02d}:{now.minute:02d}"
    return (
        "당신은 Pluiz(플루이즈)입니다. 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트예요.\n"
        f"현재 날짜/시간: {date_str} {time_str}\n"
        "응답은 1~2문장으로 짧고 친근한 구어체로. 도구 실행 결과는 핵심만 요약.\n"
        "PC 제어 명령은 반드시 도구를 호출해서 실행하고, 도구 없이 '실행했어요'라고만 답하지 마세요.\n"
        # 삭제는 시스템(hitl 노드)이 반드시 확인을 받는다. LLM이 먼저 되물으면
        # 사용자가 같은 말을 두 번 해야 한다 — 실기에서 실제로 겪은 불편이다.
        "삭제 요청을 받으면 '삭제할까요?'라고 되묻지 말고 바로 삭제 도구를 호출하세요. "
        "확인 절차는 시스템이 자동으로 진행합니다.\n"
        # target 없이 부르면 '그때 포커스된 창'에 들어간다 — 실기에서 Pluiz 자기
        # 입력창에 글자가 들어간 적이 있다(BL-12).
        "type_text로 글자를 입력할 땐 target에 **어느 앱에 넣을지**를 반드시 주세요"
        "(예: target=\"메모장\"). 그래야 그 창이 앞에 온 걸 확인하고 입력합니다. "
        "'✗ …입력하지 않았습니다'가 오면 입력이 **안 된 것**이니 됐다고 하지 마세요.\n"
        # 창 규칙: 기본은 기존 창 재사용. "새로/하나 더/새 탭"일 때만 new=True.
        "앱을 열 땐 open_app을 그대로 부르세요(이미 켜져 있으면 그 창을 앞으로 가져옵니다). "
        "사용자가 '새로 열어줘'·'하나 더'·'새 탭'처럼 새 창/탭을 원할 때만 new=True를 주세요.\n"
        # 감시는 사용자가 안 보는 동안 화면을 반복 전송한다. LLM이 스스로 켜면
        # 사용자는 켜진 줄도 모른 채 화면이 나간다 — 그래서 요청이 명시적일 때만 쓴다.
        #
        # ⚠️ **금지문을 앞에 두지 말 것** (BL-19). 예전 문장은 "…할 때만 쓰세요.
        #    스스로 판단해서 시작하지 마세요."로 시작해, 모델이 안전한 쪽
        #    = **아무것도 안 하고 말로만 답하는 쪽**으로 기울었다. 실기에서
        #    "메모장 지켜보다가 오류 뜨면 알려줘"에 도구를 하나도 부르지 않고
        #    "지켜보다가 알려드릴게요!"라고 답했다. 아무도 안 보고 있었다.
        #    지금은 **해야 할 일이 먼저**, 제약이 뒤다.
        "'~하면 알려줘'·'~되면 알려줘'처럼 앞으로 생길 일을 알려달라고 하면 "
        "반드시 watch_screen을 호출하세요. 도구를 부르지 않고 '지켜볼게요'라고만 "
        "답하면 실제로는 아무도 화면을 보고 있지 않습니다.\n"
        "'그만 봐'·'감시 그만'처럼 중단을 요청하면 반드시 stop_watching을 호출하세요. "
        "부르지 않고 '중단했어요'라고 답하면 감시는 계속 돕니다. "
        "(다만 사용자가 요청하지 않았는데 스스로 감시를 시작하지는 마세요.)\n"
        "이전 대화 맥락을 활용하세요. '그거', '아까 그거' 같은 지칭은 직전 대화를 참고해 해석하세요.\n"
        "사용자가 '안 됐어/안 열렸어/실행 안 됨'처럼 실패를 알리면, 같은 답을 반복하지 말고 "
        "get_running_apps로 실제 실행 여부를 확인한 뒤 다른 방법으로 다시 시도하세요. "
        "정말 안 되면 솔직하게 '안 됐다'고 말하고, 됐는지 불확실하면 확실한 척하지 마세요.\n"
        "응답은 항상 한국어로 해요."
    )


# ── 메시지 유틸 ────────────────────────────────────────────────────
def _msg_text(m: Any) -> str:
    """메시지/블록 리스트의 텍스트를 평문으로 추출."""
    c = getattr(m, "content", m)
    if isinstance(c, list):
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in c
        ).strip()
    return str(c)


def _prepare_messages(history: list[AnyMessage]) -> list[AnyMessage]:
    """LLM 호출용 메시지 구성: 시스템 프롬프트(매번 갱신) + 최근 N개 히스토리.

    ※ 단순 슬라이스(convo[-N:])는 (도구호출 AIMessage ↔ ToolMessage) 쌍을 중간에서
      잘라 깨진 시퀀스를 만들 수 있고, Gemini가 이를 400(INVALID_ARGUMENT)으로 거부한다.
      → trim_messages(start_on="human")으로 항상 사람 발화부터 시작하는 유효 시퀀스 보장.
    """
    system = SystemMessage(content=build_system_prompt())
    convo = [m for m in history if not isinstance(m, SystemMessage)]
    try:
        trimmed = trim_messages(
            convo,
            max_tokens=_MAX_HISTORY_MSGS,
            strategy="last",
            token_counter=len,          # 토큰 수가 아닌 '메시지 개수' 기준
            start_on="human",           # 항상 HumanMessage로 시작 → 고아 ToolMessage 방지
            include_system=False,       # 시스템 메시지는 위에서 별도 부착
            allow_partial=False,
        )
    except Exception as e:
        print(f"[graph._prepare_messages] trim 실패, fallback: {e}")
        # 최소 방어: 앞쪽의 고아 ToolMessage/도구호출 AIMessage 제거
        trimmed = convo[-_MAX_HISTORY_MSGS:]
        while trimmed and (
            isinstance(trimmed[0], ToolMessage)
            or (isinstance(trimmed[0], AIMessage) and getattr(trimmed[0], "tool_calls", None))
        ):
            trimmed = trimmed[1:]
    return [system] + trimmed


def _last_human_text(messages: list[AnyMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return _msg_text(m)
    return ""


def current_turn_messages(messages: list[AnyMessage]) -> list[AnyMessage]:
    """**이번 턴**의 메시지만 반환한다 (마지막 HumanMessage부터 끝까지).

    ⚠️ 왜 필요한가 —
    `state["messages"]`는 이번 턴이 아니라 **그 thread의 전체 히스토리**다
    (MemorySaver + add_messages 리듀서). fast_path 결과까지 messages 하나로
    모은 것이 맥락 붕괴를 고친 핵심 설계인데(= 지우면 안 되는 구조),
    그 대가로 "이번 턴"과 "지금까지 전부"의 경계가 사라졌다.

    경계를 잃은 채 전체를 훑으면 이런 일이 난다:
      - 턴1의 도구 오류가 턴5의 정상 응답을 "실행 중 문제가 생겼어요"로 덮어씀
      - 턴1의 도구 호출이 턴2의 잡담에 붙어 엉뚱한 캐시 학습이 일어남
    따라서 "이번 턴의 결과"를 판단하는 쪽은 반드시 이 함수를 거친다.

    ※ HITL 재개(Command(resume))는 HumanMessage를 추가하지 않으므로,
      승인 후에도 턴의 시작점은 원래 명령("…삭제해줘") 그대로다 — 의도한 동작이다.
    """
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return list(messages[i:])
    return list(messages)


# ── 출력 검증 (T04 + 빈응답 복구) — output_guard의 순수 로직 ─────────
_TOOL_ERROR_RE = re.compile(
    r'^\[(?:오류|error|[가-힣a-zA-Z_]+ 오류)\]'
    r'|^오류\s*:'
    r'|^Error\s*:',
    re.IGNORECASE,
)
_SUCCESS_LIKE_RE = re.compile(
    r'(?<!못)(?:했어요|켰어요|열었어요|닫았어요|실행했어요|설정했어요|만들었어요|저장했어요|됐어요|완료했어요|완료)[!.]?\s*$'
)


# LLM 응답이 비었고 **이번 턴에 실행된 도구도 없을 때** 쓰는 말.
#
# ⚠️ 예전엔 여기서 "명령을 실행했습니다."라고 답했다. 그건 **거짓말이다** —
#    이 자리에 오면 아무 일도 일어나지 않았다. 2026-09-03 실기에서 실제로
#    "메모장 새로 열어줘"에 "명령을 실행했습니다"라고 답해 놓고 새 탭은 안 열렸고,
#    사용자가 "안 됐는데"라고 해서야 다시 시도해 열렸다.
#    도구가 거짓 성공을 보고하던 것(BL-12)과 **같은 계열의 결함**이다.
_NOTHING_HAPPENED_MSG = "죄송해요, 방금 건 처리하지 못했어요. 다시 한 번 말씀해 주시겠어요?"


def verify_output(messages: list[AnyMessage]) -> Optional[str]:
    """도구 실행 결과를 검증해 필요 시 보정 텍스트를 반환한다.

    - 마지막 AI 응답이 비어 있으면 → 마지막 ToolMessage 내용으로 복원.
    - 도구 오류가 있는데 AI가 성공처럼 응답했으면 → 오류 내용으로 교체.
    - 보정 불필요하면 None.

    (agent.py의 빈응답 복구 + T04 로직을 노드용 순수 함수로 이관)

    ⚠️ 판단 범위는 **이번 턴뿐이다**(`current_turn_messages`). 전체 히스토리를 훑으면
      과거 턴의 도구 오류가 지금의 성공 응답을 덮어쓰고, 빈 응답 복구가 몇 턴 전
      ToolMessage를 끌어온다.
    """
    turn = current_turn_messages(messages)

    # 마지막 AIMessage(응답) 추출
    response = ""
    for m in reversed(turn):
        if isinstance(m, AIMessage):
            response = _msg_text(m)
            break

    # 도구 오류 수집 (이번 턴에 실행된 것만)
    tool_errors: list[str] = []
    for m in turn:
        if isinstance(m, ToolMessage):
            c = _msg_text(m).strip()
            if _TOOL_ERROR_RE.match(c):
                tool_errors.append(c)

    # 1) 빈 응답 → 이번 턴의 ToolMessage에서 복원
    if not response.strip():
        for m in reversed(turn):
            if isinstance(m, ToolMessage):
                c = _msg_text(m).strip()
                if c:
                    return c
        # 도구도 안 돌고 응답도 없다 = **아무 일도 없었다.** 됐다고 하지 않는다.
        return _NOTHING_HAPPENED_MSG

    # 2) 도구 오류 + 성공처럼 보이는 응답 → 오류로 보정
    if tool_errors and _SUCCESS_LIKE_RE.search(response):
        clean = re.sub(r'^\[[^\]]+\]\s*', '', tool_errors[0]).strip() or tool_errors[0]
        return f"실행 중 문제가 생겼어요: {clean}"

    return None


# ── 화면 감시 정직성 (BL-19) ───────────────────────────────────────
#
# 감시는 이 프로젝트에서 드물게 **진실이 싸게 확인되는** 기능이다 — 모니터가
# 자기가 켜졌는지 알고 있다. 그래서 말이 아니라 **상태**로 검사한다.
#
# 2026-09-04 실기에서 두 가지가 한꺼번에 드러났다:
#   ① 도구를 하나도 안 부르고 "지켜보다가 알려드릴게요!"라고 답했다 (아무도 안 봤다)
#   ② 고쳐서 도구가 불린 뒤엔, LLM이 **고지를 요약해 삼켰다** —
#      "5초마다 · 최대 10분 · '그만 봐'"가 사라지고 "알려드릴게요!"만 남았다.
# ②가 특히 중요하다. 감시를 **승인이 아니라 고지**로 하기로 한 근거가 고지 자체다
# (DEVLOG 2026-09-03 「설계 전에 정한 것 4가지」). 고지가 사라지면 그 근거가 무너진다.

_WATCH_NOTICE_MARK = "그만 봐"   # 시작 고지에만 들어가는 문구 (tools/vision._watch_notice)


def watch_notice_to_deliver(messages: list[AnyMessage]) -> Optional[str]:
    """이번 턴에 감시가 **시작됐으면** 그 고지 원문을 반환한다. 아니면 None.

    LLM이 요약하지 못하게 **도구가 만든 문장을 그대로** 사용자에게 보낸다.
    Vision의 답을 요약하지 않는 것과 같은 방침이다(DEVLOG 2026-09-03 § 정직성).
    """
    turn = current_turn_messages(messages)
    for m in reversed(turn):
        if isinstance(m, ToolMessage) and getattr(m, "name", "") == "watch_screen":
            c = _msg_text(m).strip()
            # 시작에 성공한 경우만. 거절(✗ 이미 …/꺼져 있어)은 LLM이 전해도 된다.
            if c.startswith("✓") and _WATCH_NOTICE_MARK in c:
                return c
            return None
    return None


# 무엇을 보고 거짓말이라고 판단하는가.
#
# **판정은 상태가 한다** — 도구가 0개 돌았고 모니터가 꺼져 있다는 두 사실이 전부
# 결정적이다. 아래 정규식들은 판정하지 않고 **범위만 좁힌다**:
#   ① 사용자가 감시를 요청한 턴인가  ② 응답이 해줬다고 말하는가
# 손으로 쓴 정규식이 이 프로젝트를 반복해서 무너뜨렸기에(BL-02 · BL-15 ·
# HITL 무한루프) 정규식에 판단을 맡기지 않는다.
#
# ⚠️ **응답 문구만 보면 안 된다.** 2026-09-04 실기에서 새어나간 거짓말은
#    "메모장에서 오류 메시지가 뜨면 바로 알려드릴게요!" 였다 — '지켜보'도 '감시'도
#    없다. 그래서 범위는 **사용자 입력**으로 잡는다. 무엇을 요청했는지가
#    어떻게 답했는지보다 안정적이다.
_WATCH_WORD_RE = re.compile(r'지켜보|감시')
_COND_RE = re.compile(r'뜨면|나오면|되면|생기면|끝나면|바뀌면|보이면|열리면|닫히면|완료되면')
_TELL_RE = re.compile(r'알려|말해|알림')
_STOP_REQUEST_RE = re.compile(r'그만\s*(봐|보지|볼래)|감시\s*(그만|중단|꺼)|안\s*봐도|그만 두')
# 응답이 "해줬다/해주겠다"고 말하는가.
_WATCH_ASSERT_RE = re.compile(r'게요|했어요|했습니다|멈췄|중단|시작했')

_WATCH_LIE_MSG = (
    "죄송해요, 화면 감시를 실제로 시작하지 못했어요. "
    '다시 한 번 "…하면 알려줘"라고 말씀해 주시겠어요?'
)
_STOP_LIE_MSG = "지금 지켜보고 있는 화면은 없어요."


def _is_watch_request(text: str) -> bool:
    """사용자가 '앞으로 생길 일을 알려달라'고 한 턴인가."""
    return bool(_WATCH_WORD_RE.search(text)
                or (_COND_RE.search(text) and _TELL_RE.search(text)))


# 감시 요청인데 도구를 안 불렀을 때 **한 번만** 다시 묻는 말.
#
# 왜 재시도가 필요한가: 2026-09-04 실측에서 `watch_screen` 호출률이
# **회차마다 크게 흔들렸다**(같은 시각 교차 측정에서 5회 중 2~4회). temperature=0인데도
# 그렇다. 프롬프트를 긍정문으로 고쳐 많이 나아졌지만 **확실해지지는 않는다.**
# 감시는 실패해도 사용자가 알아채기 어려운 기능이라(그래서 BL-19이 오래 숨었다)
# 한 겹을 더 둔다. 실패의 대가가 비대칭이다 — 안 켜졌는데 켜진 줄 알면 아무도 안 본다.
#
# ⚠️ **한 번만** 한다. 무한 재시도는 응답 지연을 그만큼 늘리고, HITL 무한루프
#    사고와 같은 계열의 위험이다. 두 번째도 실패하면 output_guard가 정직하게 말한다.
_WATCH_RETRY_DIRECTIVE = (
    "\n\n[중요] 사용자는 지금 화면 감시를 요청했습니다. "
    "watch_screen(또는 중단이면 stop_watching) 도구를 **반드시 지금 호출**하세요. "
    "도구를 부르지 않고 말로만 답하면 실제로는 아무 일도 일어나지 않습니다."
)


def needs_watch_retry(user_text: str, response: Any, *, watching: bool) -> bool:
    """감시 요청인데 도구를 안 불렀는가 — 한 번 더 물어볼 자리인지 판단한다.

    `detect_watch_lie`와 같은 신호를 쓰지만 시점이 다르다. 이건 **agent 노드 안**
    에서 아직 되돌릴 수 있을 때 보고, 저건 다 끝난 뒤 마지막 그물이다.
    """
    if getattr(response, "tool_calls", None):
        return False
    if not user_text.strip():
        return False
    if _STOP_REQUEST_RE.search(user_text):
        # 이미 꺼져 있으면 stop_watching을 안 불러도 결과가 같다 — 굳이 더 묻지 않는다.
        return watching
    return _is_watch_request(user_text) and not watching


def with_watch_directive(msgs: list[AnyMessage]) -> list[AnyMessage]:
    """재시도용 메시지 — 시스템 프롬프트에 지시를 덧붙인다.

    ⚠️ 시스템 메시지를 **뒤에 새로 붙이지 않는다.** Gemini는 시스템 지시를 따로
      받아서, 두 번째 SystemMessage는 무시되거나 400이 된다. 기존 것을 교체한다.
    """
    out = list(msgs)
    for i, m in enumerate(out):
        if isinstance(m, SystemMessage):
            out[i] = SystemMessage(content=_msg_text(m) + _WATCH_RETRY_DIRECTIVE)
            return out
    return [SystemMessage(content=_WATCH_RETRY_DIRECTIVE.strip())] + out


def detect_watch_lie(messages: list[AnyMessage], *, watching: bool) -> Optional[str]:
    """응답이 감시를 해줬다고 말하는데 **실제로는 아무 일도 없었으면** 정직한 말로 바꾼다.

    네 조건이 **모두** 맞을 때만 동작한다:
      ① 이번 턴에 실행된 도구가 0개            (상태 — 결정적)
      ② 모니터가 돌고 있지 않다                (상태 — 결정적)
      ③ 사용자가 감시/중단을 요청한 턴이다     (범위)
      ④ 응답이 해줬다고 말한다                 (범위)

    `watching`을 주입받는 이유: 이 모듈은 Windows도 모니터도 없이 mock으로 검증된다.

    ⚠️ **캐시 히트(fast_hit) 턴에는 부르지 말 것.** fast_path는 도구를 실제로
      실행하고도 messages에는 AIMessage 하나만 남긴다(절대규칙 2). 그래서 여기서는
      "도구 0개"로 보인다. output_guard가 decision을 보고 걸러낸다.
    """
    turn = current_turn_messages(messages)

    # ① 이번 턴에 도구가 하나라도 돌았으면 손대지 않는다.
    if any(getattr(m, "tool_calls", None) for m in turn):
        return None
    if any(isinstance(m, ToolMessage) for m in turn):
        return None

    # ② 진짜로 돌고 있으면 거짓말이 아니다.
    if watching:
        return None

    user_text = ""
    for m in turn:
        if isinstance(m, HumanMessage):
            user_text = _msg_text(m)
            break
    response = ""
    for m in reversed(turn):
        if isinstance(m, AIMessage):
            response = _msg_text(m)
            break
    if not response.strip() or not user_text.strip():
        return None

    # ④ 응답이 "해줬다"고 말하지 않으면(질문·거절·설명) 손대지 않는다.
    if not _WATCH_ASSERT_RE.search(response):
        return None

    # ③ 중단 요청이 먼저다 — "그만 봐"에는 시작 실패 안내가 아니라 현재 상태를 말해야 한다.
    if _STOP_REQUEST_RE.search(user_text):
        return _STOP_LIE_MSG
    if _is_watch_request(user_text):
        return _WATCH_LIE_MSG
    return None


def _monitor_is_watching() -> bool:
    """제품 경로에서 모니터 상태를 읽는다. 실패하면 '돌고 있다'고 본다.

    ⚠️ 실패 시 True인 게 안전하다 — False로 보면 멀쩡히 돌고 있는 감시를
      "시작하지 못했다"고 **거짓 교정**하게 된다. 모르면 손대지 않는 쪽이 맞다.
    """
    try:
        from core.screen_monitor import get_monitor
        return bool(get_monitor().status().get("active"))
    except Exception:
        return True


def extract_response(state: dict) -> str:
    """그래프 실행 결과 state에서 마지막 AIMessage 텍스트를 추출."""
    for m in reversed(state["messages"]):
        if isinstance(m, AIMessage):
            t = _msg_text(m)
            if t.strip():
                return t
    return ""


# ── 실행 결과 시각적 검증 (Phase 2) — visual_verify 노드의 순수 로직 ─
#
# **왜 이 층이 따로 필요한가.**
# 바로 위 verify_output()은 "도구가 [오류]를 반환했는데 AI가 성공처럼 답하는" 경우를
# 잡는다. 즉 **도구의 자기보고를 믿는다.** 그런데 이 프로젝트가 반복해서 데인 건
# 도구가 **거짓으로 ✓를 반환하는** 경우다(BL-12: 입력이 안 됐는데 "✓ 입력 완료").
# 그건 텍스트로는 알 수 없고 화면을 봐야 안다.
#
# ⚠️ 이 층은 **판정하지 않는다.** Vision의 답을 정규식으로 성공/실패로 접지 않고,
#    원문 증거를 도구 결과에 붙여 agent에게 넘긴다. 손으로 쓴 정규식이 이 프로젝트를
#    반복해서 무너뜨렸다(BL-02 부정어 오매칭 · BL-15 복합명령 절단 · HITL 승인 무한루프).
#    자동 재시도도 하지 않는다 — **정직하게 보고만** 한다.

_VISUAL_EVIDENCE_PREFIX = "[화면 확인]"


def build_visual_question(tool_name: str, args: Optional[dict]) -> Optional[tuple[str, str]]:
    """도구 호출에서 (캡처할 창, Vision에게 물을 것)을 만든다. 대상 아니면 None.

    전체 화면이 아니라 **창 하나만** 찍는다. 판독 정확도가 오르고, 외부로 나가는
    화면 범위가 줄어든다(OWASP LLM02 — tools/vision.py 주의사항 참조).
    """
    args = args or {}
    if tool_name == "type_text":
        text = str(args.get("text", "")).strip()
        target = str(args.get("target", "")).strip()
        if not text or not target:
            # ⚠️ **target을 모르면 검증하지 않는다.** 예전엔 "활성창"을 찍었는데,
            #    type_text는 애초에 활성창에 글자를 넣는다 — 글자가 간 그 창을 그대로
            #    확인하니 **항상 "있다"**가 나온다. 순환이라 틀린 창에 들어간 걸
            #    원리적으로 못 잡고, 오히려 **거짓 성공에 화면 증거를 붙여 줬다.**
            #    2026-09-03 실기에서 실제로 그렇게 오보했다.
            #    어디에 넣으려 했는지 모르면 확인할 방법이 없는 게 맞다.
            return None
        snippet = text[:30] + ("..." if len(text) > 30 else "")
        return (target, (
            f"이 창은 '{target}'입니다. 방금 여기에 '{snippet}' 라는 내용을 "
            "입력했습니다. 그 내용이 실제로 들어가 있나요? "
            "본문이 비어 있으면 '비어 있다'고, 다른 내용만 있으면 그 내용을 "
            "그대로 말해주세요."
        ))
    return None


def _tool_reported_failure(content: str) -> bool:
    """도구가 이미 실패를 자백했는가. (그렇다면 화면을 볼 이유가 없다 — 8초를 아낀다)"""
    c = str(content).strip()
    return c.startswith("✗") or bool(_TOOL_ERROR_RE.match(c))


def last_tool_result(messages: list[AnyMessage]) -> Optional[tuple[str, dict, ToolMessage]]:
    """**이번 턴**의 마지막 ToolMessage와 그 짝인 도구 호출을 (이름, 인자, 메시지)로.

    ⚠️ 반드시 current_turn_messages()를 거친다(절대규칙 6). 전체 히스토리를 훑으면
      몇 턴 전의 type_text가 지금 턴을 8초 느리게 만든다.
    """
    turn = current_turn_messages(messages)
    tm = next((m for m in reversed(turn) if isinstance(m, ToolMessage)), None)
    if tm is None:
        return None
    call_id = getattr(tm, "tool_call_id", None)
    for m in reversed(turn):
        for c in (getattr(m, "tool_calls", None) or []):
            if isinstance(c, dict) and c.get("id") == call_id:
                return (c.get("name", ""), c.get("args", {}) or {}, tm)
    return None


# ── 계획 수립 (Plan-and-Execute, M3) — planner 노드의 순수 로직 ─────
#
# **이 층의 값어치는 "여러 단계를 실행한다"가 아니라 "몇 단계를 못 했는지 말할 수 있다"이다.**
# `"메모장 열고 크롬 닫아줘"`에서 앞의 하나만 하고 성공했다고 답해도 지금까지는 시스템이
# 그걸 알 방법이 없었다 — 상태에 "무엇을 하기로 했는지"가 없었기 때문이다.
# BL-12(엉뚱한 창에 입력해 놓고 성공 보고) · BL-15(뒷문장을 삼키고 성공 보고) ·
# BL-19(도구를 부르지도 않고 "지켜볼게요")와 **같은 계열의 마지막 판본**이다.
# → docs/design/M3_계획수립노드.md
#
# ⚠️ 여기도 visual_verify와 같은 절제를 지킨다 — **판정하지 않고 추출만 한다.**
#    계획을 다시 세우지도(replan) 않는다. LLM 호출은 턴당 1회다.

_plog = get_logger("Plan")

# 최소 출하본은 2단계까지만 다룬다. 늘리기 전에 라이브 증거가 먼저다(ADR §7-2).
PLAN_MAX_STEPS = 2

# **JSON이 아니라 번호 목록을 요구한다.** BL-19 조건(모델 능력이 시간대에 따라 흔들린다)
# 에서 가장 먼저 무너지는 능력이 구조화 출력 스키마 준수다. 목록은 깨져도 추출이 되고,
# 추출이 안 되면 계획 없음 = **오늘 경로 그대로**다.
PLAN_DECOMPOSE_PROMPT = f"""당신은 한국어 PC 제어 명령을 실행 순서대로 나누는 도구입니다.
- 최대 {PLAN_MAX_STEPS}단계까지만 나눕니다.
- 한 줄에 한 단계씩, '1. ' '2. ' 처럼 번호를 붙인 목록으로만 답합니다.
- 각 단계는 그 자체로 실행 가능한 하나의 명령이어야 합니다.
- 설명·인사·코드블록·JSON을 쓰지 않습니다.
- 나눌 수 없는 단일 명령이면 아무것도 출력하지 않습니다.
예) 입력: 메모장 열고 크롬 닫아줘
1. 메모장 열기
2. 크롬 닫기"""

_PLAN_STEP_RE = re.compile(r'^\s*\d+\s*[.)]\s*(.+?)\s*$')
_PLAN_NORM_RE = re.compile(r"""[\s.,!?~…·"'`\-]+""")


def _plan_norm(text: Any) -> str:
    """단계 비교용 정규화 — 띄어쓰기·구두점을 지운다."""
    return _PLAN_NORM_RE.sub("", str(text)).lower()


def parse_plan(raw: Any, original: str = "") -> list[str]:
    """분해기 응답에서 단계 목록을 **추출**한다. `[]` = 계획 없음(= 오늘 경로).

    ⚠️ **판정이 아니라 추출이다.** 좌표를 지어내지 않는 find_ui_element(절대규칙 9)와
      같은 계열의 절제다 — 확실하지 않으면 만들어 내지 말고 빈손으로 돌아간다.
      빈손의 착지점은 오류 메시지가 아니라 **오늘의 정상 경로**다(ADR §3-4).

    버리는 경우(전부 `[]`):
      - 번호 목록이 없다(산문만) · 빈 응답
      - 단계가 1개뿐이다 (= 나눌 게 없었다)
      - **단계 하나가 입력 원문 그대로다** (= 분해에 실패하고 되돌려 준 것)
      - 단계가 중복이다
      - **PLAN_MAX_STEPS를 넘는다** — 잘라서 2개만 하면 3번째를 *모르는 채로* 끝난다.
        "못 했다"고 말할 수도 없으니 이 기능의 존재 이유와 정반대다. 통째로 버린다.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        steps = [str(x).strip() for x in raw]
    else:
        steps = []
        for line in str(getattr(raw, "content", raw)).splitlines():
            m = _PLAN_STEP_RE.match(line)
            if m:
                steps.append(m.group(1).strip())
    steps = [s for s in steps if s]

    if len(steps) < 2 or len(steps) > PLAN_MAX_STEPS:
        return []
    norms = [_plan_norm(s) for s in steps]
    if len(set(norms)) != len(norms):
        return []
    if original and _plan_norm(original) in norms:
        return []
    return steps


def _is_plannable(text: str) -> bool:
    """이 발화를 단계로 나눠 볼 자리인가. (게이트 — 양방향 오류가 전부 안전하다)

    놓치면 = 오늘 동작. 오탐하면 = 3초 낭비 후 정상 진행.

    - **부정어는 제외한다**: "크롬 말고 메모장 열어줘"는 복합처럼 보이지만 단계가 둘이 아니다.
    - **감시 요청은 제외한다**: 계획 턴은 도구가 여러 번 돌아 `detect_watch_lie`의 조건 ①
      ("이번 턴 도구 0개")을 깨뜨린다. BL-19 그물을 약하게 만드느니 **기능을 포기한다**
      (ADR §5-1).
    """
    t = (text or "").strip()
    if not t or has_negation(t) or _is_watch_request(t):
        return False
    return is_compound_command(t)


# 단계 지시. **메시지가 아니라 SystemMessage 교체로 준다** — with_watch_directive와 같은
# 이유다(graph.py 아래). HumanMessage를 넣으면 거기서 턴이 새로 시작되어(절대규칙 6)
# current_turn_messages가 계획 실행 도중에 턴 경계를 잃는다.
_PLAN_STEP_DIRECTIVE = """

[계획] 사용자의 명령을 {total}단계로 나눴습니다:
{listing}
지금은 **{no}단계: {step}** 만 실행하세요. 이 단계에 필요한 도구를 지금 호출하고, 다음 단계는 아직 하지 마세요. 이 단계가 이미 끝났으면 도구를 부르지 말고 결과만 한 문장으로 말하세요."""


def with_step_directive(msgs: list[AnyMessage], plan: list[str], cursor: int) -> list[AnyMessage]:
    """지금 실행할 단계를 시스템 프롬프트에 덧붙인 메시지 목록. (원본을 바꾸지 않는다)

    ⚠️ 시스템 메시지를 **뒤에 새로 붙이지 않는다.** Gemini는 두 번째 SystemMessage를
      무시하거나 400을 낸다. 기존 것을 교체한다. (with_watch_directive와 동일)
    """
    if not plan or cursor >= len(plan):
        return list(msgs)
    listing = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(plan))
    directive = _PLAN_STEP_DIRECTIVE.format(
        total=len(plan), listing=listing, no=cursor + 1, step=plan[cursor])
    out = list(msgs)
    for i, m in enumerate(out):
        if isinstance(m, SystemMessage):
            out[i] = SystemMessage(content=_msg_text(m) + directive)
            return out
    return [SystemMessage(content=directive.strip())] + out


def _as_int(v: Any) -> int:
    try:
        return max(int(v or 0), 0)
    except Exception:
        return 0


def turn_tool_call_count(messages: list[AnyMessage]) -> int:
    """이번 턴에 나온 도구 호출 수. **거부돼 실행되지 않은 것도 센다.**

    세는 게 아니라 **안 세는 것**이 중요하다 — 승인 거부 턴에서는 호출이 나와 있고
    실행만 안 됐는데, 그걸 빼려고 ToolMessage 내용을 들여다보면 문구 판정이 된다.
    여기서는 **낙관적인 상한**만 주고, 비관적인 쪽은 커서가 맡는다(steps_covered).
    """
    return sum(len(getattr(m, "tool_calls", None) or [])
               for m in current_turn_messages(messages))


def steps_covered(cursor: Any, tool_calls: Any) -> int:
    """단계가 여기까지는 진행됐다고 볼 근거 — **덜 낙관적인 쪽**을 믿는다. (M3-1)

    두 신호는 서로 독립이고 각각 진행의 **상한**이라, 겹치는 데까지만 인정한다.

        A 둘 다 실행됨   커서 2 · 호출 2 → 2  조용하다
        B 단계를 건너뜀  커서 2 · 호출 1 → 1  "'계산기 열기'는 못 했어요"
        C 승인 거부      커서 1 · 호출 2 → 1  "'test.txt 삭제'는 못 했어요"

    ⚠️ **한 쪽만 보면 반드시 깨진다.** 커서만 보면 B가(커서는 무조건 전진한다),
      호출 수만 보면 C가 깨진다. 라이브에서 A와 B가 같은 날 둘 다 나왔다.
      → docs/design/M3-1_단계완료판정.md
    """
    return min(_as_int(cursor), _as_int(tool_calls))


def remaining_steps(plan: Optional[list], covered: Any) -> list[str]:
    """아직 했다는 근거가 없는 단계들. (`covered`는 `steps_covered`의 결과다)"""
    return list(plan or [])[_as_int(covered):]


def unfinished_notice(plan: Optional[list], covered: Any) -> str:
    """못 한 단계를 알리는 **접미** 문구. 없으면 빈 문자열.

    판정하지 않는다 — 상태에 남아 있는 단계를 그대로 읽어 말할 뿐이다.
    기존 "삭제는 취소했어요. " 는 **접두**라 자리가 겹치지 않는다.
    조사를 하드코딩하지 않으려고 목록 형태로 붙인다("…는/은" 문제 회피).
    """
    rest = remaining_steps(plan, covered)
    if not rest:
        return ""
    return " 다만 이건 못 했어요: " + ", ".join(f"'{s}'" for s in rest) + "."


# ── 그래프 빌더 ────────────────────────────────────────────────────
def build_pluiz_graph(
    *,
    llm: Any,
    tools: Optional[list] = None,
    security_check: Callable[[str], tuple[bool, str]],
    fast_resolve: Optional[Callable[[str], Any]] = None,
    checkpointer: Optional[Any] = None,
    dangerous_tools: Optional[set] = None,
    target_exists: Optional[Callable[[dict], bool]] = None,
    visual_check: Optional[Callable[[str, str], str]] = None,
    visual_verify_tools: Optional[set] = None,
    is_watching: Optional[Callable[[], bool]] = None,
    plan_decompose: Optional[Callable[[str], Any]] = None,
):
    """Pluiz StateGraph를 구성해 compiled graph를 반환한다. (동기 노드)

    Args:
        llm: bind_tools/invoke를 지원하는 채팅 모델 (또는 동일 인터페이스 mock).
        tools: LangChain 도구 리스트 (ToolNode용). 없으면 tools 노드 생략.
        security_check(text) -> (blocked, reason): 입력 보안 검사(코드 레벨).
        fast_resolve(text) -> Optional[str] | Awaitable: 캐시/라우터 즉시 처리 결과,
            처리 불가 시 None. (동기·비동기 모두 허용)
        checkpointer: 대화 영속성. 없으면 MemorySaver 기본 생성.
        target_exists(dangerous_tool_call) -> bool: 삭제 대상이 실제로 있는지.
            None이면 확인하지 않는다(mock 테스트 기본값). 없는 대상이면 승인을
            묻지 않고 바로 "못 찾았다"로 답한다 — 묻고 나서 없다고 하면 헷갈린다.
        visual_check(window, question) -> str: 화면을 실제로 보고 답하는 함수
            (프로덕션에서는 tools/vision.describe_screen). **None이면 visual_verify
            노드를 아예 만들지 않는다** — 그래프가 이 인자 없이 지금까지와 완전히
            동일하게 동작한다(mock 테스트·설정 OFF 경로).
        visual_verify_tools: 화면으로 확인할 도구 이름 집합. 기본 VISUAL_VERIFY_TOOLS.
        plan_decompose(text) -> str | list[str] | None: 복합 명령을 단계로 나눈 응답
            (번호 목록 텍스트, 또는 단계 리스트). **None이면 planner 노드를 아예
            만들지 않는다** — visual_check와 같은 패턴이고, 그래야 계획이 꺼진 경로가
            글자 그대로 예전과 같다. → docs/design/M3_계획수립노드.md
        is_watching() -> bool: 화면 감시가 실제로 돌고 있는지. output_guard가
            "지켜볼게요"라는 **말**과 대조할 **상태**다(BL-19). 기본은 제품 모니터.
            주입받는 이유는 llm·visual_check와 같다 — mock으로 전부 검증하기 위해.
    """
    tools = tools or []
    dangerous = dangerous_tools if dangerous_tools is not None else DANGEROUS_TOOLS
    visual_tools = (visual_verify_tools if visual_verify_tools is not None
                    else VISUAL_VERIFY_TOOLS)
    llm_with_tools = llm.bind_tools(tools) if tools else llm
    is_watching = is_watching or _monitor_is_watching

    # BL-19 원인 ② — **재시도 패스에서만** 도구 호출을 강제한다.
    # 설득(프롬프트)은 확률을 올릴 뿐이다. 2026-09-04 나쁜 구간에서는 첫 패스도
    # 재시도도 함께 실패했다(0/10). `tool_choice`는 그 구간에서도 함수 호출을
    # 강제하므로, 확률을 올리던 겹 하나를 **구조로** 바꾼다.
    # ⚠️ 첫 패스는 절대 건드리지 않는다 — 평범한 대화까지 도구를 부르게 된다.
    # ⚠️ 지원하지 않는 provider·mock이면 None이고, 그러면 **오늘과 똑같이** 동작한다.
    _forced_bind: dict[str, Any] = {}

    def _forced_llm(name: str):
        """`name` 도구를 반드시 부르게 묶은 LLM. 못 묶으면 None(=오늘 경로)."""
        if name not in _forced_bind:
            bound = None
            if tools:
                try:
                    bound = llm.bind_tools(tools, tool_choice=name)
                except Exception as e:
                    _log.info("[BL-19] tool_choice 미지원(%s) → 설득 재시도로 폴백",
                              type(e).__name__)
            _forced_bind[name] = bound
        return _forced_bind[name]

    # ── 노드 ───────────────────────────────────────────────────────
    def input_guard(state: PluizState) -> dict:
        """OWASP LLM01/02 자리. 현재는 코드 레벨 보안 검사."""
        text = _last_human_text(state["messages"])
        blocked, reason = security_check(text)
        # 지난 턴에 켜진 채 남아 있을 수 있는 플래그를 새 턴 시작 시 끈다.
        # (승인 질문 상태로 턴이 끝나면 output_guard를 거치지 않아 값이 살아남는다)
        if blocked:
            return {"messages": [AIMessage(content=reason)], "decision": "blocked",
                    "deletion_cancelled": False, "visual_verified": False,
                    "plan": [], "plan_cursor": 0}
        return {"decision": "", "deletion_cancelled": False, "visual_verified": False,
                "plan": [], "plan_cursor": 0}

    def fast_path(state: PluizState) -> dict:
        """캐시/라우터 빠른 경로. 히트 시 결과를 messages에 기록(맥락 통합 핵심).

        미스일 때만 **계획을 세워 볼 자리인지**를 더 본다(M3). 캐시가 처리한 명령은
        planner를 타지 않는다 — 이미 끝난 일에 LLM 왕복 3초를 얹을 이유가 없다.
        """
        text = _last_human_text(state["messages"])
        result = None
        if fast_resolve is not None:
            try:
                result = fast_resolve(text)
            except Exception as e:
                print(f"[graph.fast_path] 오류(무시): {type(e).__name__}: {e}")
                result = None
        if result is not None:
            return {"messages": [AIMessage(content=str(result))], "decision": "fast_hit"}
        if plan_decompose is not None and _is_plannable(text):
            return {"decision": "to_plan"}
        return {"decision": "to_agent"}

    def planner(state: PluizState) -> dict:
        """복합 명령을 단계로 나눠 **상태에 적는다**. 실행은 하지 않는다. (M3)

        ⚠️ **이 노드는 턴을 절대 죽이지 않는다.** 분해기 예외 · 산문만 반환 ·
          단계 부족 · 상한 초과는 전부 `{}` 하나로 수렴해 **오늘과 완전히 동일한**
          단일 루프로 진행한다. *"계획을 세우지 못했어요"* 라고 말하지 않는다 —
          오늘도 이 명령들의 상당수는 단일 루프가 처리해 내므로, 실행은 성공하는데
          실패를 예고하는 꼴이 된다. Vision이 화면을 못 봤을 때 아무것도 붙이지 않는
          것과 같은 절제다. (ADR §3-4 — 계획 **수립** 실패는 들리지 않고,
          계획 **실행** 실패는 output_guard가 반드시 말한다)
        """
        text = _last_human_text(state["messages"])
        try:
            raw = plan_decompose(text)
        except Exception as e:
            _plog.warning("분해 실패(무시): %s: %s | 입력=%r", type(e).__name__, e, text)
            return {}
        steps = parse_plan(raw, text)
        if not steps:
            _plog.info("계획 없음 → 오늘 경로 그대로 | 입력=%r", text)
            return {}
        _plog.info("계획 %d단계 | %s", len(steps), " / ".join(steps))
        return {"plan": steps, "plan_cursor": 0}

    def agent(state: PluizState) -> dict:
        """LLM ReAct 추론 노드 (동기 invoke — interrupt 호환).

        계획이 있으면 **지금 실행할 단계만** 시스템 프롬프트로 지시한다(M3).
        실행기를 새로 만들지 않는다 — 기존 agent ⇄ tools 루프가 한 단계씩 처리하고
        라우터가 되돌린다.
        """
        msgs = _prepare_messages(state["messages"])
        plan = list(state.get("plan") or [])
        cursor = int(state.get("plan_cursor") or 0)
        in_plan = bool(plan) and cursor < len(plan)
        if in_plan:
            msgs = with_step_directive(msgs, plan, cursor)
        response = llm_with_tools.invoke(msgs)

        # BL-19: 감시 요청인데 도구를 안 불렀으면 **한 번만** 다시 묻는다.
        # 호출률이 회차마다 흔들려서(2026-09-04 실측) 프롬프트만으로는 부족하다.
        user_text = _last_human_text(state["messages"])
        if needs_watch_retry(user_text, response, watching=is_watching()):
            want = ("stop_watching" if _STOP_REQUEST_RE.search(user_text)
                    else "watch_screen")
            _log.info("[BL-19] 감시 요청인데 도구 미호출 → 1회 재시도(강제=%s) | 입력=%r",
                      want, user_text)
            retried = None
            forced = _forced_llm(want)
            if forced is not None:
                try:
                    retried = forced.invoke(with_watch_directive(msgs))
                except Exception as e:
                    # 강제가 거부돼도 **턴을 죽이지 않는다** — 설득 재시도로 내려간다.
                    _log.warning("[BL-19] 강제 호출 실패(%s: %s) → 설득 재시도로 폴백",
                                 type(e).__name__, e)
                    retried = None
            if retried is None:
                retried = llm_with_tools.invoke(with_watch_directive(msgs))
            if getattr(retried, "tool_calls", None):
                response = retried
            else:
                _log.warning("[BL-19] 재시도에도 도구 미호출 — 정직하게 보고한다")

        out: dict = {"messages": [response]}
        # 도구를 안 불렀다 = 이 단계에서 더 할 일이 없다 → 다음 단계로 넘어간다.
        # ⚠️ 커서가 **반드시** 전진하므로 agent 자기루프는 최대 len(plan)회에서 끝난다.
        #   (전진 없이 되돌리면 무한루프다 — HITL 무한루프 사고와 같은 계열)
        if in_plan and not getattr(response, "tool_calls", None):
            out["plan_cursor"] = cursor + 1
            # '완료'가 아니라 **커서 전진**이다 — 실제로 했는지는 output_guard가
            # 도구 호출 수와 대조해 판정한다(M3-1).
            _plog.info("%d/%d 단계 넘어감 | %r", cursor + 1, len(plan), plan[cursor])
        return out

    def output_guard(state: PluizState) -> dict:
        """OWASP LLM05 + reflection 자리. T04 보정 + 빈응답 복구 + 감시 정직성(BL-19)."""
        # 감시 시작 고지는 **원문 그대로** 전한다. LLM이 요약하면 간격·상한·중단법이
        # 사라지는데, 그 고지가 감시를 승인 없이 허용한 근거다.
        # 계획을 세웠는데 다 못 했으면 **접미**로 알린다(M3). 판정하지 않는다 —
        # 상태에 남아 있는 단계를 그대로 읽어 말할 뿐이다. 기존 "삭제는 취소했어요. "는
        # 접두라 자리가 겹치지 않는다.
        # ⚠️ **커서를 그대로 믿지 않는다** (M3-1 / BL-21 ①). 커서는 진행률이 아니라
        #   agent 자기루프를 끝내려고 **무조건 전진하는 루프 제어 값**이다. 그걸 그대로
        #   읽던 탓에 라이브에서 단계를 건너뛰고도 문구가 붙지 않았다.
        tail = unfinished_notice(
            state.get("plan"),
            steps_covered(state.get("plan_cursor"),
                          turn_tool_call_count(state["messages"])))

        notice = watch_notice_to_deliver(state["messages"])
        if notice is not None:
            note = "삭제는 취소했어요. " if state.get("deletion_cancelled") else ""
            return {"messages": [AIMessage(content=note + notice + tail)],
                    "deletion_cancelled": False}

        # 도구를 안 부르고 "지켜볼게요"·"중단했어요"라고 말한 경우 (BL-19).
        # ⚠️ 캐시 히트는 제외한다. fast_path는 도구를 **실제로 실행하고도** messages에는
        #    AIMessage 하나만 남겨서(절대규칙 2) 여기서는 "도구 0개"로 보인다.
        #    거르지 않으면 멀쩡히 실행된 캐시 응답을 거짓말로 몰아 덮어쓴다.
        lie = (None if state.get("decision") == "fast_hit"
               else detect_watch_lie(state["messages"], watching=is_watching()))
        if lie is not None:
            note = "삭제는 취소했어요. " if state.get("deletion_cancelled") else ""
            return {"messages": [AIMessage(content=note + lie + tail)],
                    "deletion_cancelled": False}

        corrected = verify_output(state["messages"])
        note = "삭제는 취소했어요. " if state.get("deletion_cancelled") else ""
        if corrected is not None:
            return {"messages": [AIMessage(content=note + corrected + tail)],
                    "deletion_cancelled": False}
        if note or tail:
            # 새 명령의 답변 앞에 취소 사실을 붙인다. 안 붙이면 사용자는 삭제가
            # 어떻게 됐는지 모른 채 새 명령의 결과만 보게 된다.
            last = state["messages"][-1]
            if isinstance(last, AIMessage):
                return {"messages": [AIMessage(content=note + _msg_text(last) + tail)],
                        "deletion_cancelled": False}
        return {}

    def visual_verify(state: PluizState) -> dict:
        """도구 실행 결과를 **화면으로** 확인해 그 증거를 도구 결과에 붙인다.

        ⚠️ **async로 바꾸지 말 것** — 이 그래프의 노드는 전부 동기다(절대규칙 1).

        증거는 새 메시지를 append 하지 않고 **마지막 ToolMessage를 같은 id로 교체**해
        전달한다. add_messages 리듀서가 같은 id를 덮어쓰기 때문이다.
        다른 방법은 전부 깨진다:
          - SystemMessage → _prepare_messages()가 걸러내서 LLM이 못 본다
          - HumanMessage  → current_turn_messages()가 거기서 턴을 새로 시작한다(절대규칙 6)
          - ToolMessage 추가 append → 한 tool_call_id에 둘이 되어 Gemini 400
          - 별도 state 필드 → LLM에는 messages만 가므로 agent가 못 본다

        **응답을 조작하지 않는다.** 증거를 붙일 뿐, 성공/실패 판정도 재시도도 하지 않는다.
        """
        found = last_tool_result(state["messages"])
        if not found:
            return {"visual_verified": True}
        name, args, tm = found
        built = build_visual_question(name, args)
        if built is None:
            return {"visual_verified": True}
        window, question = built

        try:
            evidence = str(visual_check(window, question) or "").strip()
        except Exception as e:
            # 검증이 본 명령을 망치면 안 된다. Vision은 네트워크·쿼터·포커스 등
            # 실패 요인이 많다 — 증거 없이 원본 그대로 통과시킨다.
            print(f"[graph.visual_verify] 화면 확인 실패(무시): {type(e).__name__}: {e}")
            return {"visual_verified": True}

        # 화면을 **못 봤을 때**는 아무것도 붙이지 않는다. 못 본 걸 봤다고 하면
        # 이 노드가 고치려던 바로 그 정직성 문제를 스스로 저지르는 꼴이다.
        if not evidence or _tool_reported_failure(evidence):
            return {"visual_verified": True}

        merged = ToolMessage(
            content=(f"{_msg_text(tm)}\n"
                     f"{_VISUAL_EVIDENCE_PREFIX} {evidence}"),
            tool_call_id=tm.tool_call_id,
            id=tm.id,                 # ← 같은 id여야 리듀서가 '교체'한다
            name=getattr(tm, "name", None),
        )
        return {"messages": [merged], "visual_verified": True}

    def hitl(state: PluizState) -> dict:
        """위험 도구 실행 전 사람 승인(HITL, Lab19). interrupt로 그래프를 일시정지.
        재개 시 응답을 해석해 승인이면 tools로, 거부면 취소 응답.
        (interrupt는 동기 호출이라 동기 노드로 둔다 — config 컨텍스트 보장)

        승인도 거부도 아닌 답(unclear)이면 **한 번 더 물어본다.** 여기서 바로
        취소해 버리면, 사용자가 승인과 무관한 새 명령을 말했을 때 그 명령이
        조용히 사라진다(발화가 Command(resume)로 소비되기 때문). 재질문으로
        사용자가 상황을 인지할 기회를 준다. 끝까지 애매하면 **취소**(안전 기본값).
        """
        last = state["messages"][-1]
        calls = list(getattr(last, "tool_calls", []) or [])
        dcall = next((c for c in calls if c.get("name") in dangerous), None)

        def _close_calls(reason: str) -> list:
            """매달린 tool_calls를 ToolMessage로 마감(히스토리 오염 방지)."""
            return [ToolMessage(content=reason, tool_call_id=c["id"])
                    for c in calls if c.get("id")]

        # ── 대상이 존재하지 않으면 **묻지 않는다** ──────────────────
        # 예전엔 없는 폴더인데도 "정말 삭제할까요?"를 먼저 묻고, 승인한 뒤에야
        # "없는 것 같아요"라고 답했다(실기에서 확인). 순서가 거꾸로였다.
        # 없는 대상은 삭제될 것도 없으니 승인이 무의미하고, 사용자만 헷갈린다.
        if target_exists is not None and dcall is not None:
            try:
                found = target_exists(dcall)
            except Exception as e:
                print(f"[graph.hitl] 대상 확인 실패(무시): {type(e).__name__}: {e}")
                found = True          # 확인 못 하면 원래대로 승인 절차를 밟는다
            if not found:
                base = _target_name(dcall)
                return {"messages": _close_calls(
                    f"✗ '{base}'을(를) 찾을 수 없습니다. 삭제하지 않았습니다."
                ), "decision": "not_found", "deletion_cancelled": False}

        # 그래프를 멈추고 사용자에게 질문(오케스트레이터가 질문을 UI로 전달)
        question = _confirm_question(dcall)
        verdict = "unclear"
        answer: Any = ""
        for _ask in range(_MAX_CONFIRM_ASKS):
            answer = interrupt({"question": question})
            verdict = classify_confirmation(answer)
            # 승인 판정은 사용자 말버릇에 가장 많이 부딪히는 자리다. 무엇을 어떻게
            # 읽었는지 남기지 않으면 "왜 '네'가 안 먹었나"를 사후에 알 수 없다.
            _log.info("승인 판정 | %d번째 | 답변=%r → %s", _ask + 1, answer, verdict)
            if verdict != "unclear":
                break
            question = _reask_question(dcall)

        if verdict == "approve":
            # ⚠️ 반드시 끈다. 예전엔 앞 턴에서 켜진 값이 살아남아, **실제로 삭제해 놓고**
            #    "삭제는 취소했어요. …휴지통으로 옮겼어요" 라고 답했다(실기에서 확인).
            return {"decision": "approved", "deletion_cancelled": False}

        # ── 승인 대기 중에 들어온 **다른 명령** ────────────────────
        # 삭제를 취소하고 그 명령을 처리한다. 재질문하면 사용자가 같은 말을
        # 두 번 해야 한다(실기에서 실제로 겪었다). HumanMessage로 넣으므로
        # 여기서부터가 "이번 턴"이 된다 — 의미상 새 명령이 맞다(절대규칙 6).
        if verdict == "other_command":
            msgs = _close_calls("사용자가 다른 명령을 내려 삭제를 취소했습니다.")
            msgs.append(HumanMessage(content=str(answer)))
            # ⚠️ **계획도 반드시 지운다**(M3). Command(resume)는 input_guard를 거치지
            #   않으므로, 안 지우면 새 명령을 처리할 agent가 "지금은 2단계: test.txt
            #   삭제" 지시를 받는다. 취소 플래그가 턴을 넘어 새어 실제로 삭제해 놓고
            #   "삭제는 취소했어요"라고 답한 사고와 **완전히 같은 모양**이다.
            return {"messages": msgs, "decision": "other_command",
                    "deletion_cancelled": True, "plan": [], "plan_cursor": 0}

        # 거부/애매: 취소 응답
        cancel = _close_calls("사용자가 삭제를 취소했습니다.")
        cancel.append(AIMessage(content=(
            "네, 삭제를 취소했어요." if verdict == "reject"
            else "답을 알아듣지 못해서 삭제는 취소했어요. 방금 하신 말씀을 다시 한 번 말씀해 주세요."
        )))
        return {"messages": cancel, "decision": "rejected", "deletion_cancelled": False}

    # ── 라우팅 ─────────────────────────────────────────────────────
    def route_after_guard(state: PluizState) -> str:
        return "output_guard" if state.get("decision") == "blocked" else "fast_path"

    def route_after_fast(state: PluizState) -> str:
        d = state.get("decision")
        if d == "fast_hit":
            return "output_guard"
        if d == "to_plan":
            return "planner"   # plan_decompose가 없으면 이 값 자체가 만들어지지 않는다
        return "agent"

    def route_after_agent(state: PluizState) -> str:
        last = state["messages"][-1]
        calls = getattr(last, "tool_calls", None)
        if calls:
            if any(c.get("name") in dangerous for c in calls):
                return "hitl"      # 위험 도구 → 승인 절차
            return "tools"
        # 도구를 안 불렀는데 계획에 남은 단계가 있으면 그 단계로 되돌린다(M3).
        # agent가 커서를 이미 전진시킨 뒤라 유한하다.
        plan = state.get("plan") or []
        if plan and int(state.get("plan_cursor") or 0) < len(plan):
            return "agent"
        return "output_guard"

    def route_after_hitl(state: PluizState) -> str:
        d = state.get("decision")
        if d == "approved":
            return "tools"
        # 다른 명령 / 대상 없음 → LLM이 이어서 처리한다(명령 실행 · 자연스러운 안내)
        if d in ("other_command", "not_found"):
            return "agent"
        return "output_guard"

    def route_after_tools(state: PluizState) -> str:
        """도구 실행 직후 — **화면을 볼 값어치가 있을 때만** visual_verify로 보낸다.

        Vision 1회가 약 8초다. 아래를 전부 통과할 때만 그 비용을 쓴다.
        (visual_check가 없으면 이 라우터 자체가 그래프에 붙지 않는다)
        """
        if state.get("visual_verified"):
            return "agent"                      # 턴당 1회
        found = last_tool_result(state["messages"])
        if not found:
            return "agent"
        name, args, tm = found
        if name not in visual_tools:
            return "agent"
        if _tool_reported_failure(_msg_text(tm)):
            return "agent"                      # 이미 정직하다. 확인할 이유가 없다
        if build_visual_question(name, args) is None:
            return "agent"
        return "visual_verify"

    # ── 조립 ───────────────────────────────────────────────────────
    g = StateGraph(PluizState)
    g.add_node("input_guard", input_guard)
    g.add_node("fast_path", fast_path)
    g.add_node("agent", agent)
    g.add_node("output_guard", output_guard)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", route_after_guard,
                            {"fast_path": "fast_path", "output_guard": "output_guard"})

    # 계획 수립(M3)은 설정이 아니라 **주입 여부**로 켜진다. plan_decompose가 없으면
    # planner 노드도 엣지도 만들지 않는다 — visual_check(아래)와 완전히 같은 패턴이고,
    # 그래야 꺼진 경로가 글자 그대로 예전과 같다.
    fast_dests = {"agent": "agent", "output_guard": "output_guard"}
    agent_dests = {"tools": "tools", "hitl": "hitl", "output_guard": "output_guard"}
    if plan_decompose is not None:
        g.add_node("planner", planner)
        g.add_edge("planner", "agent")
        fast_dests["planner"] = "planner"
        agent_dests["agent"] = "agent"      # 남은 단계로 되돌아가는 자기루프

    if tools:
        g.add_node("tools", ToolNode(tools))
        g.add_node("hitl", hitl)
        g.add_conditional_edges("fast_path", route_after_fast, fast_dests)
        g.add_conditional_edges("agent", route_after_agent, agent_dests)
        # "agent"가 목적지에 있는 이유: 승인 대기 중 **다른 명령**이 들어왔거나
        # 삭제 **대상이 없을 때** LLM이 이어서 처리해야 한다.
        g.add_conditional_edges("hitl", route_after_hitl,
                                {"tools": "tools", "agent": "agent",
                                 "output_guard": "output_guard"})
        if visual_check is not None:
            # 도구 실행 결과를 화면으로 확인하고 agent에게 넘긴다.
            # ⚠️ visual_check가 없으면 이 분기 전체를 건너뛰어 **예전과 완전히 동일한**
            #    tools → agent 엣지를 쓴다. 설정 OFF와 mock 테스트가 그 경로다.
            g.add_node("visual_verify", visual_verify)
            g.add_conditional_edges("tools", route_after_tools,
                                    {"visual_verify": "visual_verify", "agent": "agent"})
            g.add_edge("visual_verify", "agent")
        else:
            g.add_edge("tools", "agent")
    else:
        # 도구가 없으면 계획을 실행할 수단 자체가 없다 — 자기루프도 두지 않는다.
        g.add_conditional_edges("fast_path", route_after_fast, fast_dests)
        g.add_edge("agent", "output_guard")

    g.add_edge("output_guard", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
