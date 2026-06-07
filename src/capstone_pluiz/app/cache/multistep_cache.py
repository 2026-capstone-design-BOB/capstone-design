# app/cache/multistep_cache.py
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pluiz_cache.db")


class MultiStepCache:
    def __init__(self):
        self._init_db()
        print("[MultiStepCache] 초기화 완료")

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS multistep_cache (
                    cache_key TEXT PRIMARY KEY,
                    original_input TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    step_count INTEGER NOT NULL,
                    success_count INTEGER DEFAULT 1,
                    last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def _make_key(self, steps: list[dict]) -> str:
        """
        스텝 리스트 전체를 키로 변환.
        예: [{"action":"open_app","params":{"app":"chrome"}}, {"action":"youtube_search",...}]
             → "open_app:chrome|youtube_search:아이유"
        """
        parts = []
        for step in steps:
            action = step.get("action", "")
            params = step.get("params", {})
            values = ":".join(str(v) for v in params.values() if v)
            parts.append(f"{action}:{values}" if values else action)
        return "|".join(parts)

    def get(self, steps: list[dict]) -> list[dict] | None:
        """
        복합 명령 전체 키로 캐시 조회.
        반환: 스텝 리스트 (각 스텝에 code 포함) 또는 None
        """
        key = self._make_key(steps)
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT steps FROM multistep_cache WHERE cache_key = ?", (key,)
            ).fetchone()

        if row:
            self._update_used(key)
            print(f"[MultiStepCache] 히트: {key}")
            return json.loads(row[0])
        return None

    def save(self, steps: list[dict], original_input: str = ""):
        """
        복합 명령 전체를 캐시에 저장.
        steps: 각 스텝에 code가 포함된 상태여야 함.
        """
        key = self._make_key(steps)
        with sqlite3.connect(DB_PATH) as conn:
            existing = conn.execute(
                "SELECT cache_key FROM multistep_cache WHERE cache_key = ?", (key,)
            ).fetchone()

            if existing:
                conn.execute("""
                    UPDATE multistep_cache
                    SET success_count = success_count + 1,
                        last_used_at = CURRENT_TIMESTAMP
                    WHERE cache_key = ?
                """, (key,))
            else:
                conn.execute("""
                    INSERT INTO multistep_cache
                    (cache_key, original_input, steps, step_count)
                    VALUES (?, ?, ?, ?)
                """, (
                    key,
                    original_input,
                    json.dumps(steps, ensure_ascii=False),
                    len(steps)
                ))
            conn.commit()
        print(f"[MultiStepCache] 저장: {key} ({len(steps)}스텝)")

    def _update_used(self, key: str):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                UPDATE multistep_cache
                SET success_count = success_count + 1,
                    last_used_at = CURRENT_TIMESTAMP
                WHERE cache_key = ?
            """, (key,))
            conn.commit()

    def get_all(self) -> list:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT cache_key, original_input, step_count, success_count, last_used_at
                FROM multistep_cache ORDER BY success_count DESC
            """).fetchall()
        return [
            {
                "key": r[0],
                "original_input": r[1],
                "step_count": r[2],
                "count": r[3],
                "last_used": r[4]
            }
            for r in rows
        ]

    def clear(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM multistep_cache")
            conn.commit()
        print("[MultiStepCache] 전체 초기화 완료")
