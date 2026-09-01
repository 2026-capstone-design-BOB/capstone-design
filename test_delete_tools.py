"""
P2-1 삭제 도구 검증 (임시 파일 사용, OS 안전)
실행: python test_delete_tools.py
"""
import sys, os, tempfile, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# tools.filesystem만 직접 로드
spec = importlib.util.spec_from_file_location(
    "tools.filesystem", os.path.join(os.path.dirname(__file__), "tools", "filesystem.py"))
# tools 패키지 stub
import types
sys.modules.setdefault("tools", types.ModuleType("tools"))
fs = importlib.util.module_from_spec(spec); spec.loader.exec_module(fs)


def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    tmp = tempfile.mkdtemp()

    print("=== delete_file ===")
    # 파일 생성 후 삭제
    fpath = os.path.join(tmp, "지울파일.txt")
    with open(fpath, "w") as f: f.write("bye")
    r = fs.delete_file.invoke({"file_path": fpath})
    check("파일 삭제 성공 응답", r.startswith("✓"))
    check("실제로 파일 사라짐", not os.path.exists(fpath))

    # 없는 파일
    r = fs.delete_file.invoke({"file_path": os.path.join(tmp, "없음.txt")})
    check("없는 파일 → 실패 안내", "찾을 수 없" in r)

    # 폴더를 delete_file로 → 거부
    sub = os.path.join(tmp, "폴더"); os.makedirs(sub)
    r = fs.delete_file.invoke({"file_path": sub})
    check("폴더를 delete_file → 거부", "delete_folder" in r)

    print("=== delete_folder ===")
    r = fs.delete_folder.invoke({"folder_path": sub})
    check("폴더 삭제 성공 응답", r.startswith("✓"))
    check("실제로 폴더 사라짐", not os.path.exists(sub))

    print("=== 보호 경로 차단 ===")
    check("_is_protected_path(C:\\\\Windows)", fs._is_protected_path("C:\\Windows\\x.dll"))
    check("_is_protected_path(드라이브 루트)", fs._is_protected_path("C:\\"))
    check("_is_protected_path(일반 경로)==False", not fs._is_protected_path(tmp + "/a.txt"))
    # 실제 삭제 도구에서도 보호경로 거부 (존재하지 않아도 경로 검사 전 존재체크가 먼저이므로
    # 존재하는 임시 파일을 보호경로처럼 만들 순 없어 함수 단위로만 확인)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
