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
from core.agent import get_agent
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

    # 에이전트 재초기화
    from core.agent import reset_agent
    reset_agent()

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

        agent = get_agent()
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
    agent = get_agent()
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


# ── WebSocket (실시간 스트리밍) ───────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket으로 스트리밍 응답.
    토큰 단위로 UI에 실시간 전송.
    use_tts=true 시 end 메시지에 audio_base64 포함.
    """
    await websocket.accept()
    agent = get_agent()

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
