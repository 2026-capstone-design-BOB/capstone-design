# Pluiz V2 — 마일스톤 정리 문서
> 작성 기준: Phase 1~4 통합 테스트 완료 시점

---

## 1. 지금까지 한 것

### Phase 1 — 프롬프트 보강
- `local_agent.py`의 `SYSTEM_PROMPT` 강화
  - 구어체/모호한 표현 처리 규칙 추가 ("봐봐", "ㅋㅋ", "야" 등 필터)
  - 명령 유형 5가지 정의 및 예시 대폭 확충 (볼륨 수치 처리, 창 제어, 파일명 처리 등)
- `supervisor_agent.py`의 `BRAIN_PROMPT` 강화
  - 경로 백슬래시 처리 규칙 명시 (split/join 방식 강제)
  - 창 제어 ctypes 코드 패턴 구체화 (Z-order 기반 타겟 탐색)
  - 볼륨 수치 처리 규칙 세분화 (상대값/절대값/기본값 구분)
  - selenium 사용 금지 케이스 명시 (단순 앱 실행 시)

### Phase 2 — app_paths DB + PathResolver + setup.py
- `command_cache.py`에 `app_paths` 테이블 추가
  - `save_app_path()`, `get_app_path()`, `get_all_app_paths()` 구현
  - `preset_version` 컬럼 추가 (Preset 버전 관리)
- `path_resolver.py` 신규 구현
  - 탐색 전략 4단계: 레지스트리 → fallback 경로 → where 명령 → 시작메뉴 .lnk
  - `FIXED_PATHS`: 고정 경로 앱 (notepad, calc, mspaint, explorer)
  - `SEARCH_APPS`: 탐색 필요 앱 (chrome, edge, kakao, word, excel, powerpoint)
  - `validate_all()`: 기존 저장 경로 파일 존재 여부 검증
  - `get_prompt_paths()`: BRAIN_PROMPT 주입용 문자열 생성
- `setup.py` 구현
  - DB 테이블 초기화 → 앱 경로 탐색 → Preset 캐시 삽입 순서로 실행

### Phase 3 — server.py 캐시 버그 수정
- 캐시 조회 시 `command` dict 기준으로 key 생성하도록 수정
- 중복 캐시 저장 방지 로직 정리

### Phase 4 — 통합 테스트 완료
- main.py에서 `executor = router.interpreter`로 변경 (InterpreterExecutor 중복 초기화 제거)
- `command_cache.py` `_init_db` 중복 정의 버그 수정
- `supervisor_agent.py` `global BRAIN_PROMPT` → `self.prompt` 인스턴스 변수로 변경
- 전체 플로우 테스트 통과 (STT → 분류 → 실행 → 캐시 저장 → 캐시 히트)

---

## 2. 구조 및 동작 흐름

### 2-1. 실행 전제 조건

```
[최초 1회] python setup.py
    ↓
    DB 테이블 초기화 (command_cache, app_paths)
    앱 설치 경로 탐색 → app_paths 테이블에 저장
    Preset 캐시 삽입 (screenshot 등)
    ↓
[이후 매번] python app/main.py
```

> setup.py를 실행하지 않으면 app_paths 테이블이 비어 있어
> BRAIN_PROMPT에 경로가 주입되지 않고, Gemini가 경로를 추측하게 됨.

---

### 2-2. 전체 동작 흐름 (대표 예: "메모장 열어줘")

```
[사용자 입력]
"메모장 열어줘"
        │
        ▼
[main.py]
  mode 선택 (STT or 텍스트)
        │
        ▼
[LocalAgent.analyze_command()]  ← Ollama(로컬) or Gemini(클라우드)
  SYSTEM_PROMPT + 사용자 입력 → LLM 호출
  응답: {"type": "local", "action": "open_app", "params": {"app": "notepad"}}
        │
        ▼
[main.py] CommandCache.get(command)
  cache_key = "open_app:notepad"
  ┌─────────────────────────────────┐
  │ 캐시 히트?                       │
  │  YES → executor.run_from_cache() │
  │  NO  → router.route() 진행       │
  └─────────────────────────────────┘
        │ (캐시 미스 경로)
        ▼
[CommandRouter.route()]
  type = "local" → _handle_local() → interpreter.execute()
        │
        ▼
[InterpreterExecutor.execute()]
  1. cache.get(command) → 미스 확인 (재확인)
  2. supervisor.generate_code(command, original_input) 호출 (최대 3회)
        │
        ▼
[SupervisorAgent.generate_code()]
  self.prompt (BRAIN_PROMPT + 경로 정보) + 사용자 명령 → Gemini API 호출
  응답에서 ```python ... ``` 블록 추출
  반환: "import subprocess\nsubprocess.Popen(['C:/Windows/System32/notepad.exe'])"
        │
        ▼
[InterpreterExecutor._execute_code()]
  ┌─────────────────────────────────────────┐
  │ AST Guard (check_code)                   │
  │  - ast.parse()로 문법 오류 검사           │
  │  - 금지 패턴 노드 탐색 (import os 등)    │
  │  결과: safe=True → exec() 실행            │
  │        safe=False (문법 오류) → syntax_error (재시도) │
  │        safe=False (보안 위반) → blocked (중단)        │
  └─────────────────────────────────────────┘
        │ (실행 성공)
        ▼
[InterpreterExecutor.execute()]
  cache.save(command, code) → DB 저장
  supervisor.explain_result() → "메모장이 성공적으로 열렸습니다."
        │
        ▼
[main.py]
  결과 출력
```

---

### 2-3. 캐싱 시스템 상세

**캐시 키 생성 규칙 (`_make_key`)**
```
action + params values를 ":" 으로 연결
예) action="open_app", params={"app": "notepad"} → "open_app:notepad"
    action="volume_up", params={} → "volume_up"
    action="create_file", params={"name": "test.txt", "location": "desktop"} → "create_file:test.txt:desktop"
```

**캐시 저장 조건**
- 코드 실행 결과 `status == "success"`인 경우에만 저장
- 보안 차단(`blocked`) 또는 오류(`error`)는 저장하지 않음

**캐시 히트 경로 (main.py vs executor 이중 체크)**
- `main.py`에서 1차 조회 → 히트 시 `executor.run_from_cache()` 직접 호출
- `executor.execute()` 내부에서도 2차 조회 → router를 통해 들어온 경우 대비

**Preset 캐시**
- `setup.py`에서 미리 삽입 (screenshot 등 고정 코드)
- `preset_version` 컬럼으로 버전 관리 → 버전 동일 시 업데이트 스킵

---

### 2-4. 에러 처리 로직

| 상황 | 처리 방식 |
|------|----------|
| Gemini API 키 없음 | `available=False` → fallback 메시지 반환 |
| Gemini 응답 없음 (None) | "AI 서버가 혼잡합니다" 메시지 반환 |
| 코드 문법 오류 | `syntax_error` 상태 → 최대 3회 재시도 후 포기 |
| 3회 모두 문법 오류 | "코드 생성에 실패했습니다" 반환 |
| 보안 차단 | 즉시 중단, 캐시 저장 안 함 |
| LocalAgent JSON 파싱 실패 | `{"type": "unknown", ...}` 반환 |
| LocalAgent API 오류 | retryDelay 파싱 후 대기, 최대 3회 재시도 |
| 알 수 없는 명령 type | `_handle_unknown()` → "명령을 이해하지 못했습니다" |

---

### 2-5. AST 보안 로직

`app/security/ast_guard.py`의 `check_code(code)` 함수

**동작 순서:**
```
1. ast.parse(code) 시도
   → 실패: syntax_error 반환 (재시도 가능)

2. AST 노드 순회 → 금지 패턴 탐지
   금지 항목 예시:
   - 파일 삭제: os.remove, shutil.rmtree
   - 시스템 명령 위험: subprocess + rm/del/format
   - 레지스트리 수정: winreg.SetValue 등
   → 탐지: blocked 반환 (캐시 저장 없이 즉시 중단)

3. 통과 시: safe=True 반환 → exec() 실행
```

---

### 2-6. 경로 주입 흐름

```
setup.py 실행
    → PathResolver.resolve_all()
    → 탐색 결과를 app_paths 테이블에 저장 (verified=1)

main.py → SupervisorAgent.__init__()
    → PathResolver().get_prompt_paths()
    → app_paths 테이블에서 verified=1 경로만 읽어옴
    → BRAIN_PROMPT의 {APP_PATHS_PLACEHOLDER}를 실제 경로 문자열로 치환
    → self.prompt에 저장

generate_code() 호출 시
    → self.prompt 사용 (경로 주입된 상태)
    → Gemini가 실제 설치 경로를 그대로 코드에 사용
```

---

## 3. 남아 있는 문제점 및 해결 계획

### 🔴 미구현 (기능 공백)

| 문제 | 해결 방법 | 시점 |
|------|----------|------|
| 맥락 없는 명령 처리 ("그거 다시 해줘") | `context_memory.py` 구현 | 다음 Phase |
| app_paths 주기적 재탐색 없음 | main.py 시작 시 마지막 업데이트 7일 경과 체크 후 백그라운드 재탐색 | 향후 |
| 실행 성공 코드에서 경로 자동 학습 없음 | `_execute_code()` 성공 후 `.exe` 경로 regex 추출 → app_paths 업데이트 | 향후 |

### 🟡 구조적 개선 필요

| 문제 | 해결 방법 | 시점 |
|------|----------|------|
| 창 제어 시 포그라운드 오인식 | `window_utils.py`에 `get_target_window()` 구현 (psutil로 ignore 프로세스 필터) | 향후 |
| `BaseAgent._call_llm()`에 system role 분리 없음 | Claude/OpenAI 전환 시 system/user role 분리 필요 | 멀티 프로바이더 지원 시 |
| `main.py`에 이중 캐시 조회 (main + executor) | 하나로 통합 또는 명시적 분리 문서화 | 리팩토링 시 |

### 🟢 알려진 경미한 버그

| 문제 | 현황 | 처리 |
|------|------|------|
| `mspaint` 첫 setup 실행 시 "경로 유효하지 않음" 로그 | verified=0 상태에서 재탐색 후 정상 저장됨 | 동작은 정상, 로그만 혼란스러움 — 메시지 개선 가능 |

---

## 4. 어려웠던 점 / Challenging Issues

### Issue 1 — 캐시 키 충돌 설계
**문제:** `action`만으로 키를 만들면 "메모장 열어줘"와 "크롬 열어줘"가 같은 키 `open_app`으로 충돌.

**해결:** params의 values를 순서대로 join → `open_app:notepad` vs `open_app:chrome`으로 분리.

**잔여 위험:** params key 순서가 LLM 응답마다 달라질 수 있음. 현재는 dict insertion order에 의존하고 있어 LLM이 `{"app": "notepad"}` 대신 `{"name": "notepad"}`처럼 다른 key를 쓰면 키가 달라짐. 장기적으로는 key까지 포함한 정규화 필요.

---

### Issue 2 — `_init_db` 중복 정의 버그
**문제:** `command_cache.py`에 `_init_db`가 두 번 정의되어 있었고, Python은 나중 것으로 덮어씀. 첫 번째 정의(app_paths 테이블 없는 버전)가 살아남아 `app_paths` 테이블이 생성되지 않는 버그.

**해결:** 두 정의를 하나로 병합. app_paths 포함 버전으로 통일.

---

### Issue 3 — `global BRAIN_PROMPT` 불안정성
**문제:** `SupervisorAgent.__init__()`에서 `global BRAIN_PROMPT`로 모듈 변수를 직접 수정하면, 모듈 재로드 시 원본으로 초기화되거나 멀티스레딩 환경에서 경쟁 조건 발생 가능.

**해결:** `self.prompt = BRAIN_PROMPT`로 인스턴스 변수에 복사 후 치환. 모듈 상수는 불변으로 유지.

---

### Issue 4 — 코드 생성 문법 오류 처리
**문제:** Gemini가 가끔 문법 오류가 있는 코드를 생성함. 첫 버전은 오류 시 바로 실패 반환.

**해결:** AST Guard에서 `syntax_error`와 `blocked`를 구분. `syntax_error`는 재시도 가능, `blocked`는 즉시 중단. 최대 3회 재시도 루프 추가.

---

### Issue 5 — 경로 탐색 신뢰성
**문제:** Windows 환경마다 앱 설치 경로가 다름. Gemini가 경로를 추측해서 틀리는 경우 발생.

**해결:** setup.py에서 레지스트리 → fallback → where → 시작메뉴 4단계 탐색 후 DB 저장. SupervisorAgent 초기화 시 실제 경로를 프롬프트에 주입. 테스트 결과 Gemini가 주입된 경로를 그대로 사용하는 것 확인.

---

## 5. 앞으로 할 것

### 다음 단계: context_memory.py

**목표:** 이전 명령 맥락을 기억해서 "그거 다시 해줘", "방금 열었던 거 닫아줘" 같은 참조형 명령 처리.

**구현 방향 (2단계):**

**Step A — 단순 히스토리**
```
app/memory/context_memory.py
  - 최근 N개 (기본 10개) 명령 히스토리 저장
  - SQLite 테이블 or 메모리 내 deque
  - LocalAgent.analyze_command()에 히스토리 컨텍스트 주입
  - "그거", "방금", "다시" 등 참조 표현 감지 → 직전 command 반환
```

**Step B — 요약 압축**
```
  - 히스토리가 N개 초과 시 오래된 것을 LLM으로 요약
  - 요약본을 context로 유지 → 토큰 절약
  - 구현 위치: ContextMemory.compress()
```

### 그 이후

| 순서 | 항목 |
|------|------|
| 1 | context_memory.py Step A 구현 |
| 2 | context_memory.py Step B (압축) 구현 |
| 3 | window_utils.py (get_target_window) 구현 |
| 4 | 실행 코드에서 경로 자동 학습 |
| 5 | app_paths 주기적 재탐색 스케줄러 |
| 6 | Electron UI 연동 (frontend-ui) |
| 7 | 멀티 프로바이더 지원 (Claude/OpenAI fallback) |

---

*마지막 업데이트: Phase 4 통합 테스트 완료 후*
