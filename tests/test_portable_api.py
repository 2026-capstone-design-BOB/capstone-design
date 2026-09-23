"""/export · /import 엔드포인트 — M6 ②
실행: python tests/test_portable_api.py

서버를 띄우지 않는다 — FastAPI TestClient로 **앱을 직접** 부른다.
(WORKFLOW의 «서버 통합 3파일»과 달리 이건 mock 스위트에 들어간다)

## 왜 API 층을 따로 검증하나

`core/portable.py`가 아무리 옳아도 **배선이 틀리면 아무 일도 안 일어난다.**
이 프로젝트가 실제로 겪은 모양이다:

  - **BL-16** — `/voice`의 스칼라에서 `Form(...)`을 빼자 FastAPI가 **쿼리 파라미터**로
    해석해 FormData로 온 값을 통째로 무시했다. 음성과 텍스트가 다른 대화가 됐고,
    평범한 명령은 멀쩡해 보이다가 **맥락이 필요한 순간에만** 무너졌다.
    `/import`의 `mode`·`history`가 **정확히 같은 함정** 위에 있다.
  - **BL-14** — 토큰이 안 실리는 경로는 **그 기능만 조용히 401**이 난다.
"""
import _testenv  # noqa: F401

import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ⚠️ main을 import하기 전에 캐시를 임시 경로로 돌린다 (사용자 캐시를 안 건드린다)
import tempfile  # noqa: E402
_TMP = tempfile.mkdtemp()
os.environ["PLUIZ_CACHE_FILE"] = os.path.join(_TMP, "command_cache.json")
# 토큰 파일도 임시로 — 사용자 서버가 돌고 있어도 그 토큰을 건드리지 않는다
os.environ["PLUIZ_TOKEN_FILE"] = os.path.join(_TMP, ".auth_token")


def run():
    passed = total = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")
        if not cond and detail:
            for line in str(detail).splitlines()[:6]:
                print(f"       {line}")

    try:
        from fastapi.testclient import TestClient
    except Exception as e:
        print(f"  (건너뜀) TestClient 없음: {e}")
        return True

    import main
    from core import portable

    # ⚠️ `with TestClient(...)` 를 쓰지 않는다 — startup/shutdown이 돌면
    #   shutdown의 `auth.clear_token()`이 **사용자 서버의 토큰 파일을 지운다.**
    #   2026-09-02에 실제로 그렇게 UI가 끊긴 사고가 있었다(WORKFLOW의 경고).
    #   토큰만 직접 주입한다 — 검증하려는 건 인증 발급이 아니라 배선이다.
    main._AUTH_TOKEN = "test-token-portable-api"
    # base_url을 127.0.0.1로 — TrustedHostMiddleware가 `testserver`를 막는다
    # (`allowed_hosts=["127.0.0.1","localhost"]`. 그 설정이 맞고, 테스트가 맞춰야 한다)
    client = TestClient(main.app, base_url="http://127.0.0.1")
    hdr = {main.auth.HEADER_NAME: main._AUTH_TOKEN}

    # ── §1. 인증 (BL-14) ────────────────────────────────────
    print("=== §1. 인증이 걸려 있다 (BL-14) ===")
    from config.settings import get_settings
    if get_settings().auth_enabled:
        check("토큰 없이 /export는 401", client.get("/export").status_code == 401)
        check("토큰 없이 /import는 401",
              client.post("/import", files={"file": ("a.zip", b"x")}).status_code == 401)
    else:
        check("(인증 꺼짐 — 건너뜀)", True)

    # ── §2. 내보내기 ────────────────────────────────────────
    print("\n=== §2. GET /export ===")
    r = client.get("/export", headers=hdr)
    check("200으로 zip을 준다", r.status_code == 200, r.status_code)
    check("Content-Type이 zip", r.headers.get("content-type") == "application/zip",
          r.headers.get("content-type"))
    check("파일 이름을 붙여 준다",
          "pluiz-export-" in r.headers.get("content-disposition", ""),
          r.headers.get("content-disposition"))
    check("실제로 zip이다", r.content[:2] == b"PK", r.content[:8])

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = set(z.namelist())
    check("manifest가 들어 있다", portable.MANIFEST_NAME in names, names)
    check("🔒 .env가 안 들어 있다", not any(".env" in n for n in names), names)
    check("🔒 히스토리는 기본으로 안 들어 있다", "session.db" not in names, names)

    r2 = client.get("/export?history=true", headers=hdr)
    with zipfile.ZipFile(io.BytesIO(r2.content)) as z:
        m = json.loads(z.read(portable.MANIFEST_NAME).decode("utf-8"))
    check("?history=true면 매니페스트가 그렇게 적는다", m["includes_history"] is True, m)

    # ── §3. 가져오기 — 우리 것이 아니면 거절 ────────────────
    print("\n=== §3. POST /import — 아무 파일이나 받지 않는다 ===")
    r = client.post("/import", headers=hdr, files={"file": ("x.zip", b"not a zip")})
    check("zip이 아니면 400", r.status_code == 400, r.status_code)
    check("왜 거절했는지 말한다", "message" in r.json(), r.json())
    check("🔒 «아무것도 안 바꿨다»고 알린다",
          "아무것도" in r.json().get("note", ""), r.json())

    # ── §4. 🚨 Form(...) 함정 (BL-16과 같은 모양) ───────────
    print("\n=== §4. 🚨 mode가 FormData로 실제 전달되는가 (BL-16 계열) ===")

    def bundle(entries):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("command_cache.json", json.dumps(entries, ensure_ascii=False))
            z.writestr(portable.MANIFEST_NAME, json.dumps(
                {"bundle_version": portable.BUNDLE_VERSION, "product": "pluiz",
                 "created": "2026-09-10T00:00:00", "items": {}}))
        return buf.getvalue()

    def entry(pattern, app):
        return {"pattern": pattern,
                "tool_calls": [{"name": "open_app", "args": {"app": app}}],
                "response_template": f"✓ {app}", "hit_count": 1,
                "is_seed": False, "source": "dynamic"}

    # 먼저 하나 넣어 둔다
    r = client.post("/import", headers=hdr,
                    files={"file": ("a.zip", bundle({"노트 띄워줘": entry("노트 띄워줘", "메모장")}))},
                    data={"mode": "merge"})
    check("가져오기가 200", r.status_code == 200, r.text[:200])
    check("사람이 읽을 문장을 준다", "message" in r.json(), r.json())

    cache_file = os.environ["PLUIZ_CACHE_FILE"]
    with open(cache_file, encoding="utf-8") as f:
        got = json.load(f)
    check("파일에 실제로 들어갔다", "노트 띄워줘" in got, list(got)[:5])

    # 같은 패턴을 다른 내용으로 — merge면 지켜지고 replace면 덮인다.
    # **mode가 무시되면 이 둘이 구별되지 않는다** — 그게 BL-16이 남긴 교훈이다.
    r = client.post("/import", headers=hdr,
                    files={"file": ("b.zip", bundle({"노트 띄워줘": entry("노트 띄워줘", "계산기")}))},
                    data={"mode": "merge"})
    with open(cache_file, encoding="utf-8") as f:
        got = json.load(f)
    check("mode=merge면 기존을 지킨다",
          got["노트 띄워줘"]["tool_calls"][0]["args"]["app"] == "메모장",
          got["노트 띄워줘"])

    r = client.post("/import", headers=hdr,
                    files={"file": ("c.zip", bundle({"노트 띄워줘": entry("노트 띄워줘", "계산기")}))},
                    data={"mode": "replace"})
    with open(cache_file, encoding="utf-8") as f:
        got = json.load(f)
    check("🚨 mode=replace가 **실제로 전달된다** (Form(...)을 빼면 여기서 깨진다)",
          got["노트 띄워줘"]["tool_calls"][0]["args"]["app"] == "계산기",
          got["노트 띄워줘"])

    # ── §5. 오염된 번들은 API로도 못 들어온다 ───────────────
    print("\n=== §5. 🚨 오염된 번들이 API 경로로도 막힌다 (BL-27) ===")
    r = client.post("/import", headers=hdr,
                    files={"file": ("d.zip", bundle({"그래": entry("그래", "메모장")}))},
                    data={"mode": "merge"})
    with open(cache_file, encoding="utf-8") as f:
        got = json.load(f)
    check("🚨 '그래'가 API로도 안 들어온다", "그래" not in got, list(got)[:5])
    check("거른 사실을 말한다", "거르고 넣지 않았어요" in r.json().get("message", ""),
          r.json().get("message"))

    # ── §6. 메모리 캐시가 갱신된다 ──────────────────────────
    print("\n=== §6. 가져온 명령이 바로 먹는다 (reload) ===")
    from core.command_cache import get_cache
    check("프로세스 안 캐시에도 반영됐다",
          any("노트" in k for k in get_cache()._cache),
          [k for k in get_cache()._cache if not get_cache()._cache[k].is_seed][:5])

    # ── §7. 왕복 ────────────────────────────────────────────
    print("\n=== §7. 내보낸 것을 그대로 다시 가져올 수 있다 ===")
    exported = client.get("/export", headers=hdr).content
    r = client.post("/import", headers=hdr,
                    files={"file": ("round.zip", exported)}, data={"mode": "merge"})
    check("자기 자신을 가져와도 200", r.status_code == 200, r.text[:200])
    check("왕복에서 거절이 없다",
          not r.json()["report"].get("cache", {}).get("rejected"),
          r.json()["report"].get("cache"))

    # ── §8. UI 배선 (BL-13이 가르쳐 준 것) ──────────────────
    #
    # 프런트와 서버가 **다른 파일**이라 어긋나도 아무도 안 알려 준다.
    # BL-13에서 `test_wakeword_ui.py`가 필드 이름(422)·토큰 경로(401)를
    # 소스 대조로 못 박은 것과 같은 수법이다.
    print("\n=== §8. UI 배선 — 프런트와 서버가 같은 말을 하는가 ===")
    ui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "electron-ui", "renderer", "index.html")
    with open(ui, encoding="utf-8") as f:          # ⚠️ cp949로 읽으면 깨진다(절대규칙 7)
        html = f.read()

    check("내보내기 버튼이 있다", 'id="export-btn"' in html)
    check("가져오기 버튼이 있다", 'id="import-btn"' in html)
    check("파일 선택 input이 있다", 'id="import-file"' in html)
    check("zip만 고르게 한다", 'accept=".zip"' in html)

    check("경로가 서버와 같다 — /export", "`${API}/export`" in html)
    check("경로가 서버와 같다 — /import", "`${API}/import`" in html)
    check("필드 이름이 서버와 같다 — file",
          "fd.append('file'" in html)
    check("필드 이름이 서버와 같다 — mode",
          "fd.append('mode'" in html)

    # 🔒 다운로드를 <a href>로 걸면 토큰이 안 실려 401이 난다 (BL-14).
    #    사용자에겐 «그 버튼만 조용히 안 되는» 것으로 보인다.
    check("🔒 다운로드를 fetch로 받는다 (토큰 래퍼를 타야 한다 — BL-14)",
          "await fetch(`${API}/export`)" in html)
    check("🔒 <a href>로 /export를 직접 걸지 않는다",
          'href="' + "${API}/export" not in html and "href='${API}/export" not in html)

    # 되돌릴 수 없는 변경 앞에서는 한 번 묻는다
    check("가져오기 전에 확인을 받는다", "confirm(" in html.split("async function importBundle")[-1])
    check("기본이 merge다 (조용한 덮어쓰기 없음)", "'merge'" in html)
    check("API 키가 안 담긴다고 말해 준다", "API 키" in html and "담기지 않아요" in html)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
