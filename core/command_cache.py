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

동적 캐싱 비활성화 (파라미터 오염 문제로 시드 기반만 사용).
"""

import json
import os
import re
import asyncio
from dataclasses import dataclass, asdict, field
from difflib import SequenceMatcher
from typing import Optional

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(_BASE_DIR, "cache", "command_cache.json")
SIMILARITY_THRESHOLD = 0.80


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
    ("volume_up",        ["볼륨 올", "소리 올", "볼륨 높", "소리 높", "볼륨 크게", "소리 크게"]),
    ("volume_down",      ["볼륨 내", "소리 내", "볼륨 낮", "소리 낮", "볼륨 작게", "소리 작게"]),
    ("mute",             ["음소거"]),
    ("brightness_up",    ["밝기 올", "밝기 높", "화면 밝게", "밝게 해", "밝혀줘"]),
    ("brightness_down",  ["밝기 내", "밝기 낮", "화면 어둡", "어둡게 해"]),
    ("screenshot",       ["스크린샷", "화면 캡처", "캡처해줘"]),
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
                          "열어 줘", "켜 줘", "실행 해줘", "열어", "켜", "실행", "시작"]),
    ("recent_file",      ["최근에 열었던", "최근 파일", "최근에 열"]),
]


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

    def _extract_entity(self, text: str) -> Optional[str]:
        """텍스트에서 entity 키 추출. 더 긴 표면형 우선."""
        text_ns = text.replace(" ", "")
        for surface, key in ALL_ENTITIES:
            if surface.replace(" ", "") in text_ns:
                return key
        return None

    def _extract_action(self, text: str) -> Optional[str]:
        """텍스트에서 action 키 추출. 우선순위 순서대로 확인."""
        text_ns = text.replace(" ", "")
        for action_key, triggers in ACTION_PATTERNS:
            for trigger in triggers:
                if trigger.replace(" ", "") in text_ns:
                    return action_key
        return None

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

        # Stage 1: Intent-based
        intent = self._extract_intent(normalized)
        if intent and intent in self._intent_index:
            matched = self._intent_index[intent]
            print(f"[CommandCache] [S1-intent] {intent} → {matched.pattern!r}")
            return matched, 0.90

        # Stage 2: SequenceMatcher fallback
        best_entry: Optional[CacheEntry] = None
        best_score = 0.0
        for key, entry in self._cache.items():
            score = SequenceMatcher(None, normalized, key).ratio()
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_score >= SIMILARITY_THRESHOLD and best_entry is not None:
            print(f"[CommandCache] [S2-fuzzy] score={best_score:.2f} → {best_entry.pattern!r}")
            return best_entry, best_score

        return None

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
        """동적 캐싱 비활성화 (파라미터 오염 문제)."""
        pass

    def increment_hit(self, pattern: str):
        if pattern in self._cache:
            self._cache[pattern].hit_count += 1
            self._persist()

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
