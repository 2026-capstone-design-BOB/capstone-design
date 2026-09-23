"""
음성과 텍스트가 **같은 대화**를 쓰는지 검증 (mock — 서버 실행 불필요)
실행: python tests/test_voice_thread.py

## 무슨 일이 있었나 (2026-09-03 실기)

```
👤 그 파일 지워줘            → 🤖 '임시.txt' 파일을 정말 삭제할까요?
🎤 어 삭제해 줘              → 🤖 무엇을 삭제할까요? 파일인가요, 폴더인가요?
                               ← 승인이 아니라 **새 명령**으로 처리됐다
   … 100초 뒤 …
👤 메모장 열어줘             → 🤖 '임시.txt' 파일을 찾을 수 없어서 삭제하지 못했어요.
                               ← 텍스트 쪽에 남아 있던 승인 대기가 이 발화를 삼켰다
```

원인은 한 줄이었다. `main.py`의 `/voice`가

    async def voice_input(audio: UploadFile = File(...), thread_id: str = "default")

였는데, FastAPI는 `Form(...)` 없는 스칼라를 **쿼리 파라미터**로 읽는다. 렌더러는
`FormData`로 보내므로(`fd.append('thread_id', threadId)`) 그 값이 **통째로 무시되고**
음성은 항상 `thread_id="default"`, 텍스트는 `pluiz_<timestamp>` 를 썼다.
**음성과 텍스트가 서로 다른 대화였다.**

증상이 조용해서 위험했다 — 평범한 명령은 각자 잘 도니까 아무 문제가 없어 보이고,
**맥락이 이어져야 하는 순간(승인·"그거")에만** 무너진다.

## 이 테스트가 지키는 것

  - FastAPI가 정말 그렇게 동작한다는 것 (기억이 아니라 실행으로 확인)
  - `main.py`의 `/voice`가 `Form(...)`으로 선언돼 있다는 것
  - 렌더러가 음성·텍스트에 같은 threadId를 쓴다는 것
"""
import sys, os, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0
skipped = []

def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")

def skip(name, reason):
    skipped.append(f"{name} ({reason})")
    print(f"  ⚠ SKIP {name} — {reason}")


print("=== ① FastAPI 동작 확인 — Form 없는 스칼라는 폼 필드를 못 받는다 ===")
# main.py를 import 하지 않는다(STT·psutil 등 무거운 의존성). 같은 시그니처를 직접 세워
# **왜 그 한 줄이 필요한지**를 실행으로 보인다.
try:
    from fastapi import FastAPI, UploadFile, File, Form
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.post("/without_form")          # 고치기 전 시그니처
    async def _without(audio: UploadFile = File(...), thread_id: str = "default"):
        return {"thread_id": thread_id}

    @app.post("/with_form")             # 고친 뒤 시그니처
    async def _with(audio: UploadFile = File(...), thread_id: str = Form("default")):
        return {"thread_id": thread_id}

    c = TestClient(app)
    files = {"audio": ("voice.webm", b"x", "audio/webm")}
    sent = "pluiz_1756880000000"        # 렌더러가 만드는 형태
    data = {"thread_id": sent}          # 렌더러가 보내는 방식(form field)

    got_without = c.post("/without_form", files=files, data=data).json()["thread_id"]
    got_with = c.post("/with_form", files=files, data=data).json()["thread_id"]

    check("Form 없으면 폼 필드가 무시되고 기본값이 쓰인다 (= 실기의 원인)",
          got_without == "default", f"→ {got_without!r}")
    check("Form 선언하면 렌더러가 보낸 값이 들어온다",
          got_with == sent, f"→ {got_with!r}")
except ImportError as e:
    skip("FastAPI 동작 확인", f"fastapi/testclient 없음 — {e}")


print("\n=== ② main.py의 /voice 가 Form으로 선언돼 있다 ===")
src = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
m = re.search(r"async def voice_input\((.*?)\):", src, re.S)
check("voice_input 시그니처를 찾았다", m is not None)
if m:
    sig = m.group(1)
    check("thread_id 가 Form(...) 이다", "thread_id" in sig and "Form(" in sig,
          f"→ {' '.join(sig.split())}")
    check("use_tts 도 Form(...) 이다  (렌더러가 폼으로 보낸다)",
          re.search(r"use_tts[^,]*Form\(", sig) is not None,
          f"→ {' '.join(sig.split())}")
    check("Form 을 import 하고 있다", re.search(r"from fastapi import .*\bForm\b", src) is not None)
    check("왜 필요한지 주석으로 남아 있다 (또 지워지면 조용히 깨진다)",
          "쿼리 파라미터" in src and "Form" in src)


print("\n=== ③ /ws(텍스트)도 같은 thread_id 를 받는다 ===")
check("/ws 핸들러가 thread_id 를 읽는다",
      re.search(r'thread_id\s*=\s*data\.get\("thread_id"', src) is not None)


print("\n=== ④ 렌더러가 음성·텍스트에 같은 threadId 를 쓴다 ===")
ui_path = os.path.join(_ROOT, "electron-ui", "renderer", "index.html")
if os.path.exists(ui_path):
    ui = open(ui_path, encoding="utf-8").read()
    decls = re.findall(r"(?:let|const|var)\s+threadId\s*=", ui)
    check("threadId 선언이 하나뿐이다 (음성·텍스트가 갈리지 않는다)",
          len(decls) == 1, f"→ {len(decls)}개")
    check("음성 요청이 threadId 를 보낸다",
          re.search(r"fd\.append\(\s*'thread_id'\s*,\s*threadId", ui) is not None)
    check("텍스트(WS) 요청이 같은 threadId 를 보낸다",
          re.search(r"thread_id:\s*threadId", ui) is not None)
else:
    skip("렌더러 확인", "electron-ui/renderer/index.html 없음")


tail = f"  ({len(skipped)}건 SKIP: {'; '.join(skipped)})" if skipped else ""
print(f"\n결과: {passed}/{total} 통과{tail}")
sys.exit(0 if passed == total else 1)
