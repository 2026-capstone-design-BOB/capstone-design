"""
웨이크워드 설정 검증 — mock (마이크·모델 불필요)
실행: python tests/test_wakeword.py

실제 음성 인식은 사람이 마이크에 대고 말해야 하므로 여기서 하지 않는다.
여기서 보는 것은 **말하기 전에 이미 정해져 있는 것들**이다:
  - 사용자가 정한 웨이크워드가 실제로 반영되는가
  - 기본값이 "플루이즈"인가 (2026-09-02 이전엔 "소윤아"였다)
  - "헤이 플루이즈"처럼 앞뒤에 말을 붙여도 걸리는가
  - 흔한 오인식 변형이 자동 생성되는가
  - **엉뚱한 말에 반응하지 않는가** ← 오탐이 나면 웨이크워드는 못 쓴다
  - 끄면 정말 꺼지는가

⚠️ `services/wakeword.py`는 최상위에서 sounddevice·faster-whisper를 import 한다.
없으면 `_die()`가 프로세스를 죽이므로, 여기서는 **소스를 읽어 매칭 부분만 떼어내
실행**한다. 그래야 CI(ubuntu, 오디오 패키지 없음)에서도 계약을 검증할 수 있다.
"""
import sys, os, re, types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

passed = total = 0
def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond: passed += 1; print(f"  ✓ {name}")
    else:    print(f"  ✗ {name} {detail}")


# ── 오디오 의존성 없이 매칭 로직만 로드 ──────────────────────────
# 소스에서 "웨이크워드" 섹션부터 _reload_loop 앞까지를 떼어내 독립 실행한다.
_src = open(os.path.join(_ROOT, "services", "wakeword.py"), encoding="utf-8").read()
_start = _src.index("_RELOAD_SEC = ")   # 모듈 docstring의 언급이 아니라 실제 정의부터
_end = _src.index("def _reload_loop")
_mod = types.ModuleType("wakeword_matching")
_mod.__dict__.update({"sys": sys, "os": os, "re": re, "time": __import__("time")})
exec(compile(_src[_start:_end], "wakeword_matching", "exec"), _mod.__dict__)

expand, load, is_wake = _mod._expand, _mod._load_wake_words, _mod.is_wake


def _set_words(words, enabled=True):
    """설정을 바꾼 뒤 매칭 테이블을 다시 만든다 (실제 .env는 건드리지 않는다)."""
    class FakeSettings:
        wake_words = words
        wake_word_enabled = enabled
        @property
        def wake_word_list(self):
            return [w.strip() for w in self.wake_words.split(",") if w.strip()]
    fake = FakeSettings()

    # ⚠️ 진짜 config.settings를 import 하지 않는다 — pydantic_settings가 필요한데
    #    CI는 그걸 설치하지 않는다. stub 모듈을 sys.modules에 꽂아 넣는다.
    #    `_load_wake_words()`가 `from config.settings import get_settings` 하므로 stub이 잡힌다.
    def _get(): return fake
    _get.cache_clear = lambda: None

    stub = types.ModuleType("config.settings")
    stub.get_settings = _get
    parent = types.ModuleType("config")
    parent.settings = stub

    saved = {k: sys.modules.get(k) for k in ("config", "config.settings")}
    sys.modules["config"] = parent
    sys.modules["config.settings"] = stub
    try:
        _mod.WAKE_WORDS = load()
    finally:
        for k, v in saved.items():
            if v is None: sys.modules.pop(k, None)
            else:         sys.modules[k] = v
    return _mod.WAKE_WORDS


print("=== ① 기본값은 '플루이즈' ===")
words = _set_words("")
check("기본 웨이크워드에 '플루이즈' 포함", "플루이즈" in words, f"→ {words[:5]}")
check("옛 웨이크워드 '소윤아'는 더 이상 기본값이 아님",
      not any("소윤" in w for w in words), f"→ {words[:8]}")

print("\n=== ② 호출 형태 (부분매칭) ===")
for phrase in ["플루이즈", "헤이 플루이즈", "야 플루이즈", "플루이즈야", "플루이즈 뭐해",
               "Hey Pluiz", "pluiz"]:
    check(f"인식: {phrase!r}", is_wake(phrase))

print("\n=== ③ 오인식 변형 자동 생성 ===")
for variant in ["플루이스", "블루이즈", "프루이즈", "플루이지"]:
    check(f"변형 인식: {variant!r}", is_wake(variant))
check("변형은 거리 1까지만 (조합 폭발 방지)",
      len(expand("플루이즈")) < 20, f"→ {len(expand('플루이즈'))}개")

print("\n=== ④ 엉뚱한 말에 반응하지 않는다 (오탐 방지) ===")
for phrase in ["블루투스 켜줘", "루이비통 검색해줘", "오늘 날씨 어때", "메모장 열어줘",
               "그냥 아무 말이나 해봤어", ",", "...", "   "]:
    check(f"무시: {phrase!r}", not is_wake(phrase))

print("\n=== ⑤ 사용자가 직접 정한 웨이크워드가 반영된다 ===")
words = _set_words("컴퓨터")
check("'컴퓨터'로 바꾸면 인식됨", is_wake("컴퓨터 뭐해"))
check("바꾼 뒤엔 기본값('플루이즈')이 안 걸림", not is_wake("플루이즈"), f"→ {words}")

words = _set_words("자비스, 헤이 자비스")
check("여러 개 등록 가능 — '자비스'", is_wake("자비스"))
check("여러 개 등록 가능 — '헤이 자비스'", is_wake("헤이 자비스"))

print("\n=== ⑥ 끄면 정말 꺼진다 ===")
words = _set_words("플루이즈", enabled=False)
check("WAKE_WORD_ENABLED=false → 목록 비움", words == [], f"→ {words}")
check("꺼진 상태에선 웨이크워드도 무시", not is_wake("플루이즈"))

print("\n=== ⑦ 설정 스키마 ===")
# 진짜 Settings는 pydantic_settings가 있어야 한다. CI엔 없으므로 SKIP(사유 명시).
_skipped = []
try:
    from config.settings import Settings
    st = Settings(wake_words="가, 나 , ,다", wake_word_enabled=True)
    check("wake_word_list가 공백·빈 항목을 정리", st.wake_word_list == ["가", "나", "다"],
          f"→ {st.wake_word_list}")
except Exception as e:
    _skipped.append("설정 스키마 (pydantic_settings 없음)")
    print("  ⚠ SKIP 설정 스키마 — pydantic_settings 미설치")

tail = f"  ({len(_skipped)}건 SKIP: {chr(59).join(_skipped)})" if _skipped else ""
print(f"\n결과: {passed}/{total} 통과{tail}")
sys.exit(0 if passed == total else 1)
