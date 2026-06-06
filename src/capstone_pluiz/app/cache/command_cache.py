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
                    preset_version TEXT DEFAULT NULL,
                    success_count INTEGER DEFAULT 1,
                    last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_paths (
                    app_name TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    verified INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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

    def invalidate(self, command: dict):
        """검증 실패한 캐시 레코드 삭제."""
        key = self._make_key(command)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM command_cache WHERE cache_key = ?", (key,))
            conn.commit()
        print(f"[Cache] 무효화: {key}")

    def clear(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM command_cache")
            conn.commit()
        print("[Cache] 전체 초기화 완료")

    # ── app_paths 관련 메서드 ──

    def save_app_path(self, app_name: str, path: str, verified: bool = False):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO app_paths (app_name, path, verified, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (app_name, path, 1 if verified else 0))
            conn.commit()

    def get_app_path(self, app_name: str) -> str | None:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT path FROM app_paths WHERE app_name = ? AND verified = 1",
                (app_name,)
            ).fetchone()
        return row[0] if row and row[0] else None

    def get_all_app_paths(self) -> dict:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT app_name, path, verified FROM app_paths"
            ).fetchall()
        return {r[0]: {"path": r[1], "verified": bool(r[2])} for r in rows}

    # ── Preset 관련 메서드 ──

    def save_preset(self, command: dict, code: str, version: str):
        key = self._make_key(command)
        action = command.get("action", "")
        params = command.get("params", {})
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO command_cache
                (cache_key, action, params, code, preset_version)
                VALUES (?, ?, ?, ?, ?)
            """, (key, action, json.dumps(params, ensure_ascii=False), code, version))
            conn.commit()

    def update_preset(self, command: dict, code: str, version: str):
        key = self._make_key(command)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                UPDATE command_cache
                SET code = ?, preset_version = ?, last_used_at = CURRENT_TIMESTAMP
                WHERE cache_key = ?
            """, (code, version, key))
            conn.commit()

    def get_preset_version(self, action: str) -> str | None:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT preset_version FROM command_cache WHERE cache_key = ?",
                (action,)
            ).fetchone()
        return row[0] if row else None