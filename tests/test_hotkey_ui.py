"""
말 거는 법 배선 검증 — mock (Electron·서버 없음)
실행: python tests/test_hotkey_ui.py

## 왜 이 테스트가 생겼나

**버튼·더블클릭·`Alt+Space` 는 2026-09-02부터 전부 동작하고 있었다.** 그런데
어디에도 적혀 있지 않았고, 단축키는 `main.js` 하드코딩이라 바꿀 수도 없었다.
2026-10-02 에 설정으로 빼고 **실기에서 네 개가 터졌다:**

| | 증상 | 뿌리 |
|---|---|---|
| ① | 더블클릭이 안 먹힌다 | 단일 클릭이 **먼저** 창을 열어 레이아웃이 바뀌고, 두 번째 클릭의 `dblclick` 이 **다른 요소**로 갔다 |
| ② | `Space`·`Backspace` 만 적용된다 | 키 캡처 가드가 틀렸고, **한글 IME** 가 켜져 있으면 `e.key` 가 엉뚱하게 온다 |
| ③ | 🚨 **`Ctrl+C` 가 그대로 등록됐다** | 앱 내부 단축키는 `globalShortcut.register()` 가 **성공한다.** 「이미 쓰이는가」는 **알아낼 수 없다** |
| ④ | 창 켜자마자 음성 입력 | 웨이크 신호가 `activate(true)` 로 **창을 펼쳤다** |

## 🔑 그래서 모델을 다시 정의했다 (2026-10-02 · 사용자)

| 입력 | 뜻 |
|---|---|
| **더블클릭** | 창 활성화 — 채팅·설정·즐겨찾기. **사람이 소프트웨어를 다루는 일** |
| **단축키 · 🎙️** | 웨이크 신호 — 호출어를 대신해 **음성 인식을 깨운다. 창과 무관** |
| **`−` 버튼** | 창 접기 (단일 클릭으로 열던 길을 없앴으니 닫는 길이 분명해야 한다) |

🔑 **①은 «고치는» 게 아니라 «단일 클릭 동작을 없애서» 사라졌다** — 원인 자체가
단일 클릭이었기 때문이다. ②③은 **자유 입력을 버리고 목록 선택**으로 바뀌면서
같이 사라졌다. **탐지로 풀 수 있는 문제가 아니었다.**

## 여기서 고정하는 것

| | 왜 |
|---|---|
| 🚨 **목록 밖은 서버가 거부한다** | UI 만 막으면 샌다. 막는 자리는 **저장하는 곳**이어야 한다(BL-27·BL-50 이 세 번 치른 값) |
| 🔑 **기본값·목록의 주인이 하나다** | `main.js` 가 기본값을 들고 있으면 **잠깐이라도 틀린 키를 전역으로 가로챈다** |
| 🚨 **웨이크 신호가 창을 안 연다** | ④ 가 되돌아오면 이 줄이 깨진다 |
| **창 여는 길은 더블클릭 하나** | 단일 클릭이 돌아오면 ① 이 그대로 재발한다 |
| **등록 실패를 말한다** | BL-13 의 *"저장했는데 아무 반응 없음"* |

⚠️ 브라우저를 띄우지 않는다. 소스를 읽어 대조할 뿐이다.
"""
import _testenv  # noqa: F401
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

from config.settings import Settings  # noqa: E402


def between(text, a, b):
    i = text.index(a)
    return text[i:text.index(b, i)]

print("=== ① 🚨 더블클릭이 창을 여는 **유일한** 길인가 ===")
# 실기에서 더블클릭이 안 먹힌 원인은 **단일 클릭**이었다 — 첫 클릭이 창을 열며
# 레이아웃을 바꿔, 두 번째 클릭의 dblclick 이 다른 요소로 갔다.
# 🔑 그래서 «고치는» 게 아니라 **단일 클릭을 없애서** 사라진다. 돌아오면 재발한다.
check("🚨 대기 화면에 `onclick` 으로 창을 여는 길이 없다",
      'id="idle-view" onclick=' not in ui)
check("더블클릭이 창을 연다", 'id="idle-view" ondblclick="activate(false)"' in ui)
check("🔑 창을 **펼치면서 녹음**하는 길이 아예 없다 (④ 의 뿌리)",
      "activate(true);" not in ui)

# 🚨 **2026-10-02 실기 2차 — 한 번도 두 번도 아무 반응이 없었다.**
#   JS 는 멀쩡했다. `.card` 에 `-webkit-app-region: drag` 가 걸려 있는데
#   **Electron 의 드래그 영역은 클릭·더블클릭 이벤트를 삼킨다.**
#   버튼만 `.idle-actions` 로 `no-drag` 라 버튼은 되고 창은 안 됐다.
# 🔑 **JS 를 아무리 고쳐도 안 고쳐지는 종류였다 — CSS 사실이다.**
#   그래서 여기서 **CSS 를 센다.** 핸들러만 세는 테스트는 이걸 영원히 못 잡는다.
def css_block(name):
    i = ui.index(name + " {")
    return ui[i:ui.index("}", i)]


check("🚨 대기 화면이 **드래그 영역이 아니다** (드래그면 클릭이 안 간다)",
      "-webkit-app-region: no-drag" in css_block("    .idle-view"))
check("🔑 그래도 **창을 끌 자리는 있다** (고리가 손잡이)",
      "-webkit-app-region: drag" in css_block("    .logo-ring"))
check("⚠️ 헤더의 죽은 `ondblclick` 을 지웠다 (드래그 영역이라 안 불린다)",
      'class="a-header" ondblclick' not in ui)

print("")
print("=== ② 창을 닫는 길이 **보이는가** ===")
check("최소화 버튼이 있다", 'id="min-btn"' in ui and 'title="창 접기"' in ui)
check("그 버튼이 창만 접는다 (종료가 아니다)",
      'id="min-btn" onclick="event.stopPropagation(); deactivate()"' in ui)
check("종료 버튼은 그대로 있다", "window.pluiz.quit()" in ui)

print("")
print("=== ③ 🚨 웨이크 신호는 **창과 무관**한가 ===")
check("단축키·호출어·🎙️ 가 **같은 길**을 탄다 (`wakeListen`)",
      ui.count("wakeListen(") >= 4, f"→ {ui.count('wakeListen(')}곳")
check("🚨 단축키가 창을 열지도 닫지도 않는다",
      "window.pluiz.onToggleActive(() => wakeListen(false));" in ui)
check("호출어도 접힌 채로 듣는다", "wakeListen(true);" in ui)
check("🎙️ 버튼도 같다", 'wakeListen(false)"' in ui)
check("🔑 접힌 상태에 «지금 무슨 일인지»가 보인다 (안 보이면 반응이 없어 보인다)",
      "function idleLine()" in ui and "듣는 중…" in ui and "생각하는 중…" in ui)

# 🚨 **2026-10-02 실기 2차 — 아무것도 안 했는데 「생각하는 중…」이 남아 있었다.**
#   `sendVoice()` 는 녹음이 너무 짧으면 **try 에 들어가기도 전에 return** 한다.
#   그 길에는 `finally` 가 없어서 손으로 켠 표시가 영영 남았다.
# 🔑 그래서 **표시를 손으로 켜고 끄지 않는다 — 진짜 상태에서 끌어온다.**
#   길이 몇 개든, 새 길이 생기든 어긋날 수 없다.
check("🚨 표시가 **상태에서 나온다** (`isRec`·`busy`)",
      "function refreshIdle" in ui
      and "if (isRec) return '듣는 중…';" in ui
      and "if (busy) return '생각하는 중…';" in ui)
check("🔑 `setBusy()` 가 표시를 **같이** 되돌린다 (빠뜨릴 자리가 없게)",
      "function setBusy(v) {" in ui
      and "refreshIdle();" in ui[ui.index("function setBusy(v) {"):
                                 ui.index("function setBusy(v) {") + 220])
check("마이크가 **실패해도** 표시가 안 남는다 (finally 에서 다시 읽는다)",
      "micStarting = false;" in ui
      and "refreshIdle();        // 🚨 실패해도" in ui)
check("🚨 손으로 켜는 자리가 **남아 있지 않다**",
      "setIdleBusy(" not in ui)

# 🚨 **2026-10-02 실기 3차 — 답을 받은 뒤에도 「생각하는 중…」이 남아 있었다.**
#   `setIdleHint()` 안에 *"지금 글자에 「중…」이 들어 있으면 건드리지 않는다"* 는
#   가드가 있었다. 바쁜 표시를 덮어쓰지 않으려던 것인데 **그 가드가 자기 자신을 막았다** —
#   지우러 온 호출이 「중…」에 걸려 되돌아갔다.
# 🔑 **뿌리는 글자를 쓰는 곳이 셋이었던 것**이다(연결 상태 · 호출어 상태 · 단축키).
#   셋이 각자 «지금 덮어써도 되나»를 **글자로 추측**했다.
check("🚨 **글자를 보고 판단하지 않는다** (가드가 자기 자신을 막았다)",
      ".textContent.includes(" not in ui)
check("🔑 한 줄을 만드는 곳이 **하나다** (`idleLine()`)",
      "function idleLine()" in ui)
check("🚨 `idle-hint` 글자를 쓰는 자리가 **한 곳뿐이다**",
      ui.count("hint.textContent = idleLine()") == 1
      and ui.count("getElementById('idle-hint').textContent =") == 0,
      "쓰는 곳이 둘 이상이면 또 서로를 덮어쓴다")
check("🔑 다른 곳은 **상태만 바꾸고 다시 그리라고 말한다**",
      "connOk = ok;" in ui and "wakeReady = (s === 'ready');" in ui)
# 우선순위가 곧 그 함수다 — 녹음이 연결 상태보다 앞에 와야 «듣는 중»이 안 가려진다.
_line = between(ui, "function idleLine()", "function fillHotkeyChoices")
check("우선순위가 녹음 → 처리 → 연결 → 호출어 → 대기 순이다",
      _line.index("isRec") < _line.index("busy") < _line.index("connOk")
      < _line.index("wakeReady"))
check("헛깨어남이 **사람이 연 창을 닫지 않는다**",
      "if (!recAuto || busy) return;" in ui
      and "deactivate()" not in between(ui, "function closeIfSpurious()", "function stopVad()"))

print("")
print("=== ④ 🚨 고를 수 있는 키만 — **서버가 거부한다** ===")
# 🔑 「이미 쓰이는 키인가」는 알아낼 수 없다. `Ctrl+C` 는 전역 단축키가 아니라
#   앱 내부 단축키라 `globalShortcut.register()` 가 **성공한다.**
#   탐지로 푸는 문제가 아니라 **고를 수 있는 것을 좁히는** 문제다.
check("목록이 `config/settings.py` 에 있다", "hotkey_choices: ClassVar" in settings)
check("🚨 서버가 목록 밖을 **거부한다** (UI 만 막으면 샌다)",
      "if key not in Settings.hotkey_choices:" in server
      and '"status": "rejected"' in server)
check("기본값이 목록 안에 있다",
      Settings.model_fields["hotkey"].default in Settings.hotkey_choices)
check("🚨 `Ctrl+C` 는 고를 수 없다", "Ctrl+C" not in Settings.hotkey_choices)
check("🚨 조합키 없는 키도 고를 수 없다",
      all("+" in k for k in Settings.hotkey_choices))
check("서버가 목록을 UI 에 내려준다",
      '"hotkey_choices": list(Settings.hotkey_choices)' in server)
check("UI 가 **자기 목록을 안 들고 있다** (서버가 준 것으로 채운다)",
      "function fillHotkeyChoices" in ui and "Ctrl+Alt+P" not in ui)
check("UI 가 자유 입력이 아니다 (키 캡처가 없다)",
      'id="hotkey-select"' in ui and "hotkey-input" not in ui
      and "accelFrom" not in ui)
check("UI 가 서버의 거부를 **말한다**", "'rejected'" in ui and "고를 수 없는 키예요" in ui)
check("⚠️ `Alt+Space` 는 겹친다고 **표시한다** (고를 수는 있다)",
      "Windows 창 메뉴와 겹침" in ui and "Alt+Space" in Settings.hotkey_choices)
check("⚠️ `.env` 에 개행이 끼어들지 못한다 (BL-14 ③ 과 같은 자리)",
      "ch not in (chr(10), chr(13))" in server)

print("")
print("=== ⑤ 🔑 기본값의 주인이 **하나**인가 ===")
# 🚨 `main.js` 가 기본값을 들고 있으면, 서버 값을 받기 전까지 **틀린 키를 전역으로
#   가로챈다.** 그래서 이 프로세스는 **아무 것도 안 잡고** 렌더러가 알려 줄 때까지 기다린다.
check("🚨 `main.js` 에 기본값이 없다", "DEFAULT_HOTKEY" not in mainjs)
check("빈 값을 받으면 **아무 키도 안 잡는다**",
      "if (!want) return { ok: false" in mainjs)
check("UI 가 서버 기본값으로 덮어쓴다", "hotkeyDefault = data.hotkey_default" in ui)
check("서버가 기본값을 알려 준다",
      'Settings.model_fields["hotkey"].default' in server)
check("🚨 설정을 **못 읽어도** 단축키는 잡힌다 (안 그러면 아예 못 부른다)",
      "window.pluiz.setHotkey(hotkeyDefault)" in ui)

print("")
print("=== ⑥ 등록 실패를 **말하는가** (BL-13 의 자리) ===")
check("main.js 가 register() 의 반환값을 본다", "globalShortcut.register(want" in mainjs)
check("실패를 렌더러에 돌려준다", "{ ok: false" in mainjs and "{ ok: true" in mainjs)
check("🔑 실패하면 **쓰던 키로 되돌린다**",
      "if (previous && globalShortcut.register(previous" in mainjs)
check("preload 가 그 답을 건네준다",
      "setHotkey:" in preload and "invoke('set-hotkey'" in preload)
check("main 이 그 채널을 받는다", "ipcMain.handle('set-hotkey'" in mainjs)
check("UI 가 실패를 사용자에게 말한다", "다른 프로그램이 쓰고 있어요" in ui)
check("저장만으로 «된다»고 말하지 않는다",
      "await window.pluiz.setHotkey(data.hotkey)" in ui)
check("창을 띄울 때 저장해 둔 키를 **실제로 잡는다**", "window.pluiz.setHotkey(hk)" in ui)

print("")
print("=== ⑦ 호출어를 끄지 않는다 · 안내가 한 곳에서 나온다 ===")
check("웨이크워드는 그대로 돈다", "startWakeword();" in mainjs)
check("설정에 «말 거는 방법» 이 있다", "말 거는 방법" in ui)
# 🚨 안내문을 세 곳이 각자 쓰고 있어서, 어떤 경로로 들어오면 옛 문구가 남았다.
check("🔑 안내문이 **한 함수**에서만 만들어진다",
      "function idleLine()" in ui and ui.count("'더블클릭 · 🎙️'") == 0)
check("안내가 «말하기»와 «창 열기»를 갈라 말한다",
      "말하기 ${" in ui and "창 더블클릭" in ui)
check("호출어 로딩 중에도 «지금도 돼요»라고 말한다", "는 지금도 돼요" in ui)

print("")
print(chr(61) * 60)
print(f"결과: {passed}/{total} 통과")
print(chr(61) * 60)
sys.exit(0 if passed == total else 1)
