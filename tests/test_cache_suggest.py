"""
임베딩 «제안» 검증 — M5 §5-2. mock (ONNX 모델이 없으면 건너뛴다)
실행: python tests/test_cache_suggest.py

## 왜 이 파일이 생겼나

임베딩으로 **실행**을 결정하려던 원안(§5-1)은 실측으로 무효가 됐다 —
오매칭 0인 임계가 **존재하지 않는다**(마진이 어느 설정에서도 음수).
그래서 임베딩은 **제안**만 하고 실행은 사용자의 「네」가 정한다(§5-2).

## 이 파일이 지키는 것

  ① 🔒 **제안은 아무것도 실행하지 않는다** — 후보를 돌려줄 뿐이다
  ② 🚨 **점수를 문지기로 쓰지 않는다.** 구현 중 재보니 `'뻥카 치냐'`가
     코사인 **0.552**로 정상 매칭(0.388)보다 **높았다.** 실제 문지기는
     `_shares_token()`(낱말 겹침)이고, 이게 없으면 잡담에 제안이 나간다
  ③ 「네」 하면 **실제로 실행되므로** 안전 조건은 그대로 건다 —
     안전 도구만(V5) · 복합 명령 제외(BL-15) · 대조 게이트(BL-27)
  ④ 모델이 없으면 **조용히 아무 일도 안 한다**(캐시는 핵심 경로다)
"""
import _testenv  # noqa: F401
import sys, os, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ⚠️ BL-11 — 사용자의 실제 캐시를 건드리지 않는다
os.environ["PLUIZ_CACHE_FILE"] = os.path.join(
    tempfile.gettempdir(), "pluiz_test_suggest.json")

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


from core.command_cache import CommandCache, LEARNABLE_TOOLS
from core.graph_agent import _offline_reply, _OFFLINE_MSG

cache = CommandCache()


print("[1] 🔒 제안은 실행하지 않는다 · 계약")

hit = cache.suggest("밝기 좀 낮춰봐")
check("(entry, score) 튜플을 돌려준다", hit is None or (isinstance(hit, tuple) and len(hit) == 2))
check("suggest()가 execute를 부르지 않는다",
      "execute" not in cache.suggest.__doc__ or "실행하지 않는다" in cache.suggest.__doc__)

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "core", "command_cache.py"), encoding="utf-8").read()
body = src[src.find("def suggest(self"):src.find("def _shares_token")]
check("🔒 suggest() 안에서 도구를 실행하지 않는다",
      "execute" not in body and "_get_tools_map" not in body,
      "제안이 실행하면 §5-1로 되돌아간 것이다")


_EMB_OK = hit is not None
if not _EMB_OK:
    print("  ⚠️ 임베딩 모델이 없어 [2]~[4]를 건너뜁니다 (models/embed)")


print("")
print("[2] 🚨 점수가 아니라 낱말 겹침이 문지기다")

# 구현 중 실측한 값들. 점수만 보면 잡담이 정상 매칭을 이긴다.
check("_shares_token이 있다", hasattr(cache, "_shares_token"))
check("잡담은 후보와 낱말이 안 겹친다",
      not cache._shares_token("뻥카 치냐", "소리 내려줘"),
      "이게 True면 코사인 0.965짜리 잡담이 제안으로 나간다")
check("같은 대상이면 겹친다", cache._shares_token("메모장 하나 띄워봐", "메모장 열어줘"))
check("대상이 같으면 동작이 안 잡혀도 겹친다",
      cache._shares_token("소리 조금만 더 크게", "소리 올려줘"),
      "Stage 1이 (entity AND action)을 요구해 놓친 자리 — 여기가 제안의 값이다")

if _EMB_OK:
    NOISE = ["뻥카 치냐", "오늘 저녁 뭐 먹지", "안녕 반가워", "나 지금 바빠",
             "그래서 어떻게 됐어", "재밌겠다"]
    bad = [q for q in NOISE if cache.suggest(q) is not None]
    check("잡담 6개에 제안이 하나도 안 나간다", not bad, f"→ {bad}")

    GOOD = {
        "밝기 좀 낮춰봐": "밝기 내려줘",
        "음소거 좀": "음소거해줘",
        "바탕화면 좀 보자": "바탕화면 보여줘",
        "배터리 상태 어때": "배터리 확인해줘",
    }
    for q, want in GOOD.items():
        r = cache.suggest(q)
        check(f"{q!r} → {want!r}", r is not None and r[0].pattern == want,
              f"→ {r[0].pattern!r}" if r else "→ 제안 없음")


    # 🔖 2026-09-11 실기 — `'밝기 좀 낮춰봐'` 는 제안이 나오는데
    #    **`'어 밝기 좀 낮춰봐'` 는 안 나왔다.** 「어」 한 글자가 전역 순위를 흔들어
    #    맞는 후보를 top-3 **밖으로** 밀어낸 것이다. 그래서 «순위 → 걸러내기»를
    #    **«걸러내기 → 순위»로 뒤집었다.** 짧은 문장 임베딩은 이런 잡음에 약하다.
    FILLER = ["어 밝기 좀 낮춰봐", "어 밝기 낮춰줘", "음 그럼 바탕화면 좀 보자",
              "아 소리 좀 키워줘", "소리 좀 키워줘"]
    miss = [q for q in FILLER if cache.suggest(q) is None]
    check("🚨 «어/음/아» 같은 군말이 붙어도 제안이 나온다", not miss, f"→ {miss}")
    check("군말이 있든 없든 같은 대상을 고른다",
          (cache.suggest("어 밝기 좀 낮춰봐") or [None])[0] is not None
          and cache.suggest("밝기 좀 낮춰봐")[0].tool_calls[0]["name"]
              == cache.suggest("어 밝기 좀 낮춰봐")[0].tool_calls[0]["name"],
          "패턴은 달라도 **도구는 같아야** 한다")

check("걸러낸 뒤에 순위를 본다(반대로 하면 군말에 흔들린다)",
      "_shares_token(text, keys[i])" in src and "max(cand" in src)
# 🔖 2026-09-11 — 뜻 없는 바닥값이 멀쩡한 명령을 갈랐다
# ('소리 좀 키워줘' 0.14는 막히고 '어 소리 좀 키워봐' 0.16은 통과했다).
check("🚨 점수 임계를 두지 않는다", "SUGGEST_MIN_COS" not in src,
      "순위 말고 뜻이 없는 숫자를 문지기로 쓰면 갈림만 생긴다")


print("")
print("[3] 🚨 「네」 하면 실행된다 — 안전 조건은 느슨하게 두지 않는다")

# V5 — 삭제·클릭·타이핑은 제안조차 하지 않는다
check("V5: 안전 도구만 후보에 넣는다", "LEARNABLE_TOOLS" in body,
      "제안을 수락하면 승인(HITL) 없이 실행된다")
check("V5: 도구가 하나인 것만", "len(calls) != 1" in body)
if _EMB_OK:
    for q in ("a.txt 지워줘", "파일 삭제해줘", "메모장에 회의록이라고 적어줘"):
        check(f"위험한 말에는 제안 없음: {q!r}", cache.suggest(q) is None)

# 🚨 V3 — 반대 동작을 제안하지 않는다.
# 2026-09-11에 테스트가 잡은 사고: '메모장에 회의록이라고 적어줘' 에
# '메모장 꺼줘'(close_app)가 1등으로 올라왔다. 「네」 했으면 쓰던 글이 날아간다.
check("V3: 어긋나는 동작을 거른다", "_AMBIGUOUS_ACTIONS" in src)
check("V3: 동작이 둘 다 잡히면 같아야 한다",
      not cache._shares_token("메모장 열어줘", "메모장 꺼줘"),
      "열다/닫다가 통과하면 반대 동작이 실행된다")
check("V3: 동작을 모르면 열기/닫기를 제안하지 않는다",
      not cache._shares_token("메모장에 회의록이라고 적어줘", "메모장 꺼줘"))
check("V3: 대상만으로 뜻이 좁혀지는 건 통과한다",
      cache._shares_token("소리 조금만 더 크게", "소리 올려줘"),
      "여기까지 막으면 제안 기능 자체가 죽는다")

# BL-15 — 복합 명령은 절반만 실행되면 그게 사고다
check("복합 명령을 거른다", "is_compound_command" in body)
if _EMB_OK:
    check("'메모장 열고 계산기도 열어줘' 제안 없음",
          cache.suggest("메모장 열고 계산기도 열어줘") is None)

# BL-27 — find()와 같은 판정
check("대조 게이트를 건다", "has_contrast_marker" in body)
if _EMB_OK:
    check("'메모장 말고 계산기 열어줘' 제안 없음",
          cache.suggest("메모장 말고 계산기 열어줘") is None)


print("")
print("[4] 오프라인 응답 — 거절 대신 제안 (M5 §5-2 ①)")

check("cache가 없으면 오늘과 똑같다", _offline_reply(None, "밝기 낮춰줘") == _OFFLINE_MSG)


class _Boom:
    def suggest(self, t):
        raise RuntimeError("일부러")


check("제안이 터져도 턴을 죽이지 않는다",
      _offline_reply(_Boom(), "밝기 낮춰줘") == _OFFLINE_MSG)


class _Fake:
    class E:
        pattern = "밝기 내려줘"
    def suggest(self, t):
        return (self.E(), 0.7)


msg = _offline_reply(_Fake(), "밝기 좀 낮춰봐")
check("제안이 있으면 되묻는다", "밝기 내려줘" in msg and "말씀이신가요" in msg)
check("되묻되 «못 했다»를 숨기지 않는다", "처리하지 못했" in msg,
      "제안만 하고 실패를 안 말하면 «한 걸 말하지 않는 것»(BL-32)과 같은 모양이다")
check("어떻게 답하면 되는지 알려준다", "네" in msg)
check("🚨 제안이 없으면 오늘과 똑같다",
      _offline_reply(type("N", (), {"suggest": lambda s, t: None})(), "x") == _OFFLINE_MSG)

agent_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "core", "graph_agent.py"), encoding="utf-8").read()
# 2026-09-11: 두 분기가 각자 `_offline_reply`를 부르던 것을 `_dead_end` 하나로 합쳤다
# (실패 턴이 로그를 안 남기던 것을 고치면서 — 아래 «턴 실패» 검사 참조).
# 그래서 «호출이 2개인가»가 아니라 **«두 분기가 모두 네트워크 여부를 판정해 넘기는가»** 를 본다.
check("네트워크 오류일 때만 제안한다",
      agent_src.count('"network" if _is_network_error(') == 2,
      "두 분기(재시도 전/후) 모두 _dead_end에 network 여부를 넘겨야 한다")
check("제안은 network 판정일 때만 나간다",
      '_offline_reply(getattr(self, "cache", None), user_input)' in agent_src
      and 'if kind == "network":' in agent_src)
check("네트워크 오류가 아니면 그대로 오류를 말한다",
      "명령 처리 중 오류가 발생했어요" in agent_src)

# 🚨 2026-09-11 실기: 오프라인 턴 6개가 **로그 한 줄 없이** 사라졌다.
#   세 경로(타임아웃·네트워크·기타)가 전부 `return`만 했기 때문이다.
check("실패한 턴은 반드시 로그를 남긴다", '"턴 실패 | 입력=%r | 사유=%s' in agent_src,
      "ERROR 0건인데 턴이 사라지는 일이 다시 생기면 안 된다")
check("타임아웃이면 오프라인인지 확인한다",
      'if kind == "timeout" and _looks_offline():' in agent_src,
      "오프라인에서는 네트워크 오류보다 타임아웃이 먼저 난다 — 그래서 타임아웃은 최종 판정이 아니다")

# 🚨 거짓 약속 금지: 예전 문구는 «앱 실행은 오프라인에서도 쓸 수 있어요!» 라고
#   약속했는데 캐시가 빗나가면 안 됐다(실기에서 «메모장 열어달라»가 실패).
check("오프라인 문구가 되는 범위를 넘겨 약속하지 않는다",
      "오프라인에서도 쓸 수 있어요" not in _OFFLINE_MSG
      and "이미 익혀 둔 명령" in _OFFLINE_MSG,
      "BL-12·19·26·35(«안 한 걸 했다고 말하기»)의 오프라인 버전이 된다")


# ── 🚨 BL-41 — 읽기 관문이 실제로 이 문장을 잡는가 ──────────────────
#
# 2026-09-11 실기에서 **이 문장이 캐시에 박혔다**(«메뉴 추천»이 사라진 채):
#     "어 그 pc 밝기 올려 주고 오늘 저녁 메뉴 좀 추천해 주라 소윤이 배고파" → [brightness_up]
#
# 쓰기 관문이 `has_uncovered_command`를 부르도록 고쳤는데(BL-41),
# **그 전제는 이 함수가 이 문장을 True로 읽는다는 것**이다. 전제를 여기서 못 박는다 —
# 배선은 `test_cache_wire.py` §8이 보고, **판정 자체는 여기가 본다.**
print("")
print("=== 🚨 BL-41 — 실기에서 오염시킨 그 문장을 읽기 관문이 잡는가 ===")
_live = "어 그 pc 밝기 올려 주고 오늘 저녁 메뉴 좀 추천해 주라 소윤이 배고파"
check("🚩 원문 재현: 읽기 관문이 «잔여 명령 있음»으로 읽는다",
      cache.has_uncovered_command(cache._normalize(_live)) is True,
      "이게 False가 되면 BL-41 수정이 무력화되고 같은 오염이 다시 쌓인다")

# 🔖 **왜 `is_compound_command` 하나로는 부족했는지**도 같이 남긴다 —
#    이 사실이 바뀌면(넓어지면) BL-41의 근거가 사라지므로 알고 싶다.
from core.fast_path import is_compound_command as _icc
check("참고: is_compound_command는 이 문장을 놓친다 (BL-41의 근거)",
      _icc(cache._normalize(_live)) is False,
      "이게 True로 바뀌면 두 관문 중 하나로 충분해진 것 — 주석을 갱신할 때다")

check("정상 단일 명령은 읽기 관문을 통과한다(회귀)",
      cache.has_uncovered_command(cache._normalize("소리 키워줘")) is False)


print("")
print(chr(61) * 60)
print(f"결과: {passed}/{total} 통과")
print(chr(61) * 60)
sys.exit(0 if passed == total else 1)
