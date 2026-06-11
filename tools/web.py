"""
웹 도구
URL 열기 / 검색 / 유튜브 / 지도
Playwright 사용 (Selenium 대체)
"""

import subprocess
import os
from langchain_core.tools import tool


def _open_with_browser(url: str) -> str:
    """기본 브라우저로 URL 열기. Playwright 없어도 동작하는 fallback."""
    try:
        os.startfile(url)
        return url
    except Exception:
        try:
            subprocess.Popen(["start", url], shell=True)
            return url
        except Exception as e:
            raise RuntimeError(f"URL 열기 실패: {e}")


async def _open_with_playwright(url: str) -> str:
    """Playwright로 URL 열기 (세밀한 제어가 필요할 때)."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        # 브라우저를 닫지 않음 — 사용자가 계속 사용할 수 있도록
        return url


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
        return f"✓ {url} 을(를) 열었습니다."
    except Exception as e:
        return f"✗ URL 열기 실패: {e}"


@tool
def web_search(query: str, engine: str = "google") -> str:
    """
    웹 검색을 실행합니다.
    query: 검색어
    engine: 검색 엔진 (google, naver, bing) — 기본값 google
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
        return f"✗ 검색 실패: {e}"


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
        return f"✗ 유튜브 검색 실패: {e}"


@tool
def map_search(destination: str, origin: str = "") -> str:
    """
    지도에서 장소를 검색하거나 경로를 찾습니다.
    destination: 목적지 (예: 강남역, 서울시청)
    origin: 출발지 (경로 검색 시, 비워두면 장소 검색만)
    """
    import urllib.parse

    if origin:
        # 경로 검색: 카카오맵 경로 검색
        encoded_dest = urllib.parse.quote(destination)
        encoded_orig = urllib.parse.quote(origin)
        url = f"https://map.kakao.com/?sName={encoded_orig}&eName={encoded_dest}"
        label = f"'{origin}' → '{destination}' 경로"
    else:
        # 장소 검색: 카카오맵
        encoded = urllib.parse.quote(destination)
        url = f"https://map.kakao.com/?q={encoded}"
        label = f"'{destination}'"

    try:
        _open_with_browser(url)
        return f"✓ {label} 지도를 열었습니다."
    except Exception as e:
        return f"✗ 지도 검색 실패: {e}"
