"""
파일시스템 도구
파일/폴더 생성, 파일 탐색, 최근 파일 열기
"""

import os
import re
import glob
import difflib
import subprocess
from datetime import datetime
from langchain_core.tools import tool


# 지원하는 위치 매핑
LOCATION_MAP: dict[str, str] = {
    "desktop":   os.path.join(os.path.expanduser("~"), "Desktop"),
    "바탕화면":   os.path.join(os.path.expanduser("~"), "Desktop"),
    "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
    "다운로드":   os.path.join(os.path.expanduser("~"), "Downloads"),
    "documents": os.path.join(os.path.expanduser("~"), "Documents"),
    "문서":       os.path.join(os.path.expanduser("~"), "Documents"),
    "pictures":  os.path.join(os.path.expanduser("~"), "Pictures"),
    "사진":       os.path.join(os.path.expanduser("~"), "Pictures"),
    "home":      os.path.expanduser("~"),
    "홈":         os.path.expanduser("~"),
}


def _resolve_location(location: str) -> str | None:
    """위치 문자열을 실제 경로로 변환.
    지원 형식:
    - "바탕화면", "desktop" 등 키워드
    - "C:/..." 절대 경로 (존재 여부 무관)
    - "바탕화면/서브폴더", "desktop/subfolder" 형식
    """
    key = location.lower().strip()
    path = LOCATION_MAP.get(key)
    if path:
        return path
    # 절대 경로면 그대로 사용 (존재하지 않아도 반환 — create_file/folder가 생성)
    if os.path.isabs(location):
        return location
    # "바탕화면/서브폴더" 형식 처리
    parts = location.replace("\\", "/").split("/", 1)
    if len(parts) == 2:
        base = LOCATION_MAP.get(parts[0].lower().strip())
        if base:
            return os.path.join(base, parts[1])
    return None


@tool
def create_file(name: str, location: str = "desktop", content: str = "") -> str:
    """
    파일을 생성합니다.
    name: 파일명 (확장자 포함, 예: 메모.txt, 보고서.docx)
    location: 저장 위치 — 기본 바탕화면
      · 키워드: desktop/바탕화면, downloads/다운로드, documents/문서
      · 서브폴더: "바탕화면/폴더명" 형식 가능 (예: "바탕화면/프로젝트", "downloads/새폴더")
    content: 파일 내용 (선택, 기본 빈 파일)
    """
    base = _resolve_location(location)
    if not base:
        return f"✗ '{location}'은(는) 지원하지 않는 위치입니다. (desktop, downloads, documents 중 선택)"

    # LLM02: 비밀/자격증명 파일명으로 생성(덮어쓰기) 차단
    if _is_secret_path(name):
        return _SECRET_REFUSE

    path = os.path.join(base, name)
    try:
        os.makedirs(os.path.dirname(path) or base, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✓ '{name}' 파일을 {location}에 생성했습니다.\n경로: {path}"
    except Exception as e:
        return f"✗ 파일 생성 실패: {e}"


@tool
def create_folder(name: str, location: str = "desktop") -> str:
    """
    폴더를 생성합니다.
    name: 폴더명
    location: 위치 (desktop, downloads, documents) — 기본 바탕화면
    """
    base = _resolve_location(location)
    if not base:
        return f"✗ '{location}'은(는) 지원하지 않는 위치입니다."

    path = os.path.join(base, name)
    try:
        os.makedirs(path, exist_ok=True)
        return f"✓ '{name}' 폴더를 {location}에 생성했습니다.\n경로: {path}"
    except Exception as e:
        return f"✗ 폴더 생성 실패: {e}"


# ── 파일 찾기 (BL-07) ────────────────────────────────────────────
#
# 2026-09-02 실기에서 이게 «UX»가 아니라 **기능 구멍**이라는 게 드러났다:
# 사용자는 폴더를 '학교 문서'로 기억했는데 실제 이름은 '학교문'이었고,
# `glob("*학교 문서*")`는 0건이라 요청이 계속 "없어요"로 끝났다.
#
# **2026-09-10에 무엇이 실제로 막고 있었는지 쟀다**(오기억 16쌍 평가셋):
#
#   현행 glob (공백 그대로)      긍정 3/8
#   공백·구분자만 걷어내면       긍정 7/8 · **오매칭 0**      ← 이게 대부분이었다
#   difflib 0.70                긍정 6/8 · 오매칭 0
#
# 즉 **막고 있던 건 근사 매칭의 부재가 아니라 띄어쓰기였다.**
# difflib를 «실행»에 쓰지 않는 이유도 여기서 나온다 — 정규화 매칭보다 성적이
# 나쁘고, 마진이 좁다(`이력서`↔`이론서.pdf`가 0.667로 임계 0.70에 붙어 있다).
# 그래서 difflib는 **아무것도 못 찾았을 때 «혹시 이건가요» 제안**으로만 쓴다.
# 틀려도 사고가 아니고, 고르는 건 사용자다.
# (임베딩 캐시 ADR §6-3에서 «실행을 결정하는 데는 쓰지 않는다»고 정한 것과 같은 모양)
#
# ⚠️ 평가셋 16쌍은 **내가 만든 것**이라 과적합일 수 있다. 다만 ①의 이득
#    (3/8 → 7/8)은 띄어쓰기 정규화라는 **기계적인 이유**에서 나오므로
#    새로운 오기억 패턴에도 그대로 간다. difflib 쪽 숫자는 덜 믿는다.

_FIND_ORDER = ("desktop", "downloads", "documents")   # 다른 위치를 훑는 순서
_MAX_SCAN = 200_000                                   # 폭주 방지 (실측: 바탕화면 5.3만)


def _norm_name(s: str) -> str:
    """비교용 정규화 — 확장자·공백·구분자를 걷어내고 소문자로.

    '학교 문서' 와 '학교문서', '개발착수서' 와 '개발_착수서.hwp' 를 같게 본다.
    **이 한 줄이 긍정 3/8 → 7/8 을 만든다.**
    """
    if "." in s[1:]:
        s = s.rsplit(".", 1)[0]
    return re.sub(r"[\s_\-()\[\]]+", "", s).lower()


# ── 한글 음차 → 알파벳 (D-01a, 2026-09-14) ──────────────────────────────
# 음성으로 영문 파일명을 부르면 STT는 **소리 나는 대로** 준다 — `a.txt` 가
# «에이점 티엑스티» 로 온다. STT는 제 일을 한 것이다(사람이 그렇게 말했다).
# 1차 리허설 D-01에서 나왔다: *"발음만 듣고 제대로 못 알아들어서 잘못 찾아."*
#
# 🚨 **치환하지 않고 후보를 «더한다».** '오이.jpg' 의 '오이'는 음차로 읽으면
#   오(o)+이(e) = 'oe' 다 — 치환하면 **멀쩡히 되던 매칭이 죽는다.** 원문 키를
#   언제나 먼저 두고 음차 키를 뒤에 붙여 **하나라도 맞으면 맞은 것**으로 본다.
#   그래서 이 기능은 **잃는 것이 없다** — 오변환도 무해하다.
#
# 🚨 **전부 쪼개져야만 변환한다.** '이력서'는 이(e) 다음 '력서'가 남으므로
#   음차가 아니다 → 후보를 안 만든다. 한 조각이라도 남으면 통째로 버린다.
#   (부분 변환을 허용하면 한국어 파일명 대부분이 알파벳 쓰레기가 된다)
#
# 🚨 **두 조각 이상일 때만 변환한다.** 홑음절 letter-name이 하필 전부 흔한
#   한국어 낱말이다 — 이·오·비·시·지·디·티·피·유·엘·엠·엔·알·큐.
#   '비' 하나를 'b'로 읽으면 이름에 b가 든 **모든 파일**이 걸린다.
_KO_PIECES = {
    "에이": "a", "비": "b", "씨": "c", "시": "c", "디": "d", "이": "e",
    "에프": "f", "지": "g", "에이치": "h", "아이": "i", "제이": "j",
    "케이": "k", "엘": "l", "엠": "m", "엔": "n", "오": "o", "피": "p",
    "큐": "q", "알": "r", "아르": "r", "에스": "s", "티": "t", "유": "u",
    "브이": "v", "더블유": "w", "더블류": "w", "엑스": "x", "와이": "y",
    "제트": "z", "지트": "z",
    "점": ".", "닷": ".",            # "에이**점**티엑스티"
}
# 긴 것부터 — '에이치'가 '에이'+'치'로 쪼개지면 안 된다.
_KO_PIECE_KEYS = sorted(_KO_PIECES, key=len, reverse=True)
_KO_MIN_PIECES = 2


def _romanize_ko(s: str, min_pieces: int = _KO_MIN_PIECES) -> str | None:
    """«에이점 티엑스티» → 'a.txt'. 음차가 아니면 **None**(후보를 안 만든다).

    반환이 None이어도 부르는 쪽은 원문으로 그대로 찾는다 — 이 함수는
    더할 후보가 있는지만 답한다.

    ⚠️ `min_pieces`를 **기본값보다 낮춰 부르는 곳은 `_match_in` 하나뿐이다.**
      문턱이 존재하는 이유(홑음절 letter-name이 전부 흔한 한국어 낱말이다)는
      그대로 유효하다 — 낮춰도 되는 조건은 거기에 적어 뒀다.
    """
    t = re.sub(r"\s+", "", s)
    if not t or not re.search(r"[가-힣]", t):
        return None                      # 한글이 없으면 음차일 수가 없다
    out: list[str] = []
    i = pieces = 0
    while i < len(t):
        ch = t[i]
        if ch.isascii() and (ch.isalnum() or ch in "._-"):
            out.append(ch)               # '에이점 txt' 처럼 섞여 올 수 있다
            i += 1
            continue
        for k in _KO_PIECE_KEYS:
            if t.startswith(k, i):
                out.append(_KO_PIECES[k])
                i += len(k)
                pieces += 1
                break
        else:
            return None                  # 한 조각이라도 남으면 음차가 아니다
    if pieces < min_pieces:
        return None
    return "".join(out)


def _alts(s: str) -> list[str]:
    """원문 + 음차 후보. **원문이 언제나 첫 번째다**(빠른 경로를 지키려고)."""
    if not s:
        return []
    out = [s]
    r = _romanize_ko(s)
    if r and r not in out:
        out.append(r)
    return out


def _walk_names(base: str, include_dirs: bool = False) -> list[str]:
    """base 아래 모든 파일의 전체 경로. (비밀 파일은 애초에 담지 않는다)

    include_dirs=True면 **폴더도** 담는다 — 근사 제안 전용이다(§_near_misses).
    """
    out: list[str] = []
    for root, dirs, files in os.walk(base):
        for f in files:
            p = os.path.join(root, f)
            if not _is_secret_path(p):
                out.append(p)
        if include_dirs:
            for d in dirs:
                p = os.path.join(root, d)
                if not _is_secret_path(p):
                    out.append(p)
        if len(out) >= _MAX_SCAN:
            break
    return out


def _match_in(base: str, name: str, extension: str) -> list[str]:
    """한 위치에서 찾는다. 빠른 glob 먼저, 안 되면 정규화 비교.

    ⚠️ 순서가 중요하다 — glob은 다운로드 6개에서 0.002초다.
      대부분의 요청이 여기서 끝나므로 **느린 경로를 기본으로 만들지 않는다.**
    """
    if not os.path.isdir(base):
        return []

    if not name and not extension:
        return []

    # 음차 후보를 더한다 — **원문 조합이 언제나 먼저** 돈다(D-01a).
    name_alts = _alts(name) or [""]
    ext_alts = _alts(extension) or [""]

    # 🚨 **조각이 name/extension으로 갈라져 오면 양쪽 다 문턱에 걸린다 (D-01a).**
    #   *"에이점 티엑스티 찾아줘"* 를 LLM이 한 덩어리(`name='에이점 티엑스티'`)로
    #   주면 위 후보가 'a.txt'를 만들어 낸다. 그런데 **점을 구분자로 읽어**
    #   `name='에이'` · `extension='티엑스티'`(또는 이미 `'txt'`)로 나눠 주면
    #   `_romanize_ko('에이')`는 조각이 하나뿐이라 **None**이다 —
    #   홑음절 letter-name('비'·'이'·'오'…)을 막는 그 문턱이다.
    #   실측으로 이 갈래에서 `a.txt`를 **못 찾았다**(2026-09-16).
    #
    #   그래서 여기서만 문턱을 1로 낮춘다. 낮춰도 되는 근거는 **조건**에 있다:
    #   ① `extension`이 따로 왔다는 것 자체가 «파일명 전체를 불러 줬다»는 신호고,
    #   ② 이 후보는 **원문 조합이 전부 빗나간 뒤에만** 돈다(아래 순서).
    #   그래서 '비.pdf'라는 한국어 파일이 있으면 그쪽이 **먼저** 잡힌다.
    #   ③ 느린 2차(정규화 비교)에는 **넣지 않는다** — 거기는 순서가 없어서
    #      'b'가 이름에 b가 든 파일을 한꺼번에 끌어온다.
    split_pairs: list[tuple[str, str]] = []
    if name and extension:
        rn = _romanize_ko(name, min_pieces=1)
        if rn:
            for ex in ext_alts:
                if ex and (rn, ex) not in split_pairs:
                    split_pairs.append((rn, ex))

    pairs = [(nm, ex) for nm in name_alts for ex in ext_alts] + split_pairs
    for nm, ex in pairs:
        if nm and ex:
            pattern = f"*{nm}*.{ex}"
        elif nm:
            pattern = f"*{nm}*"
        elif ex:
            pattern = f"*.{ex}"
        else:
            continue
        hits = [m for m in glob.glob(os.path.join(base, "**", pattern), recursive=True)
                if not _is_secret_path(m)]
        if hits:
            return hits

    # 2차 — 띄어쓰기·구분자를 걷어내고 다시 본다 (실측: 여기가 대부분을 잡는다)
    if not name:
        return []
    keys = []
    for nm in name_alts:
        k = _norm_name(nm)
        if k and k not in keys:
            keys.append(k)
    if not keys:
        return []
    exts = [e.lower().lstrip(".") for e in ext_alts if e]
    out = []
    for p in _walk_names(base):
        b = os.path.basename(p)
        if exts and not any(b.lower().endswith("." + e) for e in exts):
            continue
        nb = _norm_name(b)
        if any(k in nb for k in keys):
            out.append(p)
    return out


def _near_misses(name: str, bases: list[str], limit: int = 3) -> list[str]:
    """아무것도 못 찾았을 때의 «혹시 이건가요» 후보.

    ⚠️ **제안이지 답이 아니다.** 실행에 쓰지 않는다 — 위 주석의 마진 이야기 참조.

    ⚠️ **폴더도 넣는다.** BL-07 원문 사례('학교 문서' → '학교문')가 하필 폴더였다.
      결과 목록에는 안 넣는다(이 도구의 계약은 «파일 탐색»이다) — 제안에만 넣고
      «(폴더)»라고 밝혀서, 사용자가 다음에 무엇을 할지 알 수 있게 한다.
      *"왜 없는지 확인할 방법이 없었다"* 가 BL-07의 원래 불평이었다.
    """
    if not name:
        return []
    keys = []
    for nm in _alts(name):             # 음차 후보도 «혹시 이건가요»에 태운다
        k = _norm_name(nm)
        if k and k not in keys:
            keys.append(k)
    if not keys:
        return []
    pool: dict[str, str] = {}          # 정규화 이름 → 보여줄 이름 (중복 제거)
    for base in bases:
        if not os.path.isdir(base):
            continue
        for p in _walk_names(base, include_dirs=True):
            label = os.path.basename(p)
            if os.path.isdir(p):
                label += " (폴더)"
            pool.setdefault(_norm_name(os.path.basename(p)), label)
    names = list(pool)
    close: list[str] = []
    for k in keys:                     # 원문 후보가 먼저 자리를 잡는다
        for c in difflib.get_close_matches(k, names, n=limit, cutoff=0.70):
            if c not in close:
                close.append(c)
    return [pool[c] for c in close[:limit]]


@tool
def find_file(name: str = "", extension: str = "", location: str = "") -> str:
    """
    파일을 탐색합니다. 이름을 정확히 몰라도 됩니다.
    띄어쓰기가 달라도("학교 문서" ↔ "학교문서") 찾고, 위치를 안 주면
    바탕화면·다운로드·문서를 차례로 훑습니다.
    name: 파일명 또는 키워드 (선택)
    extension: 확장자 (예: pdf, txt, docx) — **모르면 비워 두세요.**
               지어내지 마세요. 확장자를 주고 못 찾으면 빼고 다시 찾습니다.
    location: 탐색 위치 (desktop, downloads, documents) — 비우면 전부
    """
    if not name and not extension:
        return "✗ 파일명 또는 확장자를 알려주세요."

    # 어디를 볼 것인가. 위치를 줬으면 거기부터, 그 다음 나머지.
    if location:
        base = _resolve_location(location)
        if not base:
            return f"✗ '{location}'은(는) 지원하지 않는 위치입니다."
        ordered = [(location, base)]
        seen = {os.path.normcase(base)}
        for k in _FIND_ORDER:
            p = LOCATION_MAP[k]
            if os.path.normcase(p) not in seen:
                ordered.append((k, p))
                seen.add(os.path.normcase(p))
    else:
        ordered = [(k, LOCATION_MAP[k]) for k in _FIND_ORDER]

    # 1차: 준 조건 그대로. 2차: 확장자를 빼고 (LLM이 확장자를 지어냈을 수 있다)
    for attempt, ext in enumerate((extension, "") if extension else (extension,)):
        for idx, (loc_name, base) in enumerate(ordered):
            hits = _match_in(base, name, ext)
            if not hits:
                continue

            head = f"✓ {len(hits)}개 파일을 찾았습니다"
            notes = []
            # **한 일은 반드시 말한다** — 사용자가 시킨 곳이 아닌 데서 찾았으면
            # 그걸 밝히지 않으면 다음 명령("그거 지워줘")이 엉뚱한 걸 가리킨다.
            if location and idx > 0:
                notes.append(f"'{location}'이 아니라 '{loc_name}'에서")
            elif not location:
                notes.append(f"'{loc_name}'에서")
            if attempt > 0:
                notes.append(f"확장자 '{extension}'로는 못 찾아 빼고")
            if notes:
                head += f" ({' · '.join(notes)} 찾았어요)"

            lines = [head + ":"]
            for i, m in enumerate(hits[:10], 1):
                lines.append(f"  {i}. {os.path.basename(m)}")
            if len(hits) > 10:
                lines.append(f"  ... 외 {len(hits) - 10}개")
            return "\n".join(lines)

    # 아무 데도 없다. 여기서 그냥 끝내면 사용자는 **다음에 뭘 할지 모른다** —
    # BL-07이 «없어요»로만 끝나던 바로 그 자리다.
    where = "바탕화면·다운로드·문서" if not location else f"'{location}'과 다른 위치들"
    what = name or extension
    # 조사 하드코딩('을(를)') 금지 — core/graph.py §211의 규칙과 같다.
    # (지연 import: 이 도구는 캐시 모듈 없이도 단독으로 돌아야 한다)
    try:
        from core.command_cache import _select_particle
        eul = _select_particle(what, "을", "를")
    except Exception:
        eul = "을(를)"
    near = _near_misses(name, [b for _, b in ordered])
    if near:
        listed = " · ".join(f"'{n}'" for n in near)
        return (f"✗ {where}에서 '{what}'{eul} 찾지 못했습니다.\n"
                f"  혹시 이건가요? {listed}")
    return (f"✗ {where}에서 '{what}'{eul} 찾지 못했습니다. "
            f"비슷한 이름도 없어요.")


@tool
def list_directory(location: str = "desktop", only: str = "all") -> str:
    """폴더 안에 무엇이 있는지 **이름을 나열**합니다.
    사용자가 정확한 이름을 모를 때("바탕화면에 뭐 있어?", "폴더 목록 보여줘",
    "거기서 내가 고를게") 쓰세요. find_file은 이름이나 확장자를 알아야 하지만
    이 도구는 몰라도 됩니다.
    location: desktop / documents / downloads / pictures 또는 절대경로. 기본 바탕화면.
    only: "all"(기본) / "folders"(폴더만) / "files"(파일만)
    """
    base = _resolve_location(location)
    if not base:
        return f"✗ '{location}'은(는) 지원하지 않는 위치입니다."
    if not os.path.isdir(base):
        return f"✗ '{location}' 폴더가 없습니다: {base}"

    try:
        names = sorted(os.listdir(base), key=str.lower)
    except PermissionError:
        return f"✗ '{location}'을(를) 읽을 권한이 없습니다."

    folders, files = [], []
    for n in names:
        full = os.path.join(base, n)
        # LLM02: 비밀/자격증명 파일은 목록에서도 제외한다 (find_file과 같은 정책)
        if _is_secret_path(full):
            continue
        # 숨김 파일·시스템 파일은 사용자가 말하는 대상이 아니다
        if n.startswith(".") or n.lower() in ("desktop.ini", "thumbs.db"):
            continue
        (folders if os.path.isdir(full) else files).append(n)

    want = (only or "all").lower().strip()
    if want == "folders":
        groups = [("폴더", folders)]
    elif want == "files":
        groups = [("파일", files)]
    else:
        groups = [("폴더", folders), ("파일", files)]

    if not any(items for _, items in groups):
        return f"✓ '{location}'에 표시할 항목이 없습니다."

    LIMIT = 40   # 음성으로 읽어주기엔 이것도 많다. 넘으면 개수만 알린다.
    out = [f"✓ {location} 목록:"]
    for label, items in groups:
        if not items:
            continue
        out.append(f"[{label} {len(items)}개]")
        for n in items[:LIMIT]:
            out.append(f"  - {n}")
        if len(items) > LIMIT:
            out.append(f"  ... 외 {len(items) - LIMIT}개")
    return "\n".join(out)


@tool
def open_recent_file() -> str:
    """
    최근에 열었던 파일 목록을 보여주고 탐색기로 최근 파일 폴더를 엽니다.
    """
    recent_path = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft", "Windows", "Recent"
    )
    try:
        subprocess.Popen(["explorer", recent_path])
        return f"✓ 최근 파일 폴더를 열었습니다."
    except Exception as e:
        return f"✗ 최근 파일 열기 실패: {e}"


@tool
def open_file(file_path: str, app: str = "") -> str:
    """
    파일을 기본 앱 또는 지정한 앱으로 엽니다.
    파일 경로가 있을 때 사용합니다. 앱만 실행(파일 없이)할 때는 open_app을 사용하세요.
    "파일 만들고 메모장으로 열어줘" → create_file() 후 open_file(file_path="파일명", app="notepad")
    "todo.txt를 메모장으로 열어줘" → open_file(file_path="todo.txt", app="notepad")
    file_path: 파일 경로 또는 파일명 (바탕화면·문서·다운로드 상대경로 가능)
               예: "메모.txt", "바탕화면/보고서.docx", "C:/Users/user/Desktop/todo.txt"
    app: 열 앱 이름 (예: notepad, chrome, excel). 비워두면 기본 앱으로 열기.
    """
    # 상대 경로 해석 (바탕화면, 문서, 다운로드)
    resolved = _resolve_location_in_path(file_path)

    # LLM02: 비밀/자격증명 파일 접근 차단
    if _is_secret_path(resolved):
        return _SECRET_REFUSE

    # BL-31 — 여기서 그냥 «없습니다»로 끝내면 **find_file이 방금 찾은 파일을
    # 못 여는** 일이 난다. 두 도구의 계약이 어긋나 있었다:
    #   find_file  : glob(base/**/…, recursive=True)  → 하위 폴더까지 본다
    #   open_file  : os.path.join(base, file_path)    → 바로 아래 한 겹만 본다
    # 그래서 못 찾았을 때만 **find_file과 같은 탐색을 한 번** 한다.
    found_note = ""
    if not os.path.exists(resolved):
        hits = _locate_for_open(file_path)
        if len(hits) == 1:
            loc, path = hits[0]
            # 탐색으로 새로 얻은 경로다 — 비밀 파일 판정을 **다시** 통과시킨다.
            # (_match_in도 거르지만, 관문을 우회하는 입구를 만들지 않는다)
            if _is_secret_path(path):
                return _SECRET_REFUSE
            resolved = path
            found_note = _where_note(loc, path)
        elif len(hits) > 1:
            # **열지 않는다.** 무엇을 여는지 사용자가 정해야 한다.
            lines = [f"✗ '{os.path.basename(file_path)}' 이름이 여러 개라 "
                     f"어느 것인지 몰라 열지 않았습니다:"]
            for i, (loc, p) in enumerate(hits[:5], 1):
                lines.append(f"  {i}. {os.path.basename(p)} {_where_note(loc, p)}")
            if len(hits) > 5:
                lines.append(f"  ... 외 {len(hits) - 5}개")
            return "\n".join(lines)
        else:
            return f"✗ 파일을 찾을 수 없습니다: {resolved}"

    try:
        if app:
            # 앱 이름으로 실행 파일 찾기
            from tools.app_control import _normalize, APP_PROCESS_MAP, _resolve_path
            app_key = _normalize(app)
            exe_list = APP_PROCESS_MAP.get(app_key, [f"{app_key}.exe"])

            # 직접 exe 이름으로 시도
            import shutil
            exe_name = exe_list[0]
            exe_path = shutil.which(exe_name) or _resolve_path(app_key)

            if exe_path:
                subprocess.Popen([exe_path, resolved])
            else:
                # fallback: shell 명령
                subprocess.Popen([exe_name, resolved], shell=True)
        else:
            os.startfile(resolved)

        # **한 일은 반드시 말한다** — 시킨 경로가 아닌 데서 찾아 열었으면
        # 그걸 밝히지 않으면 다음 명령("그거 지워줘")이 엉뚱한 걸 가리킨다.
        # (find_file이 «어디서 찾았는지»를 말하는 것과 같은 규칙)
        return f"✓ '{os.path.basename(resolved)}' 파일을 열었습니다.{found_note}"
    except Exception as e:
        return f"✗ 파일 열기 실패: {e}"


def _resolve_location_in_path(file_path: str) -> str:
    """경로 문자열을 실제 경로로 변환. 상대 위치명(바탕화면 등) 처리."""
    if os.path.isabs(file_path):
        return file_path

    parts = file_path.replace("\\", "/").split("/", 1)
    if len(parts) == 2:
        base = _resolve_location(parts[0])
        if base:
            return os.path.join(base, parts[1])

    for loc in ["바탕화면", "문서", "다운로드"]:
        base = _resolve_location(loc)
        if base:
            candidate = os.path.join(base, file_path)
            if os.path.exists(candidate):
                return candidate

    return file_path


def _where_note(loc: str, path: str) -> str:
    """«어디서 찾았는지» 한 조각. 절대경로는 내보내지 않는다.

    사용자 이름이 든 전체 경로(`C:/Users/…`)를 응답에 실으면 개인정보가 섞이고
    TTS로도 읽힌다. 기준 폴더 이름 + 그 아래 상대경로까지만 말한다.
    """
    base = LOCATION_MAP.get(loc)
    if not base:
        return ""
    try:
        rel = os.path.relpath(os.path.dirname(path), base)
    except ValueError:      # 드라이브가 다르면 relpath가 실패한다
        return f" ('{loc}'에서 찾았어요)"
    if rel in (".", ""):
        return f" ('{loc}'에서 찾았어요)"
    return f" ('{loc}/{rel.replace(os.sep, '/')}'에서 찾았어요)"


def _locate_for_open(file_path: str) -> list[tuple[str, str]]:
    """`open_file`이 못 찾았을 때 **find_file과 같은 탐색**을 한 번 한다 (BL-31).

    반환: `[(위치키, 경로), ...]` — 0개면 없는 것, 2개 이상이면 **부르는 쪽이
    열지 말고 되물어야 한다.**

    🚨 **여는 것에만 쓴다. `delete_file`·`delete_folder`에 붙이지 말 것.**
      여는 것은 되돌릴 수 있지만 지우는 것은 되돌릴 수 없다. 삭제에 재귀 탐색을
      붙이면 *"보고서.docx 지워줘"* 가 **사용자가 생각한 적 없는 하위 폴더의 파일**을
      지운다. 승인 질문은 이름만 보여주므로 사용자는 그게 다른 파일인지 알 수 없다.
      이 비대칭은 실수가 아니라 **의도된 것**이다.
    """
    name = os.path.basename(file_path.replace("\\", "/")).strip()
    if not name:
        return []
    stem, dot_ext = os.path.splitext(name)
    ext = dot_ext.lstrip(".")
    if not stem:            # ".env" 같은 것 — 확장자만 남는 이름은 탐색하지 않는다
        return []

    # find_file과 같은 2패스: 준 확장자로 먼저, 없으면 빼고 다시
    # (LLM이 확장자를 지어냈을 수 있다 — BL-07에서 확인된 실패 양상)
    for use_ext in ((ext, "") if ext else ("",)):
        hits: list[tuple[str, str]] = []
        seen: set[str] = set()
        for loc in _FIND_ORDER:
            base = LOCATION_MAP.get(loc)
            if not base:
                continue
            for m in _match_in(base, stem, use_ext):
                key = os.path.normcase(os.path.abspath(m))
                if key in seen or not os.path.isfile(m):
                    continue        # 폴더는 열지 않는다 — 이 도구의 계약은 «파일»이다
                seen.add(key)
                hits.append((loc, m))
        if hits:
            return hits
    return []


@tool
def write_excel(filename: str, headers: str, rows: str, location: str = "desktop") -> str:
    """
    엑셀(.xlsx) 파일을 생성합니다. 검색·비교 데이터를 표 형식으로 저장할 때 사용합니다.
    filename: 파일명 (예: 에어컨비교.xlsx)
    headers: 열 제목, 쉼표로 구분 (예: "모델명,가격,용량,에너지효율등급")
    rows: 행 데이터. 행은 줄바꿈(\\n)으로, 열은 쉼표로 구분.
          (예: "삼성 무풍 에어컨,1200000원,18평형,1등급\\nLG 휘센,1100000원,16평형,1등급")
    location: 저장 위치 (desktop/바탕화면, downloads/다운로드, documents/문서)
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return "✗ write_excel 사용을 위해 openpyxl이 필요합니다. (pip install openpyxl)"

    base = _resolve_location(location)
    if not base:
        return f"✗ '{location}'은(는) 지원하지 않는 위치입니다."

    if not filename.endswith(".xlsx"):
        filename += ".xlsx"
    path = os.path.join(base, filename)

    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "데이터"

        # 헤더 행
        header_list = [h.strip() for h in headers.split(",")]
        ws.append(header_list)

        # 헤더 스타일 (파란 배경 + 흰 글씨)
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        # 데이터 행
        for line in rows.strip().splitlines():
            if line.strip():
                ws.append([col.strip() for col in line.split(",")])

        # 열 너비 자동 조정
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        os.makedirs(base, exist_ok=True)
        wb.save(path)
        return f"✓ '{filename}' 엑셀 파일을 저장했습니다.\n경로: {path}"

    except Exception as e:
        return f"✗ 엑셀 파일 생성 실패: {e}"


# ── 위험 동작: 삭제 (HITL 승인 대상) ──────────────────────────────
# 이 도구들은 절대 캐시/라우터로 처리하지 않고, 그래프 hitl 노드에서
# 사용자 승인을 받은 뒤에만 실행된다 (P2).

_PROTECTED_SUBSTR = ("\\windows", "/windows", "system32", "syswow64",
                     "\\program files", "/program files")


_DRIVE_ROOT_RE = re.compile(r'^[a-zA-Z]:[\\/]?$')   # C:  C:\  C:/


def _is_protected_path(path: str) -> bool:
    """시스템/보호 경로 또는 드라이브 루트면 True (삭제 금지)."""
    raw = (path or "").strip()
    if _DRIVE_ROOT_RE.match(raw):       # 드라이브 루트 (플랫폼 무관)
        return True
    p = os.path.abspath(path)
    drive, tail = os.path.splitdrive(p)
    if tail in ("", "\\", "/"):         # 드라이브 루트(Windows)
        return True
    low = p.lower()
    return any(s in low for s in _PROTECTED_SUBSTR)


# ── 비밀 파일 접근 차단 (OWASP LLM02) ─────────────────────────────
_SECRET_NAME_RE = re.compile(
    r'(^\.env(\.|$)|credential|secret|passwd|password|id_rsa|\.pem$|\.key$|\.pfx$|'
    r'apikey|api_key|_token\.json$|token\.json$)', re.IGNORECASE)


def _is_secret_path(path: str) -> bool:
    """비밀/자격증명 파일(.env, token.json, credentials 등)이면 True."""
    base = os.path.basename((path or "").replace("\\", "/")).strip().lower()
    return bool(_SECRET_NAME_RE.search(base))


_SECRET_REFUSE = "✗ 보안상 비밀/설정 파일(.env, 토큰, 자격증명 등)은 접근할 수 없어요."


def _to_trash(path: str) -> str:
    """가능하면 휴지통으로 이동, 실패 시 영구 삭제. 방식('trash'|'permanent') 반환."""
    try:
        from send2trash import send2trash as _s2t
        _s2t(path)
        return "trash"
    except Exception:
        if os.path.isdir(path):
            import shutil
            shutil.rmtree(path)
        else:
            os.remove(path)
        return "permanent"


@tool
def delete_file(file_path: str) -> str:
    """파일을 삭제합니다(가능하면 휴지통으로 이동). 되돌리기 어려운 위험 동작이라
    반드시 사용자 승인을 받은 뒤 실행됩니다.
    file_path: 파일 경로 또는 상대경로(바탕화면/문서/다운로드).
    """
    resolved = _resolve_location_in_path(file_path)
    if not os.path.exists(resolved):
        return f"✗ 파일을 찾을 수 없습니다: {resolved}"
    if os.path.isdir(resolved):
        return f"✗ '{os.path.basename(resolved)}'은(는) 폴더예요. 폴더는 delete_folder를 쓰세요."
    if _is_protected_path(resolved):
        return "✗ 시스템/보호 경로의 파일은 삭제할 수 없어요."
    if _is_secret_path(resolved):
        return _SECRET_REFUSE
    try:
        how = _to_trash(resolved)
        where = "휴지통으로 옮겼어요" if how == "trash" else "삭제했어요"
        return f"✓ '{os.path.basename(resolved)}' {where}."
    except Exception as e:
        return f"✗ 삭제 실패: {e}"


@tool
def delete_folder(folder_path: str) -> str:
    """폴더를 삭제합니다(가능하면 휴지통으로 이동). 되돌리기 어려운 위험 동작이라
    반드시 사용자 승인을 받은 뒤 실행됩니다.
    folder_path: 폴더 경로 또는 상대경로(바탕화면/문서/다운로드).
    """
    resolved = _resolve_location_in_path(folder_path)
    if not os.path.exists(resolved):
        return f"✗ 폴더를 찾을 수 없습니다: {resolved}"
    if not os.path.isdir(resolved):
        return f"✗ '{os.path.basename(resolved)}'은(는) 파일이에요. delete_file을 쓰세요."
    if _is_protected_path(resolved):
        return "✗ 시스템/보호 경로의 폴더는 삭제할 수 없어요."
    try:
        how = _to_trash(resolved)
        where = "휴지통으로 옮겼어요" if how == "trash" else "삭제했어요"
        return f"✓ '{os.path.basename(resolved)}' 폴더를 {where}."
    except Exception as e:
        return f"✗ 삭제 실패: {e}"
