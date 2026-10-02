# -*- coding: utf-8 -*-
"""생성 문서를 **전부** 다시 만든다. 하나라도 빠뜨리지 않으려고 둔다.

    conda activate pluiz
    python scripts/build_docs.py            # 셋 다 다시 만든다
    python scripts/build_docs.py --check    # 낡은 것이 있는지만 본다

🔑 **왜 있나** — 생성 문서가 셋이 되면서, 원본을 고치고 **하나만** 다시 만드는 길이
  생겼다. 그러면 나머지가 낡는다(이 저장소가 다섯 번 데인 바로 그 모양이다).
  마무리 절차와 테스트가 가리키는 명령을 **하나로** 둔다.
"""
from __future__ import annotations

import sys

import build_board
import build_features
import build_overview

BUILDERS = (build_board, build_overview, build_features)


def main() -> int:
    bad = 0
    for m in BUILDERS:
        bad |= m.main()
    if bad:
        print("\n🚨 낡았거나 만들지 못한 것이 있습니다 (위 줄을 보세요)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
