# tools/db_manager.py
# Pluiz V2 개발용 DB 관리 도구
# 실행: python tools/db_manager.py

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cache.command_cache import CommandCache

def print_menu():
    print("\n" + "=" * 50)
    print("  Pluiz V2 DB 관리 도구")
    print("=" * 50)
    print("  1. 전체 캐시 목록 보기")
    print("  2. 특정 캐시 검색")
    print("  3. 특정 캐시 삭제")
    print("  4. 전체 캐시 삭제")
    print("  5. 캐시 통계 보기")
    print("  6. 특정 캐시 코드 보기")
    print("  7. DB 파일 위치 확인")
    print("  0. 종료")
    print("=" * 50)

def show_all(cache: CommandCache):
    rows = cache.get_all()
    if not rows:
        print("\n[비어있음] 캐시된 명령이 없어요.")
        return
    print(f"\n총 {len(rows)}개 캐시\n")
    print(f"{'번호':<4} {'키':<30} {'액션':<20} {'횟수':<6} {'마지막 사용'}")
    print("-" * 85)
    for i, r in enumerate(rows, 1):
        print(f"{i:<4} {r['key']:<30} {r['action']:<20} {r['count']:<6} {r['last_used']}")

def search_cache(cache: CommandCache):
    keyword = input("\n검색어 입력: ").strip()
    rows = cache.get_all()
    results = [r for r in rows if keyword.lower() in r['key'].lower()
               or keyword.lower() in r['action'].lower()]
    if not results:
        print(f"[없음] '{keyword}' 관련 캐시가 없어요.")
        return
    print(f"\n'{keyword}' 검색 결과: {len(results)}개\n")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['key']} | 횟수: {r['count']} | {r['last_used']}")

def delete_one(cache: CommandCache):
    rows = cache.get_all()
    if not rows:
        print("\n[비어있음] 삭제할 캐시가 없어요.")
        return
    show_all(cache)
    try:
        num = int(input("\n삭제할 번호 입력 (0=취소): ").strip())
        if num == 0:
            return
        if num < 1 or num > len(rows):
            print("[오류] 잘못된 번호예요.")
            return
        target = rows[num - 1]
        confirm = input(f"'{target['key']}' 삭제할까요? (y/n): ").strip().lower()
        if confirm == 'y':
            import sqlite3
            from app.cache.command_cache import DB_PATH
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM command_cache WHERE cache_key = ?", (target['key'],))
                conn.commit()
            print(f"[완료] '{target['key']}' 삭제됐어요.")
        else:
            print("[취소]")
    except ValueError:
        print("[오류] 숫자를 입력해주세요.")

def delete_all(cache: CommandCache):
    rows = cache.get_all()
    if not rows:
        print("\n[비어있음] 삭제할 캐시가 없어요.")
        return
    confirm = input(f"\n전체 {len(rows)}개 캐시를 모두 삭제할까요? (y/n): ").strip().lower()
    if confirm == 'y':
        cache.clear()
        print("[완료] 전체 캐시 삭제됐어요.")
    else:
        print("[취소]")

def show_stats(cache: CommandCache):
    rows = cache.get_all()
    if not rows:
        print("\n[비어있음] 캐시가 없어요.")
        return
    total = len(rows)
    total_hits = sum(r['count'] for r in rows)
    top5 = rows[:5]
    print(f"\n총 캐시 수    : {total}개")
    print(f"총 히트 수    : {total_hits}회")
    print(f"평균 히트 수  : {total_hits / total:.1f}회")
    print(f"\n[자주 쓰는 명령 TOP 5]")
    for i, r in enumerate(top5, 1):
        print(f"  {i}. {r['key']} ({r['count']}회)")

def show_code(cache: CommandCache):
    rows = cache.get_all()
    if not rows:
        print("\n[비어있음] 캐시가 없어요.")
        return
    show_all(cache)
    try:
        num = int(input("\n코드 볼 번호 입력 (0=취소): ").strip())
        if num == 0:
            return
        if num < 1 or num > len(rows):
            print("[오류] 잘못된 번호예요.")
            return
        target = rows[num - 1]
        import sqlite3
        from app.cache.command_cache import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT code FROM command_cache WHERE cache_key = ?",
                (target['key'],)
            ).fetchone()
        if row:
            print(f"\n[{target['key']}] 캐시된 코드:")
            print("─" * 40)
            print(row[0])
            print("─" * 40)
    except ValueError:
        print("[오류] 숫자를 입력해주세요.")

def show_db_path():
    from app.cache.command_cache import DB_PATH
    print(f"\nDB 파일 위치: {DB_PATH}")
    exists = os.path.exists(DB_PATH)
    size = os.path.getsize(DB_PATH) if exists else 0
    print(f"파일 존재: {'✅' if exists else '❌'}")
    if exists:
        print(f"파일 크기: {size:,} bytes")

def main():
    cache = CommandCache()
    while True:
        print_menu()
        choice = input("선택: ").strip()
        if choice == "1":
            show_all(cache)
        elif choice == "2":
            search_cache(cache)
        elif choice == "3":
            delete_one(cache)
        elif choice == "4":
            delete_all(cache)
        elif choice == "5":
            show_stats(cache)
        elif choice == "6":
            show_code(cache)
        elif choice == "7":
            show_db_path()
        elif choice == "0":
            print("\n종료합니다.")
            break
        else:
            print("[오류] 0~7 중에서 선택해주세요.")

if __name__ == "__main__":
    main()