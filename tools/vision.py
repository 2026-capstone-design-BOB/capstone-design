"""
화면 이해 (Vision)
==================
스크린샷을 Vision LLM에 넘겨 **화면에 무엇이 있는지 한국어로 설명**한다.
로드맵 9월 Phase 2(화면 이해)의 진입점이다. → docs/ROADMAP.md

## 무엇이 가능해지는가
- *"지금 화면에 뭐 있어?"* — 전체 화면 설명
- *"메모장에 뭐라고 써 있어?"* — 특정 창의 내용 읽기
- *"오류 메시지 뭐라고 떠?"* — 질문을 곁들인 해석

## 설계 결정

**1. 캡처는 `take_screenshot`을 재사용한다.**
창 찾기·최소화 복원·HWND 캡처 로직이 이미 `tools/system.py`에 있다. 다시 짜면
두 벌이 되어 한쪽만 고쳐지는 문제가 생긴다.

**2. 바탕화면이 아니라 임시 파일에 찍고 지운다.**
`take_screenshot`은 바탕화면에 파일을 남기는 게 목적이지만, 여기서는 화면을 *읽는* 게
목적이라 파일이 남으면 쓰레기다. 다 쓰면 지운다.

**3. 보내기 전에 축소한다.**
4K 스크린샷은 수 MB다. 그대로 보내면 느리고 토큰을 많이 먹는다. 긴 변 기준
`_MAX_EDGE`로 줄인다. UI 텍스트 판독에는 이 정도면 충분하다.

## ⚠️ 개인정보 (OWASP LLM02)
**이 도구는 화면 내용을 외부 LLM API로 전송한다.** 화면에 비밀번호·계좌·주민번호가
떠 있으면 그것도 함께 나간다. 그래서:
- 도구 설명(docstring)에 "사용자가 명시적으로 요청할 때만"을 못박아 LLM이 임의로
  호출하지 않게 한다.
- 반환된 설명은 그래프 밖 `mask_sensitive_output()`(core/security.py)을 거쳐
  사용자에게 나간다 — 전송 자체를 막지는 못하지만 **출력 노출은 막힌다.**
- 전송을 원천 차단하려면 로컬 Vision 모델이 필요하다. 현재 범위 밖이다.
"""

import base64
import json
import os
import re
import tempfile

from langchain_core.tools import tool

from core.logger import get_logger

log = get_logger("Vision")

# 긴 변 기준 축소 목표(px). UI 텍스트 판독과 비용의 절충값.
_MAX_EDGE = 1600

# Vision 호출 기본 지시. 화면 설명은 장황해지기 쉬워 형식을 못박는다.
_BASE_PROMPT = (
    "이 스크린샷은 사용자의 Windows 화면입니다. 한국어로 답하세요.\n"
    "- 어떤 프로그램/창이 열려 있는지, 화면에 보이는 주요 텍스트와 버튼을 알려주세요.\n"
    "- 오류 메시지나 경고가 보이면 그 내용을 그대로 옮겨주세요.\n"
    "- 추측하지 말고 실제로 보이는 것만 말하세요. 안 보이면 '보이지 않는다'고 하세요.\n"
    "- 3~5문장으로 간결하게."
)


# ── UI 요소 좌표 찾기 (Phase 2) ────────────────────────────────────
#
# describe_screen은 "무엇이 보이는지"만 답한다. 클릭·자동화로 가려면 "어디에 있는지"가
# 필요하다. 로드맵 9월 항목. → docs/ROADMAP.md
#
# ⚠️ **좌표를 지어내지 않는 것이 이 도구의 전부다.** 화면 설명은 틀려도 사용자가 읽고
#    거르지만, 좌표는 숫자라 그럴듯해 보이고 다음 단계(클릭)가 그대로 믿는다.
#    못 찾았으면 못 찾았다고 해야 한다.

# 정규화 좌표 상한. Gemini의 2D 박스 관례([ymin,xmin,ymax,xmax], 0~1000)를 따르되
# **프롬프트에 명시**한다 — 모델 기본값에 기대면 조용히 어긋난다.
_BOX_SCALE = 1000

# 박스가 이미지를 거의 다 덮으면 "모르겠다"를 그림 전체로 답한 것이다.
# 좌표로서 쓸모가 없으므로 못 찾은 것으로 본다.
_BOX_MAX_COVERAGE = 0.95

_UI_PROMPT = (
    "이 스크린샷은 사용자의 Windows 화면입니다.\n"
    "찾을 대상: {target}\n\n"
    "대상이 화면에 **실제로 보이면** 그 위치를 JSON으로만 답하세요. 설명 문장은 쓰지 마세요.\n"
    '{{"found": true, "box": [ymin, xmin, ymax, xmax], "label": "무엇을 찾았는지"}}\n'
    "좌표는 이미지 기준 0~1000 정수이고 순서는 [ymin, xmin, ymax, xmax]입니다.\n\n"
    "대상이 화면에 **없거나 확실하지 않으면** 반드시 이렇게 답하세요.\n"
    '{{"found": false, "reason": "왜 못 찾았는지 한 문장"}}\n\n'
    "⚠️ 추측해서 좌표를 만들지 마세요. 안 보이면 found를 false로 두는 것이 맞습니다."
)


def parse_ui_box(text: str) -> dict:
    """Vision 응답에서 좌표를 꺼낸다. 못 믿을 답이면 `{"found": False, "reason": …}`.

    **의심스러우면 못 찾은 것으로 본다.** 좌표는 숫자라 그럴듯해 보이고 다음 단계가
    그대로 믿기 때문에, 어중간하게 넘기면 엉뚱한 곳을 클릭하게 된다.
    """
    raw = (text or "").strip()
    if not raw:
        return {"found": False, "reason": "응답이 비어 있습니다"}

    # ```json 펜스를 걷어낸다
    fenced = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", raw, re.S)
    if fenced:
        raw = fenced.group(1).strip()

    data = None
    try:
        data = json.loads(raw)
    except Exception:
        # 앞뒤에 잡담이 섞인 경우 — 객체만 집어낸다
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return {"found": False, "reason": "좌표 형식(JSON)이 아닌 답을 받았습니다"}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {"found": False, "reason": "좌표를 해석하지 못했습니다"}

    # 배열로 답하는 경우가 있다. 하나면 그걸 쓰고, **여럿이면 고르지 않는다** —
    # 조용히 첫 번째를 집으면 사용자는 여러 후보가 있었다는 걸 모른 채
    # 엉뚱한 것을 클릭하게 된다.
    if isinstance(data, list):
        items = [d for d in data if isinstance(d, dict)]
        if len(items) == 1:
            data = items[0]
        elif len(items) > 1:
            return {"found": False,
                    "reason": f"비슷한 후보가 {len(items)}개라 어느 것인지 특정하지 못했습니다"}
        else:
            return {"found": False, "reason": "좌표를 해석하지 못했습니다"}

    if not isinstance(data, dict):
        return {"found": False, "reason": "좌표를 해석하지 못했습니다"}

    if not data.get("found"):
        return {"found": False,
                "reason": str(data.get("reason") or "화면에서 찾지 못했습니다")}

    box = data.get("box")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return {"found": False, "reason": "좌표가 4개가 아닙니다"}
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box)
    except Exception:
        return {"found": False, "reason": "좌표가 숫자가 아닙니다"}

    if not all(0 <= v <= _BOX_SCALE for v in (ymin, xmin, ymax, xmax)):
        return {"found": False, "reason": "좌표가 화면 범위를 벗어났습니다"}
    if ymin >= ymax or xmin >= xmax:
        return {"found": False, "reason": "좌표 순서가 뒤집혀 있습니다"}

    coverage = ((ymax - ymin) / _BOX_SCALE) * ((xmax - xmin) / _BOX_SCALE)
    if coverage >= _BOX_MAX_COVERAGE:
        # 화면 전체를 박스로 답한 것 = 사실상 "모르겠다"
        return {"found": False, "reason": "화면 전체를 가리켜서 위치로 쓸 수 없습니다"}

    return {"found": True, "box": (ymin, xmin, ymax, xmax),
            "label": str(data.get("label") or "").strip()}


def box_to_screen(box, image_size, origin=(0, 0)) -> dict:
    """정규화 박스 → **화면 좌표**. `{"center", "rect", "size"}`.

    정규화 값은 보낸 이미지 기준인데, 축소는 원본을 비율 그대로 줄인 것이라
    **축소 배율이 상쇄된다.** 그래서 원본 크기만 있으면 된다.

    origin은 캡처 이미지의 (0,0)이 화면의 어디인가다(`tools/system.capture_origin`).
    창 캡처면 창의 좌상단, 전체 화면이면 (0,0). 이걸 빼먹으면 창이 화면 가운데 있을 때
    좌표가 통째로 밀린다.
    """
    ymin, xmin, ymax, xmax = box
    w, h = image_size
    ox, oy = origin
    x1 = ox + xmin / _BOX_SCALE * w
    x2 = ox + xmax / _BOX_SCALE * w
    y1 = oy + ymin / _BOX_SCALE * h
    y2 = oy + ymax / _BOX_SCALE * h
    return {
        "center": (round((x1 + x2) / 2), round((y1 + y2) / 2)),
        "rect": (round(x1), round(y1), round(x2), round(y2)),
        "size": (round(x2 - x1), round(y2 - y1)),
    }


def _shrink_and_encode(path: str) -> str:
    """이미지를 축소해 base64로 인코딩. 실패하면 원본을 그대로 인코딩한다."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
            longest = max(w, h)
            if longest > _MAX_EDGE:
                ratio = _MAX_EDGE / longest
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
                log.debug("축소: %dx%d → %dx%d", w, h, img.size[0], img.size[1])
            rgb = img.convert("RGB")
            buf = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            buf.close()
            rgb.save(buf.name, "PNG")
            with open(buf.name, "rb") as f:
                data = f.read()
            os.unlink(buf.name)
            return base64.b64encode(data).decode("ascii")
    except Exception as e:
        log.warning("축소 실패 → 원본 전송: %s", e)
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")


@tool
def describe_screen(window: str = "", question: str = "") -> str:
    """
    지금 화면에 무엇이 보이는지 확인해 설명합니다.
    사용자가 화면 내용을 물어볼 때만 사용하세요 (예: "지금 화면에 뭐 있어?",
    "메모장에 뭐라고 써 있어?", "무슨 오류가 떴어?").

    window: 볼 대상 — 비워두면 전체 화면 / "활성창"이면 현재 포커스 창 / 앱 이름이면 해당 창
    question: 화면에 대해 구체적으로 묻고 싶은 것 (비워두면 전체 설명)
    """
    tmp_path = ""
    try:
        # ── 1) 캡처 (tools/system.py 재사용) ───────────────────────
        from tools.system import take_screenshot

        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="pluiz_vision_")
        os.close(fd)

        shot = take_screenshot.invoke({"save_path": tmp_path, "window": window})
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            log.warning("캡처 실패: %s", shot)
            return f"✗ 화면을 캡처하지 못했습니다. {shot}"

        log.info("캡처 완료 (%s) %d bytes",
                 window or "전체화면", os.path.getsize(tmp_path))

        # ── 2) Vision 호출 ────────────────────────────────────────
        b64 = _shrink_and_encode(tmp_path)

        prompt = _BASE_PROMPT
        if question.strip():
            prompt += f"\n\n사용자의 질문: {question.strip()}\n이 질문에 먼저 답하세요."

        from langchain_core.messages import HumanMessage
        from core.llm import build_llm

        llm = build_llm()
        msg = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"},
        ])

        log.debug("Vision 호출 (question=%r)", question)
        res = llm.invoke([msg])
        text = (getattr(res, "content", "") or "").strip()

        if not text:
            log.warning("Vision 응답이 비어 있음")
            return "✗ 화면을 분석했지만 설명을 받지 못했습니다. 다시 시도해주세요."

        log.info("Vision 응답 %d자", len(text))
        return text

    except ImportError as e:
        log.exception("Vision 의존성 없음")
        return f"[오류] 화면 분석에 필요한 패키지가 없습니다: {e}"
    except Exception as e:
        # 네트워크·API 키·쿼터 등. 사용자에게는 짧게, 파일에는 스택트레이스까지.
        log.exception("Vision 호출 실패")
        return f"[오류] 화면을 분석하지 못했습니다: {type(e).__name__}: {e}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                log.debug("임시 파일 삭제 실패: %s", tmp_path)


def locate_ui_element(target: str, window: str = "") -> dict:
    """화면에서 요소를 찾아 **화면 좌표**를 돌려준다. 도구가 아니라 내부 함수다.

    찾으면 `{"found": True, "center", "rect", "size", "label", "window_rect"}`,
    못 찾으면 `{"found": False, "reason": …}`.

    `find_ui_element`(사람에게 알려주기)와 `click_ui_element`(실제로 누르기)가 **같은
    경로**를 쓰게 하려고 뺐다. 클릭 쪽에서 좌표를 다시 구하면 두 벌이 되어 한쪽만
    고쳐진다 — 좌표는 어긋나도 그럴듯해 보이므로 특히 위험하다.

    `window_rect`는 캡처 당시 창의 화면 사각형이다. 클릭 직전에 창이 움직이지
    않았는지 대조하는 데 쓴다.
    """
    tmp_path = ""
    try:
        from tools.system import take_screenshot, capture_origin, resolve_window_hwnd, window_screen_rect

        # ── 1) 캡처 원점 먼저 (좌표를 되돌리려면 반드시 필요) ──────
        # 캡처보다 **먼저** 구한다. 캡처는 됐는데 원점을 못 구하면 좌표를 화면
        # 좌표로 옮길 수 없고, 그때 창 기준 좌표를 화면 좌표인 척 내보내면
        # 다음 단계(클릭)가 엉뚱한 데를 누른다.
        try:
            origin = capture_origin(window)
            window_rect = None
            if window:
                hwnd, _ = resolve_window_hwnd(window)
                if hwnd:
                    window_rect = window_screen_rect(hwnd)
        except Exception as e:
            log.warning("캡처 원점 실패: %s", e)
            return {"found": False,
                    "reason": f"'{window or '화면'}'의 위치를 확인하지 못했습니다: {e}"}

        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="pluiz_uiloc_")
        os.close(fd)
        shot = take_screenshot.invoke({"save_path": tmp_path, "window": window})
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            log.warning("캡처 실패: %s", shot)
            return {"found": False, "reason": f"화면을 캡처하지 못했습니다. {shot}"}

        # ── 2) 원본 크기 (정규화 좌표를 픽셀로 되돌릴 기준) ────────
        try:
            from PIL import Image
            with Image.open(tmp_path) as im:
                image_size = im.size
        except Exception as e:
            log.warning("이미지 크기 확인 실패: %s", e)
            return {"found": False, "reason": f"화면 크기를 확인하지 못했습니다: {e}"}

        # ── 3) Vision 호출 ────────────────────────────────────────
        b64 = _shrink_and_encode(tmp_path)

        from langchain_core.messages import HumanMessage
        from core.llm import build_llm

        log.info("UI 요소 탐색 (%s) target=%r", window or "전체화면", target)
        res = build_llm().invoke([HumanMessage(content=[
            {"type": "text", "text": _UI_PROMPT.format(target=target)},
            {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"},
        ])])
        parsed = parse_ui_box(getattr(res, "content", "") or "")

        if not parsed["found"]:
            log.info("UI 요소 못 찾음: %s", parsed["reason"])
            return {"found": False, "reason": parsed["reason"]}

        loc = box_to_screen(parsed["box"], image_size, origin)
        loc["found"] = True
        loc["label"] = parsed["label"] or target
        loc["window_rect"] = window_rect
        log.info("UI 요소 찾음: %r → center=%s size=%s",
                 loc["label"], loc["center"], loc["size"])
        return loc

    except ImportError as e:
        log.exception("Vision 의존성 없음")
        return {"found": False, "reason": f"필요한 패키지가 없습니다: {e}"}
    except Exception as e:
        log.exception("UI 요소 탐색 실패")
        return {"found": False, "reason": f"{type(e).__name__}: {e}"}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                log.debug("임시 파일 삭제 실패: %s", tmp_path)


@tool
def find_ui_element(target: str, window: str = "") -> str:
    """
    화면에서 버튼·메뉴·입력창 같은 UI 요소를 찾아 **화면 좌표**를 알려줍니다.
    사용자가 "저장 버튼 어디 있어?"처럼 위치를 물을 때 사용하세요.
    (실제로 누르려면 click_ui_element를 쓰세요)

    target: 찾을 것 (예: "저장 버튼", "검색창", "닫기 X 버튼")
    window: 볼 대상 — 비워두면 전체 화면 / "활성창" / 앱 이름

    화면에 없으면 좌표를 만들어내지 않고 "찾지 못했다"고 답합니다.
    """
    loc = locate_ui_element(target, window)
    if not loc["found"]:
        return f"✗ 화면에서 '{target}'을(를) 찾지 못했습니다. ({loc['reason']})"

    cx, cy = loc["center"]
    bw, bh = loc["size"]
    where = f" ({window} 창)" if window else ""
    # 좌표를 냈다고 해서 확인된 건 아니다. Vision의 추정임을 문장에 남긴다.
    return (f"✓ '{loc['label']}'{where}을(를) 화면 좌표 ({cx}, {cy})에서 찾았습니다. "
            f"크기 {bw}×{bh}. (화면을 보고 추정한 위치예요)")
