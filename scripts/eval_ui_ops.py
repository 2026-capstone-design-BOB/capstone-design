# -*- coding: utf-8 -*-
"""화면 조작 성공률 — «지금 짚는 자리가 맞나» (10월 항목 2-9a)

    python scripts/eval_ui_ops.py                 # 케이스와 채점 규칙만 본다 (호출 없음)
    python scripts/eval_ui_ops.py --run           # 실제로 잰다
    python scripts/eval_ui_ops.py --run --app 설정
    python scripts/eval_ui_ops.py --run --json out.json

## 🚨 **아무것도 클릭하지 않는다.** 이게 이 파일의 제일 중요한 성질이다

`click_ui_element` 는 **진짜로 누른다.** 20케이스를 그대로 먹이면 측정이 아니라
사고다(설정이 바뀌고 창이 닫힌다). 그래서 **판정 함수 `locate_ui_element` 만** 부르고
누르는 단계는 **절대 안 간다** — `offline_coverage.py` 가 `execute_sync` 를 안 부르는
것과 같은 규칙이다.

⚠️ 대신 «판정 경로가 실물과 같은가»가 위험해진다. 그래서 `find_ui_element`·
`click_ui_element` 가 **둘 다 쓰는 바로 그 함수**를 부른다. 여기서 다시 구현하지 않는다.

## 🔑 채점을 사람이 아니라 **Windows 접근성 API** 가 한다

이 측정의 어려운 점은 *«모델이 찍은 좌표가 맞는지 기계가 어떻게 아나»* 였다.
클릭해 보면 알지만 **클릭은 되돌릴 수 없다.**

접근성 API(UIA)가 그 자리를 메운다 — **창 안의 컨트롤 이름과 실제 사각형을 그대로
알려준다.** 그래서 이렇게 채점한다.

    ① UIA 로 «이 창에 실제로 있는 컨트롤»을 뽑는다  → 이게 정답지다
    ② 그 이름을 우리 Vision 경로에 물어본다          → 이게 응시자다
    ③ 돌아온 좌표가 정답 사각형 안에 있나            → 자동 채점

🚨 **정답지를 응시자가 못 보게 한다.** Vision 에는 **이름만** 준다(좌표·사각형 없이).
   ②에 정답을 조금이라도 흘리면 그건 재는 게 아니라 베끼는 것이다.

## 🚨 이 숫자를 무엇에 쓰나 — **«개선 전»이다**

10월 W5 에 [화면 짚는 방식을 UIA 로 바꾸는 작업](../docs/research/2026-09_외부도구_후보.md)이
잡혀 있다. **그걸 시작한 뒤에 재면 «개선 전» 숫자를 영영 못 잡는다**([M7 1단계](
../docs/design/M7_웨이크워드_재구축.md)가 같은 이유로 평가 하네스를 먼저 만들었다).

그래서 같은 케이스를 **두 경로에 다 물어본다.**

| 경로 | 무엇 |
|---|---|
| `vision` | 지금 방식 — 화면을 찍어 모델에게 묻는다 |
| `uia` | 바꿀 방식 — 컨트롤 트리를 직접 읽는다 |

🔑 **`uia` 열이 «정답지»이면서 동시에 «상대»다.** 좀 이상해 보이지만 맞다 —
UIA 가 못 찾는 케이스는 애초에 정답지에 안 들어오므로, uia 열은 **거의 100%가 된다.**
그러니 **uia 의 성공률을 성과로 읽으면 안 된다.** 볼 것은 **vision 열과 지연·토큰**이다.
(그림·아이콘처럼 UIA 가 못 보는 것은 이 자로 잴 수 없다 → §한계)

## ⚠️ 이 하네스가 지키는 것 — `vision_baseline.py` 와 같은 규율

- **사용자의 평소 화면을 안 찍는다.** 전부 `window=` 로 **우리가 연 창만** 본다.
- **아무것도 닫지 않는다.** 열어 둔 채 알리고 끝낸다.
- **결과를 저장소에 안 남긴다.** 화면에서 읽은 컨트롤 이름이 들어가므로
  `logs/ui_ops/`(gitignore)로 간다.
"""
import argparse
import io
import json
import os
import statistics as st
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_ROOT, "logs", "ui_ops")

#: 정답지로 쓸 창. `ensure_window_ready` 가 아는 이름이어야 한다.
DEFAULT_APP = "설정"

#: 정답지에 넣을 컨트롤 종류. 🔑 **누를 수 있는 것만** — 우리가 재려는 것이
#  «조작할 자리를 짚나»이기 때문이다. 텍스트 라벨은 짚어도 쓸모가 없다.
CLICKABLE = {"ButtonControl", "CheckBoxControl", "RadioButtonControl",
             "ListItemControl", "TabItemControl", "HyperlinkControl",
             "MenuItemControl", "ComboBoxControl"}

#: 한 창에서 최대 몇 개를 뽑나. 케이스 하나가 Vision 호출 한 번(약 4초·화면 한 장)이다.
DEFAULT_N = 12

#: 이름이 이보다 짧거나 길면 뺀다. 너무 짧으면 화면에 여러 개 있고,
#  너무 길면 사람이 그렇게 안 부른다.
NAME_MIN, NAME_MAX = 2, 20


# ── 정답지 ───────────────────────────────────────────────────────────

def ground_truth(app: str, limit: int):
    """UIA 로 «그 창에 실제로 있는, 누를 수 있는 컨트롤»을 뽑는다.

    반환: [{"name", "type", "rect": (l, t, r, b)}]
    """
    import uiautomation as auto
    auto.SetGlobalSearchTimeout(2)

    win = None
    for w in auto.GetRootControl().GetChildren():
        if w.ControlTypeName == "WindowControl" and app in (w.Name or ""):
            win = w
            break
    if win is None:
        return [], f"'{app}' 창을 못 찾았어요. 먼저 열어 주세요."

    # 🚨 **창 안에 실제로 보이는 것만** 정답지에 넣는다 (2026-09-24 첫 실측에서 배웠다).
    #   UIA 는 **스크롤로 밀려 화면 밖에 있는 컨트롤도** 목록에 준다. 그걸 정답지에
    #   넣으면 Vision 이 *"화면에 보이지 않습니다"* 라고 **옳게** 답한 것을 «실패»로
    #   센다 — 자가 틀린 것이지 응시자가 틀린 게 아니다.
    wr = win.BoundingRectangle
    vis = (wr.left, wr.top, wr.right, wr.bottom)

    seen, out = set(), []
    for c in win.GetChildren():
        _walk(c, seen, out, depth=0, vis=vis)
    # 이름이 겹치면 «어느 것»인지 정답이 하나가 아니다 → 통째로 뺀다
    from collections import Counter
    dup = {n for n, k in Counter(x["name"] for x in out).items() if k > 1}
    out = [x for x in out if x["name"] not in dup]
    return out[:limit], ""


def _inside(r, vis) -> bool:
    """컨트롤이 창의 보이는 영역 안에 **온전히** 들어 있나."""
    return (r.right > r.left and r.bottom > r.top
            and r.left >= vis[0] and r.top >= vis[1]
            and r.right <= vis[2] and r.bottom <= vis[3])


def _walk(c, seen, out, depth, vis):
    if depth > 6 or len(out) > 400:
        return
    try:
        name = (c.Name or "").strip()
        tname = c.ControlTypeName
        if (tname in CLICKABLE and NAME_MIN <= len(name) <= NAME_MAX
                and name not in seen):
            r = c.BoundingRectangle
            if _inside(r, vis):
                seen.add(name)
                out.append({"name": name, "type": tname,
                            "rect": (r.left, r.top, r.right, r.bottom)})
        for ch in c.GetChildren():
            _walk(ch, seen, out, depth + 1, vis)
    except Exception:
        return          # 사라진 컨트롤 — 훑는 중에 화면이 바뀔 수 있다


# ── 응시자 ───────────────────────────────────────────────────────────

def ask_vision(name: str, app: str) -> dict:
    """지금 방식. 🚨 **이름만** 준다 — 정답 사각형을 흘리지 않는다."""
    from tools.vision import locate_ui_element
    t0 = time.monotonic()
    try:
        res = locate_ui_element(name, window=app)
    except Exception as e:                                    # noqa: BLE001
        return {"found": False, "sec": time.monotonic() - t0,
                "err": f"{type(e).__name__}: {e}"}
    took = time.monotonic() - t0
    if not res.get("found"):
        return {"found": False, "sec": took, "reason": res.get("reason", "")}
    cx, cy = res.get("center", (None, None))
    return {"found": True, "sec": took, "point": (cx, cy)}


def ask_uia(name: str, app: str) -> dict:
    """바꿀 방식. 트리에서 이름으로 찾는다 — 화면을 안 찍고 토큰을 안 쓴다."""
    import uiautomation as auto
    t0 = time.monotonic()
    try:
        win = None
        for w in auto.GetRootControl().GetChildren():
            if w.ControlTypeName == "WindowControl" and app in (w.Name or ""):
                win = w
                break
        if win is None:
            return {"found": False, "sec": time.monotonic() - t0}
        hit = []
        _find_named(win, name, hit, 0)
        took = time.monotonic() - t0
        if not hit:
            return {"found": False, "sec": took}
        r = hit[0]
        return {"found": True, "sec": took,
                "point": ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)}
    except Exception as e:                                    # noqa: BLE001
        return {"found": False, "sec": time.monotonic() - t0,
                "err": f"{type(e).__name__}: {e}"}


def _find_named(c, name, hit, depth):
    if hit or depth > 6:
        return
    try:
        if (c.Name or "").strip() == name:
            r = c.BoundingRectangle
            # 🚨 **크기가 0인 노드는 건너뛴다.** 트리에는 같은 이름의 **숨은 노드**가
            #   있을 수 있고, 첫 번째를 그냥 쓰면 (0,0) 을 답으로 내놓는다
            #   (2026-09-24 첫 실측에서 '시스템' 이 그랬다).
            if r.right > r.left and r.bottom > r.top:
                hit.append((r.left, r.top, r.right, r.bottom))
                return
        for ch in c.GetChildren():
            _find_named(ch, name, hit, depth + 1)
    except Exception:
        return


# ── 채점 ─────────────────────────────────────────────────────────────

def score(point, rect) -> str:
    """정답 사각형 안이면 hit, 밖이면 miss. 좌표가 없으면 none.

    🚨 **«가까우면 맞다»로 봐주지 않는다.** 클릭은 사각형 안이어야 눌린다 —
      «10픽셀 옆»은 다른 버튼이거나 아무것도 아니다. 봐주면 이 자는
      «실제로 눌리는가»가 아니라 «비슷한가»를 재게 된다.
    """
    if not point or point[0] is None:
        return "none"
    l, t, r, b = rect
    return "hit" if (l <= point[0] <= r and t <= point[1] <= b) else "miss"


def summarize(rows, engine):
    er = [r for r in rows if r["engine"] == engine]
    if not er:
        return {}
    n = len(er)
    hit = sum(1 for r in er if r["verdict"] == "hit")
    miss = sum(1 for r in er if r["verdict"] == "miss")
    none = sum(1 for r in er if r["verdict"] == "none")
    secs = sorted(r["sec"] for r in er)
    return {
        "n": n, "hit": hit, "miss": miss, "none": none,
        "성공률": round(100.0 * hit / n, 1),
        # 🚨 «못 찾았다»와 «틀린 자리를 찍었다»를 **따로** 센다.
        #   앞은 사용자가 «못 찾았대» 하고 끝나지만, 뒤는 **엉뚱한 데를 누른다.**
        "오답률": round(100.0 * miss / n, 1),
        "지연중앙": round(st.median(secs), 2),
        "지연p90": round(secs[min(n - 1, int(n * 0.9))], 2),
    }


def report(rows, cases, app):
    print(f"\n{'=' * 74}")
    print(f"화면 조작 성공률 (2-9a) — 창 '{app}' · 케이스 {len(cases)}개 · 클릭 0회")
    print("=" * 74)
    print(f"\n  {'경로':<10}{'n':>4}{'맞음':>6}{'틀림':>6}{'못찾음':>7}"
          f"{'성공률':>8}{'오답률':>8}{'지연중앙':>10}{'p90':>8}")
    for e in ("vision", "uia"):
        m = summarize(rows, e)
        if not m:
            continue
        print(f"  {e:<10}{m['n']:>4}{m['hit']:>6}{m['miss']:>6}{m['none']:>7}"
              f"{m['성공률']:>7}%{m['오답률']:>7}%{m['지연중앙']:>9.2f}s{m['지연p90']:>7.2f}s")

    print("\n🚨 이 표를 읽는 법")
    print("  · **uia 열의 성공률을 성과로 읽지 말 것** — 정답지를 UIA 가 만들었으므로")
    print("    UIA 가 못 찾는 것은 애초에 케이스에 없다. 거의 100%가 나오는 게 당연하다.")
    print("  · 볼 것은 **vision 열**과 **두 경로의 지연 차이**다.")
    print("  · 🚨 «틀림»은 «못찾음»보다 나쁘다 — 못 찾으면 사용자가 알지만,")
    print("    틀린 자리는 **정확하게 엉뚱한 곳을 누른다.**")


def show_rules(app, n):
    print(f"""
화면 조작 성공률 측정 (2-9a) — **아직 아무것도 안 했다** (`--run` 을 붙이세요)

  정답지   Windows 접근성 API 가 '{app}' 창에서 **누를 수 있는 컨트롤**을 뽑는다
           (버튼·체크박스·탭·목록항목 등 · 이름이 {NAME_MIN}~{NAME_MAX}자 · 이름이 겹치면 제외)
  응시자   ① vision — 지금 방식(화면을 찍어 모델에게 묻는다)
           ② uia    — 바꿀 방식(트리를 직접 읽는다)
  채점     돌아온 좌표가 **정답 사각형 안**이면 맞음. 가까우면 봐주지 않는다.
  케이스   최대 {n}개 (하나가 Vision 호출 한 번 ≈ 4초 · 화면 한 장)

  🚨 클릭은 **한 번도** 하지 않는다. locate 까지만 부른다.
  🚨 Vision 에는 **이름만** 준다 — 정답 좌표를 흘리면 재는 게 아니라 베끼는 것이다.
  ⚠️  '{app}' 창이 **열려 있어야** 한다. 이 스크립트는 창을 닫지 않는다.
""")


def main():
    ap = argparse.ArgumentParser(description="화면 조작 성공률을 잰다 (2-9a)")
    ap.add_argument("--run", action="store_true", help="실제로 잰다 (없으면 규칙만 본다)")
    ap.add_argument("--app", default=DEFAULT_APP, help=f"볼 창 (기본 {DEFAULT_APP})")
    ap.add_argument("--limit", type=int, default=DEFAULT_N, help="케이스 수")
    ap.add_argument("--engines", default="vision,uia", help="쉼표로")
    ap.add_argument("--json", default="", help="결과 JSON 경로")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not args.run:
        show_rules(args.app, args.limit)
        return 0

    try:
        import uiautomation  # noqa: F401
    except ImportError:
        print("✗ uiautomation 이 없습니다.  pip install uiautomation")
        return 2

    print(f"▶ '{args.app}' 창에서 정답지를 뽑는 중 …")
    cases, err = ground_truth(args.app, args.limit)
    if err:
        print(f"✗ {err}")
        return 1
    if not cases:
        print(f"✗ '{args.app}' 창에서 누를 수 있는 컨트롤을 못 찾았어요.")
        return 1
    print(f"  정답지 {len(cases)}개: " + ", ".join(c["name"] for c in cases[:6])
          + (" …" if len(cases) > 6 else ""))

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    rows = []
    for i, c in enumerate(cases, 1):
        for e in engines:
            res = (ask_vision if e == "vision" else ask_uia)(c["name"], args.app)
            v = score(res.get("point"), c["rect"]) if res.get("found") else "none"
            rows.append({"case": c["name"], "type": c["type"], "rect": c["rect"],
                         "engine": e, "verdict": v, "sec": round(res["sec"], 3),
                         "point": res.get("point"), "reason": res.get("reason", ""),
                         "err": res.get("err", "")})
            if args.verbose:
                mark = {"hit": "✅", "miss": "🚨", "none": "⬜"}[v]
                print(f"  {mark} [{e:6}] {c['name']!r} → {res.get('point')} "
                      f"({res['sec']:.2f}s)")
        if not args.verbose:
            print(f"  … {i}/{len(cases)}")

    report(rows, cases, args.app)

    os.makedirs(OUT_DIR, exist_ok=True)
    path = args.json or os.path.join(
        OUT_DIR, f"ui_ops_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump({"app": args.app, "engines": engines,
                   "요약": {e: summarize(rows, e) for e in engines},
                   "케이스": rows}, f, ensure_ascii=False, indent=1)
    print(f"\n💾 {path}")
    print("   (logs/ 는 gitignore 다 — 화면에서 읽은 컨트롤 이름이 들어 있다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
