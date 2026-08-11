# Pluiz v2 — 개발 일지 (DEVLOG)

> 작업 진행을 시간순으로 누적 기록하는 개발 일지입니다.
> 각 항목: **일시 / 목표 / 완료 스텝 / 검증 결과 / 특이사항**.
> 가장 최신 항목이 위로 오도록 작성합니다.

---

## 2026-08-11 17:12 KST — 전체 회귀 스윕 결과 + 낡은 테스트 정리

### 사용자 Windows 회귀 결과 (새 엔진, USE_GRAPH=true)
- test_commands.py: 대체로 PASS. **INPUT-02만 실패 = 환경 문제**(pyperclip 미설치,
  `pip install pyperclip`로 해결). 코드 회귀 아님.
- test_regression.py: 21개 중 19 PASS / 2 FAIL.

### ⚠️ 파동효과 결론: 새 엔진 전환으로 깨진 기능 없음
두 FAIL 모두 **우리 변경이 아니라 테스트 코드가 낡은 것**으로 확인:
- **R-11**(탐색기 차단): 동작은 정상(차단 경고 정상 출력). 테스트 판정어
  (`셸 프로세스` 등)가 실제 메시지(`시스템 프로세스`, `파일 탐색기`)와 불일치 → 오탐.
  (close_app 메시지는 우리가 안 건드림.)
- **R-07**(agent.py `닫기` 존재): `닫기`는 agent.py에 **원래도 없음**(git diff로 확인,
  우리가 지운 것 아님). `말기→닫기` 교정은 현재 프롬프트에 무관한 구식 검사였음.

### 수정 (`test_regression.py`)
- R-11: 판정어를 실제 메시지에 맞게 확장(`시스템 프로세스`/`닫을 수 없`/`파일 탐색기`).
- R-07: 무관한 `말기`/`닫기` 검사 제거, 유효한 `벼륨→볼륨`만 유지.
- 정적 재현으로 두 항목 통과 확인. 컴파일 OK.

### 백로그
- BL-06(신규): 테스트 스위트(test_commands/test_regression)가 **옛 엔진 기준**으로 작성됨.
  새 엔진 수렴 시 스위트도 그래프 엔진 기준으로 갱신 필요.

### 결론
**P2 완전 종료.** 새 엔진 기본 + HITL + 삭제 게이팅 + 회귀 무결(테스트 오탐만 정리).
다음: **P3 — OWASP 보안 가드레일**.

---

## 2026-08-11 — ✅ P2(HITL 승인) 완료 — 캡스톤 정리

### P2가 한 일 (요약)
위험 명령(파일/폴더 삭제)을 **실행 전에 사람 승인**을 받도록 만들었다. 강의 개념
HITL(Lab19) + Excessive Agency(LLM06) 대응을 그래프 노드로 실제 구현.

### 무엇을·어떻게 (단계별)
- **P2-1** 삭제 도구 신설(`delete_file`/`delete_folder`) — 휴지통 이동(send2trash) +
  보호경로/드라이브루트 차단. (기존엔 삭제 기능 자체가 없었음)
- **P2-2** 그래프 `hitl` 노드 + langgraph `interrupt` — 위험 도구 감지 시 일시정지·질문.
- **P2-3** 오케스트레이터 resume 배선 — 대기 감지 후 다음 발화를 `Command(resume)`으로.
- **동기 전환**(엔지니어링 결정) — langgraph 1.2.10 async+interrupt 버그 회피 위해
  그래프 노드 sync화 + `asyncio.to_thread(graph.invoke)`. 우리 도구가 원래 동기라 더 자연스러움.
- **엔진 정책** — 새 엔진(그래프+HITL) **기본값 승격**, 삭제 도구는 새 엔진에서만 노출(게이팅).

### 지금 상태 (현재)
- **기본 엔진 = PluizGraphAgent(그래프)**. 구 엔진은 비상 폴백으로 보존(`USE_GRAPH=false`).
- **HITL 실사용 검증 완료**: 사용자 Windows에서 삭제 요청 → 매번 "정말 삭제할까요?" →
  "응" 삭제 / "아니" 취소 정상. startup 로그 `[PluizGraphAgent] tools=33개` 확인.
- **확인 없는 삭제 원천 불가**: 새 엔진=HITL 강제, 구 엔진=삭제 도구 없음.
- mock 테스트 6종 55개 전부 그린, 전체 컴파일 OK.

### ⚠️ 파동효과(ripple) 주의 — 미완 회귀
- 오늘 **동기 전환 + 새 엔진 기본값 승격**으로 이제 **모든 명령이 새 엔진 경유**.
  그런데 새 엔진의 **비삭제 기능(앱·볼륨·웹·파일·캘린더 등) 전체 실기 회귀는 아직 안 함**
  (P1.5-e 실기는 동기 전환 *이전* 버전이었음).
- → **P2 마무리 전, 사용자 Windows 전체 회귀 스윕 필요**(아래 테스트 항목).

### 백로그 연동
- BL-04(도구 미호출 재시도·토큰 스트리밍 미이관), BL-05(구 엔진 최종 제거).

### 다음
전체 회귀 스윕 통과 확인 → P3(OWASP 보안 가드레일)로.

---

## 2026-08-11 (저녁) — 엔진 정책 확정: 새 엔진 기본 승격 + 삭제 도구 게이팅

### 배경 (왜 엔진이 두 개인가)
- P1.5 그래프 이관은 코어 실행경로 교체라 최고 위험 작업 → **안전 전략으로
  신·구 엔진 병존 + `USE_GRAPH` 플래그**를 채택(즉시 롤백용 낙하산).
  - 구 엔진: `core/agent.py`(PluizAgent) — 원본. HITL·삭제 게이트 없음.
  - 신 엔진: `core/graph.py`+`graph_agent.py`(PluizGraphAgent) — 그래프 + HITL.
- 두 엔진 공존이 "지금 어느 엔진인가?" 혼란 유발. 실기 중 삭제가 들쭉날쭉했던 원인:
  **구 엔진은 삭제 확인을 프롬프트 부탁에만 의존** → LLM이 불규칙하게 물어봄
  (신 엔진은 interrupt로 코드 레벨 강제 → 항상 물어봄).

### 결정 (사용자 승인)
- **① 새 엔진 기본값 승격**: `settings.use_graph` 기본 `False→True`,
  `.env.example` `USE_GRAPH=true`. 설정 없이도 그래프+HITL 엔진이 기본.
- **② 삭제 도구 게이팅**: `tool_registry.get_all_tools()`가 `use_graph=True`일 때만
  `delete_file`/`delete_folder` 노출. → **구 엔진엔 삭제 도구 자체가 없어
  "확인 없는 삭제"가 원천 불가능.** (신 33개 / 구 31개 확인)
- 구 엔진은 **당분간 비상 폴백으로 보존**(롤백 낙하산 + 미이관 항목 BL-04 백업).

### 엔진 최종 방향 (로드맵)
- 새 엔진이 실사용에서 충분히 검증되면 → **구 엔진(`core/agent.py`) 완전 삭제**,
  `factory.py`/`USE_GRAPH` 플래그도 제거하여 **그래프 단일 엔진으로 수렴**.
- 선행 조건: BL-04(도구 미호출 재시도, 토큰 스트리밍) 이관 여부 판단 + 며칠 실사용 무결.

### 검증
- 삭제 도구 게이팅 use_graph별 정상. mock 테스트 6종 전부 회귀 통과. 컴파일 OK.

### 남은 것
- P2-5 재검증(사용자): 콘솔에 `[PluizGraphAgent]` 확인 후 삭제 승인/거부 재확인.

---

## 2026-08-11 (저녁) — P2-2·3·4: HITL(interrupt) 구현 + 동기 전환

### 엔지니어링 결정: 그래프 동기(sync) 전환

- **문제**: langgraph 1.2.10에서 `interrupt()`가 async `ainvoke` 경로에서
  "config 컨텍스트 없음" 에러(버전 버그). sync `invoke`에선 정상.
- **해결(사용자 승인)**: 그래프 노드를 async→sync 전환, 오케스트레이터가
  `asyncio.to_thread(graph.invoke)`로 실행(이벤트 루프 비블로킹).
  우리 도구가 원래 동기 함수라 구조적으로도 더 자연스러움. technical debt 없음.
- 전환 파일: router.py / fast_path.py(+command_cache.execute_sync 추가) /
  graph.py(노드 sync) / graph_agent.py(to_thread + resume 배선).

### P2-2 hitl 노드 (`core/graph.py`)

- `DANGEROUS_TOOLS={delete_file, delete_folder}`, `interpret_confirmation`(거부 우선·애매시 취소),
  `_confirm_question`(파일명 포함 질문).
- `hitl` 노드: `interrupt(question)`로 일시정지. 승인→tools, 거부→취소 응답
  (매달린 tool_calls를 ToolMessage로 마감해 오염 방지).
- 라우팅: agent→(위험 도구)→hitl→(승인)tools/(거부)output_guard.

### P2-3 오케스트레이터 resume 배선 (`core/graph_agent.py`)

- `_pending_interrupt`(get_state로 대기 감지) → 대기 중이면 다음 발화를
  `Command(resume=발화)`로 전달. interrupt 발생 시 질문을 반환(세션 저장 보류).

### P2-4 검증: 총 55개 테스트 통과

- test_hitl_graph 11/11 (그래프 interrupt/resume), test_hitl_agent 8/8 (오케스트레이터
  승인/거부/대기해제), fast_path 11, graph_context 10, graph_agent 6, delete_tools 9.
- 회귀 전부 유지(동기 전환 후에도 맥락·보안·타임아웃 정상).

### 다음

P2-5: 사용자 Windows 실기 (USE_GRAPH=true 필수 — HITL은 그래프 코어에만 있음).

---

## 2026-08-11 (저녁) — P2-1: 위험 도구 추가 (삭제)

### 목표

HITL로 보호할 위험 동작 마련: 파일/폴더 삭제 도구 (기존엔 삭제 기능 자체가 없었음).

### 완료

- **`tools/filesystem.py`** — `delete_file`/`delete_folder` 추가.
  - `_to_trash`: send2trash로 휴지통 이동, 실패 시 영구삭제 fallback.
  - `_is_protected_path`: 드라이브 루트(정규식) + Windows/System32/Program Files 차단.
  - 파일↔폴더 혼동 방지, 없는 경로 안내.
- **`core/tool_registry.py`** — 등록(총 31→**33개**). 위험 동작으로 주석 표시.
- **`requirements.txt`** — `send2trash>=1.8.0` 추가.
- ⚠️ 삭제 도구는 캐시/라우터에 넣지 않음 → 반드시 LLM+HITL 경유(다음 단계).

### 검증

- `test_delete_tools.py` 9/9: 파일/폴더 삭제, 없는 경로, 혼동 거부, 보호경로 차단.
- 등록 도구 33개 확인. 컴파일 OK.

### 다음

P2-2: graph.py에 hitl 노드 + interrupt, 위험 도구 감지 라우팅.

---

## 2026-08-10 (저녁) — P1.5-e: 실기 검증 완료 → ✅ P1.5 이관 성공

### 검증 (사용자 Windows, USE_GRAPH=true)

| 테스트                                 | 결과                                            |
| -------------------------------------- | ----------------------------------------------- |
| "메모장 열어줘" → "그거 닫아줘"        | ✅ 맥락 복원("메모장 닫았어요")                 |
| "계산기 켜줘" → (딴말) → "닫아 달라고" | ✅ 딴말 껴도 맥락 유지("계산기 닫았어요")       |
| "계산기 켜줘"                          | ✅ 캐시                                         |
| "볼륨 30으로 설정해줘"                 | ✅ 라우터                                       |
| "유튜브에서 아이유 틀어줘"             | ✅ 라우터(유튜브 재생)                          |
| "메모장이랑 계산기 열어줘"             | ✅ LLM 복합                                     |
| "rm-rf 실행해줘"                       | ⚠️ 차단됨(단, 코드필터 아닌 LLM이 거절 — BL-03) |

**결론: 그래프 코어(PluizGraphAgent)가 실기에서 정상 동작. P1.5 이관 성공.**
기존 agent.py는 폴백으로 보존(USE_GRAPH=false 시 즉시 복귀 가능).

### 발견 → 백로그

- **BL-03** "rm-rf"(공백 없는 변형)를 code 보안필터(`security.py`)가 미포착.
  LLM 백스톱이 거절해 결과는 안전. 기존부터 있던 갭(이관과 무관). BACKLOG 등록.

### P1.5 미이관(후속 판단) — 실기상 문제 없었음

- 도구 미호출 재시도(RETRY_PROMPT): 새 코어 미이관. 실기에서 이상 없음.
- 토큰 단위 스트리밍(/ws): 현재 단일 청크. 음성(/voice)엔 영향 없음.

### 다음 결정 대기

- 그래프 코어를 기본값으로 승격할지(현재 코드 기본 use_graph=False, 사용자 .env에서 true).

---

## 2026-08-10 16:45 KST — P1.5-d: main.py 플래그 전환

### 목표

`.env USE_GRAPH`로 신(그래프)/구(기존) 코어 무중단 선택. 기본 false → 무영향.

### 완료

- **`core/factory.py` 신규** — `get_active_agent()`/`reset_active_agent()`:
  USE_GRAPH에 따라 PluizAgent(구) 또는 PluizGraphAgent(신) 싱글톤 반환.
- **`config/settings.py`** — `use_graph: bool = False` 추가.
- **`.env.example`** — `USE_GRAPH=false` 문서화.
- **`main.py`** — `get_agent()`→`get_active_agent()` (3곳: /chat·/voice·/ws),
  reset도 `reset_active_agent()`로. import 교체.

### 검증

- 컴파일 OK. main.py에 직접 get_agent() 호출 잔존 0.
- USE_GRAPH 플래그 파싱: 기본 False / "true"→True 확인.
- 팩토리 선택 로직(mock): false→구, true→신 정상.
- 기본값 false라 **현재 동작 무변화**(안전).

### 다음

P1.5-e: 사용자 Windows 실기 검증.

1. USE_GRAPH=false로 기존 동작 정상 재확인
2. USE_GRAPH=true로 전환 후: 맥락(캐시 후속)·앱제어·볼륨·검색·보안·타임아웃 회귀 확인
3. 문제 시 플래그 false 원복. 결과에 따라 미이관 항목(도구 재시도·토큰 스트리밍) 판단.

---

## 2026-08-10 16:35 KST — P1.5-c: 오케스트레이터 (PluizGraphAgent)

### 목표

그래프 부품들을 하나로 묶어, 기존 PluizAgent와 동일 공개 API로 제공.

### 완료 (신규 2파일, agent.py 불변)

- **`core/router.py`** — 결정론적 라우터(youtube/map/folder/volume/max·min)를
  그래프 경로용 독립 async 함수 `route_deterministic`로 이관. tool import는 분기 내 lazy.
- **`core/graph_agent.py`** — `PluizGraphAgent`:
  - 공개 API `run_async(user_input, thread_id)` / `stream(...)` (기존과 동일 시그니처).
  - 의존성 주입 가능(테스트) + 미주입 시 프로덕션 기본값 lazy import.
  - fast_path = 캐시 + router 결합(resolve_fast_path).
  - 타임아웃(agent_timeout), 세션저장, 네트워크/타임아웃/히스토리오염 예외 처리.
  - `get_graph_agent()` / `reset_graph_agent()` 싱글톤.

### 검증

- `test_graph_agent.py` 6/6: 맥락+세션저장 / 보안차단 / 타임아웃 / stream API.
- 회귀: fast_path 11/11, graph 10/10 유지. 컴파일 OK.

### 남은 것 / 메모

- stream()은 현재 단일 청크 반환(토큰 스트리밍은 후속 정교화, 기능엔 지장 없음).
- 도구 미호출 재시도(RETRY_PROMPT)는 미이관 → P1.5-e 실기에서 필요성 확인 후 판단.

### 다음

P1.5-d: `main.py`가 `.env USE_GRAPH` 플래그로 신(PluizGraphAgent)/구(PluizAgent) 선택.
설정 추가 + 팩토리. 착수 전 보고.

---

## 2026-08-10 16:20 KST — P1.5-b: 그래프 노드 실로직

### 목표

graph.py 노드에 실제 로직 채우기 + 실서비스용 async 전환.

### 완료 (`core/graph.py` 갱신, agent.py 불변)

- **노드 async 전환**: agent=`ainvoke`, fast_path=async 어댑터 `await`(동기/비동기 모두 허용).
- **output_guard 실로직**: 순수 함수 `verify_output(messages)`로 이관 —
  ① 도구오류 + 성공처럼 보이는 응답 → 보정(T04) ② 빈 응답 → ToolMessage로 복원.
- **fast_path ↔ P1.5-a 어댑터** 연결 시그니처 확정.
- `_msg_text`/`extract_response` 등 메시지 유틸 정리.

### 검증

- `test_graph_context.py`(async) 10/10: 맥락 유지 / 보안 차단 / verify_output 3케이스.
- 회귀: `test_fast_path.py` 11/11 유지. graph.py 컴파일 OK.

### 다음

P1.5-c: `PluizGraphAgent` 오케스트레이터 — 기존 PluizAgent와 동일 공개 API
(run_async/stream) + 타임아웃·세션저장·폴백·재시도 래핑. 착수 전 보고.

---

## 2026-08-10 16:09 KST — P1.5-a: fast_resolve 어댑터

> ※ 이 항목부터가 오늘(2026-08-10) 작업. 위쪽 07-30 항목들은 지난 세션 기록.
> (시스템/샌드박스 시계 모두 2026-08-10로 확인)

### 목표

그래프 fast_path 노드가 쓸, 캐시+라우터+복합감지 통합 순수 함수 구현 (P1.5 첫 단계).

### 완료 (`core/fast_path.py` 신규)

- `resolve_fast_path(user_input, cache, router_resolve)` — DI 기반, OS·API 불필요.
  1. 복합/문맥참조 명령 감지 → None(=LLM으로) 2) 캐시 조회·실행 3) 라우터.
- `is_compound_command` / `is_multi_app_command` 헬퍼.
- 기존 agent.py 규칙(\_COMPOUND_CMD, 다중앱)과 동일 로직 (원본 불변).

### 검증

- `test_fast_path.py` 11/11 통과 (캐시히트·라우터히트·복합·다중앱·미스·빈입력).
- 컴파일 OK.

### 다음

P1.5-b: `core/graph.py` 실 노드 로직(input_guard·fast_path·output_guard) 구현. 착수 전 보고.

---

## 2026-07-30 17:10 KST 무렵 — P1.5 계획: 그래프 이관 계획서 작성

### 결정 배경

- HITL(P2)을 (A)지금 구조에 붙이기 vs (B)그래프로 이관 후 얹기 사이에서,
  향후 로드맵(HITL+OWASP+reflection이 전부 그래프 노드 자리)을 고려하면
  A식 개별 패치는 "흩어진 if/return" 구조를 재축적 = technical debt.
  → 사용자와 합의: **지금 그래프로 이관(B)** 후 P2/P3를 노드 추가로 진행.
- 현재/목표 구조 비교 다이어그램으로 사용자 인식 정렬 완료.

### 산출물

- `docs/M1_P1.5_그래프이관_계획.md` — 로직 이관 1:1 매핑표, 파일 변경 계획,
  단계(P1.5-a~e), 리스크/완화, 완료기준.
- 핵심 안전장치: 기존 agent.py 폴백 유지 + `.env USE_GRAPH` 플래그 전환 + 롤백.

### 다음

계획서 승인 시 → P1.5-a(fast_resolve 어댑터)부터 착수. 각 단계 착수 전 보고.

---

## 2026-07-30 16:50 KST — BL-01: 에이전트 타임아웃 적용

> ※ 날짜 정정: 이전 기록의 "2026-07-15"는 샌드박스 시계 오류였음. 실제 날짜 2026-07-30로 전면 수정.
> 이후 일지는 확인된 날짜/시각으로만 기록. (시각은 사용자 확인값 16:48 KST 기준 근사)

### 목표

복잡한 명령에서 LLM 호출 지연/정지 시 UI가 무한 "처리중"이 되는 문제(BL-01) 해결.

### 수정 내용 (`core/agent.py`)

- `import asyncio` 추가.
- `_ainvoke_with_timeout(payload, config)` 헬퍼: `settings.agent_timeout`(기본 30초)로
  `graph.ainvoke`를 `asyncio.wait_for` 감쌈. (기존 미사용 설정값을 실제 연결)
- run_async의 ainvoke 3곳(메인/오염재시도/도구미호출재시도) 모두 헬퍼 경유로 교체.
- 타임아웃 발생 시 친절 메시지 반환:
  "처리가 너무 오래 걸려서 중단했어요. 조금 더 간단하게 말씀해 주시겠어요?"

### 검증

- agent.py 컴파일 OK. 감싸지 않은 직접 ainvoke 없음(헬퍼 내부 1곳만 정상).
- asyncio.wait_for 타임아웃 메커니즘 동작 확인(1초 초과 → TimeoutError → 친절 경로).

### 범위/남은 것

- 이번엔 run_async(=/voice, /chat, /ws 제어명령 경로) 커버. 사용자가 겪은 무한 대기가 이 경로.
- stream()의 대화형 astream 경로는 미적용(무한루프 위험 낮음) → 필요 시 후속.
- 실제 체감 확인은 Windows에서: 복잡 명령이 30초 초과 시 친절 메시지로 끊기는지.

---

## 2026-07-30 (P1 완료) — M1-P1 확정: agent.py 맥락 패치 (소규모 수정 채택)

### 방향 전환 (중요)

- 사용자 PC 콘솔 로그로 **버그 범위 실측 확정**:
  - 턴1 "메모장 열어줘" → `[CommandCache] 히트`(LLM 미경유) → 턴2 "그거 닫아줘"
    → `도구 미호출 감지 → 재시도` **실패** (맥락 버그 재현 ✓)
  - 대조: "메모장이랑 계산기 열어줘"(복합→LLM) → "방금 연 거 다 닫아줘" **정상**
  - ⇒ 버그는 **앞 명령이 캐시/라우터로 처리된 경우에만** 발생하는 **조건부** 문제로 확정.
    (복합·다중앱 명령은 원래 LLM 경유라 맥락 유지됨 — 사용자 기억이 맞았음)
- 추가 발견(미수정, 백로그): "계산기 **말고** 다른거 열어" → 캐시가 '계산기 열어줘'로
  오매칭(부정어 무시). 별도 이슈로 기록.
- 결정: 큰 공사(graph.py 재설계) 대신 **agent.py 소규모 수정** 채택.
  graph.py/test_graph_context.py는 POC로 보존(미연결, 프로젝트 영향 없음).

### 수정 내용 (`core/agent.py`)

- `_record_fast_path(thread_id, user_input, result_text)` 헬퍼 추가:
  `graph.update_state(config, {"messages":[HumanMessage, AIMessage]})`로
  빠른 경로 처리 명령을 LangGraph 기억에 append.
- 호출 3곳: run_async 캐시 히트 / run_async 라우터 히트 / stream 캐시 히트.

### 검증 (프로덕션 구조 동일하게 재현)

- create_react_agent + MemorySaver + update_state 로 검증:
  - 패치 적용: "메모장 열어줘"(update_state) → "그거 닫아줘" → **"메모장을 종료했어요"** ✓
  - 대조군(기억 없음): → "무엇을 닫을까요?" (버그 재현) ✓
- 패치된 agent.py 문법 컴파일 OK.

### 남은 확인 (사용자, Windows) → ✅ 확정

- 사용자 PC 재테스트 결과: "메모장 열어줘"(캐시) → "그거 닫아줘" **정상 작동 확인.**
- **P1 완료(맥락 버그 수정).** 패치가 프로덕션에서도 의도대로 동작함.

### 신규 백로그 (P1 중 발견, 미수정)

- **BL-01 에이전트 타임아웃 부재**: 복잡한 LLM 명령("계산기 빼고 다 닫아줘" 등)에서
  Gemini 호출이 지연/정지 시 UI가 "처리중"으로 무한 대기. `recursion_limit=10`은
  도구 횟수만 제한, **시간 제한 없음**. `settings.agent_timeout=30`이 정의돼 있으나
  **미사용**. → `asyncio.wait_for`로 run_async/stream 감싸 초과 시 친절 메시지 반환 필요.
- **BL-02 캐시 부정어 오매칭**: "계산기 말고 다른거 열어" → 캐시가 '계산기 열어줘'로 오작동.
  (앞서 기록) 캐시 바이패스 패턴에 '말고' 추가 등으로 해결 가능.

---

## 2026-07-30 (계속) — M1-P1(POC): 그래프 골격 + 맥락 개념 검증

### 목표

빠른 경로(캐시/라우터)가 대화 기억에 누적되지 않아 생긴 맥락 버그를,
명시적 LangGraph StateGraph로 단일 상태(messages) 통합해 근본 해결.

### 완료 (기존 코드 무손상, 신규 파일 병행)

- **`core/graph.py` 신규** — StateGraph 골격
  - 노드: input_guard → fast_path → (miss)agent ⇄ tools → output_guard → END
  - 의존성 주입(llm/tools/security_check/fast_resolve) → Windows·API 없이 mock 검증 가능
  - **fast_path 히트 시 결과를 AIMessage로 messages에 기록** = 맥락 통합 핵심
  - output_guard는 P3(OWASP/reflection) 자리로 pass-through
- **`test_graph_context.py` 신규** — mock LLM/보안/캐시로 맥락 검증

### 검증 결과: 7/7 통과

- 시나리오 A(맥락): 턴1 "메모장 켜줘"(캐시, LLM 미호출) → 턴2 "그거 꺼줘"에서
  LLM 히스토리에 "메모장" 포함 확인 → "메모장 종료" 정확 응답. **맥락 버그 해결 입증.**
- 시나리오 B(보안): 위험명령 LLM 도달 전 차단, LLM 미호출.
- 회귀: 기존 파일(agent/command_cache/security) 컴파일 무손상.

### 특이사항 / 남은 일

- 현재 graph.py는 **검증된 골격**. 아직 실서비스(main.py)에 연결 안 함 —
  실제 llm(\_build_llm)·tools(get_all_tools)·get_cache 와이어링은 별도 단계로,
  **연결 전 사용자 보고 예정** (라이브 경로 교체는 신중히).
- 샌드박스에 langgraph 1.2.10 / langchain-core 1.5.2 / pydantic-settings 설치(테스트용).
  실제 프로젝트 requirements와 버전 정합성은 Windows에서 확인 필요.

### 다음

P1 마무리 = graph.py를 실제 의존성에 연결하는 어댑터 설계 후 보고 →
승인 시 main.py 경로 점진 전환 (기존 agent.py 폴백 유지).

---

## 2026-07-30 (계속) — M1-P0: 진단 + 아키텍처 설계 문서 완료

### 목표

맥락 버그 근본 진단 + "마지막 아키텍처 정리"로서 목표 구조 확정 (코드 수정 전 설계).

### 완료

- **맥락 버그 근본원인 확정**: thread_id 누락(과거 노트)이 **아님**을 코드로 반증.
  - UI가 세션당 thread_id 1회 생성·재사용 (index.html:1252 → 1709,1736)
  - 백엔드 config 전달 정상 (agent.py:320,328,659)
  - **진짜 원인**: 캐시/라우터 빠른 경로가 `graph.ainvoke` 미경유하고 return →
    해당 명령이 MemorySaver 대화기록에 누적 안 됨 → 후속 "그거" 지칭 실패.
  - 보조: session.py(SQLite)는 표시용, LLM에 되먹임 안 됨.
- **설계 문서 작성**: `docs/M1_아키텍처_설계.md` (ADR)
  - To-Be: 명시적 LangGraph StateGraph (input_guard→fast_path→agent→tools→hitl→output_guard),
    단일 messages 상태로 맥락 통합.
  - 옵션 비교 A(미봉책)/B(그래프 재설계)/C(B+MCP) → **B 채택**, C는 설계 내장·후반 PoC.
  - 단계 계획: P1 그래프 골격(=맥락 해결) → P2 HITL → P3 OWASP → P4 벡터캐시 → P5(선택) MCP.
  - 리스크/한계·확장성 전략 명시.

### 특이사항

- 시작점 지시("맥락 버그부터")와 목표("그래프 재설계")가 P1에서 동시 충족되는 설계.
- 구현은 신규 파일 병행(예: `core/graph.py`)으로 점진 전환, 롤백 가능하게.

### 다음

P0 승인 → P1 상세 설계 노트 후 그래프 골격 구현 착수 (착수 전 보고).

---

## 2026-07-30 (계속) — Milestone 1 준비: 과거 계획·강의 개념 재구성

> 약 1개월(6.22~7.15) 공백 후 재개. 노션 정리 내용과 계절학기 강의 요약을 반영해
> "어디서 멈췄는지"와 "무엇을 적용할지"를 복구·정리한 기록.

### 재구성된 백로그 (노션 기준)

- **완료** — Sprint 1(T01 stream 재시도 / T02 조사 처리 / T03 클립보드 읽기),
  Sprint 2(T04 도구 결과 검증 / T05 히스토리 UI / T06 즐겨찾기 UI)
- **미착수** — Sprint 3~4: T07 Gemini Vision, T08 마우스 클릭 자동화, T09 병렬 명령,
  T10 패턴 학습, T11 장기 기억, T12 웨이크워드 교체

### 재개 시점의 미해결 결정 3가지 (6.29~7.6 노트)

1. Gemini Vision → 별도 API 불필요. `gemini-2.5-flash`가 멀티모달. (조사 완료)
2. (6.30) "바퀴 재발명 금지" 구조 다이어트 방향: 검색=Tavily/Exa, OS제어=MCP,
   흐름=LangGraph, 파싱=Pydantic. **신규 기능 전에 개선 우선** 결정.
3. (7.6) 맥락 처리 버그 → 수정 + 최종 구조 확정 + 마일스톤 재정리 후 진행하기로.
   → 이 중 "마일스톤 재정리"는 M0(위 항목)에서 완료.

### ⚠️ 7.6 맥락 버그 진단 정정 (중요)

- 노트의 원인 지목("astream에 thread_id/config 누락")은 **현재 코드와 불일치**.
  현재 `run_async`/`stream` 모두 `config={"configurable":{"thread_id":...}}` 전달 중
  (agent.py:320, 328, 659). 이미 반영돼 있음.
- **실제 원인 가설**: 커맨드 캐시·결정론적 라우터가 LLM 없이 처리 후 즉시 return하여
  해당 명령이 LangGraph 대화 기록(MemorySaver)에 **누적되지 않음**.
  → "메모장 켜줘"(캐시 처리) 다음 "그거 꺼줘"가 실패하는 구조적 원인.
  → M1에서 코드로 재현·확인 후 수정안 보고 예정.

### 강의 개념 → 적용 지점 매핑

| 개념                             | 적용 지점                                                             |
| -------------------------------- | --------------------------------------------------------------------- |
| OWASP LLM 보안(Day5)             | `security.py` 확장 (LLM01 인젝션/02 민감정보/05 출력검증/06 과도권한) |
| HITL(Lab19)                      | 위험 명령에 LangGraph `interrupt` 승인 흐름                           |
| LangGraph State/Node/Edge(Lab14) | 캐시→라우터→LLM 파이프라인 명시적 그래프화 (맥락 버그 근본 해결)      |
| OutputParser/Pydantic(Lab06)     | 문자열 파싱 제거, 도구 인자 구조화                                    |
| RAG/VectorStore(Lab10~12)        | 캐시 SequenceMatcher → 임베딩 유사도 매칭                             |
| MCP/A2A(Lab26)                   | OS 제어 도구를 MCP 서버로 이전 (자체 코드 감소)                       |
| Reflection/Self-RAG(Lab21~24)    | T04 오류 검증 → 정식 reflection 노드                                  |

### 다음 액션 (사용자 결정 대기)

M1 시작점(맥락 수정 / 구조 결정 / 보안 가드레일)과 우선 적용할 강의 개념 선택 후 착수.

---

## 2026-07-30 (세션 시작) — Milestone 0: 현재 상태 확정 (Baseline)

### 목표

방학 재개 시점의 프로젝트 상태를 점검하고 기준점(baseline)으로 확정.
이후 (M1) 계절학기 AI Agent 강의 개념 적용 → (M2) 신규 기능 추가의 토대 마련.

### 완료 스텝

- **Step 1 — 정적 헬스체크** ✅
- **Step 2 — 상태 확정 리포트** ✅
- **Step 3 — DEVLOG.md 생성** ✅ (이 문서)

### 검증 결과 (Linux 샌드박스에서 실행 가능한 범위)

| 항목                                              | 결과                                                        |
| ------------------------------------------------- | ----------------------------------------------------------- |
| 전체 `.py` 문법 컴파일 (py_compile)               | ✅ 전 파일 통과                                             |
| 보안 필터 로직 (`core/security.py`)               | ✅ 9/9 (위험명령·시스템경로·경로순회 차단, 정상명령 통과)   |
| 커맨드 캐시 Intent 매칭 (`core/command_cache.py`) | ✅ 11/11 (켜줘/꺼줘 구분, 미등록 앱 합성, 대화형 미스 포함) |
| 조사 처리 `_select_particle` (을/를)              | ✅ 5/5                                                      |
| `tool_registry` 등록 도구 수 (정적 파싱)          | ✅ **31개** 확인                                            |

> ⚠️ **환경 제약**: 이 프로젝트는 Windows 전용(`ctypes.windll`, 앱 제어, pycaw/wmi 등).
> 개발 세션 샌드박스는 Linux라 **실제 PC 제어 도구 및 라이브 서버 통합 테스트(`test_commands.py`)는
> Windows에서 사용자가 직접 실행**해야 검증 가능. 위 표는 OS 비의존 순수 로직/정적 분석 결과.

### 확정된 현재 상태 (Baseline)

**아키텍처 — LLM 前 3단계 필터 파이프라인** (`core/agent.py`):

1. 보안 필터(`security.py`) — 위험 패턴 29개 코드 레벨 차단
2. 커맨드 캐시(`command_cache.py`) — Intent 2단계 매칭, API 없이 직접 실행
3. 결정론적 라우터(`_route_deterministic`) — 유튜브/지도/폴더/볼륨 등 파라미터 명령 정규식 처리
4. 미스 시 → LangGraph ReAct 에이전트 (재시도·히스토리 복구·오프라인 안내 포함)

**구성요소**:

- 서버: FastAPI (:8765) — `/chat`, `/voice`, `/ws`, `/api/config`, `/history`, `/favorites`
- LLM: 기본 `gemini` / `gemini-2.5-flash` (claude·openai 전환 가능)
- STT: Google STT(온라인) + faster-whisper(오프라인) 하이브리드
- TTS: edge-tts (`ko-KR-SunHiNeural`)
- UI: Electron frameless 오버레이 (idle pill ↔ active view)
- 맥락: LangGraph MemorySaver(thread_id별) + 최근 20개 메시지 trim
- 도구 31개: 앱제어 5 / 웹 6 / 파일 6 / 시스템 10 / 입력 3 / 캘린더 1

**Git**: 브랜치 `feature/byeonsoyun`, `cache/command_cache.json` 미커밋 변경 1건.

### 특이사항 — 문서(CLAUDE.md/HANDOFF.md)와 실제 코드 불일치 (차기 정리 대상)

- 도구 개수: 문서 "26개" → 실제 **31개**
- 미반영 추가 기능: `create_calendar_event`(캘린더), `get_clipboard_text`(클립보드 읽기 — HANDOFF엔 "미구현"), `write_excel`, `crawl_page`
- LLM 모델: 문서 "Gemini 2.0 Flash" → 실제 기본 `gemini-2.5-flash`
- 날짜: 문서상 데모 마감(2026-06-15) 기준 표기가 현재 시점과 불일치

### 알려진 미구현 / 개선 후보 (M1·M2에서 다룰 후보)

1. `stream()`(WebSocket) 경로에 도구 미호출 재시도 로직 미적용
2. 캐시 히트 응답 템플릿 조사 어색함 일부 (동적 합성분은 `_select_particle` 적용됨)
3. 웨이크워드("소윤아") 인식률 낮아 보류 (데모는 Alt+Space)
4. 동적 캐싱 비활성(파라미터 오염 문제로 시드 기반만 사용)

### 다음 (Milestone 1)

계절학기 AI Agent 강의에서 배운 개념/기법을 정리 → 본 프로젝트 적용 가능 항목 분석 → 개선.
착수 전 강의 핵심 개념 목록을 확보하고, 적용안을 보고 후 승인받아 진행.

---
