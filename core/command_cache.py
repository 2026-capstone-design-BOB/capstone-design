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
from dataclasses import dataclass, asdict, field, fields
from difflib import SequenceMatcher
from typing import Optional

from core.logger import get_logger

#: 🚨 **`print` 가 아니라 로거다** (2026-09-16 감사 G-02).
#:  캐시가 도구를 돌리다 실패하면 그 사실이 `print` 로만 나가서 **`logs/pluiz.log` 에
#:  한 줄도 안 남았다.** 실기에서 «왜 안 됐지»를 로그로 되짚을 수 없었다는 뜻이다.
_log = get_logger("CommandCache")


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
# Stage 2(퍼지) 임계. **2026-09-11 2차 실기로 0.80 → 0.83으로 올렸다.**
#
# 🚨 왜 올렸나: 사용자가 *"메모장 만들어줘"* 라고 했는데 **«메모장 창을 앞으로
#   가져왔습니다»** 가 나왔다. difflib가 `'메모장 열어줘'`와 **정확히 0.800** —
#   임계에 딱 걸려 통과했다. 「만들어」와 「열어」는 다른 뜻이다.
#
# 🔬 올려도 되는 근거(실측 17문장). 경계가 비어 있다:
#     되어야 하는 것 중 S2에 의존하는 최저값 : 0.857  ('볼륨 좀 올려줘'·'밝기 좀 올려줘')
#     되면 안 되는 것 중 최고값             : 0.800  ('메모장 만들어줘')
#   → 둘 사이 **0.83**을 고른다. 0.85는 0.857과 0.007밖에 안 떠서 빡빡하다.
#
# 🔑 그리고 **S1(intent)이 같은 날 훨씬 넓어졌다** — 앱 5개와 동작 어휘가 늘어
#   예전에 S2로 흘렀던 것들이 이제 S1에서 잡힌다. 퍼지는 «마지막 수단»이므로
#   S1이 강해진 만큼 조일 수 있다.
#
# ⚠️ 올려서 빗나가는 명령은 **사라지지 않는다** — 오프라인이면 M5가
#   *"혹시 '메모장 열어줘' 말씀이신가요?"* 로 되묻고, 「네」면 실행된다.
#   **틀린 것을 말없이 실행하는 것보다 한 번 묻는 것이 낫다.**
#
# ⏸️ 더 나은 해법은 임계가 아니라 **S1을 군말에 강하게 만드는 것**이다
#   ('볼륨 좀 올려줘'가 S1=X인 이유는 트리거 "볼륨 올"이 「좀」 때문에 안 걸리는 것이다).
#   그건 `has_uncovered_command`의 커버 계산과 엮여 있어 따로 다룬다 → BACKLOG BL-43
SIMILARITY_THRESHOLD = 0.83

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
    # M6: 다른 PC에서 «가져온» 항목인가. 어디서 왔는지 남긴다.
    #
    # ⚠️ **필드를 안 만들고 dict에만 넣으면 캐시가 통째로 날아간다.**
    #   `_load()`가 `CacheEntry(**v)`로 복원하는데 모르는 키가 있으면 TypeError가 나고,
    #   그 예외를 `except`가 삼켜 **self._cache = {}** 로 초기화한다. 조용히.
    #   → 캐시 JSON에 새 키를 넣을 땐 **반드시 여기에도 필드를 추가할 것.**
    imported: bool = False


# ── P4: 동적 학습 정책 상수 ───────────────────────────────────────
# 학습 대상 화이트리스트 (파라미터 없음/고정어휘 제어 도구만).
# 자유 파라미터 도구(폴더명·검색어·set_volume 숫자·type_text 등)는 제외 → 오염 원천 차단.
LEARNABLE_TOOLS = frozenset([
    "open_app", "close_app", "maximize_window", "minimize_window", "show_desktop",
    "volume_up", "volume_down", "mute_toggle", "brightness_up", "brightness_down",
    "take_screenshot", "get_battery_status", "get_current_time", "get_running_apps",
    # 🆕 읽는 도구 (BL-60). 파라미터가 없고 아무것도 안 바꾼다.
    # ⚠️ `set_brightness` 는 **안 넣는다** — `level` 이 자유 파라미터라
    #   `set_volume` 과 같은 이유로 빠진다(캐시는 파라미터를 저장하지 않는다).
    "get_brightness", "get_volume",
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
    # 🆕 조회 (BL-60) — «묻기만 했는데 바뀌던» 자리의 나머지 절반이다.
    # 🔑 게이트가 «조작으로 가는 길»을 막고, 이 시드가 «조회로 가는 길»을 연다.
    #   시드가 없으면 매번 LLM 을 타야 답이 나온다(2.5초).
    ("밝기 얼마야",        [{"name": "get_brightness", "args": {}}],                 "✓ 지금 화면 밝기를 알려드렸습니다."),
    ("밝기 알려줘",        [{"name": "get_brightness", "args": {}}],                 "✓ 지금 화면 밝기를 알려드렸습니다."),
    ("볼륨 얼마야",        [{"name": "get_volume", "args": {}}],                     "✓ 지금 볼륨을 알려드렸습니다."),
    ("볼륨 알려줘",        [{"name": "get_volume", "args": {}}],                     "✓ 지금 볼륨을 알려드렸습니다."),
    # 🔑 «음소거됐어?» 의 답은 `get_volume` 이다 — 이 도구가 음소거 상태를 같이 말한다.
    ("음소거됐어",         [{"name": "get_volume", "args": {}}],                     "✓ 지금 음소거 상태를 알려드렸습니다."),
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
    # 🆕 2026-09-11 — 오프라인 실기에서 «그림판 열어줘»가 네 번 실패했다.
    #   `_build_intent_index`가 여기 있는 앱마다 (key,'open')·(key,'close')를
    #   **자동 합성**하므로, 한 줄 추가가 곧 «LLM 없이 도는 명령» 두 개다.
    #   오프라인이 이 제품의 차별점이라면 **이 표의 길이가 차별점의 크기**다.
    #   ⚠️ `tools/app_control.py`의 APP_ALIASES·APP_PROCESS_MAP과 **짝이 맞아야 한다** —
    #      여기만 넣으면 캐시는 히트하는데 실행이 실패한다(거짓 약속이 된다).
    ("그림판",        "paint",       "그림판"),
    ("페인트",        "paint",       "그림판"),
    ("작업 관리자",   "taskmgr",     "작업 관리자"),
    ("작업관리자",    "taskmgr",     "작업 관리자"),
    ("제어판",        "control",     "제어판"),
    ("캡처 도구",     "snippingtool", "캡처 도구"),
    ("캡처도구",      "snippingtool", "캡처 도구"),
    ("돋보기",        "magnify",     "돋보기"),
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
    # 🚨 **밝기가 볼륨보다 먼저 와야 한다. (2026-09-11 3차 실기)**
    #   *"밝기 줄여줘"* 가 **miss**였다. 원인: `volume_down`의 맨몸 트리거 「줄여」가
    #   **먼저** 걸려 `(brightness, volume_down)` 이라는 **없는 조합**이 된다.
    #   (`_match_action`은 ACTION_PATTERNS를 위에서부터 훑어 처음 맞는 것을 쓴다)
    #   ⚠️ 맨몸 트리거(「줄여」·「키워」)를 볼륨에서 빼면 *"소리 좀 줄여"* 가 깨진다 —
    #     그래서 **빼지 않고 순서를 바꿨다.**
    #   🔑 안전한 이유: 밝기 트리거는 전부 「밝기/밝게/밝혀/어둡」을 요구하므로
    #     볼륨 명령을 빼앗을 수 없다. 역은 성립하지 않아서 순서가 필요하다.
    ("brightness_up",    ["밝기 올", "밝기 높", "밝기 키", "밝기 크게",
                          "화면 밝게", "밝게 해", "밝혀줘"]),
    ("brightness_down",  ["밝기 내", "밝기 낮", "밝기 줄", "밝기 작게",
                          "화면 어둡", "어둡게 해"]),
    ("volume_up",        ["볼륨 올", "소리 올", "볼륨 높", "소리 높", "볼륨 크게", "소리 크게",
                          "볼륨 키", "소리 키", "키워", "키우"]),                     # P4-4
    ("volume_down",      ["볼륨 내", "소리 내", "볼륨 낮", "소리 낮", "볼륨 작게", "소리 작게",
                          "볼륨 줄", "소리 줄", "줄여", "줄이"]),                     # P4-4
    # 🆕 조회 동작 (BL-60). 🚨 **올리기·내리기 뒤에 온다.**
    #   앞에 두면 *"소리 얼마나 줄여줘"* 가 「볼륨 얼마」에 먼저 걸려 **명령이
    #   조회가 된다.** 뒤에 두면 「줄여」가 먼저 걸려 제대로 내려간다.
    #   (밝기가 볼륨보다 앞에 있는 것과 같은 성질의 순서다)
    ("brightness_get",   ["밝기 얼마", "밝기 몇", "밝기 알려", "밝기 어때",
                          "밝기 확인", "밝기 상태", "밝기 뭐"]),
    ("volume_get",       ["볼륨 얼마", "소리 얼마", "볼륨 몇", "소리 몇",
                          "볼륨 알려", "소리 알려", "볼륨 어때", "소리 어때",
                          "볼륨 확인", "볼륨 상태", "볼륨 뭐"]),
    # 🚨 **`mute` 보다 먼저.** 「음소거」가 `mute` 트리거라 뒤에 두면
    #   *"음소거됐어?"* 가 **음소거를 토글한다** — 상태를 물었는데 소리가 꺼진다.
    ("mute_get",         ["음소거됐", "음소거돼", "음소거상태", "음소거중",
                          "음소거야", "음소거인가", "음소거니", "음소거 상태"]),
    ("mute",             ["음소거"]),
    ("screenshot",       ["스크린샷", "화면 캡처", "캡처해줘", "찍어"]),   # P4-4 "찍어"
    ("time",             ["몇 시", "몇시", "현재 시간", "지금 시간"]),
    ("battery",          ["배터리 얼마", "배터리 확인", "배터리 남았"]),
    ("running_apps",     ["뭐 켜져", "켜져 있", "실행 중인 앱", "어떤 앱"]),
    ("show_desktop",     ["바탕화면 보여", "바탕 화면 보여"]),
    ("maximize",         ["최대화"]),
    ("minimize",         ["최소화"]),
    # close는 open보다 먼저 (꺼줘/종료가 열어줘 포함 시 오인식 방지)
    ("close",            ["꺼줘", "닫아줘", "종료해줘", "닫줘", "꺼 줘", "종료 해줘",
                          # 🆕 2026-09-11 — 실기 말투. 「끄」는 「꺼」와 달리
                          #   '끄고'·'끄자'·'끌래'를 잡는다.
                          "종료시켜", "닫기", "끄고", "끌래", "끄자", "닫자",
                          "꺼", "닫아", "종료", "닫", "끄"]),
    ("open",             ["열어줘", "켜줘", "실행해줘", "시작해줘", "띄워줘",
                          "열어 줘", "켜 줘", "실행 해줘", "열어", "켜", "실행", "시작",
                          # 🆕 2026-09-11 — 실기에서 빗나간 말투들.
                          #   «그림판 열어달라고»·«메모장을 띄어 보도록 하여라»가
                          #   miss였다(BL-37 오제안의 절반이 여기서 나왔다).
                          #   ⚠️ 「보여」는 show_desktop·recent_file보다 **뒤에** 있어
                          #     '바탕화면 보여줘'·'최근 파일 보여줘'를 빼앗지 않는다
                          #     (ACTION_PATTERNS는 위에서부터 먼저 맞는 것을 쓴다).
                          "열어달라", "열어 달라", "띄어", "띄우", "띄워봐", "띄워 봐",
                          "불러와", "불러 와", "보여줘", "보여 줘", "보여",
                          "실행시켜", "실행 시켜", "열어봐", "열어 봐", "켜봐", "켜 봐",
                          "띄워", "오픈", "열기", "열"]),                # P4-4 동의어
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
#
# 🔎 **2026-09-12 — 「하나」를 뺐다 (LAUNCH_CHECKLIST §7 「결함 B」).**
#   *"메모장 하나 띄워봐"* 가 **캐시를 통째로 포기**하고 있었다. 오프라인에서는
#   그게 «되는 명령이 안 되는» 것으로 보인다 — 제안조차 안 뜬다.
#
#   🔑 **「하나」는 단독으로는 «추가로»가 아니라 그냥 군말이다.**
#      "메모장 하나 띄워봐" = "메모장 띄워봐". «한 개 더»를 뜻하려면
#      **「더」나 「또」가 붙는다** — `"메모장 하나 더 열어줘"` · `"또 하나 열어줘"`.
#      그런데 **「더」·「또」는 이미 이 목록에 있다.** 그래서 「하나」는
#      잡아야 할 것을 혼자 잡은 적이 없고 **오탐만 만들고 있었다.** 실측:
#        "메모장 하나 띄워봐"   현행 포기 → **캐시 즉시 실행**
#        "계산기 하나 켜줘"     현행 포기 → **캐시 즉시 실행**
#        "메모장 하나 더 열어줘" 현행 포기 → **포기 그대로** (「더」가 잡는다)
#        "메모장 또 하나 열어줘" 현행 포기 → **포기 그대로** (「또」가 잡는다)
#
#   ⚠️ **`_FILLER_TOKENS`로 옮기지는 않았다.** 그 집합은 커버 계산만이 아니라
#      **매칭 경로에서도 쓰인다**(`_FILLER_TOKENS` 참조 지점 2곳). 옮겨 보니
#      `find('메모장 하나 띄워봐')` 가 **히트에서 None으로 깨졌다.**
#      BL-43이 경고한 «매칭용과 커버용이 엮여 있다»가 바로 이 자리다.
_RESIDUAL_MODIFIERS = frozenset([
    "새로", "새로운", "새", "새창", "새탭", "또", "추가로", "더", "따로",
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

# ── BL-50: 지시대명사 — **맥락에 묶인 말은 패턴이 될 수 없다** ─────
#
# 1차 리허설(2026-09-12) 대본 2장면에서 이게 박혔다:
#
#   '그거 꺼줘'  → close_app(메모장)      ← 직전 턴에만 의미가 있는 말이다
#
# 그 뒤로 **크롬을 보며 「그거 꺼줘」 하면 메모장이 꺼진다.** 캐시는 맥락을 안 본다.
#
# 🚨 **BL-27의 재발이 아니라 «다른 문»이다.** BL-27은 «승인 응답(「그래」)이 명령이
# 됐다»였고 L1~L3은 «아는 낱말이 있나 · 너무 짧나 · 대조가 있나»를 본다.
# `'그거 꺼줘'`는 「꺼」가 action이라 **셋을 전부 통과한다** — 실측으로 확인했다.
# 「그거」가 **지시대명사**라는 것은 아무도 안 봤다.
#
# ⚠️ **한 번 지우는 걸로는 안 된다.** 대본을 돌 때마다 다시 박힌다. 그래서
#   «오염분 제거»가 아니라 **게이트**로 막는다. → [BACKLOG BL-50](../docs/BACKLOG.md)
#
# 어절의 **시작**을 본다 — 한국어는 조사가 뒤에 붙으므로(「그거를」·「여기에」)
# 지시어는 어절 머리에 온다. `_CONTRAST_TOKENS`가 끝을 보는 것(「메모장말고」)과
# 정확히 반대다.
#
# ⚠️ 오판의 방향이 안전하다 — 막아서 생기는 손해는 **LLM이 2.5초에 처리**하는 것뿐이고,
#   놓쳐서 생기는 손해는 **엉뚱한 앱을 끄는 것**이다(BL-27이 정한 비대칭과 같다).
_DEIXIS_TOKENS = frozenset([
    "그거", "이거", "저거", "그걸", "이걸", "저걸",
    "그것", "이것", "저것", "그게", "이게", "저게",
    "걔", "얘", "쟤", "거기", "여기", "저기",
])

# ── BL-60: 조회 게이트 — **묻기만 했는데 상태가 바뀌던 것** ────────
#
# 2026-09-19 라이브 점검에서 *"밝기 알려줘"* 한 마디에 **화면이 70%로 바뀌었다.**
#
#   '밝기 알려줘'  ↔  '밝기 올려줘'   ← 한 글자 차이다. 유사도 **0.83**
#
# 그리고 `SIMILARITY_THRESHOLD` 가 **정확히 0.83**이다. 「알」과 「올」 하나로
# 조회가 조작이 된다. 볼륨도 같고(`'볼륨 알려줘'` → `volume_up`),
# 🚨 **«음소거됐어?» 는 `mute_toggle` 을 부른다** — 상태를 물었는데 **소리가 꺼진다.**
# (이건 백로그에도 없던 것이고, 셋 중 가장 나쁘다 — 사용자가 묻기만 했다)
#
# ## 왜 «조회 표지» 목록만으로는 안 되나
#
# 「알려줘」가 있으면 캐시를 포기하는 식으로 만들면 *"시간 알려줘"*·*"배터리 알려줘"* 가
# 같이 죽는다. **그 둘은 원래 잘 되고 있었다** — 읽는 도구로 정확히 간다.
# 그래서 발화만 보지 않고 **«묻는 말인데 걸린 도구가 상태를 바꾸는가»** 를 본다.
# 판정에 도구가 들어가므로 게이트는 Stage 0 이 아니라 **매칭 뒤**에 놓인다.
#
# ## 🚨 목록을 «조작 도구»가 아니라 «조회 도구»로 적는 이유
#
# 여집합으로 두면 **도구가 하나 늘 때마다 조용히 샌다**(`graph.py` 의
# `READONLY_RETRY_TOOLS` 가 같은 이유로 화이트리스트다). 여기서 빠뜨렸을 때
# 어느 쪽이 안전한지 보면 답이 나온다:
#
#   조작 도구를 빠뜨리면  → 묻는 말이 **실행된다.** 되돌려야 한다
#   조회 도구를 빠뜨리면  → 묻는 말이 **LLM 으로 간다.** 2.5초 느릴 뿐 답은 맞다
#
# 그래서 **모르는 도구는 조작으로 본다.** 오판의 방향이 안전한 쪽이다
# (BL-27·BL-50이 정한 비대칭과 같다).
_QUERY_SAFE_TOOLS = frozenset([
    "get_brightness", "get_volume",
    "get_battery_status", "get_current_time", "get_running_apps",
    "find_file", "list_directory",
])

#: 「줄여」·「올려」처럼 **바꾸라는 말**이 실제로 들어 있으면 그건 묻는 게 아니다.
#
# 🚨 **없으면 오프라인에서 명령이 죽는다.** *"소리 얼마나 줄여줘"* 는 「얼마」 때문에
#   조회로 읽혀 캐시를 포기하는데, 온라인이면 LLM 이 받아 주지만 **오프라인이면
#   거기서 끝난다** — 오프라인 캐시 히트는 도는데 미스는 LLM 을 못 부른다(BL-46).
#   «느려질 뿐 틀리지 않는다»가 오프라인에서는 성립하지 않는 자리다.
#
# 🔑 여기 빠뜨린 동작은 **게이트가 그대로 걸린다**(= LLM 으로 간다). 안전한 쪽이라
#   화이트리스트로 적는다 — `_QUERY_SAFE_TOOLS` 와 같은 이유다.
# ⚠️ `mute` 는 **일부러 뺐다.** 「음소거」는 명사라 *"음소거됐어?"* 에도 들어 있어서,
#   넣으면 상태를 묻는 말이 토글로 새는 길이 다시 열린다(`mute_get` 이 앞에 있어
#   대부분 막히지만, 면제까지 주면 두 겹이 한꺼번에 풀린다).
_COMMANDING_ACTIONS = frozenset([
    "brightness_up", "brightness_down", "volume_up", "volume_down",
    "open", "close", "maximize", "minimize", "show_desktop", "screenshot",
])

#: 「올려」·「줄여」처럼 **상태를 바꾸라는 동사**. `_match_action` 이 조회 동작을
#: 건너뛸지 정할 때 본다. ⚠️ 여기 빠뜨리면 조회가 명령을 가로챌 수 있으므로
#: (위 `_match_action` 주석의 «밝기 얼마나 올려줘») **늘리는 쪽이 안전하다.**
_CHANGE_VERBS = ("올려", "올리", "높여", "높이", "키워", "키우", "크게",
                 "내려", "내리", "낮춰", "낮추", "줄여", "줄이", "작게",
                 "밝게", "밝혀", "어둡게", "맞춰", "설정")

#: «묻는 말»의 표지. 공백을 지운 문자열에서 찾는다.
#
# ⚠️ **양방향으로 봐야 한다.** 의문형이지만 명령인 말(*"볼륨 30으로 맞춰 줄래"*)을
#   같이 막으면 멀쩡한 명령이 죽는다. 그래서 「줄래」·「해줄래」 같은 **요청 어미는
#   넣지 않는다** — 저건 묻는 게 아니라 부탁이다.
# ⚠️ 「확인」은 넣되 「확인해」·「확인좀」으로 좁힌다. 「배터리 확인」은 이미 조회
#   트리거이고 읽는 도구로 가므로 이 게이트에 걸려도 통과한다.
_QUERY_MARKERS = (
    "얼마",                                   # 얼마야 · 얼마나 · 얼마예요
    "몇%", "몇퍼", "몇프로", "몇단계",
    "알려줘", "알려주",
    "어때", "어떤가", "어떻게돼",
    "뭐야", "뭐예요", "뭔데",
    "상태",
    "확인해", "확인좀",
    "돼있", "되있", "됐어", "됐나",            # 「음소거됐어?」
)

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
        """(action 키, 실제로 걸린 트리거) — 우선순위 순서대로. 둘 다 공백 제거된 값.

        🚨 **조회 동작(`*_get`)은 «바꾸라는 말»이 같이 있으면 안 걸린다** (BL-60).
          *"밝기 얼마나 올려줘"* 는 「밝기얼마」를 품고 있어서 그냥 두면 **밝기를
          읽어 주고 만다** — 올려 달라고 했는데. 볼륨 쪽은 「줄여」가 조회보다
          **앞에** 있어 우연히 안 걸렸고, 밝기는 「밝기올」이 「밝기 얼마나 올려」에
          안 맞아서 드러났다. **순서로는 못 막는 축이라 여기서 본다.**
          (게이트의 `_COMMANDING_ACTIONS` 면제와 **같은 생각**이다 —
           바꾸라는 말이 있으면 묻는 게 아니다)
        """
        has_change = any(v in text_ns for v in _CHANGE_VERBS)
        for action_key, triggers in ACTION_PATTERNS:
            if has_change and action_key.endswith("_get"):
                continue
            for trigger in triggers:
                t = trigger.replace(" ", "")
                if t in text_ns:
                    return (action_key, t)
        return None

    # ── BL-60: 조회 게이트 ────────────────────────────────────────

    def has_query_marker(self, text: str) -> bool:
        """**묻는 말**인가. (`has_deixis`·`has_contrast_marker`와 같은 자리)"""
        return any(m in self._normalize(text).replace(" ", "")
                   for m in _QUERY_MARKERS)

    def query_conflict(self, user_input: str, tool_calls: list) -> bool:
        """묻는 말인데 **상태를 바꾸는 도구**가 걸렸는가. (BL-60)

        🔑 **발화만 보지도, 도구만 보지도 않는다.**
          발화만 보면 *"시간 알려줘"* 가 같이 죽고(읽는 도구로 잘 가고 있었다),
          도구만 보면 *"밝기 올려줘"* 가 막힌다(그건 조작이 맞다).
          둘이 **같이** 성립할 때가 «묻기만 했는데 바뀐다» 이고, 그때만 막는다.

        ⚠️ 막혀서 가는 곳이 **LLM**이라는 게 핵심이다 — 거기에는 이제 읽는 도구가
          있다(`get_brightness`·`get_volume`). 게이트와 도구는 **한 쌍**이라
          한쪽만 있으면 «안 바뀌지만 답도 못 하는» 상태가 된다.
        """
        if not tool_calls:
            return False
        if not self.has_query_marker(user_input):
            return False
        # «바꾸라는 말»이 실제로 있으면 묻는 게 아니다 — *"소리 얼마나 줄여줘"*
        act = self._match_action(self._normalize(user_input).replace(" ", ""))
        if act and act[0] in _COMMANDING_ACTIONS:
            return False
        return any((c.get("name", "") or "") not in _QUERY_SAFE_TOOLS
                   for c in tool_calls)

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

    def has_deixis(self, user_input: str) -> bool:
        """발화가 **직전 맥락을 가리키는 말**에 기대고 있는가. (BL-50)

        「그거 꺼줘」의 「그거」는 **직전 턴에만 의미가 있다.** 캐시는 맥락을 안 보므로
        이런 말을 패턴으로 굳히면 «크롬을 보며 「그거 꺼줘」 하니 메모장이 꺼지는»
        일이 생긴다 — 1차 리허설에서 실제로 박혔다.

        어절 **완전일치** 또는 **어절의 시작**만 본다. 한국어는 조사가 뒤에 붙어
        (「그거를」·「여기에」) 지시어가 어절 머리에 오기 때문이고, 부분일치로
        엉뚱한 낱말(「높이거나」)을 삼키지 않기 위해서다.
        `has_contrast_marker`가 어절의 **끝**을 보는 것과 정확히 반대다.
        """
        text = self._normalize(user_input)
        for tok in text.split(" "):
            if not tok:
                continue
            if tok in _DEIXIS_TOKENS:
                return True
            if any(tok.startswith(d) and len(tok) > len(d) for d in _DEIXIS_TOKENS):
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

        # Stage 0-b: 지시대명사 게이트 (BL-50) — 대조 게이트와 같은 자리다.
        #
        # 학습(L4)만 막으면 **이미 박힌 항목과 가져온 항목은 그대로 돈다.**
        # BL-27이 같은 이유로 두 곳에 걸었다 — 입구를 하나만 막으면 다른 입구로 샌다.
        # ⚠️ 막혀서 가는 곳이 **LLM**이라는 게 핵심이다 — 대화 맥락을 가진 쪽은
        #   거기뿐이라, «그거»가 무엇인지 아는 유일한 자리다.
        if self.has_deixis(normalized):
            print(f"[CommandCache] [BL-50] 지시대명사 → 캐시 포기, LLM으로: {normalized!r}")
            return None

        # Stage 1: Intent-based
        intent = self._extract_intent(normalized)
        if intent and intent in self._intent_index:
            matched = self._intent_index[intent]
            # Stage 0-c: 조회 게이트 (BL-60) — **매칭 뒤**에 놓인다.
            # 판정에 «걸린 도구»가 들어가므로 앞의 두 게이트처럼 입구에 못 둔다.
            if self.query_conflict(normalized, matched.tool_calls):
                print(f"[CommandCache] [BL-60] 묻는 말인데 조작 도구 → 캐시 포기, "
                      f"LLM으로: {normalized!r} ↛ {matched.pattern!r}")
                return None
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
            # 🚨 **여기가 실제로 샌 자리다.** '밝기 알려줘' ↔ '밝기 올려줘' 가 0.83 이고
            #    임계가 정확히 0.83 이다 — 한 글자 차이로 조회가 조작이 됐다.
            if self.query_conflict(normalized, best_entry.tool_calls):
                print(f"[CommandCache] [BL-60] 묻는 말인데 조작 도구 → 캐시 포기, "
                      f"LLM으로: {normalized!r} ↛ {best_entry.pattern!r} "
                      f"(score={best_score:.2f})")
                return None
            print(f"[CommandCache] [S2-sim] score={best_score:.2f} → {best_entry.pattern!r}")
            return best_entry, best_score

        return None

    def _similarity(self, a: str, b: str) -> float:
        """Stage-2 의미 유사도 (0~1).

        경량(글자 유사도 SequenceMatcher). 오프라인·무설치.

        ⚠️ **«이 메서드만 임베딩 코사인으로 교체하면 된다»고 오래 적혀 있었는데,
           2026-09-10에 재 보니 틀렸다.** 자를 더 좋은 것으로 바꾸면 맞는 것도 늘고
           **틀린 것도 는다.** 캐시는 승인 없이 도구를 실행하므로 팔 수 있는 정밀도가
           없다 → 임베딩은 `suggest()`(제안 전용)로 갔다.
           → [M5 §5-2](../docs/design/M5_임베딩_캐시.md)
        """
        return SequenceMatcher(None, a, b).ratio()

    # ── 임베딩 «제안» (M5 §5-2) ───────────────────────────────────
    #
    # 🔒 **이 경로는 아무것도 실행하지 않는다.** 후보 하나를 돌려줄 뿐이고,
    #    실행 여부는 **사용자의 「네」** 가 정한다.
    #
    # 왜 이렇게 됐나: 임베딩으로 «실행»을 결정하려고 τ·δ 격자를 다 훑었는데
    # **오매칭 0인 임계가 존재하지 않았다**(마진이 어느 설정에서도 음수).
    # 지금 배선하면 캐시가 `뻥카 치냐`를 실행한다(코사인 0.910).
    # 그런데 **제안**으로 쓰면 그 전제가 통째로 사라진다 — 틀려도 사고가 아니고,
    # 지표가 마진에서 **top-1(12/17)** 로 바뀐다. → M5 §6-3-C
    #
    # ⚠️ 느슨해도 되는 것(τ·δ)과 **절대 느슨하면 안 되는 것**을 가른다.
    #    사용자가 「네」라고 하면 **실제로 실행되므로** 아래 셋은 그대로 건다:
    #      ① 안전 도구만 (V5)  ② 복합 명령 제외 (BL-15)  ③ 대조 게이트 (BL-27)
    # 🚨 **절대 임계를 쓰지 않는다.** 2026-09-11에 구현하면서 재 봤더니
    #    `'뻥카 치냐'` → `'소리 내려줘'` 가 **코사인 0.965**, `'오늘 저녁 뭐 먹지'` →
    #    `'바탕화면 보여줘'` 가 **0.983**이었다. 정상 매칭(`'메모장 하나 띄워봐'`)이
    #    0.969다 — **임계를 어디에 둬도 갈리지 않는다.** ADR §6-3이 «마진이 음수»라고
    #    적은 것이 이 모양이고, 구현 중에 **같은 자리를 다시 밟아 확인했다.**
    #
    #    그래서 임베딩은 **순위만** 낸다(측정된 강점: top-1 12/17).
    #    «말이 되는가»는 **낱말 겹침**이 판정한다 — 사전은 일반화 못 하지만
    #    **오매칭이 0**이다(§6-3-D). 둘은 경쟁이 아니라 보완이다(ADR §6-3-C).
    #    ⚠️ **중심화한 코사인은 0.3~0.55대**다(원본 0.9대와 다르다). 그리고
    #    `'뻥카 치냐'`가 **0.552**로 정상 매칭(0.388)보다 높다 — 다시 말해
    #    **이 숫자는 순위 말고는 아무 뜻이 없다.**
    #
    # 🔖 **그래서 바닥값(임계)을 아예 두지 않는다.** 처음엔 «완전한 쓰레기만 자르는»
    #    용도로 0.15를 뒀는데, 2026-09-11 실기에서 그게 **멀쩡한 명령을 갈랐다** —
    #    `'소리 좀 키워줘'`(0.14)는 막히고 `'어 소리 좀 키워봐'`(0.16)는 통과했다.
    #    뜻 없는 숫자를 문지기로 쓰면 **갈림만 생긴다.** 빼고 재니 정상 6/6이
    #    살아나고 오제안은 10개 중 1개뿐이었다(`'소리 소문도 없이'` — 「소리」가
    #    글자로 들어 있는 경우. 바닥값으로는 어차피 못 막는 종류다).
    #
    #    문지기는 **오직 `_shares_token()`** 이다.

    def suggest(self, user_input: str) -> Optional[tuple["CacheEntry", float]]:
        """*"혹시 이걸 말씀하신 건가요?"* 후보. **실행하지 않는다.**

        Returns: (CacheEntry, 코사인) 또는 None.
        모델이 없거나 어떤 이유로든 실패하면 **조용히 None** — 이 기능이 없어도
        오늘과 똑같이 동작해야 한다(캐시는 핵심 경로다).
        """
        text = self._normalize(user_input)
        if not text:
            return None

        # ③ 대조 게이트 — `find()`와 같은 판정을 받는다 (BL-27)
        if self.has_contrast_marker(text):
            return None

        # ③-b 지시대명사 게이트 — 같은 이유다 (BL-50).
        #   «혹시 「메모장 꺼줘」인가요?»라고 제안하면 사용자는 「네」라고 답하고,
        #   그러면 **캐시가 고른 엉뚱한 앱이 꺼진다.** 제안도 실행의 입구다(BL-37).
        if self.has_deixis(text):
            return None

        # ② 복합 명령이면 제안하지 않는다. 「네」 했는데 절반만 실행되면 그게 사고다
        try:
            from core.fast_path import is_compound_command
            if is_compound_command(text):
                return None
        except Exception:
            pass                     # 판정을 못 하면 제안도 안 한다는 쪽이 안전하지만,
                                     # import 실패로 기능을 죽이지는 않는다

        # ②-b **V4 / BL-15 — 문장의 «일부만» 이해한 것도 제안하지 않는다.**
        #
        # 🔖 2026-09-11에 테스트가 이걸 잡았다. 처음엔 `is_compound_command`만 걸었는데
        #    *"메모장에 회의록이라고 적어줘"* 가 통과해 `'메모장 열어줘'` 를 제안했다.
        #    복합 명령이 아니라 **한 문장인데 캐시가 앞부분만 아는** 경우다.
        #    「네」 하면 메모장만 열리고 **입력은 사라진다** — BL-15가 읽기 쪽에서
        #    *"잔여 명령이 있으면 캐시를 포기한다"* 고 정한 바로 그 상황이다.
        if self.has_uncovered_command(text):
            return None

        try:
            from core.embedder import get_embedder
            emb = get_embedder()
            if not emb.available:          # ⚠️ 메서드가 아니라 프로퍼티다(지연 로딩)
                return None
            # ① 안전 도구만 남긴다 (V5 — 협상 대상이 아니다)
            keys, entries = [], []
            for key, entry in self._cache.items():
                calls = entry.tool_calls or []
                if len(calls) != 1:
                    continue
                if calls[0].get("name", "") not in LEARNABLE_TOOLS:
                    continue
                keys.append(key)
                entries.append(entry)
            if not keys:
                return None

            mat = emb.encode_many(keys)
            vec = emb.encode(text)
            if mat is None or vec is None:
                return None
            import numpy as _np
            # 중심화 — 임베딩 공간이 한쪽으로 쏠려 있어(anisotropy) 아무 두 문장이나
            # 0.9를 넘는다. 평균을 빼면 **순위**가 좋아진다(ADR §6-3: top-1 9 → 12).
            # ⚠️ 점수의 절대값은 여전히 못 믿는다 — 그래서 아래 낱말 겹침이 있다.
            mu = mat.mean(axis=0)
            mat_c = mat - mu
            vec_c = vec - mu
            n_mat = _np.linalg.norm(mat_c, axis=1) + 1e-9
            n_vec = float(_np.linalg.norm(vec_c)) + 1e-9
            sims = (mat_c @ vec_c) / (n_mat * n_vec)
        except Exception as e:
            print(f"[CommandCache] 제안 생략({type(e).__name__}: {e})")
            return None

        # 🔖 **걸러낸 뒤에 순위를 본다.** 반대로 하지 말 것 —
        #    2026-09-11 실기에서 `'밝기 좀 낮춰봐'` 는 제안이 나오는데
        #    **`'어 밝기 좀 낮춰봐'` 는 안 나왔다.** 「어」 한 글자가 전역 순위를
        #    흔들어 맞는 후보를 top-3 **밖으로** 밀어낸 것이다.
        #    짧은 문장의 임베딩은 이런 잡음에 약하다 — 그래서 **문지기(낱말 겹침)를
        #    먼저 통과시키고, 살아남은 것들 사이에서만 순위를 쓴다.**
        #    임베딩의 역할이 «후보 고르기»에서 «살아남은 것 줄 세우기»로 좁아진다.
        def _tool_of(i: int) -> Optional[str]:
            calls = entries[i].tool_calls or []
            return calls[0].get("name") if calls else None

        cand = [i for i in range(len(keys))
                if self._shares_token(text, keys[i], _tool_of(i))]
        if not cand:
            return None
        i = max(cand, key=lambda j: sims[j])
        score = float(sims[i])
        print(f"[CommandCache] [S2-embed] cos={score:.3f} "
              f"후보={len(cand)}개 → {entries[i].pattern!r} (제안)")
        return entries[i], score

    #: 반대 동작이 있고 **틀리면 되돌리기 비싼** 행동. (V3)
    #
    #  ⚠️ **«반대가 있는 모든 동작»이 아니다.** 밝기·볼륨도 올리/내리가 짝이지만
    #     여기 넣지 않는다 — 틀려도 *"다시 올려줘"* 한 마디면 끝이고, 넣으면
    #     제안이 가장 값진 자리(대상만 알고 동작을 모를 때)가 통째로 죽는다.
    #     기준은 «반대인가»가 아니라 **«되돌리는 비용»** 이다.
    #     `close_app`은 **쓰던 글이 날아갈 수 있어** 되돌릴 수 없다.
    #
    #  🔑 그리고 제안은 **후보를 문장으로 보여 준다** — 사용자가
    #     *"'밝기 올려줘' 말씀이신가요?"* 를 읽고 아니라고 할 수 있다.
    #     그게 이 설계의 안전망이고, 되돌리기 싼 것까지 막을 이유가 없는 이유다.
    _AMBIGUOUS_ACTIONS = frozenset({"open", "close"})

    #: 되돌리기 비싼 **도구** — 위 `_AMBIGUOUS_ACTIONS`의 도구판. (BL-37)
    #
    #  🚨 **왜 도구 이름으로 다시 적는가.** 예전에는 낱말 어휘(`_extract_action`)로만
    #     판정했는데 **어휘에 없는 말이 그대로 새어나갔다.** 실측:
    #       _extract_action('메모장 불러와줘') → None   ← 「불러와」가 어휘에 없었다
    #     그래서 *"메모장에 회의록이라고 적어줘"* 에 **`open_app` 후보가 제안됐고**,
    #     「네」 하면 메모장만 열리고 **적으려던 글이 사라진다.**
    #     mock 37건이 `'메모장 꺼줘'`(「꺼」는 어휘에 있다)로만 확인해 못 잡았다.
    #
    #  🔑 **캐시 엔트리는 도구 이름을 정확히 알고 있다.** 추측할 필요가 없는 것을
    #     추측하고 있었다 — 어휘는 넓히면 또 빠지지만 도구 이름은 빠질 수 없다.
    _AMBIGUOUS_TOOLS = frozenset({"open_app", "close_app"})

    def _shares_token(self, text: str, pattern: str,
                      tool_name: Optional[str] = None) -> bool:
        """발화와 후보가 **같은 것을 가리키는가** — 임베딩이 못 하는 판정.

        이게 `'뻥카 치냐' → '소리 내려줘'`(코사인 0.965)를 막는 **유일한 장치**다.
        점수는 순위 말고 아무 뜻이 없으므로 문지기는 여기다.

        `tool_name`: 후보가 실제로 부르는 도구. 주면 **어휘 대신 이것으로**
          «되돌리기 비싼 동작인가»를 판정한다(BL-37). 안 주면 예전처럼 어휘로 본다 —
          테스트가 이 함수를 2인자로 직접 부르기 때문에 기본값을 둔다.
        """
        a1, a2 = self._extract_action(text), self._extract_action(pattern)

        # V3 — 둘 다 동작이 잡혔는데 **어긋나면** 거절한다.
        #   「켜」가 잡혔는데 후보가 close_app이면 그건 반대 동작이다.
        if a1 and a2 and a1 != a2:
            return False

        # 🚨 **2026-09-11 실기 — 여기서 «그림 반 열어줘»에 «크롬 열어줘»를 제안했다.**
        #   예전에는 `if a1 and a1 == a2: return True` 로 **동작이 같으면 바로 통과**시켰다.
        #   그러면 「열어줘」 하나만 겹쳐도 **세상의 모든 «X 열어줘»가 후보**가 되고,
        #   대상은 임베딩 순위가 고르는데 그게 못 믿을 신호다(ADR §6-3).
        #   사용자가 본 것: *"그림 반 열어줘"* → *"혹시 '크롬 열어줘' 말씀이신가요?"*
        #
        # 🔑 **그래서 대상(entity) 합의를 «항상» 요구한다.** 동작이 같다는 건
        #   «무엇을» 할지 정해 주지 않는다 — 제안의 값은 대상을 맞히는 데 있다.
        #   대상을 모르면 **제안하지 않는 것이 정직하다**(틀린 앱을 열게 하는 것보다).
        e1, e2 = self._extract_entity(text), self._extract_entity(pattern)
        if not (e1 and e1 == e2):
            return False
        if a1 and a1 == a2:
            return True

        # 대상만 같고 **동작을 모르는** 경우 — 동작은 임베딩 순위가 고른 셈이 된다.
        #
        # 🔖 2026-09-11에 테스트가 여기서 사고를 잡았다:
        #    *"메모장에 회의록이라고 적어줘"* (entity=메모장 · action 없음) 에
        #    `'메모장 꺼줘'`(**close_app**)가 1등으로 올라왔다. 「네」 했으면
        #    **메모장이 닫히고 쓰던 글이 날아간다.**
        #    ⚠️ 임베딩의 약점이 정확히 여기다 — 「켜/꺼」를 잘 못 가른다.
        #
        #    그래서 **동작을 모를 땐 반대 동작이 있는 부류를 제안하지 않는다.**
        #    볼륨·밝기처럼 대상만으로도 뜻이 좁혀지는 것은 그대로 통과한다
        #    (`'소리 조금만 더 크게'` → `'소리 올려줘'` 는 이 경로로 산다).
        # 대상만 같고 **동작을 모르는** 경우 — 동작을 임베딩 순위가 고른 셈이 된다.
        #   그래서 **되돌리기 비싼 부류는 제안하지 않는다.**
        #   🔑 판정 근거는 **도구 이름이 먼저**다(BL-37) — 어휘는 빠지는 말이 생긴다.
        if tool_name is not None:
            return tool_name not in self._AMBIGUOUS_TOOLS
        return a2 not in self._AMBIGUOUS_ACTIONS

    # ── 도구 직접 실행 ────────────────────────────────────────────

    #: 다 실패했을 때 할 말. `graph_agent._accept_suggestion` 과 **같은 문장**이다 —
    #: 같은 일(캐시 실행 실패)에 두 가지 말을 만들지 않는다.
    _FAIL_ALL = "그 명령을 실행하지 못했어요. 직접 다시 말씀해 주시겠어요?"

    @staticmethod
    def _verdict(entry, results, failed, missing):
        """돌린 결과를 **사실대로** 문장으로 만든다 (2026-09-16 감사 G-01).

        🚨 **예전에는 도구가 실패하면 `response_template` 을 대신 돌려줬다.**
        그 템플릿은 *«볼륨 올렸어요»* 같은 **성공 문장**이다 — 즉 실패한 턴이
        사용자에게 **성공으로 들렸다.** 이 저장소가 일곱 번 고친
        «확인하지 않고 됐다고 말하는 것»(BL-12·15·19·21·23·26·35)의 캐시 판본이고,
        하필 **LLM 을 안 거치는 경로**라 그물 넷이 전부 비켜간다.

        🔑 **«못 했어요»도 거짓일 수 있다** — 도구가 여럿이면 앞의 것은 이미 돌았고
        부작용이 남아 있다. 그래서 «전부 실패»와 «일부만»을 나눠 말한다.

        ⚠️ 예외 원문을 사용자에게 읽어 주지 않는다(감사 G-14와 같은 이유).
        상세는 로그로 간다.

        📜 **계약 (감사 G-03) — 캐시 히트 턴에서 정직함을 지는 자리는 여기 하나다.**
        그 턴은 `decision == "fast_hit"` 이라 `output_guard` 의 그물 넷이 전부
        비켜간다(구조적으로 무력하다 — 검사할 `ToolMessage` 가 없다).
        그러니 **여기서 나간 문장이 곧 사용자가 듣는 말이고, 뒤에 아무 검사도 없다.**
        계약 전문은 [`core/fast_path.py`](fast_path.py) 머리에 있고
        `tests/test_fast_hit_contract.py` 가 지킨다.
        """
        bad = len(failed) + len(missing)
        if bad == 0:
            return "\n".join(results) if results else entry.response_template
        if results:
            return (f"일부만 실행됐어요 — {len(results)}개는 됐고 {bad}개는 안 됐어요. "
                    f"확인해 주시겠어요?")
        return CommandCache._FAIL_ALL

    def _get_tools_map(self) -> dict:
        """BUG-10: 도구 맵을 초기화 시 한 번만 빌드하고 재사용."""
        if not self._tools_map:
            from core.tool_registry import get_all_tools
            self._tools_map = {t.name: t for t in get_all_tools()}
        return self._tools_map

    async def execute(self, entry: "CacheEntry") -> str:
        """캐시 엔트리의 도구 시퀀스를 LLM 없이 직접 실행.

        실패를 어떻게 말하는지는 `_verdict` 에 한 곳으로 모여 있다 — 여기와
        `execute_sync` 가 **서로 다르게 말하면** 경로에 따라 정직함이 갈린다.
        """
        tools_map = self._get_tools_map()
        results: list[str] = []
        failed: list[str] = []
        missing: list[str] = []

        for call in entry.tool_calls or []:
            name = call.get("name", "")
            args = call.get("args", {})
            if name not in tools_map:
                # G-04: 모르는 도구를 **조용히 건너뛰지 않는다.** 건너뛰면 2개짜리
                #       엔트리가 1개만 돌고도 «다 했어요»가 나간다.
                missing.append(name or "?")
                _log.error("[캐시 실행] 실행=실패 | 패턴=%r | 모르는 도구 %r",
                           entry.pattern, name)
                continue
            try:
                results.append(str(await tools_map[name].ainvoke(args)))
            except Exception as e:                            # noqa: BLE001
                failed.append(name)
                _log.error("[캐시 실행] 실행=실패 | 패턴=%r | 도구=%s | %s: %s",
                           entry.pattern, name, type(e).__name__, e)
        if failed or missing:
            _log.warning("[캐시 실행] 실행=부분실패 | 패턴=%r | 성공 %d · 실패 %d · 모름 %d",
                         entry.pattern, len(results), len(failed), len(missing))
        return self._verdict(entry, results, failed, missing)

    def execute_sync(self, entry: "CacheEntry") -> str:
        """캐시 엔트리를 동기로 직접 실행 (그래프 sync 경로용, P2).
        도구가 원래 동기 함수라 .invoke로 호출한다.

        🚨 **이 경로가 감사(2026-09-16)에서 가장 큰 구멍이었다** — G-01·02·04 가
        전부 이 함수 하나에서 나왔다. 그리고 여기는 **빠른 경로**라 LLM 을 안 거친다.
        """
        tools_map = self._get_tools_map()
        results: list[str] = []
        failed: list[str] = []
        missing: list[str] = []
        for call in entry.tool_calls or []:
            name = call.get("name", "")
            args = call.get("args", {})
            if name not in tools_map:
                missing.append(name or "?")
                _log.error("[캐시 실행] 실행=실패 | 패턴=%r | 모르는 도구 %r",
                           entry.pattern, name)
                continue
            try:
                results.append(str(tools_map[name].invoke(args)))
            except Exception as e:                            # noqa: BLE001
                failed.append(name)
                _log.error("[캐시 실행] 실행=실패 | 패턴=%r | 도구=%s | %s: %s",
                           entry.pattern, name, type(e).__name__, e)
        if failed or missing:
            _log.warning("[캐시 실행] 실행=부분실패 | 패턴=%r | 성공 %d · 실패 %d · 모름 %d",
                         entry.pattern, len(results), len(failed), len(missing))
        return self._verdict(entry, results, failed, missing)

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
        - **L4** — 지시대명사(「그거」·「여기」…)가 있으면 거절. (BL-50)
          → `'그거 꺼줘'`·`'거기에 회의록 적어줘'` 차단

        🚨 **L4는 L1~L3이 못 막는 축이다.** `'그거 꺼줘'`는 「꺼」가 action이라
        L1을 통과하고, 5글자라 L2도, 대조가 없어 L3도 통과한다 — 1차 리허설에서
        그대로 학습됐다. 맥락에 묶인 말은 **패턴이 될 수 없다**는 것이 L4다.

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
        if self.has_deixis(key):
            return "L4:지시대명사"
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
        # L5 — 묻는 말을 **조작 도구**로 굳히지 않는다. (BL-60)
        # 🔑 `is_learnable_utterance()` 안에 못 넣는 이유는 저 함수가 **발화만** 보기
        #    때문이다. 여기는 도구를 같이 봐야 한다 — '밝기 알려줘' → `get_brightness`
        #    는 **학습해야 맞고**, `brightness_up` 은 굳으면 안 된다.
        if self.query_conflict(key, tool_calls):
            names = ", ".join(c.get("name", "") for c in tool_calls)
            print(f"[CommandCache] [BL-60] 학습 거부(L5:묻는 말↛조작 도구 {names}): {key!r}")
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
        """캐시 파일을 읽는다.

        ⚠️ **모르는 키 하나에 전부 날아가지 않게 한다.** 예전엔 `CacheEntry(**v)`를
          그대로 불러서, 항목 하나에 낯선 키가 있으면 TypeError가 나고 그걸 `except`가
          삼켜 **`self._cache = {}`** 로 초기화했다. 동적 학습분이 조용히 사라진다.

          M6(내보내기/가져오기)가 **다른 버전이 쓴 캐시 파일을 들여오는 통로**라
          이 위험이 커졌다. 이제 ① 모르는 키는 버리고 ② 한 항목이 깨져도
          **나머지는 살리고** ③ 버린 게 있으면 **말한다.**
        """
        if not os.path.exists(CACHE_FILE):
            return
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[CommandCache] 파일을 읽지 못했습니다 (초기화): {e}")
            self._cache = {}
            return

        known = {f.name for f in fields(CacheEntry)}
        loaded: dict = {}
        dropped_keys: set = set()
        broken: list = []
        for k, v in (data or {}).items():
            if not isinstance(v, dict):
                broken.append(k)
                continue
            extra = set(v) - known
            if extra:
                dropped_keys |= extra
            try:
                loaded[k] = CacheEntry(**{kk: vv for kk, vv in v.items() if kk in known})
            except Exception:
                broken.append(k)        # 이 항목만 버린다. 나머지는 지킨다.

        self._cache = loaded
        user_entries = sum(1 for e in self._cache.values() if not e.is_seed)
        print(f"[CommandCache] 로드 완료 — 전체 {len(self._cache)}개 "
              f"(시드 {len(self._cache)-user_entries}개, 동적 {user_entries}개)")
        if dropped_keys:
            print(f"[CommandCache] ⚠️ 모르는 필드를 무시했습니다: "
                  f"{', '.join(sorted(dropped_keys))}")
        if broken:
            print(f"[CommandCache] ⚠️ 읽지 못한 항목 {len(broken)}개를 건너뛰었습니다 "
                  f"(나머지는 그대로 있습니다)")

    def reload(self) -> None:
        """파일에서 다시 읽는다. (M6 가져오기가 파일을 바꾼 뒤 부른다)

        가져오기는 **파일을 직접** 고친다 — 프로세스 안 사본은 낡은 채로 남으므로
        이걸 안 부르면 **가져온 명령이 다음 재시작까지 안 먹는다.**
        """
        self._cache = {}
        self._load()
        self._seed()
        self._build_intent_index()

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
