"""
웹 도구
URL 열기 / 검색 / 유튜브 / 지도 / 웹 정보 가져오기
"""

import subprocess
import os
from langchain_core.tools import tool


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
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        _open_with_browser(url)
        return f"✓ {url} 열었습니다."
    except Exception as e:
        return f"x URL 열기 실패: {e}"


@tool
def web_search(query: str, engine: str = "google") -> str:
    """
    브라우저를 열어 웹 검색 결과 페이지를 보여줍니다. 검색 내용을 텍스트로 반환하지 않습니다.
    사용자가 "X 검색해줘", "X 찾아줘"처럼 브라우저로 직접 검색 결과를 보고 싶을 때 사용합니다.
    ※ LLM이 내용을 읽고 답변·저장·요약해야 하면 fetch_web_info를 사용하세요.
    query: 검색어
    engine: 검색 엔진 (google, naver, bing) 기본값 google
    """
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
        return f"x 검색 실패: {e}"


@tool
def youtube_search(query: str) -> str:
    """
    유튜브(YouTube)에서 동영상을 검색하고 첫 번째 영상을 재생합니다.
    "유튜브에서 X 검색해줘", "유튜브로 X 찾아줘", "유튜브 X 틀어줘" 패턴에 사용합니다.
    일반 웹 검색(web_search)과 달리 유튜브 전용입니다. 유튜브 관련 명령은 항상 이 도구를 사용하세요.
    query: 검색어 (예: 아이유, BTS, 파이썬 강의)
    """
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
        return f"x 유튜브 검색 실패: {e}"


@tool
def map_search(destination: str, origin: str = "") -> str:
    """
    지도에서 장소를 검색하거나 경로를 찾습니다.
    destination: 목적지 (예: 강남역, 서울시청)
    origin: 출발지 (비워두면 장소 검색만)
    """
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
        return f"x 지도 검색 실패: {e}"


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

    query: 검색어 (한국어 가능), 예: '오늘 날씨', '파이썬 최신 버전', '삼성 에어컨 가격'
    """
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="kr-kr", max_results=8):
                title = r.get("title", "")
                body  = r.get("body", "")
                href  = r.get("href", "")
                if body:
                    results.append(f"[{title}] ({href})\n{body}")
        if results:
            return f"'{query}' 검색 결과:\n\n" + "\n\n".join(results[:5])
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
            return f"'{query}' 검색 결과:\n\n" + "\n\n".join(parts)
    except Exception as e:
        print(f"[fetch_web_info] Instant Answer API 오류: {e}")

    return f"'{query}' 검색 결과를 가져오지 못했습니다. 인터넷 연결을 확인하거나 브라우저에서 직접 검색해주세요."


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
