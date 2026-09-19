# -*- coding: utf-8 -*-
"""빠른 경로의 계약 — **그물이 없는 자리에서는 지어내지 않는다** (감사 G-03)

실행: python tests/test_fast_hit_contract.py

## 왜 이 테스트가 있나

[전수 감사](../docs/research/2026-09_안전에러_전수감사.md)의 **G-03**:
*«캐시 히트 턴은 정직성 그물 넷이 전부 비켜간다»*.

| 그물 | 빠른 경로(`fast_hit`) 턴에서 | 왜 |
|---|---|---|
| `watch_notice_to_deliver` | 해당 없음 | 감시 도구는 빠른 경로 대상이 아니다 |
| `detect_watch_lie` | ❌ **명시적으로 제외** | 도구를 그래프 밖에서 돌려 «도구 0개»로 보인다 |
| `verify_output` ① 빈 응답 | ❌ 무력 | 응답이 비지 않는다 |
| `verify_output` ② 도구 오류 | ❌ **구조적으로 무력** | `ToolMessage` 가 없어 `tool_errors` 가 항상 빈 리스트 |

**그물은 고장 난 게 아니다 — 검사할 재료가 이 경로에 없는 것이다.** §4가 그걸 둘로
나눠 보여 준다(재료가 있으면 잡는다 / 빠른 경로 모양이면 못 잡는다).
누가 빠뜨린 것도 아니다. **절대규칙 2**(캐시 결과도 `messages` 에 누적한다)의
그림자이고, 그 규칙을 건드리는 자리가 **맥락 붕괴 버그가 났던 자리**다.

## 📜 그래서 «그물을 새로 치는» 대신 **계약을 못 박는다**

진실을 아는 자리는 **정확히 둘**이고, 이 파일이 그 둘을 지킨다:

| # | 자리 | 무엇을 지는가 |
|---|---|---|
| ① | `CommandCache._verdict` | 다 됨 / 일부 / 전부 실패를 사실대로 말한다 (감사 G-01) |
| ② | 각 도구의 반환값(`core/tool_result.py` 의 ✓/✗) | **라우터는 그걸 그대로 돌려준다** |

🔑 **감사는 «유일하게 진실을 아는 자리는 `execute_sync` 자신»이라고 적었는데 둘이었다.**
라우터도 같은 `fast_hit` 을 만든다 — 2026-09-19에 바로잡았다.

🚫 **`fast_path.py` 와 `router.py` 는 결과 문장을 만들지 않는다.** 거기서 «✓ …했어요»를
지어내는 순간, 그걸 검사할 그물이 **하나도 없다.** §3이 그것을 **구조로** 검사한다 —
주석은 확률을 올릴 뿐이고 보장하는 건 구조다.
"""
import io
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(*parts):
    return io.open(os.path.join(_ROOT, *parts), encoding="utf-8").read()


# ── 가짜 부품 ────────────────────────────────────────────────────────
class FakeTool:
    """도구 하나. `boom` 이면 부른 순간 터진다."""

    def __init__(self, name, out="됐어요", boom=None):
        self.name = name
        self._out = out
        self._boom = boom
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        if self._boom:
            raise self._boom
        return self._out


class Entry:
    def __init__(self, calls, template="✓ 볼륨 올렸습니다."):
        self.pattern = "볼륨 올려줘"
        self.response_template = template
        self.tool_calls = calls


class FakeCache:
    """`find` → `execute_sync` → `increment_hit` 만 갖는 최소 캐시."""

    def __init__(self, entry, out="✓ 볼륨 올렸어요", boom=None):
        self._entry = entry
        self._out = out
        self._boom = boom
        self.hits = []

    def find(self, text):
        return (self._entry, 1.0) if self._entry else None

    def execute_sync(self, entry):
        if self._boom:
            raise self._boom
        return self._out

    def increment_hit(self, pattern):
        self.hits.append(pattern)


class Grab(logging.Handler):
    """로거에 실제로 찍힌 것을 모은다 (`print` 였다면 여기 안 잡힌다)."""

    def __init__(self):
        super().__init__()
        self.rec = []

    def emit(self, r):
        self.rec.append((r.levelno, r.getMessage()))


def _with_log(name, fn):
    lg = logging.getLogger(f"pluiz.{name}")
    h = Grab()
    lg.addHandler(h)
    try:
        return fn(), h.rec
    finally:
        lg.removeHandler(h)


def _fake_module(modname, **attrs):
    """`from tools.web import youtube_search` 를 가로챈다 (라우터는 lazy import 다)."""
    import types
    m = types.ModuleType(modname)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


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
        from core.fast_path import resolve_fast_path
        from core.command_cache import CommandCache
        has_core = True
    except Exception as e:                                    # noqa: BLE001
        resolve_fast_path = CommandCache = None
        has_core = False
        _why_core = f"{type(e).__name__}: {e}"

    try:
        from core.graph import verify_output
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        has_graph = True
    except Exception as e:                                    # noqa: BLE001
        has_graph = False
        _why_graph = f"{type(e).__name__}: {e}"

    fp_src = _src("core", "fast_path.py")
    rt_src = _src("core", "router.py")
    gr_src = _src("core", "graph.py")
    cc_src = _src("core", "command_cache.py")

    # ── §1 계약 ① — 캐시가 낸 문장이 **그대로** 나간다 ──────────────
    print("\n§1 계약 ① — 캐시 문장을 빠른 경로가 손대지 않는다")
    if not has_core:
        cannot_judge(
            ["성공 문장이 그대로 나간다",
             "실패 문장도 그대로 나간다 (성공처럼 꾸미지 않는다)",
             "«일부만»도 그대로 나간다",
             "히트를 실제로 센다",
             "🚨 실패한 도구가 캐시를 지나 사용자까지 «실패»로 온다"],
            f"core 를 못 불러왔다 ({_why_core}) — `conda activate pluiz` 로 다시 돌릴 것")
    else:
        out = resolve_fast_path("볼륨 올려줘", FakeCache(Entry([]), out="✓ 볼륨 올렸어요"))
        check("성공 문장이 그대로 나간다", out == "✓ 볼륨 올렸어요", f"→ {out!r}")

        fail = CommandCache._FAIL_ALL
        out = resolve_fast_path("볼륨 올려줘", FakeCache(Entry([]), out=fail))
        check("실패 문장도 그대로 나간다 (성공처럼 꾸미지 않는다)", out == fail, f"→ {out!r}")

        part = "일부만 실행됐어요 — 1개는 됐고 1개는 안 됐어요. 확인해 주시겠어요?"
        out = resolve_fast_path("볼륨 올려줘", FakeCache(Entry([]), out=part))
        check("«일부만»도 그대로 나간다", out == part, f"→ {out!r}")

        c = FakeCache(Entry([]))
        resolve_fast_path("볼륨 올려줘", c)
        check("히트를 실제로 센다", c.hits == ["볼륨 올려줘"], f"→ {c.hits}")

        # 🚨 두 자리(`_verdict` ↔ `fast_path`)가 **실제로 이어져 있는지**를 본다.
        #   가짜 문자열이 아니라 진짜 캐시가 진짜 실패한 도구를 돌린 결과로 시험한다.
        real = CommandCache.__new__(CommandCache)
        boom = FakeTool("volume_up", boom=RuntimeError("장치를 못 찾았다"))
        real._tools_map = {"volume_up": boom}
        real._get_tools_map = lambda: real._tools_map
        real.find = lambda t: (Entry([{"name": "volume_up", "args": {}}]), 1.0)
        real.increment_hit = lambda p: None
        out = resolve_fast_path("볼륨 올려줘", real)
        check("🚨 실패한 도구가 캐시를 지나 사용자까지 «실패»로 온다",
              "볼륨 올렸" not in out and ("못" in out or "실행하지" in out), f"→ {out!r}")

    # ── §2 계약 ② — 라우터 결과가 **그대로** 나간다 ─────────────────
    print("\n§2 계약 ② — 라우터는 도구 반환값을 그대로 돌려준다")
    if not has_core:
        cannot_judge(["도구의 ✓ 문장이 그대로 나간다",
                      "🚨 도구의 ✗ 실패 문장도 **그대로** 나간다 (BL-58과 같은 자리)"],
                     "core 를 못 불러왔다")
    else:
        def _route(text):
            from core.router import route_deterministic
            return route_deterministic(text)

        for label, ret, expect in [
            ("도구의 ✓ 문장이 그대로 나간다", "✓ 유튜브에서 '아이유'를 검색했어요", None),
            ("🚨 도구의 ✗ 실패 문장도 **그대로** 나간다 (BL-58과 같은 자리)",
             "✗ 인터넷에 연결돼 있지 않아요", None),
        ]:
            tool = FakeTool("youtube_search", out=ret)
            saved = sys.modules.get("tools.web")
            sys.modules["tools.web"] = _fake_module("tools.web", youtube_search=tool)
            try:
                out = resolve_fast_path("유튜브에서 아이유 틀어줘", None, _route)
            finally:
                if saved is None:
                    sys.modules.pop("tools.web", None)
                else:
                    sys.modules["tools.web"] = saved
            check(label, out == (expect or ret), f"→ {out!r}")

    # ── §3 🚫 구조 — 빠른 경로는 결과 문장을 **만들 수 없다** ────────
    #
    # 🔑 §1·§2는 «오늘 그렇게 돈다»를 본다. 여기는 «내일도 그럴 수밖에 없다»를 본다.
    #   반환문 자체를 세므로, 누가 «✓ …했어요»를 지어내는 분기를 새로 만들면 걸린다.
    print("\n§3 🚫 구조 — 지어낼 자리가 아예 없다 (반환문 전수)")
    body = fp_src[fp_src.index("def resolve_fast_path"):]
    returns = {r.strip() for r in re.findall(r"^\s*return (.+)$", body, re.M)}
    allowed = {"None", "str(result)", "str(routed)"}
    check("`resolve_fast_path` 는 None · 캐시 결과 · 라우터 결과만 돌려준다",
          returns <= allowed, f"→ 허용 밖: {sorted(returns - allowed)}")

    rt_body = rt_src[rt_src.index("def route_deterministic"):]
    rt_returns = [r.strip() for r in re.findall(r"^\s*return (.+)$", rt_body, re.M)]
    bad_rt = [r for r in rt_returns
              if r != "None" and not re.match(r"str\(\w+\.invoke\(", r)]
    check("라우터의 모든 반환은 `str(도구.invoke(…))` 아니면 None",
          not bad_rt, f"→ 허용 밖: {bad_rt}")
    check("🚫 라우터가 성공 문구를 직접 쓰지 않는다 («…했어요» 리터럴이 없다)",
          not re.search(r'"[^"\n]*했어요', rt_body), "라우터 본문에 완성된 성공 문장이 있다")

    # ── §4 그물이 왜 못 잡는지 — **재료가 없다** ─────────────────────
    print("\n§4 그물은 고장 난 게 아니다 — 이 경로에 검사할 재료가 없다")
    if not has_graph:
        cannot_judge(
            ["재료가 있으면 그물은 잡는다 (도구 오류 + 성공투 응답)",
             "🚨 같은 거짓말이 빠른 경로 모양이면 **안 잡힌다**",
             "빈 응답 복구도 이 경로에선 할 일이 없다",
             "🔑 같은 그물이 «볼륨 올렸어요»는 성공으로 읽지도 못한다 (감사 G-12 증거)"],
            f"core.graph 를 못 불러왔다 ({_why_graph}) — langgraph 가 있는 `pluiz` 환경이 필요하다")
    else:
        # 🔑 문장을 «설정했어요»로 고른 것은 우연이 아니다. `_SUCCESS_LIKE_RE` 는
        #   **동사 화이트리스트**라 «볼륨 올렸어요»는 성공으로 읽지도 못한다
        #   (감사 G-12). 그걸 쓰면 §4가 «재료가 없어서»가 아니라 «어휘가 빠져서»
        #   통과해 버린다 — 여기서 보려는 것은 **재료**다.
        lie = "✓ 볼륨 설정했어요"
        caught = verify_output([
            HumanMessage(content="볼륨 올려줘"),
            AIMessage(content=""),
            ToolMessage(content="✗ 장치를 못 찾았어요", tool_call_id="t1"),
            AIMessage(content=lie),
        ])
        check("재료가 있으면 그물은 잡는다 (도구 오류 + 성공투 응답)",
              caught is not None and "문제가 생겼" in (caught or ""), f"→ {caught!r}")

        missed = verify_output([
            HumanMessage(content="볼륨 올려줘"),
            AIMessage(content=lie),          # fast_hit 턴의 모양 — ToolMessage 가 없다
        ])
        check("🚨 같은 거짓말이 빠른 경로 모양이면 **안 잡힌다** (= G-03)",
              missed is None, f"→ {missed!r}")

        empty = verify_output([HumanMessage(content="볼륨 올려줘"),
                               AIMessage(content=lie)])
        check("빈 응답 복구도 이 경로에선 할 일이 없다 (응답이 비지 않는다)",
              empty is None, f"→ {empty!r}")

        # 🚨 덤으로 드러난 것 — 감사 G-12의 실물 증거. 같은 자리, 같은 재료인데
        #   동사 하나가 빠져 못 잡는다. 고칠 때 **어휘 목록**이 문제라는 근거다.
        check("🔑 같은 그물이 «볼륨 올렸어요»는 성공으로 읽지도 못한다 (감사 G-12 증거)",
              verify_output([
                  HumanMessage(content="볼륨 올려줘"),
                  AIMessage(content=""),
                  ToolMessage(content="✗ 장치를 못 찾았어요", tool_call_id="t2"),
                  AIMessage(content="✓ 볼륨 올렸어요"),
              ]) is None)

    check("`detect_watch_lie` 의 fast_hit 제외가 그대로 있다",
          'state.get("decision") == "fast_hit"' in gr_src)
    check("🔑 그 제외를 지워도 «그물이 생기지» 않는다는 근거가 코드에 적혀 있다",
          "구조적으로 무력" in gr_src)

    # ── §5 실패가 **셀 수 있게** 남는다 (감사 G-02의 쌍둥이) ─────────
    #
    # 🚨 2026-09-18에 G-02를 `command_cache.py` 에서만 메웠다. 같은 경로의
    #   `fast_path.py`·`router.py`·`graph.py` 는 `print` 그대로였다 —
    #   즉 **빠른 경로가 통째로 실패해도 `logs/pluiz.log` 에 한 줄도 안 남았다.**
    print("\n§5 실패가 `logs/pluiz.log` 로 간다 (`print` 가 아니다)")
    check("`fast_path.py` 에 `print(` 가 없다", "print(" not in fp_src)
    check("`router.py` 에 `print(` 가 없다", "print(" not in rt_src)
    check("그래프의 빠른 경로 노드도 `print` 를 안 쓴다",
          "[graph.fast_path]" not in gr_src)

    if not has_core:
        cannot_judge(["캐시가 터지면 ERROR 가 실제로 찍힌다",
                      "라우터가 터지면 ERROR 가 실제로 찍힌다",
                      "로그에는 예외 원문이 남는다 (사람이 되짚어야 한다)"],
                     "core 를 못 불러왔다")
    else:
        cache = FakeCache(Entry([]), boom=RuntimeError("도구 맵이 깨졌다"))
        (_out, rec) = _with_log(
            "FastPath", lambda: resolve_fast_path("볼륨 올려줘", cache))
        check("캐시가 터지면 ERROR 가 실제로 찍힌다",
              any(lv >= logging.ERROR for lv, _ in rec), f"→ {rec}")
        check("로그에는 예외 원문이 남는다 (사람이 되짚어야 한다)",
              any("도구 맵이 깨졌다" in m for _, m in rec), f"→ {rec}")

        def _boom_router(text):
            from core.router import route_deterministic
            return route_deterministic(text)

        tool = FakeTool("youtube_search", boom=RuntimeError("브라우저가 없다"))
        saved = sys.modules.get("tools.web")
        sys.modules["tools.web"] = _fake_module("tools.web", youtube_search=tool)
        try:
            (_o, rec2) = _with_log(
                "Router",
                lambda: resolve_fast_path("유튜브에서 아이유 틀어줘", None, _boom_router))
        finally:
            if saved is None:
                sys.modules.pop("tools.web", None)
            else:
                sys.modules["tools.web"] = saved
        check("라우터가 터지면 ERROR 가 실제로 찍힌다",
              any(lv >= logging.ERROR for lv, _ in rec2), f"→ {rec2}")

    # ── §6 G-18 — 지금 흐름을 **알고** 둔다 ─────────────────────────
    #
    # 캐시 실행이 터지면 라우터가 **같은 발화에 다시 행동한다.** 고치지 않았다 —
    # 이 실패가 실사용에서 나는지 아무도 모르기 때문이다(G-02 때문에 셀 수가
    # 없었다). 그래서 §5로 **세기부터** 하고, 흐름은 여기에 못 박아 둔다.
    # 🔑 «실측 없이 정하면 추측이다»(BL-23). 이 테스트는 판단이 아니라 **현재**다.
    print("\n§6 G-18 — 캐시가 터지면 라우터가 같은 발화에 답한다 (현재 동작)")
    if not has_core:
        cannot_judge(["캐시 실패 뒤 라우터가 이어서 돈다",
                      "그 사실이 로그에 남아 셀 수 있다"],
                     "core 를 못 불러왔다")
    else:
        cache = FakeCache(Entry([]), boom=RuntimeError("터졌다"))
        (out, rec) = _with_log(
            "FastPath",
            lambda: resolve_fast_path("볼륨 올려줘", cache, lambda t: "✓ 라우터가 했어요"))
        check("캐시 실패 뒤 라우터가 이어서 돈다", out == "✓ 라우터가 했어요", f"→ {out!r}")
        check("그 사실이 로그에 남아 셀 수 있다",
              any("라우터로 계속" in m for _, m in rec), f"→ {rec}")

    # ── §7 계약이 **코드 옆에** 적혀 있다 ───────────────────────────
    #
    # 🔑 문서에만 있으면 다음 사람이 «정리»한다. 이 저장소가 반복해 데인 모양이다.
    print("\n§7 계약이 코드 옆에 남아 있다 (문서에만 있지 않다)")
    check("`fast_path.py` 머리에 계약 전문이 있다",
          "G-03" in fp_src and "그물" in fp_src and "정확히 둘" in fp_src)
    check("`router.py` 가 «결과를 지어내지 않는다»를 적어 둔다",
          "G-03" in rt_src and "지어내지 않는다" in rt_src)
    check("그래프의 fast_hit 반환 옆에 근거가 있다",
          "G-03" in gr_src and "fast_hit" in gr_src)
    check("`_verdict` 가 «여기가 마지막 관문»임을 적어 둔다",
          "G-03" in cc_src and "_verdict" in cc_src)

    if skipped:
        print(f"\n결과: {passed}/{total} · 🚨 판정 불가 {skipped}건 — 초록이 아니다")
        print("   빠른 경로 계약을 다 못 쟀다. `conda activate pluiz` 로 다시 돌릴 것")
    else:
        print(f"\n결과: {passed}/{total} 통과")
    return passed == total and skipped == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
