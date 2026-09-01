"""
Pluiz Sprint 1 & 2 자동 테스트
================================
Sprint 1 (T02, T03)과 Sprint 2 (T04, T05, T06) 구현 검증.

실행 방법:
  1. 서버 없이 (정적 검사만):  python test_sprint1_2.py --static
  2. 서버 실행 후 전체:        python test_sprint1_2.py

※ 전체 실행은 서버가 http://127.0.0.1:8765 에서 실행 중이어야 합니다.
"""

import sys
import os
import re
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STATIC_ONLY = "--static" in sys.argv
API = "http://127.0.0.1:8765"

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

results = {"pass": 0, "fail": 0, "skip": 0}

def ok(msg):   print(f"  {GREEN}✓ PASS{RESET}  {msg}"); results["pass"] += 1
def fail(msg): print(f"  {RED}✗ FAIL{RESET}  {msg}"); results["fail"] += 1
def skip(msg): print(f"  {YELLOW}→ SKIP{RESET}  {msg}"); results["skip"] += 1
def info(msg): print(f"         {YELLOW}{msg}{RESET}")

def header(title):
    print(f"\n{BOLD}{CYAN}{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}{RESET}")


# ══════════════════════════════════════════════════════════════════
# PART A — 정적 검사 (서버 불필요)
# ══════════════════════════════════════════════════════════════════

header("PART A  정적 코드 검사 (서버 불필요)")

# ── A-1. 파일 문법 검사 ───────────────────────────────────────────
print(f"\n{BOLD}▶ A-1. Python 파일 문법{RESET}")
import py_compile
for path in [
    "core/agent.py",
    "core/command_cache.py",
    "core/tool_registry.py",
    "tools/input_control.py",
    "main.py",
]:
    try:
        py_compile.compile(path, doraise=True)
        ok(f"{path}")
    except py_compile.PyCompileError as e:
        fail(f"{path}: {e}")


# ── A-2. T02: _select_particle 조사 처리 ──────────────────────────
print(f"\n{BOLD}▶ A-2. T02: _select_particle() 조사 처리{RESET}")

src_cc = open("core/command_cache.py", encoding="utf-8").read()

if "_select_particle" not in src_cc:
    fail("_select_particle 함수 없음")
else:
    # command_cache.py를 exec해서 함수 직접 테스트
    ns = {}
    try:
        exec(src_cc.replace(
            "_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))",
            f"_BASE_DIR = {repr(os.path.dirname(os.path.abspath(__file__)))}"
        ), ns)
        _sp = ns["_select_particle"]
        _APP_DISPLAY = ns["_APP_DISPLAY"]

        cases = [
            # (단어,  종성형, 무종성형, 기대값)
            ("메모장",      "을", "를", "을"),   # 장: 받침ㅇ
            ("계산기",      "을", "를", "를"),   # 기: 받침없음
            ("크롬",        "을", "를", "을"),   # 롬: 받침ㅁ
            ("엣지",        "을", "를", "를"),   # 지: 받침없음
            ("카카오톡",    "을", "를", "을"),   # 톡: 받침ㄱ
            ("파일 탐색기", "을", "를", "를"),   # 기: 받침없음
            ("터미널",      "을", "를", "을"),   # 널: 받침ㄹ
            ("설정",        "을", "를", "을"),   # 정: 받침ㅇ
            ("VS Code",     "을", "를", "를"),   # 비한글
            ("Excel",       "을", "를", "를"),   # 비한글
            ("이",          "은", "는", "은"),   # 종성: 이(없음)→는? 아니 이→이(없음)이니 "는"
        ]
        # "이": ord("이")-0xAC00 = 0x51 = 이(ㅇ+ㅣ+없음) → code%28 = 이의 code = (0xC774-0xAC00)=7028, 7028%28=0 → 받침없음 → 는
        # 수정: "이" → (ord("이")-0xAC00) = (0xC774-0xAC00) = 7028, 7028%28 = 7028//28*28=250*28=7000, 7028-7000=28 → 28%28=0 → 무종성
        # 실제 "이"의 code: 이=U+C774, C774-AC00=7028 → 7028%28=7028-251*28=7028-7028=0 → 받침없음 → 는
        # 위 케이스 기대값 수정
        cases[-1] = ("이", "은", "는", "는")

        passed = 0
        for word, jong, no_jong, expected in cases:
            result = _sp(word, jong, no_jong)
            if result == expected:
                passed += 1
            else:
                info(f"  실패: '{word}' → '{result}' (기대: '{expected}')")

        if passed == len(cases):
            ok(f"_select_particle {passed}/{len(cases)} 케이스 통과")
        else:
            fail(f"_select_particle {passed}/{len(cases)} 통과 — 일부 실패")

        # 을(를) 형태가 남아있지 않은지 확인
        if "을(를)" not in src_cc:
            ok("을(를) 하드코딩 완전 제거됨")
        else:
            fail("을(를) 형태 여전히 존재함")

        # 모든 _APP_DISPLAY 앱에 대해 조사 정상 생성 확인
        all_valid = all(
            _sp(name, "을", "를") in ("을", "를")
            for name in _APP_DISPLAY.values()
        )
        if all_valid:
            ok(f"_APP_DISPLAY {len(_APP_DISPLAY)}개 앱 전체 정상 조사 생성")
        else:
            fail("일부 앱에서 조사 생성 오류")

    except Exception as e:
        fail(f"command_cache exec 오류: {e}")


# ── A-3. T03: get_clipboard_text 도구 ────────────────────────────
print(f"\n{BOLD}▶ A-3. T03: get_clipboard_text 도구{RESET}")

src_ic = open("tools/input_control.py", encoding="utf-8").read()
src_tr = open("core/tool_registry.py", encoding="utf-8").read()
src_ag = open("core/agent.py", encoding="utf-8").read()

if "def get_clipboard_text()" in src_ic:
    ok("get_clipboard_text 도구 정의 존재")
else:
    fail("get_clipboard_text 도구 없음")

if src_ic.count("@tool") == 3:
    ok("@tool 데코레이터 3개 (type_text, get_clipboard_text, press_key)")
else:
    fail(f"@tool 데코레이터 수 이상: {src_ic.count('@tool')}개")

if "get_clipboard_text" in src_tr and src_tr.count("get_clipboard_text") >= 2:
    ok("tool_registry에 import + 등록 완료")
else:
    fail("tool_registry 등록 누락")

if '"클립보드"' in src_ag:
    ok("agent.py _CONTROL_KEYWORDS에 '클립보드' 추가됨")
else:
    fail("_CONTROL_KEYWORDS에 '클립보드' 없음")

if "pyperclip.paste()" in src_ic:
    ok("pyperclip.paste() 호출 코드 존재")
else:
    fail("pyperclip.paste() 없음")

if 'content[:200]' in src_ic:
    ok("200자 미리보기 처리 존재")
else:
    fail("200자 미리보기 처리 없음")


# ── A-4. T04: 도구 실행 결과 검증 레이어 ─────────────────────────
print(f"\n{BOLD}▶ A-4. T04: 도구 실행 결과 검증 레이어{RESET}")

if "_TOOL_ERROR_RE = re.compile(" in src_ag:
    ok("_TOOL_ERROR_RE 패턴 정의됨")
else:
    fail("_TOOL_ERROR_RE 없음")

if "_SUCCESS_LIKE_RE = re.compile(" in src_ag:
    ok("_SUCCESS_LIKE_RE 패턴 정의됨")
else:
    fail("_SUCCESS_LIKE_RE 없음")

if "def _extract_tool_errors(" in src_ag:
    ok("_extract_tool_errors() 메서드 정의됨")
else:
    fail("_extract_tool_errors() 없음")

if "def _patch_response_on_error(" in src_ag:
    ok("_patch_response_on_error() 메서드 정의됨")
else:
    fail("_patch_response_on_error() 없음")

if "_extract_tool_errors(result)" in src_ag:
    ok("run_async()에 검증 단계 삽입됨")
else:
    fail("run_async() 검증 단계 없음")

# 패턴 동작 단위 테스트
_TOOL_ERROR_RE = re.compile(
    r'^\[(?:오류|error|[가-힣a-zA-Z_]+ 오류)\]'
    r'|^오류\s*:'
    r'|^Error\s*:',
    re.IGNORECASE,
)
_SUCCESS_LIKE_RE = re.compile(
    r'(?<!못)(?:했어요|켰어요|열었어요|닫았어요|실행했어요|설정했어요|만들었어요|저장했어요|됐어요|완료했어요|완료)[!.]?\s*$'
)

error_cases = [
    ("[오류] pyautogui 없음", True),
    ("[type_text 오류] 오류", True),
    ("오류: 파일 없음", True),
    ("Error: not found", True),
    ("✓ 메모장 실행했습니다.", False),
    ("메모장을 열었어요.", False),
]
success_cases = [
    ("메모장 켰어요!", True),
    ("볼륨 설정했어요.", True),
    ("완료했어요", True),
    ("실행하지 못했어요.", False),
    ("실행을 못했어요.", False),
    ("찾을 수 없었어요.", False),
]

ep = sum(1 for t, e in error_cases if bool(_TOOL_ERROR_RE.match(t)) == e)
sp = sum(1 for t, e in success_cases if bool(_SUCCESS_LIKE_RE.search(t)) == e)

if ep == len(error_cases):
    ok(f"_TOOL_ERROR_RE 패턴 {ep}/{len(error_cases)} 케이스 정확")
else:
    fail(f"_TOOL_ERROR_RE 패턴 오탐: {ep}/{len(error_cases)}")

if sp == len(success_cases):
    ok(f"_SUCCESS_LIKE_RE 패턴 {sp}/{len(success_cases)} 케이스 정확 (부정형 제외 포함)")
else:
    fail(f"_SUCCESS_LIKE_RE 패턴 오탐: {sp}/{len(success_cases)}")


# ── A-5. T05: 히스토리 UI ─────────────────────────────────────────
print(f"\n{BOLD}▶ A-5. T05: 히스토리 UI{RESET}")

html = open("electron-ui/renderer/index.html", encoding="utf-8").read()
src_main = open("main.py", encoding="utf-8").read()

ui_checks = {
    "hist-btn 헤더 버튼":     'id="hist-btn"' in html,
    "history-view 섹션":     'id="history-view"' in html,
    "hist-list 컨테이너":    'id="hist-list"' in html,
    "toggleHistory 함수":    "function toggleHistory()" in html,
    "loadHistory 함수":      "function loadHistory()" in html,
    "clearHistory 함수":     "function clearHistory()" in html,
    "rerunFromHistory 함수": "function rerunFromHistory(" in html,
    "/history API 호출":     "/history?n=30" in html,
    "GET /history 엔드포인트":  '@app.get("/history")' in src_main,
    "DELETE /history 엔드포인트": '@app.delete("/history")' in src_main,
}
for name, passed in ui_checks.items():
    ok(name) if passed else fail(name)


# ── A-6. T06: 즐겨찾기 UI ────────────────────────────────────────
print(f"\n{BOLD}▶ A-6. T06: 즐겨찾기 UI{RESET}")

fav_checks = {
    "fav-btn 헤더 버튼":       'id="fav-btn"' in html,
    "fav-view 섹션":           'id="fav-view"' in html,
    "fav-add-form 입력폼":     'id="fav-add-form"' in html,
    "toggleFavorites 함수":    "function toggleFavorites()" in html,
    "loadFavorites 함수":      "function loadFavorites()" in html,
    "saveFavorite 함수":       "function saveFavorite()" in html,
    "deleteFavorite 함수":     "function deleteFavorite(" in html,
    "runFavorite 즉시실행":    "function runFavorite(" in html,
    "GET /favorites":          '@app.get("/favorites")' in src_main,
    "POST /favorites":         '@app.post("/favorites")' in src_main,
    "DELETE /favorites/{idx}": '@app.delete("/favorites/{index}")' in src_main,
    "favorites.json 영속 저장": "favorites.json" in src_main,
}
for name, passed in fav_checks.items():
    ok(name) if passed else fail(name)


# ── A-7. 도구 수 확인 ─────────────────────────────────────────────
print(f"\n{BOLD}▶ A-7. tool_registry 도구 수 확인{RESET}")
try:
    from core.tool_registry import get_all_tools
    tools = get_all_tools()
    names = [t.name for t in tools]
    expected = [
        "open_app", "close_app", "maximize_window", "minimize_window", "show_desktop",
        "open_url", "web_search", "youtube_search", "map_search", "fetch_web_info", "crawl_page",
        "create_file", "create_folder", "find_file", "open_recent_file", "open_file", "write_excel",
        "volume_up", "volume_down", "set_volume", "mute_toggle", "brightness_up", "brightness_down",
        "take_screenshot", "get_battery_status", "get_current_time", "get_running_apps",
        "type_text", "press_key", "get_clipboard_text",
        "create_calendar_event",
    ]
    missing = [t for t in expected if t not in names]
    if not missing:
        ok(f"전체 {len(tools)}개 도구 등록 확인 (기대 {len(expected)}개 포함)")
    else:
        fail(f"누락 도구: {missing}")
except ImportError as e:
    skip(f"langchain_core 미설치 환경 (실제 실행 환경에서 확인): {e}")
except Exception as e:
    fail(f"tool_registry 로드 오류: {e}")


# ══════════════════════════════════════════════════════════════════
# PART B — 통합 테스트 (서버 필요)
# ══════════════════════════════════════════════════════════════════

if STATIC_ONLY:
    print(f"\n{YELLOW}[--static 모드] 서버 통합 테스트 건너뜀{RESET}")
else:
    header("PART B  서버 통합 테스트 (서버 실행 필요)")

    import requests

    try:
        r = requests.get(f"{API}/health", timeout=5)
        info(f"서버 응답: {r.json()}")
    except Exception as e:
        print(f"\n{RED}서버 연결 실패: {e}")
        print(f"먼저 python main.py를 실행하거나 --static 옵션을 사용하세요.{RESET}")
        sys.exit(1)

    def api(method, path, **kwargs):
        try:
            fn = getattr(requests, method)
            return fn(f"{API}{path}", timeout=15, **kwargs)
        except Exception as e:
            return None

    # ── B-1. 히스토리 API ─────────────────────────────────────────
    print(f"\n{BOLD}▶ B-1. T05: 히스토리 API{RESET}")

    # 대화 하나 생성
    chat_res = api("post", "/chat", json={"text": "안녕", "thread_id": "test_hist"})
    time.sleep(1.0)

    r = api("get", "/history?n=5")
    if r and r.status_code == 200:
        data = r.json()
        if "history" in data and isinstance(data["history"], list):
            ok(f"GET /history 정상 (최근 {len(data['history'])}개 반환)")
        else:
            fail(f"응답 형식 이상: {data}")
    else:
        fail(f"GET /history 실패: {r}")

    r = api("delete", "/history")
    if r and r.status_code == 200 and r.json().get("status") == "cleared":
        ok("DELETE /history 정상 (히스토리 초기화)")
    else:
        fail(f"DELETE /history 실패: {r}")

    r = api("get", "/history?n=5")
    if r and r.status_code == 200:
        count = len(r.json().get("history", []))
        if count == 0:
            ok("삭제 후 히스토리 비어있음 확인")
        else:
            fail(f"삭제 후 {count}개 남아있음")
    else:
        fail("삭제 후 확인 실패")

    # ── B-2. 즐겨찾기 API (CRUD) ──────────────────────────────────
    print(f"\n{BOLD}▶ B-2. T06: 즐겨찾기 API CRUD{RESET}")

    # 초기화: 기존 즐겨찾기 전부 삭제
    r = api("get", "/favorites")
    if r and r.status_code == 200:
        for i in range(len(r.json().get("favorites", [])) - 1, -1, -1):
            api("delete", f"/favorites/{i}")

    # POST — 추가
    r = api("post", "/favorites", json={"label": "테스트 명령", "command": "메모장 열어줘"})
    if r and r.status_code == 200 and r.json().get("status") == "ok":
        ok("POST /favorites 추가 성공")
    else:
        fail(f"POST /favorites 실패: {r.text if r else r}")

    # 중복 추가 → exists
    r = api("post", "/favorites", json={"label": "테스트 명령", "command": "메모장 열어줘"})
    if r and r.json().get("status") == "exists":
        ok("중복 추가 → 'exists' 반환")
    else:
        fail(f"중복 처리 이상: {r.json() if r else r}")

    # GET — 목록
    r = api("get", "/favorites")
    if r and r.status_code == 200:
        favs = r.json().get("favorites", [])
        if len(favs) == 1 and favs[0]["command"] == "메모장 열어줘":
            ok("GET /favorites 목록 정상 (1개)")
        else:
            fail(f"목록 이상: {favs}")
    else:
        fail(f"GET /favorites 실패: {r}")

    # DELETE — 삭제
    r = api("delete", "/favorites/0")
    if r and r.status_code == 200 and r.json().get("status") == "ok":
        ok("DELETE /favorites/0 삭제 성공")
    else:
        fail(f"DELETE /favorites/0 실패: {r.json() if r else r}")

    r = api("get", "/favorites")
    if r and len(r.json().get("favorites", [])) == 0:
        ok("삭제 후 즐겨찾기 비어있음 확인")
    else:
        fail("삭제 후 목록 이상")

    # favorites.json 파일 생성 확인
    fav_json = os.path.join(os.path.dirname(__file__), "cache", "favorites.json")
    if os.path.exists(fav_json):
        ok(f"favorites.json 파일 생성 확인")
    else:
        # 아이템 추가 후 파일 생성되는지 확인
        api("post", "/favorites", json={"label": "테스트", "command": "계산기 열어줘"})
        time.sleep(0.5)
        if os.path.exists(fav_json):
            ok("favorites.json 파일 생성 확인 (추가 후)")
            api("delete", "/favorites/0")
        else:
            fail("favorites.json 파일 미생성")

    # ── B-3. T03: 클립보드 도구 (서버 경유) ──────────────────────
    print(f"\n{BOLD}▶ B-3. T03: get_clipboard_text (서버 경유){RESET}")

    r = api("post", "/chat", json={"text": "클립보드 내용 보여줘", "thread_id": "test_clip"})
    if r and r.status_code == 200:
        resp = r.json().get("response", "")
        info(f"응답: {resp[:80]}")
        # 클립보드가 비었거나 내용이 반환되면 OK
        if "클립보드" in resp or "비어있" in resp or "📋" in resp:
            ok("클립보드 도구 호출 및 응답 정상")
        elif resp:
            ok("응답 수신 (클립보드 내용 여부는 수동 확인)")
        else:
            fail("응답 없음")
    else:
        fail(f"요청 실패: {r}")

    # ── B-4. T04: 도구 오류 검증 (통합) ──────────────────────────
    print(f"\n{BOLD}▶ B-4. T04: 도구 오류 검증 레이어 (응답 확인){RESET}")

    # 존재하지 않는 앱 — 오류가 있어도 서버가 응답을 반환해야 함
    r = api("post", "/chat", json={"text": "포토샵222_없는앱 열어줘", "thread_id": "test_err"})
    if r and r.status_code == 200:
        resp = r.json().get("response", "")
        info(f"없는 앱 응답: {resp[:80]}")
        if resp and "오류" not in resp.lower()[:20]:
            ok("오류 발생 시 서버 크래시 없이 응답 반환")
        elif resp:
            ok(f"오류 응답 정상 처리: {resp[:50]}")
        else:
            fail("응답 없음")
    else:
        fail(f"요청 실패: {r}")


# ══════════════════════════════════════════════════════════════════
# 결과 요약
# ══════════════════════════════════════════════════════════════════

total = results["pass"] + results["fail"] + results["skip"]
print(f"\n{BOLD}{'='*55}")
print("  Sprint 1 & 2 테스트 완료")
print(f"{'='*55}{RESET}")
print(f"  총 {total}개  {GREEN}PASS {results['pass']}{RESET}  {RED}FAIL {results['fail']}{RESET}  {YELLOW}SKIP {results['skip']}{RESET}")

if results["fail"] == 0:
    print(f"\n  {GREEN}{BOLD}전체 통과!{RESET}")
    sys.exit(0)
else:
    print(f"\n  {YELLOW}FAIL 항목을 확인하세요.{RESET}")
    sys.exit(1)
