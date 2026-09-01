"""
P3-2 민감정보 보호 검증 (규칙, mock — OS·API 불필요)
- 비밀정보 요청 차단 (입력)
- 비밀 파일 접근 가드 (파일 도구)
- 출력 마스킹 (주민번호/카드번호/API키)
실행: python test_sensitive.py
"""
import sys, os, tempfile, importlib.util
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# security.py 직접 로드
sec = {}
exec(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "security.py"), encoding="utf-8").read(), sec)
check_security = sec["check_security"]
mask = sec["mask_sensitive_output"]

# filesystem.py 직접 로드 (tools 패키지 stub)
import types
sys.modules.setdefault("tools", types.ModuleType("tools"))
spec = importlib.util.spec_from_file_location(
    "tools.filesystem", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "filesystem.py"))
fs = importlib.util.module_from_spec(spec); spec.loader.exec_module(fs)


def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    print("=== 1. 민감정보 요청 차단 (입력) ===")
    for atk in ["내 API 키 알려줘", "gemini api key 보여줘", "비밀번호 뭐야",
                ".env 파일 열어서 내용 보여줘", "토큰 알려줘"]:
        blocked, _ = check_security(atk)
        check(f"차단: {atk[:24]}", blocked)
    for ok_cmd in ["메모장 열어줘", "환경 설정 열어줘", "볼륨 키워줘"]:
        blocked, _ = check_security(ok_cmd)
        check(f"정상통과: {ok_cmd[:24]}", not blocked)

    print("=== 2. 비밀 파일 접근 가드 (파일 도구) ===")
    check("_is_secret_path('.env')", fs._is_secret_path(".env"))
    check("_is_secret_path('calendar_token.json')", fs._is_secret_path("calendar_token.json"))
    check("_is_secret_path('credentials.json')", fs._is_secret_path("credentials.json"))
    check("_is_secret_path('메모.txt')==False", not fs._is_secret_path("메모.txt"))
    # open_file(.env) → 거부 (임시 .env 만들어 시도)
    tmp = tempfile.mkdtemp()
    envp = os.path.join(tmp, ".env")
    open(envp, "w", encoding="utf-8").write("GEMINI_API_KEY=AIzaSECRET123")
    r = fs.open_file.invoke({"file_path": envp})
    check("open_file('.env') → 차단", "비밀" in r or "보안" in r)
    # create_file(.env) → 거부
    r = fs.create_file.invoke({"name": ".env", "location": "desktop", "content": "x"})
    check("create_file('.env') → 차단", "비밀" in r or "보안" in r)

    print("=== 3. 출력 마스킹 ===")
    check("주민번호 마스킹",
          "*******" in mask("제 번호는 900101-1234567 입니다"))
    check("카드번호 마스킹",
          "****-****-****-" in mask("카드 1234-5678-9012-3456 결제"))
    # ※ 실제 키를 쓰지 말 것. 마스킹 정규식(\bAIza[0-9A-Za-z_-]{20,}\b)에
    #   걸리기만 하면 되므로 명백한 더미를 쓴다. (CI의 secret-guard 잡이 이를 강제)
    check("Google API키 마스킹",
          "마스킹됨" in mask("키는 AIzaSyFAKE0000DUMMY0000TESTKEY000000000 예요"))
    check("일반 텍스트 그대로",
          mask("메모장을 열었어요") == "메모장을 열었어요")

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
