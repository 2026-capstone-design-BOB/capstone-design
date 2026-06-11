"""
TTS 서비스 - edge-tts 기반
Microsoft Edge 엔진 무료 사용, API 키 불필요
"""

import asyncio
import tempfile
import os
import subprocess
from config.settings import get_settings


class TTSService:
    def __init__(self):
        settings = get_settings()
        self.voice = settings.tts_voice

    async def speak_async(self, text: str):
        """텍스트를 음성으로 변환하여 재생 (비동기)."""
        import edge_tts

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name

        try:
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(tmp_path)
            self._play_audio(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def speak(self, text: str):
        """동기 래퍼."""
        asyncio.run(self.speak_async(text))

    async def to_bytes_async(self, text: str) -> bytes:
        """텍스트 → MP3 바이트 반환 (스트리밍 전송용)."""
        import edge_tts
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        try:
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(tmp_path)
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _play_audio(self, path: str):
        """OS 기본 플레이어로 오디오 재생."""
        try:
            os.startfile(path)
        except Exception:
            subprocess.Popen(
                ["powershell", "-c", f"(New-Object Media.SoundPlayer '{path}').PlaySync()"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


# 싱글턴
_tts_instance: TTSService | None = None

def get_tts() -> TTSService:
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = TTSService()
    return _tts_instance
