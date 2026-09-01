"""
Pluiz 키보드 입력 도구
----------------------
포그라운드 앱에 텍스트 입력 및 키 이벤트 전송.

의존성: pyautogui, pyperclip
설치: pip install pyautogui pyperclip
"""

import time
from langchain_core.tools import tool


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


@tool
def type_text(text: str) -> str:
    """
    현재 포그라운드(활성) 앱에 텍스트를 입력한다.
    한국어, 영어, 특수문자 모두 지원.
    예: 메모장에 'Hello 안녕' 입력, 검색창에 키워드 입력.

    Args:
        text: 입력할 텍스트 (한국어 포함 가능)
    """
    try:
        pyperclip = _get_pyperclip()
        pyautogui = _get_pyautogui()

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

        return f"✓ 텍스트 입력 완료: '{text[:30]}{'...' if len(text) > 30 else ''}'"
    except ImportError as e:
        return f"[오류] {e}"
    except Exception as e:
        return f"[type_text 오류] {type(e).__name__}: {e}"


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
        return f"[오류] {e}"
    except Exception as e:
        return f"[get_clipboard_text 오류] {type(e).__name__}: {e}"


@tool
def press_key(key: str) -> str:
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
    """
    try:
        pyautogui = _get_pyautogui()

        normalized = key.strip().lower()
        actual_key = _KEY_MAP.get(normalized, normalized)

        # 단축키 처리 (ctrl+s, alt+f4 등)
        if "+" in actual_key:
            parts = [p.strip() for p in actual_key.split("+")]
            pyautogui.hotkey(*parts)
        else:
            pyautogui.press(actual_key)

        return f"✓ '{key}' 키 입력 완료"
    except ImportError as e:
        return f"[오류] {e}"
    except Exception as e:
        return f"[press_key 오류] {type(e).__name__}: {e}"
