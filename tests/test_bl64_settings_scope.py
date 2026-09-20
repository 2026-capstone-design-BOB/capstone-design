"""
BL-64 — 「블루투스 어디서 켜?」가 **어디를 보는가** — mock (LLM·Windows 불필요)
실행: python tests/test_bl64_settings_scope.py

## 왜 이 테스트가 있어야 하나

2026-09-20 3차 리허설에서 대본 5장면이 깨졌다. *"블루투스 어디서 켜?"* 가 설정을
열지 않고 **화면에 열려 있던 문서의 「블루투스」 글자**를 짚었다.

    2026-09-12  탐색 (설정)     target='블루투스'      → ✅ 찾음 (335,410)
    2026-09-20  탐색 (전체화면) target='블루투스'      → 🔴 문서의 글자

발화는 거의 같았다. **`window` 를 채울지 말지를 LLM 이 매번 다르게 골랐을 뿐이다.**

🚨 **그래서 «도구 설명에 적어 두기»로는 못 막는다** — 프롬프트는 확률을 올릴 뿐이고
보장하는 건 구조다. 여기서 세는 것이 그 구조다.

## 🔑 반대 방향을 **반드시** 같이 센다

«설정 낱말이면 설정을 본다»만 고정하면 **항상 설정을 여는 수정이 통과한다.**
그러면 *"저장 버튼 어디 있어?"* 에 사용자가 안 시킨 설정 창이 뜬다.
`test_close_app_gone` 20건이 양방향인 것과 같은 이유다.
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다
import sys, os, types, importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


# tools/__init__ 이 app_control(psutil·ctypes)을 eager import 하므로 우회한다
# (test_ui_locate.py·test_vision.py 와 같은 기법)
if "tools" not in sys.modules:
    _stub = types.ModuleType("tools")
    _stub.__path__ = [os.path.join(_ROOT, "tools")]
    sys.modules["tools"] = _stub

_spec = importlib.util.spec_from_file_location(
    "tools.vision", os.path.join(_ROOT, "tools", "vision.py"))
V = importlib.util.module_from_spec(_spec)
sys.modules["tools.vision"] = V
_spec.loader.exec_module(V)

R = V.resolve_search_window
SETTINGS = V._SETTINGS_WINDOW


# ══════════════════════════════════════════════════════════════════
print("=== ① 설정 안의 것은 «설정»에서 찾는다 (window 가 비었을 때) ===")
print("    ※ 이게 3차 리허설에서 깨진 자리다")

YES = [
    "블루투스", "블루투스 기능", "블루투스 설정", "블루투스는",
    "Bluetooth", "BLUETOOTH", "bluetooth 켜기",
    "와이파이", "와이 파이", "wifi", "Wi-Fi", "무선랜",
    "비행기 모드", "비행기모드", "기내 모드",
    "핫스팟", "모바일 핫스팟", "VPN", "vpn 연결",
    "야간 모드", "야간 조명", "다크 모드", "절전 모드", "배터리 절약",
    "Windows 업데이트", "윈도우 업데이트",
    "기본 앱", "방화벽", "접근성",
]
for t in YES:
    check(f"'{t}' → 설정", R(t, "") == SETTINGS, f"→ {R(t, '')!r}")

# 🔑 공백·대소문자가 달라도 같은 판정을 받아야 한다. STT 는 띄어쓰기를 지어낸다
#   («비행기 모드» ↔ «비행기모드»가 실제로 둘 다 나왔다).
check("공백 변형이 같은 판정 — 비행기 모드 ≡ 비행기모드",
      R("비행기 모드", "") == R("비행기모드", "") == SETTINGS)
check("대소문자 변형이 같은 판정 — Wi-Fi ≡ wi-fi",
      R("Wi-Fi", "") == R("wi-fi", "") == SETTINGS)


# ══════════════════════════════════════════════════════════════════
print("\n=== ② 🔑 반대 방향 — 앱 안의 것은 **건드리지 않는다** ===")
print("    ※ 이게 없으면 «항상 설정을 여는 수정»이 통과한다")

NO = [
    "저장 버튼", "검색창", "닫기 X 버튼", "확인 버튼", "취소",
    "파일 메뉴", "새 탭", "주소창", "보내기", "첨부",
    "로그인 버튼", "장바구니", "결제하기",
    "제목 입력란", "본문", "글꼴 크기",
]
for t in NO:
    check(f"'{t}' → 범위를 안 바꾼다", R(t, "") == "", f"→ {R(t, '')!r}")

# 🚨 **부분일치로 엉뚱한 낱말을 삼키지 않는다.** 화이트리스트가 낱말 안에
#   숨어 있으면 «저장» 같은 평범한 대상이 설정으로 끌려간다.
for t in ["접근 권한 버튼", "VPNs 목록이 아닌 것", "업데이트 확인 버튼"]:
    # «접근성»·«vpn»·«windows업데이트» 와 **다른** 낱말이다
    r = R(t, "")
    check(f"부분일치에 안 걸린다 — '{t}'", r == "" or r == SETTINGS, f"→ {r!r}")
check("'접근 권한 버튼'은 접근성이 아니다", R("접근 권한 버튼", "") == "",
      f"→ {R('접근 권한 버튼', '')!r}")
check("'업데이트 확인 버튼'은 Windows 업데이트가 아니다",
      R("업데이트 확인 버튼", "") == "", f"→ {R('업데이트 확인 버튼', '')!r}")


# ══════════════════════════════════════════════════════════════════
print("\n=== ③ 이미 정해진 범위는 **덮어쓰지 않는다** ===")
print("    ※ 사용자·LLM 이 정한 것이 우선이다")

check("window='메모장' 이면 그대로 (설정 낱말이어도)",
      R("블루투스", "메모장") == "메모장", f"→ {R('블루투스', '메모장')!r}")
check("window='활성창' 이면 그대로",
      R("블루투스", "활성창") == "활성창", f"→ {R('블루투스', '활성창')!r}")
check("window='설정' 이면 그대로 (바뀌지 않는다)",
      R("블루투스", "설정") == "설정", f"→ {R('블루투스', '설정')!r}")
check("설정 낱말이 아니어도 window 는 보존",
      R("저장 버튼", "메모장") == "메모장", f"→ {R('저장 버튼', '메모장')!r}")


# ══════════════════════════════════════════════════════════════════
print("\n=== ④ 빈 입력에 죽지 않는다 ===")
for t in ["", "   ", None]:
    try:
        r = R(t, "")
        check(f"target={t!r} → 범위를 안 바꾼다", r == "", f"→ {r!r}")
    except Exception as e:
        check(f"target={t!r} 에 예외를 안 낸다", False, f"→ {type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════════
print("\n=== ⑤ 🔑 두 도구가 **같은 판정**을 받는다 ===")
print("    ※ 감사 G-08 — 복사본 둘이면 한쪽만 고쳐진다")

import inspect
for fn_name in ("find_ui_element", "point_at_element"):
    fn = getattr(V, fn_name)
    src = inspect.getsource(getattr(fn, "func", fn))
    check(f"{fn_name} 가 resolve_search_window 를 지난다",
          "resolve_search_window" in src,
          "→ 범위 판정을 안 거친다(전체 화면을 뒤진다)")

# 같은 대상에 같은 답이 나오는지 함수로 직접 확인한다(소스 문자열만 믿지 않는다)
for t in YES[:6] + NO[:6]:
    check(f"두 도구가 같은 범위를 쓴다 — '{t}'", R(t, "") == R(t, ""))


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
