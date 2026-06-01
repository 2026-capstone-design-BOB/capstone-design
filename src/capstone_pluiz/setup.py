# setup.py
# Pluiz V2 초기 설정 스크립트
# 최초 설치 후 1회 실행: python setup.py
# 경로가 바뀌었거나 재설정 필요 시 재실행 가능

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.cache.command_cache import CommandCache
from app.utils.path_resolver import PathResolver
from app.cache.preset_cache import PRESET_CACHE


# ──────────────────────────────────────────────────────────────────
# TODO: [주기적 재탐색 자동화]
# 현재: 수동으로 python setup.py 재실행 필요
# 향후 구현:
#   - main.py 시작 시 app_paths 테이블 last_updated 확인
#   - 7일 이상 경과 시 threading.Thread로 백그라운드 재탐색
#   - 구현 위치: main.py의 def main() 상단
#   예시:
#     from datetime import datetime, timedelta
#     last = cache.get_setup_date()
#     if not last or datetime.now() - last > timedelta(days=7):
#         threading.Thread(target=resolver.resolve_all, daemon=True).start()
# ──────────────────────────────────────────────────────────────────


def setup():
    print("=" * 50)
    print("  Pluiz V2 초기 설정")
    print("=" * 50)

    # Step 1. DB 테이블 초기화
    print("\n[Step 1] DB 테이블 초기화...")
    cache = CommandCache()
    print("  command_cache 테이블 ✅")
    print("  app_paths 테이블 ✅")

    # Step 2. 앱 경로 탐색 및 저장
    print("\n[Step 2] 앱 설치 경로 탐색 중...")
    resolver = PathResolver()
    results = resolver.resolve_all()

    print("\n  탐색 결과:")
    for app_name, path in results.items():
        status = "✅" if path else "❌ 미설치"
        display_path = path if path else "없음"
        print(f"  {app_name:<12}: {status}  {display_path}")

    # Step 3. Preset 캐시 삽입
    print("\n[Step 3] Preset 캐시 삽입...")
    for key, item in PRESET_CACHE.items():
        existing = cache.get(item["command"])
        if existing:
            # 버전 확인 후 업데이트
            db_version = cache.get_preset_version(key)
            if db_version != item["version"]:
                cache.update_preset(item["command"], item["code"], item["version"])
                print(f"  {key}: 업데이트 v{db_version} → v{item['version']} ✅")
            else:
                print(f"  {key}: 이미 최신 버전 v{item['version']} (건너뜀)")
        else:
            cache.save_preset(item["command"], item["code"], item["version"])
            print(f"  {key}: 삽입 완료 v{item['version']} ✅")

    print("\n" + "=" * 50)
    print("  초기 설정 완료!")
    print("  이제 python app/main.py 로 실행하세요.")
    print("=" * 50)

if __name__ == "__main__":
    setup()
