# test_feedback_retry.py — 피드백 재시도 실효성 테스트
# chrome app_paths를 잘못된 경로로 바꿔서
# 사전 검증 통과 → 실행 후 검증 실패 → 피드백 재시도 유도
import sqlite3
import os

db = os.path.join("app", "cache", "pluiz_cache.db")

with sqlite3.connect(db) as conn:
    # 잘못된 경로로 교체 (파일은 존재하지 않지만 DB엔 있음)
    conn.execute("""
        UPDATE app_paths
        SET path = 'C:/FakePath/chrome.exe', verified = 1
        WHERE app_name = 'chrome'
    """)
    # 캐시도 삭제 (코드 재생성 유도)
    conn.execute("DELETE FROM command_cache WHERE cache_key = 'open_app:chrome'")
    conn.commit()

print("완료: chrome 경로를 잘못된 경로로 교체 + 캐시 삭제")
print("이제 main.py 실행 후 '크롬 열어줘' 입력하세요.")
print()
print("확인 포인트:")
print("  1. [AppResolver] DB 히트: chrome → C:/FakePath/chrome.exe  (사전 검증 통과)")
print("  2. [시도 1/3] 검증 실패  (실행 후 검증 실패)")
print("  3. 재시도 시 생성된 코드가 이전과 다른지 확인")
