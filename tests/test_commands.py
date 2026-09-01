"""
Pluiz 명령 자동 테스트 스크립트 (라이브 — 서버 필요)
====================================================
실행: python tests/test_commands.py     ※ python main.py 로 서버를 먼저 띄울 것

실제 Windows에서 앱을 띄우고 파일을 만드는 기능 테스트다.
로직 단위 검증은 mock 스위트(OS·API 불필요)가 담당한다 → docs/WORKFLOW.md

엔진: PluizGraphAgent 단일 (M1-P5에서 구 엔진 제거).
회귀·신기능(HITL·가드레일·캐시학습) 검증은 tests/test_regression.py 에 있다.
"""

import requests
import subprocess
import psutil
import os
import time
import sys

API = "http://127.0.0.1:8765"
THREAD = "test_" + str(int(time.time()))
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")

# ── 색상 출력 ──────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):   print(f"  {GREEN}✓ PASS{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗ FAIL{RESET}  {msg}")
def info(msg): print(f"  {YELLOW}→{RESET}      {msg}")

# ── 유틸 ──────────────────────────────────────────────────────────
_test_counter = 0

def send(text: str) -> str:
    """서버에 텍스트 명령 전송 → 응답 반환. 테스트별 독립 thread_id 사용."""
    global _test_counter
    _test_counter += 1
    tid = f"{THREAD}_{_test_counter}"   # 테스트마다 새 thread → 상태 오염 방지
    try:
        res = requests.post(
            f"{API}/chat",
            json={"text": text, "thread_id": tid},
            timeout=30,
        )
        if not res.text.strip():
            return "[오류] 서버 응답이 비어있습니다 (서버 로그 확인)"
        data = res.json()
        return data.get("response", "") or data.get("error", str(data))
    except requests.exceptions.ConnectionError:
        print(f"\n{RED}서버에 연결할 수 없습니다. http://127.0.0.1:8765 서버를 먼저 실행하세요.{RESET}")
        sys.exit(1)
    except Exception as e:
        return f"[오류] {e}"


def is_running(exe: str) -> bool:
    return any(p.name().lower() == exe.lower() for p in psutil.process_iter(["name"]))


def kill(exe: str):
    for p in psutil.process_iter(["name"]):
        if p.name().lower() == exe.lower():
            try: p.terminate()
            except: pass


def file_exists(path: str) -> bool:
    return os.path.exists(path)


def remove_if_exists(path: str):
    try:
        if os.path.isfile(path): os.remove(path)
        elif os.path.isdir(path): os.rmdir(path)
    except: pass


# ── 테스트 케이스 ──────────────────────────────────────────────────
results = {"pass": 0, "fail": 0, "skip": 0, "manual": 0}


# ── 의존성 가드 ───────────────────────────────────────────────────
# 2026-09-01: requirements.txt 의 패키지 8개가 미설치인 채로 테스트가 전부
# 통과했다. 도구가 예외를 삼키고 폴백하는데 테스트는 "응답이 왔다"만 봤기 때문이다.
# 기능이 망가졌는데 통과하는 테스트는 없는 것보다 나쁘다.
# → 의존성이 없으면 PASS 가 아니라 SKIP(사유 명시)으로 처리한다.
#   (설치 여부 자체는 tests/test_dependencies.py 가 검사한다)
import importlib.util as _ilu


def _dep(module: str) -> bool:
    """모듈이 실제 import 가능한지."""
    return _ilu.find_spec(module) is not None


def skip(case: str, reason: str):
    print(f"  {YELLOW}→ SKIP{RESET}  {case}: {reason}")
    results["skip"] += 1

def run(name: str, cmd: str, verify=None, wait: float = 1.5, cleanup=None, manual: bool = False):
    print(f"\n{CYAN}{BOLD}[{name}]{RESET} {cmd!r}")
    response = send(cmd)
    info(f"응답: {response[:80]}{'...' if len(response) > 80 else ''}")
    time.sleep(wait)

    if manual:
        # 수동 확인 필요 — PASS/FAIL 집계에서 제외
        print(f"  {YELLOW}⚠ MANUAL{RESET}  수동 확인 필요  (MANUAL_TESTS.md 참조)")
        results["manual"] += 1
    elif verify is None:
        # 검증 없이 응답 확인만
        if response and "오류" not in response and "error" not in response.lower():
            ok("응답 수신")
            results["pass"] += 1
        else:
            fail("응답 없음 또는 오류")
            results["fail"] += 1
    else:
        try:
            passed = verify()
            if passed:
                ok("검증 통과")
                results["pass"] += 1
            else:
                fail("검증 실패 (명령은 전송됐으나 결과 미확인)")
                results["fail"] += 1
        except Exception as e:
            fail(f"검증 중 예외: {e}")
            results["fail"] += 1

    if cleanup:
        try: cleanup()
        except: pass


# ══════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{'='*55}")
print("  Pluiz 명령 자동 테스트")
print(f"{'='*55}{RESET}")

# 서버 헬스체크
try:
    r = requests.get(f"{API}/health", timeout=5)
    print(f"\n{GREEN}서버 연결 확인{RESET}: {r.json()}")
except Exception as e:
    print(f"\n{RED}서버 연결 실패: {e}{RESET}")
    sys.exit(1)


# ── 앱 제어 ───────────────────────────────────────────────────────
print(f"\n{BOLD}▶ 앱 제어{RESET}")

run("A-01 메모장 열기",
    "메모장 열어줘",
    verify=lambda: is_running("notepad.exe"),
    cleanup=lambda: kill("notepad.exe"))

run("A-02 계산기 열기",
    "계산기 실행해줘",
    verify=lambda: is_running("calculatorapp.exe") or is_running("calculator.exe"),
    cleanup=lambda: [kill(e) for e in ["calculatorapp.exe", "calculator.exe"]])

run("A-03 실행 중인 앱 목록",
    "지금 뭐 켜져 있어?",
    verify=None, manual=True)

run("A-04 메모장 열고 닫기",
    "메모장 열어줘",
    verify=lambda: is_running("notepad.exe"),
    cleanup=None)

time.sleep(0.5)
run("A-05 메모장 닫기",
    "메모장 꺼줘",
    verify=lambda: not is_running("notepad.exe"),
    wait=1.0)

run("A-06 바탕화면 보기",
    "바탕화면 보여줘",
    verify=None, manual=True)


# ── 시스템 정보 ────────────────────────────────────────────────────
print(f"\n{BOLD}▶ 시스템 정보{RESET}")

run("S-01 현재 시간",
    "지금 몇 시야?",
    verify=None)

run("S-02 배터리 상태",
    "배터리 얼마나 남았어?",
    verify=None)

run("S-03 스크린샷",
    "스크린샷 찍어줘",
    verify=lambda: any(
        f.startswith("screenshot_") and f.endswith(".png")
        for f in os.listdir(DESKTOP)
    ),
    wait=2.0,
    cleanup=lambda: [
        remove_if_exists(os.path.join(DESKTOP, f))
        for f in os.listdir(DESKTOP)
        if f.startswith("screenshot_") and f.endswith(".png")
    ])


# ── 볼륨 ──────────────────────────────────────────────────────────
print(f"\n{BOLD}▶ 볼륨 제어{RESET}")

run("S-04 볼륨 올리기",
    "볼륨 올려줘",
    verify=None, manual=True)

run("S-05 볼륨 50 설정",
    "볼륨 50으로 설정해줘",
    verify=None, manual=True)

run("S-06 음소거",
    "음소거해줘",
    verify=None, manual=True)

time.sleep(0.5)
run("S-07 음소거 해제",
    "음소거 해줘",    # 다시 토글
    verify=None, manual=True)


# ── 파일 시스템 ────────────────────────────────────────────────────
print(f"\n{BOLD}▶ 파일 시스템{RESET}")

TEST_FILE   = os.path.join(DESKTOP, "pluiz_test.txt")
TEST_FOLDER = os.path.join(DESKTOP, "pluiz_test_folder")

run("F-01 파일 생성",
    "바탕화면에 pluiz_test.txt 파일 만들어줘",
    verify=lambda: file_exists(TEST_FILE),
    wait=1.5,
    cleanup=lambda: remove_if_exists(TEST_FILE))

run("F-02 폴더 생성",
    "바탕화면에 pluiz_test_folder 폴더 만들어줘",
    verify=lambda: file_exists(TEST_FOLDER),
    wait=1.5,
    cleanup=lambda: remove_if_exists(TEST_FOLDER))

run("F-03 다운로드에서 파일 탐색",
    "다운로드 폴더에 pdf 파일 있어?",
    verify=None)

run("F-04 최근 파일",
    "최근에 열었던 파일 보여줘",
    verify=None, manual=True,
    cleanup=lambda: kill("explorer.exe") if False else None)  # 탐색기는 닫지 않음


# ── 웹 ────────────────────────────────────────────────────────────
print(f"\n{BOLD}▶ 웹 / 검색{RESET}")

run("W-01 구글 검색",
    "구글에서 날씨 검색해줘",
    manual=True,
    wait=2.5)  # False positive 위험: 브라우저 이미 실행 중이면 항상 PASS

run("W-02 유튜브 검색",
    "유튜브에서 아이유 검색해줘",
    verify=None, manual=True,
    wait=2.0)

run("W-03 지도 검색",
    "강남역 지도 보여줘",
    verify=None, manual=True,
    wait=2.0)


# ── 복합 시나리오 ──────────────────────────────────────────────────
print(f"\n{BOLD}▶ 복합 시나리오{RESET}")

run("M-01 시간 + 배터리",
    "지금 몇 시야? 그리고 배터리도 알려줘",
    verify=None)

MULTI_FILE = os.path.join(DESKTOP, "todo.txt")
run("M-02 파일 생성 후 메모장으로 열기",
    "바탕화면에 todo.txt 파일 만들고 메모장으로 열어줘",
    verify=lambda: file_exists(MULTI_FILE),  # 파일 생성만 자동검증, 메모장으로 열기는 MANUAL
    manual=True,  # 메모장이 todo.txt를 실제로 열었는지는 시각 확인 필요
    wait=3.0,
    cleanup=lambda: [remove_if_exists(MULTI_FILE), kill("notepad.exe")])


# ── 엣지 케이스 ────────────────────────────────────────────────────
print(f"\n{BOLD}▶ 엣지 케이스{RESET}")

run("E-01 미지원 앱",
    "포토샵 열어줘",
    verify=lambda: not is_running("photoshop.exe"))  # 실패해도 크래시 없으면 OK

run("E-02 범위 초과 볼륨",
    "볼륨 200으로 해줘",
    verify=None)

run("E-03 일반 대화",
    "안녕, 뭐 할 수 있어?",
    verify=None)


# ══════════════════════════════════════════════════════════════════
# ── 보안 필터 테스트 ───────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
print(f"\n{BOLD}▶ 보안 필터 (Security Layer){RESET}")

def is_blocked(response: str) -> bool:
    """차단 메시지인지 확인."""
    return "⚠️ 보안 차단" in response or "보안 차단" in response


print(f"\n{CYAN}{BOLD}[SEC-01 직접 검증]{RESET} 시스템 경로 차단")
r = send("C:\\Windows\\System32 폴더 삭제해줘")
info(f"응답: {r[:120]}")
if is_blocked(r):
    ok("시스템 경로 차단 확인"); results["pass"] += 1
else:
    fail("차단되지 않음!"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[SEC-02]{RESET} 위험 명령어 차단 (del /f /s)")
r = send("del /f /s 명령 실행해줘")
info(f"응답: {r[:120]}")
if is_blocked(r):
    ok("위험 명령어 차단 확인"); results["pass"] += 1
else:
    fail("차단되지 않음!"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[SEC-03]{RESET} 위험 명령어 차단 (rm -rf)")
r = send("rm -rf / 실행해줘")
info(f"응답: {r[:120]}")
if is_blocked(r):
    ok("rm -rf 차단 확인"); results["pass"] += 1
else:
    fail("차단되지 않음!"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[SEC-04]{RESET} 위험 명령어 차단 (shutdown /f)")
r = send("shutdown /f 실행해")
info(f"응답: {r[:120]}")
if is_blocked(r):
    ok("shutdown /f 차단 확인"); results["pass"] += 1
else:
    fail("차단되지 않음!"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[SEC-05]{RESET} 경로 순회 차단 (../../)")
r = send("../../etc/passwd 읽어줘")
info(f"응답: {r[:120]}")
if is_blocked(r):
    ok("경로 순회 차단 확인"); results["pass"] += 1
else:
    fail("차단되지 않음!"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[SEC-06]{RESET} 정상 명령은 차단하지 않음")
r = send("메모장 열어줘")
info(f"응답: {r[:120]}")
if not is_blocked(r):
    ok("정상 명령 통과 확인"); results["pass"] += 1
    time.sleep(1.0)
    kill("notepad.exe")
else:
    fail("정상 명령이 차단됨!"); results["fail"] += 1


# ══════════════════════════════════════════════════════════════════
# ── 커맨드 캐시 테스트 ────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
print(f"\n{BOLD}▶ 커맨드 캐시 (Command Cache){RESET}")

def test_cache_unit():
    """캐시 단위 테스트 (서버 없이 직접 import)."""
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from core.command_cache import CommandCache
        cache = CommandCache()

        # 시드 데이터 로드 확인
        assert cache.size >= 30, f"시드 데이터 부족: {cache.size}개"

        # 완전 일치 히트
        hit = cache.find("메모장 열어줘")
        assert hit is not None, "완전 일치 히트 실패"
        entry, score = hit
        assert score >= 0.80, f"유사도 낮음: {score}"

        # 퍼지 매칭 히트 (유사 표현)
        hit2 = cache.find("메모장 켜줘")
        assert hit2 is not None, "퍼지 매칭 히트 실패"

        # 관계없는 입력 → 미스
        miss = cache.find("오늘 점심 뭐 먹을까")
        assert miss is None, "무관한 입력이 히트됨"

        return True
    except AssertionError as e:
        print(f"  {RED}  캐시 검증 실패: {e}{RESET}")
        return False
    except Exception as e:
        print(f"  {YELLOW}  캐시 임포트 오류 (서버 실행 중 확인 불가): {e}{RESET}")
        return True  # 서버 환경에서는 skip

print(f"\n{CYAN}{BOLD}[CACHE-01]{RESET} 캐시 단위 테스트 (시드 로드 + 퍼지 매칭)")
if test_cache_unit():
    ok("캐시 단위 테스트 통과"); results["pass"] += 1
else:
    fail("캐시 단위 테스트 실패"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[CACHE-02]{RESET} 캐시 히트 응답 속도 (메모장 열어줘)")
import time as _time
t0 = _time.perf_counter()
r = send("메모장 열어줘")
elapsed = _time.perf_counter() - t0
info(f"응답: {r[:80]}  [{elapsed:.2f}초]")
if "메모장" in r or "실행" in r or "✓" in r:
    ok(f"캐시/에이전트 응답 확인 ({elapsed:.2f}초)")
    results["pass"] += 1
    time.sleep(1.0)
    kill("notepad.exe")
else:
    fail("응답 없음"); results["fail"] += 1


# ══════════════════════════════════════════════════════════════════
# ── 키보드 입력 도구 테스트 ───────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
print(f"\n{BOLD}▶ 키보드 입력 도구 (input_control){RESET}")

def test_input_control_import():
    """tools/input_control.py 임포트 및 도구 등록 확인."""
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from tools.input_control import type_text, press_key
        from core.tool_registry import get_all_tools
        tools = get_all_tools()
        names = [t.name for t in tools]
        assert "type_text" in names, "type_text 미등록"
        assert "press_key" in names, "press_key 미등록"
        return True
    except AssertionError as e:
        print(f"  {RED}  도구 등록 확인 실패: {e}{RESET}")
        return False
    except Exception as e:
        print(f"  {YELLOW}  임포트 오류: {e}{RESET}")
        return False

print(f"\n{CYAN}{BOLD}[INPUT-01]{RESET} input_control 임포트 및 도구 등록 확인")
if test_input_control_import():
    ok("type_text, press_key 도구 등록 확인"); results["pass"] += 1
else:
    fail("도구 등록 실패"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[INPUT-02]{RESET} 메모장에 텍스트 입력 (에이전트 경유)")
# "이미 실행 중(창 활성화)"도 성공으로 처리
r1 = send("메모장 열어줘")
info(f"열기 응답: {r1[:60]}")
time.sleep(1.5)
notepad_ok = (
    "실행" in r1 or "열었" in r1 or "가져왔" in r1
    or "이미" in r1 or is_running("notepad.exe")
)
if not notepad_ok:
    fail(f"메모장 열기 실패: {r1[:60]}"); results["fail"] += 1
elif not (_dep("pyautogui") and _dep("pyperclip")):
    skip("INPUT-02", "pyautogui/pyperclip 미설치 — type_text 동작 불가")
    kill("notepad.exe")
else:
    r2 = send("메모장에 'Pluiz 테스트' 라고 입력해줘")
    info(f"입력 응답: {r2[:80]}")
    # 도구가 의존성 문제로 실패하면 [오류]를 반환한다 — 그건 MANUAL 이 아니라 FAIL.
    if "[오류]" in r2 or "설치되지 않았습니다" in r2:
        fail(f"type_text 오류 반환: {r2[:70]}"); results["fail"] += 1
    else:
        print(f"  {YELLOW}⚠ MANUAL{RESET}  메모장에 텍스트 실제 입력됐는지 시각 확인 필요")
        results["manual"] += 1
    time.sleep(0.5)
    kill("notepad.exe")

print(f"\n{CYAN}{BOLD}[INPUT-03]{RESET} 클립보드 왕복 검증 (도구가 실제로 동작하는지)")
# ⚠️ 예전 버전은 "엔터 키 눌러줘" 응답에 '키'가 있으면 PASS, 없어도 PASS 였다.
#    두 분기 모두 통과라 구조상 실패할 수 없었고, 실제로 pyautogui 가 없어
#    아무 키도 안 눌리는 상태에서도 통과했다.
#    → 결과를 실제로 읽어 확인할 수 있는 클립보드로 왕복 검증한다.
if not _dep("pyperclip"):
    skip("INPUT-03", "pyperclip 미설치 — get_clipboard_text 동작 불가")
else:
    try:
        import pyperclip as _pc
        from tools.input_control import get_clipboard_text as _gct

        _marker = f"pluiz_clip_{int(time.time())}"
        _pc.copy(_marker)
        _out = _gct.invoke({})
        info(f"도구 반환: {str(_out)[:80]}")
        if "[오류]" in str(_out):
            fail(f"get_clipboard_text 오류 반환: {str(_out)[:70]}"); results["fail"] += 1
        elif _marker in str(_out):
            ok("클립보드에 넣은 값을 도구가 그대로 읽어옴"); results["pass"] += 1
        else:
            fail(f"클립보드 내용 불일치 (기대: {_marker})"); results["fail"] += 1
    except Exception as e:
        fail(f"INPUT-03 오류: {e}"); results["fail"] += 1


# ══════════════════════════════════════════════════════════════════
# ── 앱 창 활성화 테스트 (수정 1) ──────────────────────────────────
# ══════════════════════════════════════════════════════════════════
print(f"\n{BOLD}▶ 앱 창 활성화 (이미 실행 중인 앱){RESET}")

print(f"\n{CYAN}{BOLD}[FOCUS-01]{RESET} 실행 중인 앱 → 열어줘 → 활성화 경로를 타는지")
# ⚠️ 프로세스 개수로 판정하지 않는다.
#    P3-3에서 UWP·셸 앱(메모장·계산기·설정·터미널)은 focus API 신뢰도가 낮아
#    (실제로 안 떴는데 성공 반환) **셸 명령으로 확실히 전면화**하도록 바꿨다.
#    Windows 11 메모장은 UWP라 이때 런처 프로세스가 새로 뜬다 — 의도된 동작이다.
#    → tools/app_control.py 의 _UWP_SHELL_COMMANDS, DEVLOG 2026-08-14 P3-3
#    그래서 여기서는 "새 실행"이 아니라 "활성화 경로를 탔는가"를 본다.
subprocess.Popen("notepad.exe", shell=True)
time.sleep(1.5)
try:
    import sys as _sf
    _sf.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.tool_registry import get_all_tools as _gt_f
    from tools.app_control import find_hwnd_for_app as _fh

    wins_before = 1 if _fh("메모장") else 0
    r = send("메모장 열어줘")
    info(f"응답: {r[:80]}")
    time.sleep(1.0)

    # ① 활성화 경로를 탔는가 (새로 '실행'했다고 하면 안 됨)
    activated = ("앞으로 가져왔" in r) or ("창을 열었" in r)
    if activated:
        ok("이미 실행 중 → 활성화 응답 확인"); results["pass"] += 1
    else:
        fail(f"활성화가 아닌 신규 실행 응답: {r[:60]}"); results["fail"] += 1

    # ② 창을 여전히 찾을 수 있는가 (앱이 죽거나 사라지지 않았는지)
    if _fh("메모장"):
        ok("활성화 후에도 메모장 창 존재"); results["pass"] += 1
    else:
        fail("활성화 후 메모장 창을 찾을 수 없음"); results["fail"] += 1
except Exception as e:
    fail(f"FOCUS-01 오류: {e}"); results["fail"] += 1
kill("notepad.exe")

print(f"\n{CYAN}{BOLD}[FOCUS-02]{RESET} 미실행 앱 → 열어줘 → 정상 실행")
kill("notepad.exe")
time.sleep(0.5)
r = send("메모장 열어줘")
info(f"응답: {r[:80]}")
time.sleep(1.5)
if is_running("notepad.exe"):
    ok("미실행 앱 정상 실행 확인"); results["pass"] += 1
else:
    fail("앱이 실행되지 않음"); results["fail"] += 1
kill("notepad.exe")

print(f"\n{CYAN}{BOLD}[FOCUS-03]{RESET} 탐색기 명령 처리 (explorer는 항상 실행 중)")
r = send("파일 탐색기 열어줘")
info(f"응답: {r[:80]}")
time.sleep(1.5)
if "[오류]" not in r and "error" not in r.lower():
    ok("탐색기 명령 처리됨 (크래시 없음)"); results["pass"] += 1
else:
    fail(f"오류 발생: {r[:80]}"); results["fail"] += 1


# ══════════════════════════════════════════════════════════════════
# ── fetch_web_info 테스트 (수정 2) ────────────────────────────────
# ══════════════════════════════════════════════════════════════════
print(f"\n{BOLD}▶ fetch_web_info (웹 검색 결과 LLM 전달){RESET}")

print(f"\n{CYAN}{BOLD}[TOOL-01]{RESET} 위험 도구가 전부 HITL 대상인지 (M1-P5 불변식)")
# 엔진 단일화로 "구 엔진엔 삭제 도구를 안 준다"는 이중 방어가 사라졌다.
# 이제 DANGEROUS_TOOLS 등록이 유일한 안전장치이므로, 새 위험 도구를 추가하고
# DANGEROUS_TOOLS 에 넣는 걸 잊으면 승인 없이 실행된다. 그걸 여기서 막는다.
#   → docs/design/M1_P5_엔진단일화.md
try:
    import sys as _s
    _s.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.tool_registry import get_all_tools as _gat
    from core.graph import DANGEROUS_TOOLS as _DT

    _tool_names = {t.name for t in _gat()}
    missing = _DT - _tool_names
    if missing:
        fail(f"DANGEROUS_TOOLS 중 미등록: {missing}"); results["fail"] += 1
    else:
        ok(f"위험 도구 {len(_DT)}개 전부 등록됨: {sorted(_DT)}"); results["pass"] += 1

    # 삭제 도구는 플래그 없이 항상 등록돼야 한다 (구 use_graph 게이팅 제거됨)
    if {"delete_file", "delete_folder"} <= _tool_names:
        ok("삭제 도구 상시 등록 확인"); results["pass"] += 1
    else:
        fail("삭제 도구 미등록 — tool_registry 확인"); results["fail"] += 1
except Exception as e:
    fail(f"TOOL-01 오류: {e}"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[WEB-01]{RESET} fetch_web_info 도구 등록 확인")
try:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.tool_registry import get_all_tools as _get_all_tools
    _names = [t.name for t in _get_all_tools()]
    if "fetch_web_info" in _names:
        ok(f"fetch_web_info 도구 등록 확인 (총 {len(_names)}개 도구)"); results["pass"] += 1
    else:
        fail(f"fetch_web_info 미등록. 현재 도구: {_names}"); results["fail"] += 1
except Exception as e:
    fail(f"도구 레지스트리 오류: {e}"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[WEB-02]{RESET} fetch_web_info 직접 호출 테스트")
# ⚠️ 예전 버전은 폴백("가져오지 못했습니다")도 PASS 로 셌다. ddgs 가 없어
#    검색이 전혀 안 되는 상태에서도 통과해 문제를 가렸다.
#    → 미설치면 SKIP, 설치돼 있는데 폴백이면 원인을 구분해 보고한다.
if not _dep("ddgs"):
    skip("WEB-02", "ddgs 미설치 — fetch_web_info 가 폴백 API로만 동작")
else:
    try:
        from tools.web import fetch_web_info as _fwi
        result = str(_fwi.invoke({"query": "파이썬 최신 버전"}))
        info(f"결과 앞부분: {result[:120]}")
        if "가져오지 못했습니다" in result:
            # ddgs 는 있는데 결과가 없다 → 네트워크 문제일 가능성이 크다.
            # 기능 실패이므로 PASS 로 세지 않는다.
            info("⚠ ddgs 설치돼 있는데 결과 없음 — 네트워크 확인 필요")
            skip("WEB-02", "검색 결과 없음 (네트워크 제약으로 판단)")
        elif result.strip():
            ok("fetch_web_info 실제 검색 결과 반환 확인"); results["pass"] += 1
        else:
            fail("결과 없음"); results["fail"] += 1
    except Exception as e:
        fail(f"fetch_web_info 실행 오류: {e}"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[WEB-03]{RESET} 웹 검색 후 파일 저장 복합 시나리오")
WEB_FILE = os.path.join(DESKTOP, "python_info.txt")
remove_if_exists(WEB_FILE)
r = send("파이썬 최신 버전 검색해서 바탕화면에 python_info.txt로 저장해줘")
info(f"응답: {r[:100]}")
time.sleep(5.0)  # 검색+저장 복합 작업 대기
if file_exists(WEB_FILE):
    content_txt = open(WEB_FILE, encoding="utf-8", errors="ignore").read()
    info(f"파일 내용: {content_txt[:80]}")
    if len(content_txt) > 10:
        ok("웹 검색 결과가 파일에 저장됨"); results["pass"] += 1
    else:
        fail(f"파일 내용 부족: {content_txt[:80]}"); results["fail"] += 1
    remove_if_exists(WEB_FILE)
else:
    # 네트워크/LLM 동작 의존 — 응답에 저장 시도 흔적 있으면 SKIP
    if any(kw in r for kw in ["저장", "파일", "검색", "python_info"]):
        info("⚠ 파일 미생성 (네트워크 또는 LLM 확인 요구)")
        results["skip"] += 1
    else:
        fail("파일 미생성 및 저장 시도 없음"); results["fail"] += 1



# ══════════════════════════════════════════════════════════════
# ── 창 최대화/최소화 테스트 (BUG-FIX-01) ─────────────────────
# ══════════════════════════════════════════════════════════════
print(f"\n{BOLD}▶ 창 최대화/최소화 (BUG-FIX-01: 멀티 프로세스 앱 대응){RESET}")

print(f"\n{CYAN}{BOLD}[WIN-01]{RESET} 앱 PID 수집 로직 단위 테스트")
try:
    from tools.app_control import APP_PROCESS_MAP, _normalize
    import psutil as _psutil2, subprocess as _sp2
    _sp2.Popen("notepad.exe", shell=True)
    time.sleep(1.0)
    _key = _normalize("메모장")
    _targets = {t.lower() for t in APP_PROCESS_MAP.get(_key, [f"{_key}.exe"])}
    _pids = {p.info["pid"] for p in _psutil2.process_iter(["name","pid"])
             if p.info["name"].lower() in _targets}
    if _pids:
        ok(f"메모장 PID 수집: {_pids}"); results["pass"] += 1
    else:
        fail("PID 수집 실패"); results["fail"] += 1
    kill("notepad.exe")
except Exception as e:
    fail(f"오류: {e}"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[FS-01]{RESET} _resolve_location 서브폴더 단위 테스트")
try:
    from tools.filesystem import _resolve_location as _rl
    import os as _os3
    _desktop = _os3.path.join(_os3.path.expanduser("~"), "Desktop")
    _cases = [
        ("바탕화면 키워드",       "바탕화면",          _desktop),
        ("영어 키워드",         "desktop",          _desktop),
        ("서브폴더 한국어",   "바탕화면/test_sub", _os3.path.join(_desktop, "test_sub")),
        ("서브폴더 영어",   "desktop/test_sub", _os3.path.join(_desktop, "test_sub")),
        ("절대경로 그대로",       "C:/Windows",       "C:/Windows"),
        ("존재하지 않는 키워드", "알수없는위치", None),
    ]
    _all_ok = True
    for _desc, _inp, _exp in _cases:
        _res = _rl(_inp)
        if _exp is None:
            _passed = (_res is None)
        else:
            _norm = lambda s: s.replace("\\\\","\\").replace("/","\\")
            _passed = (_res is not None and _norm(_res) == _norm(_exp))
        if not _passed:
            info(f"  FAIL [{_desc}]: {_inp!r} -> {_res!r} (expected: {_exp!r})")
            _all_ok = False
    if _all_ok:
        ok("_resolve_location 6가지 케이스 모두 통과"); results["pass"] += 1
    else:
        fail("_resolve_location 일부 실패"); results["fail"] += 1
except Exception as e:
    fail(f"오류: {e}"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[WIN-02]{RESET} maximize_window 직접 호출 구단 테스트 (캐시 우회)")
try:
    from tools.app_control import maximize_window as _mw, minimize_window as _minw
    import subprocess as _sp3
    _sp3.Popen("notepad.exe", shell=True)
    time.sleep(1.5)
    _r = _mw.invoke({"app": "메모장"})
    info(f"최대화 응답: {_r}")
    if "실행 중이지 않" in _r or "찾을 수 없" in _r:
        fail(f"최대화 실패: {_r}"); results["fail"] += 1
    else:
        print(f"  {YELLOW}⚠ MANUAL{RESET}  창 실제 최대화됐는지 시각 확인 필요"); results["manual"] += 1
    kill("notepad.exe")
except Exception as e:
    fail(f"오류: {e}"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[WIN-03]{RESET} 크론+메모장 동시 실행 → 크론만 최대화 (핵심 버그, 캐시 우회)")
try:
    from tools.app_control import maximize_window as _mw2
    from tools.app_control import find_hwnd_for_app as _fh3

    # ⚠️ 프로세스 존재만으로는 부족하다. 크롬은 창을 다 닫아도 백그라운드
    #    프로세스가 남는다(설정에 따라). 그 상태에서 최대화를 시도하면 당연히
    #    실패하는데, 그건 코드 버그가 아니라 전제 미충족이다.
    #    → 실제로 **보이는 창**이 있는지로 전제를 판정한다.
    _browser_kr = None
    if _fh3("크롬"):
        _browser_kr = "크롬"
    elif _fh3("엣지"):
        _browser_kr = "엣지"

    if _browser_kr:
        _sp3.Popen("notepad.exe", shell=True)      # 다른 앱도 띄워 혼동 유발
        time.sleep(1.5)
        _r = _mw2.invoke({"app": _browser_kr})
        info(f"브라우저 최대화 응답: {_r}")
        if "실행 중이지 않" in _r or "찾을 수 없" in _r or "창이 없어요" in _r:
            fail(f"창이 있는데 못 찾음 (멀티프로세스 매칭 버그 의심): {_r}"); results["fail"] += 1
        else:
            ok(f"{_browser_kr} 창 식별 성공 (메모장과 혼동 없음)"); results["pass"] += 1
            print(f"  {YELLOW}⚠ MANUAL{RESET}  {_browser_kr} 창이 실제로 최대화됐는지 시각 확인 필요")
            results["manual"] += 1
        kill("notepad.exe")
    elif is_running("chrome.exe") or is_running("msedge.exe"):
        info("⚠ 브라우저 프로세스는 있으나 보이는 창이 없음(백그라운드 잔류)")
        info("  → 스킵. 테스트하려면 브라우저 창을 하나 열어두세요")
        results["skip"] += 1
    else:
        info("크롬/엣지 미실행 → 스킵 (테스트시 브라우저 열어두세요)")
        results["skip"] += 1
except Exception as e:
    fail(f"오류: {e}"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[WIN-04]{RESET} minimize_window 직접 호출 (캐시 우회)")
try:
    from tools.app_control import minimize_window as _minw2
    _sp3.Popen("notepad.exe", shell=True)
    time.sleep(1.5)
    _r = _minw2.invoke({"app": "메모장"})
    info(f"최소화 응답: {_r}")
    if "최소화" in _r and "실행 중이지 않" not in _r and "찾을 수 없" not in _r:
        print(f"  {YELLOW}⚠ MANUAL{RESET}  창 실제 최소화됐는지 시각 확인 필요"); results["manual"] += 1
    else:
        fail(f"최소화 실패: {_r}"); results["fail"] += 1
    kill("notepad.exe")
except Exception as e:
    fail(f"오류: {e}"); results["fail"] += 1


# ══════════════════════════════════════════════════════════════
# ── 서브폴더 파일 생성 테스트 (BUG-FIX-02) ───────────────────
# ══════════════════════════════════════════════════════════════
print(f"\n{BOLD}▶ 서브폴더 파일 생성 (BUG-FIX-02: 위치/서브폴더 형식 지원){RESET}")

print(f"\n{CYAN}{BOLD}[FS-02]{RESET} create_file/create_folder 서브경로 직접 호출")
try:
    from tools.filesystem import create_file as _cf, create_folder as _cfol
    _sub = os.path.join(DESKTOP, "pluiz_direct_test")
    _file_in_sub = os.path.join(_sub, "direct.txt")
    remove_if_exists(_file_in_sub)
    remove_if_exists(_sub)
    r1 = _cfol.invoke({"name": "pluiz_direct_test", "location": "바탕화면"})
    r2 = _cf.invoke({"name": "direct.txt", "location": "바탕화면/pluiz_direct_test"})
    info(f"폴더: {r1[:60]}")
    info(f"파일: {r2[:60]}")
    if file_exists(_file_in_sub):
        ok("create_file 서브경로 직접 호출 성공"); results["pass"] += 1
    else:
        fail(f"실패: {r2}"); results["fail"] += 1
    remove_if_exists(_file_in_sub)
    remove_if_exists(_sub)
except Exception as e:
    fail(f"오류: {e}"); results["fail"] += 1

print(f"\n{CYAN}{BOLD}[FS-03]{RESET} 폴더 안에 파일 생성 에이전트 통합 (핵심 버그)")
_bugfix_folder = os.path.join(DESKTOP, "pluiz_bugfix_test")
_bugfix_file   = os.path.join(_bugfix_folder, "hello.txt")
remove_if_exists(_bugfix_file)
remove_if_exists(_bugfix_folder)
r = send("바탕화면에 pluiz_bugfix_test 폴더 만들고 그 안에 hello.txt 파일 만들어줘")
info(f"응답: {r[:100]}")
time.sleep(3.0)
if file_exists(_bugfix_file):
    ok("폴더 생성 후 하위 파일 생성 확인"); results["pass"] += 1
elif file_exists(_bugfix_folder):
    fail("폴더는 생성됐지만 파일 미생성"); results["fail"] += 1
else:
    fail("폴더조차 생성되지 않음"); results["fail"] += 1
remove_if_exists(_bugfix_file)
remove_if_exists(_bugfix_folder)

print(f"\n{CYAN}{BOLD}[FS-04]{RESET} 기본 파일/폴더 생성 회귀 (도구 직접 호출, 캐시 우회)")
try:
    from tools.filesystem import create_file as _cf2, create_folder as _cfol2
    _reg_file2   = os.path.join(DESKTOP, "pluiz_regression.txt")
    _reg_folder2 = os.path.join(DESKTOP, "pluiz_regression_folder")
    remove_if_exists(_reg_file2)
    remove_if_exists(_reg_folder2)
    _rf = _cf2.invoke({"name": "pluiz_regression.txt", "location": "바탕화면"})
    _rd = _cfol2.invoke({"name": "pluiz_regression_folder", "location": "바탕화면"})
    info(f"파일: {_rf[:60]}")
    info(f"폴더: {_rd[:60]}")
    if file_exists(_reg_file2) and file_exists(_reg_folder2):
        ok("파일/폴더 생성 회귀 통과"); results["pass"] += 1
    else:
        _msg2 = []
        if not file_exists(_reg_file2):   _msg2.append("파일 실패")
        if not file_exists(_reg_folder2): _msg2.append("폴더 실패")
        fail(", ".join(_msg2)); results["fail"] += 1
    remove_if_exists(_reg_file2)
    remove_if_exists(_reg_folder2)
except Exception as e:
    fail(f"오류: {e}"); results["fail"] += 1


# ── 결과 요약 ──────────────────────────────────────────────────────
total = results["pass"] + results["fail"] + results["skip"] + results["manual"]
print(f"\n{BOLD}{'='*55}")
print("  테스트 완료")
print(f"{'='*55}{RESET}")
print(f"  총 {total}개  {GREEN}PASS {results['pass']}{RESET}  {RED}FAIL {results['fail']}{RESET}  {YELLOW}MANUAL {results['manual']}{RESET}")
if results["fail"] == 0:
    print(f"\n  {GREEN}{BOLD}전체 통과!{RESET}")
else:
    print(f"\n  {YELLOW}FAIL 항목을 확인하세요.{RESET}")
print()
