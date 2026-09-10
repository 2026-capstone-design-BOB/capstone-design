"""
Pluiz 오프라인 커맨드 캐시
--------------------------
자주 쓰는 명령을 LLM API 없이 직접 실행.

2단계 매칭 구조:
  Stage 1 — Intent-based:  (entity, action) 쌍 추출 → 인덱스 조회
             의미 기반이라 "실행해줘"/"열어줘"/"켜줘" 등 변형 표현에 강건.
             "계산기 켜줘"·"계산기 꺼줘"처럼 글자는 비슷하지만 의미가 다른 경우에도 정확.
  Stage 2 — SequenceMatcher 퍼지 매칭 (임계값 0.80):
             intent 추출 실패 시 fallback.

동적 학습 (P4, 정책: docs/design/M1_P4_캐시정책.md):
  LLM이 성공 실행한 **화이트리스트 도구**(LEARNABLE_TOOLS) 명령만 1회 즉시 학습한다.
  사용자 '표현'만 저장하고 **파라미터는 저장하지 않아** 오염을 원천 차단한다.
  (폴더명·검색어·set_volume 숫자 등 자유 파라미터 명령은 학습 거부)
  시드/동적은 source로 분리되어 동적만 원버튼 롤백 가능(clear_dynamic).
"""

import json
import os
import re
import asyncio
from datetime import datetime
from dataclasses import dataclass, asdict, field
from difflib import SequenceMatcher
from typing import Optional


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ⚠️ 환경변수로 덮어쓸 수 있다 (BL-11). `PLUIZ_LOG_DIR`과 같은 패턴이다.
#
# 이 파일은 **git 추적 대상**인데 테스트가 여기에 학습 결과를 써서, 테스트를 돌릴
# 때마다 작업 트리가 더러워졌다(매번 `git checkout cache/command_cache.json`).
# 더 나쁜 건 반대 방향이다 — 테스트가 **사용자의 실제 학습 내용을 읽어서**,
# 어떤 명령이 학습돼 있느냐에 따라 같은 테스트가 통과했다 실패했다 할 수 있었다.
#
#   테스트  → tests/_testenv.py 가 임시 경로로 돌린다 (자동, 손댈 것 없음)
#   라이브  → 서버가 쓰므로 **서버 쪽에** 준다:
#            PLUIZ_CACHE_FILE=/tmp/pluiz_live.json python main.py
CACHE_FILE = (os.environ.get("PLUIZ_CACHE_FILE")
              or os.path.join(_BASE_DIR, "cache", "command_cache.json"))
SIMILARITY_THRESHOLD = 0.80

# Stage 1(intent) 히트에서 **커버되지 않은 실질 어절**의 허용 상한.
# 이보다 많으면 «명령어를 스쳐 지나가는 긴 문장»으로 보고 캐시를 쓰지 않는다.
# 2026-09-09 실측으로 정했다 — 캐시 패턴 44개는 전부 0~1개, 실기 사고 문장은 5·9개.
_MAX_UNCOVERED_TOKENS = 3


# ── 한국어 조사 선택 헬퍼 ─────────────────────────────────────────

def _select_particle(word: str, jong_form: str, no_jong_form: str) -> str:
    """마지막 글자의 받침 유무에 따라 한국어 조사를 선택한다.

    한글 음절 범위(U+AC00~U+D7A3):
      (ord(char) - 0xAC00) % 28 != 0 이면 받침 있음 → jong_form
      0 이면 받침 없음                              → no_jong_form
    비한글 문자(영어 등)는 no_jong_form 반환.

    예:
      _select_particle("메모장", "을", "를") → "을"  (장: 받침 ㅇ)
      _select_particle("계산기", "을", "를") → "를"  (기: 받침 없음)
      _select_particle("크롬",   "을", "를") → "을"  (롬: 받침 ㅁ)
      _select_particle("엣지",   "을", "를") → "를"  (지: 받침 없음)
      _select_particle("VS Code","을", "를") → "를"  (비한글 → 기본형)
    """
    if not word:
        return no_jong_form
    last_char = word[-1]
    code = ord(last_char) - 0xAC00
    if 0 <= code <= 11171:               # 한글 음절 범위
        return jong_form if (code % 28 != 0) else no_jong_form
    return no_jong_form                  # 영어·숫자 등 → 기본형


# ── 데이터 구조 ───────────────────────────────────────────────────

@dataclass
class CacheEntry:
    pattern: str
    tool_calls: list
    response_template: str
    hit_count: int = 0
    is_seed: bool = False
    # P4: 동적 학습 감사/관리용 (기본값 → 기존 JSON 하위호환)
    source: str = "seed"        # "seed" | "dynamic"
    learned_at: str = ""        # 학습 시각 ISO
    last_used: str = ""         # 마지막 사용 시각 ISO


# ── P4: 동적 학습 정책 상수 ───────────────────────────────────────
# 학습 대상 화이트리스트 (파라미터 없음/고정어휘 제어 도구만).
# 자유 파라미터 도구(폴더명·검색어·set_volume 숫자·type_text 등)는 제외 → 오염 원천 차단.
LEARNABLE_TOOLS = frozenset([
    "open_app", "close_app", "maximize_window", "minimize_window", "show_desktop",
    "volume_up", "volume_down", "mute_toggle", "brightness_up", "brightness_down",
    "take_screenshot", "get_battery_status", "get_current_time", "get_running_apps",
    "open_recent_file",
])
# 이 도구들의 args 중 '자유 파라미터'로 간주해 학습을 막을 키
_FREE_PARAM_KEYS = frozenset(["query", "url", "level", "name", "content", "text",
                              "headers", "rows", "destination", "origin", "file_path",
                              "folder_path", "save_path"])
DEFAULT_MAX_DYNAMIC = 200       # 동적 학습 상한 (settings로 오버라이드)


# ── 시드 데이터 ────────────────────────────────────────────────────

SEED_DATA: list[tuple[str, list, str]] = [
    ("메모장 열어줘",      [{"name": "open_app", "args": {"app": "메모장"}}],        "✓ 메모장을 실행했습니다."),
    ("메모장 켜줘",        [{"name": "open_app", "args": {"app": "메모장"}}],        "✓ 메모장을 실행했습니다."),
    ("메모장 꺼줘",        [{"name": "close_app", "args": {"app": "메모장"}}],       "✓ 메모장을 종료했습니다."),
    ("계산기 열어줘",      [{"name": "open_app", "args": {"app": "계산기"}}],        "✓ 계산기를 실행했습니다."),
    ("계산기 켜줘",        [{"name": "open_app", "args": {"app": "계산기"}}],        "✓ 계산기를 실행했습니다."),
    ("크롬 열어줘",        [{"name": "open_app", "args": {"app": "크롬"}}],          "✓ Chrome을 실행했습니다."),
    ("크롬 켜줘",          [{"name": "open_app", "args": {"app": "크롬"}}],          "✓ Chrome을 실행했습니다."),
    ("탐색기 열어줘",      [{"name": "open_app", "args": {"app": "탐색기"}}],        "✓ 파일 탐색기를 열었습니다."),
    ("파일 탐색기 열어줘", [{"name": "open_app", "args": {"app": "파일탐색기"}}],    "✓ 파일 탐색기를 열었습니다."),
    ("바탕화면 보여줘",    [{"name": "show_desktop", "args": {}}],                   "✓ 바탕화면을 표시했습니다."),
    ("창 최대화해줘",      [{"name": "maximize_window", "args": {}}],                "✓ 창을 최대화했습니다."),
    ("창 최소화해줘",      [{"name": "minimize_window", "args": {}}],                "✓ 창을 최소화했습니다."),
    ("설정 열어줘",        [{"name": "open_app", "args": {"app": "settings"}}],      "✓ 설정을 열었습니다."),
    ("윈도우 설정 열어줘", [{"name": "open_app", "args": {"app": "settings"}}],      "✓ 설정을 열었습니다."),
    ("카카오톡 열어줘",    [{"name": "open_app", "args": {"app": "카카오톡"}}],      "✓ 카카오톡을 실행했습니다."),
    ("볼륨 올려줘",        [{"name": "volume_up", "args": {}}],                      "✓ 볼륨을 높였습니다."),
    ("소리 올려줘",        [{"name": "volume_up", "args": {}}],                      "✓ 볼륨을 높였습니다."),
    ("볼륨 내려줘",        [{"name": "volume_down", "args": {}}],                    "✓ 볼륨을 낮췄습니다."),
    ("소리 내려줘",        [{"name": "volume_down", "args": {}}],                    "✓ 볼륨을 낮췄습니다."),
    ("음소거해줘",         [{"name": "mute_toggle", "args": {}}],                    "✓ 음소거 상태를 변경했습니다."),
    ("음소거 해줘",        [{"name": "mute_toggle", "args": {}}],                    "✓ 음소거 상태를 변경했습니다."),
    ("밝기 올려줘",        [{"name": "brightness_up", "args": {}}],                  "✓ 화면 밝기를 높였습니다."),
    ("화면 밝게 해줘",     [{"name": "brightness_up", "args": {}}],                  "✓ 화면 밝기를 높였습니다."),
    ("밝기 내려줘",        [{"name": "brightness_down", "args": {}}],                "✓ 화면 밝기를 낮췄습니다."),
    ("화면 어둡게 해줘",   [{"name": "brightness_down", "args": {}}],                "✓ 화면 밝기를 낮췄습니다."),
    ("스크린샷 찍어줘",    [{"name": "take_screenshot", "args": {}}],                "✓ 스크린샷을 저장했습니다."),
    ("화면 캡처해줘",      [{"name": "take_screenshot", "args": {}}],                "✓ 스크린샷을 저장했습니다."),
    ("지금 몇 시야",       [{"name": "get_current_time", "args": {}}],               "현재 시각을 확인합니다."),
    ("배터리 얼마나 남았어",[{"name": "get_battery_status", "args": {}}],             "배터리 상태를 확인합니다."),
    ("배터리 확인해줘",    [{"name": "get_battery_status", "args": {}}],             "배터리 상태를 확인합니다."),
    ("지금 뭐 켜져 있어",  [{"name": "get_running_apps", "args": {}}],               "실행 중인 앱 목록을 확인합니다."),
    ("실행 중인 앱 알려줘",[{"name": "get_running_apps", "args": {}}],               "실행 중인 앱 목록을 확인합니다."),
    ("구글 열어줘",        [{"name": "open_url", "args": {"url": "https://www.google.com"}}],  "✓ Google을 열었습니다."),
    ("유튜브 열어줘",      [{"name": "open_url", "args": {"url": "https://www.youtube.com"}}], "✓ YouTube를 열었습니다."),
    ("네이버 열어줘",      [{"name": "open_url", "args": {"url": "https://www.naver.com"}}],   "✓ Naver를 열었습니다."),
    ("날씨 검색해줘",      [{"name": "web_search", "args": {"query": "오늘 날씨"}}],           "✓ 날씨를 검색했습니다."),
    ("최근에 열었던 파일 보여줘", [{"name": "open_recent_file", "args": {}}],         "최근 파일을 확인합니다."),
]


# ── Intent-based 매칭용 상수 ──────────────────────────────────────

# 앱 엔티티: (표면형, 정규 키, 한국어 표시명)
# 더 긴/구체적 표면형 먼저 (매칭 우선순위)
APP_ENTITIES: list[tuple[str, str, str]] = [
    ("구글크롬",      "chrome",      "크롬"),
    ("크롬",          "chrome",      "크롬"),
    ("마이크로소프트엣지", "edge",   "엣지"),
    ("엣지",          "edge",        "엣지"),
    ("메모장",        "notepad",     "메모장"),
    ("노트패드",      "notepad",     "메모장"),   # P4-4 동의어
    ("계산기",        "calculator",  "계산기"),
    ("파일 탐색기",   "explorer",    "파일 탐색기"),
    ("파일탐색기",    "explorer",    "파일 탐색기"),
    ("탐색기",        "explorer",    "파일 탐색기"),
    ("카카오톡",      "kakaotalk",   "카카오톡"),
    ("카톡",          "kakaotalk",   "카카오톡"),
    ("카카오",        "kakaotalk",   "카카오톡"),
    ("비주얼스튜디오코드", "vscode", "VS Code"),
    ("vscode",        "vscode",      "VS Code"),
    ("파이어폭스",    "firefox",     "Firefox"),
    ("파워포인트",    "powerpoint",  "PowerPoint"),
    ("엑셀",          "excel",       "Excel"),
    ("워드",          "word",        "Word"),
    ("터미널",        "terminal",    "터미널"),
    ("윈도우 설정",   "settings",    "설정"),
    ("설정",          "settings",    "설정"),
]

# 앱 키 집합 (open/close 합성에 사용)
_APP_KEYS = {key for _, key, _ in APP_ENTITIES}
# 앱 키 → 한국어 표시명 (BUG-09: 기존 dead code 제거, 루프 방식으로 통일)
_APP_DISPLAY: dict = {}
for _, _key, _display in APP_ENTITIES:
    if _key not in _APP_DISPLAY:
        _APP_DISPLAY[_key] = _display

# 시스템/웹 엔티티
SYSTEM_ENTITIES: list[tuple[str, str]] = [
    ("볼륨",          "volume"),
    ("소리",          "volume"),
    ("음소거",        "mute"),
    ("밝기",          "brightness"),
    ("바탕화면",      "desktop"),
    ("스크린샷",      "screenshot"),
    ("화면 캡처",     "screenshot"),
    ("화면 찍",       "screenshot"),   # P4-4 동의어 ("화면 찍어")
    ("배터리",        "battery"),
    ("시간",          "time"),
    ("시계",          "time"),
    ("유튜브",        "youtube"),
    ("네이버",        "naver"),
    ("구글",          "google"),
    ("지도",          "map"),
]

# 전체 엔티티 맵 (app + system, 긴 것 먼저)
ALL_ENTITIES: list[tuple[str, str]] = (
    [(s, k) for s, k, _ in APP_ENTITIES] + SYSTEM_ENTITIES
)

# 동작 유형 패턴 (우선순위 순서: 더 구체적인 것 먼저)
ACTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("volume_up",        ["볼륨 올", "소리 올", "볼륨 높", "소리 높", "볼륨 크게", "소리 크게",
                          "볼륨 키", "소리 키", "키워", "키우"]),                     # P4-4
    ("volume_down",      ["볼륨 내", "소리 내", "볼륨 낮", "소리 낮", "볼륨 작게", "소리 작게",
                          "볼륨 줄", "소리 줄", "줄여", "줄이"]),                     # P4-4
    ("mute",             ["음소거"]),
    ("brightness_up",    ["밝기 올", "밝기 높", "화면 밝게", "밝게 해", "밝혀줘"]),
    ("brightness_down",  ["밝기 내", "밝기 낮", "화면 어둡", "어둡게 해"]),
    ("screenshot",       ["스크린샷", "화면 캡처", "캡처해줘", "찍어"]),   # P4-4 "찍어"
    ("time",             ["몇 시", "몇시", "현재 시간", "지금 시간"]),
    ("battery",          ["배터리 얼마", "배터리 확인", "배터리 남았"]),
    ("running_apps",     ["뭐 켜져", "켜져 있", "실행 중인 앱", "어떤 앱"]),
    ("show_desktop",     ["바탕화면 보여", "바탕 화면 보여"]),
    ("maximize",         ["최대화"]),
    ("minimize",         ["최소화"]),
    # close는 open보다 먼저 (꺼줘/종료가 열어줘 포함 시 오인식 방지)
    ("close",            ["꺼줘", "닫아줘", "종료해줘", "닫줘", "꺼 줘", "종료 해줘",
                          "꺼", "닫아", "종료"]),
    ("open",             ["열어줘", "켜줘", "실행해줘", "시작해줘", "띄워줘",
                          "열어 줘", "켜 줘", "실행 해줘", "열어", "켜", "실행", "시작",
                          "띄워", "오픈", "열기"]),                     # P4-4 동의어
    ("recent_file",      ["최근에 열었던", "최근 파일", "최근에 열"]),
]


# 명령형 어미 — **캐시가 해석하지 못한 말에 또 명령이 있는지** 판정할 때 쓴다. (BL-15)
#
# 왜 필요한가: entity+action 추출은 문장에서 **처음 걸린 것 하나씩만** 본다.
# 그래서 "메모장 열어서 회의록 써줘"는 (notepad, open)으로 히트해 메모장만 열고
# **뒷문장이 조용히 사라졌다.** 사용자는 "왜 안 적혔지?"만 겪고 로그엔 성공으로 남는다.
# (2026-09-03 실기에서 실제로 발생 — 사용자가 "회의록 써달라니까 씹었다"고 지적)
#
# 여기서 어미 목록을 늘리는 식의 땜질을 하지 않는다. **캐시가 커버한 어절을 빼고**
# 남은 말에 명령의 꼴이 있으면 캐시를 포기한다 — 어느 동사인지는 알 필요가 없다.
# 의미를 바꾸지 않는 삽입어. "스크린샷 **좀** 찍어줘"처럼 명령어와 그 동사 사이에 끼어든다.
_FILLER_TOKENS = frozenset([
    "좀", "다", "빨리", "당장", "어서", "얼른", "그냥", "지금", "제발",
    "이제", "다시", "한번", "한 번", "정말", "진짜", "빨랑",
])

# 캐시가 **표현할 수 없는** 수식어. (BL-15와 같은 뿌리)
#
# 캐시 엔트리는 도구 이름만 저장하고 **파라미터를 저장하지 않는다**(P4 오염 방지 정책).
# 그래서 파라미터를 바꾸는 말이 남아 있으면 그 명령은 캐시가 재현할 수 없다:
#   "새로 메모장 열어줘" → 캐시는 open_app(app='메모장')만 안다. **new=True를 모른다.**
#   → 기존 창을 앞으로 가져와 놓고 "새로 열었다"고 답한다.
# 2026-09-03 실기에서 사용자가 지적한 그대로다:
#   *"메모장을 새로 열라고 하면 기존 창을 앞으로 가져오는 게 아니라 새 탭을 추가하라는 건데"*
#
# ※ 어절 **완전일치**로만 본다. 부분일치면 "새로고침"이 "새로"에 걸린다.
_RESIDUAL_MODIFIERS = frozenset([
    "새로", "새로운", "새", "새창", "새탭", "또", "추가로", "하나", "더", "따로",
])

# ── BL-27: 부정·대조 토큰 ─────────────────────────────────────────
#
# 캐시는 문장에서 **처음 걸린 entity 하나**만 집는다. 그래서 대조문이 뒤집힌다:
#
#   "메모장 말고 계산기 열어줘" → (notepad, open) → **메모장이 열린다**
#
# `has_uncovered_command()`도 못 잡는다 — 남는 어절이 「말고」뿐이라 명령의 꼴이 아니고,
# 잔여 어절도 2개뿐이라 커버율 임계(3)에 걸리지 않는다.
#
# ⚠️ **이건 임베딩으로 바꿔도 안 고쳐진다.** 문장 임베딩은 부정·대조에 약하고
# 「메모장 말고 계산기」의 벡터는 「메모장 열어줘」와 가깝다. 그래서 **고치지 않고
# 피한다** — 대조 표지가 있으면 캐시를 통째로 포기하고 LLM이 문장 전체를 읽게 한다.
# 오판의 방향이 안전하다: 느려질 뿐(2.5초) 틀리지 않는다.
# → [M5 ADR §3-4](../docs/design/M5_임베딩_캐시.md)
_CONTRAST_TOKENS = frozenset(["말고", "말구", "대신", "아니라", "아니고", "빼고"])

# ── BL-27: 학습 자격 — **발화** 쪽 조건 ───────────────────────────
#
# `_is_learnable()`은 **도구**가 화이트리스트인지만 봤다. 발화가 명령의 꼴인지는
# 보지 않아서, 승인 응답·잡담·STT 오인식이 그대로 «패턴»이 됐다. 실제로 박혀 있던 것:
#
#   '그래'               → close_app   ← **승인 응답이다.** 승인 대기가 아닐 때
#                                        「그래」라고 하면 앱이 꺼진다
#   '오시가 된거야 다시'  → get_current_time  ← STT 오인식
#
# 한 번 박히면 `hit_count`만 늘며 영구화된다(BL-21과 같은 계열).
#
# ⚠️ **임계는 실측으로 정했다** (2026-09-10, ADR §6-1):
#   글자수 3 — '그래'(2)는 막고 **'음소거'(3)·'음소거해줘'(5)는 살린다.**
#   ADR 초안의 «어절 2개 이상»은 **틀렸다** — 시드 '음소거해줘'가 1어절이다.
_MIN_LEARN_CHARS = 3

_RESIDUAL_CMD_TAIL = re.compile(
    r'(줘|줄래|주라|주세요|주시겠어요|주시겠어|달라|달라니까|다오'
    r'|봐|봐라|보여|알려|해라|하렴|하자)$'
)


# ── CommandCache 클래스 ───────────────────────────────────────────

class CommandCache:
    """
    명령 캐시 관리자.

    find() 호출 순서:
    1. Intent-based (entity+action 추출 → 인덱스 조회)  ← 의미 정확도 우선
    2. SequenceMatcher 퍼지 매칭 (임계값 0.80)         ← fallback
    """

    def __init__(self):
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        self._cache: dict[str, CacheEntry] = {}
        self._intent_index: dict[tuple[str, str], CacheEntry] = {}
        # BUG-10: execute() 호출마다 get_all_tools()를 재생성하지 않도록 캐싱
        self._tools_map: dict = {}
        # P4: 동적 학습 설정(settings 오버라이드, 실패 시 기본값)
        self._max_dynamic = DEFAULT_MAX_DYNAMIC
        self._learning_enabled = True
        try:
            from config.settings import get_settings
            s = get_settings()
            self._max_dynamic = int(getattr(s, "cache_max_dynamic", DEFAULT_MAX_DYNAMIC))
            self._learning_enabled = bool(getattr(s, "cache_learning", True))
        except Exception:
            pass
        self._load()
        self._seed()
        self._build_intent_index()

    # ── 정규화 ────────────────────────────────────────────────────

    def _normalize(self, text: str) -> str:
        text = text.strip().lower()
        for old, new in [("해 줘", "해줘"), ("열 어줘", "열어줘"), (" 줘", "줘")]:
            text = text.replace(old, new)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # ── Intent 추출 ───────────────────────────────────────────────

    def _match_entity(self, text_ns: str) -> Optional[tuple[str, str]]:
        """(entity 키, 실제로 걸린 표면형) — 더 긴 표면형 우선. 둘 다 공백 제거된 값."""
        for surface, key in ALL_ENTITIES:
            s = surface.replace(" ", "")
            if s in text_ns:
                return (key, s)
        return None

    def _match_action(self, text_ns: str) -> Optional[tuple[str, str]]:
        """(action 키, 실제로 걸린 트리거) — 우선순위 순서대로. 둘 다 공백 제거된 값."""
        for action_key, triggers in ACTION_PATTERNS:
            for trigger in triggers:
                t = trigger.replace(" ", "")
                if t in text_ns:
                    return (action_key, t)
        return None

    def _extract_entity(self, text: str) -> Optional[str]:
        """텍스트에서 entity 키 추출. 더 긴 표면형 우선."""
        m = self._match_entity(text.replace(" ", ""))
        return m[0] if m else None

    def _extract_action(self, text: str) -> Optional[str]:
        """텍스트에서 action 키 추출. 우선순위 순서대로 확인."""
        m = self._match_action(text.replace(" ", ""))
        return m[0] if m else None

    def has_uncovered_command(self, user_input: str) -> bool:
        """캐시가 해석한 부분 **말고 남은 말에 또 다른 명령**이 있는가. (BL-15)

        남은 말이 **또 다른 명령**이거나(→ 뒷문장이 증발), **파라미터를 바꾸는
        수식어**이면(→ 캐시는 파라미터를 저장하지 않아 재현 불가) True.

        캐시는 문장에서 entity 하나 + action 하나만 집어내고 **나머지는 보지 않는다.**
        그래서 뒤에 붙은 명령이 조용히 사라졌다:

            "새로 메모장 열어서 거기에 회의록이라고 써줘"
              → (notepad, open) 히트 → 메모장만 열림. "회의록 써줘"는 증발.
            "새로 메모장 열어줘"
              → 같은 히트 → open_app(app='메모장'). **new=True를 모른다.**
                 기존 창을 앞으로 가져와 놓고 "새로 열었다"고 답한다.

        판정 방법: 걸린 entity 표면형과 action 트리거가 **차지한 어절**을 지우고,
        남은 어절 중 명령형 어미로 끝나는 게 있으면 True.

        - 어느 동사인지는 묻지 않는다. 동사 목록을 늘리는 땜질은 하지 않는다는 뜻이다.
          (`열어서`를 패턴에 추가하는 식이면 `띄워서`·`실행해서`에서 또 터진다)
        - 오판의 방향이 안전하다 — True로 잘못 봐도 **LLM이 문장 전체를 해석**한다.
          느려질 뿐 틀리지 않는다. 반대로 놓치면 명령이 사라진다.
        - **Stage 1(intent) 히트에만 해당한다.** 이유는 본문 주석 참조.
        """
        text = self._normalize(user_input)
        tokens = [t for t in text.split(" ") if t]
        if not tokens:
            return False
        text_ns_all = "".join(tokens)

        # ⚠️ **Stage 1(intent) 히트에만 적용한다.**
        # Stage 2는 문장 전체의 문자열 유사도(≥0.80)로 매칭하므로, 뒤에 명령이 더
        # 붙으면 점수가 알아서 떨어진다 — 커버 범위를 따질 일이 없다.
        # 이 구분을 빼면 정상 명령이 무더기로 캐시를 못 탄다. 실측 오탐 3건:
        #   "볼륨 좀 올려줘"("볼륨 올" 트리거가 '좀' 때문에 안 걸림) ·
        #   "음소거 해줘"·"스크린샷 찍어줘"(엔티티가 아예 없음)
        # → 셋 다 action이나 entity 한쪽이 없어 S2로 가던 것들이었다.
        matched_entity = self._match_entity(text_ns_all)
        matched_action = self._match_action(text_ns_all)
        if not matched_entity or not matched_action:
            return False

        # 공백 없는 문자열 ↔ 어절 인덱스 매핑
        # (트리거가 "볼륨 올"처럼 두 어절에 걸쳐 있어서 공백 제거 후 찾아야 한다)
        owner: list[int] = []
        for i, tok in enumerate(tokens):
            owner.extend([i] * len(tok))
        text_ns = text_ns_all

        # entity와 action이 **같은 낱말**인 명령이 있다("음소거", "스크린샷", "최대화").
        # 이런 건 낱말 자체가 명령이고 동사를 따로 데리고 다닌다 — "음소거 해줘",
        # "스크린샷 찍어줘". 그 동사를 잔여 명령으로 읽으면 정상 명령이 캐시를 못 탄다.
        # 그래서 이때만 **바로 뒤 어절 하나**를 같은 명령의 일부로 본다.
        # (entity ≠ action이면 이미 동사가 커버 안에 있다 — "계산기 실행해서 계산해줘"의
        #  '계산해줘'까지 삼키면 안 되므로 흡수하지 않는다)
        absorb_next = matched_entity[1] == matched_action[1]

        covered: set[int] = set()
        for matched in (matched_entity, matched_action):
            surface = matched[1]
            start = text_ns.find(surface)
            if start < 0:
                continue
            # 트리거가 걸친 어절은 통째로 커버로 본다.
            # "열어줘"에 트리거 "열어"가 걸리면 어절 전체가 커버다 — 안 그러면
            # 남은 "줘"가 명령으로 읽혀 **모든 캐시 히트가 무효화된다.**
            covered.update(owner[start:start + len(surface)])

        if absorb_next and covered:
            # 명령어와 그 동사 사이에 삽입어가 끼어들 수 있다("스크린샷 **좀** 찍어줘").
            # 삽입어를 건너뛰고 **실질 어절 하나**를 흡수한다.
            j = max(covered) + 1
            while j < len(tokens) and (len(tokens[j]) < 2 or tokens[j] in _FILLER_TOKENS):
                covered.add(j)
                j += 1
            if j < len(tokens):
                covered.add(j)

        # 🚨 **문장의 대부분이 명령과 무관하면 명령이 아니다.** (2026-09-09)
        #
        # 실기 사고: *"아니 설정 창은 애초에 실행 중이지 않았는데 뭘 가져와 너 왜
        # 나한테 뻥카 치냐"* 가 `설정 열어줘`에 매칭돼 **불평이 명령으로 실행됐다.**
        # 「설정」+「실행」이 문장 어디에든 있으면 intent가 잡히는데, 아래 어미 검사는
        # 그걸 못 걸렀다(명령형으로 끝나는 어절이 없었다).
        #
        # 어미 목록을 늘리는 땜질은 하지 않는다(위 docstring의 원칙). 대신
        # **커버율**을 본다 — 캐시는 «짧고 곧은 명령»을 위한 것이고, 명령어를
        # 스쳐 지나갈 뿐인 긴 문장은 LLM이 문장 전체를 읽어야 한다.
        #
        # 임계 3은 실측으로 정했다: **캐시 패턴 44개 중 막히는 것 0개**,
        # 위 두 사고 문장은 각각 5개·9개가 남는다. 여유가 크다.
        # ⚠️ 오판의 방향도 안전하다 — True로 잘못 봐도 **LLM이 해석**하므로
        #   느려질 뿐 틀리지 않는다.
        leftover = sum(1 for i, tok in enumerate(tokens)
                       if i not in covered and len(tok) >= 2
                       and tok not in _FILLER_TOKENS)
        if leftover >= _MAX_UNCOVERED_TOKENS:
            return True

        for i, tok in enumerate(tokens):
            if i in covered:
                continue
            # 파라미터를 바꾸는 수식어("새로"…)는 한 글자여도 본다 — 캐시가 못 담는다
            if tok in _RESIDUAL_MODIFIERS:
                return True
            if len(tok) < 2:
                continue          # 한 글자 어절("줘","좀")은 잡음이라 세지 않는다
            if _RESIDUAL_CMD_TAIL.search(tok):
                return True
        return False

    def has_contrast_marker(self, user_input: str) -> bool:
        """발화에 부정·대조 표지가 있는가. (BL-27)

        「메모장 **말고** 계산기 열어줘」처럼 대조가 있으면 캐시는 **처음 걸린 것**을
        집어 정반대를 실행한다. 있으면 캐시를 쓰지 않는다.

        어절 **완전일치** 또는 **어절의 끝**만 본다 — 붙여 쓴 「메모장말고」를 잡되,
        부분일치로 엉뚱한 낱말을 삼키지 않기 위해서다.
        """
        text = self._normalize(user_input)
        for tok in text.split(" "):
            if not tok:
                continue
            if tok in _CONTRAST_TOKENS:
                return True
            if any(tok.endswith(m) and len(tok) > len(m) for m in _CONTRAST_TOKENS):
                return True
        return False

    def _extract_intent(self, text: str) -> Optional[tuple[str, str]]:
        """(entity_key, action_key) 쌍 추출. 둘 다 있을 때만 반환."""
        entity = self._extract_entity(text)
        action = self._extract_action(text)
        if entity and action:
            return (entity, action)
        return None

    # ── Intent 인덱스 구축 ────────────────────────────────────────

    def _build_intent_index(self):
        """캐시 엔트리에서 intent 인덱스 구축 + 누락 app 조합 합성.

        시드에 없는 앱+open/close 조합도 동적으로 생성해
        "계산기 꺼줘", "크롬 종료해줘" 등 미등록 패턴을 커버.
        """
        self._intent_index = {}

        # 1. 기존 캐시 엔트리에서 인덱스 구축
        for key, entry in self._cache.items():
            intent = self._extract_intent(key)
            if intent is None:
                continue
            if intent not in self._intent_index:
                self._intent_index[intent] = entry
            elif entry.hit_count > self._intent_index[intent].hit_count:
                self._intent_index[intent] = entry

        # 2. 앱 엔티티의 open/close 합성 (시드에 없는 조합 자동 생성)
        synthesized = 0
        for app_key, display_name in _APP_DISPLAY.items():
            # open 합성
            if (app_key, "open") not in self._intent_index:
                eul_reul = _select_particle(display_name, "을", "를")
                self._intent_index[(app_key, "open")] = CacheEntry(
                    pattern=f"{display_name} 열어줘",
                    tool_calls=[{"name": "open_app", "args": {"app": display_name}}],
                    response_template=f"✓ {display_name}{eul_reul} 실행했습니다.",
                    is_seed=True,
                )
                synthesized += 1
            # close 합성
            if (app_key, "close") not in self._intent_index:
                eul_reul = _select_particle(display_name, "을", "를")
                self._intent_index[(app_key, "close")] = CacheEntry(
                    pattern=f"{display_name} 꺼줘",
                    tool_calls=[{"name": "close_app", "args": {"app": display_name}}],
                    response_template=f"✓ {display_name}{eul_reul} 종료했습니다.",
                    is_seed=True,
                )
                synthesized += 1

        print(f"[CommandCache] intent 인덱스 {len(self._intent_index)}개 "
              f"(기존 {len(self._intent_index)-synthesized}개 + 합성 {synthesized}개)")

    # ── 통합 검색 (Stage 1: Intent → Stage 2: SequenceMatcher) ───

    def find(self, user_input: str) -> Optional[tuple["CacheEntry", float]]:
        """
        2단계 매칭.

        Stage 1 (Intent-based): entity+action 추출 → 인덱스 직접 조회.
            의미 기반이므로 표현 변형과 동음이의어(켜줘/꺼줘)에 강건.
        Stage 2 (SequenceMatcher): intent 추출 실패 시 문자열 유사도 fallback.
            시스템 제어(볼륨, 밝기 등) 단독 키워드 명령에 유용.

        Returns: (CacheEntry, similarity_score) 또는 None
        """
        normalized = self._normalize(user_input)

        # Stage 0: 부정·대조 게이트 (BL-27) — **두 단계 모두에 건다.**
        #
        # Stage 1의 결함이라 Stage 2 쪽에만 걸면 안 되고, 반대로 Stage 2(장차 임베딩)도
        # 대조를 못 보므로 한쪽만 걸어도 샌다. 여기 한 곳에서 막으면 호출자가
        # 무엇이든(fast_path·테스트) 같은 판정을 받는다.
        if self.has_contrast_marker(normalized):
            print(f"[CommandCache] [BL-27] 대조 표지 → 캐시 포기, LLM으로: {normalized!r}")
            return None

        # Stage 1: Intent-based
        intent = self._extract_intent(normalized)
        if intent and intent in self._intent_index:
            matched = self._intent_index[intent]
            print(f"[CommandCache] [S1-intent] {intent} → {matched.pattern!r}")
            return matched, 0.90

        # Stage 2: 의미 유사도 fallback (학습 표현 포함 전체 캐시 대상)
        best_entry: Optional[CacheEntry] = None
        best_score = 0.0
        for key, entry in self._cache.items():
            score = self._similarity(normalized, key)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_score >= SIMILARITY_THRESHOLD and best_entry is not None:
            print(f"[CommandCache] [S2-sim] score={best_score:.2f} → {best_entry.pattern!r}")
            return best_entry, best_score

        return None

    def _similarity(self, a: str, b: str) -> float:
        """Stage-2 의미 유사도 (0~1). 교체 지점(swap point).

        현재: 경량(글자 유사도 SequenceMatcher). 오프라인·무설치.
        후속(P4-A): 이 메서드만 로컬 임베딩 코사인 유사도로 교체하면 의미매칭이 강화됨.
        (find() 등 나머지 로직은 그대로 재사용)
        """
        return SequenceMatcher(None, a, b).ratio()

    # ── 도구 직접 실행 ────────────────────────────────────────────

    def _get_tools_map(self) -> dict:
        """BUG-10: 도구 맵을 초기화 시 한 번만 빌드하고 재사용."""
        if not self._tools_map:
            from core.tool_registry import get_all_tools
            self._tools_map = {t.name: t for t in get_all_tools()}
        return self._tools_map

    async def execute(self, entry: "CacheEntry") -> str:
        """캐시 엔트리의 도구 시퀀스를 LLM 없이 직접 실행."""
        tools_map = self._get_tools_map()
        results: list[str] = []

        for call in entry.tool_calls:
            name = call.get("name", "")
            args = call.get("args", {})
            if name not in tools_map:
                print(f"[CommandCache] 알 수 없는 도구: {name}")
                continue
            try:
                result = await tools_map[name].ainvoke(args)
                results.append(str(result))
            except Exception as e:
                print(f"[CommandCache] 도구 실행 오류 ({name}): {e}")
                results.append(entry.response_template)

        return "\n".join(results) if results else entry.response_template

    def execute_sync(self, entry: "CacheEntry") -> str:
        """캐시 엔트리를 동기로 직접 실행 (그래프 sync 경로용, P2).
        도구가 원래 동기 함수라 .invoke로 호출한다."""
        tools_map = self._get_tools_map()
        results: list[str] = []
        for call in entry.tool_calls:
            name = call.get("name", "")
            args = call.get("args", {})
            if name not in tools_map:
                continue
            try:
                results.append(str(tools_map[name].invoke(args)))
            except Exception as e:
                print(f"[CommandCache] 동기 실행 오류 ({name}): {e}")
                results.append(entry.response_template)
        return "\n".join(results) if results else entry.response_template

    # ── 캐싱 ──────────────────────────────────────────────────────

    def save(self, user_input: str, tool_calls: list, response: str):
        """(구) 동적 캐싱 진입점 — P4 learn()으로 대체. 하위호환용 위임."""
        self.learn(user_input, tool_calls)

    def increment_hit(self, pattern: str):
        if pattern in self._cache:
            self._cache[pattern].hit_count += 1
            self._cache[pattern].last_used = _now_iso()
            self._persist()

    # ── P4: 안전한 동적 학습 ──────────────────────────────────────

    def _is_learnable(self, tool_calls: list) -> bool:
        """화이트리스트 단일 도구 + 자유 파라미터 없음일 때만 학습 허용(오염 차단)."""
        if not tool_calls or len(tool_calls) != 1:
            return False
        call = tool_calls[0]
        if call.get("name", "") not in LEARNABLE_TOOLS:
            return False
        for k, v in (call.get("args") or {}).items():
            if k == "app":                      # 고정어휘 앱 이름(성공 실행=유효) 허용
                continue
            if k == "amount":                   # 볼륨 기본량(10)만 허용, 숫자 지정은 거부
                if str(v) != "10":
                    return False
                continue
            return False                        # 그 외 파라미터 → 학습 거부
        return True

    def is_learnable_utterance(self, user_input: str) -> Optional[str]:
        """**발화**가 패턴이 될 자격이 있는가. 거절 사유(문자열) 또는 None(=통과). (BL-27)

        `_is_learnable()`이 «도구» 쪽을 보는 것과 짝이다. 이쪽은 «발화» 쪽을 본다.

        - **L1** — 캐시가 아는 낱말(entity **또는** action)이 **하나도 없으면** 거절.
          캐시가 한 낱말도 못 알아듣는 말은 캐시의 패턴이 될 수 없다.
          → `'그래'`·`'오시가 된거야 다시'`(STT 오인식) 차단
        - **L2** — 공백 제외 `_MIN_LEARN_CHARS`글자 미만이면 거절. → `'그래'`(2글자)
        - **L3** — 부정·대조 표지가 있으면 거절. → `'계산기 말고 메모장 열어줘'`

        ⚠️ **L1은 «entity **또는** action»이다. «둘 다»가 아니다.**
        ADR 초안은 «intent(둘 다) 추출 실패 시 거절»이었는데, 재보니 **시드 37개 중
        9개와 정상 표현 12개 중 11개**를 막았다(2026-09-10 실측, ADR §6-1).
        『창 최대화해줘』·『지금 몇 시야』에는 entity가 없다 — 낱말 자체가 명령이다.

        비용도 적어 둔다: L1은 캐시 어휘에 없는 정상 표현
        (『충전 얼마나 남았어』·『창 좀 꽉 채워줘』)도 막는다. **미스는 LLM이 2.5초에
        처리하지만 오매칭은 엉뚱한 실행이라** 정밀도를 위로 둔 것이다.
        """
        key = self._normalize(user_input)
        if len(key.replace(" ", "")) < _MIN_LEARN_CHARS:
            return f"L2:너무 짧음({len(key.replace(' ', ''))}글자)"
        if self.has_contrast_marker(key):
            return "L3:부정·대조 표지"
        if not (self._extract_entity(key) or self._extract_action(key)):
            return "L1:아는 낱말 없음"
        return None

    def learn(self, user_input: str, tool_calls: list) -> bool:
        """LLM이 성공 실행한 화이트리스트 제어명령의 '사용자 표현'을 학습한다.
        파라미터는 저장하지 않음(오염 차단). 반환: 새로 학습했으면 True."""
        if not self._learning_enabled:
            return False
        if not self._is_learnable(tool_calls):
            return False
        key = self._normalize(user_input)
        if not key or len(key) < 2:
            return False
        reason = self.is_learnable_utterance(key)      # BL-27: 발화 쪽 자격
        if reason is not None:
            print(f"[CommandCache] [BL-27] 학습 거부({reason}): {key!r}")
            return False
        now = _now_iso()
        if key in self._cache:                  # 이미 알고 있음 → 사용 기록만 갱신
            e = self._cache[key]
            e.hit_count += 1
            e.last_used = now
            self._persist()
            return False
        entry = CacheEntry(
            pattern=key, tool_calls=tool_calls,
            response_template="✓ 실행했어요.",
            hit_count=1, is_seed=False,
            source="dynamic", learned_at=now, last_used=now,
        )
        self._cache[key] = entry
        intent = self._extract_intent(key)      # 인텐트 추출되면 인덱스에도 반영
        if intent and intent not in self._intent_index:
            self._intent_index[intent] = entry
        self._evict_if_over_cap()
        self._persist()
        print(f"[CommandCache] 학습: {key!r} → {[c.get('name') for c in tool_calls]}")
        return True

    def _evict_if_over_cap(self):
        """동적 항목이 상한 초과 시 정리: hit 적고 오래 안 쓴 것부터(LRU+LFU)."""
        dyn = [(k, e) for k, e in self._cache.items() if e.source == "dynamic"]
        if len(dyn) <= self._max_dynamic:
            return
        dyn.sort(key=lambda kv: (kv[1].hit_count, kv[1].last_used or ""))
        for k, _ in dyn[: len(dyn) - self._max_dynamic]:
            del self._cache[k]

    # ── P4: 관리 (시드 보호) ──────────────────────────────────────

    def delete_entry(self, pattern: str) -> bool:
        """동적 항목 개별 삭제. 시드는 보호(거부)."""
        key = self._normalize(pattern)
        e = self._cache.get(key)
        if not e or e.is_seed:
            return False
        del self._cache[key]
        self._build_intent_index()
        self._persist()
        return True

    def prune_unlearnable_dynamic(self, dry_run: bool = False) -> list[tuple[str, str]]:
        """새 학습 자격(BL-27)을 통과 못 하는 **동적** 항목을 골라 지운다.

        `[(패턴, 거절사유), ...]`를 반환한다. `dry_run=True`면 목록만 만들고 지우지 않는다.

        **필터를 넣는다고 이미 박힌 것이 사라지지는 않는다.** 그리고
        `clear_dynamic()`은 **전부** 지운다 — 쓸 만한 것까지 날린다. 그래서 선별 제거다.
        시드는 건드리지 않는다(`source == "dynamic"`만 본다).
        """
        victims: list[tuple[str, str]] = []
        for key, entry in list(self._cache.items()):
            if entry.source != "dynamic" or entry.is_seed:
                continue
            reason = self.is_learnable_utterance(key)
            if reason is not None:
                victims.append((key, reason))
        if dry_run or not victims:
            return victims
        for key, _ in victims:
            del self._cache[key]
        self._build_intent_index()
        self._persist()
        return victims

    def clear_dynamic(self) -> int:
        """동적 학습 전체 초기화(오염 롤백 원버튼). 시드 유지. 삭제 개수 반환."""
        keys = [k for k, e in self._cache.items() if e.source == "dynamic"]
        for k in keys:
            del self._cache[k]
        self._build_intent_index()
        self._persist()
        return len(keys)

    def stats(self) -> dict:
        seed = sum(1 for e in self._cache.values() if e.is_seed)
        dyn = sum(1 for e in self._cache.values() if e.source == "dynamic")
        return {"total": len(self._cache), "seed": seed,
                "dynamic": dyn, "max_dynamic": self._max_dynamic,
                "learning_enabled": self._learning_enabled}

    def list_dynamic(self) -> list[dict]:
        return [{"pattern": e.pattern,
                 "tools": [c.get("name") for c in e.tool_calls],
                 "hit_count": e.hit_count,
                 "learned_at": e.learned_at, "last_used": e.last_used}
                for e in self._cache.values() if e.source == "dynamic"]

    def list_seeds(self) -> list[dict]:
        return [{"pattern": e.pattern,
                 "tools": [c.get("name") for c in e.tool_calls],
                 "hit_count": e.hit_count}
                for e in self._cache.values() if e.is_seed]

    def learnable_tools(self) -> list[str]:
        return sorted(LEARNABLE_TOOLS)

    # ── 영속화 ────────────────────────────────────────────────────

    def _persist(self):
        data = {k: asdict(v) for k, v in self._cache.items()}
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[CommandCache] 저장 실패: {e}")

    def _load(self):
        if not os.path.exists(CACHE_FILE):
            return
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._cache = {k: CacheEntry(**v) for k, v in data.items()}
            user_entries = sum(1 for e in self._cache.values() if not e.is_seed)
            print(f"[CommandCache] 로드 완료 — 전체 {len(self._cache)}개 "
                  f"(시드 {len(self._cache)-user_entries}개, 동적 {user_entries}개)")
        except Exception as e:
            print(f"[CommandCache] 로드 실패 (초기화): {e}")
            self._cache = {}

    def _seed(self):
        added = 0
        for pattern_text, tool_calls, response in SEED_DATA:
            key = self._normalize(pattern_text)
            if key not in self._cache:
                self._cache[key] = CacheEntry(
                    pattern=key, tool_calls=tool_calls,
                    response_template=response, hit_count=0, is_seed=True,
                )
                added += 1
        if added:
            print(f"[CommandCache] 시드 데이터 {added}개 추가")
            self._persist()

    @property
    def size(self) -> int:
        return len(self._cache)


# ── 헬퍼 ─────────────────────────────────────────────────────────

def extract_tool_calls_from_messages(messages: list) -> list[dict]:
    calls: list[dict] = []
    for msg in messages:
        tc_list = getattr(msg, "tool_calls", None)
        if not tc_list:
            continue
        for tc in tc_list:
            if isinstance(tc, dict):
                calls.append({"name": tc.get("name", ""), "args": tc.get("args", {})})
            else:
                calls.append({"name": getattr(tc, "name", ""), "args": getattr(tc, "args", {})})
    return calls


# ── 싱글턴 ───────────────────────────────────────────────────────

_cache_instance: Optional[CommandCache] = None


def get_cache() -> "CommandCache":
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CommandCache()
    return _cache_instance
