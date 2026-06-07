# setup.py
# Pluiz V2 초기 설정 스크립트
# 최초 설치 후 1회 실행: python setup.py
# 경로가 바뀌었거나 재설정 필요 시 재실행 가능

import sys
import os
import subprocess
import importlib
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.cache.command_cache import CommandCache
from app.cache.multistep_cache import MultiStepCache
from app.utils.path_resolver import PathResolver
from app.cache.preset_cache import PRESET_CACHE


def check_environment():
    print("\n[Step 0] 환경 검증 중...")
    all_ok = True

    major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) < (3, 10):
        print(f"  ❌ Python 3.10 이상 필요 (현재: {major}.{minor})")
        all_ok = False
    else:
        print(f"  ✅ Python {major}.{minor}")

    required = {
        "google.genai":      "google-genai",
        "selenium":          "selenium",
        "speech_recognition":"SpeechRecognition",
        "psutil":            "psutil",
        "win32com":          "pywin32",
        "requests":          "requests",
    }
    for module, pip_name in required.items():
        try:
            importlib.import_module(module)
            print(f"  ✅ {pip_name}")
        except ImportError:
            print(f"  ❌ {pip_name} 미설치 → pip install {pip_name}")
            all_ok = False

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-c", "Get-ExecutionPolicy"],
            capture_output=True, text=True, timeout=10
        )
        policy = result.stdout.strip()
        if policy in ("Restricted", "AllSigned"):
            print(f"  ⚠️  PowerShell 실행 정책: {policy}")
            print(f"      밝기/배터리 명령 실패할 수 있음")
        else:
            print(f"  ✅ PowerShell 실행 정책: {policy}")
    except Exception as e:
        print(f"  ⚠️  PowerShell 확인 실패: {e}")

    chrome_paths = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google/Chrome/Application/chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google/Chrome/Application/chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google/Chrome/Application/chrome.exe"),
    ]
    if any(os.path.exists(p) for p in chrome_paths):
        print(f"  ✅ Chrome 설치 확인")
    else:
        print(f"  ⚠️  Chrome 미설치 → 웹 검색/유튜브 기능 사용 불가")

    if all_ok:
        print("\n  환경 검증 완료 ✅ 모든 필수 패키지 정상")
    else:
        print("\n  ❌ 누락된 패키지가 있습니다. 위 항목 설치 후 재실행하세요.")
        print("  계속 진행하시겠습니까? (y/n): ", end="")
        if input().strip().lower() != "y":
            sys.exit(1)

    return all_ok


def setup():
    print("=" * 50)
    print("  Pluiz V2 초기 설정")
    print("=" * 50)

    check_environment()

    # Step 1. DB 테이블 초기화
    print("\n[Step 1] DB 테이블 초기화...")
    cache = CommandCache()
    cache.clear()                  # 기존 캐시 전체 삭제
    multistep_cache = MultiStepCache()
    multistep_cache.clear()        # 멀티스텝 캐시 전체 삭제
    print("  command_cache 테이블 ✅ (초기화 완료)")
    print("  multistep_cache 테이블 ✅ (초기화 완료)")
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