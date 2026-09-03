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
"""
import os
import tempfile

os.environ.setdefault(
    "PLUIZ_LOG_DIR", os.path.join(tempfile.gettempdir(), "pluiz_test_logs")
)
