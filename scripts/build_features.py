# -*- coding: utf-8 -*-
"""**전체 기능 설명**을 만든다 — 지금 이 순간 무엇을 할 수 있는가, 전부.

    conda activate pluiz
    python scripts/build_features.py            # docs/전체_기능_설명.html
    python scripts/build_features.py --check    # 낡았는지만 본다

## 🔑 왜 문서가 아니라 **코드**에서 만드나

기능 목록은 **문서로 쓰면 반드시 낡는다.** 실제로 그랬다 —
`docs/meetings/2026-09-11_제품_기능_현황.html` 은 그날의 기능 목록이고,
지금은 도구가 44개에서 67개가 됐다. 그 문서는 **고칠 수 없는 기록**이라 그대로 뒀다.

🔑 **기능의 단일 출처는 `core/tool_registry.py` 다** — 거기 `get_all_tools()` 에
등록된 것이 곧 «할 수 있는 일»이고, `core/graph.py` 의 `DANGEROUS_TOOLS` 가
곧 «먼저 묻는 일»이다. **그 둘을 읽어서 만든다.** 도구를 하나 더하면 **이 문서가
저절로 늘어난다** — 적는 걸 잊을 자리가 없다.

## 🚨 모르는 모듈이 나오면 죽는다

`tools/` 에 새 파일을 만들면 아래 표에 분류 이름을 적어야 한다.
**«기타»로 조용히 밀어 넣지 않는다** — 그러면 새 기능이 설명 없이 목록 끝에 쌓이고,
그건 «있는데 아무도 모르는 기능»이 된다. (`test_tool_eval_cases` 가 «도구를 늘리면
평가 문장도 늘게» 강제하는 것과 같은 모양이다.)
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

# ⚠️ **로그를 더럽히지 않는다**(BL-11). 도구를 import 하면 `core/logger.py` 가
#   깨어나는데, 그 줄이 실기 기록 사이에 섞이면 «무슨 일이 있었나»를 못 믿는다.
os.environ.setdefault("PLUIZ_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "pluiz_build_logs"))
os.environ.setdefault("PLUIZ_CACHE_FILE",
                      os.path.join(tempfile.gettempdir(), "pluiz_build_cache",
                                   "command_cache.json"))

import build_board as BB
from build_board import Missing

_ROOT = BB._ROOT
OUT = os.path.join(_ROOT, "docs", "전체_기능_설명.html")

#: 모듈 → 사람이 읽는 분류. 🚨 **여기 없는 모듈이 나오면 죽는다**(위 주석 참조).
GROUPS: list[tuple[str, str, str]] = [
    ("tools.app_control", "앱과 창", "프로그램을 켜고 끄고, 창을 배치합니다"),
    ("tools.system",      "컴퓨터 설정", "소리·밝기·화면·배터리처럼 PC 자체를 다룹니다"),
    ("tools.filesystem",  "파일과 폴더", "만들고 찾고 옮깁니다. **되돌릴 수 없는 것은 먼저 묻습니다**"),
    ("tools.web",         "웹", "검색하고 열고, 필요하면 내용을 읽어 옵니다"),
    ("tools.vision",      "화면 보기", "화면을 읽고 «그거 어딨지»를 짚어 줍니다"),
    ("tools.input_control", "대신 입력하기", "글자를 치고 눌러 줍니다"),
    ("tools.background",  "나중에 알려주기", "지금 말고 **이따가** 할 일을 맡아 둡니다"),
    ("tools.google_auth", "구글 연결", "일정·메일을 쓰려면 한 번 로그인이 필요합니다"),
    ("tools.calendar",    "일정", "구글 캘린더를 읽고 적습니다"),
    ("tools.gmail",       "메일", "읽고 보냅니다. 🔒 보내는 길은 두 겹으로 막혀 있습니다"),
    ("tools.weather",     "날씨", "링크가 아니라 **값으로** 답합니다"),
]


def _first_line(desc: str) -> str:
    """LLM 에게 주는 설명은 길다. 사람에게는 **첫 문장**이면 된다."""
    t = (desc or "").strip()
    for cut in ("\n", ". ", "。"):
        if cut in t:
            t = t.split(cut)[0]
    t = t.replace("**", "").replace("`", "").strip()
    return t if t.endswith((".", "다", "요", "!", "?")) else t + "."


def bucket(tools) -> dict:
    """도구를 분류별로 나눈다. 🚨 **모르는 모듈이 나오면 죽는다.**

    «기타»로 밀어 넣지 않는 이유는 위 모듈 주석에 적어 뒀다 —
    그러면 새 기능이 설명 없이 목록 끝에 쌓이고, 그건 «있는데 아무도 모르는 기능»이다.

    🔑 **순수 함수로 뺀 이유** — 이래야 테스트가 «모르는 모듈이면 정말 죽는가»를
      가짜 도구 하나로 **실제로 돌려 볼 수 있다.** (안 그러면 그 검사는 흉내만 낸다)
    """
    known = {m for m, _, _ in GROUPS}
    out: dict[str, list] = {m: [] for m in known}
    for t in tools:
        fn = getattr(t, "func", None) or getattr(t, "coroutine", None)
        mod = getattr(fn, "__module__", "")
        if mod not in known:
            raise Missing(
                f"모르는 모듈 «{mod}» (도구 {getattr(t, 'name', '?')}) — "
                f"scripts/build_features.py 의 GROUPS 에 분류 이름을 적어 주세요")
        out[mod].append(t)
    return out


def collect() -> tuple[list, set, dict]:
    sys.path.insert(0, _ROOT)
    from core.graph import DANGEROUS_TOOLS
    from core.tool_registry import get_all_tools

    tools = get_all_tools()
    if not tools:
        raise Missing("get_all_tools() 가 비어 있다")
    return tools, set(DANGEROUS_TOOLS), bucket(tools)


def build() -> str:
    tools, danger, buckets = collect()
    readme = BB.read("docs", "README.md")
    nums = dict((k, v) for k, v, _ in BB.numbers(readme))

    secs = []
    for mod, title, blurb in GROUPS:
        items = sorted(buckets[mod], key=lambda t: t.name)
        if not items:
            continue
        rows = "".join(
            f"<tr><th>{t.name}</th><td>{_first_line(t.description)}"
            + ('<br><span class="r"><b>⚠️ 먼저 물어봅니다</b> — 되돌릴 수 없어서요</span>'
               if t.name in danger else "")
            + "</td></tr>"
            for t in items)
        secs.append(
            f'<h3 style="margin:26px 0 4px">{title} '
            f'<span class="sub" style="font-weight:400">· {len(items)}개</span></h3>'
            f'<p class="sub" style="margin:0 0 8px">{BB.md(blurb)[3:-4]}</p>'
            f'<div class="card scroll"><table>{rows}</table></div>')

    n_danger = sum(1 for t in tools if t.name in danger)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pluiz 전체 기능 설명</title>
<style>{BB._CSS}</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>전체 기능 — 지금 할 수 있는 일 {len(tools)}가지</h1>
  <p class="sub">이 순간 기준 · <b>이 파일은 손으로 고치지 마세요</b> —
     <code>python scripts/build_features.py</code> 가 만듭니다</p>
</header>

<div class="warn">
  <b>🔑 이 목록은 문서가 아니라 <b>코드에서</b> 나옵니다.</b><br>
  «할 수 있는 일» = <code>core/tool_registry.py</code> 의 <code>get_all_tools()</code> ·
  «먼저 묻는 일» = <code>core/graph.py</code> 의 <code>DANGEROUS_TOOLS</code>.<br>
  🚨 그래서 <b>기능을 더하면 이 문서가 저절로 늘어납니다</b> — 적는 걸 잊을 자리가 없습니다.
  (기능 목록을 손으로 쓰면 반드시 낡습니다. <code>docs/meetings/</code> 의 2026-09-11 자
  기능 현황이 그 증거입니다 — 그때는 44개였습니다)
</div>

<div class="grid">
  <div class="stat"><span class="k">할 수 있는 일</span><span class="v">{len(tools)}가지</span>
    <span class="note">분류 {len([g for g in GROUPS if buckets[g[0]]])}개</span></div>
  <div class="stat"><span class="k">먼저 물어보는 일</span><span class="v r">{n_danger}가지</span>
    <span class="note">되돌릴 수 없는 것만</span></div>
  <div class="stat"><span class="k">자동 테스트</span><span class="v">{nums["자동 테스트"]}</span>
    <span class="note">실패 0 · 가짜 환경</span></div>
</div>

<div class="warn">
  <b>⚠️ 「먼저 물어본다」의 기준은 «되돌릴 수 있나» 한 줄입니다.</b><br>
  파일 <b>복사</b>는 원본이 남아서 안 묻고, <b>옮기기·이름 변경</b>은 묻습니다.
  앱을 <b>곱게</b> 닫는 것은 안 묻고, <b>강제 종료</b>는 저장 안 한 내용이 날아가서 묻습니다.
</div>

<h2><span class="n">·</span>기능 전부</h2>
{"".join(secs)}

<footer>
  다시 만들기 — <code>python scripts/build_features.py</code> ·
  낡았는지만 보기 — <code>python scripts/build_features.py --check</code><br>
  개요는 <a href="시스템_전체_설명.html">시스템 전체 설명</a> ·
  개발용 한 장은 <a href="작업_진행판.html">작업 진행판</a> 입니다.
</footer>

</div>
</body>
</html>
"""


def main() -> int:
    try:
        html = build()
    except Missing as e:
        print(f"[features] 🚨 만들지 않는다: {e}")
        return 2
    if "--check" in sys.argv:
        cur = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur == html:
            print("[features] ✅ 최신입니다")
            return 0
        print("[features] 🚨 낡았습니다 — `python scripts/build_features.py`")
        return 1
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(html)
    print(f"[features] ✅ {os.path.relpath(OUT, _ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
