# inject_bad_cache_file.py — TC-6 테스트용 잘못된 파일 생성 캐시 심기
# 실행 순서:
#   1. python inject_bad_cache_file.py
#   2. main.py 실행 후 "바탕화면에 test.txt 만들어줘" 입력
import sqlite3
import os
import json

db = os.path.join("app", "cache", "pluiz_cache.db")

# open()은 있지만 존재하지 않는 경로에 생성 시도 → FileNotFoundError → 실행 실패 출력
# 단, try/except가 감싸고 있어서 실행 자체는 성공처럼 보임
BAD_CODE = """\
import os
try:
    fake_path = "C:/fake/path/test.txt"
    with open(fake_path, "w") as f:
        pass
    print(f"생성 완료: {fake_path}")
    print("실행 완료")
except Exception as e:
    print(f"실행 실패: {e}")
"""

with sqlite3.connect(db) as conn:
    conn.execute(
        """
        INSERT OR REPLACE INTO command_cache
            (cache_key, action, params, code, success_count, last_used_at, created_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            "natural_language:바탕화면에 test.txt 만들어줘",
            "natural_language",
            json.dumps({"input": "바탕화면에 test.txt 만들어줘"}),
            BAD_CODE,
            1,
        )
    )
    conn.commit()

print("완료: natural_language:바탕화면에 test.txt 만들어줘 에 잘못된 경로 코드 심기 완료")
print("기대 동작: 캐시 히트 → open() 감지 → os.path.exists() 실패 → 캐시 무효화 → Gemini 재생성")
print()
print("이제 main.py 실행 후 '바탕화면에 test.txt 만들어줘' 입력하세요")