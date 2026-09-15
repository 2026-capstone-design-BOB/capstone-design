"""
STT 서비스 - 하이브리드 (Google STT + faster-whisper 오프라인 폴백)

온라인  → Google STT (recognize_google, 비공식 무료, 키 불필요)
오프라인 → faster-whisper (로컬 실행, API 불필요)

네트워크 상태는 10초 캐싱으로 매 요청마다 체크 오버헤드 방지.
Google STT 실패(RequestError, UnknownValueError 등) 시 자동으로 Whisper 폴백.
서버 시작 시 Whisper를 백그라운드에서 미리 로드해 폴백 지연 최소화.
"""

import os
import socket
import logging
import tempfile
import threading
import time

log = logging.getLogger("pluiz.stt")

from config.settings import get_settings


# ── 네트워크 상태 감지 ───────────────────────────────────────────────

_NETWORK_HOST = "www.google.com"
_NETWORK_PORT = 443
_NETWORK_TIMEOUT = 2      # 초
_NETWORK_CACHE_TTL = 10   # 초 — 캐싱 주기

_network_cache: dict = {"online": None, "checked_at": 0.0}
_network_lock = threading.Lock()


def _is_online() -> bool:
    """Google 서버 TCP 연결로 네트워크 상태 확인. TTL 내 결과 캐싱."""
    with _network_lock:
        now = time.monotonic()
        if (
            _network_cache["online"] is not None
            and now - _network_cache["checked_at"] < _NETWORK_CACHE_TTL
        ):
            return _network_cache["online"]

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(_NETWORK_TIMEOUT)
            s.connect((_NETWORK_HOST, _NETWORK_PORT))
            s.close()
            online = True
        except OSError:
            online = False

        _network_cache["online"] = online
        _network_cache["checked_at"] = time.monotonic()
        return online


# ── STT 후처리 교정 딕셔너리 ─────────────────────────────────────────
# STT 오인식 패턴 → 올바른 단어 교정 (순서대로 적용)

_CORRECTIONS = [
    ("세 폴더",   "새 폴더"),
    ("세폴더",    "새폴더"),
    ("볼류",      "볼륨"),
    ("벼륨",      "볼륨"),
    ("보륨",      "볼륨"),
    ("장도",      "정도"),
    ("쟁도",      "정도"),
    ("채소와",    "최소화"),
    ("채소화",    "최소화"),
    ("채대화",    "최대화"),
    ("유트브",    "유튜브"),
    ("유투브",    "유튜브"),
    ("유튜 브",   "유튜브"),
    ("메모 장",   "메모장"),
    ("계산 기",   "계산기"),
    ("카카 오",   "카카오"),
    ("바탕 화면", "바탕화면"),
    ("다운 로드", "다운로드"),
    ("스크린 샷", "스크린샷"),
    ("최대 화",   "최대화"),
    ("최소 화",   "최소화"),
    ("검색 해줘", "검색해줘"),
    ("실행 해줘", "실행해줘"),
    ("열어 줘",   "열어줘"),
    ("만들어 줘", "만들어줘"),
    ("설정 해줘", "설정해줘"),
    ("알려 줘",   "알려줘"),
    ("찾아 줘",   "찾아줘"),
    ("보여 줘",   "보여줘"),
    ("내려 줘",   "내려줘"),
    ("올려 줘",   "올려줘"),
]


def _postprocess(text: str) -> str:
    """STT 결과에서 빈번한 오인식 패턴 교정."""
    for wrong, correct in _CORRECTIONS:
        text = text.replace(wrong, correct)
    return text.strip()


# ── Whisper initial_prompt (도메인 힌트) ──────────────────────────────
# 자주 사용하는 명령어를 힌트로 제공해 인식률 향상

_WHISPER_PROMPT = (
    "볼륨 메모장 계산기 유튜브 크롬 엣지 카카오톡 탐색기 "
    "바탕화면 다운로드 문서 폴더 파일 스크린샷 "
    "최대화 최소화 검색 실행 종료 설정 열어줘 켜줘 닫아줘 "
    "만들어줘 찾아줘 올려줘 내려줘 음소거 밝기"
)

# ── 프롬프트 반추 검사 (BL-53) ───────────────────────────────────────

# 반추로 인정할 최소 어절 수.
#
# 2어절까지는 사람이 실제로 말할 수 있다("메모장 계산기"). 3어절 연속은 아니다 —
# 프롬프트의 3어절 조각은 전부 "볼륨 메모장 계산기" · "열어줘 켜줘 닫아줘" ·
# "올려줘 내려줘 음소거" 같은 **어휘 목록의 토막**이라 발화로 성립하지 않는다.
_ECHO_MIN_WORDS = 3

# 어절을 가르는 문장부호. (re를 쓰지 않는다 — 이 모듈은 정규식을 안 들여온다)
_PUNCT_CHARS = frozenset(',.!?~…·"' + "'")


def _norm_for_echo(text) -> str:
    """반추 검사용 정규화 — 문장부호를 지우고 어절 사이를 공백 하나로 고른다."""
    cleaned = "".join(" " if ch in _PUNCT_CHARS else ch for ch in str(text or ""))
    return " ".join(cleaned.split())


_ECHO_HAYSTACK = _norm_for_echo(_WHISPER_PROMPT)


def is_prompt_echo(text) -> bool:
    """Whisper가 **우리가 준 initial_prompt를 그대로 되뱉었는가**. (BL-53)

    🚨 **이것이 BL-53의 진짜 원인이다.** 2026-09-14 2차 리허설에서 사용자가
    승인 질문("a.txt를 정말 삭제할까요?")에 "그래"라고 답했는데 49자가 올라왔다:

        '크롬 엣지 카카오톡 탐색기 바탕화면 다운로드 문서 폴더 파일 스크린샷 최대화 최소화 검색'

    **랜덤 환각이 아니다** — `_WHISPER_PROMPT` 108자의 **15번째 글자부터 잘라낸
    연속 조각**이고 한 글자도 다르지 않다. `initial_prompt`는 디코더를 조건화하는데,
    알아들을 게 없는 오디오가 들어오면 디코더가 그 프롬프트를 **그냥 이어 쓴다.**
    google STT가 먼저 실패했다는 것이 정확히 그 상황("알아들을 게 없음")이다.

    ⚠️ 우리 프롬프트가 **문장이 아니라 단어 나열**이라 «끝날 이유»가 없어 특히
    취약하다. 문장 꼴로 바꾸면 발생 확률 자체가 내려가지만 **모든 음성 명령의
    인식에 영향**을 주므로 시연 뒤로 미뤘다 → BACKLOG BL-53.

    🔑 **그물이 여기 있어야 하는 이유**: 이 텍스트가 일단 만들어지면 그 뒤는
    전부 정상 경로다. 승인 대기 중이었다면 «다른 명령»으로 읽혀 **삭제가 조용히
    취소된다.** 애초에 만들지 않는 것이 가장 싸고 확실하다.

    🚨 **반추된 프롬프트는 반드시 명령형 어미로 끝난다** — 프롬프트 꼬리가
    "… 최소화 **검색** 실행 종료 …"이고 `core/graph.py`의 `_COMMAND_TAIL_RE`에도
    `검색|실행|종료`가 있다. 둘 다 «PC 제어 어휘»에서 뽑은 목록이라 **우연히 뚫린
    것이 아니라 구조적으로 뚫리게 돼 있었다.** 그래서 graph 쪽 문지기(2층)만으로는
    부족하다 — 같은 뿌리를 공유하는 방어는 같이 무너진다.
    """
    norm = _norm_for_echo(text)
    if not norm:
        return False
    if len(norm.split(" ")) < _ECHO_MIN_WORDS:
        return False
    return norm in _ECHO_HAYSTACK


# ── STT 서비스 ───────────────────────────────────────────────────────

class STTService:
    def __init__(self):
        settings = get_settings()
        self.model_size = settings.whisper_model
        self.language = settings.whisper_language

        self._whisper_model = None
        self._whisper_lock = threading.Lock()

        # 서버 시작 시 Whisper 백그라운드 프리로드 (오프라인 폴백 지연 방지)
        threading.Thread(
            target=self._preload_whisper, daemon=True, name="WhisperLoader"
        ).start()

    # ── Whisper 관리 ────────────────────────────────────────────────

    def _preload_whisper(self):
        try:
            self._get_whisper()
            print("[STT] Whisper 사전 로드 완료")
        except Exception as e:
            print(f"[STT] Whisper 사전 로드 실패: {e}")

    def _get_whisper(self):
        """faster-whisper 모델 lazy load (스레드 안전)."""
        with self._whisper_lock:
            if self._whisper_model is None:
                from faster_whisper import WhisperModel
                print(f"[STT] Whisper 모델 로드 중: {self.model_size}")
                self._whisper_model = WhisperModel(
                    self.model_size, device="cpu", compute_type="int8"
                )
                print(f"[STT] Whisper 모델 로드 완료: {self.model_size}")
            return self._whisper_model

    # ── 공개 API ────────────────────────────────────────────────────

    def transcribe_bytes(self, audio_bytes: bytes) -> str:
        """webm 바이트 → 텍스트. 온라인 시 Google STT, 오프라인 시 faster-whisper."""
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            webm_path = f.name

        # 🚨 2026-09-09 — 여기는 `print`만 하고 있어서 **로그 파일에 아무것도 안 남았다.**
        #   사용자가 *"음성 입력을 이해 못하겠다고 뜬다"* 고 했을 때 `logs/pluiz.log`에
        #   STT 줄이 한 줄도 없어 **원인을 좁힐 수가 없었다.** 콘솔은 서버를 띄운
        #   창에만 있고 그 창은 대개 닫혀 있다. 진단은 파일에 남아야 한다.
        size = len(audio_bytes)
        log.info("[STT] 인식 시작 | %d bytes | %s", size,
                 "google" if _is_online() else "whisper(오프라인)")
        if size < 2000:
            # 빈 녹음은 STT가 아니라 **마이크·녹음 쪽** 문제다. 갈라서 남긴다.
            log.warning("[STT] 오디오가 너무 짧다(%d bytes) — 녹음이 안 됐을 수 있다", size)

        try:
            if _is_online():
                result = self._transcribe_google(webm_path)
                if result is not None:
                    log.info("[STT] google 성공 | %d자 | %r", len(result), result[:40])
                    return _postprocess(result)
                print("[STT] Google STT 실패 → Whisper 폴백")
                log.info("[STT] google 실패 → whisper 폴백")
            else:
                print("[STT] 오프라인 → Whisper 사용")

            result = self._transcribe_whisper(webm_path)

            # 🚨 **BL-53 — 우리가 준 initial_prompt를 되뱉었으면 버린다.**
            #   그냥 두면 이 텍스트가 «사용자가 한 말»로 그대로 흘러간다. 2차
            #   리허설에서는 승인 대기 중이라 «다른 명령»으로 읽혀 **삭제가 조용히
            #   취소됐다.** 빈 결과로 만들면 `/voice`가 «인식하지 못했습니다»로
            #   끝내고 **승인 대기는 살아 있어** 한 번 더 말하면 이어진다.
            if is_prompt_echo(result):
                log.warning("[STT] 프롬프트 반추 폐기 | %d자 | %r — "
                            "알아들을 게 없는 오디오였다", len(result), result[:60])
                return ""

            if not (result or "").strip():
                log.warning("[STT] whisper도 빈 결과 — 사용자에게 «인식하지 못했다»가 나간다")
            else:
                log.info("[STT] whisper 성공 | %d자 | %r", len(result), result[:40])
            return _postprocess(result)

        finally:
            try:
                os.unlink(webm_path)
            except Exception:
                pass

    def get_status(self) -> dict:
        """현재 STT 상태 반환 (UI 표시용)."""
        online = _is_online()
        return {
            "online":         online,
            "active_engine":  "google" if online else "whisper",
            "whisper_loaded": self._whisper_model is not None,
            "whisper_model":  self.model_size,
        }

    # ── 내부 로직 ───────────────────────────────────────────────────

    def _transcribe_google(self, webm_path: str) -> str | None:
        """
        Google STT (speech_recognition.recognize_google).
        성공 시 텍스트, 실패 시 None (→ Whisper 폴백 트리거).
        오디오 변환은 PyAV (faster-whisper 의존성)로 처리 — ffmpeg 실행 파일 불필요.
        """
        try:
            import av
            import speech_recognition as sr

            # PyAV로 webm → 16kHz mono s16 PCM 변환 (ffmpeg 실행 파일 불필요)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            pcm_chunks: list[bytes] = []

            with av.open(webm_path) as container:
                for frame in container.decode(audio=0):
                    for resampled in resampler.resample(frame):
                        pcm_chunks.append(bytes(resampled.planes[0]))

            # 남은 버퍼 flush
            for resampled in resampler.resample(None):
                pcm_chunks.append(bytes(resampled.planes[0]))

            raw_data = b"".join(pcm_chunks)
            if not raw_data:
                print("[STT] Google STT: 변환된 오디오 데이터 없음")
                return None

            audio_data = sr.AudioData(raw_data, sample_rate=16000, sample_width=2)
            recognizer = sr.Recognizer()
            text = recognizer.recognize_google(audio_data, language="ko-KR")
            print(f"[STT] 인식 결과 (Google): {text!r}")

            # 성공 → 온라인 캐시 즉시 갱신
            with _network_lock:
                _network_cache["online"] = True
                _network_cache["checked_at"] = time.monotonic()

            return text

        except Exception as e:
            try:
                import speech_recognition as sr
                if isinstance(e, sr.UnknownValueError):
                    print("[STT] Google STT: 음성 불명확 → Whisper 폴백")
                elif isinstance(e, sr.RequestError):
                    print(f"[STT] Google STT 네트워크 오류 → Whisper 폴백: {e}")
                    with _network_lock:
                        _network_cache["online"] = False
                        _network_cache["checked_at"] = time.monotonic()
                else:
                    print(f"[STT] Google STT 오류 ({type(e).__name__}) → Whisper 폴백: {e}")
            except ImportError:
                print(f"[STT] Google STT 오류 → Whisper 폴백: {e}")
            return None

    def _transcribe_whisper(self, webm_path: str) -> str:
        """faster-whisper로 변환. initial_prompt로 한국어 도메인 힌트 제공."""
        try:
            model = self._get_whisper()
            segments, _ = model.transcribe(
                webm_path,
                language=self.language,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                initial_prompt=_WHISPER_PROMPT,
            )
            segs = list(segments)
            text = " ".join(seg.text.strip() for seg in segs)

            # 🔬 **BL-53 3층 계측 — 아직 자르지 않는다.**
            #   faster-whisper는 세그먼트마다 `no_speech_prob`(무음일 확률)과
            #   `avg_logprob`(디코딩 확신)을 주는데 지금까지 **통째로 버리고
            #   있었다.** 환각은 이 둘이 나쁠 때 나오므로 여기가 «다음 그물»의
            #   자리다. 다만 **임계값을 실측 없이 정하면 추측**이고, 이 저장소는
            #   BL-23에서 정확히 그걸로 헛발을 짚었다(「임계값으로는 못 고친다」).
            #   그래서 BL-40 때처럼 **먼저 재고, 3차 리허설 로그로 임계를 정한다.**
            if segs:
                ns = max(float(getattr(s, "no_speech_prob", 0.0) or 0.0) for s in segs)
                lp = min(float(getattr(s, "avg_logprob", 0.0) or 0.0) for s in segs)
                log.info("[STT] whisper 신뢰도 | 세그먼트 %d개 | no_speech=%.3f | "
                         "avg_logprob=%.3f | %d자", len(segs), ns, lp, len(text.strip()))

            print(f"[STT] 인식 결과 (Whisper): {text!r}")
            return text.strip()
        except Exception as e:
            print(f"[STT] Whisper 오류: {e}")
            return ""


# ── 싱글턴 ───────────────────────────────────────────────────────────

_stt_instance: STTService | None = None


def get_stt() -> STTService:
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = STTService()
    return _stt_instance
