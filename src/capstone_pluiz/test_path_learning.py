# test_path_learning.py — 경로 자동 학습 테스트
import sqlite3
import os

db = os.path.join("app", "cache", "pluiz_cache.db")

# 1. chrome 경로 삭제
with sqlite3.connect(db) as conn:
    conn.execute("DELETE FROM app_paths WHERE app_name = 'chrome'")
    conn.commit()
print("1. chrome app_paths 삭제 완료")

# 2. chrome 캐시도 삭제 (캐시 미스 유도)
with sqlite3.connect(db) as conn:
    conn.execute("DELETE FROM command_cache WHERE cache_key = 'open_app:chrome'")
    conn.commit()
print("2. open_app:chrome 캐시 삭제 완료")
print()
print("이제 main.py 실행 후 '크롬 열어줘' 입력하세요.")
print("성공 후 아래 스크립트로 DB 확인:")
print("  python check_path_learning.py")
