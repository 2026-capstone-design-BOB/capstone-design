# app/agents/base_agent.py
from abc import ABC, abstractmethod
import json
import re

class BaseAgent(ABC):
    """
    모든 에이전트의 추상 클래스.
    Gemini / Claude / OpenAI 모두 _call_llm() 하나로 통일.
    """

    def _init_client(self, provider: str, model_id: str):
        """각 agent __init__에서 호출. provider에 맞는 클라이언트 셋업."""
        self.provider  = provider
        self.model_id  = model_id
        self.available = False

        if provider == "gemini":
            from config.settings import GEMINI_API_KEY
            if not GEMINI_API_KEY:
                print(f"[{self.__class__.__name__}] GEMINI_API_KEY 없음")
                return
            from google import genai
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            self.available = True

        elif provider == "claude":
            from config.settings import CLAUDE_API_KEY
            if not CLAUDE_API_KEY:
                print(f"[{self.__class__.__name__}] CLAUDE_API_KEY 없음")
                return
            import anthropic
            self.client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            self.available = True

        elif provider == "openai":
            from config.settings import OPENAI_API_KEY
            if not OPENAI_API_KEY:
                print(f"[{self.__class__.__name__}] OPENAI_API_KEY 없음")
                return
            from openai import OpenAI
            self.client = OpenAI(api_key=OPENAI_API_KEY)
            self.available = True

        else:
            print(f"[{self.__class__.__name__}] 알 수 없는 provider: {provider}")
            return

        print(f"[{self.__class__.__name__}] {provider} ({model_id}) 초기화 완료")

    def _call_llm(self, prompt: str) -> str:
        """provider에 관계없이 텍스트 응답을 반환."""
        if self.provider == "gemini":
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            return response.text.strip()

        elif self.provider == "claude":
            message = self.client.messages.create(
                model=self.model_id,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text.strip()

        elif self.provider == "openai":
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()

    def _parse_json(self, text: str) -> dict:
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        return {"type": "unknown", "action": "unknown", "params": {}, "raw": text}

    @abstractmethod
    def analyze_command(self, user_input: str) -> dict:
        pass