# app/utils/path_resolver.py
# 앱 설치 경로 탐색 유틸리티
# setup.py에서 호출하여 app_paths 테이블에 저장

import os
import subprocess
import winreg
import glob
from app.cache.command_cache import CommandCache

# ──────────────────────────────────────────────────────────────────
# TODO: [경로 주기적 재탐색]
# 현재: setup.py 수동 재실행 필요
# 향후 구현:
#   - main.py 시작 시 app_paths 테이블의 마지막 업데이트 날짜 확인
#   - 7일 이상 경과 시 백그라운드 스레드로 resolve_all() 자동 실행
#   - 구현 위치: main.py 또는 별도 app/utils/scheduler.py
# ──────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────
# TODO: [실행 중 경로 학습]
# 현재: Gemini가 성공적으로 실행한 코드에서 경로 추출 안 함
# 향후 구현:
#   - interpreter_exec.py 실행 성공 후 코드에서 .exe 경로 패턴 추출
#   - 추출된 경로를 app_paths 테이블에 업데이트
#   - 정규식: r'[A-Z]:/[^\s"\']+\.exe'
#   - 구현 위치: interpreter_exec.py _execute_code() 성공 후
# ──────────────────────────────────────────────────────────────────


# 고정 경로 (Windows 기본 앱 - 탐색 불필요)
FIXED_PATHS = {
    "notepad":  "C:/Windows/System32/notepad.exe",
    "calc":     "C:/Windows/System32/calc.exe",
    "mspaint":  "C:/Windows/System32/mspaint.exe",
    "explorer": "C:/Windows/explorer.exe",
}

# 탐색 필요 앱
SEARCH_APPS = {
    "chrome": {
        "exe_name": "chrome.exe",
        "registry_keys": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
        ],
        "fallback_paths": [
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Google/Chrome/Application/chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                         "Google/Chrome/Application/chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Google/Chrome/Application/chrome.exe"),
        ],
        "hardcoded": "C:/Program Files/Google/Chrome/Application/chrome.exe",
    },
    "edge": {
        "exe_name": "msedge.exe",
        "registry_keys": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
        ],
        "fallback_paths": [
            os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                         "Microsoft/Edge/Application/msedge.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Microsoft/Edge/Application/msedge.exe"),
        ],
        "hardcoded": "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    },
    "kakao": {
        "exe_name": "KakaoTalk.exe",
        "registry_keys": [],
        "fallback_paths": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Kakao/KakaoTalk/KakaoTalk.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Kakao/KakaoTalk/KakaoTalk.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                         "Kakao/KakaoTalk/KakaoTalk.exe"),
        ],
        "hardcoded": None,
    },
    "word": {
        "exe_name": "WINWORD.EXE",
        "registry_keys": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\winword.exe"),
        ],
        "fallback_paths": [
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Microsoft Office/root/Office16/WINWORD.EXE"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                         "Microsoft Office/root/Office16/WINWORD.EXE"),
        ],
        "hardcoded": None,
    },
    "excel": {
        "exe_name": "EXCEL.EXE",
        "registry_keys": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
        ],
        "fallback_paths": [
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Microsoft Office/root/Office16/EXCEL.EXE"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                         "Microsoft Office/root/Office16/EXCEL.EXE"),
        ],
        "hardcoded": None,
    },
    "powerpoint": {
        "exe_name": "POWERPNT.EXE",
        "registry_keys": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\powerpnt.exe"),
        ],
        "fallback_paths": [
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Microsoft Office/root/Office16/POWERPNT.EXE"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                         "Microsoft Office/root/Office16/POWERPNT.EXE"),
        ],
        "hardcoded": None,
    },
}


class PathResolver:
    def __init__(self):
        self.cache = CommandCache()

    def _search_registry(self, registry_keys: list) -> str | None:
        for hkey, subkey in registry_keys:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    path, _ = winreg.QueryValueEx(key, "")
                    path = path.replace("\\", "/")
                    if os.path.exists(path):
                        return path
            except (FileNotFoundError, OSError):
                continue
        return None

    def _search_fallback(self, fallback_paths: list) -> str | None:
        for path in fallback_paths:
            path = path.replace("\\", "/")
            if os.path.exists(path):
                return path
        return None

    def _search_where(self, exe_name: str) -> str | None:
        """where 명령어로 PATH에서 탐색"""
        try:
            result = subprocess.run(
                ["where", exe_name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                path = result.stdout.strip().splitlines()[0].replace("\\", "/")
                if os.path.exists(path):
                    return path
        except Exception:
            pass
        return None

    def _search_start_menu(self, exe_name: str) -> str | None:
        """시작 메뉴 바로가기(.lnk)에서 탐색"""
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")

            start_menu_paths = [
                os.path.join(os.environ.get("APPDATA", ""),
                             "Microsoft/Windows/Start Menu/Programs"),
                os.path.join(os.environ.get("PROGRAMDATA", ""),
                             "Microsoft/Windows/Start Menu/Programs"),
            ]

            exe_base = os.path.splitext(exe_name)[0].lower()

            for start_path in start_menu_paths:
                for lnk in glob.glob(os.path.join(start_path, "**/*.lnk"), recursive=True):
                    if exe_base in os.path.basename(lnk).lower():
                        try:
                            shortcut = shell.CreateShortCut(lnk)
                            target = shortcut.Targetpath.replace("\\", "/")
                            if target and os.path.exists(target):
                                return target
                        except Exception:
                            continue
        except ImportError:
            # win32com 없으면 건너뜀
            pass
        except Exception:
            pass
        return None

    def validate_all(self) -> list:
        """
        app_paths 테이블의 모든 경로 유효성 검증
        존재하지 않으면 verified=0으로 변경 → 재탐색 트리거
        """
        invalid = []
        all_paths = self.cache.get_all_app_paths()
        for app_name, info in all_paths.items():
            path = info.get("path", "")
            if path and not os.path.exists(path):
                self.cache.save_app_path(app_name, path, verified=False)
                invalid.append(app_name)
                print(f"  [PathResolver] {app_name}: 경로 유효하지 않음 → 재탐색 필요")
        return invalid

    def resolve(self, app_name: str) -> str | None:
        """
        단일 앱 경로 탐색
        순서: 레지스트리 → fallback → where → 시작메뉴 → hardcoded
        """
        if app_name in FIXED_PATHS:
            return FIXED_PATHS[app_name]

        if app_name not in SEARCH_APPS:
            return None

        app_info = SEARCH_APPS[app_name]
        exe_name = app_info.get("exe_name", "")

        # 1. 레지스트리
        path = self._search_registry(app_info.get("registry_keys", []))
        if path:
            print(f"  [PathResolver] {app_name}: 레지스트리 발견 → {path}")
            return path

        # 2. fallback 경로
        path = self._search_fallback(app_info.get("fallback_paths", []))
        if path:
            print(f"  [PathResolver] {app_name}: 일반 경로 발견 → {path}")
            return path

        # 3. where 명령어
        if exe_name:
            path = self._search_where(exe_name)
            if path:
                print(f"  [PathResolver] {app_name}: where 명령으로 발견 → {path}")
                return path

        # 4. 시작 메뉴 바로가기
        if exe_name:
            path = self._search_start_menu(exe_name)
            if path:
                print(f"  [PathResolver] {app_name}: 시작 메뉴에서 발견 → {path}")
                return path

        # 5. hardcoded 폴백
        hardcoded = app_info.get("hardcoded")
        if hardcoded:
            print(f"  [PathResolver] {app_name}: 폴백 경로 사용 → {hardcoded}")
            return hardcoded

        print(f"  [PathResolver] {app_name}: 설치 경로 찾지 못함")
        return None

    def resolve_all(self) -> dict:
        """
        모든 앱 경로 탐색 후 app_paths 테이블에 저장
        1. 유효성 검증 먼저 (기존 경로 깨진 것 체크)
        2. 탐색 실패 또는 invalid 앱 재탐색
        """
        # 기존 경로 유효성 검증
        invalid_apps = self.validate_all()

        results = {}

        # 고정 경로 저장
        for app_name, path in FIXED_PATHS.items():
            self.cache.save_app_path(app_name, path, verified=True)
            results[app_name] = path

        # 탐색 필요 앱
        for app_name in SEARCH_APPS:
            # 이미 유효한 경로가 있으면 건너뜀
            if app_name not in invalid_apps:
                existing = self.cache.get_app_path(app_name)
                if existing:
                    results[app_name] = existing
                    continue

            # 탐색
            path = self.resolve(app_name)
            if path:
                self.cache.save_app_path(app_name, path, verified=True)
                results[app_name] = path
            else:
                self.cache.save_app_path(app_name, "", verified=False)
                results[app_name] = None

        return results

    def get_prompt_paths(self) -> str:
        """BRAIN_PROMPT 주입용 경로 문자열 생성"""
        lines = ["Windows 앱 경로 (사용자 환경에서 탐색된 실제 경로):"]
        app_labels = {
            "chrome":      "크롬",
            "edge":        "엣지",
            "kakao":       "카카오톡",
            "word":        "워드",
            "excel":       "엑셀",
            "powerpoint":  "파워포인트",
            "notepad":     "메모장",
            "calc":        "계산기",
            "mspaint":     "그림판",
            "explorer":    "파일탐색기",
        }
        for app_name, label in app_labels.items():
            path = self.cache.get_app_path(app_name)
            if path:
                lines.append(f"- {label}: {path}")
            else:
                lines.append(f"- {label}: (설치되지 않음 또는 경로 미확인)")
        return "\n".join(lines)