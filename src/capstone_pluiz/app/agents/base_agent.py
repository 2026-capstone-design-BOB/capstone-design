# app/agents/base_agent.py
from abc import ABC, abstractmethod
import json
import re

# ── 오프라인 폴백 설정 ────────────────────────────────────────────
# _call_llm()은 Ollama 직접 호출용 (경량 텍스트 응답만 필요한 경우)
# 코드 생성+실행 전체 폴백은 OfflineExecutor(Open Interpreter)가 담당
# → InterpreterExecutor에서 분기

OLLAMA_BASE_URL    = "http://localhost:11434"
OLLAMA_MODEL_NAME  = "llama3:latest"   # ollama list 기준

# 폴백을 트리거하는 오류 키워드
# "일시적 오류"(429 rate limit)는 포함하지 않음 → InterpreterExecutor 재시도가 담당
# "완전 불가" 오류만 폴백 대상
FALLBACK_TRIGGERS = (
    "connection",    # 네트워크 끊김 (진짜 오프라인)
    "api_key",       # 키 오류
    "permission",    # 권한 오류
)

# 일시적 오류 — 폴백 아닌 재시도 대상 (잠깐 기다리면 해결됨)
TRANSIENT_TRIGGERS = (
    "quota",         # 429 quota 초과
    "rate",          # rate limit
    "resource_exhausted",
    "unavailable",   # 503 일시적 과부하
    "overloaded",    # 서버 과부하
    "timeout",       # 타임아웃 (일시적)
)
# ─────────────────────────────────────────────────────────────────


class BaseAgent(ABC):
    """
    모든 에이전트의 추상 클래스.
    Gemini / Claude / OpenAI / Ollama 모두 _call_llm() 하나로 통일.

    폴백 정책:
      일시적 오류(429 등) → 재시도만 (InterpreterExecutor가 처리)
      완전 불가 오류      → _call_llm()에서 Ollama로 전환
      코드 생성+실행 폴백 → OfflineExecutor (InterpreterExecutor 레벨)
    """

    def _init_client(self, provider: str, model_id: str):
        self.provider  = provider
        self.model_id  = model_id
        self.available = False

        if provider == "gemini":
            from config.settings import GEMINI_API_KEY
            if not GEMINI_API_KEY:
                print(f"[{self.__class__.__name__}] GEMINI_API_KEY 없음 → 오프라인 폴백 대기")
                return
            from google import genai
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            self.available = True

        elif provider == "claude":
            from config.settings import CLAUDE_API_KEY
            if not CLAUDE_API_KEY:
                print(f"[{self.__class__.__name__}] CLAUDE_API_KEY 없음 → 오프라인 폴백 대기")
                return
            import anthropic
            self.client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            self.available = True

        elif provider == "openai":
            from config.settings import OPENAI_API_KEY
            if not OPENAI_API_KEY:
                print(f"[{self.__class__.__name__}] OPENAI_API_KEY 없음 → 오프라인 폴백 대기")
                return
            from openai import OpenAI
            self.client = OpenAI(api_key=OPENAI_API_KEY)
            self.available = True

        elif provider == "ollama":
            self.client = None
            self.available = True

        else:
            print(f"[{self.__class__.__name__}] 알 수 없는 provider: {provider}")
            return

        if provider != "ollama":
            print(f"[{self.__class__.__name__}] {provider} ({model_id}) 초기화 완료")

    def _call_ollama(self, prompt: str) -> str:
        """Ollama 직접 호출 — 경량 텍스트 응답용."""
        import requests as _req
        resp = _req.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL_NAME, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()

    def _is_permanent_failure(self, error: Exception) -> bool:
        """완전 불가 오류인지 판단 — 폴백 트리거."""
        msg       = str(error).lower()
        type_name = type(error).__name__.lower()
        combined  = msg + " " + type_name
        return any(t in combined for t in FALLBACK_TRIGGERS)

    def _is_transient_error(self, error: Exception) -> bool:
        """일시적 오류인지 판단 — 재시도 대상, 폴백 아님."""
        msg = str(error).lower()
        return any(t in msg for t in TRANSIENT_TRIGGERS)

    def _call_llm(self, prompt: str) -> str:
        """
        provider에 관계없이 텍스트 응답 반환.

        available=False (키 없음)    → Ollama 직접 호출
        완전 불가 오류 발생           → Ollama 직접 호출
        일시적 오류 (429 등)          → 그대로 예외 올림 (InterpreterExecutor 재시도)
        Ollama도 실패                 → 원래 예외 올림
        """
        if not self.available:
            print(f"[{self.__class__.__name__}] API 불가 → Ollama 폴백")
            return self._call_ollama(prompt)

        try:
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

            elif self.provider == "ollama":
                return self._call_ollama(prompt)

        except Exception as e:
            if self._is_transient_error(e):
                # 429 등 일시적 오류 → 재시도 대상, 폴백 안 함
                raise

            if self._is_permanent_failure(e):
                print(f"[{self.__class__.__name__}] API 완전 불가 → Ollama 폴백: {type(e).__name__}")
                try:
                    return self._call_ollama(prompt)
                except Exception as ollama_err:
                    print(f"[{self.__class__.__name__}] Ollama도 실패: {ollama_err}")
                    raise e  # 원래 에러 올림 → InterpreterExecutor가 오프라인 분기 판단

            raise  # 그 외 오류는 그대로

    def _parse_json(self, text: str) -> dict | list:
        # 1. 배열 먼저 시도
        list_match = re.search(r'\[.*\]', text, re.DOTALL)
        if list_match:
            try:
                parsed = json.loads(list_match.group())
                if isinstance(parsed, list) and parsed:
                    return parsed
            except:
                pass

        # 2. 단일 객체
        dict_match = re.search(r'\{.*\}', text, re.DOTALL)
        if dict_match:
            try:
                return json.loads(dict_match.group())
            except:
                pass

        # 3. 배열 괄호 없이 쉼표로 구분된 JSON 오브젝트들
        objects = re.findall(r'\{[^{}]+\}', text, re.DOTALL)
        valid = []
        for o in objects:
            try:
                parsed = json.loads(o)
                if isinstance(parsed, dict) and "type" in parsed and "action" in parsed:
                    valid.append(parsed)
            except:
                pass
        if len(valid) > 1:
            return valid
        elif len(valid) == 1:
            return valid[0]

        return {"type": "unknown", "action": "unknown", "params": {}, "raw": text}

    @abstractmethod
    def analyze_command(self, user_input: str) -> dict | list:
        pass