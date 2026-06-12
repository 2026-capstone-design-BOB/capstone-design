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
    웹 검색을 실행합니다.
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
    유튜브에서 검색합니다.
    query: 검색어 (예: 아이유, BTS, 파이썬 강의)
    """
    import urllib.parse
    encoded = urllib.parse.quote(query)
    url = f"https://www.youtube.com/results?search_query={encoded}"
    try:
        _open_with_browser(url)
        return f"✓ 유튜브에서 '{query}'를 검색했습니다."
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
        url = f"https://map.kakao.com/?sName={urllib.parse.quote(origin)}&eName={urllib.parse.quote(destination)}"
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
    웹에서 정보를 검색하고 실제 내용을 텍스트로 반환합니다.
    open_url/web_search와 달리 브라우저를 열지 않고 결과 텍스트를 LLM에게 직접 전달합니다.
    파일 저장, 요약, 비교 등 검색 결과를 활용하는 작업에 사용하세요.
    예: '스타벅스 강남점 영업시간', '파이썬 최신 버전', '오늘 날씨'

    query: 검색어 (한국어 가능)
    """
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="kr-kr", max_results=5):
                title = r.get("title", "")
                body  = r.get("body", "")
                if body:
                    results.append(f"[{title}]\n{body}")
        if results:
            return f"'{query}' 검색 결과:\n\n" + "\n\n".join(results[:3])
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
