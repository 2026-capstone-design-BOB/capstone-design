# -*- coding: utf-8 -*-
"""도구 평가 문장 — **도구 하나에 문장 하나 이상.** 측정기 둘이 같이 쓰는 표.

    from tool_eval_cases import ALL_CASES, MULTI_CASES, NEW_2026_09

## 왜 이 파일이 따로 있나 — 같은 빚을 **세 번** 졌다

| 언제 | 도구 | 평가 문장 |
|---|---|---|
| 2026-09-24 (1) | 47 → 58 | 안 늘림 (📏 *"다음엔 평가 문장부터"*) |
| 2026-09-24 (2) | 58 → 62 | 안 늘림 (📏 같은 말을 또 적음) |
| 2026-09-25 | 62 → 67 | 안 늘림 ([BL-71](../docs/BACKLOG.md)) |

세 번 다 «다음엔 늘린다»라고 **적어서** 막으려 했고 세 번 다 안 됐다.
🔑 이 저장소가 이미 아는 교훈이 그것이다 — **프롬프트(와 메모)는 확률을 올릴 뿐이고
보장하는 건 구조다**([CLAUDE.md](../CLAUDE.md)). 그래서 이번엔 적는 대신 **자를** 뒀다:

- 표는 여기 **한 곳**에 있고,
- `tests/test_tool_eval_cases.py` 가 **`get_all_tools()` 와 대조한다.**
  문장 없는 도구를 등록하면 **테스트가 깨진다.**

`test_worker.py` [21]이 문서의 도구 개수에 대해 한 것과 같은 방식이다.

## 🚨 `expect` 는 **내가 붙인 라벨이다**

«정답»이 아니라 «내가 이게 맞다고 본 것»이다. 셋이 똑같이 틀릴 수도 있으므로
[멀티 API 표](../docs/research/2026-09_멀티API.md)에서는 **보조 지표**로만 쓴다.
여기를 주 지표로 쓰는 쪽([`eval_tool_selection.py`](eval_tool_selection.py))은
그 한계를 **보고서 머리에 매번 찍는다.**

## 🚨 «빈 문자열»도 답이다

`expect=""` 는 **아무 도구도 부르지 않는 것이 맞다**는 뜻이다. 잡담에 도구를
부르는 것은 «안 했는데 했다고 말하기»의 입구라 이 저장소가 반복해서 데인 자리다
(BL-12 · BL-19 · BL-61). 그래서 «안 부르기»도 채점한다.

## 어디서 왔나 — 대부분 **페르소나 §3 의 발화**다

새 도구 20개의 문장은 [페르소나 §3](../docs/planning/페르소나_직장인.md) 표의
«발화 예» 칸에서 가져왔다. 그 도구들이 **애초에 그 칸을 메우려고** 만들어졌으므로
«그 발화가 그 도구를 부르나»가 정확히 물어야 할 질문이다.
🚨 다만 그 칸도 사람이 적은 것이라 **실사용 로그가 아니다.** 실사용 발화로 재는
자는 따로 있다(`scripts/eval_tool_routing.py` — 로그에서 뽑은 발화를 쓴다).
"""
from collections import namedtuple

#: text  — 사용자가 말할 법한 한 마디
#: expect— 이게 불려야 한다고 내가 본 도구 이름 (""=아무것도 안 부르는 게 맞다)
#: group — 보고서에서 묶는 칸
#: multi — 🔒 멀티 API 동등성 표(2-3)의 **얼어 있는 20문장**인가
Case = namedtuple("Case", "text expect group multi")


# ── 🔒 멀티 API 20문장 (2026-09-23 고정 · 순서를 바꾸지 말 것) ──────
#
# 🚨 **순서가 계약이다.** `docs/research/2026-09_멀티API.json` 이 결과를 **인덱스로**
#   맞춰 놓는다(`results[p]["rows"][i]` ↔ `CASES[i]`). 중간에 끼워 넣거나 빼면
#   **옛 열이 통째로 어긋난다** — 키가 나중에 생길 provider 를 위해 남겨 둔 열이다.
#   `tests/test_tool_eval_cases.py` ④가 이 스무 줄을 글자까지 지킨다.
#
# 갈래 구분과 «어려운 것을 일부러 남겨 뒀다»는 2026-09-23 의 원문 그대로다:
#   ③ «강제로»(캐시가 삼켰던 것) · ⑩ 소리 나는 대로 부른 파일명(D-01a) ·
#   ⑭ target 없는 입력(BL-12).
_MULTI = [
    # ① 앱
    Case("메모장 켜 줘",                       "open_app",         "앱",      True),
    Case("그림판 꺼 줘",                       "close_app",        "앱",      True),
    Case("그림판 강제로 꺼 줘",                "force_close_app",  "앱",      True),
    Case("지금 켜져 있는 앱 목록 알려줘",      "get_running_apps", "앱",      True),
    # ② 시스템 · 창
    Case("볼륨 30으로 맞춰줘",                 "set_volume",       "시스템",  True),
    Case("소리 꺼줘",                          "mute",             "시스템",  True),
    Case("화면 밝기 좀 올려줘",                "brightness_up",    "시스템",  True),
    Case("메모장 최대화해줘",                  "maximize_window",  "창",      True),
    # ③ 파일 — 승인이 필요한 것을 일부러 넣었다(실행은 안 한다)
    Case("바탕화면에 회의록.txt 만들어줘",     "create_file",      "파일",    True),
    Case("에이점 티엑스티 지워 줘",            "delete_file",      "파일",    True),
    Case("보고서 어디 있는지 찾아줘",          "find_file",        "파일",    True),
    Case("다운로드 폴더에 뭐 있는지 알려줘",   "list_directory",   "파일",    True),
    # ④ 화면 · 입력
    Case("지금 화면에 뭐 보여",                "describe_screen",  "화면",    True),
    Case("메모장에 안녕하세요 라고 써 줘",     "type_text",        "화면",    True),
    Case("메모장에 오류 뜨면 알려줘",          "watch_screen",     "화면",    True),
    # ⑤ 온라인
    Case("유튜브에서 아이유 노래 틀어줘",      "youtube_search",   "온라인",  True),
    Case("파이썬 리스트 정렬하는 법 검색해줘", "web_search",       "온라인",  True),
    Case("오늘 날씨 어때",                     "get_weather",      "온라인",  True),
    # ⑥ 로컬 정보 · 도구 없음
    Case("지금 몇 시야",                       "get_current_time", "정보",    True),
    Case("오늘 저녁 뭐 먹지",                  "",                 "🚫 잡담", True),
]


# ── 나머지 도구 (2026-09-28 신설 · BL-71) ──────────────────────────
#
# 🔑 **한 도구에 한 문장만 넣었다.** 많이 넣을수록 좋아 보이지만, 그러면 «어느 칸이
#   비었나»가 표 안에서 흐려진다. 자는 **덮었나/못 덮었나**를 먼저 답해야 한다.
#   문장을 더 넣는 일은 «어느 도구가 잘 안 불린다»가 나온 뒤에 그 도구에만 한다.
_ADDED = [
    # ── 창 · 멀티태스킹 (🆕 뒤 셋이 2026-09-24 도구)
    Case("메모장 창 내려 줘",                          "minimize_window", "창", False),
    Case("창 다 내리고 바탕화면 보여줘",               "show_desktop",    "창", False),
    Case("엑셀 창으로 가줘",                           "switch_window",   "창", False),
    Case("엑셀이랑 크롬 반씩 같이 보여줘",             "split_screen",    "창", False),
    Case("메모장만 남기고 나머지 창 다 내려줘",        "minimize_others", "창", False),

    # ── 웹 — 🚨 «연다»와 «읽어 온다»가 갈리는 자리다(브라우저를 띄우나 텍스트를 주나)
    Case("https://www.naver.com 열어줘",               "open_url",       "온라인", False),
    Case("강남역에서 서울역까지 가는 길 찾아줘",       "map_search",     "온라인", False),
    Case("전기차 보조금 얼마인지 찾아서 알려줘",       "fetch_web_info", "온라인", False),
    Case("https://example.com 이 페이지 내용 읽어줘",  "crawl_page",     "온라인", False),

    # ── 파일 (🆕 copy · move · rename 이 2026-09-24 도구)
    Case("바탕화면에 발표자료 폴더 만들어줘",          "create_folder",    "파일", False),
    Case("최근에 열었던 파일 목록 보여줘",             "open_recent_file", "파일", False),
    Case("바탕화면에 있는 회의록.txt 열어줘",          "open_file",        "파일", False),
    Case("1월 10만원 2월 12만원 지출 내역을 엑셀로 저장해줘",
                                                       "write_excel",      "파일", False),
    Case("회의록.txt 를 백업 폴더에 복사해둬",         "copy_file",        "파일", False),
    Case("회의록.txt 를 문서 폴더로 옮겨줘",           "move_file",        "파일", False),
    Case("회의록.txt 이름을 주간보고.txt 로 바꿔줘",   "rename_file",      "파일", False),
    Case("회의록.txt 에 회의 취소라고 덮어써 줘",      "overwrite_file",   "파일", False),
    Case("바탕화면 임시 폴더 지워줘",                  "delete_folder",    "파일", False),

    # ── 시스템 — 🔑 **방향과 읽기.** «켜 줘»가 소리를 껐던 2026-09-23 실기가 여기 있다
    Case("소리 좀 키워줘",                             "volume_up",          "시스템", False),
    Case("소리 좀 줄여줘",                             "volume_down",        "시스템", False),
    Case("소리 다시 켜줘",                             "unmute",             "시스템", False),
    Case("화면 밝기 좀 낮춰줘",                        "brightness_down",    "시스템", False),
    Case("밝기 50으로 맞춰줘",                         "set_brightness",     "시스템", False),
    Case("지금 볼륨 몇이야",                           "get_volume",         "시스템", False),
    Case("지금 화면 밝기 얼마야",                      "get_brightness",     "시스템", False),
    Case("화면 캡처해줘",                              "take_screenshot",    "시스템", False),
    Case("배터리 얼마나 남았어",                       "get_battery_status", "시스템", False),

    # ── 업무 환경 (🆕 다섯 전부 2026-09-24 도구 · 페르소나 §3-H)
    Case("화면 공유할 건데 알림 꺼줘",                 "notifications_off",        "업무", False),
    Case("알림 다시 켜줘",                             "notifications_on",         "업무", False),
    Case("지금 알림 켜져 있어?",                       "get_notifications_status", "업무", False),
    Case("화면 안 꺼지게 해줘",                        "keep_awake",               "업무", False),
    Case("이제 화면 꺼져도 돼",                        "allow_sleep",              "업무", False),

    # ── 입력 · 클립보드 (🆕 scan_sensitive 가 2026-09-24 도구)
    Case("컨트롤 에스 눌러줘",                         "press_key",          "입력", False),
    Case("방금 복사한 거 뭐야",                        "get_clipboard_text", "입력", False),
    Case("보내기 전에 개인정보 있나 봐줘",             "scan_sensitive",     "입력", False),
    Case("확인 버튼 눌러줘",                           "click_ui_element",   "입력", False),

    # ── 일정 (🆕 읽기가 2026-09-24 도구 · §4-① «쓰기는 있는데 읽기가 없다»의 짝)
    Case("내일 오후 3시에 팀 회의 잡아줘",             "create_calendar_event", "일정", False),
    Case("오늘 일정 뭐 있어?",                         "list_calendar_events",  "일정", False),

    # ── 메일 (🆕 셋 다 새 도구 · 🔒 보내는 도구는 **아예 없다**)
    Case("밤새 온 메일 있어?",                         "list_emails", "메일", False),
    Case("부장님이 보낸 메일 읽어줘",                  "read_email",  "메일", False),
    Case("메일 오면 알려줘",                           "watch_inbox", "메일", False),

    # ── 약속 · 백그라운드 (🆕 넷 다 2026-09-25 도구 · 그래프 «밖»)
    Case("30분 뒤에 약 먹으라고 알려줘",               "remind_me",       "약속", False),
    Case("알려주기로 한 거 뭐 있어?",                  "list_reminders",  "약속", False),
    Case("아까 알려달라고 한 거 취소해줘",             "cancel_reminder", "약속", False),
    Case("전기차 보조금 세 군데 찾아서 정리해줘, 오래 걸려도 되니까 끝나면 알려줘",
                                                       "do_in_background", "약속", False),

    # ── 화면 이해 — 🚨 첫 줄은 [BL-64](../docs/BACKLOG.md)가 **정확히 여기서** 깨졌던 자리다
    #
    # 🔴 **이 줄은 2026-09-28 측정에서 «틀림»으로 나왔고, 일부러 안 고쳤다.**
    #   모델이 `point_at_element` 를 불렀다. 둘 다 `target` 하나만 받고, 하나는
    #   좌표를 **돌려주고** 하나는 그 자리를 **화면에 표시한다.** *"어디 있어?"* 라는
    #   발화로는 **원리상 갈리지 않는다** — 그리고 「길잡이」라는 정체성에서는
    #   표시하는 쪽이 오히려 맞는 답이다.
    #   🚨 **그래서 라벨을 바꿔 초록으로 만들지 않았다.** 바꾸면 이 자는 2026-09-24 의
    #   «고정 20문장 100%» 와 같은 것이 된다 — **표본을 할 일 목록으로 쓴 자**.
    #   이건 모델의 결함이 아니라 **도구 표면의 결함**이라 [BL-75](../docs/BACKLOG.md)로 남겼다.
    Case("블루투스 켜는 데 어디 있어?",                "find_ui_element",  "화면", False),
    Case("설정 버튼 어디 있는지 짚어줘",               "point_at_element", "화면", False),
    Case("화면 그만 봐도 돼",                          "stop_watching",    "화면", False),

    # ── 🚫 도구를 안 부르는 것이 맞는 자리 (위 ⑳과 한 쌍)
    Case("고마워 수고했어",                            "",                 "🚫 잡담", False),

    # ── 🚫 **인자가 모자라면 지어내지 말고 되물어야 하는 자리** (2026-09-28 신설)
    #
    # 🔑 **이 세 줄은 첫 측정이 만들어 준 것이다.** 처음엔 아래 문장들에 도구 라벨을
    #   붙여 뒀는데 셋 다 «틀림»으로 나왔다. 그런데 무슨 말을 했는지 보니 전부
    #   **되묻고 있었다** — *"뭘 알려드릴까요?"* · *"어떤 내용으로 덮어쓸까요?"*.
    #   🚨 **틀린 것은 모델이 아니라 내 문장이었다.** 셋 다 도구가 **required 로 받는
    #   값**을 발화가 안 담고 있었고(`remind_me.what` · `write_excel.headers/rows` ·
    #   덮어쓸 내용), 그런데도 도구를 불렀다면 그것은 **값을 지어낸 것**이다 —
    #   BL-61 이 막으려던 바로 그 행동이다.
    #
    # 그래서 문장을 둘로 갈랐다: 인자를 **담은** 문장은 위 갈래에서 도구를 재고,
    # 인자가 **빠진** 문장은 여기서 «안 부르고 되묻나»를 잰다.
    # 🚨 그러므로 **이 갈래의 100% 는 «잘한다»가 아니라 «안 지어낸다»는 뜻이다.**
    Case("이 표 엑셀로 저장해줘",                      "",        "🚫 되묻기", False),
    Case("회의록.txt 덮어써 줘",                       "",        "🚫 되묻기", False),
    Case("30분 뒤에 알려줘",                           "",        "🚫 되묻기", False),
]

#: 전체 평가셋. **모든 등록 도구가 여기 한 번 이상 나온다**(테스트가 지킨다).
ALL_CASES = _MULTI + _ADDED

#: 🔒 멀티 API 동등성 표(2-3)가 쓰는 20문장. `(text, expect, group)` 3-튜플.
MULTI_CASES = [(c.text, c.expect, c.group) for c in ALL_CASES if c.multi]

#: 2026-09-24~25 에 들어온 도구 20개 — **이번 측정이 겨냥한 것**.
#: 🚨 손으로 적었다. 출처는 `git diff cf73cca 54e1f8c -- core/tool_registry.py` 다.
#:   나중에 «새 도구»의 뜻이 바뀌면 여기 이름이 낡는다 — 그때는 지우는 것이 맞다.
#:   전체 표가 이미 **모든** 도구를 덮고 있어서, 이 목록은 «이번 빚»을 가리킬 뿐이다.
NEW_2026_09 = frozenset([
    "switch_window", "split_screen", "minimize_others",
    "copy_file", "move_file", "rename_file",
    "notifications_off", "notifications_on", "get_notifications_status",
    "keep_awake", "allow_sleep",
    "scan_sensitive",
    "list_calendar_events",
    "list_emails", "read_email", "watch_inbox",
    "remind_me", "list_reminders", "cancel_reminder", "do_in_background",
])


def covered_tools() -> set:
    """평가 문장이 하나라도 있는 도구 이름들."""
    return {c.expect for c in ALL_CASES if c.expect}
