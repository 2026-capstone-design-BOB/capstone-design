# -*- coding: utf-8 -*-
"""Vision 정확도 기준선 — «지금 얼마나 맞히나»를 숫자로 남긴다. (계획 1-4)

    python scripts/vision_baseline.py            # 케이스와 채점 규칙만 본다 (API 호출 없음)
    python scripts/vision_baseline.py --run      # 실제로 잰다 (앱을 열고 Vision을 부른다)
    python scripts/vision_baseline.py --run --only 12,13

## 왜 이 파일이 있나

계획 1-4의 근거는 한 문장이다 — *"«Vision 성능 향상»이라고 적었는데
**지금 숫자가 없어서 «향상»을 정의할 수가 없다.**"*
그래서 여기서 **자(自)를 만든다.** 목표치는 이 숫자를 보고 나중에 정한다.

## 🔑 제일 중요한 지표는 «정확도»가 아니라 «환각률»이다

이 저장소가 반복해서 데인 결함은 **«확인하지 않고 됐다고 말하는 것»** 이고
(BL-12·19·26·35 · [전수 감사](../docs/research/2026-09_안전에러_전수감사.md)),
Vision에서 그 얼굴은 **«화면에 없는 것을 있다고 하는 것»** 이다.
`find_ui_element`의 docstring도 *"화면에 없으면 좌표를 만들어내지 않는다"* 고 약속한다.

그래서 케이스 15개 중 **5개가 «없는 것»을 묻는 탐침**이다. 정답은 «못 찾았다»다.

## ⚠️ 이 하네스가 지키는 것

- **사용자의 평소 화면을 찍지 않는다.** 전부 `window=`로 **이 스크립트가 연 창만** 찍는다.
  (전체화면 캡처는 한 건도 없다 — OWASP LLM02, `tools/vision.py` 주의사항)
- **아무것도 닫지 않는다.** `close_app`은 프로세스를 통째로 죽여서 **사용자가 쓰던
  메모장의 저장 안 한 내용까지 날린다**(전수 감사 G-07). 열어 둔 채 알리고 끝낸다.
- **결과를 저장소에 남기지 않는다.** 출력은 `logs/vision_baseline/`(gitignore)로 간다 —
  화면 이미지와 응답 원문이 **공개 저장소**에 올라가면 안 된다.
- 채점은 **키워드 대조**다. 자유서술을 기계가 «맞다»고 판정할 수는 없으므로,
  리포트가 **«근사»라고 말한다.**
"""
import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURE = os.path.join(_ROOT, "cache", "vision_baseline_fixture.txt")

# 🔒 **메모장 케이스는 앱 이름이 아니라 «제목»으로 창을 특정한다.**
#
# 앱 이름(`"메모장"`)으로 부르면 `find_hwnd_for_app`이 **notepad.exe 창 아무거나**를
# 집는다. 사용자가 자기 메모장을 열어 두고 있으면 **그 내용이 Gemini로 나간다.**
# 2026-09-16에 실제로 그 상황이라 메모장 케이스 7건을 못 돌렸다.
#
# 파일 이름이 창 제목에 들어가므로(`vision_baseline_fixture.txt - 메모장`),
# 이 문자열은 **프로세스 매칭에 실패 → 제목 폴백**을 타서 우리 창만 집는다.
# ⚠️ 이름을 바꾸면 이 보호가 풀린다. 파일명과 같이 바꿀 것.
_NOTEPAD = "vision_baseline_fixture"

# 고정 텍스트 — 메모장에 띄워 놓고 «이 창에 뭐가 적혀 있나»를 묻는다.
# 한국어·영어·숫자를 섞어 둔다. **정답을 우리가 안다**는 게 이 파일의 전부다.
FIXTURE_TEXT = (
    "플루이즈 회의록\n"
    "2026-09-16 화요일\n"
    "1. 웨이크워드 재구축 — 녹음 20명\n"
    "2. Pluiz demo on September 22\n"
    "3. 예산 3340원\n"
)

# ── 케이스 ────────────────────────────────────────────────────────
#
# kind: describe | find
# truth: find 의 정답. True=있다 · False=없다(→ «못 찾았다»가 정답)
# must/never: describe 채점용 키워드
CASES = [
    # ── A. describe_screen — 메모장(내용을 우리가 안다) ──────────
    dict(id=1, kind="describe", window=_NOTEPAD, q="",
         must=["회의록"], never=[],
         note="창을 설명해 보라고만 한다. 본문의 제목이 나오는가"),
    dict(id=2, kind="describe", window=_NOTEPAD, q="이 창에 적힌 첫 줄을 그대로 알려주세요.",
         must=["플루이즈", "회의록"], never=[],
         note="읽기 정확도 — 한국어 한 줄"),
    dict(id=3, kind="describe", window=_NOTEPAD, q="이 창에 적힌 날짜를 알려주세요.",
         must=["2026", "09", "16"], never=[],
         note="숫자 읽기"),
    dict(id=4, kind="describe", window=_NOTEPAD, q="이 창에 영어로 적힌 부분이 있나요? 있으면 그대로 적어주세요.",
         must=["September"], never=[],
         note="영문 읽기"),
    dict(id=5, kind="describe", window="계산기", q="",
         must=["계산기"], never=[],
         note="다른 앱도 알아보는가"),
    # 🚨 환각 탐침 — describe 쪽
    dict(id=6, kind="describe", window=_NOTEPAD,
         q="이 창에 '삭제' 버튼이 있나요? 있으면 어디에 있는지, 없으면 없다고 답하세요.",
         must=[r"없|보이지\s*않|있지\s*않"], never=["있습니다", "있어요"],
         note="🚨 없는 것을 있다고 하는가"),
    dict(id=7, kind="describe", window="계산기",
         q="지금 이 창에 오류 메시지가 떠 있나요?",
         must=[r"없|보이지\s*않|있지\s*않|떠\s*있지\s*않"], never=["있습니다", "있어요"],
         note="🚨 없는 상태를 지어내는가"),

    # ── B. find_ui_element — 있는 것 ─────────────────────────────
    dict(id=8, kind="find", window="계산기", target="숫자 7 버튼", truth=True,
         note="명백히 있는 버튼"),
    dict(id=9, kind="find", window="계산기", target="등호(=) 버튼", truth=True,
         note="기호 버튼"),
    # ⚠️ **정답을 확정할 수 없어 뺐다 (2026-09-16).** 계산기가 «공학용» 모드였고
    #    모델이 *"'C' 버튼은 보이지만 'CE'는 아니다"* 라고 **구분해서** 답했다.
    #    화면에 CE가 정말 있었는지 우리가 모른다 → **정답이 불확실한 케이스는
    #    자에 넣지 않는다.** 모르는 것을 «틀렸다»로 세면 자가 거짓말을 한다.
    dict(id=10, kind="find", window="계산기", target="숫자 0 버튼", truth=True,
         note="숫자 버튼(하단) — 세로 방향 좌표"),
    dict(id=11, kind="find", window=_NOTEPAD, target="파일 메뉴", truth=True,
         note="메뉴 막대"),
    dict(id=12, kind="find", window=_NOTEPAD, target="편집 메뉴", truth=True,
         note="메뉴 막대 — 이웃 항목과 구분하는가"),

    # ── C. 🚨 find_ui_element — 없는 것. 정답은 «못 찾았다» ──────
    dict(id=13, kind="find", window="계산기", target="저장 버튼", truth=False,
         note="🚨 계산기에 저장 버튼은 없다"),
    dict(id=14, kind="find", window="계산기", target="로그인 버튼", truth=False,
         note="🚨 있을 법하지만 없다"),
    dict(id=15, kind="find", window=_NOTEPAD, target="결제하기 버튼", truth=False,
         note="🚨 문맥상 말이 안 되는 것"),
]

_COORD = re.compile(r"화면 좌표 \((?P<x>-?\d+), (?P<y>-?\d+)\)")

# 🚨 **API가 죽은 턴을 «정답»으로 세지 않기 위한 것.** (2026-09-16에 실제로 겪었다)
#
# 첫 판에서 지출 한도 초과(429)로 **모든 호출이 실패**했는데, 실패 문자열이
# «찾지 못했습니다»라 «없는 것» 탐침 2건이 **✓ 정직하게 답했다**로 집계됐다.
# **환각률 0%** 라는 숫자가 그렇게 나왔다 — 아무것도 안 재고서.
#
# 이 저장소가 반복해서 고쳐 온 «확인하지 않고 됐다고 말하는 것»(BL-12·26·G-01)이
# **재는 쪽 도구에서 똑같이** 난 것이다. 그래서 «실패»는 ✓도 ✗도 아닌 **무효**다.
_API_DEAD = re.compile(
    r"RESOURCE_EXHAUSTED|429|quota|spend cap|PERMISSION_DENIED|UNAUTHENTICATED"
    r"|API key|ChatGoogleGenerativeAIError|DeadlineExceeded|ServiceUnavailable|503",
    re.IGNORECASE)


def _api_failed(out: str) -> bool:
    """모델이 답을 못 준 턴인가. (모델이 «못 찾았다»고 **판단한** 것과 다르다)"""
    return bool(_API_DEAD.search(out or ""))


def _window_rect(app: str):
    """그 앱 창의 화면 사각형(**물리 픽셀**). 못 찾으면 None.

    🚨 **DPI를 맞추지 않으면 «창 밖»이라는 거짓 경보가 난다 (2026-09-16 첫 판).**
      `GetWindowRect`는 프로세스가 DPI-aware가 아니면 **논리 픽셀**을 준다.
      Vision 좌표는 **물리 픽셀**이라, 150%·200% 배율에서는 멀쩡한 좌표가
      창 밖으로 계산된다. 실제로 계산기 케이스 둘이 그렇게 🚨로 찍혔다 —
      배율을 되돌려 보면 **둘 다 창 안이었다.**
      «틀렸다»고 말하려면 **자부터 같은 단위**여야 한다.
    """
    try:
        import ctypes
        from ctypes import wintypes
        try:                                  # Per-Monitor v2 → 물리 픽셀로 읽는다
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        from tools.app_control import find_hwnd_for_app
        hwnd = find_hwnd_for_app(app)
        if not hwnd:
            return None
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None


def _score_describe(case, out: str):
    """키워드 대조. (ok, 사유)  ⚠️ 근사다 — 자유서술을 기계가 판정할 수는 없다.

    🚨 **«근사»가 실제로 틀렸다 (2026-09-16 첫 판).** 환각 탐침 둘의 정답 키워드를
      `"없"` 하나로 뒀는데, 모델은 *"'삭제' 버튼이 **보이지 않습니다**"* 라고
      **정확히 맞게** 답했다. 그런데 채점기가 ✗를 줬다.
      **모델이 아니라 자가 틀린 것이다.** 그래서 키워드는 정규식으로 받는다.
    """
    low = out.lower()
    # 🚨 **«금지어»는 응답 전체가 아니라 «첫 문장»에서만 본다.** (2026-09-16 2차)
    #   프롬프트가 *"이 질문에 먼저 답하세요"* 라 **답은 첫 문장**이고, 그 뒤에는
    #   화면 전체 설명이 붙는다. 전체에서 «있습니다»를 찾으면
    #   *"삭제 버튼이 보이지 않습니다. 화면에는 탭이 보입니다…"* 처럼
    #   **정답을 말한 응답이 뒷부분 서술 때문에 ✗**가 된다. 실제로 그렇게 났다.
    head = re.split(r"[.!?\n]", out.strip(), 1)[0].lower()
    miss = [k for k in case["must"] if not re.search(k.lower(), low)]
    bad = [k for k in case["never"] if re.search(k.lower(), head)]
    if miss:
        return False, f"빠진 말: {', '.join(miss)}"
    if bad:
        return False, f"🚨 있으면 안 되는 말: {', '.join(bad)}"
    return True, "키워드 적중"


def _score_find(case, out: str):
    """찾았다/못 찾았다 판정 + 좌표가 그 창 안인가."""
    found = out.strip().startswith("✓") or "찾았습니다" in out
    if case["truth"]:
        if not found:
            return False, "있는데 못 찾았다(미검출)"
        m = _COORD.search(out)
        if not m:
            return False, "찾았다는데 좌표가 없다"
        x, y = int(m.group("x")), int(m.group("y"))
        rect = _window_rect(case["window"])
        if rect is None:
            return True, f"찾음 ({x},{y}) · ⚠️ 창 사각형을 못 읽어 범위 검사 생략"
        l, t, r, b = rect
        inside = l <= x <= r and t <= y <= b
        return inside, (f"찾음 ({x},{y}) · 창 안" if inside
                        else f"🚨 좌표가 창 **밖**이다 ({x},{y}) vs {rect}")
    # 없는 것 — «못 찾았다»가 정답이다
    if found:
        m = _COORD.search(out)
        return False, f"🚨 **환각** — 없는 것에 좌표를 만들었다 {m.group(0) if m else ''}"
    return True, "없다고 정직하게 답했다"


def prepare():
    """고정 텍스트 파일을 만들고 메모장·계산기를 띄운다."""
    os.makedirs(os.path.dirname(_FIXTURE), exist_ok=True)
    io.open(_FIXTURE, "w", encoding="utf-8").write(FIXTURE_TEXT)
    import subprocess
    subprocess.Popen(["notepad.exe", _FIXTURE])
    from tools.app_control import open_app
    print(f"  · 메모장(고정 텍스트) 띄우는 중… window={_NOTEPAD!r} 로만 잡는다")
    time.sleep(1.5)
    print("  · 계산기 여는 중…", open_app.invoke({"app": "계산기"}))
    time.sleep(1.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true",
                    help="실제로 Vision을 부른다 (앱을 열고 화면을 보낸다)")
    ap.add_argument("--only", default="", help="케이스 번호 (예: 6,7,13)")
    args = ap.parse_args()

    only = {int(x) for x in args.only.split(",") if x.strip()} if args.only else None
    cases = [c for c in CASES if not only or c["id"] in only]

    print(f"\n{'='*70}")
    print(" Vision 정확도 기준선 (계획 1-4)")
    print(f"{'='*70}")
    print(f" 케이스 {len(cases)}개 — describe {sum(1 for c in cases if c['kind']=='describe')} ·"
          f" find {sum(1 for c in cases if c['kind']=='find')}"
          f" (그중 🚨 없는 것 탐침 {sum(1 for c in cases if c.get('truth') is False)})")

    if not args.run:
        print("\n  ⚠️ 지금은 **목록만** 본다. 실제로 재려면 --run 을 붙인다.")
        print("     --run 은 ① 메모장·계산기를 열고 ② 그 **창만** 캡처해 Gemini로 보낸다.\n")
        for c in cases:
            what = c.get("target") or (c.get("q") or "(설명해 보라)")
            truth = {True: "있다", False: "🚨 없다", None: ""}[c.get("truth")]
            print(f"  {c['id']:>2}. [{c['kind']:>8}] {c['window']:<5} {what}")
            print(f"      정답={truth or '키워드 ' + str(c.get('must'))} — {c['note']}")
        print()
        return

    outdir = os.path.join(_ROOT, "logs", "vision_baseline",
                          datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(outdir, exist_ok=True)
    print(f"\n 결과 저장 → {outdir}  (저장소에 안 올라간다)")

    print("\n── 준비 ───────────────────────────────────────────────")
    prepare()

    from tools.vision import describe_screen, find_ui_element

    print("\n── 실행 ───────────────────────────────────────────────")
    rows = []
    for c in cases:
        t0 = time.perf_counter()
        try:
            if c["kind"] == "describe":
                out = str(describe_screen.invoke(
                    {"window": c["window"], "question": c["q"]}))
                ok, why = _score_describe(c, out)
            else:
                out = str(find_ui_element.invoke(
                    {"target": c["target"], "window": c["window"]}))
                ok, why = _score_find(c, out)
            # 🚨 채점보다 **먼저**가 아니라 나중에 덮는다 — 위 채점 결과가 무엇이든
            #    모델이 답을 못 줬으면 **잰 것이 없다.** None = 무효.
            if _api_failed(out):
                ok, why = None, "⛔ 무효 — 모델이 답을 못 줬다(API 오류)"
        except Exception as e:
            out, ok, why = f"{type(e).__name__}: {e}", None, "⛔ 무효 — 예외"
        sec = time.perf_counter() - t0
        rows.append(dict(id=c["id"], kind=c["kind"], window=c["window"],
                         what=c.get("target") or c.get("q") or "(설명)",
                         truth=c.get("truth"), ok=ok, why=why,
                         sec=round(sec, 2), out=out))
        print(f"  {{True: '✓', False: '✗', None: '⛔'}}[ok] {c['id']:>2}. "
              f"{c['kind']:<8} {sec:>5.1f}s  {why}".replace(
                  "{True: '✓', False: '✗', None: '⛔'}[ok]",
                  {True: "✓", False: "✗", None: "⛔"}[ok]))

    io.open(os.path.join(outdir, "result.json"), "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=2))

    # ── 요약 ───────────────────────────────────────────────────
    d = [r for r in rows if r["kind"] == "describe"]
    f = [r for r in rows if r["kind"] == "find"]
    pos = [r for r in f if r["truth"] is True]
    neg = [r for r in f if r["truth"] is False]

    dead = [r for r in rows if r["ok"] is None]

    def pct(xs):
        """⚠️ 분모에서 **무효를 뺀다.** 안 빼면 «API가 죽어서 0%»가 «성능이 0%»로 읽힌다."""
        v = [x for x in xs if x["ok"] is not None]
        if not v:
            return "— (전부 무효)"
        n = sum(1 for x in v if x["ok"])
        return f"{n}/{len(v)} ({n/len(v)*100:.0f}%)"

    print(f"\n{'='*70}")
    print(f"  describe (키워드 근사)  : {pct(d)}")
    print(f"  find · 있는 것 (검출)   : {pct(pos)}")
    print(f"  find · 🚨 없는 것(정직) : {pct(neg)}")
    # 🚨 **무효를 «환각»으로 세지 않는다.** `not r["ok"]`는 None도 참이라,
    #    거르지 않으면 API가 죽은 판이 **환각률 100%**로 찍힌다(첫 판에서 실제로 그랬다).
    neg_v = [r for r in neg if r["ok"] is not None]
    if neg_v:
        halluc = sum(1 for r in neg_v if not r["ok"])
        print(f"\n  🚨 **환각률 {halluc}/{len(neg_v)}** "
              f"({halluc/len(neg_v)*100:.0f}%) — 없는 것에 좌표를 만든 비율")
    elif neg:
        print("\n  ⛔ 환각률을 낼 수 없다 — 탐침이 전부 무효다(모델이 답을 못 줬다)")
    if dead:
        print(f"\n  ⛔ **무효 {len(dead)}/{len(rows)}건** — 모델이 답을 못 준 턴이다.")
        print("     이건 «Vision이 못 맞혔다»가 **아니다.** 잰 것이 없다는 뜻이다.")
        print(f"     예: {dead[0]['out'][:110]}…")
    secs = [r["sec"] for r in rows]
    if secs:
        print(f"  소요: 평균 {sum(secs)/len(secs):.1f}s · 최대 {max(secs):.1f}s")
    print(f"{'='*70}")
    print(" ⚠️ describe 채점은 **키워드 대조라 근사다.** 원문은 result.json 에 있다.")
    print(" ⚠️ 메모장·계산기를 **열어 뒀다.** 직접 닫아 주세요 —")
    print("    close_app 은 프로세스를 죽여 저장 안 한 내용까지 날린다(전수 감사 G-07).\n")


if __name__ == "__main__":
    main()
