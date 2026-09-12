# Pluiz v2 — Claude Code 진입점

**Pluiz** — 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트. 졸업 캡스톤.
FastAPI 서버(:8765) + Electron 오버레이 UI + LangGraph `StateGraph` 에이전트.

---

## 🚀 "docs 보고 진행해줘" 라고 하면

1. [`docs/TASKS.md`](docs/TASKS.md) — **작업 체크리스트.** 지금 뭘 하는 중이고 다음이 뭔지
2. [`docs/ROADMAP.md`](docs/ROADMAP.md) — 어디로 가는가 (학기 목표 · 계획 대비 실제)
3. [`docs/DEVLOG.md`](docs/DEVLOG.md) **최상단** — 직전 세션에 무슨 일이 있었는지

이 셋만 읽으면 바로 작업할 수 있습니다.
상세가 필요하면 [`docs/README.md`](docs/README.md)의 작업별 라우팅 표를 보세요.

---

## 💸 토큰 — 이 저장소는 한국어 문서가 커서 낭비가 증폭됩니다

- **서브에이전트를 기본으로 쓰지 않습니다.** 파일은 직접 읽습니다(5개 이하면 무조건).
  범위가 불확실할 때만 `Grep`으로 좁힌 뒤 읽습니다.
- **산출물이 문서인 작업**(ADR·설계·기록)엔 **플랜 모드를 쓰지 않습니다** —
  계획과 결과물이 같은 물건이라 같은 내용을 두 번 이상 쓰게 됩니다.
- 큰 문서는 `limit`/`offset`으로 필요한 부분만. `DEVLOG.md`는 **최상단 항목만** 보면 됩니다.
- 할 일이 이미 특정돼 있으면 **위 세 문서를 통독하지 않습니다.** 해당 문서만 엽니다.

> 2026-09-05에 ADR 하나(480줄)를 만들며 에이전트 3개를 돌리고 같은 설계를 네 번 썼습니다.
> **프롬프트는 확률을 올릴 뿐이고 보장하는 건 구조입니다**(BL-19의 교훈과 같은 모양) —
> 그래서 진입점 자체를 짧게 유지합니다. 세션 서사는 [`docs/DEVLOG.md`](docs/DEVLOG.md)에만 씁니다.

---

## 📖 먼저 [`docs/README.md`](docs/README.md)를 읽으세요

이 파일은 **안내만 합니다.** 실제 내용은 전부 `docs/` 아래에 있습니다.

> **원칙: 한 사실은 한 문서에만.**
> 과거에 이 파일이 코드와 크게 어긋난 적이 있는데, 같은 내용이 여러 문서에 중복돼
> 한쪽만 갱신됐기 때문입니다. 그래서 이 파일에는 상세를 적지 않습니다.
> **여기에 설명을 추가하고 싶다면, 해당 `docs/` 문서에 쓰고 여기서는 링크만 하세요.**

| 알고 싶은 것 | 문서 |
|---|---|
| **지금 뭘 해야 하나 (체크리스트)** | [docs/TASKS.md](docs/TASKS.md) ← **여기부터** |
| **어디로 가는가 (학기 목표)** | [docs/ROADMAP.md](docs/ROADMAP.md) |
| **전체 문서 지도 · 작업별 라우팅** | [docs/README.md](docs/README.md) |
| 뭘 어디에 두는가 · 새 파일 배치 | [docs/STRUCTURE.md](docs/STRUCTURE.md) |
| 시스템이 어떻게 도는가 (그래프·도구·보안·캐시) | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **로그로 무슨 일이 있었는지 보기** | `logs/pluiz.log` — `[Agent] 턴 완료`·`[Graph] 승인 판정`·`[FastPath] [BL-15]`·`[Vision]` |
| 어떻게 작업하는가 (테스트·DEVLOG·커밋) | [docs/WORKFLOW.md](docs/WORKFLOW.md) |
| 지금까지 무엇을 했나 | [docs/DEVLOG.md](docs/DEVLOG.md) ← 최상단이 최신 |
| 무엇이 남았나 | [docs/BACKLOG.md](docs/BACKLOG.md) |
| 왜 이렇게 설계했나 | [docs/design/](docs/design/) |

---

## ⚠️ 코드를 고치기 전에 — 절대 규칙

아래는 어기면 바로 깨지는 것들입니다. 배경 설명은 각 링크 참조.

1. **그래프 노드를 async로 바꾸지 말 것** — LangGraph `interrupt`(HITL 승인)가 sync
   경로에서만 안정 동작합니다. → [ARCHITECTURE.md](docs/ARCHITECTURE.md#그래프-파이프라인)

2. **`fast_path` 히트를 조기 return으로 "최적화"하지 말 것** — 캐시 결과도
   `state.messages`에 누적돼야 다음 턴에 맥락이 이어집니다. 이걸 지우면 맥락 붕괴 버그가
   재발합니다. → [design/M1_아키텍처_설계.md](docs/design/M1_아키텍처_설계.md)

3. **히스토리를 슬라이스로 자르지 말 것** — `trim_messages(start_on="human")`만 사용.
   슬라이스는 도구호출/ToolMessage 쌍을 깨서 Gemini 400을 유발합니다.

4. **`.env` 변경 후 `get_settings.cache_clear()`** — `@lru_cache`라 안 하면 옛 값이 계속 쓰입니다.

5. **`services/`·`electron-ui/`를 `src/` 같은 폴더로 감싸지 말 것** — Electron이
   `../services/wakeword.py`를 직접 참조합니다. → [STRUCTURE.md § 구조적 제약](docs/STRUCTURE.md#구조적-제약--옮기면-깨지는-것들)

6. **"이번 턴"을 판단할 땐 `current_turn_messages()`를 쓸 것** — `state["messages"]`는
   thread 전체 히스토리다. 그냥 훑으면 과거 턴의 도구 오류·도구 호출이 현재 응답과
   캐시 학습을 오염시킨다. → [design/M1_아키텍처_설계.md § 5-A](docs/design/M1_아키텍처_설계.md)

7. **테스트에서 소스를 열 땐 `encoding="utf-8"`를 붙일 것** — 한글이 든 소스를
   Windows 기본 cp949로 읽으면 `UnicodeDecodeError`가 납니다.
   `tests/`의 테스트는 루트를 `dirname(dirname(abspath(__file__)))`로 계산합니다.

8. **`/voice`의 `thread_id`·`use_tts`에서 `Form(...)`을 빼지 말 것** — FastAPI가
   스칼라를 **쿼리 파라미터**로 해석해 렌더러가 FormData로 보내는 값을 통째로 무시한다.
   그러면 **음성과 텍스트가 서로 다른 대화가 되고**, 평범한 명령은 멀쩡해 보이다가
   승인·지칭처럼 맥락이 필요한 순간에만 무너진다. → [BACKLOG BL-16](docs/BACKLOG.md)

9. **클릭 도구에 좌표 인자(`x`, `y`)를 추가하지 말 것** — `click_ui_element`가
   `(target, window)`만 받는 건 실수가 아니다. LLM이 좌표를 넘길 수 있으면 언젠가
   지어내고, 그러면 **틀린 좌표를 정확히 클릭하는** 도구가 된다. 클릭은 되돌릴 수 없다.
   → [ARCHITECTURE § 도구](docs/ARCHITECTURE.md#도구-41개)

10. **`main.py`의 `allow_origins=["null"]`과 OPTIONS 면제를 "정리"하지 말 것** —
   둘 다 오타가 아니라 **UI가 돌기 위한 조건**입니다. 렌더러는 `file://`이라 `Origin: null`을
   보내고, `X-Pluiz-Token`은 safelisted 헤더가 아니라 모든 요청이 프리플라이트를 거칩니다.
   여기를 조이면 공격자가 아니라 **UI 자신이 막힙니다.** 실질적 방어는 토큰입니다.
   → [ARCHITECTURE.md § 보안 0층](docs/ARCHITECTURE.md#보안--5층-방어)

11. **계획 상태(`plan`/`plan_cursor`)를 턴 너머로 새게 하지 말 것** — ① 이 두 필드에
   **리듀서를 붙이면** 지난 턴 계획이 이번 턴 뒤에 이어 붙는다. ② `hitl`의
   `other_command` 분기에서 **계획을 지우는 줄을 지우면**, 승인 대기 중 들어온 새 명령이
   *"지금은 2단계: test.txt 삭제"* 지시를 받는다(`Command(resume)`은 `input_guard`를
   거치지 않는다). 취소 플래그가 새어 **삭제해 놓고 "취소했어요"라고 답한 사고와 같은
   모양**이다. → [design/M3_계획수립노드.md § 3-3](docs/design/M3_계획수립노드.md)

---

## 실행 · 테스트

**⚠️ 루트 `python`(anaconda base)에는 langgraph가 없습니다. `pluiz` 환경을 쓰세요.**
**⚠️ 콘솔이 cp949라 테스트 출력에 `PYTHONIOENCODING=utf-8`이 필요합니다.**

```bash
conda activate pluiz
export PYTHONIOENCODING=utf-8

launch.bat                  # 서버 + Electron UI
python main.py              # 서버만

python tests/test_graph_agent.py  # 30/30
python tests/test_cache_learn.py  # 67/67
python tests/test_hitl_agent.py   # 8/8
python tests/test_hitl_graph.py   # 140/140  ← 승인 경로 전체(BL-20·24·38·40)
python tests/test_offline_skip.py # 11/11   ← 오프라인이면 LLM을 안 부른다(BL-46)

python scripts/run_mock_suite.py  # 46파일 1601/1601  ← 합계는 항상 이걸로 센다
```

상세: [docs/WORKFLOW.md](docs/WORKFLOW.md)

---

## 작업을 마칠 때

**[docs/DEVLOG.md](docs/DEVLOG.md)에 항목 추가 + 관련 문서 갱신까지가 한 세트입니다.**
기록되지 않은 작업은 다음 세션에서 존재하지 않는 것과 같습니다.
새 문서를 만들었다면 [docs/README.md](docs/README.md) 인덱스에도 추가하세요.

### 🔚 "마무리해줘"라고 하면

절차가 [docs/WORKFLOW.md § "마무리해줘"](docs/WORKFLOW.md#-마무리해줘--세션을-닫는-절차)에
**체크리스트로** 있습니다. 그대로 따르세요 — 사용자가 매번 무엇을 하라고
지시하지 않아도 되도록 고정해 둔 것입니다.

요약: 작업 트리 정리(캐시 되돌리기·서버 종료) → mock 스위트를 **실제로 돌려**
숫자 확인 → DEVLOG·TASKS·BACKLOG·README 갱신 → 성격별 커밋 →
**푸시는 하지 않음(⏸️ 사용자 결정)** → 「한 일 / 사용자가 할 일 / 남은 것」 보고.

**목표는 다음 세션이 "docs 보고 진행해줘" 한 마디로 이어가는 것입니다.**
