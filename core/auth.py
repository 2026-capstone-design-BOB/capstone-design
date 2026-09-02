"""로컬 API 접근 제어 (BL-14) — 토큰 발급 · 검증.

**위협모델**: 사용자가 열어 둔 **웹페이지**가 `127.0.0.1:8765`에 명령을 밀어넣는 것.
서버가 로컬 파일에 적어 둔 토큰을 웹페이지는 읽을 수 없다 — 이게 방어의 근거다.
(CORS는 응답 *읽기*만 막고 요청 처리는 막지 못하므로 방어가 되지 않는다.
 자세한 이유는 docs/ARCHITECTURE.md § 보안 참조)

⚠️ **stdlib만 import 한다.** CI의 mock 잡은 langgraph·langchain-core만 설치한다
(`.github/workflows/tests.yml`). 여기서 fastapi나 pydantic_settings를 끌어오면
`tests/test_auth.py`가 CI에서 죽는다. FastAPI 결합은 전부 `main.py` 쪽에 둔다.

검증 로직(`is_authorized`)을 순수 함수로 둔 것도 같은 이유다 — 서버 없이 테스트된다.
"""

import os
import secrets

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 요청에 토큰을 싣는 두 경로
HEADER_NAME = "X-Pluiz-Token"   # 일반 HTTP
QUERY_NAME = "token"            # WebSocket(브라우저가 헤더를 못 붙인다) · /cache/ui

# 환경변수 오버라이드 — 테스트·CI가 토큰을 고정하거나 파일 위치를 옮길 때 쓴다
ENV_TOKEN = "PLUIZ_AUTH_TOKEN"
ENV_TOKEN_FILE = "PLUIZ_TOKEN_FILE"

# 인증 면제. `/health`만 — 기동 확인용이고 노출되는 정보가 없다.
EXEMPT_PATHS = frozenset({"/health"})

_DEFAULT_TOKEN_FILE = os.path.join(_BASE_DIR, "cache", ".auth_token")


def token_path() -> str:
    """토큰 파일 경로. `PLUIZ_TOKEN_FILE`로 덮어쓸 수 있다(테스트용)."""
    return os.environ.get(ENV_TOKEN_FILE) or _DEFAULT_TOKEN_FILE


def issue_token() -> str:
    """서버 기동 시 1회. 토큰을 정하고 파일에 기록한 뒤 돌려준다.

    `PLUIZ_AUTH_TOKEN`이 있으면 그 값을 쓴다(고정 토큰이 필요한 상황용).
    없으면 매 기동마다 새로 만든다 — 재시작하면 옛 토큰은 무효가 된다.
    """
    token = os.environ.get(ENV_TOKEN, "").strip() or secrets.token_urlsafe(32)
    path = token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(token)
    return token


def read_token() -> str:
    """현재 유효한 토큰을 읽는다. 없으면 빈 문자열.

    Electron(`electron-ui/main.js`)과 라이브 테스트가 이걸로 같은 값을 얻는다.
    """
    env = os.environ.get(ENV_TOKEN, "").strip()
    if env:
        return env
    try:
        with open(token_path(), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def clear_token() -> None:
    """서버 종료 시 정리. 실패해도 무시한다 — 다음 기동이 어차피 덮어쓴다."""
    try:
        os.remove(token_path())
    except OSError:
        pass


def is_exempt(path: str) -> bool:
    """인증 없이 통과시킬 경로인가."""
    return _normalize(path) in EXEMPT_PATHS


def is_authorized(path: str, header_token, query_token, expected: str) -> bool:
    """요청을 통과시킬지 판정한다. (순수 함수 — 서버 없이 테스트된다)

    `expected`가 비어 있으면 **전부 거부**한다(fail-closed). 서버는 기동 시 항상
    토큰을 발급하므로, 비어 있다는 건 뭔가 깨졌다는 뜻이다. 인증을 통째로 끄고
    싶으면 `.env`의 `AUTH_ENABLED=false`를 쓴다 — 그 판단은 `main.py`가 한다.
    """
    if is_exempt(path):
        return True
    if not expected:
        return False
    for provided in (header_token, query_token):
        if provided and secrets.compare_digest(str(provided), expected):
            return True
    return False


def _normalize(path: str) -> str:
    """`/health/` 같은 변형을 `/health`로. 빈 문자열은 `/`로 본다."""
    p = (path or "/").split("?", 1)[0]
    return p.rstrip("/") or "/"
