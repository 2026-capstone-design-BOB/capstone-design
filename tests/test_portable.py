"""내보내기 / 가져오기 — M6
실행: python tests/test_portable.py

→ ADR: docs/design/M6_내보내기_가져오기.md

## 이 테스트의 핵심은 §4다

나머지는 지퍼 파일 다루기다. §4는 **가져오기가 BL-27 필터의 우회로가 되는지**를 본다.

`is_learnable_utterance()`는 `learn()` 경로에만 걸려 있다. 가져오기가 캐시 파일을
그대로 받아들이면, 다른 PC에서 오염된 엔트리(`'그래' → close_app`)가 필터를 우회해
들어온다. **오늘 고친 것이 파일 하나로 되돌려진다.**

그래서 여기서 **일부러 오염된 번들을 만들어 넣어 본다.**
"""
import _testenv  # noqa: F401

import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import portable  # noqa: E402
from core.command_cache import CommandCache  # noqa: E402


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

    cache = CommandCache()
    tmp = tempfile.mkdtemp()
    cache_path = os.path.join(tmp, "command_cache.json")

    def write_cache(d):
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def read_cache():
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)

    def entry(pattern, tool, app=None, seed=False):
        return {"pattern": pattern,
                "tool_calls": [{"name": tool, "args": ({"app": app} if app else {})}],
                "response_template": "✓ 됐어요", "hit_count": 3,
                "is_seed": seed, "source": "seed" if seed else "dynamic"}

    def make_bundle(entries, favorites=None, version=portable.BUNDLE_VERSION,
                    product="pluiz"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("command_cache.json", json.dumps(entries, ensure_ascii=False))
            if favorites is not None:
                z.writestr("favorites.json", json.dumps(favorites, ensure_ascii=False))
            z.writestr(portable.MANIFEST_NAME, json.dumps(
                {"bundle_version": version, "product": product,
                 "created": "2026-09-10T00:00:00", "items": {}}))
        return buf.getvalue()

    # ── §1. 내보내기 ────────────────────────────────────────
    print("=== §1. 내보내기 ===")
    write_cache({
        "메모장 열어줘": entry("메모장 열어줘", "open_app", "메모장", seed=True),
        "노트 띄워줘": entry("노트 띄워줘", "open_app", "메모장"),
    })
    data, manifest = portable.build_bundle(cache_path=cache_path)

    check("zip이 만들어진다", data[:2] == b"PK", data[:8])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        exported = json.loads(z.read("command_cache.json").decode("utf-8"))
    check("manifest.json이 들어 있다", portable.MANIFEST_NAME in names, names)
    check("동적 학습분만 담는다", list(exported) == ["노트 띄워줘"], list(exported))
    check("🔒 시드는 안 담는다 (코드가 제공한다 — 낡은 시드가 새 시드를 덮으면 안 된다)",
          "메모장 열어줘" not in exported)
    check("매니페스트가 개수를 적는다", manifest["items"]["command_cache"] == 1, manifest)
    check("히스토리는 기본으로 안 담는다", "session.db" not in names, names)
    check("파일 이름에 날짜가 들어간다",
          portable.suggested_filename().startswith("pluiz-export-2"))

    # 🔒 allowlist — 목록에 없는 것은 «거르는» 게 아니라 «담길 수 없다»
    print("\n=== §2. .env는 넣을 수 없다 (allowlist) ===")
    listed = {rel for _n, rel, _d in portable._EXPORTABLE}
    check("🔒 .env가 목록에 없다", not any(".env" in r for r in listed), listed)
    check("🔒 로그가 목록에 없다", not any("log" in r.lower() for r in listed), listed)
    check("🔒 웨이크워드 모델이 목록에 없다",
          not any("npz" in r.lower() for r in listed), listed)
    check("담기는 것은 캐시·즐겨찾기·히스토리 셋뿐이다", len(portable._EXPORTABLE) == 3)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        check("실제 zip에 .env가 없다", not any(".env" in n for n in z.namelist()))

    # ── §3. 우리 것이 아닌 파일은 거절한다 ──────────────────
    print("\n=== §3. 아무 zip이나 받지 않는다 ===")
    try:
        portable.read_manifest(b"not a zip")
        check("zip이 아니면 거절한다", False, "예외가 안 났다")
    except portable.BundleError as e:
        check("zip이 아니면 거절한다", "zip" in str(e), e)

    plain = io.BytesIO()
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("hello.txt", "hi")
    try:
        portable.read_manifest(plain.getvalue())
        check("manifest 없으면 거절한다", False, "예외가 안 났다")
    except portable.BundleError as e:
        check("manifest 없으면 거절한다", "manifest" in str(e), e)

    try:
        portable.read_manifest(make_bundle({}, version=99))
        check("모르는 버전은 거절한다", False, "예외가 안 났다")
    except portable.BundleError as e:
        check("모르는 버전은 거절한다", "99" in str(e), e)
        check("왜 거절했는지 말한다 (반쯤 가져오는 것보다 낫다)", "형식 버전" in str(e), e)

    try:
        portable.read_manifest(make_bundle({}, product="other"))
        check("다른 제품 파일은 거절한다", False, "예외가 안 났다")
    except portable.BundleError as e:
        check("다른 제품 파일은 거절한다", "Pluiz" in str(e), e)

    # 거절했으면 **아무것도 안 건드려야** 한다
    write_cache({"노트 띄워줘": entry("노트 띄워줘", "open_app", "메모장")})
    before = read_cache()
    try:
        portable.import_bundle(b"not a zip", cache, cache_path=cache_path)
    except portable.BundleError:
        pass
    check("🔒 거절한 뒤 캐시가 그대로다", read_cache() == before)

    # ── §4. 🚨 가져오기는 학습의 다른 입구다 (BL-27) ────────
    print("\n=== §4. 🚨 오염된 번들이 BL-27 필터를 우회하지 못한다 ===")
    write_cache({})
    poisoned = {
        "그래": entry("그래", "close_app", "메모장"),                  # L2: 2글자 · L1
        "계산기 말고 메모장 열어줘": entry("계산기 말고 메모장 열어줘",
                                          "open_app", "메모장"),      # L3: 대조 표지
        "오시가 된거야 다시": entry("오시가 된거야 다시", "open_app", "메모장"),  # L1
        "노트 띄워줘": entry("노트 띄워줘", "open_app", "메모장"),       # 정상
    }
    rep = portable.import_bundle(make_bundle(poisoned), cache, cache_path=cache_path)
    after = read_cache()

    check("🚨 '그래'가 들어오지 않는다 (BL-27이 파일로 되돌려지지 않는다)",
          "그래" not in after, list(after))
    check("🚨 대조 표지('말고')가 들어오지 않는다",
          "계산기 말고 메모장 열어줘" not in after, list(after))
    check("🚨 STT 오인식이 들어오지 않는다",
          "오시가 된거야 다시" not in after, list(after))
    check("정상 표현은 들어온다", "노트 띄워줘" in after, list(after))
    check("거른 개수를 보고한다", len(rep["cache"]["rejected"]) == 3, rep["cache"])
    check("거른 **사유**도 남긴다 (조용히 버리지 않는다)",
          all(why for _p, why in rep["cache"]["rejected"]), rep["cache"]["rejected"])
    check("사용자에게 거른 사실을 말한다",
          "거르고 넣지 않았어요" in portable.describe_report(rep),
          portable.describe_report(rep))
    check("들어온 것에 출처 표시가 남는다", after["노트 띄워줘"].get("imported") is True)

    # 학습 대상이 아닌 도구도 막힌다
    write_cache({})
    rep2 = portable.import_bundle(
        make_bundle({"파일 지워줘 그거": entry("파일 지워줘 그거", "delete_file")}),
        cache, cache_path=cache_path)
    check("🔒 학습 대상이 아닌 도구(delete_file)는 안 들어온다",
          read_cache() == {}, read_cache())
    check("그 사유도 남는다", rep2["cache"]["rejected"], rep2["cache"])

    # ── §5. 병합은 기존을 지킨다 ────────────────────────────
    print("\n=== §5. 병합 — 기존 우선 · 시드는 절대 안 덮는다 ===")
    mine = entry("노트 띄워줘", "open_app", "메모장")
    mine["response_template"] = "✓ 내 것"
    write_cache({
        "노트 띄워줘": mine,
        "메모장 열어줘": entry("메모장 열어줘", "open_app", "메모장", seed=True),
    })
    theirs = entry("노트 띄워줘", "open_app", "계산기")
    theirs["response_template"] = "✓ 남의 것"
    theirs_seed = entry("메모장 열어줘", "open_app", "계산기")

    portable.import_bundle(
        make_bundle({"노트 띄워줘": theirs, "메모장 열어줘": theirs_seed}),
        cache, cache_path=cache_path)
    got = read_cache()
    check("같은 패턴이면 기존을 지킨다 (조용한 덮어쓰기 없음)",
          got["노트 띄워줘"]["response_template"] == "✓ 내 것", got["노트 띄워줘"])
    check("🔒 시드는 덮이지 않는다",
          got["메모장 열어줘"]["tool_calls"][0]["args"]["app"] == "메모장",
          got["메모장 열어줘"])

    # replace 모드는 명시할 때만
    portable.import_bundle(make_bundle({"노트 띄워줘": theirs}), cache,
                           mode="replace", cache_path=cache_path)
    got = read_cache()
    check("mode=replace면 덮어쓴다", got["노트 띄워줘"]["response_template"] == "✓ 남의 것")

    portable.import_bundle(make_bundle({"메모장 열어줘": theirs_seed}), cache,
                           mode="replace", cache_path=cache_path)
    check("🔒 replace여도 시드는 안 덮는다",
          read_cache()["메모장 열어줘"]["tool_calls"][0]["args"]["app"] == "메모장")

    # ── §6. 되돌릴 길 ───────────────────────────────────────
    print("\n=== §6. 되돌릴 수 없는 변경 앞에서 되돌릴 길을 만든다 ===")
    write_cache({"노트 띄워줘": mine})
    rep3 = portable.import_bundle(make_bundle({"쪽지 열어줘": entry("쪽지 열어줘", "open_app", "메모장")}),
                                  cache, cache_path=cache_path)
    backups = [f for f in os.listdir(tmp) if ".backup-" in f]
    check("가져오기 전에 백업을 남긴다", backups, os.listdir(tmp))
    check("백업을 사용자에게 알린다", rep3["backups"], rep3)
    if backups:
        with open(os.path.join(tmp, backups[0]), encoding="utf-8") as f:
            check("백업이 **가져오기 전** 내용이다", list(json.load(f)) == ["노트 띄워줘"])

    # ── §7. 왕복 ────────────────────────────────────────────
    print("\n=== §7. 내보낸 것을 그대로 다시 가져올 수 있다 ===")
    write_cache({
        "노트 띄워줘": entry("노트 띄워줘", "open_app", "메모장"),
        "쪽지 열어줘": entry("쪽지 열어줘", "open_app", "메모장"),
        "메모장 열어줘": entry("메모장 열어줘", "open_app", "메모장", seed=True),
    })
    blob, _m = portable.build_bundle(cache_path=cache_path)
    write_cache({})                       # 다른 PC라고 치고 비운다
    rep4 = portable.import_bundle(blob, cache, cache_path=cache_path)
    got = read_cache()
    check("내보낸 동적 학습분이 그대로 돌아온다",
          set(got) == {"노트 띄워줘", "쪽지 열어줘"}, list(got))
    check("왕복에서 거절된 것이 없다", not rep4["cache"]["rejected"], rep4["cache"])
    check("보고 문장이 사람이 읽을 만하다",
          "명령 2개" in portable.describe_report(rep4), portable.describe_report(rep4))

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
