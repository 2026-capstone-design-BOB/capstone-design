"""
Pluiz v2 - FastAPI 서버
Electron UI와 HTTP/WebSocket으로 통신
"""

import asyncio
from contextlib import asynccontextmanager
import os
from typing import Literal

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# BUG-02: create_task 참조 손실 방지용 백그라운드 태스크 집합
_bg_tasks: set = set()

from config.settings import get_settings
from core import auth
from core.graph_agent import get_graph_agent
from core.security import check_security
from services.tts import get_tts
from services.stt import get_stt

# 서버가 이번 기동에 발급한 토큰. lifespan에서 채워진다.
_AUTH_TOKEN = ""

# ── 화면 감시 알림 채널 (Phase 2) ─────────────────────────────────
# 감시(core/screen_monitor.py)는 **턴이 끝난 뒤에** 도는 백그라운드 스레드라
# 응답으로 돌려줄 곳이 없다. 열려 있는 /ws로 서버가 직접 밀어넣는다.
_ws_clients: set = set()
_main_loop = None                 # 감시 스레드가 이벤트 루프로 건너오는 다리
_pending_notifications: list = [] # 붙어 있는 UI가 없을 때 잠시 보관
_MAX_PENDING = 5


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """기동 시 토큰 발급 → `cache/.auth_token`, 종료 시 정리. (BL-14)

    Electron(`electron-ui/main.js`)과 라이브 테스트가 이 파일을 읽어 같은 값을 얻는다.
    웹페이지는 로컬 파일을 못 읽는다 — 그게 이 방어의 근거다.
    """
    global _AUTH_TOKEN
    s = get_settings()

    # ⚠️ 발급 **전에** 포트를 확인한다. uvicorn은 소켓을 잡기 전에 lifespan을 돌리므로,
    # 서버가 이미 떠 있는데 또 띄우면 두 번째가 죽으면서 **첫 번째의 토큰 파일을
    # 덮어쓰고 지운다.** 그러면 멀쩡히 돌던 UI가 재연결에서 토큰을 잃는다.
    # (launch.bat을 두 번 실행하면 실제로 일어난다 — 2026-09-02 실측으로 발견)
    if auth.port_in_use(s.server_host, s.server_port):
        print(f"[auth] ⚠️ {s.server_host}:{s.server_port} 에 이미 서버가 있습니다. "
              f"토큰을 건드리지 않고 종료합니다 (기존 서버와 UI는 그대로 동작).")
        yield
        return

    _AUTH_TOKEN = auth.issue_token()
    if s.auth_enabled:
        print(f"[auth] 접근 토큰 발급됨 → {auth.token_path()}")
        print(f"[auth] 캐시 대시보드: http://{s.server_host}:{s.server_port}"
              f"/cache/ui?{auth.QUERY_NAME}={_AUTH_TOKEN}")
    else:
        print("[auth] ⚠️ AUTH_ENABLED=false — 로컬 API 접근 제어가 꺼져 있습니다 (BL-14)")
    # 화면 감시가 UI로 말을 걸 수 있게 다리를 놓는다. 감시 스레드는 이벤트 루프
    # 밖에 있으므로, 여기서 잡아 둔 루프로 run_coroutine_threadsafe 해서 건너온다.
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    from core import screen_monitor, pointer
    screen_monitor.set_notifier(_push_from_monitor)
    # 포인팅 표시(M4)도 **같은 통로**로 나간다. 두 번째 채널을 만들면 토큰·수명
    # 관리가 두 벌이 된다. → docs/design/M4_포인팅_확대.md §3-2
    pointer.set_notifier(_push_from_monitor)

    try:
        yield
    finally:
        # 서버가 내려가면 감시도 멈춘다. 안 그러면 알릴 곳도 없이 화면만 계속 나간다.
        screen_monitor.set_notifier(None)
        screen_monitor.reset_monitor()
        # 서버가 내려가면 표시도 없앤다. 남겨 두면 «표시 중»으로 알고 캡처가
        # 기다리는 상태가 되고, 정작 지울 UI는 없다.
        pointer.set_notifier(None)
        pointer.reset()
        # 내 토큰일 때만 지운다 (위와 같은 이유의 2차 방어)
        auth.clear_token(expected=_AUTH_TOKEN)


app = FastAPI(title="Pluiz v2", version="2.0.0", lifespan=lifespan)

# ── BL-14: 로컬 API 접근 제어 ─────────────────────────────────────
# 이 서버는 PC를 조작한다. 인증이 없으면 사용자가 열어 둔 **아무 웹페이지**가
# fetch 한 줄로 명령을 밀어넣을 수 있다. 방어는 아래 세 겹이고, 실질적 방어는 ③이다.
#
# ① Host 검사 — DNS 리바인딩 차단. 공격 도메인이 127.0.0.1로 해석되면 페이지가
#    서버와 **동일 출처**가 되어 CORS가 통째로 무력화된다. Host를 고정해 그걸 막는다.
# ② CORS — `allow_origins`가 "null"인 건 오타가 아니다. Electron 렌더러는
#    `loadFile`(file://)이라 브라우저가 `Origin: null`을 보낸다. 이 값을 허용하지
#    않으면 UI 자신이 막힌다. ⚠️ 그러나 **CORS는 응답 읽기만 막고 요청 처리는 막지
#    못한다** — 명령은 그대로 실행된다. 그래서 CORS는 방어가 아니라 defense-in-depth다.
# ③ 토큰 — `auth_guard` 미들웨어 + `/ws` 검사. 웹페이지는 로컬 파일을 못 읽으므로
#    서버가 `cache/.auth_token`에 적어 둔 값을 알 수 없다. **이게 진짜 방어다.**
#
# 배경: docs/BACKLOG.md BL-14 · docs/ARCHITECTURE.md § 보안 — 5층 방어
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null"],          # file:// 렌더러. 위 ② 주석 참조 — 되돌리지 말 것
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", auth.HEADER_NAME],
)


@app.middleware("http")
async def auth_guard(request, call_next):
    """토큰 없는 HTTP 요청을 401로 막는다.

    ⚠️ 이 미들웨어는 **WebSocket을 타지 않는다.** `/ws`는 엔드포인트 안에서 따로 막는다.
    """
    # CORS 프리플라이트(OPTIONS)는 통과시킨다. `X-Pluiz-Token`은 safelisted 헤더가
    # 아니라 렌더러의 모든 요청이 프리플라이트를 거치는데, 프리플라이트에는 그 헤더가
    # 실리지 않는다. 여기서 401을 주면 **UI 자신이 전부 막힌다.**
    # 프리플라이트는 아무것도 실행하지 않고 정보도 주지 않으므로 안전하다.
    if request.method == "OPTIONS":
        return await call_next(request)

    if get_settings().auth_enabled and not auth.is_authorized(
        request.url.path,
        request.headers.get(auth.HEADER_NAME),
        request.query_params.get(auth.QUERY_NAME),
        _AUTH_TOKEN,
    ):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)


# ── 데이터 모델 ───────────────────────────────────────────────────

class TextRequest(BaseModel):
    text: str
    thread_id: str = "default"
    use_tts: bool = False


class TextResponse(BaseModel):
    response: str
    thread_id: str


class ConfigRequest(BaseModel):
    # ⚠️ str이면 안 된다 — save_config()가 이 값을 `{PROVIDER}_API_KEY`로 만들어
    # .env에 그대로 쓴다. 개행이 섞이면 .env 인젝션이 된다 (BL-14 ③).
    # config/settings.py의 llm_provider와 같은 타입이어야 한다.
    provider: Literal["gemini", "claude", "openai"]
    api_key: str


class WakeWordRequest(BaseModel):
    """웨이크워드 설정. 사용자가 직접 정한다."""
    wake_words: str = ""      # 쉼표 구분. 빈 문자열이면 기본값("플루이즈") 사용
    enabled: bool = True


# ── REST 엔드포인트 ────────────────────────────────────────────────

@app.get("/health")
async def health():
    """서버 상태 확인."""
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/config")
async def get_config():
    """현재 LLM 설정 반환."""
    s = get_settings()
    return {
        "provider": s.llm_provider,
        "has_key": bool(s.active_api_key),
        "model": s.active_model,
        "wake_words": s.wake_words,
        "wake_word_enabled": s.wake_word_enabled,
        # 사용자가 아무것도 안 정했을 때 실제로 쓰이는 값 (UI 플레이스홀더용)
        "wake_words_default": "플루이즈",
    }


@app.post("/api/config")
async def save_config(req: ConfigRequest):
    """API 키 및 provider 저장 → 에이전트 재초기화."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    # .env 파일 읽기
    lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # provider는 Literal로 이미 좁혀졌지만 api_key는 자유 문자열이다.
    # 개행이 들어오면 .env에 임의의 줄을 추가할 수 있으므로 여기서 자른다 (BL-14 ③).
    api_key = req.api_key.replace("\r", "").replace("\n", "").strip()
    key_var = f"{req.provider.upper()}_API_KEY"
    provider_found = key_found = False
    new_lines: list[str] = []

    for line in lines:
        if line.startswith("LLM_PROVIDER="):
            new_lines.append(f"LLM_PROVIDER={req.provider}\n")
            provider_found = True
        elif line.startswith(key_var + "="):
            new_lines.append(f"{key_var}={api_key}\n")
            key_found = True
        else:
            new_lines.append(line)

    if not provider_found:
        new_lines.insert(0, f"LLM_PROVIDER={req.provider}\n")
    if not key_found:
        new_lines.append(f"{key_var}={api_key}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # 캐시 초기화 → 다음 get_settings() 호출에서 .env 재로드
    get_settings.cache_clear()

    # 에이전트 재초기화
    from core.graph_agent import reset_graph_agent
    reset_graph_agent()

    print(f"[config] provider={req.provider} key=***{api_key[-4:] if api_key else ''} 저장됨")
    return {"status": "ok", "provider": req.provider}


def _write_env(updates: dict) -> None:
    """`.env`의 키를 갱신(없으면 추가)한다.

    ⚠️ `get_settings`는 `@lru_cache`라 파일만 고치면 옛 값이 계속 쓰인다.
    반드시 `cache_clear()`까지 해야 한다. (CLAUDE.md 절대규칙 4)
    """
    NEWLINE = chr(10)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}" + NEWLINE)
        else:
            out.append(line)
    for k, v in remaining.items():
        if out and not out[-1].endswith(NEWLINE):
            out.append(NEWLINE)
        out.append(f"{k}={v}" + NEWLINE)

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(out)

    get_settings.cache_clear()


@app.post("/api/wakeword")
async def save_wakeword(req: WakeWordRequest):
    """웨이크워드 저장.

    웨이크워드 프로세스(`services/wakeword.py`)는 Electron이 띄운 **별도 프로세스**라
    서버가 직접 못 바꾼다. 대신 그쪽이 주기적으로 `.env`를 다시 읽으므로
    **재시작 없이 몇 초 안에 반영된다.**
    """
    words = ",".join(w.strip() for w in req.wake_words.split(",") if w.strip())
    _write_env({
        "WAKE_WORDS": words,
        "WAKE_WORD_ENABLED": "true" if req.enabled else "false",
    })
    print(f"[config] 웨이크워드 저장: {words or chr(40)+chr(41)} enabled={req.enabled}")
    return {
        "status": "ok",
        "wake_words": words,
        "enabled": req.enabled,
        "note": "웨이크워드 서비스가 10초 안에 자동 반영합니다.",
    }


@app.post("/chat")
async def chat(req: TextRequest):
    """
    텍스트 명령 처리.
    Electron UI의 채팅 입력창에서 호출.
    """
    try:
        # ── 보안 필터 (LLM 판단 전 결정론적 차단) ─────────────────
        blocked, reason = check_security(req.text)
        if blocked:
            print(f"[Security] 차단됨: {repr(req.text[:60])}")
            return {"response": reason, "thread_id": req.thread_id}

        agent = get_graph_agent()
        response = await agent.run_async(req.text, thread_id=req.thread_id)

        if req.use_tts:
            tts = get_tts()
            # BUG-02: 참조를 _bg_tasks에 보관해 GC로 인한 태스크 중단 방지
            _task = asyncio.create_task(tts.speak_async(response))
            _bg_tasks.add(_task)
            _task.add_done_callback(_bg_tasks.discard)

        return {"response": response, "thread_id": req.thread_id}
    except Exception as e:
        print(f"[/chat 오류] {type(e).__name__}: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "response": f"처리 중 오류: {e}", "thread_id": req.thread_id}
        )


@app.post("/voice")
async def voice_input(audio: UploadFile = File(...),
                      thread_id: str = Form("default"),
                      use_tts: bool = Form(True)):
    """
    음성 파일 업로드 → STT → 에이전트 처리 → (TTS) 응답.
    Electron에서 마이크 녹음 후 전송.

    ⚠️ **`Form(...)`을 빼지 말 것.** 스칼라 파라미터를 그냥 두면 FastAPI가 이걸
    **쿼리 파라미터**로 해석해서, 렌더러가 FormData로 보내는 `thread_id`를 통째로
    무시하고 항상 "default"를 쓴다. 그러면 **음성과 텍스트가 서로 다른 대화가 된다.**

    2026-09-03 실기에서 이것 때문에 삭제 승인이 무너졌다. 텍스트로 "그 파일 지워줘"
    → 승인 질문(thread=pluiz_…)이 뜬 상태에서 음성으로 "어 삭제해 줘"라고 하면
    thread=default 로 가서 승인이 아니라 **새 명령**이 됐고("무엇을 삭제할까요?"),
    텍스트 쪽 승인 대기는 100초 뒤 엉뚱한 "메모장 열어줘"를 삼켰다.
    """
    audio_bytes = await audio.read()

    # STT
    stt = get_stt()
    text = stt.transcribe_bytes(audio_bytes)
    if not text:
        return {"error": "음성을 인식하지 못했습니다.", "text": "", "response": ""}

    # ── 보안 필터 ─────────────────────────────────────────────────
    blocked, reason = check_security(text)
    if blocked:
        print(f"[Security] 차단됨(voice): {repr(text[:60])}")
        if use_tts:
            tts = get_tts()
            audio_bytes_response = await tts.to_bytes_async(reason)
            import base64
            return {"text": text, "response": reason,
                    "audio_base64": base64.b64encode(audio_bytes_response).decode()}
        return {"text": text, "response": reason}

    # 에이전트
    agent = get_graph_agent()
    response = await agent.run_async(text, thread_id=thread_id)

    # TTS
    if use_tts:
        tts = get_tts()
        audio_bytes_response = await tts.to_bytes_async(response)
        # Base64로 인코딩해서 반환
        import base64
        audio_b64 = base64.b64encode(audio_bytes_response).decode()
        return {
            "text": text,
            "response": response,
            "audio_base64": audio_b64,
        }

    return {"text": text, "response": response}


@app.get("/history")
async def get_history(n: int = 20):
    """최근 대화 히스토리 반환."""
    from memory.session import SessionMemory
    memory = SessionMemory()
    return {"history": memory.get_recent(n)}


@app.delete("/history")
async def clear_history():
    """대화 히스토리 초기화."""
    from memory.session import SessionMemory
    memory = SessionMemory()
    memory.clear()
    return {"status": "cleared"}



# ── 즐겨찾기 (커스텀 명령) ─────────────────────────────────────────

import json as _json_module

_FAV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "favorites.json")


def _load_favorites() -> list[dict]:
    if not os.path.exists(_FAV_PATH):
        return []
    try:
        with open(_FAV_PATH, encoding="utf-8") as f:
            return _json_module.load(f)
    except Exception:
        return []


def _save_favorites(favs: list[dict]):
    os.makedirs(os.path.dirname(_FAV_PATH), exist_ok=True)
    with open(_FAV_PATH, "w", encoding="utf-8") as f:
        _json_module.dump(favs, f, ensure_ascii=False, indent=2)


class FavoriteRequest(BaseModel):
    label: str    # 표시 이름
    command: str  # 실행할 명령


@app.get("/favorites")
async def get_favorites():
    """즐겨찾기 목록 반환."""
    return {"favorites": _load_favorites()}


@app.post("/favorites")
async def add_favorite(req: FavoriteRequest):
    """즐겨찾기 추가."""
    favs = _load_favorites()
    # 같은 command 중복 방지
    if any(f["command"] == req.command for f in favs):
        return {"status": "exists"}
    favs.append({"label": req.label, "command": req.command})
    _save_favorites(favs)
    return {"status": "ok", "count": len(favs)}


@app.delete("/favorites/{index}")
async def delete_favorite(index: int):
    """인덱스로 즐겨찾기 삭제."""
    favs = _load_favorites()
    if 0 <= index < len(favs):
        removed = favs.pop(index)
        _save_favorites(favs)
        return {"status": "ok", "removed": removed}
    return {"status": "not_found"}


# ── 캐시 대시보드 HTML (개발용) ───────────────────────────────────
_CACHE_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pluiz 캐시 대시보드 (dev)</title>
<style>
  :root{--bg:#0f1115;--card:#1a1e26;--line:#2a2f3a;--fg:#e6e8ec;--mut:#9aa3b2;--acc:#5b8cff;--seed:#8a8f9a;--dyn:#33c48d;--danger:#ff6b6b}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;padding:20px}
  h1{font-size:18px;margin:0 0 4px} h2{font-size:15px;margin:22px 0 8px;color:var(--fg)}
  .mut{color:var(--mut)} code{background:#0b0d11;border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-family:ui-monospace,Consolas,monospace}
  .stats{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:96px}
  .stat b{display:block;font-size:22px} .stat span{color:var(--mut);font-size:12px}
  .bar{display:flex;gap:8px;margin:10px 0 4px;flex-wrap:wrap}
  button{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:7px 12px;cursor:pointer;font-size:13px}
  button:hover{border-color:var(--acc)} button.danger{border-color:var(--danger);color:var(--danger)}
  table{width:100%;border-collapse:collapse;margin-top:6px;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}
  th{color:var(--mut);font-weight:500;background:#151922} tr:last-child td{border-bottom:none}
  .pill{font-size:11px;padding:1px 7px;border-radius:20px;border:1px solid var(--line)}
  .pill.dyn{color:var(--dyn);border-color:#1e5b45} .pill.seed{color:var(--seed)}
  .del{color:var(--danger);border-color:#5b2323;padding:3px 9px}
  .empty{color:var(--mut);padding:14px;text-align:center}
</style></head>
<body>
  <h1>Pluiz 캐시 대시보드 <span class="mut" style="font-size:12px">/cache/ui · 개발용</span></h1>
  <div class="mut">학습된 명령을 조회·삭제하고 스키마를 확인. 시드는 삭제 보호됨.</div>
  <div class="stats" id="stats"></div>
  <div class="bar">
    <button onclick="load()">↻ 새로고침</button>
    <button class="danger" onclick="clearDynamic()">동적 전체 초기화</button>
    <span class="mut" id="msg"></span>
  </div>

  <h2>동적 학습 <span class="mut" id="dcount"></span></h2>
  <table><thead><tr><th>표현(pattern)</th><th>도구</th><th>hit</th><th>learned_at</th><th>last_used</th><th></th></tr></thead>
    <tbody id="dyn"></tbody></table>

  <h2>시드 <span class="mut" id="scount"></span> <span class="mut">(고정·삭제 보호)</span></h2>
  <table><thead><tr><th>표현</th><th>도구</th><th>hit</th></tr></thead><tbody id="seed"></tbody></table>

  <h2>학습 가능 도구 (whitelist)</h2>
  <div id="wl" class="mut"></div>

  <h2>데이터 스키마 · CacheEntry</h2>
  <table><thead><tr><th>필드</th><th>타입</th><th>설명</th></tr></thead><tbody>
    <tr><td><code>pattern</code></td><td>str</td><td>정규화된 사용자 표현(키)</td></tr>
    <tr><td><code>tool_calls</code></td><td>list[{name:str, args:dict}]</td><td>캐노니컬 도구 호출(파라미터 미저장)</td></tr>
    <tr><td><code>response_template</code></td><td>str</td><td>응답 문구</td></tr>
    <tr><td><code>hit_count</code></td><td>int</td><td>사용 횟수(LRU 보호 기준)</td></tr>
    <tr><td><code>is_seed</code></td><td>bool</td><td>시드 여부 → true면 삭제 보호</td></tr>
    <tr><td><code>source</code></td><td>"seed" | "dynamic"</td><td>출처</td></tr>
    <tr><td><code>learned_at</code></td><td>str (ISO8601)</td><td>학습 시각</td></tr>
    <tr><td><code>last_used</code></td><td>str (ISO8601)</td><td>마지막 사용 시각</td></tr>
  </tbody></table>

  <h2>API</h2>
  <table><thead><tr><th>메서드</th><th>경로</th><th>설명</th></tr></thead><tbody>
    <tr><td>GET</td><td><code>/cache</code></td><td>통계+동적+시드 (JSON)</td></tr>
    <tr><td>DELETE</td><td><code>/cache</code></td><td>동적 전체 초기화(시드 유지)</td></tr>
    <tr><td>DELETE</td><td><code>/cache/entry?pattern=</code></td><td>동적 개별 삭제(시드 거부)</td></tr>
  </tbody></table>

<script>
// BL-14: 이 페이지의 fetch에도 토큰이 필요하다. 주소창으로는 헤더를 못 붙이므로
// `?token=`으로 들어오고, 서버가 그 값을 아래 자리에 박아 내려준다.
const TOKEN='__PLUIZ_TOKEN__';
const _fetch=window.fetch.bind(window);
window.fetch=(u,o={})=>{o.headers={...(o.headers||{}),'X-Pluiz-Token':TOKEN};return _fetch(u,o);};
const $=id=>document.getElementById(id);
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function load(){
  const r=await fetch('/cache'); const d=await r.json();
  const s=d.stats;
  $('stats').innerHTML=[['total',s.total],['seed',s.seed],['dynamic',s.dynamic],['max_dynamic',s.max_dynamic],['learning',s.learning_enabled]]
    .map(([k,v])=>`<div class="stat"><b>${esc(v)}</b><span>${k}</span></div>`).join('');
  $('dcount').textContent='('+d.dynamic.length+')'; $('scount').textContent='('+d.seeds.length+')';
  $('dyn').innerHTML=d.dynamic.length? d.dynamic.map(e=>`<tr>
    <td>${esc(e.pattern)} <span class="pill dyn">dynamic</span></td><td>${esc((e.tools||[]).join(', '))}</td>
    <td>${esc(e.hit_count)}</td><td class="mut">${esc(e.learned_at||'')}</td><td class="mut">${esc(e.last_used||'')}</td>
    <td><button class="del" onclick="delEntry('${esc(e.pattern)}')">삭제</button></td></tr>`).join('')
    : '<tr><td colspan=6 class="empty">학습된 동적 항목 없음</td></tr>';
  $('seed').innerHTML=d.seeds.map(e=>`<tr><td>${esc(e.pattern)} <span class="pill seed">seed</span></td>
    <td>${esc((e.tools||[]).join(', '))}</td><td>${esc(e.hit_count)}</td></tr>`).join('');
  $('wl').innerHTML=(d.learnable_tools||[]).map(t=>`<code>${esc(t)}</code>`).join(' ');
}
async function delEntry(p){ if(!confirm('삭제: '+p+' ?'))return;
  await fetch('/cache/entry?pattern='+encodeURIComponent(p),{method:'DELETE'}); $('msg').textContent='삭제됨: '+p; load(); }
async function clearDynamic(){ if(!confirm('동적 학습 전체 초기화? (시드는 유지)'))return;
  const r=await fetch('/cache',{method:'DELETE'}); const d=await r.json(); $('msg').textContent=(d.removed||0)+'개 초기화됨'; load(); }
load();
</script></body></html>"""


# ── 캐시 관리 (P4-3) ──────────────────────────────────────────────

@app.get("/cache")
async def cache_view():
    """캐시 통계 + 동적/시드 목록 (JSON API). 사람이 보긴 /cache/ui 권장."""
    from core.command_cache import get_cache
    c = get_cache()
    return {"stats": c.stats(), "dynamic": c.list_dynamic(),
            "seeds": c.list_seeds(), "learnable_tools": c.learnable_tools()}


@app.get("/cache/ui")
async def cache_dashboard():
    """개발용 캐시 대시보드(HTML) — 조회·삭제·초기화 + 스키마/타입 문서.

    `?token=`으로 들어온다(서버 기동 로그에 전체 URL이 찍힌다). 여기까지 온 요청은
    `auth_guard`를 이미 통과했으므로, 페이지 안의 fetch가 쓸 토큰을 박아 내려준다.
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_CACHE_DASHBOARD_HTML.replace("__PLUIZ_TOKEN__", _AUTH_TOKEN))


@app.delete("/cache")
async def cache_clear_dynamic():
    """동적 학습 전체 초기화(오염 롤백). 시드는 유지."""
    from core.command_cache import get_cache
    removed = get_cache().clear_dynamic()
    return {"status": "ok", "removed": removed}


@app.delete("/cache/entry")
async def cache_delete_entry(pattern: str):
    """동적 항목 개별 삭제(?pattern=). 시드는 보호(거부)."""
    from core.command_cache import get_cache
    ok = get_cache().delete_entry(pattern)
    return {"status": "ok" if ok else "not_found_or_seed", "pattern": pattern}


# ── 화면 감시 → UI 푸시 ───────────────────────────────────────────

def _push_from_monitor(payload: dict) -> None:
    """감시 **스레드**에서 호출된다. 이벤트 루프로 넘겨 실제 전송을 시킨다.

    ⚠️ 여기서 직접 `send_json`을 부르면 안 된다 — 다른 스레드다.
    """
    loop = _main_loop
    if loop is None or loop.is_closed():
        print(f"[Monitor] 서버 루프가 없어 알림을 전달하지 못했습니다: {payload}")
        return
    try:
        asyncio.run_coroutine_threadsafe(_broadcast(payload), loop)
    except Exception as e:
        print(f"[Monitor] 알림 전달 실패: {type(e).__name__}: {e}")


async def _broadcast(payload: dict) -> None:
    """열려 있는 모든 /ws로 payload를 보낸다. 알림이면 TTS 음성을 함께 싣는다.

    감시는 **사용자가 화면을 안 보고 있을 때** 쓰는 기능이라 소리까지 있어야
    실제로 전달된다. TTS가 실패해도 텍스트는 보낸다(기존 /ws end 페이로드와 같은 방식).
    """
    if payload.get("type") == "notify" and payload.get("text"):
        try:
            import base64
            spoken = payload["text"].replace(chr(0x1F441), " ").strip()
            audio = await get_tts().to_bytes_async(spoken)
            payload = {**payload, "audio_base64": base64.b64encode(audio).decode()}
        except Exception as e:
            print(f"[Monitor] 알림 TTS 실패(텍스트만 전송): {e}")

    sent = 0
    for ws in list(_ws_clients):
        try:
            await ws.send_json(payload)
            sent += 1
        except Exception:
            _ws_clients.discard(ws)

    if sent == 0 and payload.get("type") == "notify":
        # 붙어 있는 UI가 없다 → **버리지 않는다.** 감시가 말없이 사라지는 것은
        # 이 기능이 고치려는 바로 그 문제다. 다음 연결 때 전한다.
        _pending_notifications.append(payload)
        del _pending_notifications[:-_MAX_PENDING]
        print(f"[Monitor] 연결된 UI가 없어 알림을 보관합니다 "
              f"({len(_pending_notifications)}건)")


async def _flush_pending(websocket: WebSocket) -> None:
    """UI가 (다시) 붙었을 때 보관해 둔 알림을 흘려보낸다."""
    while _pending_notifications:
        payload = _pending_notifications.pop(0)
        try:
            await websocket.send_json(payload)
        except Exception:
            _pending_notifications.insert(0, payload)
            return


# ── WebSocket (실시간 스트리밍) ───────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket으로 스트리밍 응답.
    토큰 단위로 UI에 실시간 전송.
    use_tts=true 시 end 메시지에 audio_base64 포함.

    ⚠️ **인증을 여기서 직접 한다.** `auth_guard` HTTP 미들웨어는 WebSocket을 타지 않고,
    **CORS는 WebSocket에 아예 적용되지 않는다** — 웹페이지가
    `new WebSocket('ws://127.0.0.1:8765/ws')`로 그냥 붙을 수 있어서 fetch보다 큰 구멍이었다.
    브라우저 WS는 헤더를 못 붙이므로 토큰을 쿼리(`?token=`)로 받는다. (BL-14)
    """
    if get_settings().auth_enabled and not auth.is_authorized(
        "/ws", None, websocket.query_params.get(auth.QUERY_NAME), _AUTH_TOKEN
    ):
        # accept() 하기 전에 끊는다 — 핸드셰이크 자체를 거절한다.
        await websocket.close(code=1008)   # 1008 = Policy Violation
        return

    await websocket.accept()
    agent = get_graph_agent()

    # 감시 알림을 밀어넣을 대상으로 등록한다(인증을 통과한 뒤에만).
    _ws_clients.add(websocket)
    try:
        # UI가 새로 떴거나 재연결됐을 수 있다 — 놓친 알림과 현재 감시 상태를 맞춘다.
        await _flush_pending(websocket)
        try:
            from core.screen_monitor import get_monitor
            st = get_monitor().status()
            await websocket.send_json({"type": "watch_state",
                                       "active": bool(st.get("active")),
                                       "what": st.get("what", "")})
        except Exception as e:
            print(f"[Monitor] 감시 상태 동기화 생략(무시): {e}")

        while True:
            data = await websocket.receive_json()
            text = data.get("text", "")
            thread_id = data.get("thread_id", "default")
            use_tts = data.get("use_tts", False)

            if not text:
                continue

            # ── 보안 필터 ─────────────────────────────────────────
            blocked, reason = check_security(text)
            if blocked:
                print(f"[Security] 차단됨(ws): {repr(text[:60])}")
                await websocket.send_json({"type": "start"})
                await websocket.send_json({"type": "chunk", "content": reason})
                await websocket.send_json({"type": "end", "full": reason})
                continue

            await websocket.send_json({"type": "start"})

            full_response = ""
            async for chunk in agent.stream(text, thread_id=thread_id):
                full_response += chunk
                await websocket.send_json({"type": "chunk", "content": chunk})

            # BUG-01: session_memory 저장은 stream() 내부에서 경로별로 처리.
            # 여기서 중복 저장하지 않음 (캐시/제어명령 경로에서 이중 저장되던 버그 수정).

            # TTS 요청 시 MP3를 base64로 함께 전송
            end_payload: dict = {"type": "end", "full": full_response}
            if use_tts and full_response:
                try:
                    import base64
                    tts = get_tts()
                    audio_bytes = await tts.to_bytes_async(full_response)
                    end_payload["audio_base64"] = base64.b64encode(audio_bytes).decode()
                except Exception as tts_err:
                    print(f"[TTS] 오류: {tts_err}")

            await websocket.send_json(end_payload)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        _ws_clients.discard(websocket)


# ── 진입점 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    settings = get_settings()
    print(f"[Pluiz v2] 서버 시작: http://{settings.server_host}:{settings.server_port}")
    print(f"[Pluiz v2] LLM provider: {settings.llm_provider} / {settings.active_model}")
    uvicorn.run(
        "main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
    )
