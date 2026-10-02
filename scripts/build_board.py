# -*- coding: utf-8 -*-
"""**작업 진행판**을 만든다 — 개발하면서 옆에 띄워 두고 보는 한 장.

    conda activate pluiz
    python scripts/build_board.py            # docs/작업_진행판.html 을 다시 만든다
    python scripts/build_board.py --check    # 낡았는지만 본다 (고치지 않는다)

## 🚨 왜 «손으로 쓰지» 않는가

이 저장소는 **같은 숫자가 여러 문서에 복사돼 한쪽만 갱신되는** 사고를 반복했다:

    2026-09-12  BL-35 요약이 «미해결»인 채로 상세 절만 갱신돼 있었다
    2026-09-17  CLAUDE.md 의 «48파일 1718» 이 낡은 채 발견됐다 (실제 49/1738)
    2026-09-18  같은 합계가 **네 문서에 박혀 있다가 하루에 넷이 동시에 어긋났다**
    2026-10-02  어필 재료에 «놓침 약 80%» 가 남아 있었다 (실제 15.2% — 다섯 배)

**보드는 그 사고가 가장 잘 일어나는 모양이다** — 여러 문서의 요약을 한 장에 모은 것이
바로 «복사본»이기 때문이다. 그래서 **손으로 쓰지 않고 원본에서 만든다.**

🔑 **출력이 결정적이다**(시각·난수를 넣지 않는다). 그래서
`tests/test_board.py` 가 **커밋된 보드와 지금 문서가 어긋났는지**를 바이트로 셀 수 있다 —
원본을 고치고 보드를 안 만들면 **스위트가 깨진다.** 낡을 수가 없는 구조다.

## 🔑 원본이 어디인가 (여기서 베끼지 않는다)

| 칸 | 원본 |
|---|---|
| 지금 하는 중 | `docs/TASKS.md` 「🔵 지금 하는 중」의 **첫 🚩 블록** |
| 숫자 | `docs/README.md` 상태표 — **합계의 유일한 출처** |
| 남은 결함 | `docs/BACKLOG.md` 의 미해결 요약 줄 |
| 절대 규칙 · 돌리는 법 | `CLAUDE.md` |

⚠️ **표시를 못 찾으면 조용히 비우지 않고 죽는다.** 빈 칸이 난 보드는
«할 일이 없다»로 읽혀서, 낡은 것보다 나쁘다.
"""
from __future__ import annotations

import io
import os
import re
import sys

from markdown_it import MarkdownIt

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "docs", "작업_진행판.html")

_MD = MarkdownIt("commonmark").enable("table").enable("strikethrough")


class Missing(Exception):
    """원본에서 표시를 못 찾았다. **조용히 넘어가지 않는다.**"""


def read(*parts: str) -> str:
    return io.open(os.path.join(_ROOT, *parts), encoding="utf-8").read()


def md(text: str) -> str:
    return _MD.render(text).strip()


# ── 원본에서 끌어온다 ──────────────────────────────────────────────

def now_block(tasks: str) -> str:
    """TASKS.md 「🔵 지금 하는 중」의 **첫 🚩 블록**. 인용 기호(`> `)는 벗긴다."""
    head = "## 🔵 지금 하는 중"
    if head not in tasks:
        raise Missing("TASKS.md 에 「🔵 지금 하는 중」이 없다")
    i = tasks.index(head) + len(head)
    j = tasks.find("\n> ---", i)
    if j < 0:
        raise Missing("TASKS.md 의 🚩 블록 끝(`> ---`)을 못 찾았다")
    lines = []
    for ln in tasks[i:j].splitlines():
        if ln.startswith("> "):
            lines.append(ln[2:])
        elif ln.strip() == ">":
            lines.append("")
        elif not ln.strip():
            lines.append("")
    out = "\n".join(lines).strip()
    if not out:
        raise Missing("TASKS.md 의 🚩 블록이 비어 있다")
    return out


def numbers(readme: str) -> list[tuple[str, str, str]]:
    """(이름, 값, 단서). 🔑 **합계의 유일한 출처는 README 상태표다.**"""
    m = re.search(r"mock \*\*(\d+)파일 ([\d,]+)개\*\*", readme)
    if not m:
        raise Missing("README 상태표에서 mock 합계를 못 찾았다")
    files, cases = m.group(1), m.group(2)
    t = re.search(r"\| \*\*도구\*\* \| \*\*(\d+)개\*\*", readme)
    if not t:
        raise Missing("README 상태표에서 도구 개수를 못 찾았다")
    return [
        ("자동 테스트", f"{files}파일 · {cases}건", "실패 0 · mock(가짜 환경)"),
        ("조작 가능한 도구", f"{t.group(1)}개", "앱·파일·시스템·화면·일정·메일"),
    ]


_BL = re.compile(r"^\*\*(🔴|🟡|🔵) (BL-\d+)\s*(.*)$")


def open_defects(backlog: str) -> list[tuple[str, str, str]]:
    """BACKLOG 의 **미해결** 요약 줄. ✅ 로 시작하는 줄은 해결된 것이라 안 담는다."""
    out = []
    for ln in backlog.splitlines():
        m = _BL.match(ln.strip())
        if not m:
            continue
        mark, num, rest = m.groups()
        rest = re.sub(r"\*\*", "", rest).strip(" —·.")
        out.append((mark, num, rest))
    if not out:
        raise Missing("BACKLOG 에서 미해결 줄을 하나도 못 찾았다")
    return out


def hard_rules(claude: str) -> list[str]:
    """CLAUDE.md 「절대 규칙」의 **제목 줄만**. 배경은 원본에 있다."""
    head = "## ⚠️ 코드를 고치기 전에 — 절대 규칙"
    if head not in claude:
        raise Missing("CLAUDE.md 에 「절대 규칙」이 없다")
    body = claude[claude.index(head):]
    body = body[:body.index("\n---", 1)]
    rules = re.findall(r"^\d+\.\s+\*\*(.+?)\*\*", body, re.M)
    if len(rules) < 5:
        raise Missing(f"절대 규칙을 {len(rules)}개밖에 못 찾았다")
    return rules


def how_to_run(claude: str) -> str:
    """CLAUDE.md 의 실행·테스트 코드블록."""
    m = re.search(r"```bash\n(conda activate pluiz.*?)```", claude, re.S)
    if not m:
        raise Missing("CLAUDE.md 에서 실행·테스트 블록을 못 찾았다")
    return m.group(1).rstrip()


# ── 그린다 ────────────────────────────────────────────────────────

_CSS = """
:root{--bg:#fbfaf8;--fg:#1d1c1a;--muted:#6b6862;--line:#e3ded6;--card:#fff;
--accent:#8a5a2b;--red:#a93226;--amber:#9a6b12;--blue:#2a5c8a;--chip:#f2ede5}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
--bg:#171614;--fg:#eceae6;--muted:#a29d94;--line:#333029;--card:#201e1b;
--accent:#d9a86a;--red:#e08b80;--amber:#d9b263;--blue:#8fbdeb;--chip:#2a2723}}
:root[data-theme="dark"]{--bg:#171614;--fg:#eceae6;--muted:#a29d94;--line:#333029;
--card:#201e1b;--accent:#d9a86a;--red:#e08b80;--amber:#d9b263;--blue:#8fbdeb;--chip:#2a2723}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);line-height:1.65;font-size:16px;
font-family:"Pretendard","Malgun Gothic",system-ui,-apple-system,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:36px 20px 80px}
header{border-bottom:2px solid var(--line);padding-bottom:18px;margin-bottom:28px}
h1{font-size:1.75rem;margin:0 0 6px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:.9rem;margin:0}
h2{font-size:1.15rem;margin:38px 0 10px;letter-spacing:-.01em}
h2 .n{color:var(--accent);margin-right:.5em;font-variant-numeric:tabular-nums}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;margin:12px 0}
.card h1,.card h2,.card h3{font-size:1.05rem;margin:14px 0 6px}
.card h1:first-child,.card h2:first-child{margin-top:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:12px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.stat .k{font-size:.78rem;color:var(--muted);display:block;margin-bottom:4px}
.stat .v{font-size:1.5rem;font-weight:700;letter-spacing:-.02em}
.stat .note{display:block;font-size:.78rem;color:var(--muted);margin-top:4px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:.93rem}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--chip);font-weight:600}
code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:.88em}
pre{background:var(--chip);padding:14px 16px;border-radius:10px;overflow-x:auto;font-size:.85rem}
pre code{background:none;padding:0}
.scroll{overflow-x:auto}
ul{padding-left:1.2em}
li{margin:3px 0}
.bl{display:flex;gap:10px;align-items:baseline;padding:7px 0;border-bottom:1px solid var(--line)}
.bl:last-child{border-bottom:none}
.bl .num{font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums}
.bl .t{color:var(--muted);font-size:.9rem}
.r{color:var(--red)}.a{color:var(--amber)}.b{color:var(--blue)}
.warn{background:var(--chip);border-left:3px solid var(--accent);
padding:12px 14px;border-radius:0 8px 8px 0;margin:14px 0;font-size:.92rem}
footer{margin-top:50px;padding-top:16px;border-top:1px solid var(--line);
color:var(--muted);font-size:.85rem}
"""


def build() -> str:
    tasks = read("docs", "TASKS.md")
    readme = read("docs", "README.md")
    backlog = read("docs", "BACKLOG.md")
    claude = read("CLAUDE.md")

    stats = "".join(
        f'<div class="stat"><span class="k">{k}</span>'
        f'<span class="v">{v}</span><span class="note">{n}</span></div>'
        for k, v, n in numbers(readme))

    cls = {"🔴": "r", "🟡": "a", "🔵": "b"}
    bl = "".join(
        f'<div class="bl"><span class="num {cls[m]}">{m} {num}</span>'
        f'<span class="t">{t}</span></div>'
        for m, num, t in open_defects(backlog))

    rules = "".join(f"<li>{r}</li>" for r in hard_rules(claude))

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pluiz 작업 진행판</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>작업 진행판</h1>
  <p class="sub">개발하면서 옆에 띄워 두는 한 장 ·
     <b>이 파일은 손으로 고치지 마세요</b> — <code>python scripts/build_board.py</code> 가 만듭니다</p>
</header>

<div class="warn">
  <b>🔑 이 보드는 베껴 쓴 것이 아니라 <b>원본에서 만들어진 것</b>입니다.</b><br>
  지금 하는 중 → <code>docs/TASKS.md</code> · 숫자 → <code>docs/README.md</code> 상태표 ·
  남은 결함 → <code>docs/BACKLOG.md</code> · 규칙 → <code>CLAUDE.md</code>.<br>
  🚨 원본을 고치고 <b>보드를 다시 안 만들면 테스트가 깨집니다</b>
  (<code>tests/test_board.py</code>) — 낡을 수가 없습니다.
</div>

<h2><span class="n">1</span>지금 하는 중</h2>
<div class="card scroll">
{md(now_block(tasks))}
</div>

<h2><span class="n">2</span>숫자</h2>
<p class="sub">합계의 <b>유일한 출처</b>는 <code>docs/README.md</code> 상태표입니다.
   여기 없는 숫자는 지어내지 말고 거기서 가져오세요.</p>
<div class="grid">{stats}</div>

<h2><span class="n">3</span>남은 결함</h2>
<p class="sub">🔴 즉시 · 🟡 TODO · 🔵 결정 대기 — 상세는 <code>docs/BACKLOG.md</code></p>
<div class="card">{bl}</div>

<h2><span class="n">4</span>코드를 고치기 전 — 절대 규칙</h2>
<p class="sub">어기면 바로 깨지는 것들입니다. 배경은 <code>CLAUDE.md</code> 의 각 링크에.</p>
<div class="card"><ul>{rules}</ul></div>

<h2><span class="n">5</span>돌리는 법</h2>
<div class="warn">
  🚨 <b>스위트는 cmd / Anaconda Prompt 에서 돌립니다.</b>
  Git Bash 에서 돌리면 <b>프로젝트와 무관한 거짓 실패</b>가 납니다.
</div>
<pre><code>{how_to_run(claude)}</code></pre>

<footer>
  보드를 다시 만들기 — <code>python scripts/build_board.py</code><br>
  낡았는지만 보기 — <code>python scripts/build_board.py --check</code>
</footer>

</div>
</body>
</html>
"""


def main() -> int:
    try:
        html = build()
    except Missing as e:
        print(f"[board] 🚨 원본에서 표시를 못 찾았다 — 보드를 만들지 않는다: {e}")
        print("[board]    빈 칸이 난 보드는 «할 일이 없다»로 읽혀서 낡은 것보다 나쁘다.")
        return 2

    if "--check" in sys.argv:
        cur = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur == html:
            print("[board] ✅ 최신입니다")
            return 0
        print("[board] 🚨 낡았습니다 — `python scripts/build_board.py` 로 다시 만드세요")
        return 1

    io.open(OUT, "w", encoding="utf-8", newline="\n").write(html)
    print(f"[board] ✅ {os.path.relpath(OUT, _ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
