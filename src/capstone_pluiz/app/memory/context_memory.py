# app/memory/context_memory.py
# 대화 맥락 메모리 — 히스토리 저장 + 조회
# 패턴 매칭 제거: 맥락 해석은 SupervisorAgent(Gemini)가 히스토리를 직접 보고 처리

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "context_memory.db")

# ── TODO: [확장 포인트] ────────────────────────────────────────────
# 1. 히스토리 압축 (토큰 절약)
#    히스토리 N개 초과 시 오래된 것을 LLM으로 요약 → summary 컬럼에 저장
#    구현 위치: _compress_history()
#
# 2. 개인화 메모리
#    자주 쓰는 앱/파일/검색어 패턴 학습 → user_preferences 테이블
#    구현 위치: app/memory/personal_memory.py
#
# 3. 세션 관리
#    앱 재시작 시 이전 세션 히스토리 로드 여부 선택
#    현재는 매번 전체 히스토리 유지 (DB 영속)
# ─────────────────────────────────────────────────────────────────


class ContextMemory:
    def __init__(self, history_limit: int = 10):
        """
        history_limit: SupervisorAgent 프롬프트에 주입할 최근 히스토리 개수.
                       토큰 절약을 위해 제한.
        """
        self.history_limit = history_limit
        self._init_db()
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
        """실행 완료 후 호출 — 히스토리 DB 저장"""
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

    # ── 조회 ──────────────────────────────────────────────────────

    def get_recent(self, n: int = None) -> list[dict]:
        """
        최근 n개 히스토리 반환 (오래된 순).
        n 미지정 시 history_limit 사용.
        SupervisorAgent.generate_code()에 history 인자로 전달.
        """
        limit = n if n is not None else self.history_limit
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT user_input, command, result, timestamp
                FROM command_history
                ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()

        # DESC로 가져온 뒤 역순 → 오래된 것이 앞에 오도록
        entries = [
            {
                "user_input": r[0],
                "command":    json.loads(r[1]),
                "result":     json.loads(r[2]) if r[2] else {},
                "timestamp":  r[3],
            }
            for r in rows
        ]
        return list(reversed(entries))

    def get_last_command(self) -> dict | None:
        """직전 명령 단건 반환 (취소/반복 처리 등 단순 참조용)"""
        recent = self.get_recent(1)
        return recent[0]["command"] if recent else None

    def get_last_input(self) -> str | None:
        """직전 사용자 입력 반환 (히스토리 조회 응답용)"""
        recent = self.get_recent(1)
        return recent[0]["user_input"] if recent else None

    def get_all(self) -> list[dict]:
        """전체 히스토리 반환 (디버깅/UI 용도)"""
        return self.get_recent(100)

    # ── 초기화 ────────────────────────────────────────────────────

    def clear(self):
        """히스토리 전체 초기화"""
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM command_history")
            conn.commit()
        print("[ContextMemory] 히스토리 초기화 완료")