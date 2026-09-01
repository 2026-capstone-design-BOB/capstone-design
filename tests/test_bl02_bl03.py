"""
BL-02(캐시 부정어 오매칭) · BL-03(보안필터 공백 없는 변형) 검증
================================================================
mock — Windows·LLM API 불필요.
실행: python tests/test_bl02_bl03.py

BL-03: core/security.py 의 위험 명령어 패턴이 공백을 뺀 변형("rm-rf")도 잡는지.
BL-02: core/fast_path.py 가 부정어("계산기 말고 ...")를 만나면 캐시를 건너뛰는지.
"""
import sys, os, importlib.util

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# security.py 는 의존성이 없어 exec 로 직접 로드
_sec = {}
exec(open(os.path.join(_ROOT, "core", "security.py"), encoding="utf-8").read(), _sec)
check_security = _sec["check_security"]

# fast_path.py 는 모듈로 로드 (DI 구조라 외부 의존 없음)
_spec = importlib.util.spec_from_file_location(
    "core.fast_path", os.path.join(_ROOT, "core", "fast_path.py"))
fast_path = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fast_path)


passed = total = 0


def check(name, cond):
    global passed, total
    total += 1
    passed += bool(cond)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}")


# ── BL-03: 위험 명령어 공백 변형 ──────────────────────────────────
# 공백이 있든 없든 동일하게 위험하다.
BLOCK_CASES = [
    ("rm -rf /",              "공백 있음 (기존)"),
    ("rm-rf /",               "공백 없음 ← BL-03"),
    ("rm  -rf /",             "공백 여러 개"),
    ("rm\t-rf /",             "탭 구분"),
    ("del /f /s C:\\",        "공백 있음 (기존)"),
    ("del/f/s C:\\",          "공백 없음 ← BL-03"),
    ("rmdir /s /q temp",      "공백 있음 (기존)"),
    ("rmdir/s/q temp",        "공백 없음 ← BL-03"),
    ("taskkill /f /im a.exe", "공백 있음 (기존)"),
    ("taskkill/f /im a.exe",  "공백 없음 ← BL-03"),
    ("shutdown /r /f",        "공백 있음 (기존)"),
    ("shutdown/r /f",         "공백 없음 ← BL-03"),
    ("format c:",             "공백 있음 (기존)"),
    ("format c: 해줘",         "포맷 + 한국어"),
    ("schtasks/delete /tn x", "공백 없음 ← BL-03"),
    ("cipher/w:C",            "공백 없음 ← BL-03"),
]

# 오탐 방지: 정상 입력은 통과해야 한다.
PASS_CASES = [
    ("메모장 열어줘",            "정상 앱 실행"),
    ("볼륨 올려줘",              "정상 시스템 제어"),
    ("rm 이라는 파일 찾아줘",     "rm 단독 — 플래그 없음"),
    ("warm-rf 라는 폴더 만들어",  "단어 내부 rm-rf ← \\b 로 오탐 방지"),
    ("파일 삭제해줘",            "일반 삭제 요청 (HITL이 처리)"),
    ("포맷 방법 알려줘",          "한국어 '포맷'"),
]

print("=== BL-03: 위험 명령어 — 공백 변형도 차단돼야 ===")
for text, why in BLOCK_CASES:
    blocked, _ = check_security(text)
    check(f"{text!r:30} {why}", blocked)

print("\n=== BL-03: 정상 입력 — 통과돼야 (오탐 방지) ===")
for text, why in PASS_CASES:
    blocked, _ = check_security(text)
    check(f"{text!r:30} {why}", not blocked)


# ── BL-02: 부정어 → 캐시 바이패스 ─────────────────────────────────
NEGATION_CASES = [
    ("계산기 말고 다른거 열어",     "BL-02 원본 증상"),
    ("계산기 말구 딴거 켜줘",       "구어체 '말구'"),
    ("메모장 아니라 크롬 열어",     "'아니라'"),
    ("메모장 아니고 계산기",        "'아니고'"),
    ("계산기 대신 다른거 열어",     "'대신'"),
    ("메모장 대신에 워드 켜줘",     "'대신에'"),
    ("계산기 외에 다른거 보여줘",   "'외에'"),
    ("계산기 열지 마",             "'열지 마'"),
    ("메모장 끄지 마",             "'끄지 마'"),
]

# 부정어처럼 보이지만 정상인 입력 — 캐시를 계속 타야 한다.
NO_NEGATION_CASES = [
    ("메모장 열어줘",       "평범한 명령"),
    ("계산기 꺼줘",         "평범한 명령"),
    ("말고기 검색해줘",      "'말고'가 단어 일부 ← 어절 경계로 오탐 방지"),
    ("대신동 지도 보여줘",   "'대신'이 지명 일부"),
    ("볼륨 올려줘",         "시스템 제어"),
]

print("\n=== BL-02: 부정어 → 캐시 바이패스돼야 (LLM이 처리) ===")
for text, why in NEGATION_CASES:
    check(f"{text!r:26} {why}", fast_path.is_compound_command(text))

print("\n=== BL-02: 정상 입력 — 캐시를 계속 타야 (오탐 방지) ===")
for text, why in NO_NEGATION_CASES:
    check(f"{text!r:26} {why}", not fast_path.is_compound_command(text))


# ── BL-02: resolve_fast_path 통합 — 부정어면 캐시를 아예 조회 안 함 ──
print("\n=== BL-02: resolve_fast_path 통합 동작 ===")


class _SpyCache:
    """find()가 호출되는지 감시하는 mock 캐시."""
    def __init__(self):
        self.find_called = False

    def find(self, text):
        self.find_called = True
        class _E:
            pattern = "계산기 열어줘"
        return (_E(), 0.9)

    def execute_sync(self, entry):
        return "✓ 계산기를 실행했습니다."

    def increment_hit(self, pattern):
        pass


spy = _SpyCache()
result = fast_path.resolve_fast_path("계산기 말고 다른거 열어", spy, None)
check("부정어 입력 → 캐시 find() 미호출", not spy.find_called)
check("부정어 입력 → None 반환 (LLM으로 진행)", result is None)

spy2 = _SpyCache()
result2 = fast_path.resolve_fast_path("계산기 열어줘", spy2, None)
check("정상 입력 → 캐시 find() 호출됨", spy2.find_called)
check("정상 입력 → 캐시 결과 반환", result2 == "✓ 계산기를 실행했습니다.")


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
