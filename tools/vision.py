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
import os
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
