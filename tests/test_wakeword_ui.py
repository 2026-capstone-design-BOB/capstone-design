"""
웨이크워드 설정 UI 배선 검증 — mock (Electron·서버 없음)
실행: python tests/test_wakeword_ui.py

## 왜 이 테스트가 생겼나

`POST /api/wakeword`는 2026-09-02부터 열려 있었는데 **입력란이 없어서** 사용자가
`.env`를 직접 열어야 했다(BL-13). 2026-09-07에 설정 화면에 붙였다.

프런트와 서버가 **다른 파일**이라 어긋나도 아무도 안 알려 준다. 증상은
*"저장을 눌렀는데 아무 일도 없다"* 이고, 이 저장소가 이미 겪은 모양이다 —
BL-16(`/voice`의 `Form(...)` 누락)은 **평범한 경우엔 멀쩡해 보이다가** 맥락이
필요한 순간에만 무너졌다. 그래서 넷을 본다.

  ① **필드 이름이 서버 모델과 같은가** — 다르면 422고 프런트는 조용히 실패한다
  ② **토큰이 실리는 경로로 부르는가** — `window.fetch` 래퍼는 `API`로 시작하는
     URL에만 헤더를 붙인다(BL-14). 절대 경로를 쓰면 그 기능만 401이 난다
  ③ **API 키 저장과 얽히지 않는가** — 호출어만 바꾸려는 사람이 키를 다시 넣거나
     에이전트가 재초기화되면 안 된다
  ④ **반영에 시간이 걸린다고 말하는가** — 웨이크워드는 별도 프로세스라 즉시가
     아니다. 안 말하면 저장 직후 불러 보고 고장이라고 생각한다

⚠️ 브라우저를 띄우지 않는다. 소스를 읽어 대조할 뿐이다.
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


ui = read("electron-ui", "renderer", "index.html")
server = read("main.py")


print("[1] 설정 화면에 입력란이 있다 (BL-13)")
for el in ("wake-words-input", "wake-enabled", "wake-save-btn", "wake-status"):
    check(f"{el} 요소가 있다", "id=" + Q + el + Q in ui)
check("저장 버튼이 saveWakeWords를 부른다", "onclick=" + Q + "saveWakeWords()" + Q in ui)
check("엔터로도 저장된다", "if(event.key==='Enter') saveWakeWords()" in ui)
check("설정창을 열 때 현재 값을 다시 읽는다", "loadWakeConfig();" in ui)


print("")
print("[2] 프런트가 보내는 이름 = 서버가 받는 이름 (어긋나면 422)")

model = between(server, "class WakeWordRequest(BaseModel):", "# ── REST")
check("서버에 WakeWordRequest가 있다", bool(model))
fields = set()
for line in model.splitlines()[1:]:
    t = line.strip()
    if t and t[0].isalpha() and ":" in t:
        fields.add(t.split(":")[0].strip())
check("서버 모델 필드는 wake_words · enabled 두 개다",
      fields == {"wake_words", "enabled"}, f"→ {sorted(fields)}")

fn = between(ui, "async function saveWakeWords()", "function setWakeStatus")
check("saveWakeWords가 있다", bool(fn))
for f in sorted(fields):
    check(f"프런트가 {f}를 보낸다", f in fn)
check("본문을 JSON으로 보낸다", "JSON.stringify" in fn and "application/json" in fn)
check("응답의 wake_words를 그대로 되받아 입력란에 다시 채운다", "data.wake_words" in fn)
check("서버가 정리한 값을 돌려준다(프런트가 믿을 근거)",
      Q + "wake_words" + Q + ": words" in server)


print("")
print("[3] 인증 — 토큰이 안 실리면 이 기능만 조용히 401 (BL-14)")

# window.fetch 래퍼는 `API`로 시작하는 URL에만 X-Pluiz-Token을 붙인다.
# 절대 경로(http://127.0.0.1:8765/...)를 새로 쓰면 헤더가 안 붙는다.
check("wakeword 호출이 API 템플릿을 쓴다",
      "${API}/api/wakeword" in ui, "절대 URL을 쓰면 토큰이 안 실린다")
check("설정 읽기도 API 템플릿을 쓴다", "${API}/api/config" in ui)
check("서버 엔드포인트 경로가 같다", Q + "/api/wakeword" + Q in server)


print("")
print("[4] 호출어만 바꾸는 사람이 API 키를 다시 넣지 않아도 된다")

check("API 키 입력란을 읽지 않는다", "api-key-input" not in fn)
check("에이전트를 재초기화하는 /api/config를 부르지 않는다", "/api/config" not in fn)
check("WebSocket을 끊지 않는다", "ws.close()" not in fn)
check("자기 전용 상태줄에만 쓴다(키 저장 메시지를 덮지 않는다)",
      "setWakeStatus" in fn and "setSettingStatus" not in fn)


print("")
print("[5] 저장 직후 불러 보고 고장으로 오해하지 않게 한다")

# 웨이크워드는 Electron이 띄운 **별도 프로세스**라 서버가 직접 못 바꾼다.
# .env를 다시 읽어 반영되므로 즉시가 아니다.
check("반영에 시간이 걸린다고 말한다", "10초" in fn)
check("껐을 때 대체 수단(Alt+Space)을 알려 준다", "Alt+Space" in fn)
check("비워 두면 쓰이는 기본값을 플레이스홀더로 보여 준다",
      "wake_words_default" in ui and "wake_words_default" in server)


print("")
print(chr(61) * 60)
print(f"결과: {passed}/{total} 통과")
print(chr(61) * 60)
sys.exit(0 if passed == total else 1)
