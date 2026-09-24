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
        force_close_app,
        maximize_window,
        minimize_window,
        show_desktop,
        switch_window,
        split_screen,
        minimize_others,
    )
    from tools.web import (
        open_url,
        web_search,
        youtube_search,
        map_search,
        fetch_web_info,
        crawl_page,
    )
    from tools.weather import (
        get_weather,
    )
    from tools.filesystem import (
        create_file,
        create_folder,
        find_file,
        list_directory,
        open_recent_file,
        open_file,
        write_excel,
        overwrite_file,
        delete_file,
        delete_folder,
        copy_file,
        move_file,
        rename_file,
    )
    from tools.system import (
        volume_up,
        volume_down,
        set_volume,
        get_volume,
        mute,
        unmute,
        brightness_up,
        brightness_down,
        set_brightness,
        get_brightness,
        take_screenshot,
        get_battery_status,
        get_current_time,
        get_running_apps,
        notifications_off,
        notifications_on,
        get_notifications_status,
        keep_awake,
        allow_sleep,
    )
    from tools.input_control import (
        type_text,
        press_key,
        get_clipboard_text,
        click_ui_element,
        scan_sensitive,
    )
    from tools.calendar import (
        create_calendar_event,
        list_calendar_events,
    )
    from tools.gmail import (
        list_emails,
        read_email,
        watch_inbox,
    )
    from tools.background import (
        remind_me,
        list_reminders,
        cancel_reminder,
        do_in_background,
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
        # 🔑 **여는 것과 «가는 것»은 다르다.** 이미 켜져 있는 창으로 옮기는 것이라
        #   꺼져 있으면 열지 않고 물어본다 — 안 그러면 사용자가 다른 창을 보고
        #   있다고 착각한 채 다음 말을 한다.
        switch_window,
        # 🎯 **창을 둘 띄워 놓고 사는 사람의 기본 동작.** Windows 가 이미 하는 일
        #   (Win+←/→ · Win+Home)에 «그 창을 앞으로 가져와 확인한 뒤 누르기»를 이었다.
        #   🚨 좌표를 쓰지 않는다 — 작업 표시줄·DPI·다중 모니터를 떠안지 않으려고.
        split_screen,
        minimize_others,
        # 웹
        open_url,
        web_search,
        youtube_search,
        map_search,
        fetch_web_info,
        crawl_page,
        # 날씨 — 검색이 아니라 실제 기상 자료로 답한다 (BL-34)
        get_weather,
        # 파일시스템
        create_file,
        create_folder,
        find_file,
        list_directory,
        open_recent_file,
        open_file,
        write_excel,
        # 🔑 **복사는 되돌릴 수 있어서 승인이 없다.** 원본이 그대로 남으므로
        #   최악이 «엉뚱한 사본 하나»다. 옮기기·이름변경은 아래 승인 묶음에 있다
        #   — 가른 기준은 «사용자가 되돌릴 수 있나» 한 줄이다.
        copy_file,
        # 시스템
        volume_up,
        volume_down,
        set_volume,
        # 🔑 **방향이 있는 도구 둘.** 토글 하나였을 때는 *"소리 켜 줘"* 가
        #   이미 켜져 있으면 **소리를 껐다**(2026-09-23 실기).
        mute,
        unmute,
        brightness_up,
        brightness_down,
        set_brightness,
        # 🔑 **읽는 도구** — «묻기만 했는데 값이 바뀌던» 결함의 나머지 절반이다
        #   (BL-60). 캐시 쪽 게이트만 달면 «안 바뀌지만 여전히 답을 못 하는» 상태가
        #   되고, 이것만 더하면 캐시가 먼저 채 가서 여기까지 오지도 못한다. **한 쌍이다.**
        get_volume,
        get_brightness,
        take_screenshot,
        get_battery_status,
        get_current_time,
        get_running_apps,
        # 업무 환경 — 회의·화면 공유 전에 쓰는 것들.
        # 🔑 **방향을 가진 둘 + 읽는 하나.** 토글 하나로 두면 이미 꺼져 있을 때
        #   *"알림 꺼줘"* 가 알림을 켠다(`mute_toggle` 이 그렇게 깨졌다).
        notifications_off,
        notifications_on,
        get_notifications_status,
        keep_awake,
        allow_sleep,
        # 키보드/클립보드 입력
        type_text,
        press_key,
        get_clipboard_text,
        # 보내기 전 개인정보 검사 — 마스킹 패턴을 «가리기»가 아니라 «찾기»로
        # 돌려 쓴다. 새 표면이 아니라서 위험이 늘지 않는다.
        scan_sensitive,
        # 캘린더 — 🔑 **읽기·쓰기 한 쌍.** 읽기가 없으면 *"오늘 일정 뭐야"* 가
        # LLM 잡담으로 끝나고, 그러다 없는 일정을 지어낸다(BL-60·61 과 같은 모양).
        create_calendar_event,
        list_calendar_events,
        # 📧 메일 — **읽기만 한다.** 권한(`gmail.readonly`)과 도구 목록이 **둘 다**
        #   그 경계를 진다. 🚨 `gmail_send` 는 **아예 만들지 않았다** — 권한만 조이면
        #   나중에 범위를 넓히는 순간 도구가 생기고, 도구만 없애면 권한이 남는다.
        list_emails,
        read_email,
        # 📬 **화면 밖 사건**을 보는 유일한 길(페르소나 §3-J). `watch_screen` 은
        #   화면에 보이는 것만 볼 수 있어서 *"메일 오면 알려줘"* 를 못 메웠다.
        #   엔진은 그래프 **밖**이다 → core/worker.py
        watch_inbox,
        # ⏳ 백그라운드 약속 — *"30분 뒤에"* · *"끝나면 알려줘"*.
        # 🚨 **그래프 밖이다.** 도구는 약속을 얹고 sync 인 채로 즉시 끝난다.
        #   그래서 승인 노드를 한 줄도 안 건드린다(절대규칙 1).
        #   → docs/design/M9_백그라운드_작업자.md
        remind_me,
        list_reminders,
        cancel_reminder,
        do_in_background,
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

    # 강제 종료(위험 동작 — 저장하지 않은 내용이 사라진다). 승인 대상이다.
    # 🔑 `close_app` 은 `WM_CLOSE` 로 곱게 닫으므로 승인이 없다. 둘을 **이름이 다른
    #   도구**로 나눈 것이 이 설계의 핵심이다 — `force=True` 인자였다면 LLM 이
    #   언젠가 지어낸다(절대규칙 9와 같은 모양).
    #   → docs/design/G-05-19_승인의_경계.md §4-2
    tools += [force_close_app]

    # 덮어쓰기(위험 동작 — 옛 내용이 사라진다). 승인 대상이다.
    # 🔑 `create_file` 은 이미 있는 이름이면 **안 쓰고 물어본다.** 둘을 이름이 다른
    #   도구로 나눈 것이 `close_app`/`force_close_app` 과 같은 규칙이다.
    #   → docs/design/G-05-19_승인의_경계.md §4-1
    tools += [overwrite_file]

    # 옮기기·이름변경(위험 동작 — 어디로 갔는지·옛 이름을 모르면 못 되돌린다).
    # 🚨 **둘 다 재귀 탐색을 안 한다.** 승인 질문은 이름만 보여주므로, 하위 폴더에서
    #   우연히 이름이 맞은 다른 파일이 잡히면 사용자가 그것을 알 수 없다.
    #   `_locate_for_open` 이 삭제에 대해 못 박아 둔 비대칭과 같은 자리다.
    tools += [move_file, rename_file]

    return tools


# ── ⏳ 백그라운드 전용 도구 묶음 (2026-09-25) ──────────────────────
#
# *"끝나면 알려줘"* 로 맡긴 일이 **뒤에서 도는 동안** 쓸 수 있는 것들이다.
# → docs/design/M9_백그라운드_작업자.md
#
# ## 🚨 가른 기준은 «위험한가»가 아니라 **«사용자의 손과 눈을 뺏는가»** 다
#
# 맡긴 일이 도는 동안 사용자는 **다른 창에서 자기 일을 하고 있다.** 그런데
# `type_text` 는 **지금 포커스된 창**에 글자를 넣고, `open_app` 은 창을 앞으로
# 꺼내고, `set_volume` 은 듣고 있던 소리를 바꾼다. 하나도 «위험 도구»가 아닌데
# 전부 **사용자가 하던 일을 망친다.** 그래서 목록을 «되돌릴 수 있나»가 아니라
# **«내 손이 지금 거기 있나»** 로 갈랐다.
#
# ## 🔒 그리고 승인 대상은 **여기 있을 수가 없다**
#
# 뒤에서 도는 턴이 `interrupt` 를 걸면 물어볼 사람이 그 자리에 없다 —
# **영영 안 끝난다.** 도구를 안 주는 것이 «안 부르기로 약속»보다 강하다
# (`gmail_send` 를 아예 안 만든 것과 같은 규칙).
#
# ## 🔑 **허용목록이다 — 새 도구는 기본으로 «안 준다»**
#
# 금지목록이면 다음에 누가 도구를 더할 때 **가만히 있어도 백그라운드에 들어간다.**
# 여기 이름을 적지 않으면 안 들어간다. 빠뜨리는 쪽이 안전한 방향이다.
BACKGROUND_TOOL_NAMES = {
    # 찾아보기
    "web_search", "fetch_web_info", "crawl_page", "map_search", "youtube_search",
    "get_weather",
    # 읽기 — 화면도 입력도 안 건드린다
    "find_file", "list_directory", "get_current_time",
    "list_calendar_events", "list_emails", "read_email",
    # 남기기 — 🔑 **덮어쓰지 않는 것만.** `create_file` 은 이름이 겹치면 안 쓰고
    #   말한다(G-05). `overwrite_file`·`move_file`·`rename_file` 은 승인 대상이라
    #   애초에 여기 올 수 없다.
    "create_file", "create_folder", "write_excel",
}


def get_background_tools() -> List[BaseTool]:
    """백그라운드 작업자가 쓸 도구들. `BACKGROUND_TOOL_NAMES` 에 적힌 것만.

    🚨 **이름이 안 맞으면 조용히 빠진다.** 그래서 `tests/test_worker.py` 가
      «적어 둔 이름이 전부 실재하는가»를 따로 지킨다 — 오타 하나가
      «도구가 있는 줄 알고 맡겼는데 못 하는» 상태를 만든다.
    """
    return [t for t in get_all_tools()
            if getattr(t, "name", None) in BACKGROUND_TOOL_NAMES]
