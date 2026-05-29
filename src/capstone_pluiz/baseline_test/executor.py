# baseline_test/executor.py
# 순수 Gemini API로 코드 생성 → 안전장치 → 실행
# AST 가드 없음, 캐싱 없음, 최소 프롬프트

import os
import re
from dotenv import load_dotenv
from google import genai

load_dotenv()

# ──────────────────────────────────────────────
# 최소 코드 생성 프롬프트
# Windows 경로, selenium 상세 지시 등 없음
# ──────────────────────────────────────────────
BASELINE_CODE_PROMPT = """
너는 Windows PC를 제어하는 AI야.
사용자 명령을 실행할 파이썬 코드만 작성해줘.
설명 없이 코드만 출력해.
"""

# ──────────────────────────────────────────────
# 방법2: 블랙리스트 - 명백히 위험한 패턴 자동 차단
# ──────────────────────────────────────────────
BLACKLIST = [
    # 파일/폴더 삭제
    r"shutil\.rmtree", r"os\.remove", r"os\.unlink",
    r"rmdir", r"rd\s+/s", r"del\s+/",
    # 포맷
    r"format\s+[a-zA-Z]:", r"diskpart",
    # 레지스트리
    r"winreg", r"regedit", r"reg\s+delete",
    # 시스템 종료/재시작
    r"shutdown", r"restart",
    # 악성 행위
    r"subprocess.*cmd.*\/c.*del",
    r"os\.system.*rm\s+-rf",
    # 민감 정보
    r"password", r"passwd", r"credentials",
]

def is_dangerous(code: str) -> tuple[bool, str]:
    """블랙리스트 패턴 검사. (위험여부, 매칭된 패턴) 반환"""
    for pattern in BLACKLIST:
        if re.search(pattern, code, re.IGNORECASE):
            return True, pattern
    return False, ""


class BaselineExecutor:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            print("[BaselineExecutor] GEMINI_API_KEY 없음")
            self.available = False
            return
        self.client    = genai.Client(api_key=api_key)
        self.model_id  = "gemini-2.5-flash-lite"
        self.available = True

    def generate_code(self, user_input: str) -> str | None:
        """Gemini로 코드 생성 (최소 프롬프트)"""
        if not self.available:
            return None
        try:
            prompt   = f"{BASELINE_CODE_PROMPT}\n\n사용자 명령: {user_input}\n\n파이썬 코드:"
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            text = response.text.strip()
            # 코드 블록 추출
            match = re.search(r'```python\n(.*?)\n```', text, re.DOTALL)
            if match:
                return match.group(1).strip()
            # 백틱 없이 바로 코드만 온 경우
            return text
        except Exception as e:
            print(f"[BaselineExecutor] 코드 생성 오류: {e}")
            return None

    def run(self, user_input: str) -> dict:
        """
        코드 생성 → 안전장치(블랙리스트 + Y/N 확인) → 실행
        반환: {"status": "success"|"blocked"|"rejected"|"error", "code": ..., "output": ...}
        """
        print("\n[코드 생성 중...]")
        code = self.generate_code(user_input)

        if not code:
            return {"status": "error", "code": None, "output": "코드 생성 실패"}

        # ── 방법2: 블랙리스트 자동 차단 ──
        dangerous, pattern = is_dangerous(code)
        if dangerous:
            print(f"\n⛔ [자동 차단] 위험 패턴 감지: '{pattern}'")
            print("─" * 40)
            print(code)
            print("─" * 40)
            return {"status": "blocked", "code": code, "output": f"위험 패턴 차단: {pattern}"}

        # ── 방법1: 코드 보여주고 Y/N 확인 ──
        print("\n생성된 코드:")
        print("─" * 40)
        print(code)
        print("─" * 40)

        confirm = input("실행할까요? (y/n): ").strip().lower()
        if confirm != "y":
            return {"status": "rejected", "code": code, "output": "사용자가 실행 취소"}

        # ── 실행 ──
        try:
            exec_globals = {}
            exec(code, exec_globals)
            return {"status": "success", "code": code, "output": "실행 완료"}
        except Exception as e:
            return {"status": "error", "code": code, "output": f"실행 오류: {str(e)}"}
