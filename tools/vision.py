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


def _log_response(kind: str, text: str) -> None:
    """Vision 응답을 로그에 남긴다 — 기본은 **길이만**. (2026-09-08)

    ⚠️ 미리보기는 **옵트인**이다(`.env` 에 `VISION_LOG_RESPONSE=true`).
      화면에 떠 있던 내용이 로그 파일에 그대로 남기 때문이다. 로그는
      `mask_sensitive_output()`을 거치지 않는다 — 그건 사용자에게 나가는 응답에만
      걸린다. 그래서 켜는 것은 **사람이 의도적으로** 하는 일이어야 한다.

    왜 옵션이라도 두는가 — 지금은 `Vision 응답 349자`처럼 길이만 남아서,
    2026-09-03에 *"Vision이 뭐라고 답했길래 저 결과가 나왔나"* 를 사후에 확인할
    방법이 없어 진단이 한 번 막혔다.

    설정을 못 읽으면 **안 남기는 쪽**으로 간다 — 안전 기본값이 조용히 뒤집히면 안 된다.
    """
    on, n = False, 0
    try:
        from config.settings import get_settings
        _s = get_settings()
        on, n = bool(_s.vision_log_response), int(_s.vision_log_preview_chars)
    except Exception:
        pass

    if not on or n <= 0:
        log.info("%s %d자", kind, len(text))
        return

    preview = text[:n].replace("\n", " ")
    log.info("%s %d자 | %s%s", kind, len(text), preview,
             "…" if len(text) > n else "")


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


def _shrink_and_encode_image(img) -> str:
    """PIL 이미지를 축소해 base64(PNG)로 인코딩한다.

    파일 경로가 아니라 **메모리의 이미지**를 받는 판이다. 화면 감시(watch_screen)는
    이미 픽셀 비교를 위해 캡처를 해 둔 상태라, 파일로 저장했다 다시 여는 왕복이
    있으면 같은 화면을 두 번 찍게 된다.
    """
    from PIL import Image

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


def _shrink_and_encode(path: str) -> str:
    """이미지 파일을 축소해 base64로 인코딩. 실패하면 원본을 그대로 인코딩한다."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            return _shrink_and_encode_image(img)
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

        _log_response("Vision 응답", text)
        return text

    except ImportError as e:
        log.exception("Vision 의존성 없음")
        return f"✗ 화면 분석에 필요한 패키지가 없습니다: {e}"
    except Exception as e:
        # 네트워크·API 키·쿼터 등. 사용자에게는 짧게, 파일에는 스택트레이스까지.
        log.exception("Vision 호출 실패")
        return f"✗ 화면을 분석하지 못했습니다: {type(e).__name__}: {e}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                log.debug("임시 파일 삭제 실패: %s", tmp_path)


# ── 확대(zoom) — 돋보기 방식 (M4 §6, 2026-09-09 사용자 선택) ────────
# ⚠️ **화면을 다시 찍지 않는다.** 다시 찍으면 그 사이에 뜬 우리 오버레이가 들어간다
#   (§5의 그 문제다). `locate_ui_element`가 **이미 찍어 둔 그 파일**에서 자른다.
#
# 처음엔 가장자리 카드였는데, 사용자가 *"저렇게 위에 그림이 뜨는 게 아니라 다른
# 방식으로"* 라고 해서 **돋보기**로 바꿨다(2026-09-09). 대상 자리에 겹쳐 띄우므로
# **시선을 옮길 필요가 없다** — 접근성 보조라는 목적에 더 맞는다.
LOUPE_SRC_PX = 150      # 대상 중심 기준 **물리 픽셀** 정사각 한 변. 이만큼을 잘라
LOUPE_OUT_PX = 450      # 이 크기 PNG로 키워 보낸다(고해상도 화면에서도 또렷하게)
LOUPE_MAG = 3           # 화면에 보일 배율. 고정한다 — 조절 UI를 만들지 않는다


def loupe_data_uri(image_path: str, center_img, src_px: int = LOUPE_SRC_PX,
                   out_px: int = LOUPE_OUT_PX):
    """대상 중심 주변 정사각형을 잘라 확대한 PNG data URI. 실패하면 None.

    `center_img`는 **캡처 이미지 안의** 좌표다(화면 좌표가 아니다 — 창 캡처면
    원점이 (0,0)이 아니므로 호출부에서 미리 옮겨 준다).

    ⚠️ 실패를 예외로 만들지 않는다. 확대는 **곁들이**이고, 못 만들었다고 포인팅
      자체가 죽으면 안 된다 — 고리는 그대로 그려진다.
    ⚠️ 정사각형이어야 한다. 렌더러가 **원형 돋보기**로 그리므로 비율이 어긋나면
      가운데가 대상이 아니게 된다.
    """
    try:
        from PIL import Image
        import base64, io as _io

        cx, cy = int(center_img[0]), int(center_img[1])
        half = max(8, int(src_px) // 2)
        with Image.open(image_path) as im:
            iw, ih = im.size
            # 가장자리에 붙어도 **정사각형과 중심을 유지**한다 — 잘린 채로 늘이면
            # 돋보기 가운데가 대상에서 밀린다.
            l, t = cx - half, cy - half
            r, b = cx + half, cy + half
            pad_l, pad_t = max(0, -l), max(0, -t)
            pad_r, pad_b = max(0, r - iw), max(0, b - ih)
            crop = im.crop((max(0, l), max(0, t), min(iw, r), min(ih, b)))
            if crop.size[0] <= 0 or crop.size[1] <= 0:
                return None
            if pad_l or pad_t or pad_r or pad_b:
                canvas = Image.new("RGB", (half * 2, half * 2), (24, 26, 32))
                canvas.paste(crop.convert("RGB"), (pad_l, pad_t))
                crop = canvas
            crop = crop.convert("RGB").resize((out_px, out_px), Image.LANCZOS)
            buf = _io.BytesIO()
            crop.save(buf, format="PNG", optimize=True)
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        log.warning("확대 이미지 생성 실패(무시): %s: %s", type(e).__name__, e)
        return None


# ── 2패스 정밀화 (2026-09-09 사용자 선택) ──────────────────────────
# 1차 좌표의 **반복 오차가 요소 크기만큼** 있었다(실측: 같은 «파일 메뉴»를 5번
# 찾아 x 편차 36px · y 편차 43px, 요소는 100×25px). 원인은 버그가 아니라
# **보내는 이미지의 해상도**다 — 전체화면 3072px를 1600px로 줄여 보내므로
# 작은 UI 요소는 몇 픽셀짜리가 된다.
#
# 그래서 1차 주변만 잘라 **그 조각만** 다시 묻는다. 조각은 축소되지 않으므로
# 같은 요소가 훨씬 크게 보인다.
#
# ⚠️ **실패하면 1차 결과를 그대로 쓴다.** 정밀화는 개선 시도이지 관문이 아니다 —
#   여기서 못 찾았다고 «못 찾음»으로 뒤집으면, 1차가 맞았을 때도 놓친다.
REFINE_PAD = 3.0        # 1차 요소 크기의 몇 배를 여유로 둘지
REFINE_MIN_PX = 260     # 조각이 너무 작으면 맥락이 없어 오히려 헷갈린다
REFINE_MAX_PX = 900     # 너무 크면 축소가 다시 일어나 의미가 없다


def refine_box(base_rect, image_size, pad=REFINE_PAD):
    """정밀화에 쓸 **조각 영역**(이미지 좌표). `(l, t, r, b)`.

    순수 함수라 테스트가 이미지 없이 본다.
    """
    l, t, r, b = [float(v) for v in base_rect]
    iw, ih = image_size
    w, h = max(1.0, r - l), max(1.0, b - t)
    side = max(REFINE_MIN_PX, min(REFINE_MAX_PX, max(w, h) * pad))
    cx, cy = (l + r) / 2, (t + b) / 2
    half = side / 2
    # 이미지 밖으로 나가면 **밀어 넣는다**(잘라내지 않는다) — 조각이 작아지면
    # 배율이 줄어 정밀화 효과가 사라진다.
    x1 = max(0, min(iw - side, cx - half))
    y1 = max(0, min(ih - side, cy - half))
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(iw, x1 + side), min(ih, y1 + side)
    return (int(x1), int(y1), int(x2), int(y2))


def box_in_crop_to_image(box, crop_rect):
    """조각 안의 정규화 박스 → **원본 이미지 좌표** 사각형."""
    ymin, xmin, ymax, xmax = box
    l, t, r, b = crop_rect
    cw, ch = max(1, r - l), max(1, b - t)
    return (l + xmin / _BOX_SCALE * cw, t + ymin / _BOX_SCALE * ch,
            l + xmax / _BOX_SCALE * cw, t + ymax / _BOX_SCALE * ch)


def locate_ui_element(target: str, window: str = "", want_crop: bool = False,
                      refine: bool = False, ensure_visible: bool = False) -> dict:
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
    prepared = {"action": "", "label": window}
    try:
        from tools.system import (take_screenshot, capture_origin, resolve_window_hwnd,
                                  window_screen_rect)

        # 창을 **볼 수 있는 상태**로 먼저 만든다(2026-09-09). 없으면 열고, 최소화면
        # 되살려 앞으로 낸다. ⚠️ 기본은 False다 — click_ui_element는 승인 범위를
        # 넘기지 않아야 하므로 이 경로를 타지 않는다. → tools/system.ensure_window_ready
        # ⚠️ **여기서 늦게 가져온다.** 위 한 줄에 같이 넣었더니, `tools.system`을
        #   가짜 모듈로 갈아끼우는 테스트(test_ui_locate)가 통째로 깨졌다 —
        #   창 준비는 **선택 기능**인데 그것 때문에 기본 경로가 죽으면 안 된다.
        if ensure_visible and window:
            try:
                from tools.system import ensure_window_ready
            except ImportError:
                # 창 준비는 **곁들이**다. 없으면 그냥 지금 화면을 본다 —
                # 선택 기능이 없다고 «필요한 패키지가 없습니다»로 끝나면 안 된다.
                ensure_window_ready = None
            if ensure_window_ready is not None:
                prepared = ensure_window_ready(window)
                if not prepared["ok"]:
                    return {"found": False, "reason": prepared["reason"],
                            "prepared": prepared}

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
            return {"found": False, "reason": parsed["reason"], "prepared": prepared}

        loc = box_to_screen(parsed["box"], image_size, origin)
        loc["found"] = True
        loc["label"] = parsed["label"] or target
        loc["window_rect"] = window_rect
        loc["prepared"] = prepared

        # ── 2패스 정밀화 ─────────────────────────────────────────
        # 1차 주변만 잘라 **그 조각만** 다시 묻는다. 조각은 축소되지 않으므로
        # 같은 요소가 훨씬 크게 보인다. 실패하면 1차 결과를 그대로 쓴다.
        if refine:
            img_rect = (loc["rect"][0] - origin[0], loc["rect"][1] - origin[1],
                        loc["rect"][2] - origin[0], loc["rect"][3] - origin[1])
            crop_rect = refine_box(img_rect, image_size)
            try:
                from PIL import Image
                with Image.open(tmp_path) as im:
                    piece = im.crop(crop_rect)
                b64p = _shrink_and_encode_image(piece)
                res2 = build_llm().invoke([HumanMessage(content=[
                    {"type": "text", "text": _UI_PROMPT.format(target=target)},
                    {"type": "image_url", "image_url": f"data:image/png;base64,{b64p}"},
                ])])
                p2 = parse_ui_box(getattr(res2, "content", "") or "")
                if p2["found"]:
                    r2 = box_in_crop_to_image(p2["box"], crop_rect)
                    before = loc["center"]
                    loc["rect"] = (round(r2[0] + origin[0]), round(r2[1] + origin[1]),
                                   round(r2[2] + origin[0]), round(r2[3] + origin[1]))
                    loc["center"] = (round((loc["rect"][0] + loc["rect"][2]) / 2),
                                     round((loc["rect"][1] + loc["rect"][3]) / 2))
                    loc["size"] = (loc["rect"][2] - loc["rect"][0],
                                   loc["rect"][3] - loc["rect"][1])
                    loc["refined"] = True
                    dx = loc["center"][0] - before[0]
                    dy = loc["center"][1] - before[1]
                    log.info("좌표 정밀화 | %s → %s (Δ%+d,%+d)",
                             before, loc["center"], dx, dy)
                else:
                    # ⚠️ 뒤집지 않는다. 조각에서 못 봤다고 1차가 틀린 건 아니다.
                    log.info("좌표 정밀화 실패(1차 유지): %s", p2["reason"])
            except Exception as e:
                log.warning("좌표 정밀화 건너뜀(%s: %s) — 1차 좌표를 쓴다",
                            type(e).__name__, e)

        # 확대본은 **여기서** 만든다 — 아래 finally가 임시 파일을 지우기 전이고,
        # 무엇보다 이 캡처에는 우리 오버레이가 들어 있지 않다(§5·§6).
        # ⚠️ 기본은 False다. find_ui_element·click_ui_element는 지금까지와 같다.
        if want_crop:
            loc["crop"] = loupe_data_uri(
                tmp_path,
                (loc["center"][0] - origin[0], loc["center"][1] - origin[1]))
            loc["crop_src_px"] = LOUPE_SRC_PX
            loc["crop_mag"] = LOUPE_MAG
        log.info("UI 요소 찾음: %r → center=%s size=%s%s",
                 loc["label"], loc["center"], loc["size"],
                 " (정밀화됨)" if loc.get("refined") else "")
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


# ── BL-64: 「블루투스 어디서 켜?」의 **범위** ─────────────────────
#
# 🚨 2026-09-20 3차 리허설에서 *"블루투스 어디서 켜?"* 가 설정을 열지 않고
#   **화면에 열려 있던 문서의 「블루투스」 글자**를 짚었다. 대본 5장면이다.
#
# **원인은 화면이 아니라 인자였다.** 로그 셋이 그대로 말한다:
#
#   2026-09-12  탐색 (설정)     target='블루투스'      → ✅ 찾음 (335,410)
#   2026-09-14  탐색 (설정)     target='비행기 모드'   → ❌ 못 찾음(다른 페이지)
#   2026-09-20  탐색 (전체화면) target='블루투스'      → 🔴 문서의 글자
#
# 발화는 거의 같았다(「블루투스 기능은 어디서 켜야 돼」↔「블루투스는 어디서 켜」).
# **`window` 를 채울지 말지를 LLM 이 매번 다르게 고른다.**
#
# 🔑 **그래서 도구 설명에 «설정이면 window 를 넣어라»라고 적는 것으로는 안 된다** —
#   프롬프트는 확률을 올릴 뿐이고 보장하는 건 구조다(BL-19의 교훈). 오늘 실패가
#   바로 그 증거다: 같은 질문에 다른 인자가 나왔다.
#
# ⚠️ **«못 찾으면 설정을 열고 다시 본다»로는 안 고쳐진다.** 오늘은 **못 찾은 게
#   아니라 잘못 찾았다.** 화면에 그 글자가 있었기 때문이다. 그래서 되돌아보는
#   보강이 아니라 **범위를 먼저 정하는** 수선이어야 한다.
#
# ⚠️ 오판의 방향이 안전하다 — **빠뜨리면 오늘과 같이 동작할 뿐이고**(전체 화면을
#   본다), 넣으면 설정에서 찾는다. `command_cache._DEIXIS_TOKENS` 가 정한 비대칭과
#   같은 모양이라 **여집합이 아니라 화이트리스트로** 적는다.
#
# 🚫 「저장 버튼」·「검색창」처럼 **지금 보는 앱의 것**은 여기 넣지 않는다.
#   넣으면 사용자가 안 시킨 설정 창이 뜬다.
_SETTINGS_TARGETS = (
    "블루투스", "bluetooth",
    "와이파이", "와이 파이", "wifi", "wi-fi", "무선랜",
    "비행기모드", "기내모드",
    "핫스팟", "vpn",
    "야간모드", "야간조명", "다크모드", "절전모드", "배터리절약",
    "windows업데이트", "윈도우업데이트",
    "기본앱", "방화벽", "접근성",
)

#: 설정 안의 것을 찾을 때 쓸 창 이름. `ensure_window_ready` 가 아는 이름이어야 한다.
_SETTINGS_WINDOW = "설정"


def resolve_search_window(target: str, window: str = "") -> str:
    """찾을 대상이 **Windows 설정 안의 것**이면 볼 창을 「설정」으로 정한다. (BL-64)

    `window` 가 이미 있으면 **건드리지 않는다** — 사용자/LLM 이 정한 범위가 우선이다.

    🔑 **`find_ui_element` 와 `point_at_element` 가 같은 판정을 받게** 하려고 뺐다.
      두 벌로 두면 한쪽만 고쳐진다 — 감사 G-08 이 `maximize_window`·`minimize_window`
      에서 실제로 그렇게 됐고, 그때도 **합치는 것**으로 끝냈다.
    """
    if window:
        return window
    key = "".join((target or "").split()).lower()
    if not key:
        return window
    return _SETTINGS_WINDOW if any(t in key for t in _SETTINGS_TARGETS) else window


@tool
def find_ui_element(target: str, window: str = "") -> str:
    """
    화면에서 버튼·메뉴·입력창 같은 UI 요소를 찾아 **화면 좌표**를 알려줍니다.
    사용자가 "저장 버튼 어디 있어?"처럼 위치를 물을 때 사용하세요.
    (실제로 누르려면 click_ui_element를 쓰세요)

    target: 찾을 것 (예: "저장 버튼", "검색창", "닫기 X 버튼")
    window: 볼 대상 — 비워두면 전체 화면 / "활성창" / 앱 이름
      · 블루투스·와이파이 같은 **Windows 설정 항목은 비워 두세요** —
        설정 창을 알아서 열고 거기서 찾습니다.

    화면에 없으면 좌표를 만들어내지 않고 "찾지 못했다"고 답합니다.
    """
    # 「어디 있어?」도 화면을 보는 질문이라, 창이 없거나 최소화면 먼저 살린다.
    # BL-64 — 설정 안의 것이면 **전체 화면을 뒤지지 않는다.** 화면 어딘가에 같은
    #   글자가 있으면 그걸 짚어 버린다(2026-09-20 실측).
    window = resolve_search_window(target, window)
    loc = locate_ui_element(target, window, ensure_visible=True)
    if not loc["found"]:
        return (prepared_note(loc) +
                f"✗ 화면에서 '{target}'을(를) 찾지 못했습니다. ({loc['reason']})")

    cx, cy = loc["center"]
    bw, bh = loc["size"]
    where = f" ({window} 창)" if window else ""
    # 좌표를 냈다고 해서 확인된 건 아니다. Vision의 추정임을 문장에 남긴다.
    return (prepared_note(loc) +
            f"✓ '{loc['label']}'{where}을(를) 화면 좌표 ({cx}, {cy})에서 찾았습니다. "
            f"크기 {bw}×{bh}. (화면을 보고 추정한 위치예요)")


def prepared_note(loc) -> str:
    """창을 어떻게 했는지 **먼저** 말할 접두 문구. 아무 일도 안 했으면 빈 문자열.

    ⚠️ 조용히 앱을 열거나 창을 앞으로 내면 안 된다. 사용자는 «표시해 줘»라고
      했지 «열어 줘»라고 하지 않았고, 화면이 바뀐 이유를 알 권리가 있다.
      이 프로젝트가 반복해서 고쳐 온 것이 **«한 일을 말하지 않는 것»** 이다.
    """
    p = (loc or {}).get("prepared") or {}
    label = p.get("label") or ""
    return {
        "launched": f"'{label}'이(가) 꺼져 있어서 먼저 열었어요. ",
        "restored": f"'{label}'이(가) 최소화돼 있어서 다시 띄웠어요. ",
        "fronted":  f"'{label}'을(를) 앞으로 가져왔어요. ",
    }.get(p.get("action") or "", "")


@tool
def point_at_element(target: str, window: str = "", zoom: bool = False) -> str:
    """
    화면에서 UI 요소를 찾아 **그 자리를 화면에 직접 표시**합니다.
    사용자가 "그게 어딨지", "블루투스 설정 어디서 켜?"처럼 **직접 찾고 싶어 할 때**
    쓰세요. 표시는 몇 초 뒤 저절로 사라지고, 화면은 아무것도 바뀌지 않습니다.

    target: 찾을 것 (예: "블루투스", "저장 버튼", "검색창")
    window: 볼 대상 — 비워두면 전체 화면 / "활성창" / 앱 이름
      · 블루투스·와이파이 같은 **Windows 설정 항목은 비워 두세요** —
        설정 창을 알아서 열고 거기서 찾습니다. 바탕화면에서 물어도 됩니다.
    zoom:   True면 그 부분을 크게 확대해서 같이 보여줍니다 (잘 안 보일 때)

    화면에 없으면 **아무것도 표시하지 않고** "찾지 못했다"고 답합니다.
    (대신 눌러 주려면 click_ui_element를 쓰세요 — 그건 승인이 필요합니다)
    """
    from core import pointer

    # ⚠️ **먼저 지운다.** 안 지우면 아래 캡처가 «이전 표시»가 사라지기를 8초
    #   기다린다(연달아 포인팅할 때). 어차피 새 표시로 덮을 것이다.
    pointer.hide("새 포인팅")

    # 확대본은 **이 캡처에서** 만들어진다(§6) — 다시 찍으면 우리 오버레이가 들어간다
    # 🚨 **refine=False** — 2패스 정밀화를 껐다(2026-09-09 실측).
    #   넣어 봤더니 **좋아지지 않고 나빠졌다.** 조각 안에서 Gemini가 메뉴가 아니라
    #   글자 일부 같은 것을 잡아, 요소 크기가 75×22 → 13~26px로 무너졌다.
    #   그리고 턴이 9초 → 13~17초가 됐다. **비용은 확실하고 효과는 음수다.**
    #   코드는 남겨 둔다 — 조각 프롬프트를 다듬으면 살아날 수 있고,
    #   무엇보다 «해 봤고 이랬다»가 지워지면 또 같은 걸 시도한다.
    #   → docs/design/M4_포인팅_확대.md §6-A
    # BL-64 — 범위를 **먼저** 정한다. 여기가 비면 전체 화면을 뒤지고, 화면에
    #   우연히 같은 글자가 있으면 **틀린 곳을 자신 있게 짚는다**(M4 §3이 막으려던 것).
    window = resolve_search_window(target, window)
    loc = locate_ui_element(target, window, want_crop=bool(zoom),
                            refine=False, ensure_visible=True)
    payload = pointer.point_payload(loc, zoom=zoom)
    if payload is None:
        # 못 찾았으면 **그리지 않는다.** 띄워 놓고 "근처일 거예요"라고 하면
        # 사용자는 없는 것을 찾게 된다. → ADR §4-3
        reason = loc.get("reason", "") if isinstance(loc, dict) else ""
        return (prepared_note(loc) +
                f"✗ 화면에서 '{target}'을(를) 찾지 못했습니다. ({reason})")

    pointer.show(payload)
    where = f" ({window} 창)" if window else ""
    # ⚠️ 확대본을 못 만들었으면 «확대했다»고 말하지 않는다. point_payload가
    #   zoom을 False로 내려 두므로 payload를 보고 판단한다 — 인자가 아니라 결과다.
    extra = " 크게 확대해서 같이 보여드렸어요." if payload.get("zoom") else ""
    # find_ui_element와 **같은 단서**를 단다. 화면의 표시 자체에는 단서가 없으므로
    # (그림은 정확해 보인다) 문장에서라도 추정임을 말한다. 표시 옆 라벨은
    # Electron이 그린다. → ADR §4-3
    return (prepared_note(loc) +
            f"✓ '{payload['label'] or target}'{where}을(를) 화면에 표시했어요.{extra} "
            f"{int(payload['seconds'])}초 뒤 사라져요. (화면을 보고 추정한 위치예요)")


# ── 화면 변화 모니터링 (Phase 2 마지막 항목) ───────────────────────
#
# *"오류 뜨면 알려줘"* — 턴이 끝난 뒤에도 지켜보다가 **먼저 말을 건다.**
# 루프·상한·중단 조건은 core/screen_monitor.py 가 담당하고, 여기는 그 엔진에
# 넣어 줄 **눈**(캡처·판정)과 사용자에게 보이는 **도구 2개**만 둔다.
#
# ⚠️ 이 기능은 지금까지 중 화면 전송량이 가장 크다(OWASP LLM02). 방어는 두 겹이다 —
#    ① 픽셀 차이로 먼저 거르고(캡처는 전부 로컬), ② 상한이 곧 전송 장수의 상한이다.
#    배경은 core/screen_monitor.py 의 모듈 docstring 참조.

_WATCH_PROMPT = (
    "이 스크린샷은 사용자의 Windows 화면입니다.\n"
    "사용자가 알려달라고 한 것: {what}\n\n"
    "그것이 화면에 **실제로 보이면** JSON으로만 답하세요. 설명 문장은 쓰지 마세요.\n"
    '{{"detected": true, "detail": "무엇이 보이는지 화면의 문구를 그대로 옮겨 한두 문장"}}\n\n'
    "보이지 않거나 확실하지 않으면 반드시 이렇게 답하세요.\n"
    '{{"detected": false, "reason": "왜 아닌지 한 문장"}}\n\n'
    "⚠️ 추측하지 마세요. 화면에 없으면 detected를 false로 두는 것이 맞습니다.\n"
    "⚠️ detected가 true인데 무엇을 봤는지 말할 수 없다면 그건 false입니다."
)


def parse_watch_result(text: str) -> dict:
    """Vision 응답에서 감지 여부를 꺼낸다.

    반환: `{"ok": bool, "detected": bool, "detail": str, "reason": str}`
    `ok`가 False면 **응답을 해석하지 못한 것**이다 — 호출부는 아무것도 알리면 안 된다.

    `parse_ui_box`와 같은 방침이다: **의심스러우면 아무 일도 없던 것으로 본다.**
    감시는 사용자가 화면을 안 볼 때 도는 기능이라, 잘못된 알림은 "확인하지 않고
    됐다고 말하는 것"과 똑같은 결함이 된다.
    """
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "detected": False, "detail": "",
                "reason": "응답이 비어 있습니다"}

    fenced = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", raw, re.S)
    if fenced:
        raw = fenced.group(1).strip()

    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return {"ok": False, "detected": False, "detail": "",
                    "reason": "JSON이 아닌 답을 받았습니다"}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {"ok": False, "detected": False, "detail": "",
                    "reason": "답을 해석하지 못했습니다"}

    # 배열로 답하는 경우 — 하나면 받아주고, 여럿이면 고르지 않는다.
    # (parse_ui_box와 같은 이유: 조용히 첫 번째를 집으면 사용자는 모른다)
    if isinstance(data, list):
        items = [d for d in data if isinstance(d, dict)]
        if len(items) == 1:
            data = items[0]
        else:
            return {"ok": False, "detected": False, "detail": "",
                    "reason": "답이 하나로 특정되지 않았습니다"}

    if not isinstance(data, dict):
        return {"ok": False, "detected": False, "detail": "",
                "reason": "답을 해석하지 못했습니다"}

    if "detected" not in data:
        # 필드가 없으면 "안 보인다"가 아니라 **못 알아들은 것**이다. 그 둘을 섞으면
        # 모델이 형식을 어길 때마다 조용히 "이상 없음"으로 집계된다.
        return {"ok": False, "detected": False, "detail": "",
                "reason": "detected 항목이 없습니다"}

    detected = data.get("detected")
    if not isinstance(detected, bool):
        return {"ok": False, "detected": False, "detail": "",
                "reason": "detected가 참/거짓이 아닙니다"}

    return {
        "ok": True,
        "detected": detected,
        "detail": str(data.get("detail") or "").strip(),
        "reason": str(data.get("reason") or "").strip(),
    }


def _capture_image(window: str = ""):
    """감시용 캡처 — PIL 이미지를 **메모리로** 돌려준다. 실패하면 예외.

    ⚠️ **`take_screenshot`을 쓰지 않는다.** 그 도구는 최소화된 창을
      `SW_RESTORE` → 캡처 → `SW_MINIMIZE` 한다(tools/system.py). 한 번 찍을 땐
      친절한 동작이지만, **5초마다 그러면 창이 계속 깜빡인다.**
      감시는 사용자를 방해하지 않아야 하므로, 최소화된 창은 되살리지 않고
      **못 본다고 말한다**(→ 엔진이 사유와 함께 감시를 멈춘다).

    창 해석은 `resolve_window_hwnd`를, 캡처는 `_capture_hwnd`를 그대로 재사용한다.
    여기서 따로 구현하면 `take_screenshot`·좌표 계산과 **다른 창**을 볼 수 있다.
    """
    from PIL import ImageGrab

    if not window:
        return ImageGrab.grab()

    import ctypes
    from tools.system import resolve_window_hwnd, _capture_hwnd

    hwnd, label = resolve_window_hwnd(window)
    if not hwnd:
        raise ValueError(f"'{window}' 창을 찾을 수 없습니다")
    if ctypes.windll.user32.IsIconic(hwnd):
        raise ValueError(f"'{label}' 창이 최소화돼 있습니다")
    return _capture_hwnd(hwnd)


def screen_signature(window: str = ""):
    """화면을 32×32 그레이스케일로 줄인 **서명**. 실패하면 None.

    감시 루프가 5초마다 부르는 값이다. **여기서는 아무것도 외부로 나가지 않는다** —
    변화가 있는지 로컬에서 판단하는 게 목적이고, 그래야 Vision 호출을 아낀다.
    """
    from core.screen_monitor import SIGNATURE_SIDE

    try:
        img = _capture_image(window)
        small = img.convert("L").resize((SIGNATURE_SIDE, SIGNATURE_SIDE))
        return tuple(small.getdata())
    except Exception as e:
        log.debug("서명 캡처 실패(%s): %s", window or "전체화면", e)
        return None


def vision_watch_check(window: str, what: str) -> dict:
    """화면을 실제로 보고 *"그게 보이나?"* 를 판정한다. 감시 엔진이 부른다.

    반환 규약은 `parse_watch_result`와 같다. **예외를 밖으로 내보내지 않는다** —
    감시가 서버를 죽이면 안 된다.
    """
    try:
        img = _capture_image(window)
    except Exception as e:
        log.warning("감시 캡처 실패: %s", e)
        return {"ok": False, "detected": False, "detail": "", "reason": str(e)}

    try:
        b64 = _shrink_and_encode_image(img)

        from langchain_core.messages import HumanMessage
        from core.llm import build_llm

        res = build_llm().invoke([HumanMessage(content=[
            {"type": "text", "text": _WATCH_PROMPT.format(what=what)},
            {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"},
        ])])
        text = (getattr(res, "content", "") or "").strip()
        _log_response("감시 판독 응답", text)
        return parse_watch_result(text)
    except Exception as e:
        log.exception("감시 판독 실패")
        return {"ok": False, "detected": False, "detail": "",
                "reason": f"{type(e).__name__}: {e}"}


def _watch_notice(cfg: dict, what: str, window: str) -> str:
    """감시 시작 **고지문**. 사용자가 승인 대신 받는 것이 이것이다.

    승인 질문을 붙이지 않기로 한 이상(감시는 멈추면 끝나므로 되돌릴 수 있다),
    **무엇을 얼마나 어떻게 보는지**는 반드시 말해야 한다. 다섯 가지를 다 담는다:
    ① 무엇을 보는지 ② 얼마나 자주 ③ **무엇을 놓칠 수 있는지** ④ 언제 자동으로
    멈추는지 ⑤ 어떻게 멈추는지.

    ⚠️ **③은 2026-09-08에 추가됐다 (BL-22 잔여).** 프리필터가 글자 한두 자(0.29%)를
      커서 깜빡임(0.20%)과 구분하지 못해 못 잡는데, 고지는 *"글자 생기면 알려드릴게요"*
      라고 받고 있었다. **못 하는 것을 할 수 있다고 말한 것**이고, 사용자는 그 말을
      믿고 자리를 뜬다 — 이 프로젝트가 반복해서 데인 «거짓 성공»과 같은 모양이다.
      임계를 더 내리는 대신 **할 수 있는 것만 말하기로** 했다. 임계를 내리면 커서
      깜빡임마다 화면이 외부로 나간다.
    """
    where = f"'{window}' 창" if window else "화면 전체"
    return (
        f"✓ {where}를 지켜볼게요. '{what}'이(가) 보이면 바로 알려드릴게요.\n"
        f"{cfg['interval']}초마다 화면을 확인하고, 변화가 있을 때만 화면을 읽어요.\n"
        "다만 글자 한두 자처럼 아주 작은 변화는 놓칠 수 있어요.\n"
        f"최대 {cfg['max_minutes']}분(화면 읽기 {cfg['max_vision_calls']}회)까지만 보고 "
        "자동으로 멈춰요.\n"
        '그만두려면 "그만 봐"라고 말씀해 주세요.'
    )


@tool
def watch_screen(what: str, window: str = "") -> str:
    """
    화면을 계속 지켜보다가 어떤 일이 생기면 먼저 알려줍니다.
    "오류 뜨면 알려줘", "다운로드 끝나면 알려줘"처럼 앞으로 생길 변화를 알려달라는
    요청에는 이 도구를 호출하세요. 이 도구를 부르지 않으면 아무것도 지켜보지 않습니다.
    (사용자가 요청하지 않았는데 스스로 시작하지는 마세요.)

    what: 알려줄 것 (예: "오류 메시지", "다운로드 완료", "빨간 경고창")
    window: 볼 대상 — 비워두면 전체 화면 / "활성창" / 앱 이름(예: "크롬")
            가능하면 창을 지정하세요. 화면 전체보다 정확하고 덜 노출됩니다.

    한 번에 하나만 지켜볼 수 있고, 정해진 시간·횟수가 지나면 자동으로 멈춥니다.
    """
    from core.screen_monitor import get_monitor

    res = get_monitor().start(what, window)

    if res.get("started"):
        return _watch_notice(res, what.strip(), window.strip())

    reason = res.get("reason")
    if reason == "no_target":
        return '✗ 무엇을 알려드릴지 알려주세요. (예: "오류 뜨면 알려줘")'
    if reason == "disabled":
        return ("✗ 화면 감시가 꺼져 있어 시작하지 않았습니다. "
                "(.env 의 SCREEN_WATCH_ENABLED=true 로 켤 수 있어요)")
    if reason == "already_watching":
        # **새로 시작하지 않았다는 사실을 분명히 말한다.** 두 개가 돌면 화면
        # 전송량이 두 배가 되므로 거절하는 게 맞지만, 거절을 숨기면 안 된다.
        cur = res.get("what", "")
        where = f"'{res.get('window')}' 창에서 " if res.get("window") else ""
        return (f"✗ 이미 {where}'{cur}'을(를) 지켜보는 중이라 새로 시작하지 않았어요. "
                '먼저 "그만 봐"로 멈춘 뒤 다시 말씀해 주세요.')
    return "✗ 화면 감시를 시작하지 못했습니다."


@tool
def stop_watching() -> str:
    """
    진행 중인 화면 감시를 중단합니다.
    사용자가 "그만 봐", "감시 그만", "이제 안 봐도 돼"라고 할 때 사용하세요.
    """
    from core.screen_monitor import get_monitor

    res = get_monitor().stop()
    if not res.get("stopped"):
        return "✓ 지금 지켜보고 있는 건 없어요."
    what = res.get("what", "")
    calls = res.get("vision_calls", 0)
    # ⚠️ "못 봤어요"라고 단정하지 않는다. 멈추는 순간 화면 확인이 진행 중일 수 있고,
    #    그러면 확인할 수 없는 것을 확인한 척하는 셈이 된다. 사실만 적는다.
    return f"✓ '{what}' 감시를 멈췄어요. (그동안 화면을 {calls}번 확인했어요)"
