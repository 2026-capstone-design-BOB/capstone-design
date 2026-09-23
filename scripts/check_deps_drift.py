"""
의존성 표류 점검 — `requirements.lock.txt`에 고정된 버전 vs PyPI 최신
=====================================================================
`docs/research/`의 **월간 동향 점검 ② 프레임워크** 항목을 자동으로 채운다.

왜 있나
-------
AI Agent 프레임워크는 개념이 빨리 바뀌고, 이 프로젝트는 그걸 **손으로 추적하지
않기로** 했다. 매달 사람이 릴리스 노트를 뒤지면 어느 달엔가 안 하고, 안 한 달은
기록이 비고, 기록이 비면 *"동향을 추적했다"* 가 말로만 남는다.

**이 스크립트는 «무엇이 얼마나 벌어졌나»만 말한다.** *«그래서 올릴 것인가»* 는
사람이 판단하고 `docs/research/`에 **안 올렸으면 왜 안 올렸는지**까지 적는다.
그 «안 했으면 왜»가 졸작 「SW 품질·유지보수성」의 재료다.

쓰는 법
-------
    python scripts/check_deps_drift.py            # 핵심 패키지만 (기본)
    python scripts/check_deps_drift.py --all      # lock 전체
    python scripts/check_deps_drift.py --md       # 마크다운 표 (문서에 붙여넣기용)

⚠️ 네트워크가 필요하다. 끊겨 있으면 그 패키지는 `?`로 남고 스크립트는 죽지 않는다 —
   점검이 안 되는 것과 도구가 깨지는 것은 다르다.
⚠️ `scripts/`는 서버 코드가 import 하지 않는다(STRUCTURE.md § scripts). stdlib만 쓴다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, "requirements.lock.txt")

# 핵심 = 이게 흔들리면 에이전트가 흔들리는 것들. 나머지 200여 개는 --all로 본다.
# (동향 점검에서 매달 같은 것을 봐야 «변화»가 눈에 띈다 — 그래서 목록을 고정한다)
CORE = [
    "langgraph", "langchain-core", "langchain-google-genai", "langchain-anthropic",
    "google-genai", "anthropic", "fastapi", "uvicorn", "pydantic", "pydantic-settings",
    "faster-whisper", "openwakeword", "onnxruntime", "edge-tts",
    "numpy", "pillow", "sounddevice", "psutil", "pyautogui",
]


def read_lock(path: str = LOCK) -> dict[str, str]:
    """`이름==버전`만 뽑는다. 주석·빈 줄·`-e`·URL 설치는 버린다."""
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9._-]+)==([^\s;]+)", line)
            if m:
                out[m.group(1).lower().replace("_", "-")] = m.group(2)
    return out


def latest(name: str, timeout: int = 15) -> str | None:
    """PyPI가 말하는 최신 안정 버전. 실패는 None (점검 실패 ≠ 도구 실패)."""
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)["info"]["version"]
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return None


def _parts(v: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", v)[:3]] or [0]


def drift(pinned: str, newest: str | None) -> str:
    """벌어진 정도. **major가 문제다** — 이 프로젝트가 겪은 게 정확히 그것이다
    (`langgraph>=0.2.0`이라고 적힌 채 1.x가 돌고 있었다)."""
    if newest is None:
        return "?"
    if pinned == newest:
        return "="
    a, b = _parts(pinned), _parts(newest)
    a += [0] * (3 - len(a)); b += [0] * (3 - len(b))
    if b[0] != a[0]:
        return "MAJOR"
    if b[1] != a[1]:
        return "minor"
    return "patch" if b > a else "앞섬"


def main() -> int:
    args = sys.argv[1:]
    as_md = "--md" in args
    lock = read_lock()
    names = sorted(lock) if "--all" in args else [n for n in CORE if n in lock]
    missing = [n for n in CORE if n not in lock] if "--all" not in args else []

    with ThreadPoolExecutor(max_workers=8) as ex:
        newest = dict(zip(names, ex.map(latest, names)))

    rows = [(n, lock[n], newest[n] or "?", drift(lock[n], newest[n])) for n in names]
    rows.sort(key=lambda r: {"MAJOR": 0, "minor": 1, "patch": 2, "?": 3, "=": 4,
                             "앞섬": 5}.get(r[3], 9))

    if as_md:
        print("| 패키지 | 고정(lock) | PyPI 최신 | 차이 |")
        print("|---|---|---|---|")
        for n, p, l, d in rows:
            mark = {"MAJOR": "🔴 ", "minor": "🟡 ", "patch": "", "=": "", "?": "⚪ "}.get(d, "")
            print(f"| `{n}` | {p} | {l} | {mark}{d} |")
    else:
        print(f"의존성 표류 점검 — lock {len(lock)}개 중 {len(rows)}개 확인\n")
        print(f"  {'패키지':<28} {'고정':<14} {'최신':<14} 차이")
        print("  " + "-" * 62)
        for n, p, l, d in rows:
            print(f"  {n:<28} {p:<14} {l:<14} {d}")

    major = [r[0] for r in rows if r[3] == "MAJOR"]
    unk = [r[0] for r in rows if r[3] == "?"]
    print()
    if major:
        print(f"🔴 메이저가 벌어진 것 {len(major)}개: {', '.join(major)}")
        print("   → 올릴지 말지를 정하고, **안 올렸으면 왜인지**를 docs/research/에 적는다.")
    else:
        print("🟢 메이저 차이 없음.")
    if unk:
        print(f"⚪ 확인 못 함(네트워크?): {', '.join(unk)}")
    if missing:
        print(f"⚠️ 핵심 목록에 있는데 lock에 없다: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
