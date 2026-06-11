# Pluiz v2 — 프로젝트 컨텍스트

> **개발 채팅 전용 가이드.** 이 파일을 읽으면 대화 없이도 프로젝트 상태를 파악할 수 있습니다.

---

## 프로젝트 개요

**Pluiz** — 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트.  
졸업 캡스톤 프로젝트. 데모 마감 **2026.06.15**.

사용자가 말하거나 타이핑하면 → LLM이 판단 → 도구 실행 → 음성으로 결과 안내.

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| AI 에이전트 | LangGraph `create_react_agent` + Gemini 2.0 Flash |
| STT | faster-whisper (base 모델, 로컬) |
| TTS | edge-tts (Microsoft, 무료) |
| 서버 | FastAPI + uvicorn (포트 8765) |
| UI | Electron (frameless, always-on-top 오버레이) |
| 설정 | pydantic-settings + `.env` 파일 |

---

## 디렉토리 구조

```
C:\pluiz_v2\
├── main.py                  # FastAPI 서버 진입점
├── .env                     # API 키, 포트 설정 (LLM_PROVIDER, GEMINI_API_KEY 등)
├── CLAUDE.md                # 이 파일
├── test_commands.py         # 자동화 테스트 스크립트
├── start.bat                # 서버 + Electron 한 번에 실행
├── requirements.txt
│
├── config/
│   └── settings.py          # pydantic-settings, @lru_cache, get_settings()
│
├── core/
│   ├── agent.py             # PluizAgent, get_agent(), reset_agent()
│   ├── tool_registry.py     # get_all_tools() — 도구 26개 등록
│   ├── security.py          # check_security() — 코드 레벨 입력 필터 (LLM 전 차단)
│   └── command_cache.py     # CommandCache — 오프라인 커맨드 캐시, get_cache()
│
├── tools/
│   ├── app_control.py       # open_app, close_app, maximize/minimize_window, show_desktop
│   ├── system.py            # volume_up/down/set/mute, brightness, screenshot, battery, time, running_apps
│   ├── filesystem.py        # create_file/folder, find_file, open_file, open_recent_file
│   ├── web.py               # open_url, web_search, youtube_search, map_search
│   └── input_control.py     # type_text, press_key — 포그라운드 앱 키보드 입력
│
├── cache/
│   └── command_cache.json   # 캐시 영속 저장 파일 (자동 생성)
│
├── services/
│   ├── stt.py               # STTService, get_stt() — faster-whisper
│   ├── tts.py               # TTSService, get_tts() — edge-tts
│   └── wakeword.py          # 독립 프로세스, "소윤아" 감지 → stdout에 "WAKE" 출력
│
├── memory/
│   └── session.py           # SessionMemory (SQLite, 단순 히스토리 저장용)
│
└── electron-ui/
    ├── main.js              # BrowserWindow, IPC, wakeword 프로세스 관리
    ├── preload.js           # contextBridge — quit, resize, onWakeDetected 등
    └── renderer/
        └── index.html       # 전체 UI (idle pill + active view + 설정창)
```

---

## 핵심 실행 흐름

### 음성 입력
```
index.html MediaRecorder → webm blob
  → POST /voice (multipart)
  → STTService.transcribe_bytes() → 한국어 텍스트
  → PluizAgent.run_async(text, thread_id)
  → ReAct 루프 (도구 호출 반복)
  → TTSService.to_bytes_async(response) → MP3 bytes
  → JSON { text, response, audio_base64 }
  → index.html playAudio(base64)
```

### 텍스트 입력
```
index.html WebSocket → { text, thread_id, use_tts: true }
  → /ws 핸들러
  → PluizAgent.stream() → 토큰 단위 yield
  → ws.send({ type: "chunk", content })  ← 실시간 출력
  → 스트림 종료 시 TTS 생성 → ws.send({ type: "end", audio_base64 })
  → index.html playAudio(base64)
```

### ReAct 루프 (LangGraph)
```
HumanMessage
  → LLM: 어떤 tool을 쓸까?
  → tool_call: open_app("메모장")
  → ToolMessage: "✓ 메모장 실행"
  → LLM: 추가 도구 필요? → create_file("todo.txt") ...
  → 완료 시 AIMessage 반환 → 루프 종료
```

### 맥락 유지
- `MemorySaver` — LangGraph 내장, thread_id별 인메모리 체크포인트
- 같은 thread_id → 이전 대화 전부 알고 있음
- 세션 시작 시 `pluiz_{timestamp}` 로 고정

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 |
| POST | `/chat` | 텍스트 명령 (비스트리밍) |
| POST | `/voice` | 음성 파일 → STT + 에이전트 + TTS |
| WS | `/ws` | 텍스트 스트리밍 |
| GET | `/api/config` | 현재 LLM 설정 조회 |
| POST | `/api/config` | API 키 변경 + 에이전트 재초기화 |

---

## 설정 변경 흐름 (API 키 교체)

```python
# POST /api/config → save_config()
1. .env 파일 재작성 (LLM_PROVIDER, {PROVIDER}_API_KEY)
2. get_settings.cache_clear()   # lru_cache 무효화
3. reset_agent()                # _agent_instance = None
# 다음 요청 시 get_agent()가 새 키로 PluizAgent 재생성
```

---

## UI 구조 (index.html)

```
.card (always-on-top, frameless)
├── .settings-overlay    # API 설정창 (position:absolute, z-index:1000)
│   └── provider tabs + key input + save button
├── .idle-view           # 280×64 pill
│   ├── logo-ring
│   ├── idle-info (name + status dot + hint)
│   └── idle-actions [⚙️ 설정] [🎙️ 즉시 녹음]
└── .active-view         # 420×340
    ├── a-header [로고] [소윤] [⚙️] [✕]  ← 더블클릭 → idle로 축소
    ├── voice-zone (waveform + countdown ring + mic button)
    ├── chat-list (메시지 버블)
    └── input-row (textarea + send button)
```

**주요 동작:**
- 아이들 pill 클릭 → 확장 (마이크 없이)
- 아이들 pill 더블클릭 → 확장 + 즉시 녹음 시작
- 🎙️ 버튼 클릭 → 확장 + 즉시 녹음
- 헤더 더블클릭 → idle로 축소
- ✕ → 앱 완전 종료 (forceQuit 플래그)

---

## 현재 구현 상태 (2026.06.11 기준)

### ✅ 완료
- FastAPI 서버 (HTTP + WebSocket)
- LangGraph ReAct 에이전트 (멀티스텝, 맥락 유지)
- STT: faster-whisper 로컬 (webm 입력)
- TTS: edge-tts → base64 → 브라우저 재생
- 음성 입력 + 텍스트 입력 모두 TTS 지원
- 도구 26개 (앱/시스템/파일/웹/키보드입력)
- Electron UI (idle pill ↔ active view)
- API 설정창 (첫 실행 시 자동 표시, ⚙️ 버튼으로 재접근)
- ✕ 버튼 정상 종료
- 자동화 테스트 스크립트 (25/25 통과)
- **보안 레이어** (`core/security.py`) — 위험 명령어 18개 패턴, 시스템 경로 7개, 경로 순회 차단. `/chat`, `/voice`, `/ws` 전 엔드포인트 적용
- **오프라인 커맨드 캐시** (`core/command_cache.py`) — 시드 37개, 퍼지 매칭(0.80), LLM 전 캐시 hit 시 API 없이 직접 실행. `run_async()`에 통합
- **키보드 입력 도구** (`tools/input_control.py`) — `type_text`, `press_key`. 클립보드 경유 한국어 안전 처리

### ❌ 미구현 / 보류
- 웨이크워드 ("소윤아") — faster-whisper tiny 인식률 낮음, 데모에서 Alt+Space 사용
- 클립보드 제어 (복사/붙여넣기 읽기)
- `stream()` 메서드의 캐시 통합 (현재 `run_async()`에만 적용)

---

## 도구 추가 방법

```python
# 1. tools/새파일.py 또는 기존 파일에 추가
from langchain_core.tools import tool

@tool
def my_tool(param: str) -> str:
    """도구 설명 — LLM이 이 설명 보고 언제 쓸지 판단함."""
    # Windows 제어 로직
    return "✓ 완료"

# 2. core/tool_registry.py
from tools.새파일 import my_tool
# get_all_tools() 반환 리스트에 추가
```

---

## 실행 방법

```bash
# 서버만
cd C:\pluiz_v2
python main.py

# 전체 (서버 + Electron)
start.bat

# 테스트 (서버 켜진 상태에서)
python test_commands.py
```

---

## 주의사항

- `thread_id` 오염 시 에이전트 루프 무한루프 가능 → `reset_agent()` 호출
- pycaw (볼륨 제어) asyncio 컨텍스트에서 불안정 → PowerShell fallback 있음
- Electron `file://` 프로토콜 → Web Speech API 사용 불가 (보안 컨텍스트 아님)
- `get_settings()`는 `@lru_cache` → `.env` 변경 후 반드시 `cache_clear()` 필요
