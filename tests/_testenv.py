"""
테스트 실행 환경 — **제품 상태를 건드리지 않게** 맞춰 둔다.

각 테스트 파일이 **다른 import보다 먼저** `import _testenv` 한 줄을 넣는다.
(`python tests/test_x.py`로 돌리면 파이썬이 `tests/`를 sys.path 맨 앞에 넣어 주므로
 그냥 import 된다. 파일명이 `test_*`가 아니라서 CI 글롭에도 안 걸린다.)

## 왜 있나 — 로그 오염 (BL-11 계열)

`core/logger.py`는 `logs/pluiz.log`에 쓴다. mock 테스트도 예외가 아니라서,
테스트가 남긴 줄이 **실제 사용 기록 사이에 섞였다.** 2026-09-03에 실기 진단을
하다가 이것 때문에 헤맸다 — 사용자가 말한 적 없는 `[BL-15] … 'x'` 줄과
`RuntimeError: API 키 없음(테스트)` 스택트레이스가 로그에 있었다.

로그는 "실기에서 무슨 일이 있었나"를 답하는 유일한 근거다. 거기에 테스트 잡음이
섞이면 그 근거를 못 믿는다. 그래서 테스트는 임시 경로에 쓴다.

⚠️ `setdefault`이므로 **밖에서 지정한 값이 우선한다.** 로그를 직접 보고 싶으면
   `PLUIZ_LOG_DIR=./logs python tests/test_x.py` 로 덮어쓸 수 있다.

## 왜 있나 ② — 커맨드 캐시 오염 (BL-11)

`cache/command_cache.json`은 **git 추적 대상**인데 캐시를 만지는 테스트가 여기에
학습 결과를 썼다. 그래서 테스트를 돌릴 때마다 작업 트리가 더러워졌고, 매번
`git checkout cache/command_cache.json` 을 해야 했다.

더 나쁜 건 **반대 방향**이다 — 테스트가 사용자의 실제 학습 내용을 **읽었다.**
`test_bl15_truncation.py`는 `get_cache()`로 실제 파일을 열었으므로, 어떤 명령이
학습돼 있느냐에 따라 같은 테스트가 통과했다 실패했다 할 수 있었다.
**테스트는 사용자 상태에 의존하면 안 된다.**

일부 테스트(`test_cache_learn`·`test_cache_api`·`test_cache_synonym`)는 모듈 네임스페이스의
`CACHE_FILE`을 직접 갈아끼우는 방식으로 각자 막고 있었다. 여기서 한 번에 막으므로
그 방식도 계속 동작하고(임시 경로 → 임시 경로), 새 테스트는 아무것도 안 해도 안전하다.

⚠️ **라이브 테스트는 서버가 캐시를 쓰므로 여기서 못 막는다.** 서버 쪽에 준다:
   `PLUIZ_CACHE_FILE=/tmp/pluiz_live.json python main.py`
"""
import os
import tempfile

os.environ.setdefault(
    "PLUIZ_LOG_DIR", os.path.join(tempfile.gettempdir(), "pluiz_test_logs")
)

os.environ.setdefault(
    "PLUIZ_CACHE_FILE",
    os.path.join(tempfile.gettempdir(), "pluiz_test_cache", "command_cache.json"),
)
