# -*- coding: utf-8 -*-
"""나가는 말은 **한 문을 지난다** · 예외를 낭독하지 않는다 (감사 G-13·G-14)

실행: python tests/test_output_masking.py

## 왜 이 테스트가 있나

[전수 감사](../docs/research/2026-09_안전에러_전수감사.md)가 4층(출력 마스킹)을 재 보니
**호출 지점이 전 저장소에 한 곳**이었다 — 정상 완료 경로. 그런데 턴이 끝나는 길은 여덟이다:

| 나가는 말 | 예전 | 무엇이 실릴 수 있나 |
|---|---|---|
| 정상 완료 | ✅ | |
| 승인 질문(`interrupt`) | ❌ | 파일 **전체 경로** |
| 제안 수락 실행 결과 | ❌ | 도구 출력 그대로 |
| 보안 차단 · `_dead_end` 여섯 갈래 | ❌ | **예외 원문** |
| 감시 알림(`_broadcast`) | ❌ | **화면에서 읽은 글자** |

🔑 **그래서 «호출을 일곱 군데 더 넣는» 식으로 고치지 않았다.** 그러면 다음에 `return`
이 하나 늘 때 또 샌다 — 그게 이 저장소가 반복해 데인 모양이고,
[BL-26](../docs/BACKLOG.md)의 유령 창 검사와 [BL-12](../docs/BACKLOG.md)의 포커스 확인이
**딱 그렇게** 두 곳에 안 붙어 있었다(감사 G-08·G-09).
**본체를 `_run_turn` 으로 내리고 `run_async` 를 관문으로 만들었다.**

## 🚨 G-14 — 예외가 **그대로 낭독**됐다

`f"명령 처리 중 오류가 발생했어요: {exc}"` — 예외 문자열에는 **길이 상한이 없고**,
이 답은 **TTS 로도 그대로 간다.** Gemini 400 에러 한 번이면 **영어 수백 자가 낭독된다.**
원문은 **로그로만** 보낸다 — `core/command_cache._verdict` 와 같은 규칙이다.

## 🚨 양방향

«오류면 짧게 말한다»만 고정하면 **모든 실패를 한 문장으로 뭉개는 수정**이 통과한다.
오프라인 안내(캐시 제안 포함)와 타임아웃 안내는 **서로 다른 말이어야** 한다 — §2-③이 본다.

✅ **키 유출이 관측된 적은 없다**(감사: `logs/` 를 `AIza…` 로 훑어 0건).
가능성을 닫는 것이지 사고를 고치는 게 아니다 — **과장하지 않는다.**
"""
import asyncio
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 진짜처럼 생겼지만 **가짜다.** (형식만 맞으면 정규식이 잡는다)
FAKE_KEY = "AIza" + "B" * 32
FAKE_RRN = "901010-1234567"


class Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rec = []

    def emit(self, r):
        self.rec.append((r.levelno, r.getMessage()))


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
        from core.graph_agent import PluizGraphAgent, _ERROR_MSG, _TIMEOUT_MSG
        from core.security import mask_sensitive_output
        has_mod = True
    except Exception as e:                                    # noqa: BLE001
        PluizGraphAgent = _ERROR_MSG = _TIMEOUT_MSG = mask_sensitive_output = None
        has_mod = False
        _why = f"{type(e).__name__}: {e}"

    ga_src = io.open(os.path.join(_ROOT, "core", "graph_agent.py"),
                     encoding="utf-8").read()
    main_src = io.open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()

    def bare_agent():
        """`__init__` 을 안 거친다 — LLM·그래프·캐시를 만들지 않는다."""
        return PluizGraphAgent.__new__(PluizGraphAgent)

    # ── §1 관문 — 본체가 무엇을 돌려주든 지나간다 ──────────────────
    print("\n§1 관문 — `run_async` 를 지나지 않고 나가는 말은 없다")
    if not has_mod:
        cannot_judge(["API 키가 가려진다", "주민번호가 가려진다",
                      "🔑 본문은 그대로 남는다 (통째로 지우지 않는다)",
                      "빈 응답도 죽지 않는다"],
                     f"core 를 못 불러왔다 ({_why}) — `conda activate pluiz` 로 다시 돌릴 것")
    else:
        ag = bare_agent()

        async def _fake_turn(text, thread_id="default"):
            return f"열쇠는 {FAKE_KEY} 이고 번호는 {FAKE_RRN} 입니다."
        ag._run_turn = _fake_turn
        out = asyncio.run(ag.run_async("뭐였지"))
        check("API 키가 가려진다", FAKE_KEY not in out and "마스킹됨" in out, f"→ {out!r}")
        check("주민번호가 가려진다", FAKE_RRN not in out, f"→ {out!r}")
        check("🔑 본문은 그대로 남는다 (통째로 지우지 않는다)",
              "열쇠는" in out and "번호는" in out, f"→ {out!r}")

        async def _empty(text, thread_id="default"):
            return ""
        ag._run_turn = _empty
        check("빈 응답도 죽지 않는다", asyncio.run(ag.run_async("x")) == "")

    # ── §2 G-14 — 예외를 낭독하지 않는다 ───────────────────────────
    print("\n§2 예외 원문은 **로그로만** 간다 (TTS 로 나가는 말이다)")
    if not has_mod:
        cannot_judge(["① 예외 원문이 응답에 없다",
                      "① 짧다 (소리로 나갈 수 있는 길이다)",
                      "② 로그에는 원문이 남는다",
                      "③ 🚨 타임아웃·오프라인 안내를 «오류»로 뭉개지 않았다"],
                     "core 를 못 불러왔다")
    else:
        ag = bare_agent()
        ag._clear_thread = lambda t: None
        ag.cache = None

        long_exc = RuntimeError(
            "400 INVALID_ARGUMENT: " + "the model produced an invalid response " * 8)
        lg = logging.getLogger("pluiz.Agent")
        h = Grab()
        lg.addHandler(h)
        try:
            reply = ag._dead_end("t1", "메모장 열어줘", 0.0, "error", long_exc)
        finally:
            lg.removeHandler(h)
        check("① 예외 원문이 응답에 없다",
              "INVALID_ARGUMENT" not in reply and "invalid response" not in reply,
              f"→ {reply!r}")
        check("① 짧다 (소리로 나갈 수 있는 길이다)", len(reply) < 60, f"→ {len(reply)}자")
        check("② 로그에는 원문이 남는다 (사람이 되짚어야 한다)",
              any("INVALID_ARGUMENT" in m for _, m in h.rec), f"→ {h.rec[:1]}")

        # 🚨 반대 방향 — 모든 실패를 한 문장으로 뭉개는 수정을 막는다.
        ag2 = bare_agent()
        ag2._clear_thread = lambda t: None
        ag2.cache = None
        timeout_reply = ag2._dead_end("t2", "뭐 해줘", 0.0, "timeout")
        check("③ 🚨 타임아웃 안내는 «오류»와 다른 말이다",
              timeout_reply != _ERROR_MSG and timeout_reply == _TIMEOUT_MSG,
              f"→ {timeout_reply!r}")

    # ── §3 구조 — 관문이 관문인지 ─────────────────────────────────
    #
    # 🔑 §1은 «오늘 그렇게 돈다»를 본다. 여기는 «새 `return` 이 생겨도 그렇다»를 본다.
    print("\n§3 구조 — 끝나는 길이 여덟인데 문은 하나다")
    turn = ga_src[ga_src.index("    async def _run_turn"):ga_src.index("    # 「못 함」으로 분류할")]
    returns = len([ln for ln in turn.splitlines() if ln.strip().startswith("return ")])
    check("본체에 나가는 길이 여럿이다 (여덟 안팎)", returns >= 7, f"→ {returns}개")
    check("🚨 그 길들이 전부 한 문을 지난다",
          "return _mask_out(await self._run_turn(" in ga_src)
    check("본체를 밖에서 부르는 곳이 없다 (관문을 우회하지 않는다)",
          ga_src.count("self._run_turn(") == 1, "다른 호출자가 생겼다")
    # 🔑 주석은 떼고 본다 — «예전에 이랬다»는 **남아 있어야** 하고,
    #   남으면 안 되는 것은 **코드**다. (세 번째로 같은 함정을 밟았다)
    code_only = chr(10).join(ln.split("#", 1)[0] for ln in ga_src.splitlines())
    check("🚨 예외 낭독이 돌아오지 않았다",
          "오류가 발생했어요: {exc}" not in code_only, "예외 원문이 다시 응답에 실린다")
    check("마스킹 실패를 삼키지 않는다 (`print` 가 아니다)",
          "출력 마스킹 생략(무시)" not in ga_src and "[마스킹] 실패" in ga_src)
    check("근거가 코드에 적혀 있다 (감사 G-13·G-14)",
          "G-13" in ga_src and "G-14" in ga_src)

    # ── §4 감시 알림 — 에이전트를 안 거치는 길 ─────────────────────
    #
    # ⚠️ 여기는 **소스만 본다.** `main.py` 를 부르면 서버 모듈이 뜨고 TTS 가 망을 탄다 —
    #   테스트가 제품 상태를 건드리면 안 된다(`_testenv` 의 규칙과 같은 이유).
    print("\n§4 감시 알림 — 화면에서 읽은 글자가 그대로 나가던 자리")
    bc = main_src[main_src.index("async def _broadcast"):]
    check("알림도 마스킹을 지난다", "mask_sensitive_output" in bc)
    check("🔑 **소리보다 먼저** 가린다 (읽어 준 뒤 가리면 늦다)",
          bc.index("mask_sensitive_output") < bc.index("to_bytes_async"),
          "TTS 뒤에서 마스킹한다")
    check("마스킹 실패가 로그로 간다", "알림 마스킹 실패" in bc)
    check("근거가 코드에 적혀 있다 (감사 G-13)", "G-13" in bc)

    # ── §5 마스킹 자체 — 가리고, 두 번 걸어도 같다 ─────────────────
    #
    # 🔑 «두 번 걸려도 같다»는 §1의 관문과 안쪽 기록용 마스킹이 **겹쳐도 안전하다**는
    #   근거다. 이게 깨지면 응답이 `***(마스킹됨)(마스킹됨)` 처럼 망가진다.
    print("\n§5 마스킹 자체 — 실제로 가리는가 · 멱등인가")
    if not has_mod:
        cannot_judge(["API 키를 가린다", "주민번호를 가린다", "카드번호를 가린다",
                      "🔑 두 번 걸어도 결과가 같다", "멀쩡한 숫자는 안 건드린다"],
                     "core 를 못 불러왔다")
    else:
        once = mask_sensitive_output(f"키 {FAKE_KEY} · 주민 {FAKE_RRN} · 카드 1234-5678-9012-3456")
        check("API 키를 가린다", FAKE_KEY not in once, f"→ {once}")
        check("주민번호를 가린다", FAKE_RRN not in once, f"→ {once}")
        check("카드번호를 가린다", "1234-5678-9012-3456" not in once, f"→ {once}")
        check("🔑 두 번 걸어도 결과가 같다 (멱등)",
              mask_sensitive_output(once) == once, f"→ {mask_sensitive_output(once)}")
        plain = "볼륨을 50%로 맞췄어요. 2026년 9월 19일입니다."
        check("멀쩡한 숫자는 안 건드린다", mask_sensitive_output(plain) == plain,
              f"→ {mask_sensitive_output(plain)}")

    if skipped:
        print(f"\n결과: {passed}/{total} · 🚨 판정 불가 {skipped}건 — 초록이 아니다")
        print("   나가는 말의 위생을 다 못 쟀다. `conda activate pluiz` 로 다시 돌릴 것")
    else:
        print(f"\n결과: {passed}/{total} 통과")
    return passed == total and skipped == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
