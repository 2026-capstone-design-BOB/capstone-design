# -*- coding: utf-8 -*-
"""써 보다 걸린 것을 **그 자리에서** 보고한다 (2026-10-03 신설)

    from core.feedback import build_report, append_report, log_excerpt

## 왜 파일을 고쳐 달라고 하지 않고 버튼을 만들었나

`docs/teamwork/사용_피드백.md` 는 적을 때 지킬 것 **셋**을 부탁하고 있었다.

| | 부탁 | 왜 필요한가 |
|---|---|---|
| ① | **증상만 적으세요. 원인은 적지 마세요** | 추측이 적혀 있으면 그걸 먼저 믿고 엉뚱한 데를 판다 |
| ② | **말한 그대로 적으세요** | 「좀」 같은 군말에서 실제로 걸린 적이 있다(BL-43·48) |
| ③ | **시각을 분까지 적으세요** | 없으면 로그에서 못 찾아 **적어 준 것이 버려진다** |

🔑 **셋 다 «부탁»이었다.** 이 저장소가 반복해서 적어 둔 문장이 바로 그 자리다 —
*«프롬프트는 확률을 올릴 뿐이고 보장하는 건 구조다»*. 사람에게 규칙 셋을 외우게
하는 대신, **규칙이 깨질 수 없게** 만든다.

| | 어떻게 보장하나 |
|---|---|
| ① | 🚨 **«원인»을 적을 칸을 만들지 않는다.** 없는 칸은 못 채운다 |
| ② | **앱이 안다.** 사용자가 옮겨 적지 않으므로 다듬을 기회가 없다 |
| ③ | **앱이 안다.** 시각이 비는 일이 아예 없어진다 |

남는 것은 사람만 아는 둘뿐이다 — **무엇을 기대했나**, 그리고 **어느 종류인가**.

## 🔒 이름을 받지 않는다

저장소가 공개라 실명이 한 번 들어가면 커밋 기록에 남는다(9/18 · 10/02 에
두 번 데였다). 그래서 **자유 입력 이름 칸을 두지 않고** 미리 정한 표시 중에서만
고르게 한다. 고를 수 없는 것은 적을 수도 없다.

## ⚠️ 로그는 **보여주고 나서** 담는다

`logs/pluiz.log` 발췌가 있으면 재현이 훨씬 쉽다. 다만 로그에는 화면에서 읽은
창 제목 같은 것이 섞일 수 있고 **출력 마스킹을 거치지 않는다**(`.env.example`).
→ 여기서 `mask_sensitive_output` 을 **한 번 거치고**, UI 가 보낼 내용을
사람에게 **그대로 보여준 뒤** 끌 수 있게 한다.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)

#: ⚠️ 환경변수로 덮어쓸 수 있다 — 테스트가 **사람이 쓴 보고를 건드리지 않게**
#:   한다. `PLUIZ_CACHE_FILE`·`PLUIZ_FAVORITES_FILE` 과 같은 패턴이다(BL-11 계열).
REPORT_PATH = os.environ.get("PLUIZ_FEEDBACK_FILE") or os.path.join(
    _ROOT, "logs", "사용_피드백_보고.md")

#: 🔒 **고를 수 있는 것만 적힌다.** 자유 입력이면 실명이 들어온다.
WHO = ("팀원 A", "팀원 B", "개발자")

#: 표시는 `사용_피드백.md` 의 넷과 **같은 글자**를 쓴다 — 두 벌이 되면 한쪽만
#: 갱신된다(이 저장소가 반복해서 데인 모양).
KINDS = {
    "bug":  ("⬜", "안 되거나 이상해요"),
    "slow": ("😕", "되긴 되는데 답답해요"),
    "idea": ("💡", "이런 것도 되면 좋겠어요"),
    "good": ("👍", "잘 됐어요"),
}

_HEADER = f"""# 써 보고 느낀 것 — 앱에서 보낸 보고

> 🚨 **이 파일은 저장소에 올라가지 않습니다**(`.gitignore`). 사용자가 말한 내용이
> 그대로 들어 있습니다. 변소윤에게 **파일로 직접 전달**하세요(카톡·드라이브).
> 적는 법과 처리 절차는 `docs/teamwork/사용_피드백.md` 에 있습니다.

"""

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _mask(text: str) -> str:
    """주민번호·카드번호·API키를 가린다.

    ⚠️ **터져도 보고를 죽이지 않는다.** 다만 조용히 넘어가지도 않는다 —
      가리지 못했으면 그 사실을 보고서에 적는다. (`graph_agent._mask_out` 과 같은 규칙)
    """
    if not text:
        return text
    try:
        from core.security import mask_sensitive_output
        return mask_sensitive_output(text)
    except Exception:                                         # noqa: BLE001
        return text + f"{NL}⚠️ (마스킹을 못 걸었습니다 — 보내기 전에 눈으로 확인해 주세요)"


def _log_path() -> str:
    log_dir = os.environ.get("PLUIZ_LOG_DIR") or os.path.join(_ROOT, "logs")
    return os.path.join(log_dir, "pluiz.log")


def log_excerpt(when: str, before: int = 10, after: int = 25) -> list[str]:
    """`when`(`YYYY-MM-DD HH:MM:SS`) 전후의 로그 줄.

    🔑 **앞보다 뒤를 넓게 본다.** 사용자가 «이상하다»고 느끼는 시점은 보통
      **일이 벌어진 뒤**라, 원인은 그 줄보다 **앞**에 있고 결과는 **뒤**에 있다.
      앞을 조금, 뒤를 넉넉히 가져온다.

    못 읽으면 **빈 목록**을 준다 — 로그가 없다고 보고를 막지 않는다.
    """
    path = _log_path()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [ln.rstrip(NL) for ln in f]
    except Exception:                                         # noqa: BLE001
        return []

    stamp = (when or "")[:19]
    idx = None
    for i, ln in enumerate(lines):
        m = _TS_RE.match(ln)
        if m and m.group(1) <= stamp:
            idx = i
        elif m and m.group(1) > stamp:
            break
    if idx is None:
        # 그 시각보다 이른 줄이 하나도 없다 — 로그가 그 뒤에 시작된 것이다.
        idx = 0
    lo = max(0, idx - before)
    return [_mask(ln) for ln in lines[lo:idx + after + 1]]


def build_report(
    kind: str,
    said: str,
    answered: str,
    when: str = "",
    expected: str = "",
    who: str = "",
    place: str = "",
    log_lines: list[str] | None = None,
) -> str:
    """보고 하나를 마크다운으로. 🚨 **«원인» 칸은 없다** (위 docstring ①).

    `said`/`answered`/`when` 은 **앱이 채운다.** 사람이 옮겨 적지 않으므로
    말이 다듬어지거나 시각이 비는 일이 없다.
    """
    icon, label = KINDS.get(kind, KINDS["bug"])
    who = who if who in WHO else WHO[0]
    when = (when or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))[:19]

    rows = [
        ("언제", when),
        ("누가", who),
        ("어디서", place.strip() or "(안 적음)"),
        ("뭐라고 했나", f'"{_mask(said).strip()}"' if said.strip() else "(말 없이 일어났어요)"),
        ("무슨 일이 일어났나", _mask(answered).strip() or "(아무 일도 안 일어났어요)"),
        ("뭘 기대했나", _mask(expected).strip() or "⬜ (안 적음)"),
    ]
    body = NL.join(f"| **{k}** | {v.replace(NL, ' / ')} |" for k, v in rows)

    out = [
        f"### {icon} {label} — {when}",
        "",
        "| | |",
        "|---|---|",
        body,
        "",
    ]
    if log_lines:
        out += [
            "<details><summary>그때 로그 "
            f"{len(log_lines)}줄 (펼쳐 보기)</summary>",
            "",
            "```",
            *log_lines,
            "```",
            "",
            "</details>",
            "",
        ]
    out.append("---")
    out.append("")
    return NL.join(out)


def append_report(markdown: str) -> str:
    """보고를 **맨 위에** 붙이고 파일 경로를 돌려준다 (최신이 위).

    🚨 **덮어쓰지 않는다.** 보고는 쌓이는 것이고, 하나를 잃으면 그 일은
      없던 일이 된다.
    """
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    old = ""
    if os.path.exists(REPORT_PATH):
        try:
            with open(REPORT_PATH, encoding="utf-8") as f:
                old = f.read()
        except Exception:                                     # noqa: BLE001
            old = ""
    body = old[len(_HEADER):] if old.startswith(_HEADER) else old
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(_HEADER + markdown.rstrip(NL) + NL + NL + body.lstrip(NL))
    return REPORT_PATH


def read_all() -> str:
    """쌓인 보고 전체. 없으면 빈 문자열."""
    try:
        with open(REPORT_PATH, encoding="utf-8") as f:
            return f.read()
    except Exception:                                         # noqa: BLE001
        return ""


def count() -> int:
    """보고가 몇 개 쌓였나. 머리말에는 `###` 가 없으므로 그대로 세면 된다."""
    return sum(1 for ln in read_all().split(NL) if ln.startswith("### "))


# ── 🆕 보낸 것을 **변소윤에게도** 흘려보낸다 (2026-10-03) ───────────
#
# 🚨 **이건 덤이다. 원본은 위의 파일이다.**
#   `append_report` 가 **먼저** 끝나고 나서 이 함수가 불린다. 그래서
#   인터넷이 없든 서버가 죽었든 **보고가 사라지지 않는다** — 팀원은 여전히
#   파일을 보내거나 「전부 복사」로 붙여넣을 수 있다.
#
# 🔑 ROADMAP 이 «클라우드 동기화는 안 한다»고 적어 둔 것과 어긋나지 않는다.
#   그건 **제품 기능**(사용자 데이터 동기화) 얘기고 이건 **개발 도구**다.
#   제품은 여전히 인터넷 없이 돈다 — 여기가 막혀도 Pluiz 는 멀쩡하다.

#: 비어 있으면 **아무것도 안 보낸다.** 기본이 «안 보냄»인 것이 중요하다 —
#: 팀원이 설정하지 않았는데 말한 내용이 밖으로 나가면 안 된다.
ENDPOINT_ENV = "PLUIZ_FEEDBACK_ENDPOINT"
KEY_ENV = "PLUIZ_FEEDBACK_KEY"


def send_report(markdown: str, kind: str = "", when: str = "",
                who: str = "", place: str = "") -> tuple[bool, str]:
    """수신기로 보낸다. `(보냈나, 왜 못 보냈나)`.

    🚨 **절대 예외를 올리지 않는다.** 여기서 터지면 «보고가 실패했다»로 보이는데,
      보고는 이미 파일에 쌓였다. 못 보낸 것과 못 적은 것은 **다른 일**이다.
    """
    url = (os.environ.get(ENDPOINT_ENV) or "").strip()
    key = (os.environ.get(KEY_ENV) or "").strip()
    if not url:
        return False, "안 보냄 (수신기 주소가 설정돼 있지 않아요)"
    if not key:
        return False, "안 보냄 (보내기 키가 설정돼 있지 않아요)"
    try:
        import httpx
        r = httpx.post(
            url,
            headers={"x-pluiz-key": key, "Content-Type": "application/json"},
            json={"markdown": markdown, "kind": kind, "when": when,
                  "who": who, "place": place},
            timeout=6.0,                      # 🔑 짧게. 보내다 UI 가 멈추면 안 된다
        )
        if r.status_code == 200:
            return True, ""
        if r.status_code == 401:
            return False, "보내기 키가 맞지 않아요"
        return False, f"수신기가 거절했어요 (HTTP {r.status_code})"
    except Exception as e:                                    # noqa: BLE001
        # 🔑 **왜 못 보냈는지는 말하되 자세히는 말하지 않는다** — 그 자리에서
        #   할 일은 «파일을 보내 주세요» 하나뿐이다.
        return False, f"수신기에 닿지 못했어요 ({type(e).__name__})"
