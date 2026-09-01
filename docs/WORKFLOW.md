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

"$PY" test_graph_agent.py       # 그래프 오케스트레이터  6/6
"$PY" test_hitl_agent.py        # HITL 승인            8/8
"$PY" test_cache_learn.py       # 캐시 동적 학습        15/15
"$PY" test_guardrail_hybrid.py  # 하이브리드 가드       8/8
"$PY" test_trim.py              # 히스토리 trim
"$PY" test_injection.py         # 프롬프트 인젝션
"$PY" test_sensitive.py         # 민감정보 보호
```

전체 mock 스위트는 15파일 158개. **코드를 바꿨으면 관련 스위트 + 회귀로 최소 3종은 돌린다.**

### 컴파일 확인

```bash
"$PY" -m py_compile main.py core/*.py tools/*.py services/*.py config/*.py
```

### 라이브 테스트 (서버 실행 필요)

```bash
"$PY" test_commands.py     # ⚠️ 구 엔진 기준 (BACKLOG BL-06)
"$PY" test_regression.py   # ⚠️ 동일
```

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

### 문서를 새로 만들었다면

[`docs/README.md`](README.md)의 문서 목록과 작업별 라우팅 표에 **반드시** 추가한다.
허브에 없는 문서는 없는 것과 같다.
