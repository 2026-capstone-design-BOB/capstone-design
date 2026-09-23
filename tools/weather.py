# -*- coding: utf-8 -*-
"""
날씨 도구 — **검색이 아니라 자료로 답한다.**

## 왜 이 파일이 따로 생겼나 (2026-09-11, BL-34)

TASKS에 *"도구를 더 만들지 않는다 — «도구가 없어서 실패»한 사례가 아직 하나도
확인되지 않았다"* 고 적어 뒀다. **2026-09-11에 그 사례가 처음 확인됐다.**

사용자가 *"오늘 날씨랑 어제 날씨 알려줘"* 라고 했고, 에이전트는 세 턴을 쓰고도
*"웹사이트 링크만 나오네요"* 로 끝났다. 로그를 보면 `fetch_web_info` 하나만 불렸고,
그 도구를 직접 돌려 보니 반환값에 **숫자가 한 개도 없었다** — 검색 결과는
AccuWeather·기상청 **링크와 사이트 소개문**이었고, 마지막 항목은 한 달 전
보도자료였다. 모델은 거짓말을 하지 않았다. **답할 재료가 없었다.**

그래서 «검색해서 읽는다»가 아니라 **«자료를 받아온다»** 로 바꾼다.

## 출처

`open-meteo.com` — API 키가 필요 없고, `past_days`로 **어제**를 준다
(사용자가 물은 것이 정확히 그것이다). 응답에 **출처를 밝힌다** — 근거 없이
숫자를 말하면 그게 더 나쁜 종류의 «뻥카»다(BL-26).

## 🚨 좌표를 지오코딩에 맡기지 않는 이유 — 실측했다

```
Seoul → 서울특별시 (37.566, 126.978)   ✓
서울   → 결과 없음                      ✗
부산   → 'Pusan'   (36.381, 128.368)   🚨 부산이 아니다. 경북 어딘가다
Busan → 부산광역시 (35.102, 129.030)   ✓
```

한글 지명이 **엉뚱한 좌표로 조용히 해석된다.** 그러면 이 도구는
«틀린 곳 날씨를 정확한 숫자로 말하는» 도구가 된다 — `click_ui_element`에
좌표 인자를 안 준 것(절대규칙 9)과 같은 이유로 그게 제일 나쁘다.

그래서 **주요 도시는 표로 박아 두고**, 표에 없으면 지오코딩을 쓰되
**해석된 지명을 반드시 응답에 싣는다.** 틀렸으면 사용자가 본다.
"""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from langchain_core.tools import tool

# 🚨 2026-09-11 실기 — 첫 시도가 **타임아웃으로 실패**했다(턴 소요 11.47초
#    = 8초 + LLM 왕복). 그 시각 네트워크가 흔들리고 있었다(같은 구간에서 STT도
#    whisper로 떨어졌다). 8초를 한 번 기다리느니 **5초씩 두 번**이 낫다 —
#    최악은 비슷한데 «한 번 튄 것»은 넘길 수 있다.
_TIMEOUT = 5
_RETRIES = 2
_UA = {"User-Agent": "Mozilla/5.0 (Pluiz)"}

# ── 주요 도시 좌표 (기상청·위키 기준) ─────────────────────────────
# ⚠️ 지오코딩이 한글을 못 읽는다(위 주석). 흔한 곳은 여기서 끝낸다.
_CITIES = {
    "서울": (37.5665, 126.9780), "부산": (35.1796, 129.0756),
    "대구": (35.8714, 128.6014), "인천": (37.4563, 126.7052),
    "광주": (35.1595, 126.8526), "대전": (36.3504, 127.3845),
    "울산": (35.5384, 129.3114), "세종": (36.4800, 127.2890),
    "수원": (37.2636, 127.0286), "용인": (37.2411, 127.1776),
    "성남": (37.4200, 127.1265), "고양": (37.6584, 126.8320),
    "부천": (37.5035, 126.7660), "안양": (37.3943, 126.9568),
    "화성": (37.1995, 126.8310), "평택": (36.9921, 127.1129),
    "의정부": (37.7381, 127.0338), "청주": (36.6424, 127.4890),
    "천안": (36.8151, 127.1139), "전주": (35.8242, 127.1480),
    "포항": (36.0190, 129.3435), "창원": (35.2280, 128.6811),
    "김해": (35.2285, 128.8894), "제주": (33.4996, 126.5312),
    "서귀포": (33.2541, 126.5601), "춘천": (37.8813, 127.7300),
    "강릉": (37.7519, 128.8761), "원주": (37.3422, 127.9202),
    "안동": (36.5684, 128.7294), "여수": (34.7604, 127.6622),
    "목포": (34.8118, 126.3922), "군산": (35.9676, 126.7369),
    "경주": (35.8562, 129.2247), "진주": (35.1800, 128.1076),
    "속초": (38.2070, 128.5918),
}

# 지오코딩에 넘길 때 쓰는 영문 이름 — 한글은 위 표에서 끝나므로 예비용이다.
_ROMAN = {"서울": "Seoul", "부산": "Busan", "대구": "Daegu", "인천": "Incheon",
          "광주": "Gwangju", "대전": "Daejeon", "울산": "Ulsan", "제주": "Jeju"}

# WMO weather code → 한국어. (open-meteo가 쓰는 표준 코드다)
_WMO = {
    0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림",
    45: "안개", 48: "서리 안개",
    51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비",
    56: "어는 이슬비", 57: "강하게 어는 이슬비",
    61: "약한 비", 63: "비", 65: "강한 비",
    66: "어는 비", 67: "강하게 어는 비",
    71: "약한 눈", 73: "눈", 75: "많은 눈", 77: "싸락눈",
    80: "소나기", 81: "소나기", 82: "강한 소나기",
    85: "약한 소낙눈", 86: "소낙눈",
    95: "천둥번개", 96: "천둥번개와 우박", 99: "천둥번개와 큰 우박",
}

#: 지명에서 떼어 내는 꼬리. 긴 것부터 — '특별자치시'가 '시'보다 먼저 걸려야 한다.
_SUFFIXES = ("특별자치시", "특별자치도", "특별시", "광역시", "시", "군", "구", "도")


class WeatherTimeout(Exception):
    """응답이 늦었다.

    ⚠️ **«인터넷이 없다»와 다르다.** 둘을 한 예외로 묶었더니 실기에서
    LLM이 타임아웃을 받고 *"인터넷 연결이 없어서"* 라고 **단언했다** —
    그때 인터넷은 멀쩡했다. 틀린 원인을 말하는 것도 «뻥카»의 한 종류다(BL-26).
    """


class WeatherOffline(Exception):
    """연결 자체가 안 됐다(DNS·연결 거부). 다시 걸어도 같다."""


def _get_json(url: str) -> dict:
    last = None
    for _ in range(_RETRIES):
        req = urllib.request.Request(url, headers=_UA)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except socket.timeout:
            last = WeatherTimeout("timeout")
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, socket.timeout):
                last = WeatherTimeout("timeout")
            else:
                # 다시 걸어도 같은 결과다. 기다리게 하지 않는다.
                raise WeatherOffline(str(reason or e))
    raise last if last is not None else WeatherTimeout("timeout")


def normalize_place(name: str) -> str:
    """'서울특별시' · '서울 시' · '서울의' → '서울'.

    🚨 **꼬리를 떼기 전에 표를 먼저 본다.** 안 그러면 «대구»가 «대»가 된다 —
       도시 이름 자체가 `구`·`도`·`시`로 끝나는 경우가 있다(대구·제주도).
       2026-09-11에 테스트가 이걸 잡았다. **떼는 것보다 아는 것이 먼저다.**
    """
    s = (name or "").strip().replace(" ", "")
    for tail in ("의", "날씨", "날시"):
        if s.endswith(tail) and len(s) > len(tail):
            s = s[: -len(tail)]
    if s in _CITIES:                     # ← 아는 이름이면 손대지 않는다
        return s
    for suf in _SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def resolve_place(name: str):
    """지명 → (표시이름, lat, lon, 확실한가). 못 찾으면 None.

    ⚠️ **확실하지 않으면 그렇다고 돌려준다.** 부르는 쪽이 응답에 실어
       사용자가 «엉뚱한 곳이네»를 볼 수 있게 하는 게 이 불리언의 용도다.
    """
    key = normalize_place(name)
    if not key:
        return None
    if key in _CITIES:
        lat, lon = _CITIES[key]
        return (key, lat, lon, True)

    # 표에 없다 — 지오코딩. 한글은 거의 실패하므로 아는 영문이 있으면 그걸 쓴다.
    for q in (_ROMAN.get(key), key):
        if not q:
            continue
        try:
            data = _get_json(
                "https://geocoding-api.open-meteo.com/v1/search?name="
                + urllib.parse.quote(q)
                + "&count=1&language=ko&format=json"
            )
        except Exception:
            continue
        hits = data.get("results") or []
        if hits:
            h = hits[0]
            label = h.get("name") or key
            region = h.get("admin1") or ""
            shown = f"{label}({region})" if region and region not in label else label
            # 지오코딩 결과는 **확실하지 않다** — 위 주석의 '부산 → Pusan' 사고
            return (shown, h["latitude"], h["longitude"], False)
    return None


def _day_line(daily: dict, i: int, label: str) -> str:
    code = daily["weather_code"][i]
    hi = daily["temperature_2m_max"][i]
    lo = daily["temperature_2m_min"][i]
    rain = daily["precipitation_sum"][i]
    pop = (daily.get("precipitation_probability_max") or [None] * (i + 1))[i]
    sky = _WMO.get(code, f"코드 {code}")
    line = f"{label}: {sky}, {lo:.0f}~{hi:.0f}도"
    if rain and rain > 0:
        line += f", 강수 {rain:.1f}mm"
    elif pop is not None:
        line += f", 강수확률 {pop}%"
    return line


@tool
def get_weather(location: str = "서울", days: str = "today") -> str:
    """
    실제 기상 관측·예보 자료로 날씨를 알려줍니다. 브라우저를 열지 않고,
    검색 결과 링크가 아니라 **기온·하늘상태·강수 같은 실제 수치**를 반환합니다.

    "날씨 알려줘", "오늘 날씨 어때", "어제보다 추워?", "내일 비 와?" 처럼
    날씨를 물으면 **항상 이 도구를 사용하세요.** fetch_web_info나 web_search로
    날씨를 찾으면 링크만 나와서 답할 수 없습니다.

    location: 지역 이름 (예: 서울, 부산, 제주). 사용자가 말하지 않으면 서울.
    days: "today"(오늘+지금) · "yesterday"(어제) · "tomorrow"(내일) ·
          "all"(어제·오늘·내일 전부). 사용자가 어제/내일을 같이 물으면 "all".
    """
    place = resolve_place(location or "서울")
    if not place:
        return (f"✗ '{location}'이(가) 어디인지 몰라서 날씨를 가져오지 못했습니다. "
                f"시·군 이름으로 다시 말해 주세요 (예: 서울, 부산, 제주).")
    shown, lat, lon, exact = place

    try:
        data = _get_json(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,precipitation_probability_max"
            "&past_days=1&forecast_days=2&timezone=Asia%2FSeoul"
        )
    except WeatherTimeout:
        # 🚨 원인을 **단정하지 않는다.** 위 WeatherTimeout 주석 참조.
        return ("✗ 날씨 자료를 받아오는 데 시간이 너무 걸려서 가져오지 못했습니다. "
                "잠시 뒤에 다시 물어봐 주세요. "
                "(인터넷이 느리거나 날씨 서버가 늦는 것이고, 어느 쪽인지는 확실하지 않습니다)")
    except WeatherOffline:
        return ("✗ 날씨 서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.")
    except Exception as e:
        return f"✗ 날씨 자료를 가져오지 못했습니다 ({type(e).__name__})."

    try:
        cur = data["current"]
        daily = data["daily"]
        dates = daily["time"]
    except (KeyError, TypeError):
        return "✗ 날씨 자료의 형식이 예상과 달라 읽지 못했습니다."

    # past_days=1 이므로 dates = [어제, 오늘, 내일]. 날짜로 확인한다 —
    # ⚠️ 순서를 가정하고 인덱스를 박으면 API가 바뀔 때 **조용히 어제를 오늘이라고 말한다.**
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        i_today = dates.index(today)
    except ValueError:
        i_today = 1 if len(dates) > 1 else 0
    i_yest = i_today - 1
    i_tmrw = i_today + 1

    want = (days or "today").strip().lower()
    lines = []

    if want in ("yesterday", "all") and i_yest >= 0:
        lines.append(_day_line(daily, i_yest, "어제"))

    if want in ("today", "all", "tomorrow"):
        if want != "tomorrow":
            sky = _WMO.get(cur.get("weather_code"), "")
            now = (f"지금: {sky} {cur['temperature_2m']:.0f}도"
                   f"(체감 {cur['apparent_temperature']:.0f}도), "
                   f"습도 {cur['relative_humidity_2m']}%, "
                   f"바람 {cur['wind_speed_10m']:.0f}m/s")
            lines.append(now)
            lines.append(_day_line(daily, i_today, "오늘"))

    if want in ("tomorrow", "all") and i_tmrw < len(dates):
        lines.append(_day_line(daily, i_tmrw, "내일"))

    if not lines:
        lines.append(_day_line(daily, i_today, "오늘"))

    head = f"✓ {shown} 날씨"
    if not exact:
        # 🚨 지오코딩이 해석한 곳이다. 틀렸을 수 있다는 걸 **사용자가 보게 한다.**
        head += " (지명을 검색해 찾은 위치라 다른 곳일 수 있어요)"
    body = "\n".join(lines)
    return f"{head}\n{body}\n(출처: open-meteo.com 관측·예보 자료)"
