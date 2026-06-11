"""
Pluiz 오프라인 커맨드 캐시
--------------------------
자주 쓰는 명령을 LLM API 없이 직접 실행.

구조:
- JSON 파일로 영속 저장 (cache/command_cache.json)
- 명령 패턴 → 도구 시퀀스 매핑
- API 호출 성공 시 자동 캐싱 (에이전트 run_async에서 호출)
- 퍼지 매칭: difflib.SequenceMatcher (유사도 0.80 이상 히트)
- 30+ 시드 데이터 사전 등록
"""

import json
import os
import re
import asyncio
from dataclasses import dataclass, asdict, field
from difflib import SequenceMatcher
from typing import Optional

# 캐시 파일 경로
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(_BASE_DIR, "cache", "command_cache.json")

# 캐시 히트 유사도 임계값
SIMILARITY_THRESHOLD = 0.80


# ── 데이터 구조 ───────────────────────────────────────────────────

@dataclass
class CacheEntry:
    pattern: str            # 정규화된 입력 패턴 (키)
    tool_calls: list        # [{"name": str, "args": dict}, ...]
    response_template: str  # 캐시된 응답 텍스트
    hit_count: int = 0
    is_seed: bool = False   # 시드 데이터 여부


# ── 시드 데이터 (30+ 자주 쓰는 명령) ─────────────────────────────

SEED_DATA: list[tuple[str, list, str]] = [
    # (패턴, 도구 시퀀스, 응답 템플릿)

    # ── 앱 제어 ───────────────────────────────────────────────────
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
    ("설정 열어줘",        [{"name": "open_app", "args": {"app": "설정"}}],          "✓ 설정을 열었습니다."),
    ("카카오톡 열어줘",    [{"name": "open_app", "args": {"app": "카카오톡"}}],      "✓ 카카오톡을 실행했습니다."),

    # ── 시스템 제어 ───────────────────────────────────────────────
    ("볼륨 올려줘",         [{"name": "volume_up", "args": {}}],           "✓ 볼륨을 높였습니다."),
    ("소리 올려줘",         [{"name": "volume_up", "args": {}}],           "✓ 볼륨을 높였습니다."),
    ("볼륨 내려줘",         [{"name": "volume_down", "args": {}}],         "✓ 볼륨을 낮췄습니다."),
    ("소리 내려줘",         [{"name": "volume_down", "args": {}}],         "✓ 볼륨을 낮췄습니다."),
    ("음소거해줘",          [{"name": "mute_toggle", "args": {}}],         "✓ 음소거 상태를 변경했습니다."),
    ("음소거 해줘",         [{"name": "mute_toggle", "args": {}}],         "✓ 음소거 상태를 변경했습니다."),
    ("밝기 올려줘",         [{"name": "brightness_up", "args": {}}],       "✓ 화면 밝기를 높였습니다."),
    ("화면 밝게 해줘",      [{"name": "brightness_up", "args": {}}],       "✓ 화면 밝기를 높였습니다."),
    ("밝기 내려줘",         [{"name": "brightness_down", "args": {}}],     "✓ 화면 밝기를 낮췄습니다."),
    ("화면 어둡게 해줘",    [{"name": "brightness_down", "args": {}}],     "✓ 화면 밝기를 낮췄습니다."),
    ("스크린샷 찍어줘",     [{"name": "take_screenshot", "args": {}}],     "✓ 스크린샷을 저장했습니다."),
    ("화면 캡처해줘",       [{"name": "take_screenshot", "args": {}}],     "✓ 스크린샷을 저장했습니다."),
    ("지금 몇 시야",        [{"name": "get_current_time", "args": {}}],    "현재 시각을 확인합니다."),
    ("배터리 얼마나 남았어",[{"name": "get_battery_status", "args": {}}],  "배터리 상태를 확인합니다."),
    ("배터리 확인해줘",     [{"name": "get_battery_status", "args": {}}],  "배터리 상태를 확인합니다."),
    ("지금 뭐 켜져 있어",   [{"name": "get_running_apps", "args": {}}],    "실행 중인 앱 목록을 확인합니다."),
    ("실행 중인 앱 알려줘", [{"name": "get_running_apps", "args": {}}],    "실행 중인 앱 목록을 확인합니다."),

    # ── 웹 ────────────────────────────────────────────────────────
    ("구글 열어줘",    [{"name": "open_url", "args": {"url": "https://www.google.com"}}],  "✓ Google을 열었습니다."),
    ("유튜브 열어줘",  [{"name": "open_url", "args": {"url": "https://www.youtube.com"}}], "✓ YouTube를 열었습니다."),
    ("네이버 열어줘",  [{"name": "open_url", "args": {"url": "https://www.naver.com"}}],   "✓ Naver를 열었습니다."),
    ("날씨 검색해줘",  [{"name": "web_search", "args": {"query": "오늘 날씨"}}],           "✓ 날씨를 검색했습니다."),

    # ── 파일시스템 ────────────────────────────────────────────────
    ("최근에 열었던 파일 보여줘", [{"name": "open_recent_file", "args": {}}], "최근 파일을 확인합니다."),
]


# ── CommandCache 클래스 ───────────────────────────────────────────

class CommandCache:
    """
    명령 캐시 관리자.

    - 요청 시 find() → 히트 시 execute() → 응답 반환 (API 불필요)
    - 미스 시 LLM 실행 후 save()로 자동 캐싱
    """

    def __init__(self):
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        self._cache: dict[str, CacheEntry] = {}
        self._load()
        self._seed()

    # ── 정규화 ────────────────────────────────────────────────────

    def _normalize(self, text: str) -> str:
        """입력 정규화: 소문자, 공백 통합, 구어체 조사 제거."""
        text = text.strip().lower()
        # 불필요한 어미/조사 정규화
        replacements = [
            ("해 줘", "해줘"), ("열 어줘", "열어줘"), (" 줘", "줘"),
        ]
        for old, new in replacements:
            text = text.replace(old, new)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # ── 퍼지 매칭 ─────────────────────────────────────────────────

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    def find(self, user_input: str) -> Optional[tuple["CacheEntry", float]]:
        """
        유사 명령 검색.

        Returns:
            (CacheEntry, similarity_score) 또는 None
        """
        normalized = self._normalize(user_input)
        best_entry: Optional[CacheEntry] = None
        best_score = 0.0

        for key, entry in self._cache.items():
            score = self._similarity(normalized, key)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_score >= SIMILARITY_THRESHOLD and best_entry is not None:
            return best_entry, best_score
        return None

    # ── 도구 직접 실행 ────────────────────────────────────────────

    async def execute(self, entry: "CacheEntry") -> str:
        """
        캐시 엔트리의 도구 시퀀스를 LLM 없이 직접 실행.

        Returns:
            실행 결과 텍스트 (실패 시 response_template 반환)
        """
        from core.tool_registry import get_all_tools
        tools_map = {t.name: t for t in get_all_tools()}
        results: list[str] = []

        for call in entry.tool_calls:
            name = call.get("name", "")
            args = call.get("args", {})
            if name not in tools_map:
                print(f"[CommandCache] 알 수 없는 도구: {name}")
                continue
            try:
                tool = tools_map[name]
                result = await tool.ainvoke(args)
                results.append(str(result))
            except Exception as e:
                print(f"[CommandCache] 도구 실행 오류 ({name}): {e}")
                results.append(entry.response_template)

        return "\n".join(results) if results else entry.response_template

    # ── 캐싱 ──────────────────────────────────────────────────────

    def save(self, user_input: str, tool_calls: list, response: str):
        """
        새 명령을 캐시에 저장.
        동일 패턴이 이미 있으면 hit_count만 증가.
        """
        if not tool_calls:   # 도구 없이 대화만 한 경우 캐싱 불필요
            return
        key = self._normalize(user_input)
        if key in self._cache:
            self._cache[key].hit_count += 1
        else:
            self._cache[key] = CacheEntry(
                pattern=key,
                tool_calls=tool_calls,
                response_template=response,
                hit_count=0,
                is_seed=False,
            )
        self._persist()

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
                  f"(시드 {len(self._cache) - user_entries}개, 동적 {user_entries}개)")
        except Exception as e:
            print(f"[CommandCache] 로드 실패 (초기화): {e}")
            self._cache = {}

    def _seed(self):
        """시드 데이터 등록 (없는 항목만 추가, 기존 덮어쓰지 않음)."""
        added = 0
        for pattern_text, tool_calls, response in SEED_DATA:
            key = self._normalize(pattern_text)
            if key not in self._cache:
                self._cache[key] = CacheEntry(
                    pattern=key,
                    tool_calls=tool_calls,
                    response_template=response,
                    hit_count=0,
                    is_seed=True,
                )
                added += 1
        if added:
            print(f"[CommandCache] 시드 데이터 {added}개 추가")
            self._persist()

    @property
    def size(self) -> int:
        return len(self._cache)


# ── 헬퍼: LangGraph 메시지에서 도구 호출 추출 ───────────────────

def extract_tool_calls_from_messages(messages: list) -> list[dict]:
    """
    LangGraph ainvoke 결과 메시지 목록에서 도구 호출 정보 추출.

    Args:
        messages: result["messages"] 리스트

    Returns:
        [{"name": str, "args": dict}, ...]
    """
    calls: list[dict] = []
    for msg in messages:
        tc_list = getattr(msg, "tool_calls", None)
        if not tc_list:
            continue
        for tc in tc_list:
            if isinstance(tc, dict):
                calls.append({"name": tc.get("name", ""), "args": tc.get("args", {})})
            else:
                # LangChain ToolCall 객체
                calls.append({"name": getattr(tc, "name", ""), "args": getattr(tc, "args", {})})
    return calls


# ── 싱글턴 ───────────────────────────────────────────────────────

_cache_instance: Optional[CommandCache] = None


def get_cache() -> CommandCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CommandCache()
    return _cache_instance
