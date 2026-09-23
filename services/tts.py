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


class TTSService:
    def __init__(self):
        settings = get_settings()
        self.voice = settings.tts_voice

    async def speak_async(self, text: str):
        """텍스트를 음성으로 변환하여 서버측 스피커로 재생 (비동기).

        BUG-04 수정: 기존 os.startfile()은 비동기로 파일을 열기 때문에
        finally 블록의 os.unlink()가 재생 시작 전에 파일을 삭제하는 문제가 있었음.
        to_bytes_async()로 먼저 bytes를 받은 뒤 블로킹 재생으로 변경.
        """
        audio_bytes = await self.to_bytes_async(text)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
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
        import edge_tts
        spoken = _spoken(text)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        try:
            communicate = edge_tts.Communicate(spoken, self.voice)
            await communicate.save(tmp_path)
            with open(tmp_path, "rb") as f:
                return f.read()
        except Exception as e:
            print(f"[TTS] 오류 (오프라인 또는 네트워크 문제) → 음성 없이 텍스트만 반환: {e}")
            return b""
        finally:
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
