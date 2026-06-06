# inject_bad_cache.py — T-C4 테스트용 잘못된 캐시 심기
import sqlite3
import os
import json

db = os.path.join("app", "cache", "pluiz_cache.db")

with sqlite3.connect(db) as conn:
    conn.execute(
        "INSERT OR REPLACE INTO command_cache (cache_key, action, params, code) VALUES (?, ?, ?, ?)",
        (
            "open_app:notepad",
            "open_app",
            json.dumps({"app": "notepad"}),
            'raise Exception("의도적 오류")',
        )
    )
    conn.commit()

print("완료: open_app:notepad 에 잘못된 코드 심기 완료")
print("이제 '메모장 열어줘' 실행해보세요")
