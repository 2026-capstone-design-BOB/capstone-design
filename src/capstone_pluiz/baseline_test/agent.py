# baseline_test/agent.py
# 프롬프트 최적화, 캐싱, 보안 모듈 없이
# 순수 Gemini API 호출만으로 명령 분류

import os
import json
import re
from dotenv import load_dotenv
from google import genai

load_dotenv()

# 최소한의 프롬프트 - few-shot 예시, 구어체 규칙, 상세 설명 없음
BASELINE_PROMPT = """
사용자의 PC 제어 명령을 분석해서 아래 JSON 형식으로만 답해줘.
{"type": "유형", "action": "동작", "params": {}}

type은 local, web, interpreter, system, unknown 중 하나야.
"""

class BaselineAgent:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            print("[BaselineAgent] GEMINI_API_KEY 없음")
            self.available = False
            return
        self.client = genai.Client(api_key=api_key)
        self.model_id = "gemini-2.5-flash-lite"
        self.available = True
        print(f"[BaselineAgent] Gemini ({self.model_id}) 초기화 완료")

    def analyze_command(self, user_input: str) -> dict:
        if not self.available:
            return {"type": "unknown", "action": "unknown", "params": {}}
        try:
            prompt = f"{BASELINE_PROMPT}\n\n입력: {user_input}"
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            return self._parse_json(response.text.strip())
        except Exception as e:
            print(f"[BaselineAgent] 오류: {e}")
            return {"type": "error", "action": "error", "params": {}, "raw": str(e)}

    def _parse_json(self, text: str) -> dict:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        return {"type": "unknown", "action": "unknown", "params": {}, "raw": text}
