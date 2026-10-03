from pydantic_settings import BaseSettings
from pydantic import Field
from typing import ClassVar, Literal
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

    # Vision 응답을 로그에 남길까 (2026-09-08 결정 — 기본 꺼짐, 진단할 때만 켠다)
    # 지금은 `Vision 응답 349자`처럼 **길이만** 남는다. 그래서 2026-09-03에
    # "Vision이 뭐라고 답했길래 저런 결과가 나왔나"를 사후에 확인할 수 없어 진단이
    # 한 번 막혔다. 켜면 앞 vision_log_preview_chars 자를 함께 남긴다.
    # ⚠️ **화면에 떠 있던 내용이 로그 파일에 기록된다.** 비밀번호·계좌가 보였다면
    #    그것도 남는다. 그래서 기본은 꺼짐이고, 켜는 것은 **사람이 의도적으로**
    #    하는 일이어야 한다(.env 에 VISION_LOG_RESPONSE=true 한 줄).
    #    로그는 마스킹을 거치지 않는다 — mask_sensitive_output()은 사용자에게 나가는
    #    응답에만 걸린다.
    vision_log_response: bool = False
    vision_log_preview_chars: int = 200

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

    # ── ⏳ 백그라운드 작업자 (2026-09-25) ──────────────────────────
    #
    # *"30분 뒤에 알려줘"* · *"메일 오면 알려줘"* · *"끝나면 알려줘"*.
    # 🚨 **그래프 «밖»에서 돈다** — 노드를 async 로 만들면 승인(HITL)이 깨진다
    #   (절대규칙 1). → core/worker.py · docs/design/M9_백그라운드_작업자.md
    worker_enabled: bool = True
    worker_max_jobs: int = 5          # 동시에 잡아 둘 약속 수 = 스레드 수 상한

    # 메일 기다리기 — 되풀이 확인이라 **간격이 곧 API 호출량**이다.
    # ⚠️ 모델이 더 짧게 불러도 core/worker.py 의 바닥(60초)까지만 내려간다.
    inbox_watch_interval: int = 120   # 초
    inbox_watch_max_minutes: int = 60 # 이 시간이 지나면 스스로 멈추고 **알린다**

    # 커맨드 캐시 (P4)
    cache_learning: bool = True      # 동적 학습 on/off 스위치
    cache_max_dynamic: int = 200     # 동적 학습 상한(초과 시 LRU 정리)

    # STT
    whisper_model: str = "base"      # tiny / base / small / medium
    whisper_language: str = "ko"

    # TTS
    tts_voice: str = "ko-KR-SunHiNeural"   # 자연스러운 한국어 여성 음성

    # ── 🔊 오프라인 TTS (계획 2-5) ─────────────────────────────────
    #
    # 🚨 **끊기면 «명령이 반만 되는» 게 아니라 «말도 못 했다».** `edge-tts` 는
    #   Microsoft 서버를 타므로 망이 없으면 `b""` 를 돌려줬다 — 화면에는 글이 뜨지만
    #   **아무 소리도 안 난다.** 음성 비서에서 이건 «조금 나빠지는 것»이 아니다.
    #
    # 🔑 **로컬 엔진은 이미 이 PC 에 있다** — Windows 내장 SAPI 의 한국어 목소리
    #   (Microsoft Heami). 새로 깔 것도, 내려받을 모델도 없다(2026-09-24 확인).
    #   ⚠️ 품질은 edge-tts(신경망)보다 낮다. 그래서 **기본은 auto** 다 —
    #     망이 되면 좋은 쪽, 끊기면 나는 쪽. STT 의 google→whisper 와 같은 모양이다.
    #
    #: auto = 온라인이면 edge, 실패·오프라인이면 로컬 | edge = 항상 edge | local = 항상 로컬
    tts_engine: str = "auto"
    #: 로컬(SAPI) 목소리. 비워 두면 **한국어 목소리를 자동으로 고른다.**
    #  이름 일부만 적어도 된다(예: "Heami").
    tts_local_voice: str = ""

    # 웨이크워드 — 사용자가 직접 정한다
    # 쉼표로 구분. 비워두면 services/wakeword.py 의 기본값("플루이즈" 계열)을 쓴다.
    # 예: WAKE_WORDS=플루이즈,헤이 플루이즈,pluiz
    wake_words: str = ""
    wake_word_enabled: bool = True

    # ── 말 거는 단축키 (2026-10-02) ───────────────────────────────
    # 🔑 **호출어를 끄지 않고 둘 다 쓴다.** 전시장처럼 「남의 말소리」가 많은 자리에서는
    #   호출어의 헛깨어남을 임계로 못 죽인다 — 버튼·단축키는 그게 **구조적으로 0** 이다.
    # ⚠️ 기본값을 여기 **한 곳에만** 둔다. `main.js` 와 UI 가 각자 기본값을 들고 있으면
    #   «설정은 바뀌었는데 실제로 듣는 키는 그대로»가 된다(BL-13 이 데인 모양).
    # 📌 Electron accelerator 문법이다 — `Alt+Space` · `Ctrl+Shift+P` 처럼 쓴다.
    # 🚨 **고를 수 있는 것을 목록으로 묶는다** (2026-10-02 실기).
    #
    #   자유 입력으로 두니 `Ctrl+C` 가 그대로 등록됐다. 그러면 앱이 떠 있는 동안
    #   **온 시스템에서 복사가 가로채인다.**
    #
    # 🔑 **«이미 쓰이는 키인가»는 알아낼 수 없다.** `Ctrl+C` 는 전역 단축키가 아니라
    #   앱 내부 단축키라 `globalShortcut.register()` 가 **성공한다.** Electron 이
    #   «남이 쓰는 중»을 알려 줄 길이 없다 — **탐지로 푸는 문제가 아니다.**
    #   그래서 안전한 것만 고르게 한다. 🔒 서버가 목록 밖을 **거부**하므로 UI 를
    #   우회해도 못 들어온다 — UI 만 막으면 또 샌다(BL-27·BL-50 이 세 번 치른 값).
    #
    # ⚠️ 목록의 주인도 여기다. UI 가 자기 목록을 들고 있으면 둘이 어긋난다.
    hotkey_choices: ClassVar[list[str]] = [
        "Ctrl+Alt+Space",
        "Ctrl+Alt+P",
        "Ctrl+Alt+V",
        "Ctrl+Shift+Space",
        "Alt+Shift+P",
        "Ctrl+Alt+Enter",
        # ⚠️ Windows 의 **창 시스템 메뉴**가 이 키다. 쓸 수는 있지만 겹친다 —
        #    UI 가 그렇게 표시하고, 그래서 **기본값에서 뺐다**(실기에서 걸렸다).
        "Alt+Space",
    ]

    # 📌 Electron accelerator 문법. 🔒 기본값은 반드시 위 목록 안의 것이어야 한다.
    hotkey: str = "Ctrl+Alt+Space"
    # 인식 튜닝 — 마이크/환경마다 달라서 코드 수정 없이 조절할 수 있게 뺐다
    wakeword_model: str = "base"          # tiny / base. ⚠️ base가 오히려 **5배 빠르다** —
                                          # tiny는 환각으로 수백 토큰을 뱉느라 시간을 다 쓴다
                                          # (2026-09-02 실측: tiny 61초 vs base 12.9초, 같은 오디오)
    wakeword_energy: float = 0.008        # 무음 스킵 임계. 낮출수록 작은 소리도 처리
                                          # (기본 0.015는 조용한 마이크에서 발화를 버렸다)
    # 전용 KWS 모델 (2026-09-08) — `services/wakeword_model.npz`가 있으면 이걸로 간다.
    # Whisper 경로는 지우지 않았다: 모델이 없거나 로드에 실패하면 자동으로 되돌아간다.
    wakeword_backend: str = "auto"        # auto | model | whisper ("whisper"로 강제 복귀 가능)
    # ⚠️ 에너지 관문이 백엔드마다 다르다 — **추론 비용이 24배 차이나기 때문이다.**
    #   `wakeword_energy`(0.008)는 Whisper 시절 값이다. 한 번 판단에 700ms가 들어서
    #   아무 소리에나 돌릴 수 없었다. 전용 모델은 **28.7ms**라 그 방어가 필요 없다.
    #   2026-09-08 실기에서 이게 드러났다: 사용자 마이크가 0.002~0.006으로 들어오는데
    #   관문이 0.008이라 **발화가 모델에 도달조차 못 했다.** 통과한 2번은 둘 다
    #   prob 1.000 · 0.893으로 성공했다 — 모델이 아니라 **관문이 문제였다.**
    #   (2초 창 안의 1초 발화는 나머지 침묵이 평균을 깎아 실제보다 작게 측정된다)
    wakeword_energy_model: float = 0.0015 # 모델 백엔드용. 순수 무음(≈0.0009)만 거른다
    # 🔑 **실측으로 고른 운용점이다** (2026-10-01). 올리면 오탐↓ 놓침↑.
    #   놓침은 **처음 보는 화자 4명**(호출 79회) 기준이고 — 전시회 관람객이 그 조건이다 —
    #   오탐은 **이 노트북 마이크로 받은 20분**(학습에 안 쓴 것) 실측이다.
    #
    #     연속 2 · 0.80 → 오탐 15회/시간 · 놓침 15.2%   ← 이 값
    #     연속 2 · 0.90 → 오탐  9회/시간 · 놓침 20.3%
    #     연속 3 · 0.80 → 오탐  0회/시간 · 놓침 36.7%
    #
    # 🚨 **2026-09-28 에 적었던 0.62 는 틀린 자 위에서 고른 값이었다.** 그때 오탐을
    #   「대선토론 1.94시간」으로 쟀는데, 그건 방송 마이크로 잡은 남의 목소리다.
    #   같은 모델을 실제 마이크 소리로 재니 25회/시간이 아니라 **264회/시간**이었다.
    #   뿌리는 **학습 창이 뜨는 세기(0.006)가 런타임 관문(0.0015)보다 네 배 높아서**
    #   실제로 듣는 소리의 3분의 2를 모델이 거의 안 보고 자란 것이었다.
    #   → docs/research/2026-10-01_웨이크워드_오탐_진단.md
    #
    # 🚨 전시회 목표(오탐 ≤1회/시간 · 놓침 ≤10%)에는 **아직 못 간다.**
    wakeword_threshold: float = 0.80
    # 🔑 **연속 몇 창이 임계를 넘어야 깨우나.** 이번 라운드에서 가장 큰 지렛대였다.
    #   창이 2초짜리고 0.6초마다 뜨므로 사람이 부르면 여러 창에 걸쳐 들어가는데,
    #   스치는 잡음·말소리는 한 창만 건드리기 쉽다. 같은 모델·같은 확률을
    #   **어떻게 읽을지**만 바꾸는 것이라 계산 비용이 0 이다.
    #
    #   실측(20분 소크 · 처음 보는 화자 79회 호출):
    #       연속 1 · 0.62 →  264회/시간 · 놓침 12.7%   ← 2026-09-30 까지
    #       연속 2 · 0.80 →   15회/시간 · 놓침 15.2%   ← 지금 (헛깨어남 17.6배 ↓)
    #
    # 🚨 **공짜가 아닌 것 하나** — 0.6초 늦게 깨운다. 더 올리면 더 늦어진다.
    wakeword_consecutive: int = 2
    # ── 🗣 발화 종료를 「말인지」로도 본다 (M10 · 2026-10-01) ──────────
    #
    # 🚨 **크기로는 둘 다 못 잡는다는 것이 실측으로 닫혔다.** 자동 볼륨 조절을
    #   켜면 음악이 안 끝나고(30초 꽉 채움), 끄면 2m 목소리가 0.0068 로 들어와
    #   아예 안 들린다. 임계를 어디 두든 하나는 깨진다.
    #
    # 🔑 같은 자료를 말 판정기로 재면 갈린다 — **음악 RMS 0.0026(가장 큼)인데
    #   말 확률 0.000**, 사람이 말할 땐 0.98 이다. 크기가 음악을 말보다 위로
    #   매기던 것이 결함의 전부였다.
    #
    # 🔒 **끄면 지금과 글자 그대로 같아진다.** 크기 조건은 그대로 두고
    #   「끝낼 수 있는 길」을 하나 더 놓는 것뿐이다(OR). → design/M10_발화종료_말판정.md
    vad_speech_enabled: bool = True

    # ── 🚩 신고 수신기 (2026-10-03) ──────────────────────────────────
    #
    # 🚨 **여기에 있어야 `.env` 가 읽힌다.** `os.environ` 만 보면 안 된다 —
    #   이 프로젝트의 `.env` 는 pydantic 이 **설정 객체로만** 읽고
    #   `os.environ` 에는 **안 넣는다**(2026-10-03 실측으로 확인). 그래서
    #   처음엔 팀원이 `.env` 에 적어도 **조용히 안 보내고 있었다.**
    #
    # 🔒 비어 있으면 아무것도 밖으로 안 나간다. 기본이 «안 보냄» 인 것이 핵심이다.
    # → feedback-web/README.md
    feedback_endpoint: str = ""
    feedback_key: str = ""

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
