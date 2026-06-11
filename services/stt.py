"""
STT 서비스 - faster-whisper 기반 로컬 음성 인식
API 키 불필요, 로컬에서 실행
"""

import io
import tempfile
import os
from config.settings import get_settings


class STTService:
    def __init__(self):
        settings = get_settings()
        self.model_size = settings.whisper_model
        self.language = settings.whisper_language
        self._model = None  # lazy load

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            print(f"[STT] 모델 로드 중: {self.model_size}")
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8"  # CPU에서 빠른 추론
            )
            print("[STT] 모델 로드 완료")
        return self._model

    def transcribe_file(self, audio_path: str) -> str:
        """오디오 파일 → 텍스트."""
        model = self._load_model()
        segments, info = model.transcribe(
            audio_path,
            language=self.language,
            beam_size=5,
            vad_filter=True,          # 무음 구간 자동 제거
            vad_parameters={"min_silence_duration_ms": 500},
        )
        text = " ".join(seg.text.strip() for seg in segments)
        print(f"[STT] 인식 결과: {text!r}")
        return text.strip()

    def transcribe_bytes(self, audio_bytes: bytes) -> str:
        """바이트 오디오 데이터 → 텍스트 (WebSocket/API용)."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            return self.transcribe_file(tmp_path)
        finally:
            os.unlink(tmp_path)


# 싱글턴
_stt_instance: STTService | None = None

def get_stt() -> STTService:
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = STTService()
    return _stt_instance
