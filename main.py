"""
Pluiz v2 - FastAPI 서버
Electron UI와 HTTP/WebSocket으로 통신
"""

import asyncio
import os
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# BUG-02: create_task 참조 손실 방지용 백그라운드 태스크 집합
_bg_tasks: set = set()

from config.settings import get_settings
from core.factory import get_active_agent
from core.security import check_security
from services.tts import get_tts
from services.stt import get_stt

app = FastAPI(title="Pluiz v2", version="2.0.0")

# Electron에서 접근 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 데이터 모델 ───────────────────────────────────────────────────

class TextRequest(BaseModel):
    text: str
    thread_id: str = "default"
    use_tts: bool = False


class TextResponse(BaseModel):
    response: str
    thread_id: str


class ConfigRequest(BaseModel):
    provider: str   # "gemini" | "claude" | "openai"
    api_key: str


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

    key_var = f"{req.provider.upper()}_API_KEY"
    provider_found = key_found = False
    new_lines: list[str] = []

    for line in lines:
        if line.startswith("LLM_PROVIDER="):
            new_lines.append(f"LLM_PROVIDER={req.provider}\n")
            provider_found = True
        elif line.startswith(key_var + "="):
            new_lines.append(f"{key_var}={req.api_key}\n")
            key_found = True
        else:
            new_lines.append(line)

    if not provider_found:
        new_lines.insert(0, f"LLM_PROVIDER={req.provider}\n")
    if not key_found:
        new_lines.append(f"{key_var}={req.api_key}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # 캐시 초기화 → 다음 get_settings() 호출에서 .env 재로드
    get_settings.cache_clear()

    # 에이전트 재초기화 (신/구 코어 모두)
    from core.factory import reset_active_agent
    reset_active_agent()

    print(f"[config] provider={req.provider} key=***{req.api_key[-4:] if req.api_key else ''} 저장됨")
    return {"status": "ok", "provider": req.provider}


@app.post("/chat")
async def chat(req: TextRequest):
    """
    텍스트 명령 처리.
    Electron UI의 채팅 입력창에서 호출.
    """
    from fastapi.responses import JSONResponse
    try:
        # ── 보안 필터 (LLM 판단 전 결정론적 차단) ─────────────────
        blocked, reason = check_security(req.text)
        if blocked:
            print(f"[Security] 차단됨: {repr(req.text[:60])}")
            return {"response": reason, "thread_id": req.thread_id}

        agent = get_active_agent()
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
async def voice_input(audio: UploadFile = File(...), thread_id: str = "default", use_tts: bool = True):
    """
    음성 파일 업로드 → STT → 에이전트 처리 → (TTS) 응답.
    Electron에서 마이크 녹음 후 전송.
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
    agent = get_active_agent()
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
    """개발용 캐시 대시보드(HTML) — 조회·삭제·초기화 + 스키마/타입 문서."""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_CACHE_DASHBOARD_HTML)


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


# ── WebSocket (실시간 스트리밍) ───────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket으로 스트리밍 응답.
    토큰 단위로 UI에 실시간 전송.
    use_tts=true 시 end 메시지에 audio_base64 포함.
    """
    await websocket.accept()
    agent = get_active_agent()

    try:
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
