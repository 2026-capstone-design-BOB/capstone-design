"""BL-53 — 승인이 **STT 프롬프트 반추** 하나에 깨지는 것을 막는다.

배경: docs/BACKLOG.md § BL-53 · 2026-09-14 2차 리허설

사용자가 승인 질문("a.txt를 정말 삭제할까요?")에 **"그래"** 라고 답했는데
49자가 올라왔고, 그게 «다른 명령»으로 읽혀 **삭제가 조용히 취소됐다.**

    '크롬 엣지 카카오톡 탐색기 바탕화면 다운로드 문서 폴더 파일 스크린샷 최대화 최소화 검색'

🚨 **랜덤 환각이 아니다.** `services/stt.py`의 `_WHISPER_PROMPT`를 Whisper가
그대로 되뱉은 것이다 — 108자 중 15번째 글자부터 잘라낸 **연속 조각**이고
한 글자도 다르지 않다.

🔑 **그리고 두 방어가 같은 뿌리에서 같이 무너졌다.** 프롬프트 꼬리가
"… 최대화 최소화 **검색** 실행 종료 …"이고 `_COMMAND_TAIL_RE`에도
`검색|실행|종료`가 있다. 둘 다 «PC 제어 어휘» 목록이라 **반추된 프롬프트는
반드시 명령형 어미로 끝난다.** 우연이 아니라 구조적으로 뚫리게 돼 있었다.

🚨 **이 테스트는 양방향이다.** «막는다»만 고정하면 `other_command` 분기를
통째로 없애는 수정이 통과해 버린다. 그 분기는 절대 규칙 11이 지키는 자리다 —
승인 대기 중 새 명령을 받는 건 의도된 동작이고, 계획 상태가 턴을 넘어 새는
것을 막는 자리이기도 하다. 그래서 아래 §3이 §1·§2만큼 중요하다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

from services.stt import (  # noqa: E402
    _ECHO_MIN_WORDS, _WHISPER_PROMPT, is_prompt_echo,
)
from core.graph import (  # noqa: E402
    _COMMAND_TAIL_RE, _MAX_COMMAND_TOKENS, classify_confirmation,
)

passed = total = 0


def check(name, cond, extra=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {extra}")


#: 2026-09-14 2차 리허설 로그(logs/pluiz_20260914_2차리허설.log:375)에서 그대로 가져왔다.
HALLU = ("크롬 엣지 카카오톡 탐색기 바탕화면 다운로드 문서 폴더 파일 "
         "스크린샷 최대화 최소화 검색")


print()
print("§0. 사고 재구성 — 원인이 무엇이었는지 못 박는다")

check("환각 49자는 _WHISPER_PROMPT의 **연속 조각**이다 (랜덤 환각이 아니다)",
      HALLU in " ".join(_WHISPER_PROMPT.split()),
      "프롬프트가 바뀌었다면 이 줄이 먼저 깨진다 — BL-53의 근거가 사라진 것이다")
check("길이가 로그와 같다 (49자)", len(HALLU) == 49, str(len(HALLU)))
check("🔑 반추된 프롬프트는 **명령형 어미로 끝난다** — 두 목록이 어휘를 공유한다",
      bool(_COMMAND_TAIL_RE.search(HALLU)),
      "이게 False가 되면 «우연히 뚫렸다»는 뜻이고 설명이 달라진다")

print()
print("§1. 1층 — STT가 프롬프트 반추를 만들어 내지 않는다 (services/stt.py)")

check("리허설의 실제 환각을 잡는다", is_prompt_echo(HALLU) is True)
check("프롬프트를 통째로 되뱉어도 잡는다", is_prompt_echo(_WHISPER_PROMPT) is True)
check("프롬프트 꼬리 조각도 잡는다", is_prompt_echo("열어줘 켜줘 닫아줘") is True)
check("문장부호가 붙어도 잡는다", is_prompt_echo("최대화 최소화 검색.") is True)
check("앞뒤 공백이 달라도 잡는다", is_prompt_echo("  크롬   엣지  카카오톡  ") is True)

print()
print("§2. 1층의 반대편 — **멀쩡한 발화를 죽이지 않는다**")

for utt, why in [
    ("그래",                  "대본 6장면의 실제 승인 답변"),
    ("응 지워 줘",             "승인 변형"),
    ("메모장 열어줘",           "대본 1장면"),
    ("a.txt 지워줘",           "대본 6장면"),
    ("메모장 열고 b.txt도 지워줘", "대본 7장면"),
    ("지금 화면에 뭐 있어?",      "대본 4장면"),
    ("블루투스 어디서 켜?",       "대본 5장면"),
    ("볼륨 올려줘",            "프롬프트에 든 단어지만 **연속이 아니다**"),
    ("메모장 계산기",           f"{_ECHO_MIN_WORDS}어절 미만은 사람이 말할 수 있다"),
    ("",                     "빈 결과는 반추가 아니다"),
]:
    check(f"통과: {utt!r} — {why}", is_prompt_echo(utt) is False)

print()
print("§3. 2층 — 승인 문지기. ⚠️ **other_command 분기는 살아 있어야 한다**")

check("🚨 환각은 재질문으로 간다 (삭제가 조용히 취소되지 않는다)",
      classify_confirmation(HALLU) == "unclear",
      classify_confirmation(HALLU))
check("승인은 그대로 승인이다", classify_confirmation("그래") == "approve")
check("승인 변형도 그대로", classify_confirmation("응 지워 줘") == "approve")
check("거부는 그대로 거부다", classify_confirmation("아니") == "reject")
check("⚠️ 승인 대기 중 **새 명령은 여전히 명령이다** (절대 규칙 11)",
      classify_confirmation("메모장 열어줘") == "other_command")
check("⚠️ 과거 오승인 사례도 명령으로 남는다 ('네이버 열어줘')",
      classify_confirmation("네이버 열어줘") == "other_command")
check("⚠️ 긴 복합 명령(6어절)도 명령이다 — 상한이 빡빡하면 여기서 깨진다",
      classify_confirmation("메모장 열고 계산기도 열고 볼륨도 올려줘") == "other_command")

print()
print("§4. 상한의 경계 — 숫자를 바꾸면 여기가 말해 준다")

TAIL = " 지워줘"
check(f"{_MAX_COMMAND_TOKENS}어절까지는 명령이다",
      classify_confirmation(" ".join(["가나"] * (_MAX_COMMAND_TOKENS - 1)) + TAIL)
      == "other_command")
check(f"{_MAX_COMMAND_TOKENS + 1}어절부터는 재질문이다",
      classify_confirmation(" ".join(["가나"] * _MAX_COMMAND_TOKENS) + TAIL)
      == "unclear")
check("환각은 상한을 한참 넘는다 (13어절)",
      len(HALLU.split()) > _MAX_COMMAND_TOKENS, str(len(HALLU.split())))

print()
print("§5. 두 층은 **서로를 대신하지 않는다**")

check("1층이 없어도 2층이 이번 건을 받는다", classify_confirmation(HALLU) == "unclear")
check("2층이 없어도 1층이 이번 건을 받는다", is_prompt_echo(HALLU) is True)
check("🔑 2층만으로는 부족하다 — 짧은 반추는 2층을 그냥 통과한다",
      classify_confirmation("열어줘 켜줘 닫아줘") == "other_command"
      and is_prompt_echo("열어줘 켜줘 닫아줘") is True,
      "이것이 «1층이 왜 필요한가»의 답이다")

print()
print(f"결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
