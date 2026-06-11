"""
Pluiz 보안 레이어 (Security Layer)
-----------------------------------
LLM 판단 전에 사용자 입력을 결정론적으로 검사.
프롬프트 방어는 우회 가능하므로 코드 레벨 필터가 필수.
"""

import re
from typing import Tuple


# ── 차단 패턴 정의 ────────────────────────────────────────────────

# 위험 시스템 경로 (소문자 정규식, label)
_BLOCKED_PATH_PATTERNS: list[Tuple[str, str]] = [
    (r"c:[/\\]windows[/\\]system32",  "C:\\Windows\\System32"),
    (r"c:[/\\]windows[/\\]syswow64",  "C:\\Windows\\SysWOW64"),
    (r"c:[/\\]windows[/\\]system\b",  "C:\\Windows\\System"),
    (r"c:[/\\]windows\b",             "C:\\Windows"),
    (r"%systemroot%",                 "%SystemRoot%"),
    (r"%windir%",                     "%WinDir%"),
    (r"[/\\]system32\b",              "\\System32"),
]

# 위험 명령어 패턴 (소문자 입력에 매칭, label)
_DANGEROUS_CMD_PATTERNS: list[Tuple[str, str]] = [
    (r"\brm\s+-[rRfF]{1,3}\b",                      "rm -rf"),
    (r"\bdel\s+/[fsqFSQ]",                          "del /f /s"),
    (r"\bformat\s+[a-z]:",                          "format X:"),
    (r"\breg\s+(delete|add)\b",                     "reg delete / reg add"),
    (r"\bshutdown\s+/[frFR]\b",                     "shutdown /f /r"),
    (r"\btaskkill\s+/[fiF]\b",                      "taskkill /f"),
    (r"\bnet\s+user\s+\S+\s+\S+",                  "net user (계정 변조)"),
    (r"\bnet\s+localgroup\s+administrators\b",      "net localgroup administrators"),
    (r"\brmdir\s+/[sqSQ]\b",                        "rmdir /s /q"),
    (r"\bicacls\b|\bcacls\b",                       "icacls / cacls"),
    (r"\bdiskpart\b",                               "diskpart"),
    (r"\bbcdedit\b",                                "bcdedit"),
    (r"\bwmic\b.*\bdelete\b",                       "wmic ... delete"),
    (r"powershell.*-encodedcommand",                "PowerShell -EncodedCommand"),
    (r"powershell.*-executionpolicy\s+bypass",      "PowerShell -ExecutionPolicy Bypass"),
    (r"\bcipher\s+/[wdWD]\b",                       "cipher /w /d"),
    (r"\bsc\s+(delete|stop|create)\b",              "sc delete/stop/create"),
    (r"\bschtasks\s+/delete\b",                     "schtasks /delete"),
]

# 경로 순회 패턴
_PATH_TRAVERSAL_PATTERNS: list[str] = [
    r"(\.\.[\\/]){2,}",   # ../../  또는  ..\..\ 2회 이상
]


def check_security(user_input: str) -> Tuple[bool, str]:
    """
    입력 보안 검사.

    Args:
        user_input: 사용자 원본 입력 텍스트

    Returns:
        (is_blocked, reason_korean)
        is_blocked=True → 차단되었음. reason에 한국어 사유 포함.
    """
    lower = user_input.lower()

    # 1. 위험 시스템 경로 차단
    for pattern, label in _BLOCKED_PATH_PATTERNS:
        if re.search(pattern, lower):
            return True, (
                f"⚠️ 보안 차단: '{label}' 경로에 대한 직접 접근은 허용되지 않습니다. "
                "시스템 파일 보호를 위한 보안 정책입니다."
            )

    # 2. 위험 명령어 패턴 차단
    for pattern, label in _DANGEROUS_CMD_PATTERNS:
        if re.search(pattern, lower):
            return True, (
                f"⚠️ 보안 차단: '{label}' 명령은 시스템에 돌이킬 수 없는 영향을 줄 수 있어 "
                "실행이 허용되지 않습니다."
            )

    # 3. 경로 순회 차단
    for pattern in _PATH_TRAVERSAL_PATTERNS:
        if re.search(pattern, user_input):
            return True, (
                "⚠️ 보안 차단: 경로 순회(../ 반복) 패턴이 감지되었습니다. "
                "허용되지 않는 파일 접근 방식입니다."
            )

    return False, ""
