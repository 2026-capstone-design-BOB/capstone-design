# app/services/stt.py
# 오프라인-faster-whisper | 로컬마이크-GoogleSTT | 웹업로드-OpenAI Whisper API
import speech_recognition as sr
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

class STTService:
    def __init__(self, mode: str = "google"):
        """
        mode: "google"  = Google STT (온라인, CLI용)
              "whisper" = faster-whisper (오프라인, CLI용)
              "openai"  = OpenAI Whisper API (웹 업로드용)
        """
        self.mode = mode
        self.recognizer = sr.Recognizer()

        if mode in ("google", "whisper"):
            self.microphone = sr.Microphone()

        if mode == "whisper":
            self._init_faster_whisper()
        elif mode == "openai":
            self._init_openai_whisper()

        print(f"[STT] 초기화 완료 (모드: {mode})")

    # ── 초기화 ──────────────────────────────────────────────
    def _init_faster_whisper(self):
        from faster_whisper import WhisperModel
        self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

    def _init_openai_whisper(self):
        from openai import OpenAI
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # ── CLI용: 마이크에서 직접 듣기 ─────────────────────────
    def listen_and_transcribe(self) -> str:
        """마이크에서 음성 듣고 텍스트로 변환 (CLI 전용)"""
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
            print(f"[STT] Google STT 오류, Whisper로 전환: {e}")
            return self._transcribe_faster_whisper(audio)

    def _transcribe_faster_whisper(self, audio) -> str:
        try:
            import io
            audio_data = io.BytesIO(audio.get_wav_data())
            segments, _ = self.whisper_model.transcribe(audio_data, language="ko")
            text = "".join([s.text for s in segments]).strip()
            print(f"[STT] 인식 결과: {text}")
            return text
        except Exception as e:
            print(f"[STT] Whisper 오류: {e}")
            return ""

    # ── 웹용: 업로드된 오디오 파일/바이트 변환 ───────────────
    def transcribe_audio_bytes(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        """
        웹 브라우저에서 업로드된 오디오 바이트를 텍스트로 변환.
        OpenAI Whisper API 사용 (mode="openai" 필요).
        """
        if self.mode != "openai":
            raise RuntimeError("transcribe_audio_bytes는 mode='openai' 에서만 사용 가능합니다.")
        try:
            import io
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename  # OpenAI SDK가 확장자로 포맷 추론

            transcript = self.openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ko",
            )
            text = transcript.text.strip()
            print(f"[STT-OpenAI] 인식 결과: {text}")
            return text
        except Exception as e:
            print(f"[STT-OpenAI] 오류: {e}")
            return ""