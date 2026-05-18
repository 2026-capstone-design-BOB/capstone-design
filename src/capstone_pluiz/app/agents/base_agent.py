# app/agents/base_agent.py
# 모든 Agent들의 공통 툴
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    """
    모든 에이전트의 추상 클래스
    Claude, GPT, Gemini, Ollama 모두 이 틀을 따름
    """
    
    @abstractmethod
    def analyze_command(self, user_input: str) -> dict:
        """
        사용자 명령을 분석해서 JSON으로 반환
        모든 에이전트는 반드시 이 메서드를 구현해야 함
        """
        pass
    
    def _parse_json(self, text: str) -> dict:
        """
        LLM 응답에서 JSON 추출
        공통으로 쓰이니까 여기 넣어둠
        """
        import json
        import re
        
        # JSON 블록 추출 시도
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        # 실패하면 unknown 반환
        return {
            "type": "unknown",
            "action": "unknown", 
            "params": {},
            "raw": text
        }