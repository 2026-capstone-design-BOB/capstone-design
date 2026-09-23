# -*- coding: utf-8 -*-
"""mock 스위트를 전부 돌려 **파일 수와 건수를 센다.**

    conda activate pluiz
    python scripts/run_mock_suite.py            # 전부
    python scripts/run_mock_suite.py -q         # 합계만
    python scripts/run_mock_suite.py --md       # DEVLOG에 붙일 한 줄

## 왜 이 스크립트가 있나

[WORKFLOW.md](../docs/WORKFLOW.md)의 마무리 절차가 *"mock 스위트를 **돌려서** 숫자를
확인한다. 기억이나 추정으로 적지 않는다"* 라고 못박아 두고 있다. 그런데 **세는 방식
자체가 사람마다 달랐다** — 서버가 필요한 파일을 넣느냐, `test_sprint1_2`의 PART A만
세느냐에 따라 합계가 수십 개씩 달라진다. 그러면 세션 간 비교(«+102개»)가 의미를 잃는다.

**그래서 세는 방식을 여기 고정한다.** 숫자가 아니라 **재는 자를** 저장소에 둔다.
(`scripts/check_deps_drift.py`·`scripts/analyze_tool_usage.py`와 같은 성격이다)

⚠️ **서버를 띄운 채로 돌리지 말 것.** `test_sprint1_2`의 PART B가 실제 서버에 붙어
   시드 `hit_count`를 올린다 — 2026-09-10에 실측 데이터를 그렇게 오염시킨 적이 있다.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 실 서버나 실 LLM이 있어야 도는 것들. mock 스위트가 아니다.
#: (WORKFLOW § 라이브 테스트 재실행 방법에 따로 적혀 있다)
LIVE_ONLY = {
    "test_regression.py": "실 서버 + 실제 화면이 외부로 나간다",
    "test_commands.py": "실 LLM — 간헐적으로 1건 실패한다(비결정성)",
    "test_cache_api.py": "실 서버 필요",
}

#: PART A(mock)와 PART B(서버)가 한 파일에 있어 종료코드가 항상 1이다.
#: PASS/FAIL 줄을 직접 세고, PART B 실패는 **실패로 치지 않는다.**
SPLIT_FILES = {"test_sprint1_2.py"}

_TAIL_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _run(fname: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, os.path.join("tests", fname)],
        cwd=_ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900,
    )


def main() -> int:
    quiet = "-q" in sys.argv
    as_md = "--md" in sys.argv

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    files = sorted(f for f in os.listdir(os.path.join(_ROOT, "tests"))
                   if f.startswith("test_") and f.endswith(".py"))

    rows: list[tuple[str, int, int]] = []
    failed: list[tuple[str, str]] = []
    skipped = [(f, LIVE_ONLY[f]) for f in files if f in LIVE_ONLY]

    for f in files:
        if f in LIVE_ONLY:
            continue
        p = _run(f, env)
        out = _ANSI_RE.sub("", (p.stdout or "") + (p.stderr or ""))

        if f in SPLIT_FILES:
            # PASS/FAIL 줄을 직접 센다 — 종료코드는 PART B 때문에 항상 1이다
            n_ok = len(re.findall(r"✓ PASS", out))
            n_bad = len(re.findall(r"✗ FAIL", out))
            rows.append((f + " (PART A)", n_ok, n_ok + n_bad))
            if n_bad:
                failed.append((f, f"PART A에서 {n_bad}건 실패"))
            continue

        m = _TAIL_RE.findall(out)
        n, total = (int(m[-1][0]), int(m[-1][1])) if m else (0, 0)
        rows.append((f, n, total))
        if p.returncode != 0:
            tail = "\n".join(out.strip().splitlines()[-8:])
            failed.append((f, tail))

    n_pass = sum(n for _, n, _ in rows)
    n_all = sum(t for _, _, t in rows)

    if as_md:
        print(f"전체 mock **{len(rows)}파일 {n_all}개** 통과 (실패 {len(failed)})")
        return 1 if failed else 0

    if not quiet:
        for name, n, t in rows:
            mark = " " if n == t else "★"
            print(f"  {mark} {name:36} {n}/{t}")
        if skipped:
            print(f"\n  건너뜀 {len(skipped)}파일 (mock이 아니다):")
            for f, why in skipped:
                print(f"    - {f:30} {why}")

    print(f"\n전체 mock: {len(rows)}파일 · {n_pass}/{n_all}")

    if failed:
        print(f"\n★ 실패 {len(failed)}파일")
        for f, why in failed:
            print(f"\n  {f}")
            for line in str(why).splitlines():
                print(f"      {line}")
        return 1

    print("실패 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
