from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal
from functools import lru_cache


class Settings(BaseSettings):
    # LLM
    llm_provider: Literal["gemini", "claude", "openai"] = "gemini"
    gemini_api_key: str = ""
    claude_api_key: str = ""
    openai_api_key: str = ""

    # YouTube Data API v3
    youtube_api_key: str = ""

    # 모델 (비워두면 provider별 기본값 사용)
    gemini_model: str = "gemini-2.5-flash"
    claude_model: str = "claude-haiku-4-5-20251001"
    openai_model: str = "gpt-4o-mini"

    # 서버
    server_port: int = 8765
    server_host: str = "127.0.0.1"

    # 로컬 API 접근 제어 (BL-14)
    # 서버가 기동할 때마다 토큰을 발급해 cache/.auth_token 에 적고, Electron과 라이브
    # 테스트가 그 파일을 읽는다. 웹페이지는 로컬 파일을 못 읽으므로 명령을 넣을 수 없다.
    # ⚠️ false로 두면 아무 웹사이트가 PC 제어 명령을 넣을 수 있다. 디버깅용 탈출구다.
    auth_enabled: bool = True

    # 에이전트
    agent_max_iterations: int = 10   # 무한루프 방지
    # ⚠️ 30 → 45로 올렸다(2026-09-03). 실행 결과 시각적 검증이 켜지면 한 턴에
    #    Vision 1회(약 8초)가 더해진다: agent LLM ~3초 + 도구 + Vision 8초 + agent LLM ~3초.
    #    30초로는 정상 동작이 타임아웃으로 잘릴 수 있었다.
    agent_timeout: int = 45          # 초
    # ※ use_graph 플래그는 M1-P5(엔진 단일화)에서 제거됨.
    #   PluizGraphAgent가 유일한 엔진이다. → docs/design/M1_P5_엔진단일화.md

    # 실행 결과 시각적 검증 (Phase 2)
    # 도구 실행 직후 화면을 보고 "진짜 됐나?"를 확인해 그 증거를 도구 결과에 붙인다.
    # 대상은 거짓 성공이 실측된 도구뿐이다 → core/graph.py 의 VISUAL_VERIFY_TOOLS
    # ⚠️ OWASP LLM02 — 켜져 있으면 **사용자가 화면을 묻지 않아도** type_text·open_app
    #    실행 시 스크린샷이 외부 LLM으로 나간다. describe_screen("물어볼 때만")보다
    #    넓은 전송이다. 끄려면 .env 에 VISION_VERIFY_ENABLED=false 한 줄.
    vision_verify_enabled: bool = True

    # 계획 수립 노드 (M3 · Plan-and-Execute)
    # 복합 명령을 최대 2단계로 나눠 순서대로 실행하고, **못 한 단계를 정직하게 말한다.**
    # 값어치는 "여러 단계를 실행한다"가 아니라 "몇 단계를 못 했는지 말할 수 있다"에 있다.
    # **2026-09-07에 기본 켜짐으로 올렸다.** 라이브 증거가 생겼기 때문이다 —
    #    같은 날 오전엔 꺼져 있었고, BL-21(건너뛴 단계를 완료로 세던 것)을 고친 뒤
    #    오후 실기에서 세 경우가 다 확인됐다:
    #      · 도구 2개 실행 → 조용     (거짓 실패를 만들지 않는다)
    #      · 도구 1개만 실행 → "다만 이건 못 했어요: '계산기 닫기'."
    #      · 승인 거부/승인 후 재개 → 계획이 중단을 넘어 완주
    #    켜면 복합 명령마다 LLM 왕복 1회가 얹힌다(실측 턴 3~5초 — 계획 없는 턴 4초와
    #    비슷했다). 되돌리려면 `.env`에 PLAN_ENABLED=false 한 줄이면 된다.
    #    → docs/design/M3-1_단계완료판정.md · docs/design/M3_계획수립노드.md
    plan_enabled: bool = True

    # 화면 변화 모니터링 (Phase 2) — "오류 뜨면 알려줘"
    # ⚠️ OWASP LLM02 — 지금까지 중 화면 전송량이 가장 큰 기능이다. 방어는 두 겹:
    #    ① 5초마다 찍는 건 전부 로컬(픽셀 비교)이고, 변화가 있을 때만 Vision을 부른다.
    #    ② **max_vision_calls가 곧 외부로 나가는 화면 장수의 상한이다.**
    #    시간·횟수 중 먼저 닿는 쪽에서 자동 종료한다. → core/screen_monitor.py
    screen_watch_enabled: bool = True
    screen_watch_interval: int = 5           # 초 — 캡처 주기(로컬, 전송 없음)
    screen_watch_max_minutes: int = 10
    screen_watch_max_vision_calls: int = 20  # ← 실질적인 외부 전송량 상한

    # 커맨드 캐시 (P4)
    cache_learning: bool = True      # 동적 학습 on/off 스위치
    cache_max_dynamic: int = 200     # 동적 학습 상한(초과 시 LRU 정리)

    # STT
    whisper_model: str = "base"      # tiny / base / small / medium
    whisper_language: str = "ko"

    # TTS
    tts_voice: str = "ko-KR-SunHiNeural"   # 자연스러운 한국어 여성 음성

    # 웨이크워드 — 사용자가 직접 정한다
    # 쉼표로 구분. 비워두면 services/wakeword.py 의 기본값("플루이즈" 계열)을 쓴다.
    # 예: WAKE_WORDS=플루이즈,헤이 플루이즈,pluiz
    wake_words: str = ""
    wake_word_enabled: bool = True
    # 인식 튜닝 — 마이크/환경마다 달라서 코드 수정 없이 조절할 수 있게 뺐다
    wakeword_model: str = "base"          # tiny / base. ⚠️ base가 오히려 **5배 빠르다** —
                                          # tiny는 환각으로 수백 토큰을 뱉느라 시간을 다 쓴다
                                          # (2026-09-02 실측: tiny 61초 vs base 12.9초, 같은 오디오)
    wakeword_energy: float = 0.008        # 무음 스킵 임계. 낮출수록 작은 소리도 처리
                                          # (기본 0.015는 조용한 마이크에서 발화를 버렸다)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def active_model(self) -> str:
        return {
            "gemini": self.gemini_model,
            "claude": self.claude_model,
            "openai": self.openai_model,
        }[self.llm_provider]

    @property
    def wake_word_list(self) -> list[str]:
        """설정된 웨이크워드를 리스트로. 비어 있으면 빈 리스트(→ 호출부가 기본값 사용)."""
        return [w.strip() for w in self.wake_words.split(",") if w.strip()]

    @property
    def active_api_key(self) -> str:
        return {
            "gemini": self.gemini_api_key,
            "claude": self.claude_api_key,
            "openai": self.openai_api_key,
        }[self.llm_provider]


@lru_cache
def get_settings() -> Settings:
    return Settings()
