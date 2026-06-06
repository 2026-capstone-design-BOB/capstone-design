# check_path_learning.py — 학습 결과 확인
import sqlite3
import os

db = os.path.join("app", "cache", "pluiz_cache.db")
with sqlite3.connect(db) as conn:
    row = conn.execute(
        "SELECT app_name, path, verified FROM app_paths WHERE app_name = 'chrome'"
    ).fetchone()

if row:
    print(f"[결과] chrome 경로 학습 확인:")
    print(f"  app_name : {row[0]}")
    print(f"  path     : {row[1]}")
    print(f"  verified : {row[2]}")
else:
    print("[결과] chrome 경로가 app_paths에 없음 — 학습 실패")
