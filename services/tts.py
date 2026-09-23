"""
TTS 서비스 - edge-tts 기반
Microsoft Edge 엔진 무료 사용, API 키 불필요
"""

import asyncio
import tempfile
import os
import subprocess
from config.settings import get_settings


def _spoken(text: str) -> str:
    """읽을 글만 남긴다. 정제가 통째로 실패하면 **원문을 쓴다** — 침묵보다 낫다.

    ⚠️ 정제 결과가 비면(마커와 경로뿐이었던 응답) 그때도 원문으로 돌아간다.
      «아무 말도 안 하는 것»이 «조금 이상하게 읽는 것»보다 나쁘다.
    """
    try:
        from services.speech_text import to_speech
        cleaned = to_speech(text)
        return cleaned if cleaned.strip() else text
    except Exception as e:                                    # noqa: BLE001
        print(f"[TTS] 정제 실패 — 원문 그대로 읽습니다: {type(e).__name__}: {e}")
        return text


#: 로컬(SAPI) 합성 결과의 형식. edge-tts 는 mp3 를 준다.
MIME_MP3 = "audio/mpeg"
MIME_WAV = "audio/wav"

#: SAPI 파일 스트림 열기 모드 — SSFMCreateForWrite.
_SSFM_CREATE_FOR_WRITE = 3


def local_voices() -> list[str]:
    """이 PC 가 가진 SAPI 목소리 이름들. 못 읽으면 빈 목록.

    🔑 **설정에서 고르게 하려면 먼저 «무엇이 있나»를 말할 수 있어야 한다.**
    """
    try:
        import comtypes.client
        v = comtypes.client.CreateObject("SAPI.SpVoice")
        toks = v.GetVoices()
        return [toks.Item(i).GetDescription() for i in range(toks.Count)]
    except Exception as e:                                    # noqa: BLE001
        print(f"[TTS] 로컬 목소리 목록을 못 읽었습니다: {type(e).__name__}: {e}")
        return []


def _pick_local_voice(voices, want: str):
    """원하는 목소리 토큰을 고른다. 못 고르면 `None`(= 시스템 기본).

    ⚠️ **`want` 가 비면 한국어를 찾는다.** 기본 목소리는 보통 영어라,
      그대로 두면 한국어 문장을 **영어 발음으로 읽는다.**
    """
    want = (want or "").strip().lower()
    fallback = None
    for i in range(voices.Count):
        tok = voices.Item(i)
        desc = tok.GetDescription()
        low = desc.lower()
        if want:
            if want in low:
                return tok, desc
        elif ("korean" in low or "ko-kr" in low) and fallback is None:
            fallback = (tok, desc)
    return fallback if fallback else (None, "")


class TTSService:
    def __init__(self):
        settings = get_settings()
        self.voice = settings.tts_voice
        self.engine = getattr(settings, "tts_engine", "auto")
        self.local_voice = getattr(settings, "tts_local_voice", "")

    async def speak_async(self, text: str):
        """텍스트를 음성으로 변환하여 서버측 스피커로 재생 (비동기).

        BUG-04 수정: 기존 os.startfile()은 비동기로 파일을 열기 때문에
        finally 블록의 os.unlink()가 재생 시작 전에 파일을 삭제하는 문제가 있었음.
        to_bytes_async()로 먼저 bytes를 받은 뒤 블로킹 재생으로 변경.
        """
        audio_bytes, mime = await self.synth_async(text)
        if not audio_bytes:
            return                      # 만들지 못했다. 빈 파일을 재생하지 않는다
        # ⚠️ **확장자를 형식에 맞춘다.** 로컬 폴백은 WAV 인데 `.mp3` 로 쓰면
        #   아래 플레이어들이 열지 못하고 **조용히 실패한다**(재생은 «됐다»고 돌아온다).
        suffix = ".wav" if mime == MIME_WAV else ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            # asyncio.to_thread: 블로킹 재생을 별도 스레드에서 실행 (이벤트 루프 블로킹 방지)
            await asyncio.to_thread(self._play_audio_blocking, tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def speak(self, text: str):
        """동기 래퍼."""
        asyncio.run(self.speak_async(text))

    async def to_bytes_async(self, text: str) -> bytes:
        """텍스트 → MP3 바이트 반환 (클라이언트 전송용).
        오프라인 또는 edge-tts 실패 시 빈 bytes 반환 (TTS 없이 텍스트만 전달).

        🔑 **여기가 모든 음성 경로의 길목이다** — `/voice` · `/ws` · 감시 알림 ·
          `speak_async` 가 전부 이 함수를 지난다. 그래서 «말할 것만 남기는» 정제를
          호출부 네 곳이 아니라 **여기 한 곳**에 건다 (2-2 ⓒ).
          🚨 호출부마다 넣으면 다음 `return` 에서 또 샌다 — 감사 G-13·G-14 가 그 모양이었다.

        ⚠️ **화면 텍스트는 안 바뀐다.** 정제 결과는 오직 TTS 입력이다.
        """
        audio, _mime = await self.synth_async(text)
        return audio

    async def synth_async(self, text: str) -> tuple[bytes, str]:
        """텍스트 → (오디오 바이트, mime). 아무것도 못 만들면 `(b"", "")`.

        🔑 **STT 의 google→whisper 와 같은 모양이다** — 좋은 쪽을 먼저 쓰고,
          안 되면 **로컬로 내려간다.** 다른 점은 이쪽이 더 중요하다는 것뿐이다:
          STT 가 실패하면 «못 알아들었어요»라고 말이라도 하는데,
          TTS 가 실패하면 **아무 말도 안 한다.**

        ⚠️ 형식이 갈린다(edge=mp3 · 로컬=wav). 그래서 바이트만 주지 않고
          **mime 을 같이 준다** — 받는 쪽이 `audio/mpeg` 로 고정돼 있었다.
        """
        spoken = _spoken(text)

        if self.engine != "local":
            audio = await self._synth_edge(spoken)
            if audio:
                return audio, MIME_MP3
            if self.engine == "edge":
                # 사용자가 edge 로 **고정**했다. 말없이 다른 엔진으로 바꾸지 않는다.
                print("[TTS] edge 고정인데 실패했습니다 — 음성 없이 텍스트만 나갑니다")
                return b"", ""
            print("[TTS] edge 실패 → 로컬(SAPI) 로 내려갑니다")

        audio = await asyncio.to_thread(self._synth_local, spoken)
        if audio:
            return audio, MIME_WAV
        return b"", ""

    async def _synth_edge(self, spoken: str) -> bytes:
        """edge-tts(온라인). 실패하면 빈 bytes — 예외를 밖으로 던지지 않는다."""
        import edge_tts
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        try:
            communicate = edge_tts.Communicate(spoken, self.voice)
            await communicate.save(tmp_path)
            with open(tmp_path, "rb") as f:
                return f.read()
        except Exception as e:
            print(f"[TTS] edge 오류 (오프라인 또는 네트워크 문제): {e}")
            return b""
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _synth_local(self, spoken: str) -> bytes:
        """Windows 내장 SAPI 로 합성한 **WAV 바이트**. 실패하면 빈 bytes.

        🔑 **새로 깔 것이 없다.** `comtypes` 는 `pycaw`(볼륨)가 이미 쓰고 있고,
          한국어 목소리(Microsoft Heami)는 Windows 에 들어 있다(2026-09-24 확인).
          그래서 이 폴백은 **부스 PC 에서 «되는지 확인할 것»이 하나도 없다.**

        ⚠️ 품질은 edge-tts(신경망)보다 낮다. 그래도 **침묵보다 낫다** —
          이 파일의 `_spoken()` 이 «아무 말도 안 하는 것이 더 나쁘다»고 적어 둔 것과
          같은 판단이다.
        """
        tmp_path = ""
        try:
            import comtypes.client
            # 🚨 **워커 스레드에서는 이게 없으면 항상 실패한다.**
            #   `asyncio.to_thread` 로 도는데 COM 은 **스레드마다** 초기화해야 한다.
            #   밝기·볼륨이 «서버에서만 못 읽히던» 것과 **똑같은 함정**이라
            #   그때 만들어 둔 함수를 그대로 쓴다(사본 금지 — 감사 G-08).
            from tools.system import ensure_com
            ensure_com()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name

            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            tok, desc = _pick_local_voice(voice.GetVoices(), self.local_voice)
            if tok is not None:
                voice.Voice = tok
            elif self.local_voice:
                # 고른 목소리가 이 PC 에 없다. **조용히 영어로 읽지 않는다.**
                print(f"[TTS] 로컬 목소리 {self.local_voice!r} 를 못 찾았습니다 "
                      f"— 시스템 기본으로 읽습니다")

            stream = comtypes.client.CreateObject("SAPI.SpFileStream")
            stream.Open(tmp_path, _SSFM_CREATE_FOR_WRITE, False)
            voice.AudioOutputStream = stream
            try:
                voice.Speak(spoken)
            finally:
                stream.Close()

            with open(tmp_path, "rb") as f:
                data = f.read()
            if not data:
                print("[TTS] 로컬 합성 결과가 비었습니다")
            elif desc:
                print(f"[TTS] 로컬 합성 | {desc} | {len(data):,} bytes")
            return data
        except Exception as e:                                # noqa: BLE001
            print(f"[TTS] 로컬(SAPI) 오류: {type(e).__name__}: {e}")
            return b""
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _play_audio_blocking(self, path: str):
        """MP3 블로킹 재생. 재생이 완전히 끝날 때까지 대기.

        Windows MediaPlayer COM 객체를 사용해 재생 완료를 감지함.
        실패 시 PowerShell WMPlayer fallback → 마지막으로 os.startfile + sleep.
        """
        abs_path = os.path.abspath(path)
        # BUG-04: PowerShell에서 싱글쿼트 escape는 '' (두 번 쓰기), \'가 아님
        escaped = abs_path.replace("\\", "\\\\").replace("'", "''")

        # Method 1: System.Windows.Media.MediaPlayer (재생 완료 감지 가능)
        try:
            ps = (
                "Add-Type -AssemblyName PresentationCore; "
                f"$m = [System.Windows.Media.MediaPlayer]::new(); "
                f"$m.Open([System.Uri]::new('{escaped}')); "
                "$m.Play(); "
                "Start-Sleep -Milliseconds 500; "
                "while ($m.NaturalDuration.HasTimeSpan -and "
                "       $m.Position -lt $m.NaturalDuration.TimeSpan) "
                "  { Start-Sleep -Milliseconds 100 }; "
                "$m.Stop(); $m.Close()"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True, timeout=30
            )
            if result.returncode == 0:
                return
        except Exception:
            pass

        # Method 2: WMPlayer.OCX COM fallback
        try:
            escaped2 = abs_path.replace("\\", "/")
            ps2 = (
                f"$p = New-Object -ComObject WMPlayer.OCX; "
                f"$m = $p.newMedia('{escaped2}'); "
                "$p.currentMedia = $m; $p.controls.play(); "
                "Start-Sleep -Milliseconds 500; "
                "while ($p.playState -ne 1) { Start-Sleep -Milliseconds 100 }; "
                "$p.controls.stop()"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps2],
                capture_output=True, timeout=30
            )
            if result.returncode == 0:
                return
        except Exception:
            pass

        # Method 3: 최후 fallback — os.startfile + 넉넉한 대기
        try:
            os.startfile(abs_path)
            import time
            time.sleep(5)
        except Exception:
            pass

    def _play_audio(self, path: str):
        """하위 호환용. _play_audio_blocking으로 위임."""
        self._play_audio_blocking(path)


# 싱글턴
_tts_instance: TTSService | None = None

def get_tts() -> TTSService:
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = TTSService()
    return _tts_instance
