"""BL-14 로컬 API 접근 제어 — 인증 로직 단위 테스트 (mock, 서버·OS 불필요)
실행: python tests/test_auth.py

`core/auth.py`는 stdlib만 쓰므로 이 테스트는 CI(langgraph·langchain-core만 설치)에서도 돈다.
FastAPI 결합부(미들웨어·WS 검사)는 `main.py`에 있고 라이브 A-01~A-03이 검증한다.
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ⚠️ 실제 cache/.auth_token을 건드리지 않도록 임시 경로로 돌린다.
_TMP = tempfile.mkdtemp()
os.environ["PLUIZ_TOKEN_FILE"] = os.path.join(_TMP, ".auth_token")
os.environ.pop("PLUIZ_AUTH_TOKEN", None)

from core import auth  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0


def check(name, cond):
    global passed, total
    total += 1
    passed += bool(cond)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}")


# ══════════════════════════════════════════════════════════════════
print("=== 토큰 발급 · 읽기 ===")
# ══════════════════════════════════════════════════════════════════
t1 = auth.issue_token()
check("issue_token: 충분히 긴 토큰", len(t1) >= 32)
check("issue_token: 파일 생성됨", os.path.exists(auth.token_path()))
check("read_token: 발급값과 일치", auth.read_token() == t1)

t2 = auth.issue_token()
check("재발급하면 값이 바뀐다 (재시작 시 옛 토큰 무효)", t2 != t1)
check("read_token: 최신값을 읽는다", auth.read_token() == t2)

auth.clear_token()
check("clear_token: 파일 삭제됨", not os.path.exists(auth.token_path()))
check("파일 없으면 read_token == ''", auth.read_token() == "")
auth.clear_token()  # 두 번 불러도 죽지 않아야 한다
check("clear_token 재호출해도 예외 없음", True)

os.environ["PLUIZ_AUTH_TOKEN"] = "FIXED-TOKEN-FOR-TEST"
check("env 지정 시 issue_token이 그 값을 쓴다", auth.issue_token() == "FIXED-TOKEN-FOR-TEST")
check("env 지정 시 read_token도 그 값", auth.read_token() == "FIXED-TOKEN-FOR-TEST")
os.environ.pop("PLUIZ_AUTH_TOKEN")
check("env 해제 후엔 파일값으로 돌아온다", auth.read_token() == "FIXED-TOKEN-FOR-TEST")

TOK = auth.issue_token()

# ══════════════════════════════════════════════════════════════════
print("=== 면제 경로 ===")
# ══════════════════════════════════════════════════════════════════
check("/health 면제", auth.is_exempt("/health"))
check("/health/ 도 면제 (슬래시 변형)", auth.is_exempt("/health/"))
check("/chat 은 면제 아님", not auth.is_exempt("/chat"))
check("/healthz 는 면제 아님 (부분일치 금지)", not auth.is_exempt("/healthz"))
check("/api/config 는 면제 아님", not auth.is_exempt("/api/config"))
check("/cache 는 면제 아님", not auth.is_exempt("/cache"))

# ══════════════════════════════════════════════════════════════════
print("=== is_authorized — 통과 조건 ===")
# ══════════════════════════════════════════════════════════════════
check("면제 경로는 토큰 없이 통과",
      auth.is_authorized("/health", None, None, TOK))
check("헤더 토큰 일치 → 통과",
      auth.is_authorized("/chat", TOK, None, TOK))
check("쿼리 토큰 일치 → 통과 (WS·대시보드)",
      auth.is_authorized("/ws", None, TOK, TOK))
check("헤더가 틀려도 쿼리가 맞으면 통과",
      auth.is_authorized("/chat", "wrong", TOK, TOK))

# ══════════════════════════════════════════════════════════════════
print("=== is_authorized — 차단 조건 (BL-14 공격 시나리오) ===")
# ══════════════════════════════════════════════════════════════════
check("토큰 없는 웹페이지 fetch → 차단",
      not auth.is_authorized("/chat", None, None, TOK))
check("빈 문자열 토큰 → 차단",
      not auth.is_authorized("/chat", "", "", TOK))
check("틀린 토큰 → 차단",
      not auth.is_authorized("/chat", "wrong-token", None, TOK))
check("토큰 앞부분만 맞아도 차단",
      not auth.is_authorized("/chat", TOK[:10], None, TOK))
check("뒤에 문자가 붙으면 차단",
      not auth.is_authorized("/chat", TOK + "x", None, TOK))
check("공백이 섞이면 차단",
      not auth.is_authorized("/chat", " " + TOK, None, TOK))
check("대소문자 변형 차단",
      not auth.is_authorized("/chat", "abcDEF", None, "ABCdef"))
check("WS도 토큰 없으면 차단 (CORS가 적용되지 않는 경로)",
      not auth.is_authorized("/ws", None, None, TOK))
check("expected가 비면 전부 차단 (fail-closed)",
      not auth.is_authorized("/chat", TOK, TOK, ""))
check("expected가 비어도 /health는 통과 (기동 확인 경로)",
      auth.is_authorized("/health", None, None, ""))

# ══════════════════════════════════════════════════════════════════
print("=== 구현 간 계약 (Python 상수 ↔ JS 리터럴 드리프트 방지) ===")
# ══════════════════════════════════════════════════════════════════
# 한글이 든 소스라 encoding="utf-8" 필수 (CLAUDE.md 절대규칙 7)
def read(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


check("헤더 이름 상수", auth.HEADER_NAME == "X-Pluiz-Token")
check("쿼리 이름 상수", auth.QUERY_NAME == "token")

renderer = read("electron-ui", "renderer", "index.html")
check("renderer가 같은 헤더 이름을 쓴다", auth.HEADER_NAME in renderer)
check("renderer WS URL에 토큰을 붙인다", "?token=" in renderer or "token=" in renderer)

electron_main = read("electron-ui", "main.js")
check("Electron이 토큰 파일명을 안다", ".auth_token" in electron_main)
check("Electron이 get-token IPC를 제공한다", "get-token" in electron_main)
check("preload가 getToken을 노출한다", "getToken" in read("electron-ui", "preload.js"))

server = read("main.py")
check("main.py가 core.auth를 쓴다", "core.auth" in server or "from core import auth" in server)
check("main.py CORS가 더 이상 '*'가 아니다", 'allow_origins=["*"]' not in server)
check("ConfigRequest.provider가 Literal로 좁혀졌다",
      'Literal["gemini", "claude", "openai"]' in server or 'Literal["gemini","claude","openai"]' in server)

check(".gitignore가 토큰 파일을 무시한다", ".auth_token" in read(".gitignore"))

print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
