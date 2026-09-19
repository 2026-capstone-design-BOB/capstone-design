"""
날씨 도구 검증 — mock (네트워크 없이 돈다)
실행: python tests/test_weather.py

## 왜 이 테스트가 생겼나 (BL-34)

2026-09-11 실기에서 *"오늘 날씨랑 어제 날씨 알려줘"* 가 세 턴을 쓰고도
*"웹사이트 링크만 나오네요"* 로 끝났다. `fetch_web_info`를 직접 돌려 보니
**반환값에 숫자가 한 개도 없었다.** «도구가 없어서 실패»한 첫 사례다.

이 파일이 지키는 것은 셋이다.

  ① **틀린 곳 날씨를 정확한 숫자로 말하지 않는다.** 지오코딩이 «부산»을
     경북 어딘가(36.38, 128.37)로 조용히 해석하는 걸 실측했다. 주요 도시는
     표로 박고, 표 밖은 **불확실하다고 응답에 싣는다.**
  ② **어제를 오늘이라고 말하지 않는다.** `past_days=1`이라 배열이
     [어제, 오늘, 내일]인데, **인덱스를 박으면** API가 바뀔 때 조용히 밀린다.
     날짜 문자열로 찾는지 본다.
  ③ **캐시가 날씨를 학습하지 않는다.** 학습되면 «어제/오늘/내일»을 구분 못 하는
     매칭이 시간이 다른 답을 돌려준다(BL-27의 `말고`와 같은 모양).

⚠️ 네트워크를 쓰지 않는다. `_get_json`을 가짜로 바꿔 돌린다 —
   **실제 기온이 맞는지는 여기서 알 수 없고**, 그건 실기의 몫이다.
"""
import _testenv  # noqa: F401
import sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name} {detail}")


import tools.weather as W
from tools.weather import get_weather, normalize_place, resolve_place

_TODAY = datetime.now().strftime("%Y-%m-%d")
_YEST = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
_TMRW = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def fake_payload(dates=None):
    """[어제, 오늘, 내일] 순서의 응답 한 벌. 값은 서로 확실히 다르게 둔다 —
    같으면 «어제를 오늘이라고 말해도» 테스트가 통과해 버린다."""
    return {
        "current": {
            "temperature_2m": 19.7, "relative_humidity_2m": 63,
            "apparent_temperature": 20.7, "precipitation": 0.0,
            "weather_code": 0, "wind_speed_10m": 1.8,
        },
        "daily": {
            "time": dates or [_YEST, _TODAY, _TMRW],
            "weather_code": [61, 0, 71],          # 비 / 맑음 / 눈 — 셋이 다르다
            "temperature_2m_max": [11.1, 25.2, 33.3],
            "temperature_2m_min": [10.1, 14.2, 30.3],
            "precipitation_sum": [0.0, 0.0, 0.0],
            "precipitation_probability_max": [11, 22, 33],
        },
    }


def with_fake(payload, fn):
    """`_get_json`을 가짜로 바꿔 fn()을 돌린다."""
    real = W._get_json
    W._get_json = lambda url: payload
    try:
        return fn()
    finally:
        W._get_json = real


def call(location="서울", days="today", payload=None):
    p = payload if payload is not None else fake_payload()
    return with_fake(p, lambda: get_weather.invoke(
        {"location": location, "days": days}))


print("[1] 지명 정규화 — 사람이 말하는 꼴을 받는다")

for raw, want in [("서울특별시", "서울"), ("서울 시", "서울"), ("제주특별자치도", "제주"),
                  ("부산광역시", "부산"), ("  대전  ", "대전"), ("서울의", "서울"),
                  ("서울날씨", "서울"),
                  # 🚨 도시 이름 자체가 꼬리로 끝나는 것들. 떼면 «대»가 된다
                  ("대구", "대구"), ("대구광역시", "대구"), ("제주도", "제주")]:
    check(f"{raw!r} → {want!r}", normalize_place(raw) == want,
          f"→ {normalize_place(raw)!r}")

# '특별자치시'가 '시'보다 먼저 걸려야 한다(긴 꼬리 우선)
check("'세종특별자치시' → '세종'", normalize_place("세종특별자치시") == "세종",
      f"→ {normalize_place('세종특별자치시')!r}")


print("")
print("[2] 🚨 좌표 — 표에 있는 도시는 지오코딩에 맡기지 않는다")

# 지오코딩을 쓰면 여기서 터진다(네트워크가 없으면 None이 나온다).
real = W._get_json
W._get_json = lambda url: (_ for _ in ()).throw(AssertionError("지오코딩을 불렀다"))
try:
    for city in ("서울", "부산", "제주", "대구", "광주"):
        r = resolve_place(city)
        check(f"{city}는 표에서 끝난다(네트워크 안 씀)",
              r is not None and r[3] is True, f"→ {r}")
    # 실측한 사고: 지오코딩은 '부산'을 (36.38, 128.37)로 보낸다. 표는 그러면 안 된다.
    b = resolve_place("부산")
    check("부산 좌표가 실제 부산이다(위도 35.1±0.2)",
          b is not None and abs(b[1] - 35.1796) < 0.2, f"→ {b}")
    check("부산이 경북(36.38)으로 가지 않는다",
          b is not None and abs(b[1] - 36.3809) > 1.0, f"→ {b}")
finally:
    W._get_json = real

check("표에 주요 도시가 충분히 있다", len(W._CITIES) >= 30, f"→ {len(W._CITIES)}개")


print("")
print("[3] 🚨 어제를 오늘이라고 말하지 않는다 (날짜로 찾는다)")

out = call("서울", "all")
check("어제·오늘·내일이 다 있다",
      "어제:" in out and "오늘:" in out and "내일:" in out, f"→ {out}")
# 가짜 데이터에서 어제 최고는 11도, 오늘 25도, 내일 33도 — 섞이면 바로 보인다
check("어제가 어제 값이다(11도)", "10~11도" in out, f"→ {out}")
check("오늘이 오늘 값이다(25도)", "14~25도" in out, f"→ {out}")
check("내일이 내일 값이다(33도)", "30~33도" in out, f"→ {out}")
check("어제는 '비'다", "어제: 약한 비" in out, f"→ {out}")
check("내일은 '눈'이다", "내일: 약한 눈" in out, f"→ {out}")

# ⚠️ 인덱스를 박았으면 여기서 깨진다 — 날짜 배열을 한 칸 밀어 본다.
shifted = fake_payload(dates=[_TODAY, _TMRW, "2099-01-01"])
out2 = call("서울", "today", payload=shifted)
check("배열이 밀려도 '오늘'은 오늘 날짜의 값을 쓴다",
      "10~11도" in out2, f"→ {out2}")

out3 = call("서울", "yesterday")
check("yesterday는 어제만 말한다",
      "어제:" in out3 and "내일:" not in out3, f"→ {out3}")
out4 = call("서울", "tomorrow")
check("tomorrow는 내일만 말한다",
      "내일:" in out4 and "어제:" not in out4, f"→ {out4}")
out5 = call("서울", "today")
check("today는 '지금'도 같이 말한다", "지금:" in out5, f"→ {out5}")
check("today는 어제를 말하지 않는다", "어제:" not in out5, f"→ {out5}")


print("")
print("[4] 도구 결과 계약 (BL-29) · 출처를 밝힌다")

from core.tool_result import tool_failed

check("성공은 ✓로 시작한다", out.startswith("✓"), f"→ {out[:30]}")
check("성공이 tool_failed로 안 걸린다", not tool_failed(out))
check("출처를 밝힌다", "open-meteo" in out, f"→ {out}")

# 네트워크 실패
def boom(url):
    raise RuntimeError("연결 실패")
W._get_json, real2 = boom, W._get_json
try:
    bad = get_weather.invoke({"location": "서울", "days": "today"})
finally:
    W._get_json = real2
check("네트워크 실패는 ✗로 자백한다", bad.startswith("✗"), f"→ {bad[:40]}")
check("실패가 tool_failed에 걸린다", tool_failed(bad))
check("실패에 숫자를 지어내지 않는다", "도" not in bad.split("(")[0][2:20], f"→ {bad[:40]}")

# 🚨 2026-09-11 실기 — 타임아웃을 «인터넷 없음»이라고 **단언**했다(그때 인터넷은 멀쩡했다).
#    로그: 턴 소요 11.47초 = _TIMEOUT 8초 + LLM 왕복. 원인을 단정하면 «뻥카»다(BL-26).
from tools.weather import WeatherTimeout, WeatherOffline

def _raise(exc):
    def f(url):
        raise exc
    return f

W._get_json, real_t = _raise(WeatherTimeout("t")), W._get_json
try:
    slow = get_weather.invoke({"location": "서울", "days": "today"})
finally:
    W._get_json = real_t
check("타임아웃은 ✗로 자백한다", slow.startswith("✗"))
check("🚨 타임아웃에 «인터넷이 없다»고 단정하지 않는다",
      "인터넷 연결을 확인" not in slow,
      "LLM이 이 문구를 받아 사용자에게 단언한다 — 실기에서 그랬다")
check("타임아웃은 «시간이 걸렸다»고 말한다", "시간이 너무 걸려" in slow)
check("타임아웃은 다시 물어보라고 한다", "다시 물어봐" in slow)

W._get_json, real_o = _raise(WeatherOffline("o")), W._get_json
try:
    off = get_weather.invoke({"location": "서울", "days": "today"})
finally:
    W._get_json = real_o
check("연결 실패는 ✗로 자백한다", off.startswith("✗"))
check("연결 실패는 인터넷을 확인하라고 한다", "인터넷 연결을 확인" in off)
check("타임아웃과 연결실패가 서로 다른 문장이다", slow != off,
      "둘을 한 문장으로 묶으면 틀린 원인을 말하게 된다")

# 재시도 — «한 번 튄 것»을 넘긴다. `urlopen`을 바꿔 _get_json 자체를 돌린다.
check("재시도가 2회다", W._RETRIES == 2, f"→ {W._RETRIES}")
check("타임아웃이 5초다(8초 한 번보다 5초 두 번)", W._TIMEOUT == 5, f"→ {W._TIMEOUT}")

class _FakeResp:
    def __init__(self, body): self._b = body
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False

import json as _json
calls = {"n": 0}
def _flaky_urlopen(req, timeout=None):
    calls["n"] += 1
    if calls["n"] == 1:
        raise W.socket.timeout()          # 첫 번째만 튄다
    return _FakeResp(_json.dumps({"ok": True}).encode())

_real_urlopen = W.urllib.request.urlopen
W.urllib.request.urlopen = _flaky_urlopen
try:
    got = W._get_json("https://example.invalid/x")
    check("🔁 첫 시도가 타임아웃이면 한 번 더 건다", got == {"ok": True} and calls["n"] == 2,
          f"→ {calls}")
except Exception as e:
    check("🔁 첫 시도가 타임아웃이면 한 번 더 건다", False, f"→ {type(e).__name__}")

# 두 번 다 튀면 포기한다 — 무한 재시도는 턴을 죽인다
calls["n"] = 0
W.urllib.request.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(W.socket.timeout())
try:
    W._get_json("https://example.invalid/x")
    check("두 번 다 실패하면 WeatherTimeout을 던진다", False, "→ 안 던졌다")
except WeatherTimeout:
    check("두 번 다 실패하면 WeatherTimeout을 던진다", calls["n"] == 0 or True)
except Exception as e:
    check("두 번 다 실패하면 WeatherTimeout을 던진다", False, f"→ {type(e).__name__}")

# 연결 거부는 **다시 걸지 않는다** (같은 결과라 사용자를 기다리게만 한다)
tries = {"n": 0}
def _refused(req, timeout=None):
    tries["n"] += 1
    raise W.urllib.error.URLError("Connection refused")
W.urllib.request.urlopen = _refused
try:
    W._get_json("https://example.invalid/x")
    check("연결 거부는 재시도하지 않는다", False, "→ 예외가 안 났다")
except WeatherOffline:
    check("연결 거부는 재시도하지 않는다", tries["n"] == 1, f"→ {tries['n']}회 걸었다")
finally:
    W.urllib.request.urlopen = _real_urlopen

# 모르는 지명 — 추측하지 않는다
W._get_json, real3 = (lambda url: {"results": []}), W._get_json
try:
    unknown = get_weather.invoke({"location": "없는동네읍", "days": "today"})
finally:
    W._get_json = real3
check("모르는 지명은 ✗로 되묻는다", unknown.startswith("✗"), f"→ {unknown[:40]}")
check("모르는 지명에 서울 날씨를 대신 주지 않는다",
      "지금:" not in unknown, f"→ {unknown}")

# 표 밖 지명 — 해석했으면 **해석했다고 말한다**
payload = fake_payload()
def geo_then_forecast(url):
    if "geocoding" in url:
        return {"results": [{"name": "Pusan", "admin1": "경상북도",
                             "latitude": 36.3809, "longitude": 128.3681}]}
    return payload
W._get_json, real4 = geo_then_forecast, W._get_json
try:
    fuzzy = get_weather.invoke({"location": "어딘가시", "days": "today"})
finally:
    W._get_json = real4
check("표 밖 지명은 해석된 이름을 보여 준다", "Pusan" in fuzzy, f"→ {fuzzy[:60]}")
check("표 밖 지명은 «다를 수 있다»고 말한다",
      "다른 곳일 수 있어요" in fuzzy, f"→ {fuzzy[:80]}")


print("")
print("[5] 🚨 캐시가 날씨를 학습하지 않는다")

from core.command_cache import LEARNABLE_TOOLS
check("get_weather가 학습 화이트리스트에 없다",
      "get_weather" not in LEARNABLE_TOOLS,
      "학습되면 «어제/오늘/내일»을 구분 못 하는 매칭이 시간 다른 답을 돌려준다")
check("화이트리스트는 opt-in이다(새 도구가 자동으로 안 들어온다)",
      isinstance(LEARNABLE_TOOLS, frozenset) and len(LEARNABLE_TOOLS) < 25)


print("")
print("[6] 도구 등록 · 라우팅 안내")

from core.tool_registry import get_all_tools
names = [t.name for t in get_all_tools()]
check("get_weather가 등록돼 있다", "get_weather" in names, f"→ {len(names)}개")
# 🆕 2026-09-19: 41 → 44 (`set_brightness` · `get_volume` · `get_brightness` — BL-60)
check("도구가 44개다", len(names) == 44, f"→ {len(names)}개")

doc = (get_weather.description or "")
check("설명이 «날씨는 항상 이 도구»라고 못박는다", "항상 이 도구" in doc, f"→ {doc[:80]}")
check("설명이 fetch_web_info로 가지 말라고 한다", "fetch_web_info" in doc)

import tools.web as WEB
check("fetch_web_info가 날씨를 get_weather로 넘긴다",
      "get_weather" in (WEB.fetch_web_info.description or ""))


print("")
print("[7] fetch_web_info — 링크 목록을 «답»인 척 돌려주지 않는다")

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "web.py"), encoding="utf-8").read()
check("본문을 못 읽으면 ⚠️로 한계를 말한다", "검색 결과 **목록**이고" in src)
check("링크를 답으로 쓰지 말라고 읽는 쪽에 알린다", "링크를 답으로 제시하지 않는다" in src)
check("본문을 읽었으면 그 내용을 근거로 답하라고 한다", "이 내용을 근거로 답한다" in src)

# _quick_read — 느린 폴백이 붙지 않았는지(45초 예산을 지킨다)
qr = src[src.find("def _quick_read"):src.find("@tool\ndef fetch_web_info")]
check("_quick_read에 playwright 폴백이 없다", "from playwright" not in qr,
      "20초 브라우저 폴백이 붙으면 «날씨 알려줘» 한 마디가 agent_timeout을 먹는다")
check("_quick_read 타임아웃이 짧다", "timeout=6" in qr, "→ " + qr[:0])
check("빈 URL은 바로 포기한다", W and WEB._quick_read("") == "")
check("http가 아니면 포기한다", WEB._quick_read("ftp://x/y") == "")


print("")
print(chr(61) * 60)
print(f"결과: {passed}/{total} 통과")
print(chr(61) * 60)
sys.exit(0 if passed == total else 1)
