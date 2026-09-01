# Pluiz v2 — 문서 허브

> 이 프로젝트의 모든 문서 진입점입니다. **작업을 시작하기 전 이 문서부터 읽으세요.**
> 처음이라면 [STRUCTURE.md](STRUCTURE.md) → [ARCHITECTURE.md](ARCHITECTURE.md) → [WORKFLOW.md](WORKFLOW.md) 순서를 권합니다.

---

## 지금 상태 (2026-09-01)

**Pluiz** — 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트. 졸업 캡스톤.

- 2026.06.15 데모 완료. 이후 강의 개념(LangGraph·HITL·OWASP·RAG)을 구조에 적용하는 **Milestone 1** 진행 중.
- M1 진행: P0(진단) → P1(맥락) → P1.5(그래프 이관) → P2(HITL) → P3(OWASP 가드레일) → **P4(캐시 동적 학습) 완료**
- 다음 할 일은 [BACKLOG.md](BACKLOG.md) 참조. 최근 작업 맥락은 [DEVLOG.md](DEVLOG.md) 최상단 항목.

---

## 작업별 라우팅

**무엇을 하려는지 찾아서, 지정된 문서를 읽고 시작하세요.**

| 하려는 작업 | 읽을 문서 |
|---|---|
| **새 도구 추가** | [ARCHITECTURE.md § 도구](ARCHITECTURE.md#도구-33개) → [WORKFLOW.md § 도구 추가 절차](WORKFLOW.md#새-도구-추가) |
| **버그 수정** | [BACKLOG.md](BACKLOG.md)에서 항목 확인 → [WORKFLOW.md § 작업 루프](WORKFLOW.md#작업-루프) |
| **새 파일을 어디 둘지 모를 때** | [STRUCTURE.md § 배치 결정 트리](STRUCTURE.md#새-파일-배치-결정-트리) |
| **에이전트 동작(그래프) 수정** | [ARCHITECTURE.md § 그래프](ARCHITECTURE.md#그래프-파이프라인) → [design/M1_아키텍처_설계.md](design/M1_아키텍처_설계.md) |
| **보안·가드레일 수정** | [ARCHITECTURE.md § 보안](ARCHITECTURE.md#보안--4층-방어) |
| **캐시 매칭·학습 수정** | [ARCHITECTURE.md § 캐시](ARCHITECTURE.md#커맨드-캐시) → [design/M1_P4_캐시정책.md](design/M1_P4_캐시정책.md) |
| **구조를 바꾸는 큰 결정** | [design/](design/)에 ADR 먼저 작성 → [WORKFLOW.md § 설계 결정](WORKFLOW.md#설계-결정-adr) |
| **테스트 작성·실행** | [WORKFLOW.md § 테스트](WORKFLOW.md#테스트) · 수동 항목은 [testing/](testing/) |
| **커밋·브랜치·PR** | [WORKFLOW.md § 커밋 컨벤션](WORKFLOW.md#커밋-컨벤션) · [CONTRIBUTING.md](CONTRIBUTING.md) |
| **발표·제출 자료 준비** | [presentation/](presentation/) |

---

## 문서 목록

### 개발 문서

| 문서 | 내용 | 갱신 주기 |
|---|---|---|
| [STRUCTURE.md](STRUCTURE.md) | 디렉토리 구조와 **왜 그렇게 배치했는가**. 새 파일 배치 결정 트리 | 구조 변경 시 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 시스템이 **어떻게 동작하는가**. 그래프 파이프라인·도구·보안·캐시 | 동작 변경 시 |
| [WORKFLOW.md](WORKFLOW.md) | **어떻게 작업하는가**. 작업 루프·테스트·DEVLOG 규칙·커밋 컨벤션 | 절차 변경 시 |
| [DEVLOG.md](DEVLOG.md) | 개발 일지. **단일 진실 공급원(SoT)** | 작업할 때마다 |
| [BACKLOG.md](BACKLOG.md) | 미해결 항목. [즉시/위험] vs [TODO/품질] | 발견·해결 시 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 팀 협업 규칙 (브랜치 구조·작업 루틴·충돌 해결) | 거의 없음 |

### 설계 문서 (ADR) — [design/](design/)

| 문서 | 내용 |
|---|---|
| [M1_아키텍처_설계.md](design/M1_아키텍처_설계.md) | 맥락 붕괴 버그의 근본 원인 진단 + To-Be 그래프 설계. **이 프로젝트에서 가장 중요한 문서** |
| [M1_P1.5_그래프이관_계획.md](design/M1_P1.5_그래프이관_계획.md) | 구 엔진 → 그래프 로직 1:1 이관 매핑 |
| [M1_P4_캐시정책.md](design/M1_P4_캐시정책.md) | 동적 학습의 자격·저장구조·정리·롤백 정책 |

### 테스트 문서 — [testing/](testing/)

자동 검증이 불가능한 UI·음성·시각 확인 항목. 자동 테스트는 루트 `test_*.py` 참조.

- [TEST_CASES.md](testing/TEST_CASES.md) · [MANUAL_TEST_CASES.md](testing/MANUAL_TEST_CASES.md) · [MANUAL_TESTS.md](testing/MANUAL_TESTS.md)

> ⚠️ 세 문서가 자동/수동 경계를 서로 다르게 잡고 있어 부분적으로 낡았다. 통합 예정 (BACKLOG).

### 발표 자료 — [presentation/](presentation/)

2026.06.15 데모 시점 산출물. 개발 코드와 생명주기가 달라 분리 보관.

- [STUDY_GUIDE.md](presentation/STUDY_GUIDE.md) — 발표용 기술 가이드 (948줄, 심사 Q&A 대비)
- [pluiz_QnA.md](presentation/pluiz_QnA.md) — 예상 질문 답변서 (정당성·차별성·기여도)
- [pluiz_evolution.md](presentation/pluiz_evolution.md) — V0 → V1 → V2 발전사
- `pluiz_presentation.html` — reveal.js 슬라이드 · 다이어그램 SVG/PNG 8개

### 아카이브 — [../archive/](../archive/)

대체됐지만 히스토리 참고용으로 보존.

- [HANDOFF.md](../archive/HANDOFF.md) — 2026.06.22 인수인계 스냅샷 (구 엔진 기준)
- `ui.html` — Electron 이전의 브라우저 단독 UI

---

## 문서 원칙

**한 사실은 한 문서에만 쓴다.**

과거에 `CLAUDE.md`가 코드와 크게 어긋난 적이 있는데, 원인은 같은 내용이 여러 문서에 중복돼 한쪽만 갱신됐기 때문이다. 그래서:

- 구조는 `STRUCTURE.md`, 동작은 `ARCHITECTURE.md`, 절차는 `WORKFLOW.md`가 **단독으로** 책임진다.
- [`../CLAUDE.md`](../CLAUDE.md)는 내용을 담지 않고 **여기로 안내만** 한다.
- [`../README.md`](../README.md)는 외부 방문자용 소개이므로 상세를 담지 않고 이 허브로 링크한다.
- 중복이 필요해 보이면, 중복 대신 **링크**한다.
