"""오프라인 TTS — **끊겨도 말은 한다** (계획 2-5 · 2026-09-24)

    python tests/test_tts_offline.py

## 왜 이 스위트가 있나

지금까지 TTS 는 `edge-tts`(Microsoft 서버) 하나였다. 망이 없으면
`to_bytes_async` 가 **`b""` 를 돌려줬고**, 화면에는 글이 뜨지만 **아무 소리도 안 났다.**
음성 비서에서 이건 «조금 나빠지는 것»이 아니다 — [개발_계획](../docs/planning/개발_계획.md)
2-5 가 *"끊기면 명령이 반만 되는 게 아니라 «말도 못 한다»"* 라고 적어 둔 자리다.

🔑 **로컬 엔진은 이미 이 PC 에 있었다.** Windows 내장 SAPI 의 한국어 목소리
(Microsoft Heami). **새로 깔 것도, 내려받을 모델도 없다** — `comtypes` 는
`pycaw`(볼륨)가 이미 쓰고 있다. 계획서가 후보로 적어 둔 Piper 는
새 의존성 + 모델 내려받기가 필요한데, **그 값을 치르지 않고 항목의 핵심을 얻는다.**

## 🚨 양방향으로 박는다

«실패하면 로컬로 내려간다»만 고정하면 **항상 로컬을 쓰는 수정**이 통과한다.
edge 는 신경망이라 품질이 분명히 낫다 — 평소에는 그쪽을 써야 한다.
그래서 «망이 되면 edge 를 쓴다»와 «`edge` 로 **고정**했으면 말없이 바꾸지 않는다»를
같이 못 박는다.

## ⚠️ 이 스위트는 **소리를 내지 않는다**

합성만 하고 재생은 하지 않는다. 테스트가 스피커를 울리면 아무도 안 돌린다.
"""
import _testenv  # noqa: F401
import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEXT = "메모장을 실행했어요. 지금 볼륨은 40퍼센트예요."


def run():
    passed = total = skipped = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}"
              + ("" if cond or not detail else f"   → {detail}"))

    def cannot_judge(names, why):
        """건너뛴 것은 **통과가 아니다** (BL-59)."""
        nonlocal skipped
        for n in names:
            skipped += 1
            print(f"  ⬜ 판정 불가 {n}")
        print(f"     └ {why}")

    src = io.open(os.path.join(_ROOT, "services", "tts.py"), encoding="utf-8").read()

    # ═══ ① 계약 — mime 을 같이 준다 ═══════════════════════════════
    print("=== ① 형식을 같이 알려준다 ===")
    from services.tts import TTSService, MIME_MP3, MIME_WAV
    check("edge 는 mp3, 로컬은 wav 로 구분한다", MIME_MP3 != MIME_WAV)
    check("🚨 받는 쪽에 mime 을 넘긴다 (main.py)",
          '"audio_mime"' in io.open(os.path.join(_ROOT, "main.py"),
                                    encoding="utf-8").read(),
          "없으면 WAV 를 audio/mpeg 로 재생하게 된다")
    check("   옛 이름도 그대로 산다 (to_bytes_async)",
          "async def to_bytes_async" in src and "async def synth_async" in src)

    # ═══ ② 🔑 정제는 **한 곳**에서만 건다 (2-2 ⓒ 회귀 방지) ═══════
    print("=== ② 🔑 «말할 것만 남기는» 정제가 새 경로에도 걸린다 ===")
    i_spoken = src.find("spoken = _spoken(text)")
    i_edge = src.find("async def _synth_edge")
    i_local = src.find("def _synth_local")
    check("정제가 갈림길 **앞**에 있다", 0 < i_spoken < i_edge and i_spoken < i_local,
          f"{i_spoken} / {i_edge} / {i_local}")
    # ⚠️ 주석·docstring 에도 이름이 나오므로 **호출만** 센다.
    check("🚨 엔진마다 따로 정제하지 않는다 (사본 금지)",
          src.count("= _spoken(") == 1,
          f"«= _spoken(» 이 {src.count('= _spoken(')}번 나온다")

    # ═══ ③ COM — 워커 스레드에서 도는 자리다 ═════════════════════
    print("=== ③ 🚨 워커 스레드에서 COM 을 켠다 ===")
    check("`ensure_com` 을 부른다", "ensure_com()" in src,
          "없으면 서버에서만 «CoInitialize 가 호출되지 않았습니다»로 죽는다")
    check("🔑 사본을 만들지 않고 tools.system 것을 쓴다",
          "from tools.system import ensure_com" in src)

    # ═══ ④ 실제로 한 바퀴 ═════════════════════════════════════════
    print("=== ④ 실제 합성 (소리는 내지 않는다) ===")

    async def boom(_s):
        return b""

    try:
        from services.tts import local_voices
        voices = local_voices()
        has_local = bool(voices)
    except Exception:                                         # noqa: BLE001
        voices, has_local = [], False

    if not has_local:
        cannot_judge(["🚨 망이 끊겨도 소리가 난다", "   그 결과가 WAV 다",
                      "   한국어 목소리를 고른다", "local 고정도 로컬로 간다",
                      "🚨 edge 고정이면 말없이 바꾸지 않는다",
                      "   없는 목소리를 골라도 침묵하지 않는다"],
                     "이 PC 에 SAPI 목소리가 없다(윈도우가 아니거나 comtypes 없음)")
    else:
        check("이 PC 에 한국어 목소리가 있다",
              any("korean" in v.lower() or "ko-kr" in v.lower() for v in voices),
              voices)

        # 🚨 핵심 — 망이 끊긴 척
        t = TTSService()
        t._synth_edge = boom
        audio, mime = asyncio.run(t.synth_async(TEXT))
        check("🚨 망이 끊겨도 소리가 난다", len(audio) > 0, f"{len(audio)} bytes")
        check("   그 결과가 WAV 다", mime == MIME_WAV and audio[:4] == b"RIFF",
              f"{mime} / {audio[:4]!r}")

        # local 고정
        t2 = TTSService()
        t2.engine = "local"
        a2, m2 = asyncio.run(t2.synth_async(TEXT))
        check("local 고정도 로컬로 간다", m2 == MIME_WAV and len(a2) > 0)

        # 🚨 반대 방향 — edge 로 **고정**했으면 말없이 바꾸지 않는다
        t3 = TTSService()
        t3.engine = "edge"
        t3._synth_edge = boom
        a3, m3 = asyncio.run(t3.synth_async(TEXT))
        check("🚨 edge 고정이면 말없이 바꾸지 않는다", a3 == b"" and m3 == "",
              f"{m3!r} / {len(a3)}")

        # 없는 목소리를 골라도 침묵하지 않는다
        t4 = TTSService()
        t4.engine = "local"
        t4.local_voice = "이런목소리는없다"
        a4, _ = asyncio.run(t4.synth_async(TEXT))
        check("   없는 목소리를 골라도 침묵하지 않는다", len(a4) > 0, f"{len(a4)} bytes")

    # ═══ ⑤ 🚨 반대 방향 — 평소에는 edge 를 쓴다 ═══════════════════
    #   «로컬로 내려간다»만 고정하면 **항상 로컬을 쓰는 수정**이 통과한다.
    print("=== ⑤ 🚨 평소에는 여전히 edge 를 쓴다 ===")
    calls = []

    class _Spy(TTSService):
        async def _synth_edge(self, spoken):
            calls.append(spoken)
            return b"ID3fake-mp3-bytes"

        def _synth_local(self, spoken):                       # pragma: no cover
            calls.append("LOCAL")
            return b"RIFFnope"

    a5, m5 = asyncio.run(_Spy().synth_async(TEXT))
    check("auto 에서 edge 가 **먼저** 불린다", calls and calls[0] != "LOCAL", calls)
    check("   성공하면 로컬로 안 내려간다", "LOCAL" not in calls, calls)
    check("   그 결과는 mp3 로 표시된다", m5 == MIME_MP3 and a5.startswith(b"ID3"))

    # ═══ ⑤-b 목소리 선택 — 설정으로 고를 수 있다 ═════════════════
    #   ⚠️ 여기는 **소스를 읽는다.** mock 스위트는 서버를 띄우지 않는다
    #     (`test_cache_api` 가 «실 서버 필요»로 빠져 있는 것과 같은 이유).
    print("=== ⑤-b 목소리를 고를 수 있다 (배선) ===")
    M = io.open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
    UI = io.open(os.path.join(_ROOT, "electron-ui", "renderer", "index.html"),
                 encoding="utf-8").read()
    check("서버가 목록을 준다 (GET /api/tts)", '@app.get("/api/tts")' in M)
    check("서버가 저장을 받는다 (POST /api/tts)", '@app.post("/api/tts")' in M)
    check("🔑 로컬 목록도 같이 준다 (PC 마다 다르다)", '"local_voices"' in M)
    check("🚨 온라인 목록을 못 받은 것과 «없는 것»을 구분한다",
          '"online_ok"' in M, "끊겨서 못 받은 것을 «목소리가 없다»로 보이면 안 된다")
    check("저장하면 싱글턴을 비운다 (다음 말부터 반영)",
          "_tts._tts_instance = None" in M,
          "안 비우면 서버를 껐다 켤 때까지 옛 목소리로 말한다")
    check("🚨 engine 값을 셋으로 좁힌다",
          'req.engine in ("auto", "edge", "local")' in M,
          ".env 에 아무 값이나 들어가면 조용히 auto 로 돈다")
    check("설정 화면에 세 칸이 있다",
          all(k in UI for k in ('id="tts-engine"', 'id="tts-voice"',
                                'id="tts-local-voice"')))
    check("설정을 열 때 같이 읽는다", "loadTtsConfig()" in UI)
    check("🔑 저장된 값이 목록에 없어도 보여 준다",
          "if (current && !list.includes(current)) list.unshift(current);" in UI,
          "안 그러면 고른 적 없는 값으로 바뀐 것처럼 보인다")

    # ═══ ⑥ 재생 파일 확장자 ══════════════════════════════════════
    print("=== ⑥ 서버 재생도 형식을 맞춘다 ===")
    check('WAV 면 ".wav" 로 쓴다', '".wav" if mime == MIME_WAV else ".mp3"' in src,
          "«.mp3» 로 쓰면 플레이어가 못 열고 **조용히 실패한다**")
    check("만들지 못했으면 재생하지 않는다", "if not audio_bytes:" in src)

    print(f"\n결과: {passed}/{total} 통과" + (f" · 판정 불가 {skipped}" if skipped else ""))
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
