"""list_directory 도구 검증 (임시 폴더 사용, OS 안전)
실행: python tests/test_list_directory.py

배경 — 이 도구가 왜 생겼나 (2026-09-02 실기):
  사용자: "바탕화면에 있는 폴더 이름 나열해 봐, 거기서 내가 고를게"
  Pluiz : "파일명이나 확장자를 지정해야 찾을 수 있다고 하네요"
  `find_file`은 **이름이나 확장자를 알아야** 동작한다. 이름을 모를 때 목록을
  보여줄 수단이 도구 34개 중 하나도 없었다. 폴더 이름이 '학교문'인데 사용자는
  '학교 문서'로 기억하고 있어서, 삭제 요청이 계속 "없어요"로 끝났다. → BL-07
"""
import importlib.util
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "tools.filesystem", os.path.join(_ROOT, "tools", "filesystem.py"))
sys.modules.setdefault("tools", types.ModuleType("tools"))
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)


def run():
    passed = total = 0

    def check(name, cond):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "학교문"))
    os.makedirs(os.path.join(tmp, "인턴"))
    with open(os.path.join(tmp, "메모.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    with open(os.path.join(tmp, "desktop.ini"), "w", encoding="utf-8") as f:
        f.write("x")
    with open(os.path.join(tmp, ".hidden"), "w", encoding="utf-8") as f:
        f.write("x")

    print("=== 기본 목록 (절대경로) ===")
    r = fs.list_directory.invoke({"location": tmp})
    check("성공 응답", r.startswith("✓"))
    check("폴더 '학교문' 포함", "학교문" in r)
    check("폴더 '인턴' 포함", "인턴" in r)
    check("파일 '메모.txt' 포함", "메모.txt" in r)
    check("폴더/파일 구분 표시", "[폴더" in r and "[파일" in r)
    check("개수 표시", "2개" in r)

    print("=== 잡동사니 제외 ===")
    check("desktop.ini 제외", "desktop.ini" not in r)
    check("숨김 파일 제외", ".hidden" not in r)

    print("=== only 필터 ===")
    rf = fs.list_directory.invoke({"location": tmp, "only": "folders"})
    check("only=folders → 폴더만", "학교문" in rf and "메모.txt" not in rf)
    rl = fs.list_directory.invoke({"location": tmp, "only": "files"})
    check("only=files → 파일만", "메모.txt" in rl and "학교문" not in rl)

    print("=== 키워드 위치 ===")
    r2 = fs.list_directory.invoke({"location": "바탕화면"})
    check("'바탕화면' 키워드 해석됨 (지원 위치 오류 아님)", "지원하지 않는 위치" not in r2)
    r3 = fs.list_directory.invoke({"location": "desktop"})
    check("'desktop' 키워드 해석됨", "지원하지 않는 위치" not in r3)

    print("=== 오류 처리 ===")
    r4 = fs.list_directory.invoke({"location": "화성"})
    check("모르는 위치 → 오류 응답", r4.startswith("✗"))
    r5 = fs.list_directory.invoke({"location": os.path.join(tmp, "없는폴더")})
    check("없는 폴더 → 오류 응답", r5.startswith("✗"))

    empty = tempfile.mkdtemp()
    r6 = fs.list_directory.invoke({"location": empty})
    check("빈 폴더 → 항목 없음 안내", "없어요" in r6)  # 🔄 2026-09-23 — 말투를 해요체로 통일했다(2-2 ⓐ). **소스 문구를 그대로** 적는다.

    print("=== 비밀 파일은 목록에도 나오지 않는다 (LLM02) ===")
    secret_dir = tempfile.mkdtemp()
    with open(os.path.join(secret_dir, ".env"), "w", encoding="utf-8") as f:
        f.write("GEMINI_API_KEY=x")
    with open(os.path.join(secret_dir, "보통파일.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    r7 = fs.list_directory.invoke({"location": secret_dir})
    check("일반 파일은 보인다", "보통파일.txt" in r7)
    check(".env 는 목록에서 제외", ".env" not in r7)

    print("=== 도구로 등록돼 있다 ===")
    check("langchain tool 객체", hasattr(fs.list_directory, "invoke"))
    check("이름이 name/description을 갖는다",
          bool(getattr(fs.list_directory, "description", "")))

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
