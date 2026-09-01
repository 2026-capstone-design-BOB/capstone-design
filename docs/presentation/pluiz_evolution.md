# Pluiz 프로젝트 발전사 — V0 → V1 → V2

> 졸업 캡스톤 프로젝트: 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트  
> 마감: 2026.06.15

---

## 버전 한눈에 보기

| 항목 | V0 (초기 프로토타입) | V1 (서버+멀티에이전트) | V2 (현재) |
|------|------|------|------|
| **진입점** | 터미널 CLI | FastAPI 서버 + Electron UI | FastAPI + WebSocket + Electron UI |
| **LLM** | Ollama llama3.1 (로컬) | Gemini / OpenAI + Ollama 폴백 | Gemini 2.0 Flash |
| **에이전트 구조** | 단일 컨트롤러 | 멀티에이전트 계층 (supervisor → local/base) | LangGraph ReAct 단일 에이전트 |
| **실행 방식** | LLM이 Python 코드 생성 → `exec()` | LLM이 Python 코드 생성 → `exec()` | 사전 정의된 도구 27개 직접 호출 |
| **STT** | faster-whisper (로컬) | Google Cloud STT | faster-whisper (로컬) |
| **TTS** | gTTS / pyttsx3 | OpenAI TTS (미완성, 주석 처리) | edge-tts (Microsoft, 무료) |
| **캐시** | 없음 | SQLite DB 3종 (command/multistep/preset) | JSON 퍼지 매칭 캐시 |
| **보안** | JSON 설정 기반 키워드 필터 | AST 분석 기반 가드 | 정규식 패턴 18개 필터 |
| **메모리** | 없음 | ContextMemory (직전 명령) | LangGraph MemorySaver (thread_id별 전체 히스토리) |

---

## V0 — 로컬 LLM + 코드 생성 (프로토타입)

### 구조
```
main.py (CLI 루프)
  └─ PluizController
        ├─ STTEngine (faster-whisper + SpeechRecognition)
        ├─ IntentInterpreter (Ollama API → JSON 파싱)
        ├─ SecurityManager (tts_security_config.json)
        ├─ OSHandler + WebHandler (규칙 기반 실행)
        └─ Speaker (gTTS / pyttsx3)
```

### 핵심 아이디어
사용자 명령 → Ollama(llama3.1)에 프롬프트 → JSON `{"commands": [{"action": "open", "target": "메모장"}]}` → rule-based executor로 실행

### 장점
- 인터넷 연결 없이 완전 로컬 실행
- 단순하고 명확한 흐름

### 한계
- LLM 응답이 JSON 스키마를 안 지키면 파싱 실패 → 명령 무시
- Ollama llama3.1 로컬 모델의 한국어 이해도·속도 한계
- 서버/UI 없이 터미널만 — 실사용 불가
- 멀티스텝 명령 미지원 (파일 만들고 내용 쓰는 2단계 불가)
- 의존성 폭발: torch, PyQt6, Selenium, playwright, PyAutoGUI 등 수십 개

---

## V1 — 서버 + 멀티에이전트 + 코드 실행

### 구조
```
app/server.py (FastAPI)
  ├─ CommandRouter → {local/web/interpreter/system}
  ├─ AsyncExecutor + MultistepExecutor
  ├─ SupervisorAgent ─→ LLM(Gemini/OpenAI)
  │     └─ BRAIN_PROMPT: Python 코드 생성 (19개 엄격한 규칙)
  ├─ LocalAgent + BaseAgent (멀티에이전트 계층)
  ├─ OfflineExecutor (Ollama + Open Interpreter 폴백)
  ├─ Cache: CommandCache(SQLite) + MultiStepCache + PresetCache
  ├─ STTService (Google Cloud STT / faster-whisper)
  └─ ContextMemory (직전 1회 대화만 유지)

frontend-ui/ (Electron, 독립 node_modules)
  └─ models/vosk-model-small-ko-0.22/ (오프라인 STT 모델)
```

### 핵심 아이디어
멀티에이전트 계층으로 역할 분리. 명령을 타입별로 라우팅(local/web/system).  
LLM이 Python 코드를 문자열로 생성 → `exec()`로 실행 → 결과 반환.

### 장점
- FastAPI 서버 + Electron UI로 실사용 가능한 형태
- 멀티스텝 캐시로 복합 명령 지원
- Ollama 폴백으로 API 장애 시 오프라인 대응
- 3개 캐시 계층으로 반복 명령 빠른 응답

### 한계 & 딜레마

**딜레마 1: `exec()` 보안 문제**  
LLM이 생성하는 코드를 `exec()`로 실행하는 구조는 본질적으로 위험.  
BRAIN_PROMPT에 19개 규칙으로 제약했지만, 프롬프트 인젝션이나 규칙 우회 가능성 항상 존재.  
→ AST 분석 기반 보안 가드(`app/security/ast_guard.py`) 추가했으나 완전 차단 불가능.  
→ V2에서 `exec()` 구조 자체를 폐기.

**딜레마 2: 창 포커스 문제**  
Electron 채팅창에서 명령 입력 시 포그라운드 윈도우가 채팅창 → `GetForegroundWindow()`가 잘못된 창을 타겟으로 지정.  
`supervisor_agent.py`에 TODO 주석으로 남겨진 미해결 과제.  
→ V2에서 `AttachThreadInput` + `EnumWindows` 조합으로 해결.

**딜레마 3: TTS 미완성**  
OpenAI TTS를 목표로 설계했지만 API 키 비용 문제로 주석 처리.  
TTS 없는 상태로 배포.  
→ V2에서 무료 edge-tts로 전환.

**딜레마 4: 멀티에이전트 복잡성**  
supervisor/local/base 3계층 + 5종 executor + 3종 cache → 디버깅 어려움, 실패 포인트 분산.  
→ V2에서 단일 에이전트로 단순화.

---

## V2 — LangGraph ReAct 에이전트 (현재)

### 구조
```
main.py (FastAPI + WebSocket)
  ├─ PluizAgent (LangGraph create_react_agent)
  │     ├─ Gemini 2.0 Flash (LLM)
  │     ├─ MemorySaver (thread_id별 전체 히스토리)
  │     └─ Tools ×27 (app/system/filesystem/web/input)
  ├─ CommandCache (JSON + difflib 퍼지매칭 0.80)
  ├─ SecurityLayer (정규식 18패턴, LLM 전 차단)
  ├─ STTService (faster-whisper 로컬)
  └─ TTSService (edge-tts → base64 → 브라우저 재생)

electron-ui/
  ├─ main.js (BrowserWindow + IPC)
  └─ renderer/index.html (idle pill ↔ active view)
```

### 핵심 패러다임 전환: 코드 생성 → 도구 호출
V0/V1의 "LLM이 Python 코드를 생성 → `exec()`" 방식을 완전 폐기.  
대신 LangGraph의 ReAct(Reasoning + Acting) 루프:

```
HumanMessage
  → LLM: 어떤 도구를 쓸까?
  → tool_call: open_app("메모장")
  → ToolMessage: "✓ 메모장 실행"
  → LLM: 더 필요? → create_file("todo.txt") ...
  → 완료 시 자연어 AIMessage 반환
```

LLM은 코드를 작성하지 않고 **미리 정의된 도구를 선택**만 함.  
모든 도구는 Python 함수로 구현되어 안전하고 예측 가능.

---

## 전체 발전 과정에서의 도전 과제

### 1. exec() 딜레마: 유연성 vs 보안
- **문제**: LLM이 생성한 임의 코드를 실행하면 유연하지만 보안 위협
- **V0/V1**: BRAIN_PROMPT 규칙 + AST 가드로 제한 → 완전 해결 불가
- **V2 해결**: exec() 폐기. 도구 27개로 기능을 명시적으로 제한. 보안 레이어는 LLM 전에 입력을 차단하는 역할만 수행

### 2. 창 포커스 가로채기
- **문제**: Electron 앱에서 명령 입력 시 포그라운드가 Electron → `SetForegroundWindow()` 권한 부재
- **V1**: TODO로 미해결
- **V2 해결**: Windows API `AttachThreadInput(my_tid, fg_tid, True)` — 현재 포그라운드 스레드에 일시 attach하여 권한 획득. `EnumWindows`로 대상 창 PID 매칭

### 3. 멀티스텝 명령 처리
- **V0**: 불가 (단일 명령만)
- **V1**: MultistepExecutor + MultiStepCache 별도 구현 (복잡도↑)
- **V2 해결**: LangGraph ReAct가 기본적으로 루프 처리 — 별도 멀티스텝 로직 불필요. `recursion_limit:10`으로 무한루프 방지

### 4. 한국어 음성 인식
- **V0**: faster-whisper 로컬 (CPU 강제, 속도 느림)
- **V1**: Google Cloud STT (인터넷 필요) + Vosk 오프라인 모델 포함 (미완성)
- **V2**: faster-whisper base 모델 — webm 입력 직접 처리, 로컬 실행. 웨이크워드("소윤아")는 인식률 낮아 Alt+Space 단축키로 대체

### 5. TTS 구현
- **V0**: gTTS(Google, 인터넷) + pyttsx3(로컬, 음질 낮음) 병용
- **V1**: OpenAI TTS 설계 → 비용 문제로 주석 처리, TTS 없이 배포
- **V2 해결**: Microsoft edge-tts — 무료, 고음질(한국어 선우 음성), base64 변환 후 브라우저에서 Audio API로 재생

### 6. UI 상호작용 이벤트 충돌
- **문제**: Electron `-webkit-app-region:drag`가 부모에 설정되면 자식 요소의 클릭/스크롤 이벤트 전부 가로챔
- **증상**: 채팅 목록이 보이지만 스크롤 불가, 클릭 불가, 텍스트 선택 불가
- **해결**: `.chat-list`에 `-webkit-app-region:no-drag` + `flex:1; min-height:0` 추가

### 7. 의존성 관리
- **V0**: torch, PyQt6, Selenium, playwright, PyAutoGUI, gTTS, SpeechRecognition… 수십 개
- **V1**: open-interpreter, ollama, PyAudio, Vosk 모델(350MB) 추가
- **V2**: 필수 의존성만 유지. torch 제거(faster-whisper는 onnxruntime 사용), PyQt6 제거, Selenium 제거, playwright 제거. pydantic-settings + LangGraph + fastapi + edge-tts로 경량화

### 8. 캐시 설계 변화
- **V1**: SQLite 3테이블 (command/multistep/preset) — 정확한 키 매칭, 학습(성공횟수 추적)
- **V2**: JSON + difflib 퍼지 매칭 0.80 임계값 — 유사 표현 자동 매칭. "37개 시드 명령"을 사전 정의. LLM 전 히트 시 API 호출 없이 응답

---

## 아직 미해결 또는 절충된 문제

| 문제 | 상태 | 절충안 |
|------|------|------|
| 웨이크워드 "소윤아" | faster-whisper tiny 인식률 낮아 포기 | Alt+Space 키보드 단축키 사용 |
| 클라우드 의존성 | Gemini API 키 필요, 오프라인 불가 | 데모 환경에서는 인터넷 항상 있음 |
| 클립보드 읽기 | 보안상 미구현 | 범위 외로 제외 |
| WebSocket stream 캐시 | run_async()에만 캐시 적용, stream()은 미적용 | 데모용 텍스트 입력은 주로 run_async() 사용 |

---

*작성 기준: 2026.06.12*
