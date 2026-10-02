"""
말 거는 단축키 배선 검증 — mock (Electron·서버 없음)
실행: python tests/test_hotkey_ui.py

## 왜 이 테스트가 생겼나

**버튼·더블클릭·`Alt+Space` 는 2026-09-02부터 전부 동작하고 있었다.**
그런데 2026-10-02 에 열어 보니 **어디에도 적혀 있지 않았다** — 대기 화면 안내는
`'더블클릭 · 🎙️'` 뿐이었고, 단축키는 `electron-ui/main.js` 에 **하드코딩**이라
사용자가 알 길도, 바꿀 길도 없었다. 전시회에서 *"버튼으로도 됩니다"* 라고
말하려면 **그게 화면에 있어야** 한다.

🚨 **고치면서 BL-13 의 자리로 다시 들어간다.** BL-13 은
*"저장까지 했는데 아무 반응이 없는 최악의 모양"* 이었는데, 전역 단축키는
**저장과 적용이 다른 일**이라 정확히 같은 함정이 있다:

  `.env` 에 적는 것 = 서버          ← 항상 성공한다
  그 키를 실제로 잡는 것 = Electron ← **다른 프로그램이 쓰고 있으면 실패한다**

`globalShortcut.register()` 가 `false` 를 돌려주는데 그걸 안 보면,
«저장됐어요» 라고 말해 놓고 눌러도 아무 일이 없다. 그래서 다섯을 본다.

  ① **필드 이름이 서버 모델과 같은가** — 다르면 422고 프런트는 조용히 실패한다
  ② **토큰이 실리는 경로로 부르는가** — `API` 로 시작하는 URL 에만 헤더가 붙는다(BL-14)
  ③ 🚨 **등록 실패를 말하는가** — 이게 BL-13 이다
  ④ 🔑 **기본값의 주인이 하나인가** — `main.js`·UI·서버가 각자 들고 있으면
     «설정은 바뀌었는데 실제로 듣는 키는 그대로» 가 된다
  ⑤ **호출어를 끄지 않는가** — 둘 다 되게 두는 것이 이번 결정이다

⚠️ 브라우저를 띄우지 않는다. 소스를 읽어 대조할 뿐이다.
"""
import _testenv  # noqa: F401
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

Q = chr(34)
passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


def src(*parts):
    return io.open(os.path.join(_ROOT, *parts), encoding="utf-8").read()


ui       = src("electron-ui", "renderer", "index.html")
preload  = src("electron-ui", "preload.js")
mainjs   = src("electron-ui", "main.js")
server   = src("main.py")
settings = src("config", "settings.py")

print("=== ① 필드 이름이 서버 모델과 같은가 ===")
check("서버에 `POST /api/hotkey` 가 있다", Q + "/api/hotkey" + Q in server)
check("요청 모델이 `hotkey` 를 받는다",
      "class HotkeyRequest" in server and "hotkey: str" in server)
check("UI 가 보내는 키 이름이 같다", '"hotkey": want' in ui or "hotkey: want" in ui)
check("서버가 `GET /api/config` 로 현재 값을 돌려준다",
      '"hotkey": s.hotkey' in server)

print("")
print("=== ② 토큰이 실리는 경로로 부르는가 (BL-14) ===")
check("`${API}/api/hotkey` 템플릿을 쓴다 (절대 URL 이면 401)",
      "${API}/api/hotkey" in ui)

print("")
print("=== ③ 🚨 등록 실패를 **말하는가** (BL-13 의 자리) ===")
check("main.js 가 register() 의 반환값을 본다",
      "globalShortcut.register(want" in mainjs)
check("실패를 렌더러에 돌려준다 (`ok` 를 담는다)",
      "{ ok: false" in mainjs and "{ ok: true" in mainjs)
check("🔑 실패하면 **쓰던 키로 되돌린다** (새 키도 옛 키도 없는 상태를 안 만든다)",
      "if (previous && globalShortcut.register(previous" in mainjs)
check("preload 가 그 답을 건네준다",
      "setHotkey:" in preload and "invoke('set-hotkey'" in preload)
check("main 이 그 채널을 받는다", "ipcMain.handle('set-hotkey'" in mainjs)
check("🚨 UI 가 **실패를 사용자에게 말한다**",
      "다른 프로그램이 쓰고 있어요" in ui)
check("🚨 저장만으로 «된다»고 말하지 않는다 (적용 결과를 보고 말한다)",
      "await window.pluiz.setHotkey(data.hotkey)" in ui)
check("서버도 «저장했을 뿐»이라고 적어 둔다",
      "실제로 잡혔는지는" in server)
check("창을 띄울 때 저장해 둔 키를 **실제로 잡는다** (읽고 끝내지 않는다)",
      "window.pluiz.setHotkey(hk)" in ui)

print("")
print("=== ④ 🔑 기본값의 주인이 하나인가 ===")
check("기본값이 `config/settings.py` 에 있다", 'hotkey: str = "Alt+Space"' in settings)
check("서버가 그 기본값을 UI 에 알려 준다",
      'Settings.model_fields["hotkey"].default' in server)
check("UI 가 자기 기본값을 **고집하지 않는다** (서버 값으로 덮어쓴다)",
      "hotkeyDefault = data.hotkey_default" in ui)
# 🚨 2026-10-02 이전에는 이 문구가 하드코딩된 'Alt+Space' 였다 —
#    키를 바꿀 수 있게 된 순간 **거짓말이 된다.**
check("🚨 호출어를 껐을 때 문구가 **지금 잡힌 키**를 말한다",
      "'✓ 껐어요. Alt+Space로" not in ui and "껐어요. ${hk}" in ui)

print("")
print("=== ⑤ 호출어를 끄지 않는다 (둘 다 쓴다) ===")
check("단축키를 넣으면서 웨이크워드를 끄지 않았다",
      "startWakeword();" in mainjs)
check("설정에 «말 거는 방법» 이 보인다", "말 거는 방법" in ui)
check("🚨 대기 화면이 **부르는 법을 적는다** (여기 말고는 적힌 데가 없다)",
      "setIdleHint" in ui and "더블클릭 · 🎙️ · $" in ui)
check("호출어 로딩 중에도 «버튼·단축키는 지금도 된다»고 말한다",
      "는 지금도 돼요" in ui)

print("")
print("=== ⑥ 키 캡처가 발을 쏘지 않는가 ===")
# 🔑 전역 단축키라 **다른 프로그램에서 타자 칠 때마다** 창이 뜨면 안 된다.
check("🔑 조합키 없는 한 글자는 안 받는다",
      "if (!mods.length && k.length <= 1) return null;" in ui)
check("조합키만 눌렀을 때는 아직 확정하지 않는다",
      "['Control', 'Alt', 'Shift', 'Meta'].includes(k)" in ui)
check("설정창에서 누른 키가 밖으로 새지 않는다 (preventDefault)",
      "e.preventDefault();" in ui)
# 🚨 처음 쓴 코드가 소스에 **진짜 개행을 박아** main.py 를 깨뜨렸다 — 스위트가 잡았다.
#    그래서 이스케이프 없이 **문자 코드**로 거른다. 같은 실수가 안 나는 모양이다.
check("⚠️ `.env` 에 개행이 끼어들지 못한다 (BL-14 ③ 과 같은 자리)",
      "ch not in (chr(10), chr(13))" in server)

print("")
print(chr(61) * 60)
print(f"결과: {passed}/{total} 통과")
print(chr(61) * 60)
sys.exit(0 if passed == total else 1)
