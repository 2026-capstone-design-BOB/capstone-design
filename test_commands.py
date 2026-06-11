"""
Pluiz 명령 자동 테스트 스크립트
서버가 실행 중인 상태에서 실행: python test_commands.py
"""

import requests
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
results = {"pass": 0, "fail": 0, "skip": 0}

def run(name: str, cmd: str, verify=None, wait: float = 1.5, cleanup=None):
    print(f"\n{CYAN}{BOLD}[{name}]{RESET} {cmd!r}")
    response = send(cmd)
    info(f"응답: {response[:80]}{'...' if len(response) > 80 else ''}")
    time.sleep(wait)

    if verify is None:
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
    verify=None)

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
    verify=None)


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
    verify=None)

run("S-05 볼륨 50 설정",
    "볼륨 50으로 설정해줘",
    verify=None)

run("S-06 음소거",
    "음소거해줘",
    verify=None)

time.sleep(0.5)
run("S-07 음소거 해제",
    "음소거 해줘",    # 다시 토글
    verify=None)


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
    verify=None,
    cleanup=lambda: kill("explorer.exe") if False else None)  # 탐색기는 닫지 않음


# ── 웹 ────────────────────────────────────────────────────────────
print(f"\n{BOLD}▶ 웹 / 검색{RESET}")

run("W-01 구글 검색",
    "구글에서 날씨 검색해줘",
    verify=lambda: is_running("chrome.exe") or is_running("msedge.exe"),
    wait=2.5)

run("W-02 유튜브 검색",
    "유튜브에서 아이유 검색해줘",
    verify=None,
    wait=2.0)

run("W-03 지도 검색",
    "강남역 지도 보여줘",
    verify=None,
    wait=2.0)


# ── 복합 시나리오 ──────────────────────────────────────────────────
print(f"\n{BOLD}▶ 복합 시나리오{RESET}")

run("M-01 시간 + 배터리",
    "지금 몇 시야? 그리고 배터리도 알려줘",
    verify=None)

MULTI_FILE = os.path.join(DESKTOP, "todo.txt")
run("M-02 파일 생성 후 메모장으로 열기",
    "바탕화면에 todo.txt 파일 만들고 메모장으로 열어줘",
    verify=lambda: file_exists(MULTI_FILE) and is_running("notepad.exe"),
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


# ── 결과 요약 ──────────────────────────────────────────────────────
total = results["pass"] + results["fail"] + results["skip"]
print(f"\n{BOLD}{'='*55}")
print("  테스트 완료")
print(f"{'='*55}{RESET}")
print(f"  총 {total}개  {GREEN}PASS {results['pass']}{RESET}  {RED}FAIL {results['fail']}{RESET}")
if results["fail"] == 0:
    print(f"\n  {GREEN}{BOLD}전체 통과!{RESET}")
else:
    print(f"\n  {YELLOW}FAIL 항목을 확인하세요.{RESET}")
print()
