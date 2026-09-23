"""
Pluiz 키보드 입력 도구
----------------------
포그라운드 앱에 텍스트 입력 및 키 이벤트 전송.

의존성: pyautogui, pyperclip
설치: pip install pyautogui pyperclip
"""

import time
from langchain_core.tools import tool

from core.logger import get_logger

#: 포커스 확인이 **왜 실패했는지**를 셀 수 있게 한다 (감사 G-02 모양).
#: 이 실패는 «엉뚱한 창에 입력했다»의 직전 순간이라 `print` 로 흘리면 안 된다.
_log = get_logger("Input")


# 한국어 키 이름 → pyautogui 키 이름 매핑
_KEY_MAP: dict[str, str] = {
    # 한국어
    "엔터": "enter", "엔터키": "enter",
    "탭": "tab", "탭키": "tab",
    "에스케이프": "escape", "취소": "escape",
    "스페이스": "space", "공백": "space",
    "백스페이스": "backspace", "지우기": "backspace",
    "삭제": "delete", "딜리트": "delete",
    "위": "up", "위쪽": "up",
    "아래": "down", "아래쪽": "down",
    "왼쪽": "left",
    "오른쪽": "right",
    "홈": "home",
    "엔드": "end",
    "페이지업": "pageup",
    "페이지다운": "pagedown",
    "복사": "ctrl+c",
    "붙여넣기": "ctrl+v", "붙이기": "ctrl+v",
    "잘라내기": "ctrl+x",
    "전체선택": "ctrl+a",
    "실행취소": "ctrl+z", "되돌리기": "ctrl+z",
    "저장": "ctrl+s",
    "닫기": "alt+f4",
    # 영문 별칭
    "esc": "escape",
    "enter": "enter",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4",
    "f5": "f5", "f6": "f6", "f7": "f7", "f8": "f8",
    "f9": "f9", "f10": "f10", "f11": "f11", "f12": "f12",
}


def _get_pyautogui():
    try:
        import pyautogui
        pyautogui.FAILSAFE = True   # 화면 모서리로 마우스 이동 시 중단
        pyautogui.PAUSE = 0.05
        return pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui가 설치되지 않았습니다. "
            "터미널에서 'pip install pyautogui pyperclip' 실행 후 재시도하세요."
        )


def _get_pyperclip():
    try:
        import pyperclip
        return pyperclip
    except ImportError:
        raise ImportError(
            "pyperclip이 설치되지 않았습니다. "
            "터미널에서 'pip install pyperclip' 실행 후 재시도하세요."
        )


def _foreground_window() -> tuple[int, str]:
    """현재 포그라운드 창의 (hwnd, 제목). 확인 못 하면 (0, "")."""
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return (0, "")
        n = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        return (int(hwnd), buf.value or "")
    except Exception:
        return (0, "")


def _ensure_target_focused(target: str) -> tuple[bool, str]:
    """target 앱 창이 실제로 앞에 와 있는가. (진행해도 되는가, 거부 사유)

    ⚠️ **이게 BL-12의 핵심이다.** `pyautogui`는 지정한 창이 아니라 **그때 포커스된
    창**에 키를 보낸다. 대상이 앞에 없는데 입력하면 사용자가 보고 있던 엉뚱한 창에
    글자가 들어간다. 2026-09-03 실기에서 실제로 그랬다 — *"메모장에 회의록 적어줘"*
    라고 했는데 **Pluiz 오버레이 입력창**에 "회의록"이 들어갔고, 도구는 `"✓ 입력 완료"`
    라고 답했다.

    그래서 **확인이 안 되면 입력하지 않는다.** 잘못 들어간 글자는 되돌릴 수 없다.
    창 조회·포커스는 `tools/app_control.py`의 것을 재사용한다 — 여기서 따로 구현하면
    앱 별칭("메모장"→notepad) 해석이 어긋난다.
    """
    try:
        from tools.app_control import find_hwnd_for_app, _focus_window, _normalize
    except Exception as e:
        # 확인할 수단이 없으면 막지는 않는다(예전 동작). 다만 조용히 넘어가지 않는다.
        _log.error("[포커스] 대상 창 확인 불가(그대로 진행) | %r | %s: %s",
                   target, type(e).__name__, e)
        return (True, "")

    hwnd = find_hwnd_for_app(target)
    if not hwnd:
        return (False, f"✗ '{target}' 창을 찾을 수 없어 입력하지 않았습니다. "
                       f"먼저 {target}을(를) 열어주세요.")

    fg, _title = _foreground_window()
    if fg and fg == hwnd:
        return (True, "")

    # 앞에 없으면 한 번 가져와 본다
    try:
        _focus_window(_normalize(target))
    except Exception as e:
        _log.warning("[포커스] 앞으로 가져오기 실패 | %r | %s: %s",
                     target, type(e).__name__, e)
    time.sleep(0.25)

    fg, title = _foreground_window()
    if fg and fg == hwnd:
        return (True, "")
    where = f"'{title}' 창" if title else "다른 창"
    return (False, f"✗ '{target}' 창을 앞으로 가져오지 못해 입력하지 않았습니다. "
                   f"지금 앞에 있는 건 {where}라서, 그대로 입력하면 거기에 글자가 "
                   f"들어갔을 거예요.")


@tool
def type_text(text: str, target: str = "") -> str:
    """
    지정한 앱 창에 텍스트를 입력한다.
    한국어, 영어, 특수문자 모두 지원.
    예: 메모장에 'Hello 안녕' 입력, 검색창에 키워드 입력.

    Args:
        text: 입력할 텍스트 (한국어 포함 가능)
        target: 어느 앱 창에 넣을지 (예: "메모장", "크롬"). **어디에 넣을지 알면
                반드시 지정하세요.** 지정하면 그 창이 실제로 앞에 와 있는지 확인한
                뒤에만 입력하고, 확인이 안 되면 입력하지 않고 그 사실을 알립니다.
                비워두면 현재 앞에 있는 창에 입력합니다.
    """
    try:
        pyperclip = _get_pyperclip()
        pyautogui = _get_pyautogui()

        # ── 대상 창 확인 (BL-12) — 입력 '전에' 한다 ──────────────
        if target.strip():
            ok, reason = _ensure_target_focused(target.strip())
            if not ok:
                return reason          # ⚠️ 입력하지 않고 끝낸다

        # 클립보드에 복사 후 Ctrl+V 붙여넣기 (한국어 안전 처리)
        original_clipboard = ""
        try:
            original_clipboard = pyperclip.paste()
        except Exception:
            pass

        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)

        # 클립보드 원복 (선택사항 — 사용자 클립보드 보호)
        try:
            pyperclip.copy(original_clipboard)
        except Exception:
            pass

        # **어느 창에 들어갔는지 함께 보고한다.** 예전엔 "✓ 입력 완료"만 말해서,
        # 엉뚱한 창에 들어가도 사용자가 알 방법이 없었다.
        preview = f"{text[:30]}{'...' if len(text) > 30 else ''}"
        _, title = _foreground_window()
        if title:
            return f"✓ '{title}' 창에 입력했습니다: '{preview}'"
        return f"✓ 텍스트 입력 완료: '{preview}'"
    except ImportError as e:
        return f"✗ 글자를 입력하지 못했습니다: {e}"
    except Exception as e:
        return f"✗ 글자를 입력하지 못했습니다: {type(e).__name__}: {e}"


@tool
def get_clipboard_text() -> str:
    """
    현재 클립보드에 복사된 텍스트를 읽어 반환한다.
    '클립보드에 뭐 있어?', '복사한 내용 알려줘', '클립보드 내용 보여줘' 같은 요청에 사용.
    최대 200자까지 미리보기로 반환하고, 초과 시 길이도 함께 알려줌.
    """
    try:
        pyperclip = _get_pyperclip()
        content = pyperclip.paste()
        if not content or not content.strip():
            return "클립보드가 비어있거나 텍스트가 없어요."
        preview = content[:200]
        suffix = f"... (총 {len(content)}자)" if len(content) > 200 else ""
        return f"📋 클립보드 내용:\n{preview}{suffix}"
    except ImportError as e:
        return f"✗ 클립보드를 읽지 못했습니다: {e}"
    except Exception as e:
        return f"✗ 클립보드를 읽지 못했습니다: {type(e).__name__}: {e}"


@tool
def press_key(key: str, target: str = "") -> str:
    """
    키보드 키 입력. 단일 키 또는 단축키 지원.
    한국어 키 이름도 인식함.

    예:
    - 'enter' 또는 '엔터' → Enter 키
    - 'ctrl+s' 또는 '저장' → Ctrl+S
    - 'escape' 또는 '에스케이프' → Esc
    - 'f5' → F5

    Args:
        key: 키 이름 또는 단축키 (예: 'enter', 'ctrl+c', '엔터')
        target: 어느 앱 창에 보낼지 (예: "메모장", "크롬"). **어디에 보낼지 알면
                반드시 지정하세요.** 지정하면 그 창이 실제로 앞에 와 있는지 확인한
                뒤에만 누르고, 확인이 안 되면 **누르지 않고** 그 사실을 알립니다.
                비워두면 지금 앞에 있는 창에 갑니다.
    """
    # ── 🚨 감사 G-09 — BL-12의 수선을 여기는 못 받았다 ──────────────
    #
    # BL-12은 `type_text` 에 `_ensure_target_focused()` 를 넣어 *«확인이 안 되면
    # 입력하지 않는다»* 로 고쳤다. **`press_key` 는 그대로였다.**
    #   · `target` 인자 자체가 없어 **어디로 가는지 모르고 눌렀고**
    #   · 어느 창에 갔는지 **말하지도 않았다**(`type_text` 는 말한다)
    #   · `alt+f4`·`ctrl+s`·`ctrl+w` 가 **엉뚱한 창에서** 눌리면 되돌릴 수 없다
    #
    # 🔑 BL-12의 실기 사고가 정확히 이것이었다 — 글자가 **Pluiz 오버레이 입력창**에
    #   들어갔다. `pyautogui` 는 «그때 포커스된 창»에 보내므로 **키도 같은 길로 간다.**
    #
    # ⚠️ `target` 을 **필수로 만들지는 않았다.** *"엔터 눌러줘"* 처럼 «지금 이 창»이
    #   맞는 경우가 실제로 많고, 필수로 하면 그 평범한 명령이 전부 막힌다.
    #   대신 **어디로 갔는지 항상 말한다** — 그러면 틀렸을 때 사용자가 안다.
    try:
        pyautogui = _get_pyautogui()

        if target.strip():
            ok, reason = _ensure_target_focused(target.strip())
            if not ok:
                # 🚨 누르지 않고 끝낸다. 문구의 «입력»을 «키»로 바꿔 준다 —
                #   같은 함수가 두 도구를 지키므로 말만 도구에 맞춘다.
                return reason.replace("입력하지 않았습니다", "키를 누르지 않았습니다")

        normalized = key.strip().lower()
        actual_key = _KEY_MAP.get(normalized, normalized)

        # 단축키 처리 (ctrl+s, alt+f4 등)
        if "+" in actual_key:
            parts = [p.strip() for p in actual_key.split("+")]
            pyautogui.hotkey(*parts)
        else:
            pyautogui.press(actual_key)

        # **어느 창에 갔는지 함께 보고한다.** 예전엔 "✓ 키 입력 완료"뿐이라
        # 엉뚱한 창에서 눌려도 사용자가 알 방법이 없었다.
        _, title = _foreground_window()
        if title:
            return f"✓ '{title}' 창에서 '{key}' 키를 눌렀습니다."
        return f"✓ '{key}' 키 입력 완료"
    except ImportError as e:
        return f"✗ 키를 누르지 못했습니다: {e}"
    except Exception as e:
        return f"✗ 키를 누르지 못했습니다: {type(e).__name__}: {e}"


# ── 좌표 기반 클릭 (Phase 2) ──────────────────────────────────────
#
# ⚠️ **이 도구는 좌표를 인자로 받지 않는다.** 일부러 그렇게 만들었다.
#    LLM이 좌표를 넘길 수 있으면 언젠가 지어낸다. 그러면 "틀린 좌표를 정확히
#    클릭하는" 도구가 되고, 클릭은 되돌릴 수 없다. 그래서 찾기와 누르기를 한 도구
#    안에 묶어, 좌표는 항상 `locate_ui_element`가 방금 화면을 보고 계산한 값만 쓴다.
#
# ⚠️ 실행 전 `hitl` 노드가 사용자 승인을 받는다 (core/graph.py DANGEROUS_TOOLS).

def _click_guard(loc: dict, window: str) -> str:
    """클릭해도 되는 좌표인가. 문제가 있으면 사유(문자열), 괜찮으면 "".

    화면 밖이거나 대상 창 밖이면 누르지 않는다. Vision이 틀린 좌표를 줬을 때
    **눈에 띄게 틀린 것만이라도** 걸러내려는 최소한의 그물이다.
    """
    x, y = loc["center"]

    # 1) 가상 화면(다중 모니터 포함) 안인가
    try:
        import ctypes
        u = ctypes.windll.user32
        vx = u.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        vy = u.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        vw = u.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        vh = u.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        if vw > 0 and vh > 0 and not (vx <= x < vx + vw and vy <= y < vy + vh):
            return f"좌표 ({x}, {y})가 화면 밖입니다"
    except Exception as e:
        print(f"[click] 화면 범위 확인 생략(무시): {type(e).__name__}: {e}")

    # 2) 대상 창이 **캡처 때와 같은 자리**에 있는가
    #    좌표는 캡처 시점의 창 위치를 기준으로 계산됐다. 그 사이 창이 움직였으면
    #    그 좌표는 더 이상 그 요소를 가리키지 않는다.
    rect = loc.get("window_rect")
    if window and rect:
        try:
            from tools.system import resolve_window_hwnd, window_screen_rect
            hwnd, _ = resolve_window_hwnd(window)
            if not hwnd:
                return f"'{window}' 창이 사라졌습니다"
            if window_screen_rect(hwnd) != tuple(rect):
                return f"'{window}' 창이 그 사이 움직여서 좌표가 맞지 않습니다"
        except Exception as e:
            print(f"[click] 창 이동 확인 생략(무시): {type(e).__name__}: {e}")

        left, top, w, h = rect
        if not (left <= x < left + w and top <= y < top + h):
            return f"좌표 ({x}, {y})가 '{window}' 창 밖입니다"
    return ""


@tool
def click_ui_element(target: str, window: str = "") -> str:
    """
    화면에서 버튼·메뉴 같은 요소를 찾아 **마우스로 클릭**합니다.
    사용자가 "저장 버튼 눌러줘", "확인 클릭해줘"처럼 요청할 때 사용하세요.

    target: 누를 것 (예: "저장 버튼", "확인", "닫기 X 버튼")
    window: 어느 창에서 찾을지 — 비워두면 전체 화면 / "활성창" / 앱 이름

    화면에서 못 찾으면 아무 데도 클릭하지 않습니다.
    좌표는 이 도구가 직접 화면을 보고 정하며, 좌표를 인자로 받지 않습니다.
    """
    try:
        pyautogui = _get_pyautogui()
    except ImportError as e:
        return f"✗ 클릭하지 못했습니다: {e}"

    try:
        from tools.vision import locate_ui_element
    except Exception as e:
        return f"✗ 화면 분석 기능을 불러오지 못해 클릭하지 않았습니다: {e}"

    loc = locate_ui_element(target, window)
    if not loc.get("found"):
        # 못 찾았으면 **아무 데도 누르지 않는다.** 중앙을 누른다든지 하면 안 된다.
        return (f"✗ 화면에서 '{target}'을(를) 찾지 못해 클릭하지 않았습니다. "
                f"({loc.get('reason', '알 수 없음')})")

    problem = _click_guard(loc, window)
    if problem:
        return f"✗ {problem}. 안전을 위해 클릭하지 않았습니다."

    x, y = loc["center"]
    try:
        before = pyautogui.position()
    except Exception:
        before = None
    try:
        pyautogui.click(x, y)
    except Exception as e:
        return f"✗ 클릭하지 못했습니다: {type(e).__name__}: {e}"
    finally:
        # 마우스를 원래 자리로 돌려놓는다 — 사용자가 쓰던 위치를 뺏지 않는다
        if before is not None:
            try:
                pyautogui.moveTo(before[0], before[1])
            except Exception:
                pass

    # 클릭했다는 것과 **의도한 효과가 났다는 것은 다르다.** 지어내지 않는다.
    return (f"✓ '{loc['label']}'을(를) 화면 ({x}, {y})에서 클릭했습니다. "
            f"원하는 대로 됐는지는 화면을 확인해 주세요.")
