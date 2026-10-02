# -*- coding: utf-8 -*-
"""창 껍데기 — **위치 · 알림 · 접힌 상태의 표시** (BL-85·86·87 · 2026-10-02 실기)

실행: python tests/test_ui_shell.py

## 왜 이 테스트가 있나

2026-10-02 밤 실기에서 **셋이 한꺼번에 나왔다.** 셋 다 «기능이 없는 것»이 아니라
**«접어 두고 쓰는 평소 상태»를 아무도 안 본 것**이었다.

| | 증상 | 뿌리 |
|---|---|---|
| BL-85 | 창을 옮겨 놔도 **열면 제자리로 돌아간다** | `resizeTo()` 가 `getPos()` 로 화면 하단 중앙을 **매번 다시 계산**했다 |
| BL-86 | **접으면 알림 아이콘이 안 보인다** | 배지가 `a-header`(펼친 창) 안에만 있었다 |
| BL-87 | **물 마시기 알림이 창을 통째로 편다** | `onWatchNotify()` 가 **조건 없이** 폈다 |

## ⚠️ 여기서 고정하는 것은 «그렇게 적혀 있나» 까지다

🚨 **[BL-83] 이 말하는 바로 그 한계다.** `main.js`·렌더러는 Electron 런타임에서만
도는 코드라 여기서 실제로 못 돌린다. 2026-10-02 에 결함 셋이 mock 3,000건이 초록인
채로 살아 있었던 것이 이 자리다.

**그래서 이 파일은 «실기를 대신하지 않는다».** 고정하는 것은 *«고친 모양이
되돌아가지 않는다»* 이고, **된다/안 된다는 사람이 봐야 한다.**
→ [testing/MANUAL_TESTS.md](../docs/testing/MANUAL_TESTS.md)
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)

_MAIN = io.open(os.path.join(_ROOT, "electron-ui", "main.js"),
                encoding="utf-8").read()
_UI = io.open(os.path.join(_ROOT, "electron-ui", "renderer", "index.html"),
              encoding="utf-8").read()

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name}" + (f"   → {detail}" if detail else ""))


def _func(src, name):
    """`function name(...) { … }` 본문만 떼어 온다. (중괄호를 센다)"""
    i = src.find(f"function {name}(")
    if i < 0:
        return ""
    j = src.find("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    return src[i:]


# ═══ ① 🪟 옮겨 놓은 자리를 기억한다 (BL-85) ════════════════════════
print(f"{NL}=== ① \U0001f6a8 옮겨 놓은 자리를 기억한다 (BL-85) ===")

_resize = _func(_MAIN, "resizeTo")
check("resizeTo 를 찾았다", bool(_resize))
check("🚨 **화면 중앙을 다시 계산하지 않는다** (getPos 를 안 쓴다)",
      "getPos(" not in _resize, _resize)
check("   대신 **지금 창의 자리**에서 출발한다",
      "getBounds()" in _resize)
check("🔑 **아래 가운데**를 고정점으로 삼는다 (펼칠 때 아래로 자란다)",
      "anchorBounds" in _MAIN and "cur.y + cur.height - h" in _MAIN)
check("🚨 **화면 밖으로 안 내보낸다** (창이 안 보이면 죽은 줄 안다)",
      "clampToArea" in _MAIN and "clampToArea(" in _resize)
check("🔑 **지금 창이 올라가 있는 모니터**를 쓴다 (주 모니터 고정이 아니다)",
      "getDisplayMatching" in _resize, _resize)
check("getPos 는 **첫 배치에만** 남는다 (createWindow)",
      _MAIN.count("= getPos(") == 1,   # 주석의 언급은 세지 않는다
      f"{_MAIN.count('= getPos(')}곳")
check("왜 그런지 BL-85 를 근거로 적어 뒀다", "BL-85" in _MAIN)


# ═══ ② 🔔 접어 두면 **보인다** (BL-86) ═════════════════════════════
print(f"{NL}=== ② \U0001f514 접어 두면 보인다 (BL-86) ===")

_idle = _UI[_UI.find('class="idle-view"'):_UI.find('class="active-view"')]
check("접힌 알약에 **감시 배지**가 있다", 'id="watch-badge-idle"' in _idle, )
check("접힌 알약에 **약속 배지**가 있다", 'id="worker-badge-idle"' in _idle)
check("펼친 창에도 그대로 있다",
      'id="watch-badge"' in _UI and 'id="worker-badge"' in _UI)
# 🚨 **쓰는 자리를 하나로.** 두 곳을 각각 만지면 «한쪽만 갱신된다» — 이 저장소가
#   네 번 데인 모양이고, 이번엔 그 길을 **코드 안에** 만들 뻔했다.
check("🚨 배지를 쓰는 자리가 **하나다** (setBadge)",
      "function setBadge(" in _UI)
check("   그 하나가 **두 자리 모두** 본다",
      "name + '-idle'" in _UI)
check("🔒 배지를 **직접** 집어 쓰는 코드가 안 남았다",
      _UI.count("getElementById('worker-badge')") == 0
      and _UI.count("getElementById('watch-badge')") == 0)


# ═══ ③ 🚨 알림마다 **대우가 다르다** (BL-87) ════════════════════════
#
# 🙋 2026-10-02 결정 — 가르는 기준은 «사용자가 화면을 보고 있나» 다.
#   화면 감시는 **안 보고 있을 때** 쓰는 기능이라 창을 편다.
#   약속·알람·메일 기다리기는 **자기 일을 하는 중**이라 접힌 채로 알린다.
print(f"{NL}=== ③ \U0001f6a8 알림마다 대우가 다르다 (BL-87) ===")

_notify = _func(_UI, "onWatchNotify")
check("onWatchNotify 를 찾았다", bool(_notify))
check("🚨 **worker 알림은 조용하다** (약속·알람·메일 기다리기)",
      "m.source === 'worker'" in _notify and "quiet" in _notify, _notify)
check("🚨 **창을 펴는 길이 하나뿐이고, 조용한 쪽이 아니다**",
      _notify.count("showWindow()") == 1 and "} else {" in _notify, _notify)
check("   조용한 쪽은 **고리가 반짝인다**", "blinkNotify()" in _notify)
check("⚠️ **조용해도 말과 글은 그대로 나간다** (조용히 실패하지 않는다)",
      "addMsg('a'" in _notify and "playAudio(" in _notify)
check("🔑 감시 배지는 **worker 알림에 안 꺼진다** (예전 규칙 그대로)",
      "if (!quiet) setWatchBadge(false);" in _notify)

_blink = _func(_UI, "blinkNotify")
check("🚨 녹음·처리 중이면 **고리를 안 건드린다** (그 표시가 더 급하다)",
      "isRec || busy" in _blink, _blink)
check("🔑 애니메이션을 **다시 틀 수 있다** (연속 알림이 한 번만 보이면 안 된다)",
      "offsetWidth" in _blink)
check("끝나면 **표시를 지운다** (남으면 상태가 아니라 때가 된다)",
      "animationend" in _blink and "remove('notify')" in _blink)

# 🚨 **웨이크 신호와 다른 표시여야 한다** — 같은 표시면 사용자가
#   «내가 불렀나?» 와 «쟤가 말을 거나?» 를 구별할 수 없다.
check("🚨 알림 표시가 **웨이크(awake)와 다른 애니메이션**이다",
      "@keyframes ring-notify" in _UI and "@keyframes ring-wake" in _UI)
check("   색도 다르다",
      "rgba(52, 211, 153" in _UI and "rgba(251, 191, 36" in _UI)
check("왜 그런지 BL-87 을 근거로 적어 뒀다", "BL-87" in _UI)


print(f"{NL}결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
