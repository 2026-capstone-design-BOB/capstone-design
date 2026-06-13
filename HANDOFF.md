# Pluiz v2 — 세션 인수인계 문서

> **작성일**: 2026.06.13  
> **데모 마감**: 2026.06.15 (D-2)

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

## 남은 작업

### 필수 (데모 전)

1. **서버 기동 후 test_commands.py 전체 실행**
   ```bash
   cd C:\pluiz_v2
   python main.py        # 터미널 1 (서버)
   python test_commands.py  # 터미널 2
   ```
   이전 세션 기준 25/25 통과. 이번 변경 후 미검증 상태.

2. **실제 음성 명령 통합 테스트** (Electron UI 기동)
   ```bash
   start.bat
   ```
   확인 항목:
   - "계산기 실행해줘" → 계산기 열림 (A-02, 캐시 hit)
   - "계산기 꺼줘" → 계산기 닫힘 (BUG-01, 캐시 hit)
   - "유튜브에서 아이유 검색해줘" → 유튜브 검색 실행 (W-02, LLM 경로)
   - 연속 대화 ("크롬 켜줘" → "방금 켠 거 꺼줘") → 맥락 유지 확인

### 선택 (데모 품질 개선)

3. **stream() 경로 재시도 로직** 미구현
   - 현재 `run_async()`에는 retry 있지만 `stream()` (WebSocket)에는 없음
   - WebSocket 응답이 도구 미호출로 빈 경우 재시도 안 함
   - 구현 위치: `core/agent.py` `stream()` 메서드

4. **캐시 hit 응답 템플릿 개선**
   - 현재 `entry.response_template` 고정 문자열 반환
   - "계산기 꺼줘" → "✓ 계산기을(를) 종료했습니다." (조사 어색함)
   - 조사 처리 로직 추가 or 앱별 응답 직접 지정

---

## 알려진 미구현 사항 (데모에서 제외)

- 웨이크워드 ("소윤아") — 인식률 낮음, 데모는 Alt+Space 사용
- 클립보드 읽기 도구
- stream() 재시도 로직

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
