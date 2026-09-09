"""
Tool Registry
-------------
모든 도구를 한 곳에서 등록하고 LangGraph에 전달.
새 도구 추가 = tools/ 에 함수 작성 후 여기 import만 하면 됨.
"""

from langchain_core.tools import BaseTool
from typing import List


def get_all_tools() -> List[BaseTool]:
    """등록된 모든 도구 반환. LangGraph agent에 직접 전달."""
    from tools.app_control import (
        open_app,
        close_app,
        maximize_window,
        minimize_window,
        show_desktop,
    )
    from tools.web import (
        open_url,
        web_search,
        youtube_search,
        map_search,
        fetch_web_info,
        crawl_page,
    )
    from tools.filesystem import (
        create_file,
        create_folder,
        find_file,
        list_directory,
        open_recent_file,
        open_file,
        write_excel,
        delete_file,
        delete_folder,
    )
    from tools.system import (
        volume_up,
        volume_down,
        set_volume,
        mute_toggle,
        brightness_up,
        brightness_down,
        take_screenshot,
        get_battery_status,
        get_current_time,
        get_running_apps,
    )
    from tools.input_control import (
        type_text,
        press_key,
        get_clipboard_text,
        click_ui_element,
    )
    from tools.calendar import (
        create_calendar_event,
    )
    from tools.vision import (
        describe_screen,
        find_ui_element,
        point_at_element,
        watch_screen,
        stop_watching,
    )

    tools = [
        # 앱 제어
        open_app,
        close_app,
        maximize_window,
        minimize_window,
        show_desktop,
        # 웹
        open_url,
        web_search,
        youtube_search,
        map_search,
        fetch_web_info,
        crawl_page,
        # 파일시스템
        create_file,
        create_folder,
        find_file,
        list_directory,
        open_recent_file,
        open_file,
        write_excel,
        # 시스템
        volume_up,
        volume_down,
        set_volume,
        mute_toggle,
        brightness_up,
        brightness_down,
        take_screenshot,
        get_battery_status,
        get_current_time,
        get_running_apps,
        # 키보드/클립보드 입력
        type_text,
        press_key,
        get_clipboard_text,
        # 캘린더
        create_calendar_event,
        # 화면 이해 (Vision) — 화면 내용을 외부 LLM에 전송한다. tools/vision.py 주의사항 참조
        describe_screen,
        find_ui_element,
        # 포인팅(M4) — 찾은 자리를 **화면에 표시**한다. 아무것도 바꾸지 않으므로
        # 승인은 없지만, 화면 한 장이 나가는 비용은 find_ui_element와 **같다**
        # (같은 locate_ui_element를 쓴다). → docs/design/M4_포인팅_확대.md
        point_at_element,
        # 화면 감시 — 한 번이 아니라 **지켜보는 동안 반복해서** 화면이 나간다.
        # 승인 대상은 아니지만(멈추면 끝나므로 되돌릴 수 있다) 시작할 때 간격·상한·
        # 중단법을 사용자에게 고지하고, 상한에 닿으면 스스로 멈춘다.
        # → core/screen_monitor.py
        watch_screen,
        stop_watching,
    ]

    # 좌표 기반 클릭(위험 동작 — 되돌릴 수 없다). 승인 후 실행된다.
    tools += [click_ui_element]

    # 파일 삭제(위험 동작). 실행 전 반드시 사람 승인을 받는다.
    # → core/graph.py 의 DANGEROUS_TOOLS 에 등록돼 hitl 노드가 interrupt 를 건다.
    #   새 위험 도구를 추가할 땐 DANGEROUS_TOOLS 에도 반드시 추가할 것.
    tools += [delete_file, delete_folder]

    return tools
