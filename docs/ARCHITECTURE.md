# 시스템 아키텍처

> 📍 [문서 허브](README.md) · 관련: [STRUCTURE.md](STRUCTURE.md) · [design/M1_아키텍처_설계.md](design/M1_아키텍처_설계.md)

이 문서는 **시스템이 어떻게 동작하는가**를 단독으로 책임진다.
"왜 이 설계인가"의 상세 논증은 [design/](design/)의 ADR에 있다.

---

## 한눈에

한국어 음성/텍스트 → 보안 검사 → 캐시·라우터 즉시 실행 또는 LLM 판단 → 도구 실행 → 음성 응답.

| 역할 | 기술 |
|---|---|
| AI 에이전트 | LangGraph 명시적 `StateGraph` + Gemini 2.5 Flash |
| STT | Google STT(온라인 우선) + faster-whisper(오프라인 폴백) |
| TTS | edge-tts (`ko-KR-SunHiNeural`) |
| 서버 | FastAPI + uvicorn (:8765) |
| UI | Electron frameless 오버레이 |
| 설정 | pydantic-settings + `.env` |

LLM provider는 `gemini` / `claude` / `openai` 전환 가능 ([`config/settings.py`](../config/settings.py)).

---

## 요청 흐름

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
             ├─ graph.invoke()를 asyncio.to_thread로 실행
             ├─ mask_sensitive_output()   ← 출력 마스킹
             ├─ _maybe_learn()            ← 캐시 동적 학습
             └─ session_memory.save()
```

오케스트레이터([`core/graph_agent.py`](../core/graph_agent.py))는 그래프 바깥에서
타임아웃·히스토리 오염 복구·오프라인 안내·네트워크 오류 처리를 담당한다.
그래프는 순수하게 흐름만 담당하도록 분리돼 있다.

---

## 그래프 파이프라인

[`core/graph.py`](../core/graph.py)

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
|---|---|
| `input_guard` | 코드 레벨 보안 검사 (OWASP LLM01/02) |
| `fast_path` | 캐시 + 결정론적 라우터. **히트해도 결과를 `state.messages`에 기록** |
| `agent` | LLM ReAct 추론 (동기 invoke) |
| `tools` | LangGraph `ToolNode` |
| `hitl` | 위험 도구 실행 전 `interrupt()` 사람 승인 |
| `output_guard` | 빈 응답 복구 + 도구 오류인데 성공처럼 답한 경우 보정 (LLM05, reflection) |

### ⚠️ 건드리기 전에 알아야 할 세 가지

**1. fast_path가 히트해도 결과를 messages에 누적한다 — 성능 최적화로 지우지 말 것.**

구 엔진은 캐시가 명령을 처리하면 그래프를 거치지 않고 즉시 `return` 했다. 그래서 그
대화가 LangGraph 기록(MemorySaver)에 남지 않았고, **"메모장 켜줘" 다음 "그거 꺼줘"가
실패**했다. LLM이 자기가 본 적 없는 "메모장"을 "그거"로 지칭당했기 때문이다.

이건 설정 누락이 아니라 **구조적 결함**이었다. 성능을 위한 우회 경로와 대화 기억이
단일 상태로 통합돼 있지 않았던 것이다. 모든 경로를 `state.messages` 하나로 모아
근본 해결했다. 진단 전문: [design/M1_아키텍처_설계.md](design/M1_아키텍처_설계.md)

**2. 노드는 전부 동기(sync)다 — async로 바꾸지 말 것.**

LangGraph `interrupt`(HITL 승인)가 sync invoke 경로에서만 안정 동작한다.
대신 오케스트레이터가 `asyncio.to_thread`로 감싸 이벤트 루프를 막지 않는다.

**3. 히스토리는 `trim_messages`로만 자른다 — 슬라이스 금지.**

단순 슬라이스(`convo[-N:]`)는 (도구호출 `AIMessage` ↔ `ToolMessage`) 쌍을 중간에서
잘라 깨진 시퀀스를 만들고, Gemini가 이를 400 INVALID_ARGUMENT로 거부한다.
`trim_messages(start_on="human")`이 항상 사람 발화부터 시작하는 유효 시퀀스를 보장한다.

### 맥락 유지

`MemorySaver`(thread_id별 인메모리 체크포인트) + 최근 20개 메시지.
[`memory/session.py`](../memory/session.py)의 SQLite는 **UI 표시·통계용일 뿐 LLM 입력으로
되먹임되지 않는다.** 맥락 복원은 전적으로 checkpointer가 담당한다.

---

## 도구 (33개)

[`core/tool_registry.py`](../core/tool_registry.py)에 단일 등록.

| 분류 | 개수 | 도구 |
|---|---|---|
| 앱 제어 | 5 | `open_app` `close_app` `maximize_window` `minimize_window` `show_desktop` |
| 웹 | 6 | `open_url` `web_search` `youtube_search` `map_search` `fetch_web_info` `crawl_page` |
| 파일 | 6 | `create_file` `create_folder` `find_file` `open_recent_file` `open_file` `write_excel` |
| 시스템 | 10 | `volume_up/down/set` `mute_toggle` `brightness_up/down` `take_screenshot` `get_battery_status` `get_current_time` `get_running_apps` |
| 입력 | 3 | `type_text` `press_key` `get_clipboard_text` |
| 캘린더 | 1 | `create_calendar_event` |
| **삭제** | **2** | `delete_file` `delete_folder` — **`USE_GRAPH=true`일 때만 등록** |

> **삭제 도구 게이팅**: HITL 승인이 있는 그래프 엔진에서만 노출된다
> ([`tool_registry.py:100-104`](../core/tool_registry.py)). 구 엔진에는 도구 자체가 없어
> "확인 없는 삭제"가 구조적으로 불가능하다. 프롬프트로 부탁하는 대신 **도구를 주지 않는** 방식.

도구 추가 절차는 [WORKFLOW.md § 새 도구 추가](WORKFLOW.md#새-도구-추가).

---

## 보안 — 4층 방어

강의 Day5(OWASP LLM Top 10) 개념을 하이브리드 다층 가드레일로 구현.

| 층 | 위치 | 내용 | OWASP |
|---|---|---|---|
| 1. 규칙 | [`core/security.py`](../core/security.py) | 위험경로 7 · 위험명령 22 · 경로순회 · 인젝션 8 · 민감정보 4. 오프라인·저지연 하드게이트 | LLM01/02 |
| 2. 하이브리드 LLM 판정 | [`core/guardrails.py`](../core/guardrails.py) | 규칙 통과 + `is_suspicious` 신호일 때만 LLM에 ATTACK/SAFE 질의 | LLM01/02 |
| 3. HITL | `core/graph.py` hitl 노드 | 삭제 전 `interrupt()` 승인. **애매한 답변은 취소로 처리**(안전 기본값) | LLM06 |
| 4. 출력 마스킹 | `mask_sensitive_output()` | 주민번호·카드번호·Google/OpenAI API 키 | LLM02/05 |

**설계 의도**: 규칙은 빠르고 오프라인에서 돌지만 교묘한 우회를 놓친다. LLM 판정은
우회를 잡지만 느리고 온라인이 필요하다. 그래서 **의심 신호가 있을 때만** LLM으로
escalate 한다 — 게이트는 비용 최적화, 판정기는 최종 방어.
LLM 호출 실패 시 조용히 skip 하고 규칙 결과만 쓴다(fail-safe to rules).

**정직한 한계**: 무한 패러프레이즈를 100% 차단할 수는 없다. 목표는 "완벽 차단"이 아니라
겹층으로 "탈옥·유출을 실질적으로 어렵게" 만드는 것이다. 오프라인에서는 1·3·4층만 동작한다.

---

## 커맨드 캐시

[`core/command_cache.py`](../core/command_cache.py) · 정책: [design/M1_P4_캐시정책.md](design/M1_P4_캐시정책.md)

LLM API 없이 자주 쓰는 명령을 즉시 실행한다. 저지연 + 오프라인 대응.

### 2단계 매칭

**Stage 1 — 인텐트**: `(entity, action)` 추출 → `_intent_index` 직접 조회.

문자열 유사도만 쓰면 안 되는 이유: "계산기 켜줘"와 "계산기 꺼줘"는 글자 유사도가
약 0.93이라 **틀린 답을 높은 확신으로 반환**한다. 인텐트는 `open` vs `close`를
정확히 구분한다. 시드에 없는 앱+open/close 조합은 `_build_intent_index()`가 자동 합성한다.

**Stage 2 — 유사도 fallback**: `SequenceMatcher` 임계값 0.80.
`_similarity()` 메서드로 캡슐화돼 있어, 후속 작업에서 **이 메서드만 로컬 임베딩
코사인 유사도로 교체**하면 나머지 로직을 그대로 재사용할 수 있다.

### 동적 학습

- LLM이 **성공 실행한 화이트리스트 도구** 명령만 1회 즉시 학습
- **표현만 저장하고 파라미터는 저장하지 않는다** — 오염 원천 차단
- 학습 금지: 자유 파라미터(폴더명·검색어·`set_volume` 숫자·`type_text`), 위험 명령,
  실패한 명령, 보안 차단 입력
- 상한 200(`cache_max_dynamic`), 초과 시 LRU+LFU 정리
- 시드는 삭제 보호. `DELETE /cache`로 동적 항목만 원버튼 롤백

---

## API 엔드포인트

[`main.py`](../main.py)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 서버 상태 |
| POST | `/chat` | 텍스트 명령 (비스트리밍) |
| POST | `/voice` | 음성 파일 → STT + 에이전트 + TTS |
| WS | `/ws` | 텍스트 스트리밍 (※ 현재 단일 청크 — BACKLOG BL-04) |
| GET/POST | `/api/config` | LLM 설정 조회 / API 키 변경 + 에이전트 재초기화 |
| GET/DELETE | `/history` | 대화 히스토리 |
| GET/POST/DELETE | `/favorites` | 즐겨찾기 |
| GET | `/cache` | 캐시 통계 + 동적/시드 목록 (JSON) |
| GET | `/cache/ui` | 개발용 캐시 대시보드 (HTML) |
| DELETE | `/cache` | 동적 학습 전체 초기화 (시드 유지) |
| DELETE | `/cache/entry?pattern=` | 동적 항목 개별 삭제 (시드 보호) |

### API 키 교체 흐름

```python
# POST /api/config → save_config()
1. .env 재작성 (LLM_PROVIDER, {PROVIDER}_API_KEY)
2. get_settings.cache_clear()   # lru_cache 무효화 — 빠뜨리면 옛 키가 계속 쓰임
3. reset_active_agent()         # 신·구 코어 싱글톤 모두 초기화
```

---

## 엔진 이중화 (한시적)

`USE_GRAPH` 플래그로 신/구 엔진을 고른다 ([`core/factory.py`](../core/factory.py)).

- **`true`(기본)** — `PluizGraphAgent`. 그래프 + HITL + 삭제 도구
- **`false`** — `PluizAgent` ([`core/agent.py`](../core/agent.py), 771줄). 비상 폴백

구 엔진은 롤백 낙하산 목적으로 보존 중이며, 제거는 BACKLOG **BL-05**로 관리한다.

---

## 알려진 미해결

상세는 [BACKLOG.md](BACKLOG.md).

- **BL-02** 캐시 부정어 오매칭 — "계산기 **말고** 다른거 열어" → 계산기를 엶
- **BL-03** 보안필터가 공백 없는 변형(`rm-rf`) 미포착
- **BL-04** `/ws` 실제 토큰 스트리밍 미구현
- **BL-05** 구 엔진 제거 → 그래프 단일화
- **BL-06** `test_commands.py`·`test_regression.py`가 구 엔진 기준
- **BL-07** 파일 찾기 UX (확장자 모를 때 헤맴)
- 웨이크워드("소윤아") — 인식률 낮아 보류
