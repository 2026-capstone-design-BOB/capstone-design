"""
웹 도구
URL 열기 / 검색 / 유튜브 / 지도 / 웹 정보 가져오기
"""

import subprocess
import os
from typing import Optional

from langchain_core.tools import tool


# ── 🚨 BL-58 — 망이 필요한 도구는 **하기 전에** 망을 본다 ────────────────
#
# 오프라인에서 *"유튜브에서 아이유 노래 틀어줘"* 를 하면 **브라우저는 뜨고**
# «인터넷 없음» 오류 페이지가 보이는데, Pluiz 는 **«✓ 유튜브에서 '아이유 노래'
# 검색했어요»** 라고 답했다. 방어 셋이 한꺼번에 빗나갔기 때문이다:
#
#   · BL-46(오프라인이면 LLM 을 안 부른다)  → 라우터가 그보다 **앞**이라 안 걸린다
#   · verify_output                          → 도구가 `✓` 를 냈으니 **성공**으로 읽는다
#   · os.startfile                           → «브라우저를 띄우는 데»는 **성공**했다
#
# 🔑 그래서 이건 «오프라인 결함»이 아니라 **«말을 잘못하는 결함»** 이다.
#    Windows 음성 액세스도 같은 상황에서 빈 오류 페이지를 띄운다 — 다른 건
#    저쪽은 **아무 말도 안 해서** 거짓말이 아니라는 점뿐이다.
#
# ⚠️ **판정을 못 하면 막지 않는다.** 멀쩡한 망에 «인터넷이 끊겼어요»라고 하는 것은
#    반대 방향의 거짓말이고 더 나쁘다(`core/net.looks_offline` 의 규칙과 같다).

#: 오프라인일 때 하는 말. `✗`(MARK_FAIL)로 시작해야 `tool_result` 가 실패로 읽는다.
_OFFLINE_FAIL = "✗ 인터넷이 끊겨서 지금은 못 해요."


def _offline_block(what: str) -> Optional[str]:
    """망이 필요한 도구가 **일하기 전에** 부른다.

    Returns:
        막아야 하면 사용자에게 돌려줄 실패 문자열, 아니면 `None`.

    🔑 `offline_confirmed()` 는 **두 번 본다**(TTL 캐시 + 새 탐침). 거절은
       되돌릴 수 없어서 — «못 해요»라고 말해 버리면 사용자는 다시 말해야 한다 —
       캐시된 판정 하나로 결정하지 않는다.
    """
    try:
        from core.net import offline_confirmed
        if not offline_confirmed():
            return None
    except Exception:                                         # noqa: BLE001
        # 🚨 **부르는 것까지 감싼다.** 2026-09-18에 여기서 한 번 틀렸다 —
        #    `import` 만 감싸 놓고 «판정 실패는 온라인으로 읽는다»고 주석에 적었다.
        #    탐침이 터지면 **도구가 통째로 죽는다.** 못 잡는 실패가 아니라
        #    **막지 말아야 할 실패**다.
        return None
    return f"{_OFFLINE_FAIL} ({what})"


def _open_with_browser(url: str) -> str:
    """기본 브라우저로 URL 열기."""
    try:
        os.startfile(url)
        return url
    except Exception:
        try:
            subprocess.Popen(["start", url], shell=True)
            return url
        except Exception as e:
            raise RuntimeError(f"URL 열기 실패: {e}")


# ── 도구 정의 ─────────────────────────────────────────────────────

@tool
def open_url(url: str) -> str:
    """
    지정한 URL을 기본 브라우저로 엽니다.
    url: 전체 URL (예: https://www.youtube.com)
    """
    blocked = _offline_block("URL 열기")
    if blocked:
        return blocked
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        _open_with_browser(url)
        return f"✓ {url} 열었습니다."
    except Exception as e:
        return f"✗ URL 열기 실패: {e}"


@tool
def web_search(query: str, engine: str = "google") -> str:
    """
    브라우저를 열어 웹 검색 결과 페이지를 보여줍니다. 검색 내용을 텍스트로 반환하지 않습니다.
    사용자가 "X 검색해줘", "X 찾아줘"처럼 브라우저로 직접 검색 결과를 보고 싶을 때 사용합니다.
    ※ LLM이 내용을 읽고 답변·저장·요약해야 하면 fetch_web_info를 사용하세요.
    query: 검색어
    engine: 검색 엔진 (google, naver, bing) 기본값 google
    """
    blocked = _offline_block("웹 검색")
    if blocked:
        return blocked
    import urllib.parse
    encoded = urllib.parse.quote(query)
    urls = {
        "google": f"https://www.google.com/search?q={encoded}",
        "naver":  f"https://search.naver.com/search.naver?query={encoded}",
        "bing":   f"https://www.bing.com/search?q={encoded}",
    }
    url = urls.get(engine.lower(), urls["google"])
    try:
        _open_with_browser(url)
        return f"✓ {engine}에서 '{query}'를 검색했습니다."
    except Exception as e:
        return f"✗ 검색 실패: {e}"


@tool
def youtube_search(query: str) -> str:
    """
    유튜브(YouTube)에서 동영상을 검색하고 첫 번째 영상을 재생합니다.
    "유튜브에서 X 검색해줘", "유튜브로 X 찾아줘", "유튜브 X 틀어줘" 패턴에 사용합니다.
    일반 웹 검색(web_search)과 달리 유튜브 전용입니다. 유튜브 관련 명령은 항상 이 도구를 사용하세요.
    query: 검색어 (예: 아이유, BTS, 파이썬 강의)
    """
    blocked = _offline_block("유튜브 검색")
    if blocked:
        return blocked
    import urllib.parse, urllib.request, json

    # YouTube Data API v3로 첫 번째 영상 ID 가져오기
    try:
        from config.settings import get_settings
        api_key = get_settings().youtube_api_key
        if api_key:
            encoded = urllib.parse.quote(query)
            api_url = (
                f"https://www.googleapis.com/youtube/v3/search"
                f"?part=snippet&q={encoded}&type=video&maxResults=1&key={api_key}"
            )
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            items = data.get("items", [])
            if items:
                video_id = items[0]["id"]["videoId"]
                title = items[0]["snippet"]["title"]
                url = f"https://www.youtube.com/watch?v={video_id}"
                _open_with_browser(url)
                return f"✓ '{title}' 재생합니다."
    except Exception as e:
        print(f"[youtube_search] API 오류, 검색 페이지로 fallback: {e}")

    # fallback: 검색 결과 페이지 열기
    encoded = urllib.parse.quote(query)
    url = f"https://www.youtube.com/results?search_query={encoded}"
    try:
        _open_with_browser(url)
        return f"✓ 유튜브에서 '{query}' 검색했어요."
    except Exception as e:
        return f"✗ 유튜브 검색 실패: {e}"


@tool
def map_search(destination: str, origin: str = "") -> str:
    """
    지도에서 장소를 검색하거나 경로를 찾습니다.
    destination: 목적지 (예: 강남역, 서울시청)
    origin: 출발지 (비워두면 장소 검색만)
    """
    blocked = _offline_block("지도 검색")
    if blocked:
        return blocked
    import urllib.parse
    if origin:
        url = f"https://www.google.com/maps/dir/{urllib.parse.quote(origin)}/{urllib.parse.quote(destination)}"
        label = f"'{origin}' -> '{destination}' 경로"
    else:
        url = f"https://map.kakao.com/?q={urllib.parse.quote(destination)}"
        label = f"'{destination}'"
    try:
        _open_with_browser(url)
        return f"✓ {label} 지도를 열었습니다."
    except Exception as e:
        return f"✗ 지도 검색 실패: {e}"


def _quick_read(url: str, limit: int = 2000) -> str:
    """페이지 본문을 **빠르게만** 읽는다. 못 읽으면 빈 문자열.

    ⚠️ `crawl_page`와 일부러 다르다 — playwright 폴백이 **없다.**
       이건 `fetch_web_info` 안에서 매번 도는 곁다리라, 20초짜리 브라우저
       폴백이 붙으면 «날씨 알려줘» 한 마디가 `agent_timeout`(45초)을 먹는다.
       읽히면 덤이고 안 읽히면 검색 결과로 간다 — **실패해도 조용하다.**
    """
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        import httpx
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=6, follow_redirects=True)
        resp.raise_for_status()
        text = _extract_text_from_html(resp.text)
    except Exception as e:
        print(f"[_quick_read] 실패({url}): {e}")
        return ""
    text = text.strip()
    # 300자 미만은 JS 렌더링 껍데기다. 붙여 봐야 답이 안 나오고 토큰만 쓴다.
    if len(text) < 300:
        return ""
    return text[:limit] + ("\n...(이하 생략)" if len(text) > limit else "")


@tool
def fetch_web_info(query: str) -> str:
    """
    웹에서 정보를 검색하고 실제 내용을 텍스트로 반환합니다. 브라우저를 열지 않습니다.
    반환된 텍스트를 LLM이 직접 읽고 답변·요약·파일 저장에 활용할 수 있습니다.

    다음 상황에서 사용하세요:
    - 사용자가 "X 알려줘", "X 뭐야", "X 어때" 처럼 LLM에게 답변을 요청할 때
    - "검색해서 파일/메모장에 저장해줘" — 저장까지 필요한 경우
    - "비교해줘", "요약해줘" — 내용을 읽고 정리해야 할 때

    ※ 사용자가 "검색해줘", "찾아줘"라고만 하면 web_search로 브라우저를 여세요.
    ※ **날씨는 get_weather를 쓰세요.** 이 도구로 날씨를 찾으면 기상 사이트 링크만
      나오고 실제 기온이 안 나옵니다(2026-09-11 실측).

    query: 검색어 (한국어 가능), 예: '파이썬 최신 버전', '삼성 에어컨 가격'
    """
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        results = []
        top_url = ""
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="kr-kr", max_results=8):
                title = r.get("title", "")
                body  = r.get("body", "")
                href  = r.get("href", "")
                if body:
                    results.append(f"[{title}] ({href})\n{body}")
                    if not top_url and href:
                        top_url = href
        if results:
            # 🚨 2026-09-11 (BL-34) — 여기서 그냥 돌려주면 **링크 목록이
            #    «검색 결과»라는 이름으로 답인 척** 나간다. 날씨를 물었을 때
            #    실제로 그랬다: 반환값에 숫자가 한 개도 없었고(AccuWeather·기상청
            #    **사이트 소개문**뿐이었다) 모델은 *"링크만 나오네요"* 로 끝냈다.
            #    모델이 crawl_page를 스스로 부를 거라고 기대했지만 **안 불렀다** —
            #    설득은 확률을 올릴 뿐이고 보장하는 건 구조다(BL-19의 교훈).
            #    그래서 **여기서 한 페이지를 읽어 붙인다.**
            body = _quick_read(top_url) if top_url else ""
            head = f"✓ '{query}' 검색 결과:\n\n" + "\n\n".join(results[:5])
            if body:
                return (head + f"\n\n─── 첫 번째 결과 본문 ({top_url}) ───\n" + body
                        + "\n\n(위 본문이 실제 내용이다. 링크만 전달하지 말고 "
                          "이 내용을 근거로 답한다.)")
            # 본문을 못 읽었으면 **못 읽었다고 말한다.** 링크 목록을 답으로
            # 쓰지 않도록 읽는 쪽(LLM)에게 남은 수단을 알려 준다.
            return (head + "\n\n⚠️ 위는 검색 결과 **목록**이고 페이지 본문이 아니다. "
                    "여기에 답이 없으면 crawl_page(url)로 직접 읽거나, "
                    "모르는 것은 모른다고 말한다. **링크를 답으로 제시하지 않는다.**")
    except ImportError:
        pass
    except Exception as e:
        print(f"[fetch_web_info] DDG 오류: {e}")

    # fallback: DuckDuckGo Instant Answer API
    try:
        import urllib.request, urllib.parse, json
        url = ("https://api.duckduckgo.com/?q="
               + urllib.parse.quote(query)
               + "&format=json&no_html=1&skip_disambig=1")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        parts = []
        if data.get("Answer"):
            parts.append(data["Answer"])
        if data.get("AbstractText"):
            parts.append(data["AbstractText"])
        for topic in data.get("RelatedTopics", [])[:3]:
            if isinstance(topic, dict) and topic.get("Text"):
                parts.append(topic["Text"])
        if parts:
            return f"✓ '{query}' 검색 결과:\n\n" + "\n\n".join(parts)
    except Exception as e:
        print(f"[fetch_web_info] Instant Answer API 오류: {e}")

    return f"✗ '{query}' 검색 결과를 가져오지 못했습니다. 인터넷 연결을 확인하거나 브라우저에서 직접 검색해주세요."


def _extract_text_from_html(html: str) -> str:
    """HTML에서 본문 텍스트 추출 (공통 유틸)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "iframe", "noscript", "form"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
    return "\n".join(line for line in lines if line)


@tool
def crawl_page(url: str) -> str:
    """
    웹 페이지에 직접 접속해서 본문 텍스트를 읽어옵니다.
    fetch_web_info로 URL을 찾은 뒤, 해당 페이지의 실제 내용(가격, 스펙, 본문 등)이
    필요할 때 사용하세요. 브라우저를 열지 않고 텍스트만 반환합니다.
    정적 페이지는 빠르게(~1초), JS 렌더링 페이지는 자동으로 브라우저로 재시도합니다(~5초).
    url: 읽을 웹 페이지의 전체 URL
    """
    # ── 1단계: httpx (빠름, 정적 페이지) ────────────────────────────
    text = ""
    try:
        import httpx
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        text = _extract_text_from_html(resp.text)
        print(f"[crawl_page] httpx 성공: {len(text)}자 ({url})")
    except ImportError:
        return "✗ crawl_page 사용을 위해 httpx와 beautifulsoup4가 필요합니다."
    except Exception as e:
        print(f"[crawl_page] httpx 실패: {e} → playwright 시도")

    # ── 2단계: JS 렌더링 감지 → playwright fallback ─────────────────
    # 본문이 500자 미만이면 JS 렌더링으로 판단, playwright로 재시도
    if len(text) < 500:
        print(f"[crawl_page] 본문 부족({len(text)}자) → playwright 재시도")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                )
                page.goto(url, wait_until="networkidle", timeout=20000)
                html = page.content()
                browser.close()
            text = _extract_text_from_html(html)
            print(f"[crawl_page] playwright 성공: {len(text)}자 ({url})")
        except Exception as e:
            print(f"[crawl_page] playwright 실패: {e}")
            if not text:
                return f"✗ 페이지를 읽어오지 못했습니다 ({url}): {e}"

    if not text:
        return f"✗ '{url}' 페이지에서 내용을 추출하지 못했습니다."

    # 4000자 초과 시 앞부분만 반환
    if len(text) > 4000:
        text = text[:4000] + "\n...(이하 생략)"

    return f"[{url}] 페이지 내용:\n\n{text}"
