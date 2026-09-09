# 개발 워크플로

> 📍 [문서 허브](README.md) · 관련: [STRUCTURE.md](STRUCTURE.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [CONTRIBUTING.md](CONTRIBUTING.md)

이 문서는 **어떻게 작업하는가**를 단독으로 책임진다.

---

## 환경

### ⚠️ 인터프리터

**루트 `python`(anaconda base)에는 langgraph가 없다.** 반드시 `pluiz` 환경을 쓴다.

```bash
# conda
conda activate pluiz

# 또는 직접 지정
C:/Users/byeonsoyun/anaconda3/envs/pluiz/python.exe main.py
```

### ⚠️ 콘솔 인코딩

Windows 콘솔이 cp949라 테스트 출력의 `✓`/`✗`에서 `UnicodeEncodeError`가 난다.

```bash
export PYTHONIOENCODING=utf-8      # Git Bash
$env:PYTHONIOENCODING = "utf-8"    # PowerShell
```

### 실행

```bash
setup.bat      # 최초 1회 — conda 환경 + 패키지 + .env 생성
launch.bat     # 서버 + Electron UI (실제 사용)
start.bat      # 서버만
```

---

## 작업 루프

새 작업은 항상 이 순서를 따른다.

```
1. docs/BACKLOG.md 확인          — 이미 알려진 항목인가?
2. docs/DEVLOG.md 최상단 확인     — 직전에 무슨 작업을 했나?
3. 작업
4. 테스트 (아래 § 테스트)
5. docs/DEVLOG.md 에 항목 추가    ← 빠뜨리지 말 것
6. 커밋 (아래 § 커밋 컨벤션)
```

**5번이 이 프로젝트의 핵심 규율이다.** DEVLOG가 단일 진실 공급원이라, 기록되지 않은
작업은 다음 세션에서 존재하지 않는 것과 같다. 실제로 `CLAUDE.md`가 코드와 어긋난 채
방치된 적이 있는데, 문서 갱신이 작업 루프에 들어 있지 않았던 게 원인이다.

---

## 테스트

### mock 스위트 (Windows·API 불필요)

`core/`의 모듈이 전부 의존성 주입 가능하게 작성돼 있어, 실제 LLM이나 Windows 없이 돈다.

```bash
export PYTHONIOENCODING=utf-8
PY="C:/Users/byeonsoyun/anaconda3/envs/pluiz/python.exe"

"$PY" tests/test_graph_agent.py       # 그래프 오케스트레이터 + 계측 17/17
"$PY" tests/test_hitl_agent.py        # HITL 승인            8/8
"$PY" tests/test_cache_learn.py       # 캐시 동적 학습        15/15
"$PY" tests/test_guardrail_hybrid.py  # 하이브리드 가드       8/8
"$PY" tests/test_visual_verify.py     # 실행 결과 시각적 검증  46/46
"$PY" tests/test_type_text_focus.py   # BL-12 사전 포커스 확인 21/21
"$PY" tests/test_bl15_truncation.py   # BL-15 캐시 명령 절단   43/43
"$PY" tests/test_voice_thread.py      # 음성·텍스트 대화 공유  11/11
"$PY" tests/test_ui_locate.py         # UI 요소 좌표 인식      41/41
"$PY" tests/test_click_ui.py          # 좌표 클릭(승인 필수)   28/28
"$PY" tests/test_screen_monitor.py    # 화면 변화 모니터링    139/139
"$PY" tests/test_plan_node.py         # 계획 수립 노드(M3)     37/37
"$PY" tests/test_vision.py            # Vision 계약 + 응답 로그 옵트인 17/17
"$PY" tests/test_running_apps.py      # 실행 중인 앱 목록      12/12
"$PY" tests/test_wakeword_ui.py       # 웨이크워드 설정 UI 배선 25/25
"$PY" tests/test_wakeword_kws.py      # 전용 KWS 백엔드 계약   25/25
"$PY" tests/test_trim.py              # 히스토리 trim
"$PY" tests/test_injection.py         # 프롬프트 인젝션
"$PY" tests/test_sensitive.py         # 민감정보 보호
"$PY" tests/test_bl02_bl03.py        # 위험명령 공백변형 · 캐시 부정어
"$PY" tests/test_dependencies.py     # ★ requirements.txt 선언 = 실제 설치인지
```

전체 mock 스위트는 **32파일 876개**([README 상태표](README.md)가 출처). 이 중 `test_dependencies.py`(34개)는 로컬 전용이라
CI는 31파일 842개를 돌린다. **코드를 바꿨으면 관련 스위트 + 회귀로 최소 3종은 돌린다.**

### 테스트는 제품 로그를 건드리지 않는다

각 테스트 파일 맨 위의 `import _testenv` 한 줄이 `PLUIZ_LOG_DIR`을 임시 경로로 돌린다.
안 그러면 테스트가 남긴 줄이 `logs/pluiz.log`의 **실기 기록 사이에 섞여** 진단을
방해한다(2026-09-03에 실제로 겪었다). 로거를 쓰는 테스트를 새로 만들면 그 한 줄을
넣을 것. → [`tests/_testenv.py`](../tests/_testenv.py)

테스트 로그를 직접 보고 싶으면 `PLUIZ_LOG_DIR=./logs`로 덮어쓸 수 있다.

### ⚠️ 의존성이 없으면 도구가 조용히 죽는다

도구들은 패키지가 없어도 예외를 삼키고 폴백한다. 그래서 **기능이 안 되는데
테스트는 통과**할 수 있다. 2026-09-01 실기에서 requirements.txt 의 8개 패키지가
미설치인 채로 전부 통과했다.

가장 위험한 건 `send2trash` 다. 없으면 `_to_trash()` 가 `os.remove` 로 폴백해
**휴지통을 거치지 않고 영구 삭제**한다.

### 의존성 버전 — 파일 두 개의 역할이 다르다

| 파일 | 역할 |
|---|---|
| `requirements.txt` | **하한**과 *«왜 이 패키지가 필요한가»*. 사람이 읽는 문서 |
| `requirements.lock.txt` | **정확한 버전.** 이 조합에서 mock이 통과했다. 기계가 읽는 재현 |

```bash
pip install -r requirements.lock.txt      # 재현 가능한 설치
pip freeze > requirements.lock.txt        # 갱신 (pluiz 환경에서 · 갱신 후 테스트!)
```

> **왜 잠금이 필요했나** — 하한만 있으면 설치할 때마다 최신이 들어와
> **코드를 하나도 안 고쳐도 어느 날 깨진다.** 실제로 `requirements.txt`는
> `langgraph>=0.2.0`이라고 적고 있었는데 도는 것은 **1.x**였다. 메이저가 두 번
> 올라가는 동안 아무도 몰랐고, CI는 매 실행마다 최신을 새로 설치하고 있었다.
>
> `tests/test_dependencies.py`가 **직접 의존성이 lock과 어긋나면 FAIL**한다.
> 전이 의존성은 목록만 보여주고 통과시킨다 — 매번 빨간불이 뜨면 사람이 테스트를
> 안 믿게 되고, 그게 더 나쁘다.
>
> ⚠️ **버전 숫자를 다른 곳에 또 적지 말 것.** CI(`tests.yml`)도 lock에서 `grep`으로
> 뽑아 쓴다. 두 곳에 적으면 한쪽만 갱신돼 어긋난다.

```bash
python tests/test_dependencies.py     # 선언 ↔ 실제 대조. 환경 세팅 후 꼭 한 번
```

이 테스트는 **CI에서 제외**된다. CI는 속도를 위해 langgraph·langchain-core 만
설치하므로 항상 실패하기 때문이다. 로컬 환경 점검용이다.

라이브 테스트는 의존성이 없으면 PASS 가 아니라 **SKIP(사유 명시)** 으로 처리한다.

### CI (GitHub Actions)

`main` · `develop` · `feature/**` 에 push하면 [`.github/workflows/tests.yml`](../.github/workflows/tests.yml)이 자동 실행된다.

| 잡 | 하는 일 |
|---|---|
| `mock-suite` | 문법 검사 + mock 테스트 **30파일** (Ubuntu). 서버 필요한 3개와 로컬 전용 `test_dependencies`는 제외. 개수 출처는 [README 상태표](README.md) |
| `link-check` | 모든 `.md`의 상대링크·이미지 참조가 실제 존재하는지 |
| `secret-guard` | `.env` 추적 여부 · 실제 API 키 패턴 · 커밋된 `.pyc` |

mock 테스트는 `langgraph`·`langchain-core`만 설치해서 돈다. `requirements.txt` 전체
(playwright·faster-whisper·pyautogui)는 헤드리스에서 깨지고 불필요하다.
**두 패키지의 버전은 `requirements.lock.txt`에서 `grep`으로 가져온다** — 워크플로에
숫자를 직접 적으면 lock과 두 곳이 되어 한쪽만 갱신된다.

> **테스트용 더미 키에는 `FAKE`/`DUMMY`/`EXAMPLE`을 넣을 것.**
> `secret-guard`가 실제 키 형식을 잡되 이 단어가 든 건 통과시킨다.

### 컴파일 확인

```bash
"$PY" -m py_compile main.py core/*.py tools/*.py services/*.py config/*.py tests/*.py
```

### 라이브 테스트 (서버 실행 필요)

```bash
"$PY" tests/test_commands.py     # 기능 동작 (앱 실행·파일·보안·도구 등록)
"$PY" tests/test_regression.py   # 회귀 + 신 엔진 기능 (HITL·가드레일·마스킹·캐시학습)
"$PY" tests/test_sprint1_2.py    # Sprint1&2 (--static 으로 서버 없이도 가능)

`test_regression.py`의 **G-02(하이브리드 가드레일)는 온라인 전용**이다.
오프라인이면 LLM 판정기가 skip 돼 통과할 수 있다.
`G-01`·`G-04`는 실제로 파일을 만들고 앱을 띄운다(끝나면 정리한다).
```

> 🔒 **인증(BL-14) 때문에 서버를 먼저 띄워야 한다.**
> 서버가 기동하면서 `cache/.auth_token`에 토큰을 적고, 세 스위트가 그 파일을 읽어
> 자동으로 헤더에 싣는다. 손으로 할 일은 없지만 아래 두 가지는 알고 있어야 한다.
> - **서버를 재시작하면 토큰이 바뀐다** → 테스트도 그때 다시 실행한다
> - 서버가 안 떠 있으면 토큰이 없어 **전부 401**이 난다 (연결 실패와 구분이 안 되니
>   먼저 `curl http://127.0.0.1:8765/health`로 확인할 것 — `/health`만 인증 면제다)
>
> 캐시 대시보드도 토큰이 필요하다. **서버 기동 로그에 `?token=`이 붙은 전체 URL이
> 찍히므로 그걸 그대로 열면 된다.**

> 💾 **캐시를 더럽히고 싶지 않으면 서버에 경로를 준다** (BL-11, 2026-09-05)
> ```bash
> PLUIZ_CACHE_FILE=/tmp/pluiz_live.json "$PY" main.py
> ```
> 라이브 테스트는 실제로 명령을 실행하므로 캐시가 **학습**한다. 그러면 git 추적 파일인
> `cache/command_cache.json`이 modified가 되고, 매번 `git checkout` 해야 한다.
> 위처럼 띄우면 그 일이 없다. **안 줘도 예전과 똑같이 동작한다**(그때는 되돌리면 된다).
> mock 테스트는 `import _testenv`가 알아서 막으므로 **손댈 것이 없다.**

### ⚠️ 테스트가 초록인데 사용자가 막히는 경우

2026-09-02에 **같은 실수를 두 번** 했다. mock도 라이브도 전부 통과인데
사용자가 음성으로 써 보니 바로 막혔다. 원인이 두 번 다 같았다.

> **테스트가 "설계대로 도는지"만 확인하고, 그 설계가 "사람이 실제로 말하는 방식"과
> 맞는지는 확인하지 않았다.**

| 실제로 겪은 것 | 테스트에 없던 것 |
|---|---|
| *"네이버 열어줘"* 가 재질문으로 처리돼 같은 말을 두 번 함 | 그 동작을 **PASS로 기대**하고 있었다 |
| *"응 지워 줘"* 가 승인으로 안 읽혀 네 번 말함 | **띄어쓰기 변형**(`"지워 줘"`)이 한 건도 없었다 |
| *"바탕화면에 뭐 있어?"* 를 답할 도구가 없음 | 도구 **부재**는 어떤 테스트도 잡지 못한다 |

**그래서 지키는 것:**

1. **사용자 대면 판정 로직**(승인/거부, 인텐트 분류)에는 **띄어쓰기·어미·군말 변형**을
   테스트에 넣는다. `"응"` 하나로는 부족하다 — `"응 지워 줘"`·`"그래 정말 삭제해 줘"`도 넣는다.
2. **대조군을 함께 넣는다.** *"파일이 안 지워졌다"* 는 **안전해진 것**과
   **아무것도 승인 못 하는 고장** 둘 다에서 나온다. 둘을 가르는 케이스가 있어야 한다.
3. 기대값을 쓸 때 *"지금 코드가 이렇게 도니까"* 가 아니라
   **"사용자가 이걸 보면 만족할까"** 로 판단한다.
4. mock은 **턴 단위**로 행동해야 한다. "히스토리에 ToolMessage가 있으면 …" 식의
   mock은 한 thread에서 두 번째 요청부터 다르게 굴어 시나리오를 못 만든다.
   (`test_hitl_graph.FakeLLM` · `test_cache_wire.ScriptedLLM` 참조)

### 수동 테스트

자동화 불가능한 UI·음성·시각 항목은 [testing/](testing/) 참조.

---

## 새 도구 추가

```python
# 1. tools/ 에 함수 작성
from langchain_core.tools import tool

@tool
def my_tool(param: str) -> str:
    """도구 설명 — LLM이 이 설명을 보고 언제 쓸지 판단한다. 구체적으로 쓸 것."""
    return "✓ 완료"
```

```
2. core/tool_registry.py 의 get_all_tools()에 import + 리스트 추가
3. 위험한 도구라면 core/graph.py 의 DANGEROUS_TOOLS 에도 추가 → HITL 승인 적용
4. 파라미터 없는 고정어휘 제어 도구라면
   core/command_cache.py 의 LEARNABLE_TOOLS 추가 검토 (캐시 학습 대상)
5. docs/ARCHITECTURE.md 의 도구 표 갱신
```

---

## 설계 결정 (ADR)

**"나중에 왜 이렇게 했지?"라는 질문이 나올 결정이면 [design/](design/)에 ADR을 먼저 쓴다.**

구현부터 하고 나중에 문서화하지 않는다. 대안을 비교하는 과정 자체가 설계의 일부이고,
그 비교가 남아 있어야 나중에 누군가 되돌리려 할 때 근거를 볼 수 있다.

ADR 형식: 배경·문제 정의 → 현행 평가 → 목표 구조 → 대안 비교 → 결정 → 단계별 계획.
예: [M1_아키텍처_설계.md](design/M1_아키텍처_설계.md)

---

## DEVLOG 작성 규칙

- **시간 역순** — 최신 항목이 맨 위
- 항목 형식: `## YYYY-MM-DD HH:MM KST — 제목` + `### 목표 / 완료 / 검증 / 다음`
- **검증 결과에 숫자를 적는다** (`cache_learn 15/15`). "통과함"만 적으면 나중에 회귀를 못 잡는다
- **한계를 정직하게 적는다.** P3 항목의 "무한 패러프레이즈 100% 차단 불가"처럼,
  안 되는 걸 안 된다고 적어야 다음 사람이 헛수고를 안 한다
- **과거 항목은 수정하지 않는다.** 날짜가 박힌 기록이라 사후 수정하면 로그의 의미가
  훼손된다. 경로가 바뀌어 옛 항목의 참조가 깨졌다면, **새 항목에 매핑표를 넣어** 해결한다

## BACKLOG 작성 규칙

두 태그 중 하나로 분류한다.

- **[즉시/위험]** — 구조적 결함·상태 오염 등 방치하면 이후 개발의 토대를 흔드는 것. **발견 즉시 수정**
- **[TODO/품질]** — 이미 동작하는 기능의 정확도·말투 튜닝. **개발 목표를 마친 뒤 일괄 정리**

각 항목에 증상 / 원인 / 성격 / 해결 후보 / 발견 시점을 적는다.

---

## 커밋 컨벤션

**[Conventional Commits](https://www.conventionalcommits.org/)** 를 따른다.
(2026-09-01 이전 이력의 `[Code]...` 형식은 과거 것으로 두고, 이후부터 적용)

```
<type>(<scope>): <제목>

<본문 — 무엇을 왜 바꿨는지. 어떻게는 코드가 말한다>

검증: <테스트 결과 숫자>
```

| type | 용도 |
|---|---|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `refactor` | 동작 변화 없는 구조 개선 |
| `docs` | 문서만 변경 |
| `test` | 테스트 추가·수정 |
| `chore` | 빌드·설정·의존성 |

scope 예: `cache` `graph` `security` `tools` `ui`

**한 커밋에 한 가지 의미만 담는다.** 기능 개발과 문서 정리를 같이 커밋하면
나중에 "언제 무엇이 바뀌었는지" 추적이 불가능해진다.

---

## 브랜치 흐름

```
feature/byeonsoyun  →  develop  →  main
   개인 작업            팀 통합      완성본 (README + 안정본)
```

상세 규칙과 충돌 해결법은 [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Claude Code로 작업할 때

이 저장소는 **"[docs](README.md) 보고 진행해줘"** 한 마디로 작업이 시작되도록 구성돼 있다.

1. [`../CLAUDE.md`](../CLAUDE.md) → [문서 허브](README.md)로 안내
2. 허브의 **작업별 라우팅 표**에서 필요한 문서를 찾음
3. [BACKLOG.md](BACKLOG.md)에서 할 일, [DEVLOG.md](DEVLOG.md) 최상단에서 직전 맥락 파악

**작업이 끝나면 DEVLOG 항목 추가와 관련 문서 갱신까지가 한 세트다.**
문서를 안 고치면 다음 세션이 낡은 정보로 시작한다.

---

## 🔚 "마무리해줘" — 세션을 닫는 절차

사용자가 **"마무리해줘" · "세션 닫자" · "이따 이어서 할게"** 라고 하면, 아래를
**전부** 수행한다. 매번 무엇을 해야 하는지 지시받지 않아도 되도록 여기 고정한다.

**목표는 하나다 — 다음 세션이 "docs 보고 진행해줘" 한 마디로 이어갈 수 있어야 한다.**

### 1. 코드·작업물 정리
- [ ] 작업 트리를 깨끗하게 만든다 (`git status`가 비어야 한다)
- [ ] **라이브 테스트 부산물을 되돌린다** — `git checkout cache/command_cache.json`
      (서버를 `PLUIZ_CACHE_FILE=...`로 띄웠다면 애초에 안 더러워진다 — BL-11, 2026-09-05)
- [ ] 테스트로 띄운 **서버·앱을 종료**한다. 임시 파일(확인용 canary 등)을 지운다
- [ ] 임시 진단 스크립트는 **커밋하지 않는다** (scratchpad에 둔다)

### 2. 검증 숫자를 실제로 낸다
- [ ] mock 스위트를 **돌려서** 숫자를 확인한다. 기억이나 추정으로 적지 않는다
- [ ] 실패가 있으면 **숨기지 말고** 그 사실과 이유를 기록한다

### 3. 문서 — 기록되지 않은 작업은 존재하지 않는다
- [ ] **[DEVLOG.md](DEVLOG.md) 최상단**에 항목 추가.
      맨 앞에 `> 📌 다음 세션은 …부터` 한 줄을 넣어 진입점을 명시한다
- [ ] **[TASKS.md](TASKS.md)** — 끝난 항목 `[x]`, 「🔵 지금 하는 중」을 **다음 세션 기준**으로 갱신
- [ ] **[BACKLOG.md](BACKLOG.md)** — 새로 발견한 결함을 BL 번호로 신설, 해결된 건 이동
- [ ] **[README.md](README.md) 상태표** — 테스트 개수·실측 결과. **숫자의 유일 출처다**
- [ ] 새 문서를 만들었으면 [README.md](README.md) 인덱스에 추가

### 4. 커밋 — 성격별로 나눈다
`fix:` / `feat:` / `test:` / `docs:` 를 **한 덩어리로 뭉치지 않는다.**
나중에 되돌릴 때 문서까지 딸려 사라진다. → [커밋 컨벤션](#커밋-컨벤션)

### 5. 푸시하지 않는다 ⏸️
**푸시 시점은 사용자 결정 사항이다.** 저장소가 public이라 올릴 시점을 사용자가 정한다.
마무리에 자동으로 푸시하지 말 것. (→ [TASKS.md](TASKS.md) 「⏸️ 사용자 결정 대기」)

### 6. 마지막 보고 — 세 가지만
1. **한 일** (숫자와 함께)
2. **사용자가 해야 할 것** — 특히 **사람 눈으로만 확인 가능한 것**. 명령어까지 적는다
3. **남은 것 / 못 고친 것** — ⚠️ **된 척하지 않는다.**
   "코드가 들어갔다"와 "동작한다"는 다르다. 실기 미검증이면 그렇게 적는다

### 문서를 새로 만들었다면

[`docs/README.md`](README.md)의 문서 목록과 작업별 라우팅 표에 **반드시** 추가한다.
허브에 없는 문서는 없는 것과 같다.
