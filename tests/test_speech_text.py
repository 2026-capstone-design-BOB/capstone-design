"""말할 것과 보여줄 것을 가른다 — TTS 정제 (2-2 ⓒ)

    python tests/test_speech_text.py

설계·근거: services/speech_text.py 머리말

## 🚨 양방향으로 박는다

«기호를 뗀다»만 고정하면 **전부 지워 버리는 수정**이 통과한다. 그래서 반대 방향을
같이 못 박는다 — **말은 그대로 남아야 한다.** 이 저장소가 `_await_gone` 20건에서
배운 규율이고, 여기서는 «조용히 말을 잃는» 쪽이 더 나쁘다(사용자는 음성만 듣는다).

## 🔑 이 스위트가 지키는 계약 다섯

  1. **화면 텍스트를 안 바꾼다** — 이 함수의 결과는 오직 TTS 입력이다
  2. **자르지 않는다** — 길이 상한은 조용한 절단이고 BL-15 가 그걸로 데인 자리다
  3. **말을 더하지 않는다** — 마커를 떼되 «실패했어요»를 지어내지 않는다
  4. **관문이 하나다** — 호출부 네 곳이 아니라 `to_bytes_async` 한 곳
  5. **정제가 실패해도 소리는 난다** — 예외·빈 결과면 원문으로 돌아간다

## ⚠️ 보증하지 못하는 것

**실제로 어떻게 들리는지는 사람만 안다.** 여기서는 «TTS 에 무엇이 들어가는가»까지만
잡는다. edge-tts 가 남은 글자를 어떻게 읽는지는 재지 않는다.
"""
import _testenv  # noqa: F401
import sys, os, importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _src(relpath):
    with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def run():
    passed = total = 0

    def check(name, cond, detail=""):
        nonlocal passed, total
        total += 1
        passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}"
              + ("" if cond or not detail else f"   → {detail}"))

    S = _load("pluiz_speech", os.path.join("services", "speech_text.py"))
    say = S.to_speech

    # ═══ ① 실제 응답 — 도구가 돌려주는 문자열 그대로 ═══════════════
    print("=== ① 실제 도구 응답 (tools/filesystem.py 원문) ===")
    out = say("✓ '메모.txt' 파일을 바탕화면에 생성했습니다.\n"
              r"경로: C:\Users\byeonsoyun\Desktop\메모.txt")
    check("경로 줄이 통째로 빠진다", "Users" not in out and "Desktop" not in out, out)
    check("✓ 가 빠진다", "✓" not in out, out)
    check("🔑 **말은 그대로 남는다**", "메모.txt" in out and "바탕화면에 생성했습니다" in out, out)
    check("앞머리에 군더더기가 안 남는다", not out.startswith((",", ".", " ")), repr(out))

    out = say("✗ 파일을 찾을 수 없습니다: 바탕화면/없는파일.txt")
    check("✗ 를 떼도 **실패라는 말이 남는다**", "찾을 수 없습니다" in out, out)
    check("🚨 «실패했어요»를 **지어내지 않는다**", "실패했" not in out, out)

    out = say("⚠️ 메모장을 닫지 못했어요. 저장할지 묻는 창이 떠 있을 수 있어요 — "
              "화면을 확인해 주세요.")
    check("⚠️ 를 떼도 경고 내용이 남는다",
          "닫지 못했어요" in out and "저장할지 묻는 창" in out, out)

    # ═══ ② 자르지 않는다 (BL-15 — 조용한 절단) ════════════════════
    print("=== ② 🚨 자르지 않는다 ===")
    long_ko = "설명을 드릴게요. " * 60          # 약 600자
    out = say(long_ko)
    check("긴 응답을 **안 자른다**", len(out) >= len(long_ko) - 5, f"{len(long_ko)} → {len(out)}")
    check("소스에 길이 상한이 없다",
          "[:200]" not in _src(os.path.join("services", "speech_text.py"))
          and "MAX_LEN" not in _src(os.path.join("services", "speech_text.py")))

    # ═══ ③ 말을 잃지 않는다 — 반대 방향 ═══════════════════════════
    print("=== ③ 🔑 평범한 문장은 **한 글자도 안 바뀐다** ===")
    for plain in [
        "메모장을 열었어요.",
        "지금 볼륨은 40%예요.",
        "배터리가 87% 남았고 충전 중이에요.",
        "그 파일은 바탕화면에 있어요.",
        "오늘 청주는 맑고 기온은 21도예요.",
    ]:
        check(f"그대로: {plain[:18]}", say(plain) == plain, repr(say(plain)))

    check("숫자·퍼센트·소수점이 안 깨진다", say("밝기를 30%로 맞췄어요. 0.62초 걸렸어요.")
          == "밝기를 30%로 맞췄어요. 0.62초 걸렸어요.")
    check("한글 사이 공백이 안 뭉개진다", say("메모장  열었어요.") == "메모장 열었어요.")

    # ═══ ④ 읽으면 이상한 것들 ═════════════════════════════════════
    print("=== ④ 소리로 읽을 수 없는 것 ===")
    out = say("자세한 건 https://www.google.com/search?q=날씨&hl=ko 에서 보세요.")
    check("URL 이 도메인만 남는다", "search?q=" not in out and "www.google.com" in out, out)

    out = say("**중요**: `get_weather` 도구를 썼어요.")
    check("마크다운 기호가 빠진다", "**" not in out and "`" not in out, out)
    check("마크다운 안의 말은 남는다", "중요" in out and "get_weather" in out, out)

    out = say("| 앱 | 상태 |\n| 메모장 | 실행 중 |")
    check("표 구분선(|)이 쉼표가 된다", "|" not in out, out)
    check("표 안의 말은 남는다", "메모장" in out and "실행 중" in out, out)

    out = say("첫째 줄이에요\n둘째 줄이에요")
    check("줄바꿈이 문장 끝으로 읽힌다", "\n" not in out and "줄이에요. 둘째" in out, out)

    out = say("🚨 조심하세요 🔑 중요해요 👁")
    check("이모지가 빠진다", not any(c in out for c in "🚨🔑👁"), out)
    check("이모지 사이 말은 남는다", "조심하세요" in out and "중요해요" in out, out)

    # ═══ ⑤ 빈 결과 · 예외 — 침묵하지 않는다 ═══════════════════════
    print("=== ⑤ 정제가 비거나 터져도 소리는 난다 ===")
    check("빈 입력은 빈 출력", say("") == "")
    check("마커뿐이면 빈 문자열이 된다 (호출부가 원문으로 되돌린다)",
          say("✓").strip() == "", repr(say("✓")))

    T = _src(os.path.join("services", "tts.py"))
    check("🔑 `to_bytes_async` 가 정제를 **반드시** 지난다", "_spoken(text)" in T)
    check("정제 결과가 비면 **원문**을 쓴다", "cleaned if cleaned.strip() else text" in T)
    check("정제가 터져도 **원문**을 쓴다", "return text" in T and "except Exception" in T)
    check("edge-tts 에 넘기는 것이 정제본이다", "Communicate(spoken," in T)

    # ═══ ⑥ 관문이 하나다 ═════════════════════════════════════════
    print("=== ⑥ 🔑 관문이 하나다 (감사 G-13·G-14 의 교훈) ===")
    M = _src("main.py")
    check("🚨 `main.py` 에 따로 박힌 이모지 제거 사본이 **없다**",
          "0x1F441" not in M or "replace(chr(0x1F441)" not in M)
    check("`main.py` 는 응답을 **그대로** to_bytes_async 에 넘긴다",
          'to_bytes_async(payload["text"])' in M)
    # 🚨 다음 사람이 호출부에 또 하나 심는 것을 막는다
    check("`main.py` 가 to_speech 를 직접 부르지 않는다 (사본이 생기는 자리)",
          "to_speech" not in M)

    # ═══ ⑦ 화면 텍스트는 안 바뀐다 ════════════════════════════════
    print("=== ⑦ 🔑 화면에는 경로가 그대로 남는다 ===")
    check("`speech_text` 가 도구·그래프를 import 하지 않는다 (단방향이다)",
          "tools." not in _src(os.path.join("services", "speech_text.py"))
          and "core." not in _src(os.path.join("services", "speech_text.py")))
    check("`to_speech` 는 순수 함수다 (부작용 없음)",
          "open(" not in _src(os.path.join("services", "speech_text.py")))

    # ═══ ⑧ 말투 — 다시 섞이는 것을 막는다 (2-2 ⓐ) ════════════════
    #
    # 🔑 **문구를 고정하지 않는다.** 그러면 문장 하나 고칠 때마다 테스트가 깨진다.
    #   고정하는 것은 «합쇼체가 다시 들어오지 않는다»는 **규칙**이다.
    #
    # 🚨 2026-09-23 실측: 사용자에게 나가는 문장이 **합쇼체 250 : 해요체 210** 으로
    #   섞여 있었다. 같은 파일 안에서도 섞였다. 시스템 프롬프트는 «친근한 구어체»를
    #   요구하는데 **도구가 돌려주는 문장만 딱딱했다.**
    #
    # ⚠️ **docstring 과 주석은 세지 않는다** — docstring 은 LLM 에게 주는 도구
    #   설명이고(«배터리 상태를 확인합니다»가 맞다), 주석에는 *«예전엔 «종료했습니다»가
    #   나갔다»* 같은 **기록**이 있다. 그걸 세면 영원히 빨간불이다.
    print("=== ⑧ 말투 — 사용자에게 나가는 문장은 해요체다 ===")
    import glob
    import re as _re

    FORMAL = _re.compile(r"(습니다|합니다)[.!?]")
    POLITE = _re.compile(r"(어요|아요|해요|예요|에요|게요)[.!?]")
    #: LLM 에게 주는 **지시문**. 사용자 문장이 아니라 여기서는 세지 않는다.
    ALLOW = ("기다리다가 다시 물어봐야",)

    targets = sorted(glob.glob(os.path.join(ROOT, "tools", "*.py"))) + [
        os.path.join(ROOT, "core", x) for x in
        ("graph.py", "command_cache.py", "screen_monitor.py", "pointer.py", "portable.py")]

    leftovers, polite = [], 0
    for path in targets:
        if not os.path.exists(path):
            continue
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        for ln, code in _code_lines(path):
            polite += len(POLITE.findall(code))
            if FORMAL.search(code) and not any(k in code for k in ALLOW):
                leftovers.append(f"{rel}:{ln}")

    check("🚨 사용자에게 나가는 문장에 합쇼체가 **없다**",
          not leftovers, f"{len(leftovers)}곳: {leftovers[:3]}")
    # 🔑 **반대 방향** — 문장을 «전부 지워서» 통과시키는 수정을 막는다
    check("🔑 그래도 말은 남아 있다 (해요체 문장 200개 이상)", polite > 200, f"→ {polite}개")

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total


def _strip_comment(line: str) -> str:
    """따옴표 밖의 첫 `#` 앞까지. 주석에는 결함의 **기록**이 남아 있어야 한다."""
    quote = None
    i = 0
    triples = ('"""', "'''")
    while i < len(line):
        if quote:
            if line[i] == "\\":
                i += 2
                continue
            if line.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
        else:
            if line.startswith(triples, i):
                quote = line[i:i + 3]
                i += 3
                continue
            if line[i] in ("'", '"'):
                quote = line[i]
                i += 1
                continue
            if line[i] == "#":
                return line[:i]
        i += 1
    return line


def _code_lines(path):
    """docstring 블록과 주석을 뺀 **코드 부분만** 돌려준다. (번호, 코드)"""
    in_doc = None
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            if in_doc:
                if in_doc in line:
                    in_doc = None
                continue
            code = _strip_comment(line)
            # 🚨 **한 줄짜리 docstring** 도 건너뛴다 — 삼중따옴표 개수가 짝수라
            #   «열린 블록» 판정에 안 걸린다. 2026-09-23 에 실제로 여기서 새어
            #   도구 설명 6개가 «말투 위반»으로 잡혔다(설명은 LLM 에게 주는 글이다).
            if code.lstrip().startswith(('"""', "'''", 'r"""', "r'''", 'f"""', "f'''")):
                if code.count('"""') % 2 == 1 or code.count("'''") % 2 == 1:
                    in_doc = '"""' if code.count('"""') % 2 == 1 else "'''"
                continue
            for tq in ('"""', "'''"):
                if code.count(tq) % 2 == 1:
                    in_doc = tq
                    break
            if in_doc:
                continue
            yield i, code


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
