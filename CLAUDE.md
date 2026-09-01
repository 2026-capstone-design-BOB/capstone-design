# Pluiz v2 — 프로젝트 컨텍스트

> **개발 채팅 전용 가이드.** 이 파일을 읽으면 대화 없이도 프로젝트 상태를 파악할 수 있습니다.
> **최종 갱신**: 2026-09-01 (코드 기준 현행화)

---

## 📌 문서 위계 (먼저 읽을 것)

| 문서 | 성격 | 신뢰도 |
|------|------|--------|
| **`DEVLOG.md`** | 개발 일지. 시간 역순, 단계별 목표/완료/검증 기록 | **단일 진실 공급원(SoT)** |
| **`BACKLOG.md`** | 미해결 항목. [즉시/위험] vs [TODO/품질] 분류 | 현행 |
| **`docs/design/`** | 설계 문서 (M1 아키텍처 ADR, P1.5 이관 계획, P4 캐시 정책) | 확정본 |
| `docs/testing/` | 수동 테스트 케이스 (자동화 불가 항목) | 현행 |
| `docs/presentation/` | 발표·캡스톤 자료 (슬라이드, 다이어그램, Q&A, 발표용 기술가이드) | 2026.06 데모 시점 |
| `CLAUDE.md` | 이 파일. 구조 요약 | 요약본 — 상세는 DEVLOG |
| `HANDOFF.md` | 2026.06 데모 시점 스냅샷 | **아카이브(과거 기록)** |
| `archive/` | 대체된 구 산출물 | **아카이브(참고용)** |

작업 시작 전 `DEVLOG.md` 최상단 항목과 `BACKLOG.md`를 확인하세요.

---

## 프로젝트 개요

**Pluiz** — 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트. 졸업 캡스톤.

사용자가 말하거나 타이핑하면 → 보안 검사 → 캐시/라우터 즉시 실행 or LLM 판단 → 도구 실행 → 음성으로 결과 안내.

- 브랜치: `feature/byeonsoyun`
- **2026.06.15 데모 완료.** 이후 계절학기 AI Agent 강의 개념(LangGraph·HITL·OWASP·RAG)을
  구조에 적용하는 **Milestone 1** 진행 중.
- M1 진행: P0(진단) → P1(맥락) → P1.5(그래프 이관) → P2(HITL) → P3(OWASP 가드레일) **완료**,
  **P4(캐시 동적 학습) 코드 완성**.

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| AI 에이전트 | **LangGraph 명시적 `StateGraph`** (`core/graph.py`) + Gemini 2.5 Flash |
| STT | Google STT(온라인 우선) + faster-whisper(오프라인 폴백) 하이브리드 |
| TTS | edge-tts (`ko-KR-SunHiNeural`) |
| 서버 | FastAPI + uvicorn (포트 8765) |
| UI | Electron (frameless, always-on-top 오버레이) |
| 설정 | pydantic-settings + `.env` 파일 |

LLM provider는 `gemini` / `claude` / `openai` 전환 가능 (`config/settings.py`).

---

## 디렉토리 구조

```
C:\pluiz_v2\
├── main.py                  # FastAPI 서버 진입점 (464줄)
├── .env                     # API 키, USE_GRAPH 등 (gitignore)
├── DEVLOG.md                # ★ 개발 일지 (단일 진실 공급원)
├── BACKLOG.md               # ★ 미해결 항목
├── CLAUDE.md                # 이 파일
├── HANDOFF.md               # 2026.06 데모 시점 아카이브
├── start.bat / launch.bat / setup.bat
├── requirements.txt
├── test_*.py                # 루트 테스트 19개 (mock 스위트 158개 그린)
│
├── docs/
│   ├── design/                      # 설계 문서 (개발용)
│   │   ├── M1_아키텍처_설계.md         # ADR — 맥락 버그 진단 + To-Be 그래프 설계
│   │   ├── M1_P1.5_그래프이관_계획.md
│   │   └── M1_P4_캐시정책.md           # 동적 학습 정책 확정본
│   ├── testing/                     # 수동 테스트 케이스 (자동화 불가 항목)
│   │   ├── TEST_CASES.md
│   │   ├── MANUAL_TEST_CASES.md
│   │   └── MANUAL_TESTS.md
│   └── presentation/                # 발표·캡스톤 자료 (2026.06 데모)
│       ├── STUDY_GUIDE.md              # 발표용 기술 가이드 (948줄)
│       ├── pluiz_QnA.md                # 교수·심사위원 Q&A 대비
│       ├── pluiz_evolution.md          # V0 → V1 → V2 발전사
│       ├── pluiz_presentation.html     # reveal.js 슬라이드
│       ├── architecture.html
│       └── *.svg / *.png               # 다이어그램 8개
│                                    #   ※ 슬라이드가 SVG를 상대경로로 참조 →
│                                    #     하위 폴더로 더 나누지 말 것
│
├── archive/
│   └── ui.html              # 구 브라우저 단독 UI (electron-ui로 대체됨)
│
├── config/
│   └── settings.py          # pydantic-settings, @lru_cache, get_settings()
│
├── core/
│   ├── graph.py             # ★ StateGraph 정의 (노드/엣지/HITL/output_guard)
│   ├── graph_agent.py       # ★ PluizGraphAgent — 신 엔진 오케스트레이터
│   ├── agent.py             # 구 엔진 PluizAgent (비상 폴백, BL-05 제거 후보)
│   ├── factory.py           # USE_GRAPH 플래그로 신/구 엔진 선택
│   ├── fast_path.py         # 복합명령 감지 → 캐시 → 라우터 통합 해석
│   ├── router.py            # 결정론적 정규식 라우터 9종
│   ├── command_cache.py     # 오프라인 캐시 (인텐트 매칭 + 동적 학습)
│   ├── security.py          # 규칙 기반 가드 (경로/명령/인젝션/민감정보/마스킹)
│   ├── guardrails.py        # 하이브리드 LLM 판정기 (P3-4)
│   └── tool_registry.py     # get_all_tools() — 도구 등록 단일 지점
│
├── tools/
│   ├── app_control.py       # open_app, close_app, maximize/minimize_window, show_desktop
│   ├── system.py            # volume_up/down/set/mute, brightness, screenshot, battery, time, running_apps
│   ├── filesystem.py        # create_file/folder, find_file, open_file, open_recent_file,
│   │                        #   write_excel, delete_file, delete_folder
│   ├── web.py               # open_url, web_search, youtube_search, map_search, fetch_web_info, crawl_page
│   ├── input_control.py     # type_text, press_key, get_clipboard_text
│   └── calendar.py          # create_calendar_event (Google Calendar)
│
├── cache/
│   ├── command_cache.json   # 캐시 영속 저장 (시드 + 동적 학습)
│   └── favorites.json       # 즐겨찾기
│
├── services/
│   ├── stt.py               # STTService — Google STT + faster-whisper 폴백
│   ├── tts.py               # TTSService — edge-tts, 3단 재생 폴백
│   └── wakeword.py          # 독립 프로세스 ("소윤아") — 인식률 문제로 보류
│
├── memory/
│   └── session.py           # SessionMemory (SQLite) — UI 표시/통계용.
│                            #   ※ LLM 입력으로 되먹임되지 않음 (맥락은 checkpointer 담당)
│
└── electron-ui/
    ├── main.js              # BrowserWindow, IPC, wakeword 프로세스 관리
    ├── preload.js           # contextBridge
    └── renderer/index.html  # UI 전체 (1809줄)
```

---

## 핵심 실행 흐름

### 전체 파이프라인

```
사용자 입력 (/chat · /voice · /ws)
  │
  ├─ main.py: check_security()              ← 1차 코드 필터
  │
  └─ core/factory.py: get_active_agent()
        USE_GRAPH=true(기본) → PluizGraphAgent / false → PluizAgent(구 엔진)
        │
        └─ core/graph_agent.py (오케스트레이터)
             ├─ hybrid_guard_check()      ← 의심 입력만 LLM 판정 (8초 타임아웃, 실패 시 skip)
             ├─ graph.invoke()를 asyncio.to_thread로 실행  ← interrupt 호환 위해 sync
             ├─ mask_sensitive_output()   ← 출력 마스킹
             ├─ _maybe_learn()            ← P4 동적 학습
             └─ session_memory.save()
```

### 그래프 구조 (`core/graph.py`)

```
START → input_guard ─(차단)────→ output_guard → END
           │
           ▼
        fast_path ─(hit)───────→ output_guard → END
           │(miss)
           ▼
         agent ⇄ tools ────────→ output_guard → END
           │
           └─(위험 도구)→ hitl (interrupt 승인) → tools | output_guard
```

| 노드 | 역할 |
|------|------|
| `input_guard` | 코드 레벨 보안 검사 (OWASP LLM01/02) |
| `fast_path` | 캐시 + 결정론적 라우터. **히트해도 결과를 `state.messages`에 AIMessage로 기록** |
| `agent` | LLM ReAct 추론 (동기 invoke) |
| `tools` | LangGraph `ToolNode` |
| `hitl` | 삭제 도구 실행 전 `interrupt()` 사람 승인 (Lab19) |
| `output_guard` | 빈 응답 복구 + 도구 오류인데 성공처럼 답한 경우 보정 (LLM05, reflection) |

**⚠️ 설계상 중요한 세 가지**

1. **fast_path 히트도 messages에 누적된다.**
   구 엔진은 캐시가 처리하면 즉시 `return` → 그 대화가 LangGraph 기록에 안 남아
   "메모장 켜줘" 다음 "그거 꺼줘"가 실패했다. 이게 M1의 핵심 문제였고,
   모든 경로를 단일 상태(`messages`)로 통합해 **구조적으로** 해결했다.
   진단 과정은 `docs/design/M1_아키텍처_설계.md` 참조.

2. **노드는 전부 동기(sync)다.**
   LangGraph `interrupt`가 sync invoke에서만 안정 동작하기 때문.
   오케스트레이터가 `asyncio.to_thread`로 감싸 이벤트 루프를 막지 않는다.

3. **의존성 주입(DI).** llm / tools / security_check / fast_resolve 전부 주입 가능 →
   Windows·LLM API 없이 mock으로 단위 테스트 가능. (루트 `test_*.py`가 이 방식)

### 맥락 유지
- `MemorySaver` — thread_id별 인메모리 체크포인트
- `trim_messages(start_on="human")` — 최근 20개. 단순 슬라이스는 (도구호출 AIMessage ↔ ToolMessage)
  쌍을 잘라 Gemini가 400으로 거부하므로 반드시 trim 사용

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 |
| POST | `/chat` | 텍스트 명령 (비스트리밍) |
| POST | `/voice` | 음성 파일 → STT + 에이전트 + TTS |
| WS | `/ws` | 텍스트 스트리밍 (※ 현재 단일 청크, BL-04) |
| GET/POST | `/api/config` | LLM 설정 조회 / API 키 변경 + 에이전트 재초기화 |
| GET/DELETE | `/history` | 대화 히스토리 조회 / 초기화 |
| GET/POST | `/favorites` | 즐겨찾기 목록 / 추가 |
| DELETE | `/favorites/{index}` | 즐겨찾기 삭제 |
| GET | `/cache` | 캐시 통계 + 동적/시드 목록 (JSON) |
| GET | `/cache/ui` | **개발용 캐시 대시보드 (HTML)** — 조회·삭제·초기화 |
| DELETE | `/cache` | 동적 학습 전체 초기화 (오염 롤백, 시드 유지) |
| DELETE | `/cache/entry?pattern=` | 동적 항목 개별 삭제 (시드 보호) |

---

## 도구 33개

| 분류 | 개수 | 도구 |
|------|------|------|
| 앱 제어 | 5 | `open_app` `close_app` `maximize_window` `minimize_window` `show_desktop` |
| 웹 | 6 | `open_url` `web_search` `youtube_search` `map_search` `fetch_web_info` `crawl_page` |
| 파일 | 6 | `create_file` `create_folder` `find_file` `open_recent_file` `open_file` `write_excel` |
| 시스템 | 10 | `volume_up/down/set` `mute_toggle` `brightness_up/down` `take_screenshot` `get_battery_status` `get_current_time` `get_running_apps` |
| 입력 | 3 | `type_text` `press_key` `get_clipboard_text` |
| 캘린더 | 1 | `create_calendar_event` |
| **삭제** | **2** | `delete_file` `delete_folder` — **`USE_GRAPH=true`일 때만 등록** |

> 삭제 도구는 HITL 승인이 있는 그래프 엔진에서만 노출된다
> (`core/tool_registry.py:100-104`). 구 엔진에선 도구 자체가 없어
> "확인 없는 삭제"가 구조적으로 불가능하다.

---

## 보안 — 4층 방어 (P3 완료)

| 층 | 위치 | 내용 |
|----|------|------|
| 1. 규칙 | `core/security.py` | 위험경로 7 · 위험명령 22 · 경로순회 · 인젝션 8 · 민감정보 4. 오프라인·저지연 하드게이트 |
| 2. 하이브리드 LLM 판정 | `core/guardrails.py` | 규칙 통과 + `is_suspicious` 신호일 때만 LLM에 ATTACK/SAFE 질의. 오프라인/실패 시 fail-safe skip |
| 3. HITL | `core/graph.py` hitl 노드 | 삭제 전 `interrupt()` 승인. **애매한 답변은 취소로 처리**(안전 기본값) |
| 4. 출력 마스킹 | `mask_sensitive_output()` | 주민번호·카드번호·Google/OpenAI API 키 |

**정직한 한계** (DEVLOG 기록): 무한 패러프레이즈 100% 차단은 불가.
오프라인에선 1·3·4층만 동작(교묘한 우회는 온라인에서만 포착).

---

## 커맨드 캐시 (`core/command_cache.py`)

**2단계 매칭**
- **Stage 1 — 인텐트**: `(entity, action)` 추출 → `_intent_index` 직접 조회.
  "계산기 켜줘"와 "계산기 꺼줘"는 글자 유사도 약 0.93이라 문자열 매칭은 틀린 답을
  높은 확신으로 반환한다. 인텐트는 `open` vs `close`를 정확히 구분.
  시드에 없는 앱+open/close 조합은 `_build_intent_index()`가 자동 합성.
- **Stage 2 — 유사도 fallback**: `SequenceMatcher` 0.80.
  `_similarity()` 메서드로 캡슐화됨 → **후속 P4-A에서 이 메서드만 로컬 임베딩으로 교체**하면 됨.

**동적 학습 (P4)** — 정책 확정본: `docs/design/M1_P4_캐시정책.md`
- LLM이 **성공 실행한 화이트리스트 도구** 명령만 1회 즉시 학습. 표현만 저장,
  **파라미터는 저장 안 함**(오염 원천 차단).
- 화이트리스트: `LEARNABLE_TOOLS` (파라미터 없음/고정어휘 제어 도구 15종)
- 절대 학습 안 함: 자유 파라미터(폴더명·검색어·`set_volume` 숫자·`type_text`),
  위험 명령, 실패한 명령, 보안 차단 입력
- 상한 200(`cache_max_dynamic`), 초과 시 LRU+LFU 정리. `cache_learning`으로 on/off
- 시드는 삭제 보호. `DELETE /cache`로 동적만 원버튼 롤백

---

## 설정 (`config/settings.py`)

주요 항목: `llm_provider` · `{provider}_api_key` · `gemini_model`(기본 `gemini-2.5-flash`) ·
`server_port`(8765) · `agent_timeout`(30초) · **`use_graph`(기본 `True`)** ·
`cache_learning` · `cache_max_dynamic`(200) · `whisper_model`(base) · `tts_voice`

### API 키 교체 흐름
```python
# POST /api/config → save_config()
1. .env 재작성 (LLM_PROVIDER, {PROVIDER}_API_KEY)
2. get_settings.cache_clear()   # lru_cache 무효화
3. reset_active_agent()         # 신·구 코어 싱글톤 모두 초기화
```

---

## UI 구조 (`electron-ui/renderer/index.html`)

```
.card (always-on-top, frameless)
├── .settings-overlay    # API 설정창
├── .idle-view           # 280×64 pill
└── .active-view         # 420×340 (voice-zone + chat-list + input-row)
```

- 아이들 pill 클릭 → 확장 / 더블클릭 → 확장 + 즉시 녹음
- 헤더 더블클릭 → idle로 축소 / ✕ → 앱 완전 종료

---

## 도구 추가 방법

```python
# 1. tools/새파일.py 또는 기존 파일에 추가
from langchain_core.tools import tool

@tool
def my_tool(param: str) -> str:
    """도구 설명 — LLM이 이 설명 보고 언제 쓸지 판단함."""
    return "✓ 완료"

# 2. core/tool_registry.py 의 get_all_tools()에 import + 리스트 추가
```

위험한 도구라면 `core/graph.py`의 `DANGEROUS_TOOLS`에도 추가해 HITL 승인을 태울 것.

---

## 실행 방법

```bash
# 서버만
cd C:\pluiz_v2
python main.py

# 전체 (서버 + Electron)
start.bat

# mock 테스트 (Windows·API 불필요)
python test_graph_agent.py      # 그래프 오케스트레이터
python test_hitl_agent.py       # HITL 승인
python test_cache_learn.py      # 캐시 동적 학습
python test_guardrail_hybrid.py # 하이브리드 가드

# 라이브 통합 테스트 (서버 켜진 상태, ※ 구 엔진 기준 — BL-06)
python test_commands.py
```

---

## 주의사항

- `get_settings()`는 `@lru_cache` → `.env` 변경 후 반드시 `cache_clear()` 필요
- 그래프 노드는 **반드시 동기**로 유지 (interrupt 호환)
- 히스토리 조작 시 `trim_messages` 우회 금지 — 도구호출/ToolMessage 쌍이 깨지면 Gemini 400
- `thread_id` 오염 시 `_clear_thread()` 호출 (`graph_agent.py`가 자동 복구도 함)
- pycaw(볼륨) asyncio 컨텍스트에서 불안정 → PowerShell fallback 있음
- Electron `file://` 프로토콜 → Web Speech API 사용 불가 (보안 컨텍스트 아님)
- `cache/command_cache.json` 손상 시 자동 초기화 (시드로 재구성)

---

## 알려진 미해결 (상세는 `BACKLOG.md`)

- **BL-02** 캐시 부정어 오매칭 — "계산기 **말고** 다른거 열어" → 계산기를 엶
- **BL-03** 보안필터가 공백 없는 변형(`rm-rf`) 미포착
- **BL-04** `/ws` 실제 토큰 스트리밍 미구현 (`stream()`이 단일 청크로 yield)
- **BL-05** 구 엔진(`core/agent.py` 771줄) 제거 → 그래프 단일화. 롤백 낙하산 목적으로 아직 보존
- **BL-06** `test_commands.py`·`test_regression.py`가 구 엔진 기준
- **BL-07** 파일 찾기 UX (확장자 모를 때 헤맴)
- 웨이크워드("소윤아") — 인식률 낮아 보류
