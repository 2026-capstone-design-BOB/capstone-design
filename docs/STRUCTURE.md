# 디렉토리 구조와 배치 기준

> 📍 [문서 허브](README.md) · 관련: [ARCHITECTURE.md](ARCHITECTURE.md) · [WORKFLOW.md](WORKFLOW.md)

이 문서는 **무엇을 어디에 두는가**와 **왜 그렇게 두는가**를 정한다.
새 파일을 만들 때는 [배치 결정 트리](#새-파일-배치-결정-트리)를 따른다.

---

## 왜 이 문서가 있는가

이 규칙이 없던 동안 새 파일은 전부 루트로 갔다. 그 결과 2026-09-01 이전까지 루트에
**파일 49개**가 평평하게 쌓여 있었다 — `main.py` 바로 옆에 발표용 다이어그램 PNG,
교수 Q&A 대비 문서, 수동 테스트 케이스가 나란히 놓인 상태였다.

원인은 게으름이 아니라 **기준의 부재**였다. 그래서 기준을 문서로 고정한다.

---

## 최상위 분류 — 4가지

모든 파일은 넷 중 하나에 속한다. **생명주기가 다르면 디렉토리를 나눈다**는 게 유일한 원칙이다.

| 분류 | 의미 | 위치 | 생명주기 |
|---|---|---|---|
| **실행 코드** | 서버를 돌리는 데 필요한 것 | 루트 + `core/` `tools/` `services/` `config/` `memory/` `electron-ui/` | 코드와 함께 계속 변함 |
| **문서** | 개발자·Claude Code가 읽는 것 | `docs/` | 코드 변경에 맞춰 갱신 |
| **산출물** | 특정 시점 제출·발표용 | `docs/presentation/` | 그 시점 이후 **동결** |
| **아카이브** | 대체됐지만 참고용 보존 | `archive/` | 변경하지 않음 |

발표자료가 `docs/presentation/`으로 따로 빠진 이유가 이것이다. 6월 데모 시점에
동결된 자료라, 매일 갱신되는 개발 문서와 섞이면 어느 쪽이 최신인지 알 수 없게 된다.

---

## 전체 구조

```
C:\pluiz_v2\
│
├── README.md               # GitHub 첫 화면 (외부 방문자용 소개)
├── CLAUDE.md               # Claude Code 진입점 → docs/로 라우팅
│
├── main.py                 # FastAPI 서버 진입점
├── clear_cache.py          # 캐시 초기화 유틸
├── requirements.txt
├── .env / .env.example     # API 키 (.env는 gitignore)
├── setup.bat               # 환경 구축 (conda + pip)
├── launch.bat              # 서버 + Electron 동시 실행 ← 실제 사용
├── start.bat               # 서버만 실행
│
├── .github/workflows/      # CI — mock 테스트 · 문서 링크 · 비밀정보 가드
├── tests/                  # 자동 테스트 18개 (mock 15 + 서버 필요 3)
│
├── config/                 # pydantic-settings
├── core/                   # 에이전트 엔진 · 보안 · 캐시
├── tools/                  # LLM이 호출하는 도구 (앱/시스템/파일/웹/입력/캘린더)
├── services/               # STT · TTS · 웨이크워드
├── memory/                 # SQLite 세션 기록
├── cache/                  # 커맨드 캐시 · 즐겨찾기 (런타임 생성)
├── electron-ui/            # Electron 오버레이 UI
│
├── docs/                   # ← 문서 전부
│   ├── README.md           # 문서 허브
│   ├── STRUCTURE.md        # 이 문서
│   ├── ARCHITECTURE.md
│   ├── WORKFLOW.md
│   ├── CONTRIBUTING.md
│   ├── DEVLOG.md
│   ├── BACKLOG.md
│   ├── design/             # ADR (설계 결정 기록)
│   ├── testing/            # 수동 테스트 케이스
│   └── presentation/       # 발표 자료 (동결)
│
└── archive/                # 대체된 산출물 (import 되지 않음)
    ├── core_agent_v1.py    #   구 엔진 PluizAgent — M1-P5에서 대체
    ├── HANDOFF.md          #   2026.06 인수인계 스냅샷
    └── ui.html             #   Electron 이전 브라우저 UI
```

---

## 디렉토리별 규칙

### `core/` — 에이전트 엔진

**넣는 것**: 에이전트 실행 흐름, 라우팅, 보안 판단, 캐시. OS에 직접 손대지 않는 로직.
**넣지 않는 것**: Windows API를 직접 호출하는 코드 → `tools/`로.

`core/`의 모듈은 **의존성 주입 가능하게** 작성한다. `graph.py`가 llm·tools·security_check를
인자로 받는 이유는, Windows나 LLM API 없이 mock으로 단위 테스트하기 위해서다.
이 원칙 덕분에 mock 스위트 158개가 어떤 환경에서든 돈다.

### `tools/` — LLM이 호출하는 도구

**넣는 것**: `@tool` 데코레이터가 붙은 함수. Windows 제어의 실제 구현.
**규칙**: 새 도구는 반드시 [`core/tool_registry.py`](../core/tool_registry.py)의
`get_all_tools()`에 등록해야 LLM이 볼 수 있다. 위험한 도구라면
`core/graph.py`의 `DANGEROUS_TOOLS`에도 추가해 HITL 승인을 태운다.

### `docs/design/` — ADR (Architecture Decision Record)

**넣는 것**: "왜 이렇게 만들었는가"를 남겨야 하는 구조적 결정.
**넣지 않는 것**: 작업 기록(→ `DEVLOG.md`), 할 일(→ `BACKLOG.md`).

판단 기준: **나중에 "왜 이렇게 했지?"라는 질문이 나올 결정이면 ADR을 쓴다.**
예를 들어 [M1_아키텍처_설계.md](design/M1_아키텍처_설계.md)는 맥락 붕괴 버그의 원인이
"설정 누락"이 아니라 "구조적 결함"이었다는 진단 과정을 담고 있다. 이게 없으면
나중에 누군가 fast_path를 다시 조기 return하도록 "최적화"할 수 있다.

### `archive/` — 대체된 산출물

**넣는 것**: 더 이상 안 쓰지만 히스토리로 남길 가치가 있는 것.
**삭제하지 않는 이유**: git 이력에도 남지만, 저장소를 훑는 사람에게는 보이지 않는다.
V1 → V2로 어떻게 발전했는지를 보여주는 게 이 프로젝트의 서사 중 하나라 눈에 보이게 둔다.

**규칙**: 여기 있는 파일은 **어디서도 import 하지 않는다.** 참고용 읽기 전용이다.
무엇이 왜 대체됐는지는 해당 ADR에 적는다 (예: [design/M1_P5_엔진단일화.md](design/M1_P5_엔진단일화.md)).

---

## 구조적 제약 — 옮기면 깨지는 것들

**아래는 취향이 아니라 코드가 강제하는 제약이다. 리팩터링할 때 반드시 확인할 것.**

| 제약 | 이유 | 근거 |
|---|---|---|
| `services/`·`electron-ui/`는 **루트 직속** | Electron이 `../services/wakeword.py`를 직접 찾는다. `src/` 같은 상위 폴더로 감싸면 웨이크워드가 죽는다 | [`electron-ui/main.js:52`](../electron-ui/main.js) |
| `.env`는 **루트** | `env_file=".env"`가 **CWD 기준**으로 읽힌다 | [`config/settings.py`](../config/settings.py) |
| `tests/`의 테스트는 **루트를 `dirname(dirname(abspath(__file__)))`로 계산** | 각 테스트가 `sys.path`와 `core/` 경로를 직접 만든다. 파일을 더 깊은 하위 폴더로 옮기면 `dirname`을 하나 더 씌워야 한다 | 모든 `tests/test_*.py` 상단 |
| 테스트가 소스를 `open()`할 땐 **`encoding="utf-8"` 필수** | 한글이 든 소스를 Windows 기본 cp949로 읽으면 `UnicodeDecodeError`. 실제로 `test_injection`·`test_sensitive`가 이 때문에 로컬에서 죽어 있었다 | `tests/test_sensitive.py` |
| `clear_cache.py`는 **루트** | 같은 이유 — `dirname(__file__)/cache/`를 참조 | [`clear_cache.py`](../clear_cache.py) |
| `docs/presentation/`은 **평평하게** | `pluiz_presentation.html`이 `src="pluiz_paradigm.svg"`로 상대참조한다. 다이어그램을 하위 폴더로 나누면 슬라이드가 깨진다 | `docs/presentation/pluiz_presentation.html` |
| `CLAUDE.md`는 **루트** | Claude Code가 루트에서 자동 로드한다 | 도구 규약 |
| `cache/`는 **루트 기준 계산** | `_BASE_DIR`이 `core/`의 부모로 계산된다. `core/`를 옮기면 캐시 경로가 어긋난다 | [`core/command_cache.py`](../core/command_cache.py) |

---

## 새 파일 배치 결정 트리

```
새 파일을 만든다
│
├─ 서버 실행에 필요한가?
│   ├─ Windows/OS를 직접 제어하는가? ─────────→ tools/
│   ├─ 에이전트 흐름·보안·캐시 로직인가? ─────→ core/
│   ├─ STT/TTS/웨이크워드인가? ──────────────→ services/
│   ├─ 설정 스키마인가? ─────────────────────→ config/
│   └─ 테스트 스크립트인가? ─────────────────→ tests/  (위 제약 참조)
│
├─ 문서인가?
│   ├─ "왜 이렇게 만들었나" 설계 결정 ────────→ docs/design/  (ADR)
│   ├─ "무엇을 했나" 작업 기록 ──────────────→ docs/DEVLOG.md 에 항목 추가
│   ├─ "무엇을 해야 하나" ──────────────────→ docs/BACKLOG.md 에 항목 추가
│   ├─ 수동 테스트 절차 ────────────────────→ docs/testing/
│   └─ 그 외 상시 참조 문서 ────────────────→ docs/ 루트
│                                              (+ docs/README.md 인덱스에 추가!)
│
├─ 발표·제출용 산출물인가? ───────────────────→ docs/presentation/
│
├─ 대체돼서 안 쓰지만 남길 것인가? ────────────→ archive/
│
└─ 위 어디에도 안 맞는가?
    → 루트에 두기 전에 멈추고, 이 문서에 분류를 먼저 추가할 것.
       "일단 루트에" 가 지금 상태를 만들었다.
```

---

## 문서를 추가했다면

새 문서를 만들면 **반드시** [`docs/README.md`](README.md)의 문서 목록과 작업별 라우팅 표에 추가한다.
허브에 없는 문서는 없는 것과 같다 — Claude Code든 사람이든 허브부터 읽기 때문이다.
