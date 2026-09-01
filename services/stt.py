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
import tempfile
import threading
import time

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

        try:
            if _is_online():
                result = self._transcribe_google(webm_path)
                if result is not None:
                    return _postprocess(result)
                print("[STT] Google STT 실패 → Whisper 폴백")
            else:
                print("[STT] 오프라인 → Whisper 사용")

            result = self._transcribe_whisper(webm_path)
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
            text = " ".join(seg.text.strip() for seg in segments)
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
