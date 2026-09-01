# Pluiz v2 — Claude Code 진입점

**Pluiz** — 한국어 음성 명령으로 Windows PC를 제어하는 AI 에이전트. 졸업 캡스톤.
FastAPI 서버(:8765) + Electron 오버레이 UI + LangGraph `StateGraph` 에이전트.

---

## 📖 먼저 [`docs/README.md`](docs/README.md)를 읽으세요

이 파일은 **안내만 합니다.** 실제 내용은 전부 `docs/` 아래에 있습니다.

> **원칙: 한 사실은 한 문서에만.**
> 과거에 이 파일이 코드와 크게 어긋난 적이 있는데, 같은 내용이 여러 문서에 중복돼
> 한쪽만 갱신됐기 때문입니다. 그래서 이 파일에는 상세를 적지 않습니다.
> **여기에 설명을 추가하고 싶다면, 해당 `docs/` 문서에 쓰고 여기서는 링크만 하세요.**

| 알고 싶은 것 | 문서 |
|---|---|
| **전체 문서 지도 · 작업별 라우팅** | [docs/README.md](docs/README.md) ← **여기부터** |
| 뭘 어디에 두는가 · 새 파일 배치 | [docs/STRUCTURE.md](docs/STRUCTURE.md) |
| 시스템이 어떻게 도는가 (그래프·도구·보안·캐시) | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
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

6. **테스트에서 소스를 열 땐 `encoding="utf-8"`를 붙일 것** — 한글이 든 소스를
   Windows 기본 cp949로 읽으면 `UnicodeDecodeError`가 납니다.
   `tests/`의 테스트는 루트를 `dirname(dirname(abspath(__file__)))`로 계산합니다.

---

## 실행 · 테스트

**⚠️ 루트 `python`(anaconda base)에는 langgraph가 없습니다. `pluiz` 환경을 쓰세요.**
**⚠️ 콘솔이 cp949라 테스트 출력에 `PYTHONIOENCODING=utf-8`이 필요합니다.**

```bash
conda activate pluiz
export PYTHONIOENCODING=utf-8

launch.bat                  # 서버 + Electron UI
python main.py              # 서버만

python tests/test_graph_agent.py  # 6/6
python tests/test_cache_learn.py  # 15/15
python tests/test_hitl_agent.py   # 8/8
```

상세: [docs/WORKFLOW.md](docs/WORKFLOW.md)

---

## 작업을 마칠 때

**[docs/DEVLOG.md](docs/DEVLOG.md)에 항목 추가 + 관련 문서 갱신까지가 한 세트입니다.**
기록되지 않은 작업은 다음 세션에서 존재하지 않는 것과 같습니다.
새 문서를 만들었다면 [docs/README.md](docs/README.md) 인덱스에도 추가하세요.
