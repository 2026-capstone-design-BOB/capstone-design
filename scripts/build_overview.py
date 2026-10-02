# -*- coding: utf-8 -*-
"""**시스템 전체 설명**을 만든다 — 교수님·팀원에게 보여 주는 한 장.

    conda activate pluiz
    python scripts/build_overview.py            # docs/시스템_전체_설명.html
    python scripts/build_overview.py --check    # 낡았는지만 본다

## 🚨 왜 또 만드나 — `docs/meetings/` 의 여섯 장이 **날짜가 박힌 기록**이라서

`meetings/` 의 HTML 들은 그날 보여 준 자료다. 숫자가 서술과 맞물려 있고
(*"기능은 전부 만들었다. **확인은 절반도 안 했다**"* — 2026-09-11),
**제목부터가 그날의 주장**이다. 그걸 지금 숫자로 고치면 **기록을 위조**하게 된다.

그래서 **옛것은 기록으로 두고**(맨 위에 스냅샷 배너만 붙였다) **지금 설명은 여기서
새로 만든다.** 그리고 **숫자는 손으로 안 적는다** — 그게 `meetings/` 가 낡은 이유다.

## 🔑 서술은 사람이, 숫자는 원본이

| 무엇 | 어디서 |
|---|---|
| 도구 수 · 테스트 합계 | `docs/README.md` 상태표 — **합계의 유일한 출처** |
| 남은 결함 | `docs/BACKLOG.md` 미해결 줄 |
| 제품 숫자(호출어·오프라인·캐시 응답) | `docs/teamwork/10_개발_현황.md` §1 — **발표용 숫자의 출처** |
| 절대 규칙 수 | `CLAUDE.md` |

⚠️ **표시를 못 찾으면 조용히 비우지 않고 죽는다** — 빈 칸이 난 설명서는
«그런 게 없다»로 읽혀서 낡은 것보다 나쁘다. (`build_board.py` 와 같은 규칙)
"""
from __future__ import annotations

import io
import os
import re
import sys

import build_board as BB
from build_board import Missing, md, read

_ROOT = BB._ROOT
OUT = os.path.join(_ROOT, "docs", "시스템_전체_설명.html")


def team_rows(team: str) -> dict[str, str]:
    """`teamwork/10_개발_현황.md` §1 의 (무엇 → 값). **발표용 숫자의 출처다.**"""
    head = "## 1. 지금 상태 한 눈에"
    if head not in team:
        raise Missing("teamwork/10 에 「지금 상태 한 눈에」가 없다")
    body = team[team.index(head):]
    body = body[:body.index("🔴 =")]
    out = {}
    for line in body.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 4 or cells[1].startswith("---") or cells[1] == "무엇":
            continue
        key = re.sub(r"[*`🆕]", "", cells[1]).strip()
        val = re.sub(r"\*\*(.+?)\*\*", r"\1", cells[2])
        val = re.sub(r"[🟢🟡🔴]", "", val).strip()
        if key and val:
            out[key] = val
    if len(out) < 6:
        raise Missing(f"teamwork/10 §1 에서 {len(out)}줄밖에 못 읽었다")
    return out


def pick(rows: dict[str, str], *names: str) -> str:
    """이름이 바뀌어도 **조용히 비지 않게** — 못 찾으면 죽는다."""
    for n in names:
        for k, v in rows.items():
            if n in k:
                return v
    raise Missing(f"teamwork/10 §1 에서 «{names[0]}» 를 못 찾았다")


def build() -> str:
    readme = read("docs", "README.md")
    backlog = read("docs", "BACKLOG.md")
    claude = read("CLAUDE.md")
    team = team_rows(read("docs", "teamwork", "10_개발_현황.md"))

    nums = dict((k, v) for k, v, _ in BB.numbers(readme))
    tools = nums["조작 가능한 도구"]
    tests = nums["자동 테스트"]
    defects = BB.open_defects(backlog)
    rules = BB.hard_rules(claude)

    apps = pick(team, "아는 앱")
    cache = pick(team, "캐시 응답")
    miss = pick(team, "웨이크워드 놓침", "놓침")
    false_wake = pick(team, "웨이크워드 헛깨어남", "헛깨어남")
    offline = pick(team, "오프라인")
    danger = pick(team, "되돌릴 수 없는 일")
    talk = pick(team, "말 거는 방법")

    stats = "".join(
        f'<div class="stat"><span class="k">{k}</span>'
        f'<span class="v">{v}</span><span class="note">{n}</span></div>'
        for k, v, n in [
            ("조작 가능한 기능", tools, f"아는 앱 {apps}"),
            ("자동 테스트", tests, "가짜 환경(mock) · 실패 0"),
            ("같은 명령 응답", cache, "캐시가 받으면 AI를 안 부른다"),
            ("말 거는 방법", talk, "셋 다 됩니다"),
        ])

    cls = {"🔴": "r", "🟡": "a", "🔵": "b"}
    bl = "".join(
        f'<div class="bl"><span class="num {cls[m]}">{m} {num}</span>'
        f'<span class="t">{t}</span></div>' for m, num, t in defects)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pluiz 시스템 전체 설명</title>
<style>{BB._CSS}</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>Pluiz — 말로 시키면 Windows가 알아서 합니다</h1>
  <p class="sub">시스템 전체 설명 · <b>이 파일은 손으로 고치지 마세요</b> —
     <code>python scripts/build_overview.py</code> 가 만듭니다</p>
</header>

<div class="warn">
  <b>🔑 숫자는 베껴 적지 않고 <b>원본에서 가져옵니다.</b></b><br>
  합계 → <code>docs/README.md</code> 상태표 · 발표용 숫자 →
  <code>docs/teamwork/10_개발_현황.md</code> §1 · 남은 결함 → <code>docs/BACKLOG.md</code>.<br>
  🚨 <code>docs/meetings/</code> 의 문서들은 <b>그날의 기록</b>입니다 — 숫자가 지금과 다릅니다.
  거기 숫자를 현재 값으로 쓰지 마세요.
</div>

<h2><span class="n">1</span>한 문장으로</h2>
<div class="card">
  <p><b>“메모장 열어줘”</b> 처럼 말하면, 그 말을 알아듣고 <b>실제로 Windows를 조작</b>합니다.
  챗봇이 «이렇게 하세요»라고 알려 주는 것이 아니라 <b>직접 합니다.</b></p>
  <p class="sub">호출어(“플루이즈”)·🎙️ 버튼·단축키 중 아무거나로 깨우고, 말하고, 결과를 듣습니다.</p>
</div>

<h2><span class="n">2</span>지금 상태</h2>
<div class="grid">{stats}</div>

<h2><span class="n">3</span>어떻게 도는가</h2>
<div class="card">
<table>
<tr><th>①</th><td><b>깨어난다</b> — 호출어 · 🎙️ 버튼 · 단축키. 창은 안 뜨고 접힌 채로 듣습니다</td></tr>
<tr><th>②</th><td><b>알아듣는다</b> — 녹음을 글자로(STT). <b>말이 끝났는지</b>를 크기와 «사람 말인가»
    두 가지로 판단해서 끊습니다</td></tr>
<tr><th>③</th><td><b>정한다</b> — 자주 쓰는 말이면 <b>캐시가 바로</b>({cache}) 답하고,
    처음 보는 말이면 AI가 어떤 기능을 쓸지 고릅니다</td></tr>
<tr><th>④</th><td><b>되돌릴 수 없는 일이면 먼저 묻습니다</b> — {danger}</td></tr>
<tr><th>⑤</th><td><b>한다, 그리고 확인한다</b> — 실제로 됐는지 보고, <b>안 됐으면 안 됐다고 말합니다</b></td></tr>
</table>
</div>

<h2><span class="n">4</span>남들과 다른 점</h2>
<div class="card">
<table>
<tr><th>직접 한다</th><td>알려 주는 것이 아니라 <b>실행</b>합니다. 그래서 «되돌릴 수 있나»가
    설계의 중심입니다</td></tr>
<tr><th>정직하게 말한다</th><td>못 한 것을 했다고 하지 않습니다. 도구를 안 불렀는데
    «✓ 했어요»라고 말하는 길을 <b>코드가 막습니다</b></td></tr>
<tr><th>인터넷이 끊겨도</th><td>자주 쓰는 명령은 <b>{offline}</b> 돕니다 —
    ⚠️ 차별점이라고 말하지 않습니다(윈도우 음성 액세스도 오프라인입니다)</td></tr>
<tr><th>부르는 길이 셋</th><td>{talk}. 시끄러운 곳에서는 버튼이 확실합니다 —
    <b>약점이 아니라 선택</b>입니다</td></tr>
</table>
</div>

<h2><span class="n">5</span>지금 약한 곳 (숨기지 않습니다)</h2>
<div class="card">
<table>
<tr><th>호출어 놓침</th><td>{miss}</td></tr>
<tr><th>호출어 헛깨어남</th><td>{false_wake}</td></tr>
</table>
<p class="sub">🔑 그래서 <b>버튼·단축키를 같이 넣었습니다</b> — 누르지 않으면 안 깨니까
   헛깨어남이 <b>구조적으로 0</b> 입니다.</p>
</div>

<h2><span class="n">6</span>남은 결함 {len(defects)}건</h2>
<p class="sub">🔴 즉시 · 🟡 TODO · 🔵 결정 대기 — 상세는 <code>docs/BACKLOG.md</code></p>
<div class="card">{bl}</div>

<h2><span class="n">7</span>어기면 깨지는 것 {len(rules)}가지</h2>
<p class="sub">개발할 때 지키는 규칙입니다. 배경은 <code>CLAUDE.md</code> 에.</p>
<div class="card"><ul>{"".join(f"<li>{r}</li>" for r in rules)}</ul></div>

<footer>
  다시 만들기 — <code>python scripts/build_overview.py</code> ·
  낡았는지만 보기 — <code>python scripts/build_overview.py --check</code><br>
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
        print(f"[overview] 🚨 원본에서 표시를 못 찾았다 — 만들지 않는다: {e}")
        return 2
    if "--check" in sys.argv:
        cur = io.open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur == html:
            print("[overview] ✅ 최신입니다")
            return 0
        print("[overview] 🚨 낡았습니다 — `python scripts/build_overview.py`")
        return 1
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(html)
    print(f"[overview] ✅ {os.path.relpath(OUT, _ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
