# app/services/tts.py
# OpenAI API 키 필요 — 추후 활성화
# pip install openai 필요

# from openai import OpenAI
# import os
# import tempfile

class TTSService:
    def __init__(self, voice: str = "nova"):
        # self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        # self.voice = voice
        print("[TTS] 비활성화 상태 (OpenAI API 키 필요)")

    def synthesize(self, text: str) -> bytes:
        # OpenAI API 키 필요 — 추후 활성화
        # response = self.client.audio.speech.create(
        #     model="tts-1", voice=self.voice, input=text,
        # )
        # return response.content
        return None

    def synthesize_to_file(self, text: str, output_path: str = None) -> str:
        return None