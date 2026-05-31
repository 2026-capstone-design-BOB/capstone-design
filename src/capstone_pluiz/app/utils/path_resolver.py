# app/utils/path_resolver.py
# 앱 설치 경로 탐색 유틸리티
# setup.py에서 호출하여 app_paths 테이블에 저장

import os
import winreg
from app.cache.command_cache import CommandCache

# ──────────────────────────────────────────────
# 탐색 대상 앱 정의
# ──────────────────────────────────────────────

# 고정 경로 (Windows 기본 앱 - 탐색 불필요)
FIXED_PATHS = {
    "notepad":  "C:/Windows/System32/notepad.exe",
    "calc":     "C:/Windows/System32/calc.exe",
    "mspaint":  "C:/Windows/System32/mspaint.exe",
    "explorer": "C:/Windows/explorer.exe",
}

# 탐색 필요 앱 (후보 경로 순서대로 탐색)
SEARCH_APPS = {
    "chrome": {
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
        "registry_keys": [],
        "fallback_paths": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Kakao/KakaoTalk/KakaoTalk.exe"),
        ],
        "hardcoded": None,
    },
    "word": {
        "registry_keys": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\winword.exe"),
        ],
        "fallback_paths": [
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Microsoft Office/root/Office16/WINWORD.EXE"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                         "Microsoft Office/root/Office16/WINWORD.EXE"),
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Microsoft Office/Office16/WINWORD.EXE"),
        ],
        "hardcoded": None,
    },
    "excel": {
        "registry_keys": [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
        ],
        "fallback_paths": [
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Microsoft Office/root/Office16/EXCEL.EXE"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                         "Microsoft Office/root/Office16/EXCEL.EXE"),
            os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                         "Microsoft Office/Office16/EXCEL.EXE"),
        ],
        "hardcoded": None,
    },
    "powerpoint": {
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
        """레지스트리에서 앱 경로 탐색"""
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
        """일반 설치 경로에서 탐색"""
        for path in fallback_paths:
            path = path.replace("\\", "/")
            if os.path.exists(path):
                return path
        return None

    def resolve(self, app_name: str) -> str | None:
        """단일 앱 경로 탐색. 레지스트리 → 일반경로 → 하드코딩 순서"""
        if app_name in FIXED_PATHS:
            return FIXED_PATHS[app_name]

        if app_name not in SEARCH_APPS:
            return None

        app_info = SEARCH_APPS[app_name]

        # 1. 레지스트리 탐색
        path = self._search_registry(app_info.get("registry_keys", []))
        if path:
            print(f"  [PathResolver] {app_name}: 레지스트리에서 발견 → {path}")
            return path

        # 2. 일반 경로 탐색
        path = self._search_fallback(app_info.get("fallback_paths", []))
        if path:
            print(f"  [PathResolver] {app_name}: 일반 경로에서 발견 → {path}")
            return path

        # 3. 하드코딩 폴백
        hardcoded = app_info.get("hardcoded")
        if hardcoded:
            print(f"  [PathResolver] {app_name}: 폴백 경로 사용 → {hardcoded}")
            return hardcoded

        print(f"  [PathResolver] {app_name}: 설치 경로 찾지 못함")
        return None

    def resolve_all(self) -> dict:
        """모든 앱 경로 탐색 후 app_paths 테이블에 저장"""
        results = {}

        # 고정 경로 저장
        for app_name, path in FIXED_PATHS.items():
            self.cache.save_app_path(app_name, path, verified=True)
            results[app_name] = path

        # 탐색 필요 앱 저장
        for app_name in SEARCH_APPS:
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
                lines.append(f"- {label}: (설치되지 않음)")
        return "\n".join(lines)
