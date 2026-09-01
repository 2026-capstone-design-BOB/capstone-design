"""
Wake Word Service
-----------------
Continuously transcribes short audio chunks with faster-whisper.
Outputs "WAKE" to stdout when wake word detected.
Electron reads stdout and opens the window.
"""

import sys
import os
import io
import threading
import time
import re

# Fix Windows console encoding
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    print("[wakeword] ERROR: sounddevice not installed. Run: pip install sounddevice numpy", flush=True)
    sys.exit(1)

from faster_whisper import WhisperModel

# ── Config ─────────────────────────────────────────────────────
SAMPLE_RATE     = 16000
CHUNK_SECONDS   = 1.0           # 1초 청크
CHUNK_SAMPLES   = int(SAMPLE_RATE * CHUNK_SECONDS)
ENERGY_THRESHOLD = 0.015        # 무음 스킵 임계값 (높일수록 조용한 환경에서만 반응)
COOLDOWN_SEC    = 2.5           # 연속 감지 방지 딜레이

# ── Wake words ─────────────────────────────────────────────────
# "소윤아" — 일반 한국어 이름이라 Whisper tiny 인식률이 훨씬 높음
WAKE_WORDS = [
    # 한국어 기본
    "소윤아", "소윤이", "소윤",
    "야 소윤", "야소윤",
    # 영어 음성 표기 (Whisper tiny가 영어로 들을 때)
    "soyun", "soyuna", "soyoona", "so yun", "so yoon",
    "sooyun", "sooyoon", "soyoon",
    # 혹시 모를 오인식
    "소유나", "소유니", "소윤나",
]

# 쉼표만 있거나 너무 짧은 결과 무시
NOISE_PATTERNS = re.compile(r'^[,.\s\-_]+$')


def normalize(text: str) -> str:
    return text.lower().strip().replace(' ', '')


def is_wake(text: str) -> bool:
    if not text or NOISE_PATTERNS.match(text):
        return False
    norm = normalize(text)
    for w in WAKE_WORDS:
        if normalize(w) in norm:
            return True
    return False


def rms(audio: "np.ndarray") -> float:
    return float(np.sqrt(np.mean(audio ** 2)))


def main():
    print("[wakeword] Loading model...", file=sys.stderr, flush=True)

    model = WhisperModel("tiny", device="cpu", compute_type="int8")

    print("[wakeword] 준비 완료. 감지 중...", file=sys.stderr, flush=True)

    last_wake = 0.0
    buf = np.zeros(CHUNK_SAMPLES, dtype=np.float32)
    buf_pos = 0

    def on_audio(indata, frames, time_info, status):
        nonlocal buf_pos, last_wake

        audio = indata[:, 0].astype(np.float32) if indata.ndim > 1 else indata.flatten().astype(np.float32)
        space = CHUNK_SAMPLES - buf_pos

        if len(audio) >= space:
            buf[buf_pos:] = audio[:space]
            chunk = buf.copy()
            # BUG-12: 버퍼를 채우고 남은 잔여 샘플을 다음 버퍼 시작으로 이월
            remainder = audio[space:]
            buf_pos = 0
            if len(remainder) > 0:
                buf[:len(remainder)] = remainder
                buf_pos = len(remainder)

            energy = rms(chunk)
            if energy < ENERGY_THRESHOLD:
                return  # 무음 스킵

            now = time.time()
            if now - last_wake < COOLDOWN_SEC:
                return  # 쿨다운 중

            threading.Thread(
                target=_transcribe,
                args=(model, chunk.copy(), now),
                daemon=True,
            ).start()
        else:
            buf[buf_pos:buf_pos + len(audio)] = audio
            buf_pos += len(audio)

    def _transcribe(model, chunk, ts):
        nonlocal last_wake
        try:
            segments, _ = model.transcribe(
                chunk,
                language="ko",
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 200},
                condition_on_previous_text=False,
            )
            text = " ".join(s.text for s in segments).strip()

            if not text or NOISE_PATTERNS.match(text):
                return

            print(f"[wakeword] heard: {text!r}", file=sys.stderr, flush=True)

            if is_wake(text):
                last_wake = ts
                print("WAKE", flush=True)
                print("[wakeword] *** WAKE WORD DETECTED ***", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[wakeword] transcribe error: {e}", file=sys.stderr, flush=True)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=512,
            callback=on_audio,
        ):
            print("[wakeword] Microphone stream started.", file=sys.stderr, flush=True)
            while True:
                time.sleep(0.1)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[wakeword] Stream error: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
