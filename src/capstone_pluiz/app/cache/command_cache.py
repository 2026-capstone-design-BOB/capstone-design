# app/cache/command_cache.py
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pluiz_cache.db")

class CommandCache:
    def __init__(self):
        self._init_db()
        print("[Cache] 초기화 완료")

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS command_cache (
                    cache_key TEXT PRIMARY KEY,
                    action TEXT,
                    params TEXT,
                    code TEXT NOT NULL,
                    success_count INTEGER DEFAULT 1,
                    last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def _make_key(self, command: dict) -> str:
        action = command.get("action", "")
        params = command.get("params", {})
        values = ":".join(str(v) for v in params.values() if v)
        return f"{action}:{values}" if values else action

    def get(self, command: dict) -> dict | None:
        key = self._make_key(command)
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT code FROM command_cache WHERE cache_key = ?", (key,)
            ).fetchone()
        if row:
            self._update_used(key)
            print(f"[Cache] 히트: {key}")
            return {"code": row[0]}
        return None

    def save(self, command: dict, code: str, original_input: str = ""):
        key = self._make_key(command)
        action = command.get("action", "")
        params = command.get("params", {})
        with sqlite3.connect(DB_PATH) as conn:
            existing = conn.execute(
                "SELECT cache_key FROM command_cache WHERE cache_key = ?", (key,)
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE command_cache
                    SET success_count = success_count + 1,
                        last_used_at = CURRENT_TIMESTAMP
                    WHERE cache_key = ?
                """, (key,))
            else:
                conn.execute("""
                    INSERT INTO command_cache (cache_key, action, params, code)
                    VALUES (?, ?, ?, ?)
                """, (key, action, json.dumps(params, ensure_ascii=False), code))
            conn.commit()
        print(f"[Cache] 저장: {key}")

    def _update_used(self, key: str):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                UPDATE command_cache
                SET success_count = success_count + 1,
                    last_used_at = CURRENT_TIMESTAMP
                WHERE cache_key = ?
            """, (key,))
            conn.commit()

    def get_all(self) -> list:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT cache_key, action, params, success_count, last_used_at
                FROM command_cache ORDER BY success_count DESC
            """).fetchall()
        return [{"key": r[0], "action": r[1], "params": r[2],
                 "count": r[3], "last_used": r[4]} for r in rows]

    def clear(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM command_cache")
            conn.commit()
        print("[Cache] 전체 초기화 완료")