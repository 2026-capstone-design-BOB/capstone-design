# -*- coding: utf-8 -*-
"""캐시 절감액 계산의 계약 — 숫자가 조용히 틀리지 않게 한다. (계획 1-5)

실행: python tests/test_cache_savings.py

## 왜 이 테스트가 있나

`analyze_cache_savings.py`가 내는 숫자는 **발표 슬라이드로 바로 간다.**
그런데 이 종류의 코드는 **틀려도 오류가 안 난다** — 그냥 다른 숫자가 나온다.
[BL-28 계약 테스트](test_log_format.py)가 «0턴이라고 말할 뿐 오류는 안 난다»고
적어 둔 것과 같은 자리다.

특히 두 가지가 조용히 틀린다:

1. **단가가 굴러간다.** 모델 가격표는 바뀌고(BL-57의 «별칭이 굴러간다»와 같은 성질),
   스크립트만 고치고 문서를 안 고치면 **슬라이드가 옛 숫자를 말한다.**
   → 여기서 **코드와 문서가 같은 값을 말하는지** 대조한다.
2. **평균과 중앙값을 바꿔 쓰면** 절감액이 우리에게 유리한 쪽으로 기운다.
   → 리포트가 **중앙값을 «발표엔 이 쪽»으로 표시하는지** 고정한다.

⚠️ 이 테스트는 **계산의 정의**를 고정하지 실측값을 고정하지 않는다.
   로그가 바뀌면 숫자는 당연히 바뀐다.
"""
import io
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import _testenv  # noqa: F401,E402

NL = chr(10)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 히트 2턴 · LLM 3턴. 토큰을 **일부러 치우치게** 넣었다 —
# 평균과 중앙값이 갈려야 §3의 «중앙값을 쓴다»가 검사된다.
LOG = [
    "2026-09-11 09:00:00 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:00 INFO    [Agent] 턴 완료 | 입력='메모장 열어줘' | 요청=없음 | 실행=없음"
    " | 응답 13자 | 사유=캐시 | 소요 0.10s | LLM 0회(캐시) | 토큰 0",
    "2026-09-11 09:00:01 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:01 INFO    [Agent] 턴 완료 | 입력='계산기 켜줘' | 요청=없음 | 실행=없음"
    " | 응답 12자 | 사유=캐시 | 소요 0.20s | LLM 0회(캐시) | 토큰 0",
    "2026-09-11 09:00:02 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:02 INFO    [Agent] 턴 완료 | 입력='날씨 알려줘' | 요청=['get_weather']"
    " | 실행=['get_weather'] | 응답 40자 | 소요 2.00s | LLM 1회 | 토큰 in=1000 out=100",
    "2026-09-11 09:00:03 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:03 INFO    [Agent] 턴 완료 | 입력='정리해줘' | 요청=없음 | 실행=없음"
    " | 응답 30자 | 소요 4.00s | LLM 1회 | 토큰 in=2000 out=200",
    # 🚨 긴 턴 하나가 평균을 끌어올린다. 중앙값은 안 움직인다 — 그게 이 줄의 목적이다.
    "2026-09-11 09:00:04 DEBUG   [Agent] 승인 대기 확인 | thread=pluiz_1 | next=없음",
    "2026-09-11 09:00:04 INFO    [Agent] 턴 완료 | 입력='화면 봐줘' | 요청=['describe_screen']"
    " | 실행=['describe_screen'] | 응답 200자 | 소요 9.00s | LLM 2회 | 토큰 in=30000 out=900",
    # 테스트 하네스 턴 — 실사용 집계에서 빠져야 한다
    "2026-09-11 09:00:05 DEBUG   [Agent] 승인 대기 확인 | thread=reg_1 | next=없음",
    "2026-09-11 09:00:05 INFO    [Agent] 턴 완료 | 입력='테스트' | 요청=없음 | 실행=없음"
    " | 응답 5자 | 사유=캐시 | 소요 0.01s | LLM 0회(캐시) | 토큰 0",
]


def run():
    passed = total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    import analyze_cache_savings as A

    tmp = tempfile.mkdtemp(prefix="pluiz_savings_")
    p = os.path.join(tmp, "s.log")
    io.open(p, "w", encoding="utf-8", newline=NL).write(NL.join(LOG) + NL)

    print("=== 1. 토큰 칸을 읽는다 ===")
    check("in/out 파싱", A._tokens({"tok": "in=1000 out=100"}) == (1000, 100))
    # 🚨 캐시 턴은 `토큰 0`이다. 이걸 (0,0)으로 읽으면 **LLM 턴 평균이 0쪽으로 끌려가고**
    #    절감액이 통째로 과소평가된다. «없다»와 «0이다»는 다르다.
    check("🚨 «토큰 0»은 값이 아니라 없음이다", A._tokens({"tok": "0"}) is None)
    check("«미상»도 없음이다", A._tokens({"tok": "미상"}) is None)
    check("계측 이전 턴(None)도 안 죽는다", A._tokens({"tok": None}) is None)

    print("=== 2. 파싱을 복제하지 않는다 (BL-52가 형식을 한 번 바꿨다) ===")
    # 정규식을 두 벌 두면 다음에 형식이 바뀔 때 한쪽만 고쳐진다.
    src = io.open(os.path.join(_ROOT, "scripts", "analyze_cache_savings.py"),
                  encoding="utf-8").read()
    check("analyze_tool_usage 의 parse/is_real 를 그대로 쓴다",
          "from analyze_tool_usage import parse, is_real" in src)
    # ⚠️ 리포트 라벨의 «턴 완료»가 아니라 **정규식**을 찾는다.
    #    tool_usage 쪽 패턴은 `\[Agent\] 턴 완료 \|` 다 — 그 꼴이 있으면 복제한 것이다.
    check("턴 완료 정규식을 복제하지 않았다", "[Agent] 턴 완료" not in src)

    print("=== 3. 실사용 필터가 산다 ===")
    turns = A.parse(p)
    real = [t for t in turns if A.is_real(t)]
    check("턴 6개 파싱", len(turns) == 6)
    check("reg_ 는 빠진다 → 5턴", len(real) == 5)
    hits = [t for t in real if t["cached"]]
    llm = [t for t in real if not t["cached"]]
    check("히트 2 · LLM 3", len(hits) == 2 and len(llm) == 3)
    # ⚠️ 안 거르면 히트율이 3/6=50%로 부풀어 오른다. 그게 §0 규약의 존재 이유다.
    check("🚨 필터가 히트율을 바꾼다(40% vs 50%)",
          len(hits) / len(real) == 0.4 and 3 / len(turns) == 0.5)

    print("=== 4. 평균과 중앙값이 갈린다 — 발표엔 중앙값 ===")
    import statistics
    ins = [A._tokens(t)[0] for t in llm]
    outs = [A._tokens(t)[1] for t in llm]
    check("입력 평균 11,000 · 중앙값 2,000",
          statistics.mean(ins) == 11000 and statistics.median(ins) == 2000)
    check("🚨 평균이 중앙값의 5.5배 — 긴 턴 하나가 만든다",
          statistics.mean(ins) / statistics.median(ins) == 5.5)

    def cost(i, o):
        return i / 1e6 * A.DEFAULT_IN_PRICE + o / 1e6 * A.DEFAULT_OUT_PRICE

    check("중앙값 기준 절감액이 평균 기준보다 작다(보수적)",
          cost(statistics.median(ins), statistics.median(outs)) * len(hits)
          < cost(statistics.mean(ins), statistics.mean(outs)) * len(hits))

    print("=== 5. 🚨 단가가 코드와 문서에서 같은 값인가 ===")
    # 여기가 이 파일의 핵심이다. 단가는 굴러가고(BL-57), 한쪽만 고치면
    # **슬라이드가 옛 숫자를 말한다.** 주석은 확률을 올릴 뿐이고 이 검사가 구조다.
    doc = io.open(os.path.join(_ROOT, "docs", "research", "2026-09_캐시_절감액.md"),
                  encoding="utf-8").read()
    check("문서가 입력 단가를 그대로 적고 있다",
          f"${A.DEFAULT_IN_PRICE:.2f} / 1M" in doc)
    check("문서가 출력 단가를 그대로 적고 있다",
          f"${A.DEFAULT_OUT_PRICE:.2f} / 1M" in doc)
    check("문서가 모델 이름을 그대로 적고 있다", A.DEFAULT_MODEL in doc)
    check("문서에 단가 확인 날짜가 있다", re.search(r"20\d\d-\d\d-\d\d 확인", doc))

    print("=== 6. 리포트가 «환산»임을 말하는가 ===")
    # 측정과 환산을 구분하지 않으면 이 저장소가 반복해서 데인 «확인하지 않고
    # 됐다고 말하는 것»의 숫자 판본이 된다.
    check("환산이라고 적는다", "환산" in src)
    check("중앙값 쪽을 «발표엔 이 쪽»으로 가리킨다", "발표엔 이 쪽" in src)
    check("평균 쪽에 «낙관적»이라고 붙인다", "낙관적" in src)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
