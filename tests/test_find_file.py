"""find_file 부분매칭·확장자 자동탐색·근사 제안 — BL-07
실행: python tests/test_find_file.py

## 배경 (2026-09-02 실기)

    사용자: "바탕화면에 있는 폴더 이름 나열해 봐, 거기서 내가 고를게"
    Pluiz : "파일명이나 확장자를 지정해야 찾을 수 있다고 하네요"

사용자는 폴더를 **'학교 문서'** 로 기억했는데 실제 이름은 **'학교문'** 이었다.
`glob("*학교 문서*")`는 0건이라 요청이 계속 "없어요"로 끝났고, 왜 없는지
확인할 방법이 없었다. 절반은 2026-09-02에 `list_directory`로 해결했고,
**나머지 절반(find_file 자체)이 2026-09-10에 이 파일과 함께 닫혔다.**

## 무엇을 재고 고쳤나

고치기 전에 오기억 16쌍으로 **무엇이 실제로 막고 있었는지** 쟀다:

    현행 glob (공백 그대로)   긍정 3/8
    공백·구분자만 걷어내면    긍정 7/8 · 오매칭 0     ← 대부분이 여기였다
    difflib 0.70             긍정 6/8 · 오매칭 0

**막고 있던 건 근사 매칭의 부재가 아니라 띄어쓰기였다.** 그래서 difflib는
«혹시 이건가요» 제안으로만 쓴다 — 정규화 매칭보다 성적이 나쁘고 마진도 좁다.

⚠️ 이 테스트는 **임시 폴더**에만 쓴다. 사용자의 실제 바탕화면을 뒤지지 않는다.
"""
import _testenv  # noqa: F401

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


def _touch(*parts):
    p = os.path.join(*parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("x")
    return p


def run():
    passed = total = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")
        if not cond and detail:
            for line in str(detail).splitlines():
                print(f"       {line}")

    # ── 가짜 바탕화면/다운로드/문서를 만든다 ──────────────────
    tmp = tempfile.mkdtemp()
    desk = os.path.join(tmp, "Desktop")
    down = os.path.join(tmp, "Downloads")
    docs = os.path.join(tmp, "Documents")
    for d in (desk, down, docs):
        os.makedirs(d)

    _touch(desk, "학교문", "수강신청.txt")     # BL-07 원문: 사용자는 '학교 문서'로 기억
    _touch(desk, "개발_착수서.hwp")
    _touch(desk, "주간보고서.docx")
    _touch(down, "이력서_변소윤.pdf")
    _touch(docs, "졸업작품계획서_최종.docx")
    _touch(desk, ".env")                       # 비밀 파일 — 절대 안 나와야 한다
    _touch(desk, "하위", "깊은", "회의록.txt")   # 재귀 탐색 확인

    # LOCATION_MAP을 임시 폴더로 갈아끼운다 (사용자 실제 폴더를 안 건드린다)
    orig_map = dict(fs.LOCATION_MAP)
    fs.LOCATION_MAP.update({"desktop": desk, "바탕화면": desk,
                            "downloads": down, "다운로드": down,
                            "documents": docs, "문서": docs})

    def find(**kw):
        return fs.find_file.invoke(kw)

    try:
        # ── ① 현행도 되던 것이 그대로 되는가 (회귀) ────────────
        print("=== ① 기존 동작 (회귀) ===")
        r = find(name="개발_착수서", location="desktop")
        check("정확한 이름으로 찾는다", "개발_착수서.hwp" in r, r)

        r = find(extension="pdf", location="downloads")
        check("확장자만으로 찾는다", "이력서_변소윤.pdf" in r, r)

        r = find(name="회의록", location="desktop")
        check("하위 폴더까지 재귀로 찾는다", "회의록.txt" in r, r)

        r = find(name="env", location="desktop")
        check("🔒 비밀 파일(.env)은 결과에 없다", ".env" not in r, r)

        check("이름·확장자 둘 다 없으면 거절한다", find().startswith("✗"), find())

        # ── ② BL-07 본체 — 띄어쓰기가 달라도 찾는다 ────────────
        print("\n=== ② 띄어쓰기·구분자가 달라도 찾는다 (BL-07 본체) ===")
        r = find(name="개발 착수서", location="desktop")
        check("'개발 착수서' → '개발_착수서.hwp'", "개발_착수서.hwp" in r, r)

        r = find(name="졸업작품 계획서", location="documents")
        check("'졸업작품 계획서' → '졸업작품계획서_최종.docx'",
              "졸업작품계획서_최종.docx" in r, r)

        r = find(name="보고서", location="desktop")
        check("부분 키워드 '보고서' → '주간보고서.docx'", "주간보고서.docx" in r, r)

        # ── ③ 위치를 몰라도 찾는다 ────────────────────────────
        print("\n=== ③ 위치를 안 줘도 · 틀린 위치를 줘도 찾는다 ===")
        r = find(name="이력서")
        check("위치를 안 주면 세 곳을 훑는다", "이력서_변소윤.pdf" in r, r)
        check("어디서 찾았는지 말한다", "downloads" in r or "다운로드" in r, r)

        r = find(name="이력서", location="desktop")
        check("바탕화면에 없으면 다른 곳도 본다", "이력서_변소윤.pdf" in r, r)
        check("🔒 시킨 곳이 아니었음을 밝힌다 (다음 명령이 엉뚱한 걸 가리키지 않게)",
              "desktop" in r and ("아니라" in r or "downloads" in r), r)

        # ── ④ 확장자를 지어냈어도 찾는다 ──────────────────────
        print("\n=== ④ 확장자가 틀렸으면 빼고 다시 찾는다 ===")
        r = find(name="이력서", extension="docx")
        check("확장자 docx로 못 찾으면 빼고 재시도", "이력서_변소윤.pdf" in r, r)
        check("확장자를 뺐다고 말한다", "확장자" in r, r)

        # ── ⑤ 못 찾으면 «혹시 이건가요» ───────────────────────
        print("\n=== ⑤ 못 찾았을 때 다음 단서를 준다 ===")
        # 🚩 BL-07 **원문 사례**. '학교문'은 폴더라 파일 매칭에는 안 걸린다 —
        #    고치고도 여기가 "없어요"로 끝나면 원래 불평이 그대로 남는다.
        r = find(name="학교 문서", location="desktop")
        check("실패는 ✗로 시작한다 (BL-29 계약)", r.startswith("✗"), r)
        check("🚩 원문 사례: '학교 문서' → '학교문'을 제안한다", "학교문" in r, r)
        check("폴더임을 밝힌다 (다음에 뭘 할지 알 수 있게)", "(폴더)" in r, r)
        check("결과 목록에는 폴더를 안 넣는다 (계약은 «파일 탐색»이다)",
              "혹시 이건가요" in r and "찾았습니다" not in r, r)

        # 조사를 하드코딩하지 않는다 (core/graph.py §211의 규칙)
        check("받침 있는 말에는 '을'", "'없는파일'을" in find(name="없는파일", location="desktop"))
        check("받침 없는 말에는 '를'", "'학교 문서'를" in find(name="학교 문서", location="desktop"))
        check("'을(를)'를 그대로 쓰지 않는다",
              "을(를)" not in find(name="없는파일", location="desktop"))

        r2 = find(name="주간보고소", location="desktop")
        check("가까운 이름을 제안한다", "혹시 이건가요" in r2, r2)
        check("제안에 실제 파일명이 들어 있다", "주간보고서.docx" in r2, r2)

        r3 = find(name="zzzz없는이름zzzz", location="desktop")
        check("정말 없으면 «비슷한 이름도 없어요»", "비슷한 이름도 없어요" in r3, r3)
        check("없는 것을 있다고 하지 않는다", r3.startswith("✗"), r3)

        # ── ⑥ 계약 (BL-29) ───────────────────────────────────
        print("\n=== ⑥ 반환 문자열 계약 (BL-29) ===")
        from core.tool_result import tool_failed, tool_succeeded
        check("성공은 tool_succeeded로 읽힌다",
              tool_succeeded(find(name="보고서", location="desktop")))
        check("실패는 tool_failed로 읽힌다",
              tool_failed(find(name="zzzz없는이름zzzz", location="desktop")))
        check("실패가 성공으로 오독되지 않는다",
              not tool_succeeded(find(name="zzzz없는이름zzzz", location="desktop")))

        # ── ⑦ BL-31 — 찾은 것을 열 수 있는가 (두 도구의 계약) ─────
        #
        # 실기(2026-09-10): find_file이 *"바탕화면에서 '00_개발착수서.md'를
        # 찾았어요!"* 라고 답한 **바로 다음 턴**에 open_file이 «찾을 수 없습니다».
        # find_file은 재귀로 찾는데 open_file은 바로 아래 한 겹만 봤다.
        # 여기서 두 도구를 **한 테스트 안에서** 이어 붙여 계약을 고정한다.
        print("\n=== ⑦ find_file이 찾은 것을 open_file이 연다 (BL-31) ===")
        opened = []
        orig_startfile = getattr(os, "startfile", None)
        os.startfile = lambda p: opened.append(p)      # 실제로 열지 않는다
        try:
            r = find(name="회의록", location="desktop")
            check("① find_file은 하위 폴더의 파일을 찾는다", "회의록.txt" in r, r)

            opened.clear()
            r = fs.open_file.invoke({"file_path": "회의록.txt"})
            check("② 🚩 그 파일을 open_file이 연다 (BL-31 원문)",
                  tool_succeeded(r) and opened and "회의록.txt" in opened[0], r)
            check("③ 어디서 찾았는지 말한다", "하위/깊은" in r, r)
            check("④ 절대경로를 응답에 싣지 않는다",
                  tmp not in r and "C:\\Users" not in r, r)

            # 바로 아래 파일은 원래 경로로 열린다 — 느린 탐색을 타지 않는다
            opened.clear()
            r = fs.open_file.invoke({"file_path": "주간보고서.docx"})
            check("⑤ 바로 아래 파일은 그대로 열린다 (회귀)",
                  tool_succeeded(r) and opened, r)
            check("⑥ 그때는 «찾았어요»를 붙이지 않는다", "찾았어요" not in r, r)

            # 기준 폴더 **바로 아래**에 있으면 그걸 연다 — 탐색은 못 찾았을 때만
            # 도는 보조 경로다. 직접 놓인 파일이 더 강한 근거이고, 이건 BL-31
            # 이전부터의 동작이라 바꾸면 흔한 경우가 느려지고 시끄러워진다.
            _touch(down, "회의록.txt")
            opened.clear()
            r = fs.open_file.invoke({"file_path": "회의록.txt"})
            check("⑦ 바로 아래에 있으면 탐색까지 가지 않는다",
                  tool_succeeded(r) and "찾았어요" not in r, r)
            os.remove(os.path.join(down, "회의록.txt"))

            # **탐색 안에서** 둘이 나오면 열지 않고 되묻는다 — 무엇을 여는지
            # 사용자가 정해야 한다. 여는 것은 되돌릴 수 있지만, 엉뚱한 파일을 연 뒤의
            # *"그거 지워줘"* 는 되돌릴 수 없다.
            _touch(docs, "보관", "회의록.txt")
            opened.clear()
            r = fs.open_file.invoke({"file_path": "회의록.txt"})
            check("⑧ 탐색 결과가 여러 개면 열지 않는다", not opened, r)
            check("⑨ 후보를 보여주고 되묻는다",
                  tool_failed(r) and "여러 개" in r, r)
            check("⑩ 후보마다 어디 것인지 말한다",
                  "desktop" in r and "documents" in r, r)
            os.remove(os.path.join(docs, "보관", "회의록.txt"))

            opened.clear()
            r = fs.open_file.invoke({"file_path": "zzzz없는파일zzzz.txt"})
            check("⑪ 없는 파일은 여전히 «찾을 수 없습니다»",
                  tool_failed(r) and not opened, r)

            # 🔒 탐색을 새 입구로 쓰지 못하게 한다
            opened.clear()
            r = fs.open_file.invoke({"file_path": ".env"})
            check("⑫ 🔒 탐색 경로로도 비밀 파일은 안 열린다",
                  not opened and tool_failed(r), r)

            # 🚨 의도된 비대칭 — 삭제는 재귀 탐색을 타지 않는다.
            #    여는 것은 되돌릴 수 있지만 지우는 것은 되돌릴 수 없다.
            deep = os.path.join(desk, "하위", "깊은", "회의록.txt")
            r = fs.delete_file.invoke({"file_path": "회의록.txt"})
            check("⑬ 🚨 delete_file은 하위 폴더를 뒤지지 않는다",
                  tool_failed(r), r)
            check("⑭ 🚨 그래서 깊은 곳의 파일이 살아 있다", os.path.exists(deep))
        finally:
            if orig_startfile is not None:
                os.startfile = orig_startfile

    finally:
        fs.LOCATION_MAP.clear()
        fs.LOCATION_MAP.update(orig_map)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
