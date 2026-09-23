# -*- coding: utf-8 -*-
"""로그 형식 계약 — 생산자(graph_agent·fast_path) ↔ 소비자(analyze_tool_usage). (BL-28)

실행: python tests/test_log_format.py

## 왜 이 테스트가 있나

로그 한 줄에 **주인이 둘**이다. `core/graph_agent.py`가 찍고
`scripts/analyze_tool_usage.py`가 읽는다. 둘이 다른 파일이라
**한쪽만 고치면 조용히 깨진다** — 리포트가 «0턴»이라고 말할 뿐 오류는 안 난다.

실제로 2026-09-10에 그 모양을 한 번 봤다: 분석기를 처음 돌렸더니 623턴 중 138턴만
잡혔다. 계측 칸이 2026-09-08에 **추가**됐는데 정규식이 그걸 **필수**로 봤기 때문이다.
하마터면 최근 이틀치만 보고 «도구 사용 실측»이라고 적을 뻔했다.

> `_metrics_note`의 주석이 *"형식을 함부로 바꾸지 말 것 — 11월에 이 줄을 grep한다"*
> 라고 적어 두었는데, **주석은 확률을 올릴 뿐이고 보장하는 건 구조**다. 이 파일이 구조다.

## 무엇을 고정하나

- `사유=` 태그 5종 (BL-28)
- `[캐시 실행]` 줄 — 캐시가 그래프 **밖에서** 돌린 도구를 되찾는 근거
- **옛 형식도 계속 읽혀야 한다** — 계측·사유 칸이 없던 로그가 이미 쌓여 있다
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import _testenv  # noqa: F401,E402

NL = chr(10)

NEW = [
    "2026-09-11 09:00:01 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:01 INFO    [FastPath] [캐시 실행] 패턴='메모장 열어줘' | 도구=['open_app']",
    "2026-09-11 09:00:01 INFO    [Agent] 턴 완료 | 입력='메모장 열어줘' | 도구=없음 | 응답 13자"
    " | 사유=캐시 | 소요 0.05s | LLM 0회(캐시) | 토큰 0",
    "2026-09-11 09:00:10 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:10 INFO    [FastPath] [캐시 실행] 패턴='볼륨 올려줘' | 도구=['volume_up']",
    "2026-09-11 09:00:10 INFO    [Agent] 턴 완료 | 입력='소리 올려줘' | 도구=없음 | 응답 12자"
    " | 사유=캐시 | 소요 0.04s | LLM 0회(캐시) | 토큰 0",
    "2026-09-11 09:00:20 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:20 INFO    [Agent] 턴 완료 | 입력='인쇄 버튼 눌러줘' | 도구=없음 | 응답 40자"
    " | 사유=못함 | 소요 3.10s | LLM 2회 | 토큰 in=900 out=20",
    "2026-09-11 09:00:30 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:30 INFO    [Agent] 턴 완료 | 입력='고마워' | 도구=없음 | 응답 18자"
    " | 사유=잡담 | 소요 1.00s | LLM 1회 | 토큰 in=500 out=6",
    "2026-09-11 09:00:40 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:40 INFO    [Agent] 턴 완료 | 입력='계산기 열어줘' | 도구=['open_app']"
    " | 응답 12자 | 소요 2.00s | LLM 2회 | 토큰 in=800 out=10",
    # 테스트 하네스 턴 — 실사용에서 빠져야 한다
    "2026-09-11 09:00:50 DEBUG   [Agent] 승인 대기 확인 | thread=reg_99 | next=없음",
    "2026-09-11 09:00:50 INFO    [Agent] 턴 완료 | 입력='메모장 열어줘' | 도구=['open_app_fail']"
    " | 응답 5자 | 소요 0.10s | LLM 1회 | 토큰 in=10 out=1",
]

# ⚠️ 옛 형식 — 계측(2026-09-08)·사유(2026-09-10) 이전. **이것도 읽혀야 한다.**
OLD = [
    "2026-09-03 12:32:18 INFO    [Agent] 턴 완료 | 입력='메모장 띄워봐' | 도구=['open_app'] | 응답 6자",
    "2026-09-04 16:28:15 INFO    [Agent] 턴 완료 | 입력='그만 봐' | 도구=없음 | 응답 19자",
]


def run():
    passed = total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    from analyze_tool_usage import parse, is_real

    tmp = tempfile.mkdtemp(prefix="pluiz_logfmt_")
    p_new = os.path.join(tmp, "new.log")
    p_old = os.path.join(tmp, "old.log")
    io.open(p_new, "w", encoding="utf-8", newline=NL).write(NL.join(NEW) + NL)
    io.open(p_old, "w", encoding="utf-8", newline=NL).write(NL.join(OLD) + NL)

    print("=== 1. 새 형식 (BL-28) ===")
    t = parse(p_new)
    check("턴 6개", len(t) == 6)
    check("사유=캐시", t[0]["reason"] == "캐시")
    check("사유=못함", t[2]["reason"] == "못함")
    check("사유=잡담", t[3]["reason"] == "잡담")
    check("도구가 돈 턴엔 사유가 없다", t[4]["reason"] is None)

    print("=== 2. 캐시가 그래프 «밖에서» 돌린 도구를 되찾는다 ===")
    # 이게 없으면 볼륨·밝기·시간 등이 «한 번도 안 쓰인 도구»로 잘못 집계된다
    check("open_app 되찾음", t[0]["cache_tools"] == ["open_app"])
    check("volume_up 되찾음", t[1]["cache_tools"] == ["volume_up"])
    check("캐시가 아닌 턴엔 안 붙는다", t[2]["cache_tools"] == [])
    check("도구가 돈 턴에도 안 붙는다", t[4]["cache_tools"] == [])

    print("=== 3. 테스트 턴 분리 (로그의 2/3가 테스트였다) ===")
    check("pluiz_ 는 실사용", is_real(t[0]) and t[0]["thread"] == "pluiz_1")
    check("reg_ 는 실사용이 아니다", not is_real(t[5]))
    check("thread 를 앞 줄에서 물려받는다", all(x["thread"] for x in t))

    print("=== 4. 계측 칸 ===")
    check("캐시 히트 표시", t[0]["cached"] is True)
    check("소요 파싱", t[4]["sec"] == 2.0)
    check("토큰 파싱", t[4]["tok"] == "in=800 out=10")

    print("=== 5. ⚠️ 옛 형식도 계속 읽혀야 한다 ===")
    # 2026-09-10에 실제로 깨졌던 자리다 — 정규식이 계측 칸을 «필수»로 봐서
    # 623턴 중 138턴만 잡혔다. 옛 로그가 통째로 빠지면 도구 집계가 최근치만 본다.
    o = parse(p_old)
    check("계측 없는 옛 줄도 파싱된다", len(o) == 2)
    check("옛 줄의 도구가 잡힌다", o[0]["tools"] == ["open_app"])
    check("옛 줄은 소요가 None", o[0]["sec"] is None)
    check("옛 줄은 사유가 None", o[0]["reason"] is None)
    check("옛 줄은 thread 미상", o[0]["thread"] is None and not is_real(o[0]))

    print("=== 6. BL-52 — 「요청」과 「실행」이 갈라졌다 (2026-09-12~) ===")
    #
    # 🚨 옛 `도구=`는 이름과 달리 «LLM이 **요청**한 것»이었다. 승인을 **거부**한 턴에도
    #   `도구=['delete_file','delete_file']`이 찍혀 실제로 오판을 만들었다.
    #   여기서 고정하는 것은 둘이다:
    #     ① 새 줄에서 **실행이 요청과 따로** 읽힌다
    #     ② 옛 줄(`도구=`)이 **여전히** 읽힌다 — 안 그러면 09-12 이전이 통째로 빠진다
    P52 = [
        "2026-09-12 12:00:00 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_9 | next=없음",
        # 거부한 턴 — 요청은 둘, 실행은 **0개**다
        "2026-09-12 12:00:00 INFO    [Agent] 턴 완료 | 입력='아니' | "
        "요청=['delete_file', 'delete_file'] | 실행=없음 | 응답 11자"
        " | 사유=승인거부 | 소요 0.06s | LLM 0회 | 토큰 0",
        "2026-09-12 12:00:10 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_9 | next=없음",
        # 승인한 턴 — 요청은 둘(원본+재발행), 실행은 **하나**다
        "2026-09-12 12:00:10 INFO    [Agent] 턴 완료 | 입력='어' | "
        "요청=['delete_file', 'delete_file'] | 실행=['delete_file'] | 응답 20자"
        " | 소요 0.40s | LLM 1회 | 토큰 in=100 out=9",
    ]
    p52 = os.path.join(tmp, "bl52.log")
    io.open(p52, "w", encoding="utf-8", newline=NL).write(NL.join(P52) + NL)
    b = parse(p52)
    check("턴 2개", len(b) == 2)
    check("🚨 거부 턴: 요청은 둘인데 실행은 0개", b[0]["tools"] == ["delete_file"] * 2
          and b[0]["ran"] == [])
    check("🚨 승인 턴: 한 번 실행을 둘로 세지 않는다", b[1]["ran"] == ["delete_file"])
    check("새 형식은 실행 칸이 있다고 표시된다", all(x["ran_logged"] for x in b))
    check("뒤따르는 칸(사유·소요·토큰)이 여전히 읽힌다",
          b[0]["reason"] == "승인거부" and b[0]["sec"] == 0.06 and b[1]["tok"] == "in=100 out=9")
    # ⚠️ 옛 줄은 실행 칸이 없으므로 «요청을 실행으로 친다» — 그리고 그렇다고 표시한다
    check("옛 줄은 요청을 실행으로 친다", o[0]["ran"] == ["open_app"])
    check("🚨 옛 줄은 «추정»이라고 표시된다(리포트가 그렇게 말한다)",
          not o[0]["ran_logged"] and not o[1]["ran_logged"])
    check("새 형식 NEW 줄도 여전히 옛 이름으로 읽힌다", t[4]["tools"] == ["open_app"])

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
