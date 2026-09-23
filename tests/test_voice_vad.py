"""
발화 종료 감지(VAD) 배선 검증 — mock (Electron·마이크 없음)
실행: python tests/test_voice_vad.py

## 왜 이 테스트가 생겼나 (BL-33)

2026-09-10 교수님 미팅에서 지적이 나왔다 — **음성 입력이 8초에서 잘린다.**
버그가 아니라 **설계에 발화 종료 감지가 없었다.** `REC_SEC = 8` 타이머 하나가
«사람이 말을 끝낸 시점»을 대신하고 있었다. 말이 길면 뒷말이 잘리고, 짧으면
남은 초를 멍하니 기다린다.

이 문서가 지키는 것은 **고친 코드가 다시 타이머로 돌아가지 않는 것**이고,
그보다 중요한 건 **«끝나지 않는 녹음»을 막는 세 방어선**이다:

  ① **상한(MAX_MS)** — 무음 감지가 환경 소음에 속으면 이것만 남는다.
     인터벌과 **별개의 setTimeout**으로 한 번 더 건다(인터벌이 throttle돼도 끊긴다)
  ② **TTS 되먹임 차단** — 재생 중인 자기 목소리가 마이크에 들어가면 «무음»이
     영영 오지 않는다. 화면 감시 알림(`onWatchNotify`)은 **녹음 중에도 들어온다**
  ③ **히스테리시스** — START_RMS와 KEEP_RMS가 같으면 임계 근처에서 말이
     «시작·끝·시작»으로 튄다

⚠️ 브라우저를 띄우지 않는다. 소스를 읽어 대조할 뿐이다.
   **임계값이 맞는지는 여기서 알 수 없다** — 그건 실제 목소리로만 정해진다
   (콘솔의 `[VAD]` 줄). 여기선 «구조가 서 있는지»만 본다.
"""
import _testenv  # noqa: F401
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

Q = chr(34)          # 큰따옴표 — 이스케이프를 안 쓰려고 상수로 둔다
passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


def read(*parts):
    # 절대규칙 7 — 한글이 든 소스는 utf-8 명시(cp949면 UnicodeDecodeError)
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def between(text, start, end):
    """start부터 end 직전까지. 정규식을 쓰지 않는다(백슬래시 없이 읽히게)."""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:j if j > 0 else len(text)]


def strip_comments(js):
    """`//` 주석을 걷어낸다 — 주석 속 낱말이 배선으로 오인되지 않게."""
    out = []
    for line in js.splitlines():
        t = line.strip()
        if t.startswith("//"):
            continue
        i = line.find("//")
        out.append(line[:i] if i >= 0 else line)
    return "\n".join(out)


def const_num(block, key):
    """`KEY: 1.23,` 에서 숫자만 꺼낸다."""
    i = block.find(key + ":")
    if i < 0:
        return None
    seg = block[i + len(key) + 1:]
    seg = seg.split(",")[0].split("/")[0].strip()
    try:
        return float(seg)
    except ValueError:
        return None


ui = read("electron-ui", "renderer", "index.html")
ui_code = strip_comments(ui)
mainjs = read("electron-ui", "main.js")


print("[1] 고정 8초 타이머가 사라졌다 (BL-33의 본체)")

check("REC_SEC 상수가 없다", "const REC_SEC" not in ui_code,
      "타이머가 되살아나면 같은 증상이 그대로 돌아온다")
check("cdRemain(남은 초) 상태가 없다", "cdRemain" not in ui_code)
check("startCd()를 부르는 곳이 없다", "startCd(" not in ui_code)
check("남은 시간을 세는 setInterval 100ms가 없다", "}, 100);" not in ui_code)


print("")
print("[2] VAD 상수 — 값들이 서로 모순되지 않는다")

vad = between(ui, "const VAD = {", "};")
check("VAD 상수 블록이 있다", bool(vad))

keys = ("START_RMS", "KEEP_RMS", "SILENCE_MS", "NOSPEECH_MS",
        "MAX_MS", "FLOOR_MS", "FLOOR_MULT", "FLOOR_MAX", "TICK_MS")
vals = {}
for k in keys:
    v = const_num(vad, k)
    check(f"{k}가 있다", v is not None)
    vals[k] = v

if all(v is not None for v in vals.values()):
    # ③ 히스테리시스 — 둘이 같으면 임계 근처에서 말이 튄다
    check("START_RMS > KEEP_RMS (히스테리시스)",
          vals["START_RMS"] > vals["KEEP_RMS"],
          f"→ {vals['START_RMS']} vs {vals['KEEP_RMS']}")
    # ① 상한이 가장 크다 — 다른 종료 조건보다 나중에 와야 «최후의 방어선»이다
    check("MAX_MS가 NOSPEECH_MS보다 크다",
          vals["MAX_MS"] > vals["NOSPEECH_MS"])
    check("MAX_MS가 SILENCE_MS보다 크다",
          vals["MAX_MS"] > vals["SILENCE_MS"])
    check("MAX_MS가 60초를 넘지 않는다(상한이 상한 구실을 한다)",
          0 < vals["MAX_MS"] <= 60000, f"→ {vals['MAX_MS']}")
    # 사람이 숨 쉬는 틈(0.3~0.5초)에 끊기면 안 되고, 2초를 넘으면 굼뜨게 느껴진다
    check("SILENCE_MS가 0.6~2.0초 사이다",
          600 <= vals["SILENCE_MS"] <= 2000, f"→ {vals['SILENCE_MS']}")
    # 잡음 바닥 측정 구간은 발화 시작보다 짧아야 한다
    check("FLOOR_MS < NOSPEECH_MS", vals["FLOOR_MS"] < vals["NOSPEECH_MS"])
    check("FLOOR_MAX > START_RMS (바닥 보정이 시작임계를 올리는 방향이다)",
          vals["FLOOR_MAX"] > vals["START_RMS"])
    check("TICK_MS가 SILENCE_MS보다 충분히 작다(무음을 놓치지 않는다)",
          vals["TICK_MS"] * 4 <= vals["SILENCE_MS"], f"→ {vals['TICK_MS']}")


print("")
print("[3] 배선 — 마이크 수명과 VAD 수명이 같이 간다")

start_mic = between(ui, "async function startMic()", "function stopMic")
stop_mic = between(ui, "function stopMic(send = true)", "async function sendVoice")
deact = between(ui, "function deactivate()", "// ── 상태")

check("startMic이 startVad(stream)을 부른다", "startVad(stream)" in start_mic)
check("startMic이 레벨 링을 띄운다", "showLevel()" in start_mic)
check("stopMic이 stopVad()를 부른다", "stopVad()" in stop_mic)
check("stopMic이 레벨 링을 내린다", "hideLevel()" in stop_mic)
check("deactivate가 stopVad()를 부른다", "stopVad()" in deact,
      "Esc로 닫으면 인터벌이 고아로 남는다")

# ⚠️ 주석을 걷어낸 쪽을 본다 — 주석에 적힌 «destination에 잇지 말 것»이
#    배선으로 오인되면 이 검사가 스스로를 속인다
vadfn = between(ui_code, "function startVad(stream)", "function endVad")
check("같은 MediaStream에서 분석기를 만든다",
      "createMediaStreamSource(stream)" in vadfn)
check("AnalyserNode를 쓴다", "createAnalyser()" in vadfn)
check("시간영역 파형을 읽는다(RMS 계산용)",
      "getFloatTimeDomainData" in vadfn)
# 자기 목소리를 스피커로 되내보내면 그게 곧 되먹임이다
check("분석기를 destination에 잇지 않는다",
      "destination" not in vadfn,
      "이으면 마이크 입력이 스피커로 나가 되먹임이 된다")
# requestAnimationFrame은 창이 뒤로 가면 초당 1회로 떨어진다 → 무음을 못 본다
check("requestAnimationFrame을 쓰지 않는다",
      "requestAnimationFrame" not in ui_code,
      "창이 뒤로 가면 프레임이 throttle돼 무음을 영영 못 본다")

stop_vad = between(ui, "function stopVad()", "// ── 음성 녹음")
check("stopVad가 인터벌을 지운다", "clearInterval" in stop_vad)
check("stopVad가 상한 타이머도 지운다", "clearTimeout" in stop_vad)
check("stopVad가 AudioContext를 닫는다", "close()" in stop_vad,
      "안 닫으면 녹음마다 컨텍스트가 쌓인다")


print("")
print("[4] 종료 — 사유마다 하는 일이 다르다")

endfn = between(ui, "function endVad(reason)", "function stopVad()")
check("endVad가 있다", bool(endfn))
check("말이 한 번도 없었으면 STT를 부르지 않는다",
      "nospeech" in endfn and "stopMic(false)" in endfn,
      "stopMic(true)면 빈 오디오가 서버로 나간다")

# 🚨 2026-09-11 실기 — 위 한 줄로는 **부족했다.** chunks를 비워도
#    `mr.stop()`의 마지막 flush가 다시 채워 956바이트가 STT로 나갔다.
#    («10:11:06 [STT] 956 bytes → 인식하지 못했습니다» — 6초는 NOSPEECH_MS다)
check("🚨 버리는 녹음은 **플래그**로 막는다(배열을 비우는 것으론 못 막는다)",
      "micDiscard" in ui_code,
      "mr.stop()이 마지막 dataavailable을 flush해 비운 배열을 다시 채운다")
check("stopMic이 플래그를 세운다", "micDiscard = !send" in stop_mic)
check("ondataavailable이 플래그를 본다",
      "!micDiscard" in ui_code, "flush된 마지막 조각이 배열에 들어가면 끝이다")
check("onstop도 플래그를 본다", "if (micDiscard)" in ui_code)
check("새 녹음이 플래그를 되돌린다", "micDiscard = false" in start_mic,
      "안 되돌리면 다음 녹음이 통째로 버려진다")
check("그 밖의 사유는 보낸다", "stopMic(true)" in endfn)
check("종료 사유를 콘솔에 남긴다(임계 조정의 유일한 근거다)",
      "[VAD]" in endfn and "사유=" in endfn)
check("최대 RMS를 같이 남긴다", "vadPeak" in endfn)

check("무음 종료 조건이 endpoint로 간다", "endVad('endpoint')" in ui_code)
check("발화가 없으면 nospeech로 간다", "endVad('nospeech')" in ui_code)
# ① 인터벌과 **별개의** 상한. 인터벌이 멈춰도 이건 뜬다
check("상한을 setTimeout으로 한 번 더 건다",
      "vadMaxTimer = setTimeout" in ui_code,
      "인터벌만 믿으면 인터벌이 죽을 때 녹음이 안 끝난다")
check("상한 타이머가 VAD.MAX_MS를 쓴다", "VAD.MAX_MS)" in ui_code)
# AudioContext가 없는 환경(구형 WebView 등)에서도 녹음이 끝나야 한다
check("분석기를 못 만들면 상한만으로라도 끊는다",
      ui_code.count("setTimeout(() => stopMic(true), VAD.MAX_MS)") >= 2,
      "AudioContext 없음·생성 실패 두 경로")


print("")
print("[5] TTS 되먹임 — «끝나지 않는 녹음»의 두 번째 방어선")

play = between(ui, "function playAudio(b64)", "// ── 화면 감시 알림")
check("녹음 중이면 TTS를 미룬다", "if (isRec) { pendingAudio = b64; return; }" in play,
      "틀면 자기 목소리가 마이크로 들어가 무음이 오지 않는다")
check("미룬 것을 버리지 않는다(알림을 삼키지 않는다)",
      "function flushPendingAudio" in ui_code)
check("녹음이 끝나면 흘려보낸다", "flushPendingAudio()" in stop_mic)
check("새 녹음이 시작되면 낡은 TTS는 버린다",
      "pendingAudio = null" in between(ui, "function stopCurrentAudio()", "function flushPendingAudio"))
check("마이크 시작 시 재생 중인 TTS를 끊는다", "stopCurrentAudio()" in start_mic)
# 웨이크워드 자동 시작 경로도 결국 startMic을 지난다 — 거기서 TTS가 끊긴다
check("웨이크워드 자동 시작도 startMic을 지난다",
      "autoMic" in ui_code and "startMic()" in between(ui, "function activate(autoMic", "function deactivate"))


print("")
print("[6] 링이 «남은 시간»이 아니라 «듣고 있다»를 보여준다")

check("setLevel(rms, live)가 있다", "function setLevel(rms, live)" in ui_code)
check("레벨로 링 길이를 정한다", "strokeDashoffset" in between(ui, "function setLevel", "function hideLevel"))
check("말이 잡히기 전엔 idle 표시다", "classList.toggle('idle'" in ui_code)
check("idle 색이 CSS에 있다", ".cd-ring.idle .pr" in ui)
check("가운데에 남은 초를 쓰지 않는다",
      ">8</div>" not in ui and "Math.ceil(cdRemain)" not in ui)


print("")
print("[6-B] 🚨 헛깨어남을 조용히 닫는다 (BL-23 완화, 2026-09-11)")

# 웨이크워드 오탐은 모델 문제라 10월 재구축 전에는 못 줄인다(M7).
# 대신 **보이는 증상**을 지운다 — 사용자가 시킨 적 없는 턴의 오류를 보여 주면
# 헛깨어남이 «고장»처럼 보인다.
send_voice = between(ui, "async function sendVoice(blob)", "// ── 텍스트 전송")
wake_fn = between(ui, "window.pluiz.onWakeDetected", "window.pluiz.onWakewordStatus")
toggle = between(ui, "function toggleMic()", "// 🚨 2026-09-09")
close_fn = between(ui, "function closeIfSpurious()", "function stopVad()")

check("웨이크워드가 연 녹음을 표시해 둔다", "micAuto = true" in wake_fn)
check("이미 떠 있었으면 닫지 않는다", "wakeOpened = !isActive" in wake_fn,
      "사용자가 쓰던 중에 오탐이 나면 창을 닫아 버린다")
check("출처를 **이 녹음에** 고정한다", "recAuto = micAuto" in start_mic,
      "전역만 보면 다음 녹음이 이전 출처를 물려받는다")
check("고정하면서 다음 것을 비운다", "micAuto = false" in start_mic)

check("🚨 사람이 누른 마이크는 auto가 아니다", "micAuto = false" in toggle,
      "사람이 결과를 기다리는 턴에서 오류를 삼키면 그게 더 나쁘다")
check("Alt+Space도 사람이다",
      "micAuto = false" in between(ui, "onToggleActive", "document.addEventListener"))

check("자동 녹음의 STT 실패는 조용히 닫는다",
      "if (recAuto) { closeIfSpurious(); }" in send_voice)
check("사람이 누른 녹음은 오류를 그대로 보여준다",
      "addMsg('a', '⚠️ ' + data.error)" in send_voice,
      "«조용히 끝나지 않는다»는 규칙은 사람이 시킨 턴에 적용된다")
check("자동 녹음의 무발화도 조용히 닫는다", "if (auto) { closeIfSpurious(); return; }" in endfn)

check("서버가 답하는 중이면 닫지 않는다", "busy) return" in close_fn,
      "진짜 턴을 닫아 버린다")
check("닫을 때 플래그를 되돌린다",
      "recAuto = false" in close_fn and "wakeOpened = false" in close_fn)
check("실제로 오버레이를 닫는다", "deactivate()" in close_fn)

# 헛깨어남이면 오버레이가 떠 있는 시간을 줄인다
check("자동 녹음은 더 빨리 접는다",
      "recAuto ? VAD.NOSPEECH_AUTO_MS : VAD.NOSPEECH_MS" in ui_code)
auto_ms = const_num(vad, "NOSPEECH_AUTO_MS")
check("NOSPEECH_AUTO_MS가 있다", auto_ms is not None)
if auto_ms and vals.get("NOSPEECH_MS"):
    check("자동 쪽이 더 짧다", auto_ms < vals["NOSPEECH_MS"], f"→ {auto_ms}")
    check("너무 짧지 않다(숨 고르는 사람을 자르지 않는다)", auto_ms >= 3000,
          f"→ {auto_ms}")


print("")
print("[7] 타이머가 throttle되지 않게 창을 설정했다")

win = between(mainjs, "mainWindow = new BrowserWindow({", "});")
check("mainWindow에 backgroundThrottling: false가 있다",
      "backgroundThrottling: false" in win,
      "창이 뒤로 가면 50ms 인터벌이 1초로 떨어져 무음을 못 본다")


print("")
print(chr(61) * 60)
print(f"결과: {passed}/{total} 통과")
print(chr(61) * 60)
sys.exit(0 if passed == total else 1)
