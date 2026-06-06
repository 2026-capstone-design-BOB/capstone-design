# app/services/tts.py
import os
import tempfile
from openai import OpenAI

class TTSService:
    def __init__(self, voice: str = "alloy"):
        """
        voice 옵션: alloy, echo, fable, onyx, nova, shimmer
        한국어에는 nova 또는 alloy 추천
        """
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.voice = voice
        print(f"[TTS] 초기화 완료 (voice: {voice})")

    def synthesize(self, text: str) -> bytes:
        """텍스트 → MP3 바이트 반환"""
        try:
            response = self.client.audio.speech.create(
                model="tts-1",
                voice=self.voice,
                input=text,
            )
            return response.content
        except Exception as e:
            print(f"[TTS] 오류: {e}")
            return None

    def synthesize_to_file(self, text: str, output_path: str = None) -> str:
        """텍스트 → MP3 파일로 저장 후 경로 반환"""
        audio_bytes = self.synthesize(text)
        if not audio_bytes:
            return None

        if output_path is None:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            output_path = tmp.name
            tmp.close()

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        print(f"[TTS] 저장 완료: {output_path}")
        return output_path