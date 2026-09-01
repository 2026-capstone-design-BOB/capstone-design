"""
Pluiz 캐시 클리어 스크립트
실행: python clear_cache.py
동적으로 학습된 항목만 삭제하고 시드(기본 명령 37개)는 유지합니다.
"""

import json
import os

CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "command_cache.json")


def clear_cache(keep_seeds: bool = True):
    if not os.path.exists(CACHE_PATH):
        print("캐시 파일이 없습니다.")
        return

    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    total = len(data)

    if keep_seeds:
        cleaned = {k: v for k, v in data.items() if isinstance(v, dict) and v.get("is_seed", False)}
        removed = total - len(cleaned)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        print(f"완료: 동적 항목 {removed}개 삭제 (시드 {len(cleaned)}개 유지)")
    else:
        os.remove(CACHE_PATH)
        print(f"완료: 캐시 전체 삭제 ({total}개). 다음 실행 시 시드에서 재생성됩니다.")


if __name__ == "__main__":
    import sys

    print("=" * 40)
    print("  Pluiz 캐시 클리어")
    print("=" * 40)

    if "--all" in sys.argv:
        print("모드: 전체 삭제 (시드 포함)")
        clear_cache(keep_seeds=False)
    else:
        print("모드: 동적 항목만 삭제 (시드 유지)")
        print("전체 삭제는 --all 옵션 사용")
        clear_cache(keep_seeds=True)
