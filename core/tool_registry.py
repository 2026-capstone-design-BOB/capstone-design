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
    )
    from tools.calendar import (
        create_calendar_event,
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
    ]

    # 파일 삭제(위험 동작): HITL 승인이 있는 그래프 엔진에서만 노출한다.
    # → 구 엔진(USE_GRAPH=false)에서는 삭제 도구 자체가 없어 "확인 없는 삭제"가 불가능.
    from config.settings import get_settings
    if getattr(get_settings(), "use_graph", False):
        tools += [delete_file, delete_folder]

    return tools
