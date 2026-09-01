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
# ※ 명령어와 플래그 사이 공백은 \s* (선택)로 둔다 — "rm-rf" / "del/f" 처럼
#   공백을 뺀 변형도 동일하게 위험하기 때문. 앞의 단어경계(\b)가 "warm-rf" 같은
#   단어 내부 매칭을 막아 오탐을 방지한다. (BL-03)
#   반대로 "net user x y"처럼 공백이 있어야 의미가 성립하는 건 \s+ 를 유지한다.
_DANGEROUS_CMD_PATTERNS: list[Tuple[str, str]] = [
    (r"\brm\s*-[rRfF]{1,3}\b",                      "rm -rf"),
    (r"\bdel\s*/[fsqFSQ]",                          "del /f /s"),
    (r"\bformat\s*[a-z]:",                          "format X:"),
    (r"\breg\s+(delete|add)\b",                     "reg delete / reg add"),
    (r"\bshutdown\s*/[frFR]\b",                     "shutdown /f /r"),
    (r"\btaskkill\s*/[fiF]\b",                      "taskkill /f"),
    (r"\bnet\s+user\s+\S+\s+\S+",                  "net user (계정 변조)"),
    (r"\bnet\s+localgroup\s+administrators\b",      "net localgroup administrators"),
    (r"\brmdir\s*/[sqSQ]\b",                        "rmdir /s /q"),
    (r"\bicacls\b|\bcacls\b",                       "icacls / cacls"),
    (r"\bdiskpart\b",                               "diskpart"),
    (r"\bbcdedit\b",                                "bcdedit"),
    (r"\bwmic\b.*\bdelete\b",                       "wmic ... delete"),
    (r"powershell.*-encodedcommand",                "PowerShell -EncodedCommand"),
    (r"powershell.*-executionpolicy\s+bypass",      "PowerShell -ExecutionPolicy Bypass"),
    (r"\bcipher\s*/[wdWD]\b",                       "cipher /w /d"),
    (r"\bsc\s+(delete|stop|create)\b",              "sc delete/stop/create"),
    (r"\bschtasks\s*/delete\b",                     "schtasks /delete"),
    # PowerShell 단축 플래그 (인코딩/우회 시도)
    (r"powershell[^\n]*-ec\b",                           "PowerShell -ec (EncodedCommand 단축)"),
    (r"powershell[^\n]*-ep\s+bypass",                   "PowerShell -ep bypass"),
    (r"powershell[^\n]*-nop\b",                         "PowerShell -NoProfile"),
    (r"powershell[^\n]*-w(?:indowstyle)?\s+hid",        "PowerShell -WindowStyle Hidden"),
]

# 경로 순회 패턴
_PATH_TRAVERSAL_PATTERNS: list[str] = [
    r"(\.\.[\\/]){2,}",   # ../../  또는  ..\..\ 2회 이상
]

# ── 프롬프트 인젝션 패턴 (OWASP LLM01) ────────────────────────────
# 시스템 지침 우회·프롬프트 유출·모드 전환 등 "고신뢰" 공격 신호만 규칙으로 차단.
# 교묘/애매한 시도는 P3-4 하이브리드 LLM 판정기로 escalate.
# 공백 유무 모두 매칭하도록 check 시 원문/무공백 둘 다 검사.
_INJECTION_PATTERNS: list[Tuple[str, str]] = [
    (r"(이전|위|앞)\s*(의)?\s*(지시|명령|지침|규칙)\s*(사항)?.{0,6}(무시|잊|무효|버려|잊어)", "이전 지시 무시 시도"),
    (r"(지침|규칙|제한|제약|설정|역할|필터|안전장치|가드레일)\s*(을|를)?\s*(무시|잊어|잊고|해제|무효|꺼|끄)", "규칙/안전장치 무시 시도"),
    (r"(개발자|디버그|관리자|dan)\s*모드", "모드 우회 시도"),
    (r"제한\s*(을|를)?\s*(해제|풀|없이|무시)", "제한 해제 시도"),
    (r"시스템\s*프롬프트|(프롬프트|지시사항|규칙사항)\s*(을|를)?\s*(알려|보여|출력|공개|말해)", "시스템 프롬프트 유출 시도"),
    (r"ignore\s+(all\s+|the\s+)?(previous|above|prior|earlier)\s+(instruction|prompt|rule|message)", "ignore previous"),
    (r"disregard\s+(all\s+|the\s+)?(previous|above|prior)", "disregard previous"),
    (r"developer\s*mode|jail\s*break|jailbreak|reveal\s+(your\s+)?(instruction|prompt|system)|forget\s+(your|all)\s+(rule|instruction)|bypass\s+(your\s+)?(rule|filter|instruction)|override\s+your", "영문 인젝션 패턴"),
]


def check_prompt_injection(user_input: str) -> Tuple[bool, str]:
    """프롬프트 인젝션(LLM01) 규칙 검사. (blocked, reason)."""
    lower = user_input.lower()
    lower_ns = re.sub(r"\s+", "", lower)
    for pattern, label in _INJECTION_PATTERNS:
        pat_ns = pattern.replace(r"\s*", "").replace(r"\s+", "")
        if re.search(pattern, lower) or re.search(pat_ns, lower_ns):
            return True, (
                f"⚠️ 보안 차단: 시스템 지침을 우회하려는 시도({label})가 감지됐어요. "
                "이 요청은 처리하지 않아요."
            )
    return False, ""


# ── 민감정보 요청 패턴 (OWASP LLM02) ──────────────────────────────
_SECRET_REQUEST_PATTERNS: list[Tuple[str, str]] = [
    (r"(api\s*키|api\s*key|에이피아이\s*키|앱\s*키)\s*(를|을|좀)?\s*(알려|보여|뭐|출력|말해|가르쳐|줘)", "API 키 요청"),
    (r"(비밀번호|패스워드|password|비번)\s*(를|을|좀)?\s*(알려|보여|출력|말해|뭐)", "비밀번호 요청"),
    (r"\.env\s*(파일)?\s*(을|를)?\s*(열|보여|읽|출력|내용|공개)", ".env 열람 시도"),
    (r"(토큰|token|시크릿|secret\s*key|credential|자격\s*증명|인증\s*키)\s*(를|을|좀)?\s*(알려|보여|출력|말해)", "비밀정보 요청"),
]


def check_sensitive_request(user_input: str) -> Tuple[bool, str]:
    """민감정보(API키·비밀번호·토큰·.env) 요청 차단(LLM02). (blocked, reason)."""
    lower = user_input.lower()
    for pattern, label in _SECRET_REQUEST_PATTERNS:
        if re.search(pattern, lower):
            return True, (
                f"⚠️ 보안 차단: 민감정보({label})는 보안상 알려드릴 수 없어요. "
                "API 키·비밀번호 등은 설정 화면에서 직접 관리해 주세요."
            )
    return False, ""


# ── 출력 마스킹 (OWASP LLM02/LLM05) ───────────────────────────────
# 응답에 민감정보가 섞여 나갈 때 마스킹. output_guard에서 최종 적용(P3-3).
_RRN_RE  = re.compile(r"\b(\d{6})[- ]?\d{7}\b")                    # 주민등록번호
_CARD_RE = re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?(\d{4})\b")  # 카드번호(16)
_GKEY_RE = re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b")             # Google API key
_OKEY_RE = re.compile(r"\bsk-[0-9A-Za-z_\-]{20,}\b")             # OpenAI key


def mask_sensitive_output(text: str) -> str:
    """응답 텍스트에서 주민번호·카드번호·API키를 마스킹한다."""
    if not text:
        return text
    text = _RRN_RE.sub(r"\1-*******", text)
    text = _CARD_RE.sub(r"****-****-****-\1", text)
    text = _GKEY_RE.sub("AIza***(마스킹됨)", text)
    text = _OKEY_RE.sub("sk-***(마스킹됨)", text)
    return text


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

    # 4. 프롬프트 인젝션 차단 (LLM01)
    blocked, reason = check_prompt_injection(user_input)
    if blocked:
        return True, reason

    # 5. 민감정보 요청 차단 (LLM02)
    blocked, reason = check_sensitive_request(user_input)
    if blocked:
        return True, reason

    return False, ""
