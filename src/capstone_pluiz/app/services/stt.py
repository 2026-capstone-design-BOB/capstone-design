# app/services/stt.py
# 오프라인-faster-whisper , 온라인-GoogleSTT
import speech_recognition as sr
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

class STTService:
    def __init__(self, mode: str = "google"):
        """
        mode: "google" = Google STT (온라인, 빠름)
              "whisper" = faster-whisper (오프라인, 느림)
        """
        self.mode = mode
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        
        if mode == "whisper":
            self._init_whisper()
        
        print(f"[STT] 초기화 완료 (모드: {mode})")
    
    def _init_whisper(self):
        from faster_whisper import WhisperModel
        self.whisper_model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8"
        )
    
    def listen_and_transcribe(self) -> str:
        """마이크에서 음성 듣고 텍스트로 변환"""
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
            return self._transcribe_whisper(audio)
    
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
            return self._transcribe_whisper(audio)
    
    def _transcribe_whisper(self, audio) -> str:
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