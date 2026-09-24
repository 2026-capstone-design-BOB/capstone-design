# -*- coding: utf-8 -*-
"""화면 짚기 — **접근성 API 경로** (10월 항목 A · 2026-09-24)

`tools/vision.locate_ui_element` 가 **먼저 여기에 물어보고**, 못 찾으면 지금까지 쓰던
Vision 경로로 내려간다. STT 의 `google → whisper`, TTS 의 `edge → SAPI` 와 **같은 모양**이다.

## 왜 바꾸나 — 실측이 있다

[화면 조작 성공률](../docs/research/2026-09_화면조작_성공률.md) (2026-09-24 · 설정 창 12개):

| | 지금(Vision) | 여기(UIA) |
|---|---:|---:|
| 맞는 자리를 짚나 | 58.3% | 100% |
| 🚨 **틀린 자리를 짚나** | **33.3%** | **0%** |
| 걸리는 시간 | 3.18s | **0.09s** |
| 화면이 외부로 | 매번 나간다 | **안 나간다** |

실사용 로그에서 `point_at_element` 중앙값이 **8.70초**다 — *"그거 어딨지"* 는 제품
정체성(「길잡이」)의 중심 기능이고 **가장 느린 자리**였다.

## 🚨 **대체가 아니라 «먼저 시도»다**

UIA 는 **그림·아이콘·레이아웃을 못 본다.** 컨트롤 트리에 이름이 없는 것은 여기서
영영 안 나온다 — 그건 Vision 만 할 수 있다([W-1 §5](../docs/research/2026-09_외부도구_후보.md)).
그래서 **못 찾으면 조용히 내려간다.** 여기서 «없다»고 단정하지 않는다.

## 🚨 이름 맞추기에서 **봐주지 않는다**

여기가 이 파일에서 제일 위험한 자리다. 사용자는 *"블루투스"* 라고 하는데 컨트롤
이름은 *"Bluetooth"* 거나 *"블루투스 켜기/끄기"* 일 수 있다. 느슨하게 맞추면 찾는
비율은 오르지만 **엉뚱한 컨트롤을 «정확한 좌표»로 짚는다** — Vision 의 33% 오답을
고치러 와서 같은 병을 새로 만드는 꼴이다.

그래서 **단계를 내려가며 맞추고, 같은 단계에서 둘 이상이 걸리면 포기한다.**

    ① 완전히 같다        ② 앞부분이 같다        ③ 안에 들어 있다
    └ 각 단계에서 후보가 **정확히 하나**일 때만 쓴다. 둘이면 다음 단계로도 안 가고 포기.

포기하면 Vision 이 받는다 — **모르는 것을 찍는 것보다 느린 쪽이 낫다.**
"""
import logging
import os
import time

log = logging.getLogger("pluiz.uia")

#: 트리를 훑다 멈추지 않도록 거는 상한(초).
#
# 🚨 **폴백은 «있다»가 아니라 «갈 수 있다»여야 한다** — BL-69 가 정확히 그 자리였다.
#   `recognize_google` 에 타임아웃이 없어 «망이 느릴 때» Whisper 로 가는 길이
#   안 열렸다. 여기도 같다: UIA 가 안 돌아오면 **Vision 으로 못 간다.**
#   0.09초가 실측이므로 1.5초면 충분히 넉넉하다.
UIA_TIMEOUT = 1.5

#: 트리를 얼마나 깊이 들어가나. 실측에서 설정 창은 6이면 다 닿았다.
MAX_DEPTH = 6

#: 누를 수 있는 것만 본다. 텍스트 라벨을 짚어 주면 눌러도 아무 일이 안 생긴다.
CLICKABLE = {"ButtonControl", "CheckBoxControl", "RadioButtonControl",
             "ListItemControl", "TabItemControl", "HyperlinkControl",
             "MenuItemControl", "ComboBoxControl", "EditControl",
             "SliderControl", "TreeItemControl"}

#: 끄는 스위치. `.env` 에 `PLUIZ_UIA=0` 이면 예전 경로만 쓴다.
#
# 🔑 **«개선 전»을 다시 잴 수 있어야 한다.** 이걸 안 두면 교체한 뒤에는
#   `eval_ui_ops.py` 가 옛 경로를 못 부르고, 전/후 비교가 영영 불가능해진다.
def uia_enabled() -> bool:
    return os.environ.get("PLUIZ_UIA", "1").strip().lower() not in ("0", "false", "no")


def _norm(s) -> str:
    """이름 비교용 정규화 — 공백을 지우고 소문자로."""
    return "".join(str(s or "").split()).lower()


def _collect(node, depth, out, deadline):
    """트리를 훑어 (정규화이름, 원본이름, 사각형)을 모은다."""
    if depth > MAX_DEPTH or time.monotonic() > deadline or len(out) > 600:
        return
    try:
        for c in node.GetChildren():
            if time.monotonic() > deadline:
                return
            try:
                name = (c.Name or "").strip()
                if name and c.ControlTypeName in CLICKABLE:
                    r = c.BoundingRectangle
                    # 🚨 크기가 0인 노드는 버린다 — 트리에는 같은 이름의 **숨은
                    #   노드**가 있고, 그걸 쓰면 (0,0) 을 답으로 내놓는다
                    #   (2026-09-24 측정에서 실제로 그랬다).
                    if r.right > r.left and r.bottom > r.top:
                        out.append((_norm(name), name,
                                    (r.left, r.top, r.right, r.bottom)))
            except Exception:
                pass
            _collect(c, depth + 1, out, deadline)
    except Exception:
        return


def _pick(cands, want):
    """단계를 내려가며 고른다. **같은 단계에서 둘 이상이면 포기한다.**

    반환: (원본이름, 사각형) 또는 None.
    """
    for stage, test in (
        ("완전일치", lambda n: n == want),
        ("앞부분",   lambda n: n.startswith(want)),
        ("포함",     lambda n: want in n),
    ):
        hit = [c for c in cands if test(c[0])]
        if len(hit) == 1:
            return hit[0][1], hit[0][2], stage
        if len(hit) > 1:
            # 🚨 **다음 단계로도 안 간다.** 완전일치가 둘이면 «앞부분»은 더 느슨해서
            #   더 많이 걸린다 — 느슨한 쪽으로 내려가 하나를 고르면 그게 «지어내기»다.
            log.info("[UIA] %r — %s 후보가 %d개라 포기한다 (Vision 으로)",
                     want, stage, len(hit))
            return None
    return None


def locate(target: str, window: str = "") -> dict | None:
    """접근성 트리에서 요소를 찾는다.

    찾으면 `tools.vision.locate_ui_element` 와 **같은 모양**으로 돌려준다 —
    `{"found": True, "center", "rect", "size", "label", "window_rect", "via": "uia"}`.
    못 찾거나 쓸 수 없으면 **`None`** 을 돌려준다(= «Vision 이 받아라»).

    🔑 `{"found": False}` 가 아니라 `None` 인 것이 중요하다. 여기서 «없다»고
      단정하면 부르는 쪽이 Vision 을 안 부른다 — UIA 는 그림·아이콘을 못 보므로
      «내가 못 찾았다»와 «화면에 없다»는 **다른 말**이다.
    """
    if not uia_enabled() or not (target or "").strip():
        return None

    t0 = time.monotonic()
    deadline = t0 + UIA_TIMEOUT
    try:
        import uiautomation as auto
    except ImportError:
        log.info("[UIA] uiautomation 이 없다 — Vision 으로")
        return None

    try:
        auto.SetGlobalSearchTimeout(1)
        root = auto.GetRootControl()

        # 창을 좁힌다. 창 이름이 없으면 **전체 데스크톱을 훑지 않는다** —
        # 화면에 있는 모든 앱의 컨트롤이 섞이면 이름이 겹쳐 포기만 하게 되고,
        # 무엇보다 사용자가 안 시킨 창을 들여다보는 셈이다.
        if not window:
            log.debug("[UIA] 창이 지정되지 않았다 — Vision 으로")
            return None

        scope = None
        for w in root.GetChildren():
            if w.ControlTypeName == "WindowControl" and window in (w.Name or ""):
                scope = w
                break
        if scope is None:
            log.info("[UIA] '%s' 창을 못 찾았다 — Vision 으로", window)
            return None

        wr = scope.BoundingRectangle
        cands: list = []
        _collect(scope, 0, cands, deadline)

        if time.monotonic() > deadline:
            log.warning("[UIA] %.1fs 안에 못 끝냈다 — Vision 으로 (상한 %.1fs)",
                        time.monotonic() - t0, UIA_TIMEOUT)
            return None
        if not cands:
            return None

        picked = _pick(cands, _norm(target))
        if picked is None:
            return None
        name, rect, stage = picked
        l, t, r, b = rect
        took = time.monotonic() - t0
        log.info("[UIA] 찾음 | %r → %r (%s) | %s | %.3fs | 화면을 안 내보냈다",
                 target, name, stage, (l, t, r, b), took)
        return {
            "found": True,
            "center": ((l + r) // 2, (t + b) // 2),
            "rect": (l, t, r, b),
            "size": (r - l, b - t),
            "label": name,
            "window_rect": (wr.left, wr.top, wr.right, wr.bottom),
            "via": "uia",
            "sec": round(took, 3),
        }
    except Exception as e:                                    # noqa: BLE001
        # 🚨 조용히 넘어가지 않는다. 여기서 실패하면 **매번 Vision 을 타서 느려지는데**
        #   로그가 없으면 «왜 안 빨라졌지»를 못 푼다(BL-69 가 정확히 그 모양이었다).
        log.warning("[UIA] 실패 — Vision 으로 | %s: %s", type(e).__name__, e)
        return None
