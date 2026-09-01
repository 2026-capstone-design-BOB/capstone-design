"""
결정론적 라우터 (M1-P1.5-c)
===========================
LLM 없이 파라미터형 명령을 정규식으로 감지해 도구를 직접 호출한다.
agent.py의 `_route_deterministic`를 그래프 경로용 **독립 async 함수**로 이관.

- tool import는 각 분기 내부에서 lazy 수행 → 모듈 import 시 Windows 의존 없음.
- 반환: 결과 문자열(히트) 또는 None(미히트 → LLM으로).

※ agent.py의 원본 로직은 폴백 유지를 위해 건드리지 않음(동일 규칙 복제).
"""

from __future__ import annotations

import re
from typing import Optional

_ROUTER_YT = re.compile(
    r'유튜브(?:에서|에|로)?\s+(.+?)\s*(?:검색\s*해\s*줘|검색해|틀어\s*줘|틀어|찾아\s*줘|찾아)\s*$'
)
_ROUTER_MAP_ROUTE = re.compile(
    r'^(.+?)에서\s+(.+?)\s+(?:가는\s*길|경로)\s*(?:알려\s*줘|찾아\s*줘)?\s*$'
)
_ROUTER_MAP_SIMPLE = re.compile(
    r'^(.+?)\s+(?:지도\s*(?:찾아\s*줘|보여\s*줘|열어\s*줘|검색\s*해\s*줘|알려\s*줘)?|어디야|어디에\s*있어|어디에요)\s*$'
)
_ROUTER_FOLDER = re.compile(
    r'^(?:(바탕화면|데스크탑|다운로드|문서|사진)에\s+)?(.+?)\s+(?:폴더|디렉토리)\s+(?:만들어\s*줘|만들어|생성\s*해\s*줘|생성해)\s*$'
)
_ROUTER_VOLUME = re.compile(
    r'볼륨\s*(\d+)\s*(?:%로|%|퍼센트|으로|로)?\s*(?:설정\s*해\s*줘|설정해|맞춰\s*줘|맞춰|해\s*줘)?\s*$'
)
_ROUTER_VOL_UP = re.compile(
    r'^볼륨\s*(\d+)?\s*(?:정도만?|만큼|씩|만)?\s*(?:올려|높여|크게)\s*(?:줘|달라고|줄래|해\s*줘)?\s*$'
)
_ROUTER_VOL_DOWN = re.compile(
    r'^볼륨\s*(\d+)?\s*(?:정도만?|만큼|씩|만)?\s*(?:내려|줄여|작게)\s*(?:줘|달라고|줄래|해\s*줘)?\s*$'
)
_ROUTER_MAXIMIZE = re.compile(r'^(.+?)\s+최대화\s*(?:해\s*줘|해달라고|해|줄래)?\s*$')
_ROUTER_MINIMIZE = re.compile(r'^(.+?)\s+최소화\s*(?:해\s*줘|해달라고|해|줄래)?\s*$')


def route_deterministic(user_input: str) -> Optional[str]:
    """파라미터형 명령을 직접 라우팅. 히트 시 결과 문자열, 미히트 시 None."""
    text = (user_input or "").strip()
    if not text:
        return None

    # 1. youtube_search
    m = _ROUTER_YT.search(text)
    if m and m.group(1).strip():
        try:
            from tools.web import youtube_search
            return str(youtube_search.invoke({"query": m.group(1).strip()}))
        except Exception as e:
            print(f"[router] youtube 오류: {e}")

    # 2. map_search 경로
    m = _ROUTER_MAP_ROUTE.search(text)
    if m and m.group(1).strip() and m.group(2).strip():
        try:
            from tools.web import map_search
            return str(map_search.invoke(
                {"destination": m.group(2).strip(), "origin": m.group(1).strip()}))
        except Exception as e:
            print(f"[router] map(route) 오류: {e}")

    # 3. map_search 장소
    m = _ROUTER_MAP_SIMPLE.search(text)
    if m and len(m.group(1).strip()) > 1:
        try:
            from tools.web import map_search
            return str(map_search.invoke({"destination": m.group(1).strip()}))
        except Exception as e:
            print(f"[router] map(simple) 오류: {e}")

    # 4. create_folder
    m = _ROUTER_FOLDER.search(text)
    if m and m.group(2).strip():
        location = (m.group(1) or "바탕화면").strip()
        try:
            from tools.filesystem import create_folder
            return str(create_folder.invoke(
                {"name": m.group(2).strip(), "location": location}))
        except Exception as e:
            print(f"[router] create_folder 오류: {e}")

    # 5. set_volume
    m = _ROUTER_VOLUME.search(text)
    if m:
        level = int(m.group(1))
        if 0 <= level <= 100:
            try:
                from tools.system import set_volume
                return str(set_volume.invoke({"level": level}))
            except Exception as e:
                print(f"[router] set_volume 오류: {e}")

    # 6. volume_up
    m = _ROUTER_VOL_UP.search(text)
    if m:
        amount = int(m.group(1)) if m.group(1) else 10
        try:
            from tools.system import volume_up
            return str(volume_up.invoke({"amount": amount}))
        except Exception as e:
            print(f"[router] volume_up 오류: {e}")

    # 7. volume_down
    m = _ROUTER_VOL_DOWN.search(text)
    if m:
        amount = int(m.group(1)) if m.group(1) else 10
        try:
            from tools.system import volume_down
            return str(volume_down.invoke({"amount": amount}))
        except Exception as e:
            print(f"[router] volume_down 오류: {e}")

    # 8. maximize_window
    m = _ROUTER_MAXIMIZE.search(text)
    if m and m.group(1).strip():
        try:
            from tools.app_control import maximize_window
            return str(maximize_window.invoke({"app": m.group(1).strip()}))
        except Exception as e:
            print(f"[router] maximize 오류: {e}")

    # 9. minimize_window
    m = _ROUTER_MINIMIZE.search(text)
    if m and m.group(1).strip():
        try:
            from tools.app_control import minimize_window
            return str(minimize_window.invoke({"app": m.group(1).strip()}))
        except Exception as e:
            print(f"[router] minimize 오류: {e}")

    return None
