"""
선언된 의존성이 실제로 설치돼 있는지 검증
==========================================
mock — 서버·LLM API 불필요.
실행: python tests/test_dependencies.py

## 왜 필요한가

2026-09-01 실기에서 `requirements.txt`에 있는 6개 패키지(pyautogui · pyperclip ·
send2trash · openpyxl · beautifulsoup4 · ddgs)가 실행 환경에 **없는 상태**로
테스트가 전부 통과했다. 도구들이 예외를 삼키고 폴백하기 때문이다.

특히 `send2trash`가 없으면 `tools/filesystem.py`의 `_to_trash()`가 조용히
`os.remove`로 폴백해 **휴지통을 거치지 않고 영구 삭제**한다. 사용자는 "삭제할까요?"에
승인할 뿐 복구 불가라는 걸 모른다.

기능이 망가졌는데 통과하는 테스트는 없는 것보다 나쁘다. 그래서 여기서
**선언과 실제를 대조**한다.
"""
import sys, os, re, importlib.util

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    passed += bool(cond)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


# pip 패키지명 → import 이름 (다른 것들만 매핑)
_IMPORT_NAME = {
    "beautifulsoup4": "bs4",
    "python-multipart": "multipart",
    "python-dotenv": "dotenv",
    "faster-whisper": "faster_whisper",
    "edge-tts": "edge_tts",
    "SpeechRecognition": "speech_recognition",
    "pydantic-settings": "pydantic_settings",
    "langchain-core": "langchain_core",
    "langchain-google-genai": "langchain_google_genai",
    "langchain-anthropic": "langchain_anthropic",
    "uvicorn[standard]": "uvicorn",
    "Pillow": "PIL",
}

# 이 도구가 죽으면 무엇이 안 되는지 — 실패 메시지에 같이 보여준다
_IMPACT = {
    "pyautogui":      "type_text · press_key 동작 안 함",
    "pyperclip":      "type_text(한글) · get_clipboard_text 동작 안 함",
    "send2trash":     "⚠️ delete_file/delete_folder 가 휴지통을 안 거치고 영구 삭제",
    "openpyxl":       "write_excel 동작 안 함",
    "beautifulsoup4": "crawl_page 동작 안 함",
    "ddgs":           "fetch_web_info 가 폴백 API로만 동작",
    "playwright":     "브라우저 자동화 미동작",
    "SpeechRecognition": "STT 온라인 경로(Google) 미동작 → whisper 폴백만",
    "sounddevice":    "웨이크워드 마이크 스트림 미동작",
}


def _declared_packages():
    """requirements.txt 에서 주석·빈 줄을 뺀 패키지명 목록."""
    pkgs = []
    with open(os.path.join(_ROOT, "requirements.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            name = re.split(r"[<>=!~\[]", line)[0].strip()
            if line.startswith("uvicorn"):
                name = "uvicorn"
            if name:
                pkgs.append(name)
    return pkgs


print("=== requirements.txt 선언 패키지가 실제 import 되는가 ===")
missing = []
for pkg in _declared_packages():
    mod = _IMPORT_NAME.get(pkg, pkg.replace("-", "_"))
    ok = importlib.util.find_spec(mod) is not None
    if not ok:
        missing.append(pkg)
    check(f"{pkg:<24} → import {mod}", ok, _IMPACT.get(pkg, "requirements.txt 선언됨"))

if missing:
    print(f"\n  설치 명령: pip install {' '.join(missing)}")


# ── 삭제 안전성: 폴백이 아니라 실제 휴지통을 쓰는가 ────────────────
print("\n=== 삭제가 휴지통을 거치는가 (복구 가능성) ===")
try:
    import tempfile
    from tools.filesystem import _to_trash

    tmp = os.path.join(tempfile.mkdtemp(), "pluiz_dep_check.txt")
    open(tmp, "w", encoding="utf-8").write("x")
    how = _to_trash(tmp)
    check("_to_trash() 가 휴지통 사용 ('trash')", how == "trash",
          f"실제: {how!r} — send2trash 미설치 시 영구 삭제로 폴백함")
except Exception as e:
    check("_to_trash() 검사", False, str(e))


# ── HITL 질문이 복구 가능 여부를 승인 전에 알리는가 ────────────────
print("\n=== HITL 확인 질문이 결과를 미리 알리는가 (P3-3 정직 보고) ===")
try:
    _spec = importlib.util.spec_from_file_location(
        "_g", os.path.join(_ROOT, "core", "graph.py"))
    _g = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_g)

    call = {"name": "delete_file", "args": {"file_path": "C:/x/todo.txt"}}

    q_now = _g._confirm_question(call)
    check("질문에 결과가 명시됨 (휴지통/영구)",
          ("휴지통" in q_now or "영구 삭제" in q_now), q_now)

    # send2trash 없는 환경을 흉내내 경고가 뜨는지
    _orig = _g._deletion_is_recoverable
    try:
        _g._deletion_is_recoverable = lambda: False
        q_perm = _g._confirm_question(call)
        check("복구 불가 시 경고 문구", "영구 삭제" in q_perm and "복구할 수 없" in q_perm, q_perm)
    finally:
        _g._deletion_is_recoverable = _orig

    check("조사 하드코딩 '을(를)' 없음", "을(를)" not in q_now, q_now)
except Exception as e:
    check("HITL 질문 검사", False, str(e))


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
