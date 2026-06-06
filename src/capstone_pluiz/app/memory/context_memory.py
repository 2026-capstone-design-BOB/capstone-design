# app/memory/context_memory.py
# 대화 맥락 메모리 — 히스토리 저장 + 맥락 지시어 해석
# 처리 우선순위: 패턴 매칭(코드) → 상태 추적(코드) → LLM 추론(API)

import sqlite3
import json
import os
import re
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "context_memory.db")

# ── 맥락 지시어 패턴 ──────────────────────────────────────────────
REPEAT_PATTERNS = [
    r"다시\s*해\s*줘", r"또\s*해\s*줘", r"반복\s*해\s*줘", r"똑같이\s*해\s*줘",
    r"다시\s*실행", r"한\s*번\s*더", r"다시\s*해\s*달라",
    r"^다시$", r"^또$", r"^반복$",           # 단독 입력
    r"다시\s*한\s*번", r"한\s*번\s*더\s*해", # 추가 표현
]
REF_PATTERNS = [
    r"그거", r"이거", r"그것", r"이것", r"그\s*앱", r"그\s*파일",
    r"방금\s*(?:열었던|실행한|한)\s*거", r"아까\s*(?:그거|열었던|한\s*거)"
]
HISTORY_PATTERNS = [
    r"아까\s*뭐\s*했(?:어|냐|나)",
    r"방금\s*뭐\s*했(?:어|냐|나)",
    r"지금\s*뭐\s*했(?:어|냐|나)",      # 추가
    r"최근에\s*뭐\s*했(?:어|냐|나)",    # 추가
    r"이전\s*명령",
    r"직전\s*명령",
]

# ── TODO: [확장 포인트] ────────────────────────────────────────────
# 1. 압축 (토큰 절약)
#    히스토리 N개 초과 시 오래된 것을 LLM으로 요약 → summary 컬럼에 저장
#    구현 위치: _compress_history()
#
# 2. 개인화 메모리
#    자주 쓰는 앱/파일/검색어 패턴 학습 → user_preferences 테이블
#    구현 위치: app/memory/personal_memory.py
#
# 3. 세션 관리
#    앱 재시작 시 이전 세션 히스토리 로드 여부 선택
#    현재는 매번 전체 히스토리 유지
#
# 4. 히스토리 조회 명령 처리
#    "아까 뭐 했어?" → 히스토리 요약 반환 (현재 미구현)
# ─────────────────────────────────────────────────────────────────


class ContextMemory:
    def __init__(self, history_limit: int = 10):
        """
        history_limit: 프롬프트에 주입할 최근 히스토리 개수
                       LLM 추론 시 사용, 토큰 절약을 위해 제한
        """
        self.history_limit = history_limit
        self._init_db()

        # 상태 추적 변수 (메모리 내)
        self.last_app: str | None = None       # 예) "notepad", "chrome"
        self.last_file: str | None = None      # 예) "test.txt"
        self.last_action: str | None = None    # 예) "open_app", "create_file"
        self.last_command: dict | None = None  # 직전 command 전체

        print("[ContextMemory] 초기화 완료")

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS command_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_input  TEXT NOT NULL,
                    command     TEXT NOT NULL,
                    result      TEXT,
                    timestamp   TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    # ── 저장 ──────────────────────────────────────────────────────

    def save(self, user_input: str, command: dict, result: dict):
        """실행 완료 후 호출 — 히스토리 저장 + 상태 업데이트"""
        # DB 저장
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO command_history (user_input, command, result)
                VALUES (?, ?, ?)
            """, (
                user_input,
                json.dumps(command, ensure_ascii=False),
                json.dumps(result,  ensure_ascii=False),
            ))
            conn.commit()

        # 상태 추적 업데이트
        self._update_state(command)

    def _update_state(self, command: dict):
        self.last_command = command
        self.last_action  = command.get("action", "")
        params = command.get("params", {})

        if "app" in params:
            self.last_app  = params["app"]
            self.last_file = None        # 앱 명령이면 파일 참조 초기화
        if "name" in params:
            self.last_file = params["name"]
            self.last_app  = None        # 파일 명령이면 앱 참조 초기화
        elif "file" in params:
            self.last_file = params["file"]
            self.last_app  = None

    # ── 맥락 해석 — 핵심 메서드 ──────────────────────────────────

    def resolve(self, user_input: str) -> dict | None:
        """
        맥락 지시어가 있으면 해석해서 command 반환.
        해석 불가하면 None 반환 → 호출자가 일반 분류로 진행.

        처리 순서:
          1. 반복 패턴 ("다시 해줘")
          2. 참조 패턴 ("그거 닫아줘")
          3. 히스토리 조회 ("아까 뭐 했어?")
          4. LLM 추론 (1~3 실패 시)
        """
        # 1단계: 반복 패턴
        result = self._resolve_repeat(user_input)
        if result:
            if result.get("_skip_llm"):   # 이전 명령 없음 — LLM도 건너뜀
                return None
            print(f"[ContextMemory] 반복 패턴 감지 → {result}")
            return result

        # 2단계: 참조 패턴
        result = self._resolve_reference(user_input)
        if result:
            print(f"[ContextMemory] 참조 패턴 감지 → {result}")
            return result

        # 3단계: 히스토리 조회 패턴
        result = self._resolve_history_query(user_input)
        if result:
            print(f"[ContextMemory] 히스토리 조회 감지 → {result}")
            return result

        # 4단계: LLM 추론 (맥락 지시어가 있는데 1~3으로 못 잡은 경우)
        if self._has_context_hint(user_input) and (self.last_app or self.last_file):
            result = self._resolve_with_llm(user_input)
            if result:
                print(f"[ContextMemory] LLM 추론 → {result}")
                return result

        return None

    # ── 1단계: 반복 패턴 ─────────────────────────────────────────

    def _resolve_repeat(self, user_input: str) -> dict | None:
        """'다시 해줘', '또 해줘' → last_command 그대로 반환"""
        for pattern in REPEAT_PATTERNS:
            if re.search(pattern, user_input):
                if self.last_command:
                    return self.last_command
                else:
                    print("[ContextMemory] 반복 요청이나 이전 명령 없음")
                    return {"_skip_llm": True}  # LLM 단계 건너뛰기 신호
        return None

    # ── 2단계: 참조 패턴 ─────────────────────────────────────────

    def _resolve_reference(self, user_input: str) -> dict | None:
        """
        '그거 닫아줘' → last_app으로 close_app 명령 생성
        '그거 열어줘' → last_app으로 open_app 명령 생성
        """
        has_ref = any(re.search(p, user_input) for p in REF_PATTERNS)
        if not has_ref:
            return None

        # 동작 키워드 추출
        action = self._extract_action_keyword(user_input)
        if not action:
            return None

        # 대상 결정: 앱 우선, 없으면 파일
        if self.last_app and action in ("close_app", "open_app", "maximize_window",
                                         "minimize_window"):
            return {
                "type": "local",
                "action": action,
                "params": {"app": self.last_app},
                "_from_context": True
            }

        if self.last_file and action in ("open_file", "delete_file"):
            return {
                "type": "interpreter",
                "action": action,
                "params": {"name": self.last_file},
                "_from_context": True
            }

        return None

    def _extract_action_keyword(self, user_input: str) -> str | None:
        """입력에서 동작 키워드 추출"""
        mappings = [
            (r"닫아|꺼줘|종료",        "close_app"),
            (r"열어|켜줘|실행|띄워",    "open_app"),
            (r"최대화|크게",            "maximize_window"),
            (r"최소화|작게",            "minimize_window"),
            (r"삭제|지워",              "delete_file"),
        ]
        for pattern, action in mappings:
            if re.search(pattern, user_input):
                return action
        return None

    # ── 3단계: 히스토리 조회 ─────────────────────────────────────

    def _resolve_history_query(self, user_input: str) -> dict | None:
        """
        '아까 뭐 했어?' → 히스토리 요약 반환
        현재는 마지막 명령 반환으로 단순 처리.

        TODO: LLM으로 히스토리 전체 요약해서 반환하는 방식으로 고도화
        """
        for pattern in HISTORY_PATTERNS:
            if re.search(pattern, user_input):
                last = self._get_recent_history(1)
                if last:
                    last_input = last[0]["user_input"]
                    return {
                        "type": "system",
                        "action": "history_response",
                        "params": {"message": f"마지막 명령: {last_input}"},
                        "_from_context": True
                    }
        return None

    # ── 4단계: LLM 추론 ──────────────────────────────────────────

    def _has_context_hint(self, user_input: str) -> bool:
        """맥락 지시어가 포함된 입력인지 간단히 판단"""
        hints = ["그거", "이거", "그것", "이것", "아까", "방금", "그때",
                 "다시", "또", "전에", "이전에"]
        return any(h in user_input for h in hints)

    def _resolve_with_llm(self, user_input: str) -> dict | None:
        """
        1~3단계로 해석 못한 복잡한 맥락 → Gemini로 추론
        최근 히스토리 N개 + 현재 입력을 프롬프트에 주입
        """
        try:
            from app.agents.base_agent import BaseAgent
            from config.settings import ACTIVE_PROVIDER, ACTIVE_MODEL

            history = self._get_recent_history(self.history_limit)
            if not history:
                return None

            history_text = "\n".join([
                f"[{i+1}] 입력: {h['user_input']} → 동작: {h['command'].get('action','')}"
                for i, h in enumerate(reversed(history))
            ])

            prompt = f"""아래는 사용자의 최근 PC 제어 명령 히스토리야.
히스토리:
{history_text}

현재 입력: "{user_input}"

현재 입력이 히스토리를 참조하는 맥락 명령이라면,
반드시 아래 JSON 형식으로만 답해. 해석 불가하면 null만 반환해.
type은 반드시 local / web / system / interpreter 중 하나만 사용할 것.
params는 반드시 action에 필요한 값을 히스토리에서 추출해서 채울 것.

{{"type": "유형", "action": "동작", "params": {{파라미터}}}}"""

            # TODO: BaseAgent를 직접 인스턴스화하지 않고
            #       SupervisorAgent에 메서드 추가하는 방식으로 리팩토링 고려
            class _TempAgent(BaseAgent):
                def analyze_command(self, user_input): return {}

            agent = _TempAgent()
            agent._init_client(ACTIVE_PROVIDER, ACTIVE_MODEL)

            if not agent.available:
                return None

            response = agent._call_llm(prompt)
            if response.strip() == "null" or not response.strip():
                return None

            result = agent._parse_json(response)
            if result.get("type") == "unknown":
                return None

            result["_from_context"] = True
            return result

        except Exception as e:
            print(f"[ContextMemory] LLM 추론 실패: {e}")
            return None

    # ── 히스토리 조회 ─────────────────────────────────────────────

    def _get_recent_history(self, n: int) -> list:
        """최근 n개 히스토리 반환"""
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT user_input, command, result, timestamp
                FROM command_history
                ORDER BY id DESC LIMIT ?
            """, (n,)).fetchall()
        return [
            {
                "user_input": r[0],
                "command":    json.loads(r[1]),
                "result":     json.loads(r[2]) if r[2] else {},
                "timestamp":  r[3],
            }
            for r in rows
        ]

    def get_all_history(self) -> list:
        """전체 히스토리 반환 (디버깅/UI 용도)"""
        return self._get_recent_history(100)

    def clear(self):
        """히스토리 초기화"""
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM command_history")
            conn.commit()
        self.last_app = None
        self.last_file = None
        self.last_action = None
        self.last_command = None
        print("[ContextMemory] 히스토리 초기화 완료")