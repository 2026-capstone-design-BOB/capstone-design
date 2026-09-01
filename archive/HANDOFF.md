# Pluiz v2 — 세션 인수인계 문서 (아카이브)

> ## ⚠️ 이 문서는 과거 기록입니다 (2026.06.22 시점 스냅샷)
>
> 아래 내용은 **6월 데모 직후 상태**를 기록한 것으로, 현재 코드와 다릅니다.
> 이후 Milestone 1에서 엔진이 `core/agent.py`(create_react_agent) →
> `core/graph.py`(명시적 StateGraph)로 이관되었고, HITL·OWASP 가드레일·
> 캐시 동적 학습이 추가되었습니다.
>
> **현재 상태는 다음을 보세요:**
> - `DEVLOG.md` — 개발 일지 (단일 진실 공급원)
> - `BACKLOG.md` — 미해결 항목
> - `CLAUDE.md` — 구조 요약
>
> 이 문서는 "6월 데모 시점에 무엇이 문제였고 어떻게 고쳤는가"의
> 히스토리 참고용으로만 보존합니다.

---

> **최종 업데이트**: 2026.06.22  
> **데모 마감**: 2026.06.15 ✅ 완료

---

## 이번 세션 완료 작업

| ID | 내용 | 파일 |
|----|------|------|
| BUG-01 | 캐시 매칭 Intent-based로 완전 재설계 (Stage1 Intent → Stage2 SequenceMatcher 순) | `core/command_cache.py` |
| BUG-02 | 재시도 로직: 도구 미호출 + 제어명령 키워드 감지 | `core/agent.py` |
| BUG-03 | STT 임시파일 확장자 `.wav` → `.webm` | `services/stt.py` |
| BUG-04 | TTS 파일 삭제 타이밍: speak_async 블로킹 재생 후 삭제 | `services/tts.py` |
| BUG-05 | stream() 경로에 session_memory 저장 누락 | `core/agent.py`, `main.py` |
| ISSUE-01 | settings.py 민감값 로그 노출 제거 | `config/settings.py` |
| ISSUE-02 | _clear_thread getattr 방어코딩 + checkpointer 재생성 fallback | `core/agent.py` |
| ISSUE-03 | 데드코드 run() 메서드 제거 | `core/agent.py` |
| ISSUE-04 | security.py PowerShell 단축 플래그 4개 패턴 추가 (총 29개) | `core/security.py` |
| MINOR-01 | filesystem.py 유니코드 이스케이프 → 리터럴 한국어 | `tools/filesystem.py` |
| MINOR-02 | find_file 이중 glob → 단일 recursive glob | `tools/filesystem.py` |

---

## 현재 코드 상태

### core/command_cache.py — 완전 재설계

**구조:**
```
2단계 매칭
  Stage 1 (Intent-based, 우선):
    _extract_entity() + _extract_action() → (entity_key, action_key)
    _intent_index[(entity, action)] 직접 조회
    앱+open/close 미등록 조합은 _build_intent_index()에서 자동 합성 (19개)
  Stage 2 (SequenceMatcher 0.80 이상, fallback):
    intent 추출 실패 시만 사용
```

**왜 Stage 1이 우선인가:**  
"계산기 켜줘"와 "계산기 꺼줘"는 글자 유사도 ≈ 0.93으로 Stage 1이 틀린 답을 높은 확신으로 반환함.  
Intent는 entity=calculator, action=open vs close를 정확히 구분 → 18/18 테스트 통과.

**검증:** `python3 -c "exec(open('core/command_cache.py').read()); c=CommandCache(); print(c.find('계산기 꺼줘'))"`

### core/agent.py

- `run()` 동기 메서드 제거 (호출처 없음, run_async와 기능 불일치)
- `_clear_thread()`: `getattr(checkpointer, 'storage', None)` 방어코딩
  - storage 없을 시 MemorySaver + graph 전체 재생성 fallback
- `_CONTROL_KEYWORDS`: 제어 명령 감지용 키워드 frozenset
- `_is_control_command()`: 재시도 트리거 조건 판단

### tools/filesystem.py

- `find_file`: 단일 `recursive=True` glob
- `_resolve_location_in_path`: 유니코드 이스케이프 → 리터럴 한국어 (`바탕화면`, `문서`, `다운로드`)

### services/tts.py

`speak_async`:
1. `to_bytes_async()` → MP3 바이트
2. 임시파일 기록
3. `asyncio.to_thread(_play_audio_blocking)` — 블로킹 재생
4. `finally: os.unlink()` — 재생 완료 후 삭제

`_play_audio_blocking` 3단 fallback:
1. PowerShell `System.Windows.Media.MediaPlayer` (재생 완료 감지)
2. WMPlayer.OCX COM
3. `os.startfile` + `time.sleep(5)`

---

## 남은 작업 (데모 이후 개선 후보)

1. **stream() 경로 재시도 로직** 미구현
   - 현재 `run_async()`에는 retry 있지만 `stream()` (WebSocket)에는 없음
   - WebSocket 응답이 도구 미호출로 빈 경우 재시도 안 함
   - 구현 위치: `core/agent.py` `stream()` 메서드

2. **캐시 hit 응답 템플릿 개선**
   - 현재 `entry.response_template` 고정 문자열 반환
   - "계산기 꺼줘" → "✓ 계산기을(를) 종료했습니다." (조사 어색함)
   - 조사 처리 로직 추가 or 앱별 응답 직접 지정

3. **웨이크워드 ("소윤아")** — 인식률 낮아 보류. 개선 시 faster-whisper tiny 대신 다른 모델 검토 필요

4. **클립보드 읽기 도구** — 미구현. `pyperclip` 또는 Win32 API로 구현 가능

---

---

## 실행 방법

```bash
# 서버만
cd C:\pluiz_v2
python main.py

# 전체 (서버 + Electron)
start.bat

# 테스트 (서버 켜진 상태)
python test_commands.py
```

---

## 주의사항

- `cache/command_cache.json` 손상 시 자동 초기화 (시드 37개로 재구성)
- `thread_id` 오염 → `reset_agent()` 호출
- pycaw 볼륨 제어: asyncio 컨텍스트 불안정 → PowerShell fallback 있음
- `get_settings()`는 `@lru_cache` → `.env` 변경 후 반드시 `cache_clear()` 필요
