"""
세션 메모리
대화 히스토리 저장 (SQLite). LangGraph MemorySaver가 메인이고,
이건 UI 표시용 + 통계용 보조 저장소.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session.db")


class SessionMemory:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_msg  TEXT NOT NULL,
                    agent_msg TEXT NOT NULL,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def save(self, user_msg: str, agent_msg: str):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO history (user_msg, agent_msg) VALUES (?, ?)",
                (user_msg, agent_msg)
            )
            conn.commit()

    def get_recent(self, n: int = 10) -> list[dict]:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT user_msg, agent_msg, timestamp FROM history ORDER BY id DESC LIMIT ?",
                (n,)
            ).fetchall()
        return [{"user": r[0], "agent": r[1], "time": r[2]} for r in reversed(rows)]

    def clear(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM history")
            conn.commit()
