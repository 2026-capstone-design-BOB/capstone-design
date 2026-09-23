"""
UI 요소 좌표 인식(find_ui_element) 검증 — mock (LLM·Windows·API 불필요)
실행: python tests/test_ui_locate.py

## 왜 이 테스트가 까다로워야 하나

`describe_screen`은 설명이 틀려도 사용자가 읽고 거른다. **좌표는 다르다.**
숫자라 그럴듯해 보이고, 다음 단계(좌표 기반 클릭)가 그대로 믿는다.
틀린 좌표는 조용히 엉뚱한 곳을 누르고 **되돌릴 수 없다.**

그래서 두 가지를 본다:

  ① **좌표를 지어내지 않는가** — 못 찾았으면 못 찾았다고 하는가.
     모델이 JSON 대신 잡담을 하거나, 뒤집힌 좌표를 주거나, 화면 전체를 박스로
     답해도 그걸 "찾았다"로 넘기면 안 된다.
  ② **좌표 변환이 맞는가** — 정규화 → 픽셀 → **화면 좌표**.
     창 원점을 빼먹으면 창이 화면 가운데 있을 때 좌표가 통째로 밀린다.
     이건 손으로 계산해 확인할 수 있고, 실기에서는 확인하기 어렵다.

⚠️ 실제 캡처·Gemini 호출은 하지 않는다. 라이브 영역이다.
"""
import _testenv  # noqa: F401  — 제품 로그를 더럽히지 않는다(tests/_testenv.py 참조)
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
# (tests/test_vision.py 와 같은 기법 — Linux CI에서 무관한 이유로 깨지지 않게)
if "tools" not in sys.modules:
    _stub = types.ModuleType("tools")
    _stub.__path__ = [os.path.join(_ROOT, "tools")]
    sys.modules["tools"] = _stub

_spec = importlib.util.spec_from_file_location(
    "tools.vision", os.path.join(_ROOT, "tools", "vision.py"))
V = importlib.util.module_from_spec(_spec)
sys.modules["tools.vision"] = V
_spec.loader.exec_module(V)


# ══════════════════════════════════════════════════════════════════
print("=== ① 좌표를 지어내지 않는다 ===")
print("    ※ 여기가 뚫리면 다음 단계(클릭)가 엉뚱한 곳을 누른다")

BAD = [
    ("빈 응답",              ""),
    ("공백만",               "   "),
    ("JSON 아닌 잡담",       "저장 버튼은 오른쪽 위에 있는 것 같아요"),
    ("깨진 JSON",            '{"found": true, "box": [10, 20,'),
    ("found=false",          '{"found": false, "reason": "화면에 없습니다"}'),
    ("box 개수 부족",        '{"found": true, "box": [10, 20, 30]}'),
    ("box가 숫자가 아님",    '{"found": true, "box": ["a", "b", "c", "d"]}'),
    ("좌표가 범위 초과",     '{"found": true, "box": [10, 20, 30, 1500]}'),
    ("좌표가 음수",          '{"found": true, "box": [-5, 20, 300, 400]}'),
    ("좌표 순서 뒤집힘",     '{"found": true, "box": [800, 20, 300, 400]}'),
    ("폭이 0",               '{"found": true, "box": [100, 200, 300, 200]}'),
    ("빈 배열",              '[]'),
    # 후보가 여럿이면 **고르지 않는다.** 조용히 첫 번째를 집으면 사용자는 다른
    # 후보가 있었다는 걸 모른 채 엉뚱한 것을 클릭하게 된다.
    ("후보가 여럿",          '[{"found": true, "box": [1,2,3,4]}, '
                             '{"found": true, "box": [5,6,7,8]}]'),
]
for name, raw in BAD:
    r = V.parse_ui_box(raw)
    check(f"못 찾은 것으로 처리 — {name}",
          r["found"] is False and bool(r.get("reason")), f"→ {r}")

# 화면 전체를 박스로 답하는 건 "모르겠다"를 그림으로 그린 것이다
r = V.parse_ui_box('{"found": true, "box": [0, 0, 1000, 1000]}')
check("화면 전체를 가리키면 좌표로 쓰지 않는다", r["found"] is False, f"→ {r}")
r = V.parse_ui_box('{"found": true, "box": [10, 10, 990, 990]}')
check("거의 전체(96%)도 거른다", r["found"] is False, f"→ {r}")


print("\n=== ② 제대로 된 응답은 통과한다 ===")
r = V.parse_ui_box('{"found": true, "box": [100, 200, 300, 400], "label": "저장 버튼"}')
check("찾음으로 처리", r["found"] is True, f"→ {r}")
check("좌표 보존", r["box"] == (100.0, 200.0, 300.0, 400.0), f"→ {r.get('box')}")
check("라벨 보존", r["label"] == "저장 버튼", f"→ {r.get('label')}")

fenced = '```json\n{"found": true, "box": [100, 200, 300, 400], "label": "X"}\n```'
check("```json 펜스를 견딘다", V.parse_ui_box(fenced)["found"] is True)
chatty = '네, 찾았습니다!\n{"found": true, "box": [1, 2, 3, 4], "label": "X"}\n도움이 됐길 바라요.'
check("앞뒤 잡담을 견딘다", V.parse_ui_box(chatty)["found"] is True)
check("label 없어도 통과", V.parse_ui_box('{"found": true, "box": [1,2,3,4]}')["found"] is True)
# 배열이어도 **하나뿐이면** 형식 문제일 뿐이니 받아준다. 여기서 거절하면 실제로
# 찾은 걸 "못 찾았다"고 답하게 되는데, 그것도 거짓말이다.
check("객체 하나짜리 배열은 받아준다",
      V.parse_ui_box('[{"found": true, "box": [1,2,3,4], "label": "X"}]')["found"] is True)
_amb = V.parse_ui_box('[{"found": true, "box": [1,2,3,4]}, {"found": true, "box": [5,6,7,8]}]')
check("후보가 여럿이면 개수를 알려준다", "2개" in _amb.get("reason", ""), f"→ {_amb}")


print("\n=== ③ 좌표 변환 — 손으로 계산해 맞춘다 ===")
# 1000×1000 이미지, 원점 (0,0). box [ymin,xmin,ymax,xmax] = [100,200,300,400]
#   x: 200/1000*1000=200 ~ 400/1000*1000=400 → 중심 300, 폭 200
#   y: 100 ~ 300                              → 중심 200, 높이 200
loc = V.box_to_screen((100, 200, 300, 400), (1000, 1000))
check("중심점", loc["center"] == (300, 200), f"→ {loc['center']}")
check("사각형", loc["rect"] == (200, 100, 400, 300), f"→ {loc['rect']}")
check("크기", loc["size"] == (200, 200), f"→ {loc['size']}")

# 🚨 창 원점을 더해야 화면 좌표가 된다. 빼먹으면 창이 화면 가운데 있을 때 통째로 밀린다
loc2 = V.box_to_screen((100, 200, 300, 400), (1000, 1000), origin=(1920, 50))
check("🚨 창 원점이 더해진다 (중심)", loc2["center"] == (2220, 250), f"→ {loc2['center']}")
check("🚨 창 원점이 더해진다 (사각형)",
      loc2["rect"] == (2120, 150, 2320, 350), f"→ {loc2['rect']}")
check("원점을 더해도 크기는 그대로", loc2["size"] == loc["size"], f"→ {loc2['size']}")

# 이미지 비율이 정사각형이 아닐 때 x·y가 각자 자기 축으로 환산되는지
loc3 = V.box_to_screen((0, 0, 500, 500), (1600, 900))
check("가로세로가 각자 환산된다", loc3["rect"] == (0, 0, 800, 450), f"→ {loc3['rect']}")

# 축소 배율은 상쇄된다 — 정규화 좌표는 '보낸 이미지' 기준이고 축소는 비율 유지다.
# 그래서 원본 크기만 넣으면 되고, 축소 여부는 결과에 영향을 주면 안 된다.
big = V.box_to_screen((250, 250, 750, 750), (3840, 2160))
check("4K 원본에서도 비율로 계산된다",
      big["center"] == (1920, 1080), f"→ {big['center']}")


print("\n=== ④ 도구 계약 ===")
d = V.find_ui_element.description
check("도구 설명에 좌표를 알려준다고 명시", "좌표" in d, f"→ {d[:60]}")
check("못 찾으면 지어내지 않는다고 명시", "만들어내지 않고" in d or "찾지 못했다" in d, f"→ {d}")
check("target 인자 설명 존재", "target" in d)
check("window 인자 설명 존재", "window" in d)

src = open(os.path.join(_ROOT, "tools", "vision.py"), encoding="utf-8").read()
check("프롬프트가 추측을 금지한다", "추측해서 좌표를 만들지 마세요" in src)
check("프롬프트가 좌표 순서를 명시한다", "[ymin, xmin, ymax, xmax]" in src)
check("캡처 원점을 tools/system 에서 가져온다 (직접 구현하지 않음)",
      "capture_origin" in src)


print("\n=== ⑤ 원점을 못 구하면 좌표를 내지 않는다 ===")
# 창 위치를 모르면 창 기준 좌표밖에 없는데, 그걸 화면 좌표인 척 내보내면
# 다음 단계가 엉뚱한 곳을 누른다. 캡처보다 **먼저** 원점을 구하는 이유다.
_sys_stub = types.ModuleType("tools.system")
def _boom_origin(window=""):
    raise ValueError("창을 찾을 수 없습니다")
_sys_stub.capture_origin = _boom_origin
_sys_stub.resolve_window_hwnd = lambda w: (0, w)
_sys_stub.window_screen_rect = lambda h: (0, 0, 1, 1)
_sys_stub.take_screenshot = None      # 여기까지 오면 안 된다 (오면 TypeError로 드러남)
_saved = sys.modules.get("tools.system")
sys.modules["tools.system"] = _sys_stub
try:
    r = V.find_ui_element.invoke({"target": "저장 버튼", "window": "메모장"})
    check("✗ 로 답한다", r.startswith("✗"), f"→ {r[:70]}")
    check("좌표를 지어내지 않는다", "(" not in r.split("좌표")[0] or "찾았습니다" not in r,
          f"→ {r[:70]}")
    check("사유를 알린다", "위치를 확인하지 못했습니다" in r, f"→ {r[:90]}")
finally:
    if _saved is not None:
        sys.modules["tools.system"] = _saved
    else:
        del sys.modules["tools.system"]


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
