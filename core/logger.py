"""
Pluiz 로깅 — 최소 도입
======================
`print` 대신 쓰는 공용 로거. **전면 교체가 목적이 아니다.**

## 왜 필요한가
Vision·웨이크워드처럼 **실패가 잦고 원인이 눈에 안 보이는 기능**은 `print`로 디버깅할 수
없다. 서버가 죽거나 사용자가 "안 돼요"라고 말한 뒤에 볼 수 있는 기록이 없었기 때문이다.
로드맵의 "로깅 시스템 도입"(방학 6-7월, 미착수)을 **9월 Vision 작업에 필요한 만큼만** 당겨온다.

## 왜 loguru가 아니라 표준 logging인가
- 새 의존성이 필요 없다. 지금 목적(파일에 남기기 + 레벨 구분)에는 표준으로 충분하다.
- 로드맵 문구도 "loguru **등**"이라 특정 라이브러리를 못박지 않았다.
- 나중에 loguru로 바꾸더라도 이 모듈의 `get_logger()` 인터페이스만 유지하면 호출부는 그대로다.

## 콘솔 출력은 기존 관습을 유지한다
코드베이스 전반이 `[CommandCache] 학습: ...` 형태로 찍고 있다. 콘솔은 그대로 두고
(`[이름] 메시지`), **파일에만** 시각·레벨·모듈을 붙인다. 기존 print와 섞여도 어색하지 않다.

## ⚠️ Windows 주의
- 콘솔이 cp949라 한글이 깨지거나 `UnicodeEncodeError`가 날 수 있다. 파일 핸들러는
  `encoding="utf-8"`을 **반드시** 주고, 콘솔 핸들러는 인코딩 실패 시 죽지 않게 막는다.
- 로그 파일은 `logs/pluiz.log`. `.gitignore`의 `*.log`가 이미 잡는다.

## 사용법
```python
from core.logger import get_logger
log = get_logger("Vision")

log.info("스크린샷 촬영: %s", path)   # 콘솔 + 파일
log.debug("응답 원문: %s", raw)       # 기본은 파일에만 (콘솔은 INFO 이상)
log.exception("Vision 호출 실패")      # 스택트레이스까지 파일에 남는다
```
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# ── 위치 ──────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 테스트가 제품 로그를 더럽히지 않도록 경로를 바꿀 수 있게 한다. (BL-11 계열)
# 2026-09-03에 mock 테스트가 남긴 `[BL-15] … 'x'` 6줄이 실제 사용 기록 사이에 섞여
# 실기 진단을 방해했다. 테스트는 PLUIZ_LOG_DIR을 임시 경로로 잡고 돈다.
LOG_DIR = os.environ.get("PLUIZ_LOG_DIR") or os.path.join(_ROOT, "logs")
LOG_PATH = os.path.join(LOG_DIR, "pluiz.log")

# 루트 로거 이름. 모든 Pluiz 로거는 이 아래에 붙어 핸들러를 공유한다.
_BASE = "pluiz"

_configured = False


class _SafeStreamHandler(logging.StreamHandler):
    """콘솔 인코딩(cp949)이 한글·이모지를 못 찍어도 프로그램을 죽이지 않는다.

    로깅이 기능을 망가뜨리는 건 본말전도다. 콘솔에 못 쓰면 조용히 넘어가고,
    파일 핸들러(UTF-8)에는 정상적으로 남는다.
    """

    def emit(self, record):
        try:
            super().emit(record)
        except UnicodeEncodeError:
            try:
                msg = self.format(record).encode("ascii", "replace").decode("ascii")
                self.stream.write(msg + self.terminator)
                self.flush()
            except Exception:
                pass
        except Exception:
            pass


def _level_from_env() -> int:
    """로그 레벨. `.env`의 LOG_LEVEL 또는 환경변수로 조절한다.

    settings.py를 거치지 않는 이유: 로거는 설정보다 먼저 필요할 수 있고
    (설정 로딩 자체를 로깅하고 싶을 때), 순환 import를 만들지 않기 위해서다.
    """
    name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, name, logging.INFO)


def _configure() -> None:
    """핸들러를 한 번만 붙인다. 여러 번 호출해도 중복 출력되지 않는다."""
    global _configured
    if _configured:
        return

    base = logging.getLogger(_BASE)
    base.setLevel(logging.DEBUG)      # 실제 필터링은 핸들러에서 한다
    base.propagate = False            # uvicorn 루트 로거로 새어나가 중복 출력되는 것 방지

    console = _SafeStreamHandler(sys.stdout)
    console.setLevel(_level_from_env())
    # 기존 print 관습과 같은 모양: [CommandCache] 메시지
    console.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    base.addHandler(console)

    # 파일 핸들러는 실패해도 서버가 떠야 한다 (권한·경로 문제로 죽이지 않는다)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fileh = RotatingFileHandler(
            LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fileh.setLevel(logging.DEBUG)   # 파일에는 DEBUG까지 남긴다 — 사후 추적용
        fileh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        base.addHandler(fileh)
    except Exception as e:
        base.warning("로그 파일 핸들러 비활성 (콘솔만 사용): %s", e)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """컴포넌트용 로거를 반환한다.

    `name`은 기존 print의 대괄호 안 이름을 그대로 쓴다 (예: "Vision", "CommandCache").
    콘솔에는 `[Vision] 메시지`로 찍혀 기존 출력과 같은 모양이 된다.
    """
    _configure()
    # 내부적으로는 pluiz.Vision 이지만 콘솔엔 짧은 이름만 보이게 한다
    logger = logging.getLogger(f"{_BASE}.{name}")
    logger.name = name
    return logger
