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
  ├─ main.py: auth_guard / ws 토큰 검사      ← 0층. 토큰 없으면 여기서 401 (BL-14)
  │
  ├─ main.py: check_security()              ← 1차 코드 필터
  │
  └─ core/graph_agent.py: get_graph_agent()  ← 단일 엔진
        │
        └─ PluizGraphAgent (오케스트레이터)
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
           │        │
           │        └─(못 믿을 도구)→ visual_verify → agent
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
| `visual_verify` | 도구 실행 결과를 **화면으로** 확인해 증거를 도구 결과에 붙임 (Phase 2) |
| `output_guard` | 빈 응답 복구 + 도구 오류인데 성공처럼 답한 경우 보정 (LLM05, reflection). **아무 일도 안 일어난 턴은 "실행했다"고 하지 않는다** |

### 실행 결과 시각적 검증 — `visual_verify` (2026-09-03)

`output_guard`는 **도구의 자기보고를 믿는다.** 도구가 `[오류]`를 냈는데 AI가 성공처럼
답하면 잡지만, **도구가 거짓으로 `✓`를 반환하면 아무도 모른다.** 이 프로젝트가 반복해서
데인 게 그쪽이다:

대상은 **`type_text` 하나뿐이다**(`VISUAL_VERIFY_TOOLS`). 실행 직후 `describe_screen`을
재사용해 **입력하려던 그 창**을 찍고, 받은 답을 마지막 `ToolMessage` 뒤에
`[화면 확인] …`으로 붙여 `agent`에게 넘긴다.

> **⚠️ 2026-09-03 — 처음 만든 검증은 순환이라 못 쓴다.**
> 처음엔 `type_text` 뒤에 **활성창**을 찍었다. 그런데 `type_text`는 **애초에 활성창에**
> 글자를 넣는다 — 글자가 간 그 창을 그대로 확인하니 **항상 "있다"**가 나온다.
> "엉뚱한 창에 들어갔다"는 BL-12의 **유일하게 중요한 실패 모드를 원리적으로 못 잡고**,
> 실기에서는 Pluiz 오버레이에 들어간 글자를 보고 *"메모장에 적었어요"* 라고
> **거짓 성공에 화면 증거를 붙여 줬다.** 맨몸 거짓말보다 나빴다.
> **지금은 `target`(넣으려던 창)을 찍고, `target`을 모르면 아예 검증하지 않는다.**
> 어디에 넣으려 했는지 모르면 확인할 방법이 없는 게 맞다.

> **⚠️ `open_app`도 뺐다.** `take_screenshot(window=앱)`은 그 창**만** 찍으므로
> 이미지만 봐서는 맨 앞인지 뒤에 가려졌는지 Vision이 알 수 없다 — *"앞에 있나요?"* 라고
> 물어놓고 답할 수 없는 그림을 준 셈이었다. 창이 앞에 있는지는 Win32로 즉시·정확히
> 알 수 있고(`open_app`이 이미 `_focus_window()` 결과로 판단한다) 8초도 안 든다.
> **Vision은 Win32로 알 수 없는 것에만 쓴다.**

**설계에서 중요한 네 가지**

1. **판정하지 않는다.** Vision의 답을 정규식으로 성공/실패로 접지 않고 원문을 그대로
   넘긴다. 손으로 쓴 정규식이 이 프로젝트를 반복해서 무너뜨렸다(BL-02 · BL-15 ·
   HITL 승인 무한루프). **정직하게 보고만 하고 자동 재시도도 하지 않는다.**
2. **증거는 `ToolMessage`를 *교체*해 전달한다.** `add_messages` 리듀서가 **같은 `id`를
   덮어쓰는** 성질을 쓴다. 대안은 전부 깨진다 — `SystemMessage`는 `_prepare_messages`가
   걸러내 LLM이 못 보고, `HumanMessage`는 거기서 턴이 새로 시작되며(절대규칙 6),
   `ToolMessage`를 하나 더 붙이면 한 `tool_call_id`에 둘이 되어 Gemini가 400을 낸다.
3. **부를 값어치가 있을 때만 부른다.** Vision 1회가 약 8초다. 대상 도구가 아니거나,
   도구가 이미 `✗`로 실패를 자백했거나, 이번 턴에 이미 봤으면(`visual_verified`)
   건너뛴다. **`fast_path` 히트는 `tools` 노드를 안 타므로 검증되지 않는다** — 캐시
   경로의 지연 0을 지키려는 의도다.
4. **실패해도 턴을 죽이지 않는다.** Vision은 네트워크·쿼터·포커스로 잘 실패한다.
   예외가 나거나 답이 `✗`면 **아무것도 붙이지 않는다** — 못 본 걸 봤다고 하면 이 노드가
   고치려던 정직성 문제를 스스로 저지르는 꼴이다.

> ⚠️ **`describe_screen`을 `VISUAL_VERIFY_TOOLS`에 넣지 말 것** — 자기 자신을 검증하는
> 재귀가 된다.
>
> ⚠️ **개인정보 (OWASP LLM02)** — 이 노드는 사용자가 화면을 **묻지 않아도** 스크린샷을
> 외부 LLM으로 보낸다. `describe_screen`("물어볼 때만")보다 넓은 전송이다. 그래서
> `.env`의 `VISION_VERIFY_ENABLED=false`로 끌 수 있고, 끄면 노드 자체가 그래프에
> 만들어지지 않아 예전과 완전히 동일하게 돈다. 전체 화면 대신 창 하나만 찍는 것도
> 노출 범위를 줄이려는 선택이다.
>
> ⚠️ **`agent_timeout`을 30 → 45초로 올렸다.** 한 턴이 agent LLM ~3초 + 도구 +
> Vision 8초 + agent LLM ~3초가 되기 때문이다.

#### 진짜 방어선은 도구 자신이다 — `type_text`의 사전 포커스 확인

이 노드는 **사후 관측**이라 잘못 들어간 글자를 되돌리지 못한다. 그래서 도구 쪽을 함께
고쳤다. `type_text(text, target)`는 **입력하기 전에**:

1. `find_hwnd_for_app(target)`으로 대상 창을 찾고 — 없으면 **입력하지 않는다**
2. 대상이 포그라운드가 아니면 `_focus_window()`로 한 번 가져와 본 뒤 다시 확인하고,
   그래도 아니면 **입력하지 않는다.** 이때 *"지금 앞에 있는 건 'Pluiz' 창이라
   여기에 글자가 들어갈 뻔했어요"* 처럼 **어디에 들어갈 뻔했는지** 알린다
3. 성공해도 `✓ '제목 없음 - 메모장' 창에 입력했습니다` 처럼 **어느 창에 넣었는지 밝힌다**

3번이 있었으면 실기의 오보를 사용자가 즉시 알아챘을 것이다 — 예전엔 `"✓ 입력 완료"`만
말해서 **어느 창에 들어갔는지 아무도 몰랐다.**

창 조회·포커스는 `tools/app_control.py`의 것을 재사용한다. 따로 구현하면 앱 별칭
("메모장"→`notepad`) 해석이 어긋난다.

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

## 도구 (36개)

[`core/tool_registry.py`](../core/tool_registry.py)에 단일 등록.

| 분류 | 개수 | 도구 |
|---|---|---|
| 앱 제어 | 5 | `open_app` `close_app` `maximize_window` `minimize_window` `show_desktop` |
| 웹 | 6 | `open_url` `web_search` `youtube_search` `map_search` `fetch_web_info` `crawl_page` |
| 파일 | 7 | `create_file` `create_folder` `find_file` **`list_directory`** `open_recent_file` `open_file` `write_excel` |
| 시스템 | 10 | `volume_up/down/set` `mute_toggle` `brightness_up/down` `take_screenshot` `get_battery_status` `get_current_time` `get_running_apps` |
| 입력 | 3 | `type_text` `press_key` `get_clipboard_text` |
| 캘린더 | 1 | `create_calendar_event` |
| 화면 이해 | 2 | `describe_screen`(무엇이 보이나) · `find_ui_element`(어디에 있나 — **화면 좌표**) — ⚠️ 둘 다 **화면 내용을 외부 LLM로 전송** (아래 참조) |
| **삭제** | **2** | `delete_file` `delete_folder` — **HITL 승인 필수** |

> **삭제 도구 안전장치**: `core/graph.py`의 `DANGEROUS_TOOLS`에 등록돼 있어
> `hitl` 노드가 `interrupt()`로 실행을 멈추고 사람 승인을 받는다. 프롬프트로 부탁하는
> 대신 **그래프 구조가 강제**한다.
>
> ⚠️ **새 위험 도구를 추가할 땐 `DANGEROUS_TOOLS`에 반드시 추가할 것.**
> 여기 빠지면 승인 없이 실행된다. → [design/M1_P5_엔진단일화.md](design/M1_P5_엔진단일화.md#3-4-안전장치는-어디로-갔나)

> **`describe_screen` 개인정보 주의 (OWASP LLM02)**
> 스크린샷을 Vision LLM에 보내므로, 화면에 비밀번호·계좌·주민번호가 떠 있으면
> **그것도 함께 외부로 나간다.** 완화책은 두 가지다.
> - 도구 설명에 *"사용자가 화면 내용을 물어볼 때만"* 을 못박아 LLM의 임의 호출을 억제
> - 반환된 설명은 `mask_sensitive_output()`을 거쳐 나간다 — **출력 노출은 막지만
>   전송 자체는 막지 못한다.** 원천 차단하려면 로컬 Vision 모델이 필요하다(범위 밖).
>
> **`find_ui_element` — 좌표를 지어내지 않는 것이 전부다 (2026-09-03)**
> `describe_screen`은 설명이 틀려도 사용자가 읽고 거른다. **좌표는 다르다.** 숫자라
> 그럴듯해 보이고 다음 단계(좌표 기반 클릭)가 그대로 믿는다. 그래서 이렇게 막는다.
> - 모델에게 **JSON으로만** 답하게 하고 `[ymin, xmin, ymax, xmax]` 0~1000을 명시한다
>   (모델 기본 관례에 기대면 조용히 어긋난다)
> - 뒤집힌 좌표 · 범위 밖 · 화면의 95% 이상을 덮는 박스("모르겠다"를 그림으로 그린 것) ·
>   **후보가 여럿인 응답**은 전부 **못 찾음**으로 처리한다. 조용히 첫 번째를 고르지 않는다
> - **캡처 원점을 먼저 구한다.** 창 위치를 모르면 창 기준 좌표밖에 없는데, 그걸 화면
>   좌표인 척 내보내면 클릭이 엉뚱한 데를 누른다. 원점은 `tools/system.capture_origin`
>   하나만 쓴다 — `_capture_hwnd`가 찍는 영역과 **같은 함수**(`window_screen_rect`)에서
>   나와야 좌표가 어긋나지 않는다
>
> ⚠️ **아직 실측되지 않았다.** Gemini가 좌표를 얼마나 맞히는지는 mock으로 알 수 없다.
> **클릭을 붙이기 전에 반드시 실측할 것.**

> ⚠️ **`visual_verify` 노드는 이 제한을 넘어선다** — 사용자가 화면을 묻지 않아도
> `type_text`·`open_app` 실행 시 자동으로 캡처해 보낸다. 끄는 법과 근거는
> [§ 실행 결과 시각적 검증](#실행-결과-시각적-검증--visual_verify-2026-09-03).
>
> 전송 전 축소(긴 변 1600px)와 임시파일 사용·삭제는 [`tools/vision.py`](../tools/vision.py) 참조.

### 창 규칙 — 기존 창 재사용

`open_app`이 지키는 규칙이다. 2026-09-02에 깨진 걸 발견하고 명문화했다.

| 상황 | 동작 |
|---|---|
| 이미 열려 있음 + 그냥 *"열어줘"* | **기존 창을 앞으로** (새 창을 만들지 않는다) |
| 이미 열려 있음 + *"새로/하나 더/새 탭"* | **새 탭** (탭 지원 앱) · 아니면 새 창 |
| 안 열려 있음 | 실행 |
| **탐색기** | **예외 — 항상 새 창** |

- 호출부는 `open_app(app)` 그대로 쓰고, 새 작업 공간이 필요할 때만 `new=True`를 준다.
  언제 `True`인지는 시스템 프롬프트에 명시돼 있다.
- 탭 지원 앱: 크롬 · 엣지 · 웨일 · 파이어폭스 · 메모장 · 터미널 · 탐색기 (`Ctrl+T`).

> ⚠️ **포커스를 먼저 시도하고, 실패했을 때만 셸 명령으로 폴백한다.**
> 예전엔 순서가 반대였다. UWP 목록에 있으면 `notepad.exe`를 다시 실행했는데,
> 그건 전면화가 아니라 **새 창을 만드는 것**이다. 그래놓고 *"창을 앞으로
> 가져왔습니다"* 라고 답해서 메모장이 계속 쌓였다. 셸 명령 우선은 원래 *설정* 앱의
> 포커스 실패를 우회하려던 것인데, 그 예외가 모든 UWP 앱에 적용되고 있었다.
>
> ⚠️ **새 탭은 포커스 성공을 확인한 뒤에만 `Ctrl+T`를 보낸다.** 포커스가 실패한 채
> 키를 보내면 사용자가 보고 있던 **다른 창**에 들어간다 (BL-12와 같은 함정).
>
> **탐색기가 예외인 이유**: `explorer.exe`에는 바탕화면·작업표시줄 창이 딸려 있어
> 포커스가 그쪽을 잡을 수 있다. 게다가 탐색기는 여러 창을 띄워 쓰는 게 보통이다.

도구 추가 절차는 [WORKFLOW.md § 새 도구 추가](WORKFLOW.md#새-도구-추가).

---

## 웨이크워드

[`services/wakeword.py`](../services/wakeword.py) — 마이크를 계속 듣다가 웨이크워드가
들리면 stdout에 `WAKE`를 찍고, Electron이 그걸 읽어 창을 띄운다.

**기본 웨이크워드는 "플루이즈"** 이고 *"헤이 플루이즈"* 처럼 앞에 말을 붙여 불러도 걸린다(부분매칭).

### 사용자가 직접 바꾼다

| 방법 | 위치 |
|---|---|
| `.env` | `WAKE_WORDS=자비스,헤이 자비스` (쉼표 구분) · `WAKE_WORD_ENABLED=false`로 끔 |
| API | `POST /api/wakeword` `{"wake_words": "...", "enabled": true}` |
| 조회 | `GET /api/config` — `wake_words` · `wake_word_enabled` · `wake_words_default` |

**재시작이 필요 없다.** 웨이크워드는 Electron이 띄운 별도 프로세스라 서버가 직접 못 바꾸는
대신, 그쪽이 10초마다 `.env`를 다시 읽는다(`_RELOAD_SEC`).

### 오인식 변형을 자동 생성한다 — 실측으로 정한 값

Whisper는 "플루이즈" 같은 조어를 거의 못 맞힌다. 사용자가 `플루이즈` 하나만 적어도
`_expand()`가 변형 **87개**를 만들어 붙인다.

**거리는 2다.** edge-tts로 "플루이즈"를 24가지(목소리 2 × 속도 3 × 문형 4)로 합성해
Whisper에 넣고 실제 출력을 수집해 정했다:

| 거리 | 변형 수 | 감지율 | 오탐 |
|---|---|---|---|
| 1 | 15 | 38% | 0/20 |
| **2** | **86** | **69%** | **0/20** |
| 3 | 240 | 69% (이득 없음) | 0/20 |

Whisper가 실제로 뱉은 것: `플로이즈` · `플로이드` · `플로이지` · `플로이 좀` · `하이퍼노이즈`.
그래서 `_CONFUSIONS`에 `루→로`, `즈→드`를 넣었다 — **추측이 아니라 관측값이다.**

실서비스는 0.6초마다 겹쳐 인식하므로 한 번 발화에 창이 3개 생긴다. 체감 감지율은 69%보다 높다.
오탐이 생기면 `_CONFUSIONS`를 줄이거나 `_MAX_DISTANCE`를 1로 내리는 게 첫 조치다.

### 환각 필터 — 없으면 오탐이 난다

Whisper는 짧고 조용한 구간에서 **반복 환각**을 뱉는다. 실측 예:

```
',Z.3 스트레이트 dre,Z.5.4, Z.3.4,Z.3.5.5.6,Z.3,Z.4.6,Z,9,Z,3,Z,Z,4,Z,col…'
```

수백 자짜리 난수 텍스트 안에 변형 하나가 우연히 섞이면 그대로 깨어난다 —
**실제로 그렇게 오탐이 났다.** `looks_hallucinated()`가 길이(60자 초과)와
문자 반복률(35% 초과)로 걸러낸다.

### 모델은 `base`가 기본 — tiny보다 **빠르다**

역설처럼 보이지만 실측값이다(같은 오디오, 2026-09-02):

| 모델 | 전사 | 환각 | 소요 |
|---|---|---|---|
| tiny | 14건 | 3건 | 61.1초 |
| **base** | 14건 | **0건** | **12.9초** |

tiny는 환각으로 수백 토큰을 뱉느라 시간을 다 쓴다. base는 짧고 정확하게 끝낸다.

`hotwords`(고유명사 편향)는 **기본 꺼짐**이다. 켜면 모델이 힌트를 그대로 뱉어
환각이 3건 → 11건으로 늘고 2.4배 느려졌다.

### ⚠️ 어떤 python으로 띄우는지가 결정적이다

`sounddevice` · `faster-whisper`가 필요하다. Electron이 `python`을 그냥 쓰면 Windows에서
보통 **anaconda base**로 잡히는데 거기엔 이 패키지들이 없다.

> **2026-09-02 이전까지 웨이크워드는 한 번도 동작한 적이 없다.**
> `wakeword.py`가 뜨자마자 `exit(1)` 하고 `main.js`가 5초마다 조용히 재시도하기만 했다.
> 발표자료에는 *"tiny 모델 인식률이 낮아 포기"* 로 기록돼 있었다.

지금은 [`electron-ui/main.js`](../electron-ui/main.js)의 `resolvePython()`이 후보를
실제로 import 시켜 보고 고른다: `PLUIZ_PYTHON` 환경변수 → conda `pluiz` 환경 → `python`.
전부 실패하면 **재시도하지 않고** UI에 `unavailable`을 알린다(환경 문제는 재시도로 안 고쳐진다).

---

## 로깅

[`core/logger.py`](../core/logger.py) — `get_logger("이름")` 하나만 쓴다.

| 대상 | 레벨 | 형식 |
|---|---|---|
| 콘솔 | `LOG_LEVEL` (기본 INFO) | `[이름] 메시지` — 기존 `print` 관습과 동일 |
| 파일 `logs/pluiz.log` | DEBUG | 시각·레벨·이름 + 스택트레이스. 5MB×3 로테이션, **UTF-8** |

**전면 교체가 아니다.** 코드베이스의 `print` 71개는 그대로 두고, Vision처럼 실패가 잦고
원인이 눈에 안 보이는 새 기능부터 붙인다. 로드맵의 "로깅 시스템 도입"(방학 미착수분)을
9월 작업에 필요한 만큼만 당겨온 것이다.

> ⚠️ 콘솔이 cp949라 한글이 깨질 수 있다. 파일 핸들러는 `encoding="utf-8"` 필수이고,
> 콘솔 핸들러는 인코딩 실패로 **기능을 죽이지 않도록** 예외를 삼킨다.
> 로깅이 기능을 망가뜨리는 건 본말전도다.

---

## 보안 — 5층 방어

강의 Day5(OWASP LLM Top 10) 개념을 하이브리드 다층 가드레일로 구현.

| 층 | 위치 | 내용 | OWASP |
|---|---|---|---|
| 0. 로컬 API 접근 제어 | [`core/auth.py`](../core/auth.py) + `main.py` 미들웨어 | 기동 시 토큰 발급 → 헤더/쿼리 검사. **가드레일에 도달하기 전에** 정체불명 호출자를 끊는다 | LLM06/08 |
| 1. 규칙 | [`core/security.py`](../core/security.py) | 위험경로 7 · 위험명령 22 · 경로순회 · 인젝션 8 · 민감정보 4. 오프라인·저지연 하드게이트 | LLM01/02 |
| 2. 하이브리드 LLM 판정 | [`core/guardrails.py`](../core/guardrails.py) | 규칙 통과 + `is_suspicious` 신호일 때만 LLM에 ATTACK/SAFE 질의 | LLM01/02 |
| 3. HITL | `core/graph.py` hitl 노드 | 삭제 전 `interrupt()` 승인. **애매한 답변은 취소로 처리**(안전 기본값) | LLM06 |
| 4. 출력 마스킹 | `mask_sensitive_output()` | 주민번호·카드번호·Google/OpenAI API 키 | LLM02/05 |

1~4층은 **입력의 내용**을 검사하고, 0층은 **호출자가 누구인지**를 검사한다.
번호를 0으로 매긴 건 나중에 붙였기 때문이 아니라 **가장 먼저 통과해야 하는 층**이라서다.

**설계 의도**: 규칙은 빠르고 오프라인에서 돌지만 교묘한 우회를 놓친다. LLM 판정은
우회를 잡지만 느리고 온라인이 필요하다. 그래서 **의심 신호가 있을 때만** LLM으로
escalate 한다 — 게이트는 비용 최적화, 판정기는 최종 방어.
LLM 호출 실패 시 조용히 skip 하고 규칙 결과만 쓴다(fail-safe to rules).

**정직한 한계**: 무한 패러프레이즈를 100% 차단할 수는 없다. 목표는 "완벽 차단"이 아니라
겹층으로 "탈옥·유출을 실질적으로 어렵게" 만드는 것이다. 오프라인에서는 1·3·4층만 동작한다.
(0층은 오프라인에서도 동작한다 — 네트워크가 아니라 로컬 파일에 기대기 때문이다.)

### 0층 — 로컬 API 접근 제어 (BL-14)

**막은 것**: 이 서버는 PC를 조작하는데 인증이 없었다. 사용자가 열어 둔 **아무 웹페이지**가
`fetch('http://127.0.0.1:8765/chat', …)` 한 줄로 명령을 넣을 수 있었다.
삭제는 3층(HITL)이 막지만 `open_app`·`type_text`·`open_url`·**`describe_screen`(화면을
외부 LLM으로 전송)** 은 전부 통과했다. 즉 **가장 큰 구멍이 가드레일 바깥**에 있었다.

**구조** — 세 겹이지만 실질적 방어는 ③ 하나다.

| | 무엇 | 무엇을 막나 |
|---|---|---|
| ① | `TrustedHostMiddleware` (Host 고정) | DNS 리바인딩 — 공격 도메인이 `127.0.0.1`로 해석되면 페이지가 서버와 **동일 출처**가 되어 CORS가 통째로 무력화된다 |
| ② | CORS `allow_origins=["null"]` | 일반 웹페이지가 **응답을 읽는 것** |
| ③ | **토큰** — `auth_guard` 미들웨어 + `/ws` 검사 | **명령이 실행되는 것** |

```
python main.py 기동 → secrets.token_urlsafe(32) → cache/.auth_token 기록
   ├ Electron main.js  : 파일 폴링(최대 30초) → IPC로 렌더러에 전달 → fetch 헤더 · WS 쿼리
   └ 라이브 테스트      : core.auth.read_token() 으로 같은 파일을 읽는다
```

- 헤더 `X-Pluiz-Token`, WS·대시보드는 쿼리 `?token=` (브라우저 WS는 헤더를 못 붙인다)
- 면제는 `/health` 하나. 실패는 HTTP `401` / WS `close(1008)`
- 비교는 `secrets.compare_digest`, 토큰이 없으면 **전부 거부**(fail-closed)
- 킬 스위치: `.env` `AUTH_ENABLED=false` (디버깅용. 켜 두면 위 구멍이 그대로 돌아온다)

**설계 근거 세 가지** — 되돌리기 전에 읽을 것.

1. **CORS 축소만으로는 못 막는다.** 렌더러는 `loadFile`이라 출처가 `file://` →
   브라우저가 `Origin: null`을 보낸다. 그 값을 허용해야 UI 자신이 도는데,
   `null`은 아무 사이트의 sandboxed iframe도 받는 값이다. 게다가 **CORS는 응답 읽기만
   막고 요청 처리는 막지 않는다** — 명령은 그대로 실행된다.
2. **`/ws`에는 CORS가 아예 적용되지 않는다.** 웹페이지가
   `new WebSocket('ws://127.0.0.1:8765/ws')`로 그냥 붙을 수 있어 fetch보다 큰 구멍이었다.
   그래서 WS는 엔드포인트 안에서 직접 검사한다(HTTP 미들웨어는 WS를 타지 않는다).
3. **CORS 프리플라이트(OPTIONS)는 인증을 면제한다.** `X-Pluiz-Token`은 safelisted 헤더가
   아니라 렌더러의 모든 요청이 프리플라이트를 거치는데 거기엔 토큰이 실리지 않는다.
   여기서 401을 주면 **UI 자신이 전부 막힌다.**

**정직한 한계** — 이 층이 막는 것은 딱 **웹페이지**다.

- **로컬에서 실행 중인 다른 프로그램**은 `cache/.auth_token`을 읽을 수 있다. 그 수준의
  공격자는 이미 PC에서 코드를 실행하고 있으므로 이 앱을 거칠 이유가 없다 — 위협모델 밖이다.
- 토큰은 평문 파일이고 Windows 파일 권한을 따로 조이지 않는다. 위와 같은 이유다.
- 서버를 재시작하면 토큰이 바뀐다. **라이브 테스트도 그때 다시 실행해야 한다.**

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

**`/health`를 뺀 전부가 토큰을 요구한다** (0층 — 없으면 401). 아래 "인증" 열 참조.

| 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|
| GET | `/health` | **면제** | 서버 상태 |
| POST | `/chat` | 필요 | 텍스트 명령 (비스트리밍) |
| POST | `/voice` | 필요 | 음성 파일 → STT + 에이전트 + TTS. **`thread_id`·`use_tts`는 `Form(...)`이어야 한다** — 빼면 폼 필드가 무시돼 음성이 텍스트와 다른 대화가 된다 |
| WS | `/ws` | 필요 (`?token=`) | 텍스트 스트리밍 (※ 현재 단일 청크 — BACKLOG BL-04) |
| GET/POST | `/api/config` | 필요 | LLM 설정 조회 / API 키 변경 + 에이전트 재초기화 |
| POST | `/api/wakeword` | 필요 | 웨이크워드 설정 (`.env` 갱신, 재시작 불필요) |
| GET/DELETE | `/history` | 필요 | 대화 히스토리 |
| GET/POST/DELETE | `/favorites` | 필요 | 즐겨찾기 |
| GET | `/cache` | 필요 | 캐시 통계 + 동적/시드 목록 (JSON) |
| GET | `/cache/ui` | 필요 (`?token=`) | 개발용 캐시 대시보드 (HTML). **전체 URL이 서버 기동 로그에 찍힌다** |
| DELETE | `/cache` | 필요 | 동적 학습 전체 초기화 (시드 유지) |
| DELETE | `/cache/entry?pattern=` | 필요 | 동적 항목 개별 삭제 (시드 보호) |

### API 키 교체 흐름

```python
# POST /api/config → save_config()
1. .env 재작성 (LLM_PROVIDER, {PROVIDER}_API_KEY)
2. get_settings.cache_clear()   # lru_cache 무효화 — 빠뜨리면 옛 키가 계속 쓰임
3. reset_active_agent()         # 신·구 코어 싱글톤 모두 초기화
```

---

## 엔진 (단일)

`PluizGraphAgent`가 유일한 엔진이다. 구 엔진(`PluizAgent`, 771줄)과 `USE_GRAPH`
플래그는 M1-P5에서 제거됐다.

구 엔진 소스는 **[`archive/core_agent_v1.py`](../archive/core_agent_v1.py)** 에
그대로 남아 있고, 제거 배경·기능 대응표·복원 방법은
**[design/M1_P5_엔진단일화.md](design/M1_P5_엔진단일화.md)** 에 정리돼 있다.

LLM provider 추상화는 [`core/llm.py`](../core/llm.py)의 `build_llm()`이 담당한다
(원래 구 엔진 안에 있던 것을 분리).

---

## 알려진 미해결

상세는 [BACKLOG.md](BACKLOG.md).

- **BL-15** fast_path 명령 절단 (캐시가 뒷문장을 조용히 버린다)
- **BL-04** `/ws` 실제 토큰 스트리밍 미구현
- **BL-07** 파일 찾기 UX (확장자 모를 때 헤맴)
