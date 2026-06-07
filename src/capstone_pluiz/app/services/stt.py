# app/services/stt.py
import speech_recognition as sr
import os
import io
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

class STTService:
    def __init__(self, mode: str = "google"):
        """
        mode: "google"  = Google STT (온라인, 무료, API 키 불필요) ← 기본값
              "whisper" = faster-whisper (오프라인)
              "openai"  = OpenAI Whisper API (유료) ← 추후 활성화
        """
        self.mode = mode
        self.recognizer = sr.Recognizer()

        if mode in ("google", "whisper"):
            self.microphone = sr.Microphone()

        if mode == "whisper":
            self._init_faster_whisper()
        # elif mode == "openai":       # OpenAI API 키 필요 — 추후 활성화
        #     self._init_openai_whisper()

        print(f"[STT] 초기화 완료 (모드: {mode})")

    # ── 초기화 ──────────────────────────────────────────────
    def _init_faster_whisper(self):
        from faster_whisper import WhisperModel
        self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

    # def _init_openai_whisper(self):   # 추후 활성화
    #     from openai import OpenAI
    #     self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # ── CLI용: 마이크에서 직접 듣기 ─────────────────────────
    def listen_and_transcribe(self) -> str:
        print("[STT] 말씀하세요...")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
            except sr.WaitTimeoutError:
                print("[STT] 음성 감지 안됨")
                return ""
        return self._transcribe(audio)

    def _transcribe(self, audio) -> str:
        if self.mode == "google":
            return self._transcribe_google(audio)
        else:
            return self._transcribe_faster_whisper(audio)

    def _transcribe_google(self, audio) -> str:
        try:
            text = self.recognizer.recognize_google(audio, language="ko-KR")
            print(f"[STT] 인식 결과: {text}")
            return text
        except sr.UnknownValueError:
            print("[STT] 음성 인식 실패")
            return ""
        except sr.RequestError as e:
            print(f"[STT] Google STT 오류: {e}")
            return ""

    def _transcribe_faster_whisper(self, audio) -> str:
        try:
            audio_data = io.BytesIO(audio.get_wav_data())
            segments, _ = self.whisper_model.transcribe(audio_data, language="ko")
            text = "".join([s.text for s in segments]).strip()
            print(f"[STT] 인식 결과: {text}")
            return text
        except Exception as e:
            print(f"[STT] Whisper 오류: {e}")
            return ""

    # ── 웹용: 업로드된 오디오 바이트 변환 ───────────────────
    def transcribe_audio_bytes(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        """
        Electron UI에서 녹음한 webm 파일을 텍스트로 변환.
        google 모드: pydub으로 webm → wav 변환 후 Google STT 사용
        """
        # --- OpenAI 모드 (추후 활성화) ---
        # if self.mode == "openai":
        #     return self._transcribe_bytes_openai(audio_bytes, filename)

        return self._transcribe_bytes_google(audio_bytes)

    def _transcribe_bytes_google(self, audio_bytes: bytes) -> str:
        """webm → wav 변환 후 Google STT. pydub + ffmpeg 필요."""
        try:
            from pydub import AudioSegment
            audio_seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="webm")
            wav_io = io.BytesIO()
            audio_seg.export(wav_io, format="wav")
            wav_io.seek(0)
            audio = sr.AudioData(wav_io.read(), audio_seg.frame_rate, 2)
            return self._transcribe_google(audio)
        except Exception as e:
            print(f"[STT-Google] webm 변환 오류: {e}")
            print("[STT-Google] ffmpeg 설치 여부를 확인해주세요.")
            return ""

    # --- OpenAI 변환 (추후 활성화) ---
    # def _transcribe_bytes_openai(self, audio_bytes: bytes, filename: str) -> str:
    #     try:
    #         audio_file = io.BytesIO(audio_bytes)
    #         audio_file.name = filename
    #         transcript = self.openai_client.audio.transcriptions.create(
    #             model="whisper-1", file=audio_file, language="ko",
    #         )
    #         text = transcript.text.strip()
    #         print(f"[STT-OpenAI] 인식 결과: {text}")
    #         return text
    #     except Exception as e:
    #         print(f"[STT-OpenAI] 오류: {e}")
    #         return ""