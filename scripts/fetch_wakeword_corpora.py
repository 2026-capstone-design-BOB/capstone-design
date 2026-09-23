# -*- coding: utf-8 -*-
"""웨이크워드 학습용 공개 말뭉치 내려받기 — **M7 2단계**

    python scripts/fetch_wakeword_corpora.py --list        # 무엇을 왜 받는지 + 용량 + 디스크 여유
    python scripts/fetch_wakeword_corpora.py rirs          # 하나만 (가장 작다 · 1.22GB)
    python scripts/fetch_wakeword_corpora.py --all         # 셋 다 (내려받기 약 21GB)
    python scripts/fetch_wakeword_corpora.py --verify      # 받아 둔 것만 검사한다 (md5 + 풀렸는지)
    python scripts/fetch_wakeword_corpora.py --inventory   # data/corpora/manifest.json 만 다시 쓴다

## 왜 이게 필요한가 — 지금 증강은 «흉내»다

현행 학습은 **백색잡음을 더하고 반사를 1회 섞어** 방을 흉내 낸다
(`scripts/wakeword_data.py` 의 `augment`). 그래서 조용한 방에서 만든 자로 재면
검증 95%가 나오고 **실기는 10번 중 2번**이었다.

바꿀 것은 셋이다 → [M7 §5-1 증강 표](../docs/design/M7_웨이크워드_재구축.md)

| 지금 | 바꿀 것 | 무엇으로 |
|---|---|---|
| 백색잡음 더하기 | 실제 잡음을 SNR 0~20dB로 | **MUSAN** |
| 반사 1회로 잔향 흉내 | 실측 임펄스 응답 컨볼루션 | **RIR and Noises** |
| 음성(negative)이 합성음뿐 | **사람이 실제로 말한 한국어** | **Zeroth-Korean** |

🔑 **셋 중 값이 가장 큰 것은 Zeroth다.** 기준선에서 밝혀진 오탐의 모양이
*«발음에 속는 게 아니라 음성이면 깬다»* 였다(자유 발화 214 > 헷갈리는 말 157).
**한국어 말소리를 음성(negative)으로 대량 먹이는 것**이 그 자리를 직접 친다.
→ [기준선](../docs/research/2026-09_웨이크워드_기준선.md)

## 🚨 이 스크립트는 런타임을 한 줄도 안 건드린다

`scripts/` 이고 내려받아 `data/`(git 밖)에 푼다. 9/22 동결 대상이 아니다.
→ [TASKS § 앞당길 수 있는 것을 가르는 기준](../docs/TASKS.md)

## ⚠️ 건너뛰고 «통과»라고 말하지 않는다

디스크·체크섬·압축 어느 하나라도 어긋나면 **분명히 말하고 0이 아닌 값으로 죽는다.**
조용히 건너뛴 뒤 «끝났습니다»라고 적는 것이 [BL-59](../docs/BACKLOG.md)로 적어 둔 실패 모양이다.
그래서 `--verify` 는 **받아 둔 것이 하나도 없으면 «통과»가 아니라 실패**다.

## 표준 라이브러리만 쓴다

이 저장소는 V2에서 torch를 일부러 걷어냈다. 내려받기 하나 때문에 `requests`·`tqdm`을
들이지 않는다 — `urllib` + `hashlib` + `tarfile`/`zipfile` 로 충분하다.

## 🔒 저작권 — 발표 자료에 출처를 적어야 한다

셋 다 재배포 가능한 라이선스지만 **저작자 표시가 조건**이다(CC BY 4.0 · Apache 2.0).
아래 `CORPORA` 표의 `license` 가 그대로 근거고, `data/corpora/manifest.json` 에도 박힌다.
**말뭉치 자체는 저장소에 올리지 않는다** — `.gitignore` 가 `data/` 를 통째로 막는다.
"""
import argparse
import hashlib
import json
import os
import shutil
import ssl
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "data", "corpora")
MANIFEST = os.path.join(DEST, "manifest.json")
GB = 1024 ** 3
MARGIN_BYTES = 2 * GB          # 디스크 여유를 이만큼은 남긴다
#: 한 바이트도 안 느는 바퀴를 몇 번까지 견디나. 망 깜빡임과 «정말 안 되는 것»을 가른다.
STALL_LIMIT = 3


class Corpus:
    def __init__(self, key, title, url, size, md5, archive, probe,
                 extracted_hint, license_, why, mirrors=(), extract_into=None):
        self.key = key
        self.title = title
        self.url = url
        self.mirrors = list(mirrors)
        self.size = size                      # 내려받기 바이트 (실측 · Content-Length)
        self.md5 = md5                        # OpenSLR checksum.md5 에 적힌 값
        self.archive = archive
        self.probe = probe                    # 풀렸는지 확인할 상대 경로
        self.extracted_hint = extracted_hint  # 풀었을 때 어림값 (정확하지 않다)
        self.license = license_
        self.why = why
        self.extract_into = extract_into      # 최상위 폴더가 없는 압축을 담을 자리

    @property
    def archive_path(self):
        return os.path.join(DEST, self.archive)

    @property
    def extract_dir(self):
        """압축을 풀 자리.

        🚨 2026-09-18에 여기서 한 번 데였다 — **Zeroth 압축에는 최상위 폴더가 없다.**
        `data/corpora/` 에 그대로 풀면 `train_data_01`·`test_data_01`·`AUDIO_INFO`·
        `zeroth.lm.*` 아홉 덩어리가 말뭉치 뿌리에 흩어지고, `probe`(`zeroth_korean`)는
        영영 안 생긴다. **md5 는 맞는데 «안 풀렸다»고 나오는** 그 모양이다
        (10.3GB 를 제대로 받아 놓고도 «실패»로 셌다).
        그래서 그런 압축은 **제 이름의 폴더를 만들어 그 안에 푼다.**
        """
        return os.path.join(DEST, self.extract_into) if self.extract_into else DEST

    @property
    def probe_path(self):
        return os.path.join(DEST, self.probe)

    @property
    def urls(self):
        return [self.url] + self.mirrors

    def extracted(self):
        return os.path.isdir(self.probe_path)


# ── 받을 것 ─────────────────────────────────────────────────────────
# 용량과 md5 는 2026-09-18에 openslr.org 에 직접 물어 확인한 값이다
# (Content-Length + resources/<n>/checksum.md5). 추측이 아니다.
#
# 🚨 **대체 주소도 2026-09-18에 직접 찔러 봤다.** 처음에 적어 둔 `us.openslr.org` 는
#    **인증서가 그 이름으로 발급돼 있지 않다**(Hostname mismatch). 본 주소가 끊긴
#    바로 그 순간에 대체 주소가 SSL 로 죽었다 — **«대체 주소가 있다»가 거짓이었고,
#    그 사실은 본 주소가 죽기 전까지 드러나지 않는다.** 그래서 적어 두기 전에 찔러 본다.
#      · www.openslr.org            ✅ 206(이어받기 됨)
#      · us.openslr.org             ❌ 인증서 이름 불일치 — **뺐다**
#      · openslr.elda.org           ❌ handshake timeout (한국에서)
#      · openslr.magicdatatech.com  ✅ 206 · 셋 다 크기가 본 주소와 같다
CORPORA = {
    "musan": Corpus(
        key="musan",
        title="MUSAN — 말·음악·잡음",
        url="https://www.openslr.org/resources/17/musan.tar.gz",
        mirrors=["https://openslr.magicdatatech.com/resources/17/musan.tar.gz"],
        size=11086114085,
        md5="0c472d4fc0c5141eca47ad1ffeb2a7df",
        archive="musan.tar.gz",
        probe="musan/noise",
        extracted_hint=12 * GB,
        license_="CC BY 4.0 (저작자 표시)",
        why="백색잡음 «흉내»를 실제 잡음으로 바꾼다. babble(여러 사람이 동시에 말하는 소리)이 "
            "전시회장 소음에 가장 가까운 대체재다 — 그 소음은 미리 못 구한다",
    ),
    "rirs": Corpus(
        key="rirs",
        title="RIR and Noises — 실측 방 임펄스 응답",
        url="https://www.openslr.org/resources/28/rirs_noises.zip",
        mirrors=["https://openslr.magicdatatech.com/resources/28/rirs_noises.zip"],
        size=1311166223,
        md5="e6f48e257286e05de56413b4779d8ffb",
        archive="rirs_noises.zip",
        probe="RIRS_NOISES",
        extracted_hint=2 * GB,
        license_="Apache 2.0",
        why="잔향을 «반사 1회 흉내»가 아니라 실측 컨볼루션으로. 셋 중 가장 작아서 "
            "먼저 받아 파이프라인을 뚫어 보기 좋다",
    ),
    "zeroth": Corpus(
        key="zeroth",
        title="Zeroth-Korean — 한국어 읽기 음성 약 51시간",
        url="https://www.openslr.org/resources/40/zeroth_korean.tar.gz",
        mirrors=["https://openslr.magicdatatech.com/resources/40/zeroth_korean.tar.gz",
                 "https://storage.googleapis.com/zeroth_project/zeroth_korean.tar.gz"],
        size=10339720618,
        md5="8e0a4268bb8e80db3773c331025ef1e2",
        archive="zeroth_korean.tar.gz",
        probe="zeroth_korean",
        # 🔑 이 압축만 최상위 폴더가 없다 (musan/ · RIRS_NOISES/ 는 있다)
        extract_into="zeroth_korean",
        extracted_hint=11 * GB,
        license_="CC BY 4.0 (저작자 표시)",
        why="🔴 셋 중 값이 가장 크다. 오탐의 모양이 «발음에 속는 게 아니라 음성이면 깬다» 였다 — "
            "사람이 실제로 말한 한국어를 음성(negative)으로 먹이는 것이 그 자리를 직접 친다",
    ),
}

# ── 자동으로 못 받는 것 ───────────────────────────────────────────────
# 로그인·동의가 필요해 스크립트가 대신 받을 수 없다. **여기 적어 두지 않으면
# «받을 수 있는 게 이 셋뿐»이라고 오해한다.**
MANUAL = [
    {
        # 🔑 «어느 데이터셋인가»를 여기 적어 둔다. 신청할 때 이름을 대야 하고,
        #    AI Hub 에는 음성 데이터가 수십 종이라 «AI Hub» 만으로는 신청을 못 한다.
        #    (2026-09-18 aihub.or.kr 에서 직접 확인한 이름·규모·형식이다)
        "key": "aihub",
        "title": "AI Hub — ① 자유대화 음성(일반남녀) · ② 명령어 음성(일반남녀)",
        "where": "① https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=109 (자유대화 · 4,000시간 · 2,000명+)"
                 "  ② https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=96 (명령어 · 4,000시간 · 48kHz 16bit mono)",
        "why": "🔴 우리 오탐의 출처가 «자유 발화»다(기준선 §3). ①이 그것과 같은 종류다. "
               "②는 사람이 기기에 대고 말하는 명령어라 **플루이즈에게 실제로 할 말**이고, "
               "그게 웨이크워드가 아닌 것을 배우는 가장 어려운 음성(negative)이다",
        "how": "회원가입(내국인만) → 데이터셋 페이지 «다운로드» → 활용목적 적어 신청 → 승인(며칠) → "
               "API 다운로드. ⚠️ 4,000시간을 다 받지 않는다 — 수십 시간이면 충분하다",
        "drop": "data/corpora/manual/aihub/",
        # 🔑 «목록에서 뭘 고르나» — 승인이 나면 파일이 수십 개인 트리가 나온다.
        #    여기 안 적어 두면 그 앞에서 다시 막힌다.
        "pick": (
            "[원천]만 받는다. [라벨]·대본은 **안 받아도 된다.**\n"
            "  · [원천] = 실제 음성(wav). 🔴 우리가 쓰는 것은 이것뿐이다 —\n"
            "    호출어가 아닌 한국어 말소리를 모델에 먹이는 게 목적이라 «무슨 말인지»는 필요 없다.\n"
            "  · [라벨] = 화자·환경·내용이 적힌 JSON. 지금 쓸 데가 없다.\n"
            "    (다만 작으면 같은 구간 것만 받아 둬도 손해는 아니다 — 나중에 «블루투스»처럼\n"
            "     발음이 가까운 발화를 골라내는 데 쓸 수 있다)\n"
            "  · 대본 = 대화 시나리오 텍스트. 녹음 내용이 아니다. 건너뛴다.\n"
            "\n"
            "🚨 **전부 받지 않는다. Validation 쪽에서 한 덩어리만 먼저 받는다.**\n"
            "  4,000시간은 48kHz 16bit mono 기준 시간당 약 345MB이라 통째로는 수십~수백 GB다.\n"
            "  **필요한 건 10~30시간(약 3~10GB)이면 충분하다.** 부족하면 그때 한 덩어리 더 받는다.\n"
            "  Validation 을 먼저 고르는 이유는 **작아서 파이프라인을 먼저 뚫어 볼 수 있어서**다.\n"
            "\n"
            "⚠️ 파일이 `.part1` `.part2` 처럼 나뉘어 있으면 그건 **한 파일의 조각**이다.\n"
            "  조각을 전부 받아야 풀린다. 고르는 단위는 «조각»이 아니라 «완결된 zip 하나»다."),
        # 신청서의 «활용 목적» 칸에 그대로 넣을 문구. 여기 두는 이유는 신청이
        # **사용자 몫이고 며칠 걸리는 일**이라, 물어볼 사람이 없을 때 꺼내 볼 수 있어야 해서다.
        "apply_text": (
            "졸업작품(캡스톤디자인) 과제로 한국어 음성 명령 기반 PC 제어 에이전트를 개발하고 "
            "있습니다. 호출어(웨이크워드) 검출 모델이 호출어가 아닌 한국어 발화에도 반응하는 "
            "오검출 문제가 있어, 이를 줄이기 위한 학습용 음성(negative) 데이터로 활용하고자 "
            "합니다. 음성은 모델 학습에만 사용하며 원본이나 재구성물을 외부에 공개·배포하지 "
            "않습니다. 결과물은 교내 졸업작품 전시로만 사용합니다."),
    },
    {
        "key": "commonvoice",
        "title": "Common Voice (ko) — 한국어 낭독",
        "where": "https://commonvoice.mozilla.org/ko/datasets",
        "why": "화자 다양성. Zeroth보다 마이크·환경이 잡다해서 그 점이 값이다",
        "how": "약관 동의 후 내려받기 링크가 생긴다. 계정은 필요 없다",
        "drop": "data/corpora/manual/commonvoice/",
    },
]


MANUAL_NOTE = "여기에_넣으세요.txt"


def manual_files(m):
    """수동 항목 폴더에 **실제로 들어온 파일**을 센다.

    🚨 «폴더가 있으면 받은 것»으로 세지 않는다. 이 스크립트가 빈 폴더를 미리 만들어 주므로
    폴더 존재는 아무것도 뜻하지 않는다. 안내문(`여기에_넣으세요.txt`)도 제외한다 —
    **«받았다»를 자동으로 참으로 만드는 파일이 그 폴더 안에 있으면 안 된다.**
    """
    root = os.path.join(ROOT, m["drop"])
    if not os.path.isdir(root):
        return 0
    n = 0
    for _d, _dirs, files in os.walk(root):
        n += sum(1 for f in files if f != MANUAL_NOTE)
    return n


def ensure_manual_dirs():
    """받을 자리를 **미리 만들어 둔다.** «어디에 저장하냐»가 실행 중에 답해져야 한다."""
    for m in MANUAL:
        root = os.path.join(ROOT, m["drop"])
        os.makedirs(root, exist_ok=True)
        note = os.path.join(root, MANUAL_NOTE)
        if not os.path.exists(note):
            with open(note, "w", encoding="utf-8") as f:
                f.write(
                    f"{m['title']}\n"
                    f"{'=' * 60}\n\n"
                    f"받는 곳: {m['where']}\n"
                    f"받는 법: {m['how']}\n\n"
                    f"왜 받나: {m['why']}\n\n"
                    + (f"목록에서 무엇을 고르나:\n{'-' * 60}\n{m['pick']}\n{'-' * 60}\n\n"
                       if m.get("pick") else "")
                    + (f"신청서 «활용 목적» 칸에 쓸 문구 (그대로 붙여 넣어도 된다):\n"
                       f"{'-' * 60}\n{m['apply_text']}\n{'-' * 60}\n\n"
                       if m.get("apply_text") else "") +
                    f"압축을 푼 그대로 이 폴더 안에 두면 된다. 폴더 구조는 바꾸지 않아도 된다.\n"
                    f"넣고 나서 확인:  python scripts/fetch_wakeword_corpora.py --list\n\n"
                    f"⚠️ 이 폴더는 .gitignore 가 막는다(data/). 저장소에 올라가지 않는다.\n"
                    f"   사람 목소리라 용량 문제만이 아니다 — 동의 범위가 «졸업작품 학습»이다.\n")


def human(n):
    if n >= GB:
        return f"{n / GB:.2f}GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f}MB"
    return f"{n}B"


def free_bytes():
    os.makedirs(DEST, exist_ok=True)
    return shutil.disk_usage(DEST).free


# ── 내려받기 ────────────────────────────────────────────────────────
def _opener():
    # 학교·회사 망에서 인증서 검증이 깨질 때 «조용히 끄는» 선택지는 두지 않는다.
    # 실패하면 실패라고 말한다.
    ctx = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def download(c, force=False, rounds=8):
    """이어받기로 `c.archive` 를 채운다. 이미 완전하면 건드리지 않는다.

    🚨 **끊기면 스스로 다시 붙는다**(`rounds` 바퀴까지). 2026-09-18에 MUSAN 을
    두 번 놓쳤다 — 10GB 를 받는 중 서버가 3MB/s → 370KB/s 로 떨어지다 읽기 타임아웃으로
    죽었고, 그때마다 **사람이 같은 명령을 다시 쳐야 했다.** 이어받기가 되는데도
    사람을 붙잡아 두는 것은 도구가 일을 덜 한 것이다.
    ⚠️ 한 바퀴를 다 돌았는데 한 바이트도 안 늘면 **잠깐 쉬었다 다시 본다.**
       `STALL_LIMIT` 바퀴 연속으로 그러면 멈춘다 — 안 그러면 망이 끊긴 자리에서
       영원히 돈다. 🔑 **한 번에 포기하지 않는 이유**: 2026-09-18에 8.74GB 지점에서
       `getaddrinfo failed` 가 두 주소에 동시에 났다. 서버가 죽은 게 아니라
       **이 PC의 이름 해석이 몇 초 끊긴 것**이었다. 거기서 바로 포기하면
       10GB 를 받다가 «망 깜빡임» 하나에 사람을 다시 부르게 된다.
    """
    part = c.archive_path + ".part"
    if os.path.exists(c.archive_path) and not force:
        got = os.path.getsize(c.archive_path)
        if got == c.size:
            print(f"  이미 있다 ({human(got)}) — 내려받기를 건너뛴다")
            return True
        print(f"  ⚠️ 크기가 다르다 ({human(got)} ≠ {human(c.size)}) — .part 로 되돌려 이어받는다")
        os.replace(c.archive_path, part)

    have = os.path.getsize(part) if os.path.exists(part) else 0
    if force and os.path.exists(part):
        os.remove(part)
        have = 0
    if have > c.size:
        print("  ⚠️ 받다 만 파일이 더 크다 — 버리고 처음부터 받는다")
        os.remove(part)
        have = 0

    opener = _opener()
    last_err = None
    stalled = 0
    for r_i in range(max(1, rounds)):
        before = have
        for url in c.urls:
            if have >= c.size:
                break
            try:
                _stream(opener, url, part, have, c.size)
                last_err = None
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:  # noqa: BLE001
                last_err = e
                print(f"  ⚠️ {url} 실패 ({e}) — 다음 주소를 시도한다. "
                      f"받은 {human(have)} 는 남는다")
            have = os.path.getsize(part) if os.path.exists(part) else 0
            if have >= c.size:
                break
        if have >= c.size:
            break
        if have <= before:
            stalled += 1
            if stalled >= STALL_LIMIT:
                # 🔑 여기서 멈춰야 «돌고 있는데 아무 일도 안 일어나는» 상태를 안 만든다.
                print(f"  ❌ {STALL_LIMIT}바퀴 연속으로 한 바이트도 안 늘었다. 망을 확인할 것")
                break
            wait = 5 * (2 ** (stalled - 1))          # 5 · 10 · 20초
            print(f"  ⏳ 진전이 없다 — {wait}초 쉬었다 다시 본다 "
                  f"({stalled}/{STALL_LIMIT}번째 · 받은 {human(have)} 는 그대로다)",
                  flush=True)
            time.sleep(wait)
            continue
        stalled = 0
        print(f"  ↻ 끊겼다 — {human(have)} 지점부터 다시 붙는다 "
              f"({r_i + 2}/{rounds}번째 · 받은 것은 그대로다)", flush=True)

    got = os.path.getsize(part) if os.path.exists(part) else 0
    if got != c.size:
        print(f"  ❌ 크기가 안 맞는다 ({human(got)} ≠ {human(c.size)})"
              + (f" · 마지막 오류: {last_err}" if last_err else ""))
        print("     🔑 같은 명령을 다시 돌리면 **받은 지점부터 이어받는다.** 처음부터가 아니다")
        return False
    os.replace(part, c.archive_path)
    return True


def _stream(opener, url, part, have, total):
    req = urllib.request.Request(url, headers={"User-Agent": "pluiz-m7/1.0"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    with opener.open(req, timeout=60) as r:
        resumed = (getattr(r, "status", r.getcode()) == 206)
        if have and not resumed:
            # 서버가 이어받기를 거부했다. 그냥 덧붙이면 앞부분이 두 번 들어간다.
            print("  ⚠️ 이 주소는 이어받기를 지원하지 않는다 — 처음부터 받는다")
            have = 0
        mode = "ab" if (have and resumed) else "wb"
        start, done = have, have
        t0 = time.time()
        last = 0.0
        with open(part, mode) as f:
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last >= 2.0:
                    last = now
                    sp = (done - start) / max(now - t0, 0.001)
                    eta = (total - done) / sp if sp > 0 else 0
                    print(f"  {human(done)} / {human(total)} ({done * 100 / total:.1f}%) · "
                          f"{human(int(sp))}/s · 남은 시간 약 {int(eta // 60)}분", flush=True)
    print(f"  {human(done)} / {human(total)} · 내려받기 끝", flush=True)


def md5_of(path, label=""):
    h = hashlib.md5()
    total = max(os.path.getsize(path), 1)
    done = 0
    last = 0.0
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
            done += len(b)
            now = time.time()
            if label and now - last >= 3.0:
                last = now
                print(f"  {label} md5 검사 {done * 100 / total:.0f}%", flush=True)
    return h.hexdigest()


def extract(c):
    """압축을 푼다. 이미 풀려 있으면 건드리지 않는다."""
    if c.extracted():
        print(f"  이미 풀려 있다 ({os.path.relpath(c.probe_path, ROOT)}) — 건너뛴다")
        return True
    into = c.extract_dir
    os.makedirs(into, exist_ok=True)
    print(f"  압축을 푼다 → {os.path.relpath(into, ROOT).replace(os.sep, '/')}/ (몇 분 걸린다)")
    try:
        if c.archive.endswith(".zip"):
            with zipfile.ZipFile(c.archive_path) as z:
                z.extractall(into)
        else:
            with tarfile.open(c.archive_path, "r:gz") as t:
                try:
                    t.extractall(into, filter="data")   # 3.11.4+ — 경로 탈출을 막는다
                except TypeError:
                    t.extractall(into)
    except Exception as e:                                       # noqa: BLE001
        print(f"  ❌ 푸는 중 실패: {e}")
        return False
    if not c.extracted():
        # 🚨 «풀었는데 없다»는 대개 **압축 안의 구조가 바뀐 것**이다. 이름만 말하고 끝내면
        #    사람이 탐색기를 열어 헤맨다 — 실제로 뭐가 생겼는지 여기서 보여 준다.
        try:
            got = sorted(os.listdir(into))[:12]
        except OSError:
            got = []
        print(f"  ❌ 풀렸는데 {c.probe} 가 없다 — 압축 안 구조가 바뀐 것 같다")
        print(f"     실제로 생긴 것: {', '.join(got) if got else '(비어 있다)'}")
        print(f"     → CORPORA['{c.key}'] 의 probe / extract_into 를 실제 이름에 맞춰야 한다")
        return False
    return True


def inventory_one(c):
    """풀린 폴더를 센다. 4단계(증강 파이프라인)가 이 숫자를 읽는다."""
    if not c.extracted():
        return None
    root = os.path.join(DEST, c.probe.split("/")[0])
    n, nbytes, exts = 0, 0, {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            n += 1
            ext = os.path.splitext(fn)[1].lower()
            exts[ext] = exts.get(ext, 0) + 1
            try:
                nbytes += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    top = dict(sorted(exts.items(), key=lambda kv: -kv[1])[:6])
    return {"root": os.path.relpath(root, ROOT).replace("\\", "/"),
            "files": n, "bytes": nbytes, "by_ext": top}


def write_manifest():
    os.makedirs(DEST, exist_ok=True)
    out = {
        "생성": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "만든이": "scripts/fetch_wakeword_corpora.py (M7 2단계)",
        "주의": "이 폴더는 .gitignore 가 막는다. 말뭉치도 이 파일도 저장소에 올리지 않는다",
        "말뭉치": {},
        "수동": {m["key"]: {"제목": m["title"], "받는곳": m["where"], "놓을곳": m["drop"],
                            "파일수": manual_files(m), "있음": manual_files(m) > 0}
                 for m in MANUAL},
    }
    for c in CORPORA.values():
        inv = inventory_one(c)
        out["말뭉치"][c.key] = {
            "제목": c.title,
            "출처": c.url,
            "라이선스": c.license,
            "md5": c.md5,
            "압축파일": os.path.basename(c.archive_path) if os.path.exists(c.archive_path) else None,
            "풀림": bool(inv),
            "내용": inv,
        }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def _state_line(c):
    if c.extracted():
        return "✅ 풀림"
    if os.path.exists(c.archive_path):
        return "📦 압축만 있다 (풀면 된다)"
    part = c.archive_path + ".part"
    if os.path.exists(part):
        return f"⏸️ 받다 만 것 {human(os.path.getsize(part))} (이어받는다)"
    return "⬜ 없음"


def cmd_list():
    print("웨이크워드 학습용 공개 말뭉치 — M7 2단계\n")
    total = 0
    for c in CORPORA.values():
        total += c.size
        print(f"  [{c.key}] {c.title}")
        print(f"      {_state_line(c)} · 내려받기 {human(c.size)} · 풀면 약 {human(c.extracted_hint)}")
        print(f"      {c.license} · {c.url}")
        print(f"      왜: {c.why}\n")
    free = free_bytes()
    need = total + sum(c.extracted_hint for c in CORPORA.values())
    print(f"  셋 다: 내려받기 {human(total)} · 풀기까지 합쳐 약 {human(need)} 필요")
    print(f"  지금 디스크 여유 {human(free)} → "
          f"{'✅ 충분하다' if free > need + MARGIN_BYTES else '🚨 모자란다 — 하나씩 받아라'}")
    print("  💡 다 풀고 나면 --drop-archive 로 압축파일을 지워 "
          f"{human(total)} 를 회수할 수 있다 (푼 것을 확인한 뒤에만 지운다)\n")
    print("  🚫 자동으로 못 받는 것 — 로그인·동의가 필요하다")
    ensure_manual_dirs()          # 받을 자리를 실제로 만들어 둔다 (빈 폴더 + 안내문)
    for m in MANUAL:
        n = manual_files(m)
        print(f"      [{m['key']}] {m['title']} — "
              f"{f'✅ 파일 {n}개 들어와 있다' if n else '⬜ 아직 비어 있다'}")
        print(f"          {m['where']}")
        print(f"          {m['how']}")
        print(f"          👉 받으면 여기에 둔다: {m['drop']}  (방금 만들어 뒀다)")
        print(f"          왜: {m['why']}")
    return 0


def cmd_verify():
    """받아 둔 것만 검사한다. **하나도 없으면 «통과»가 아니다.**"""
    any_found = False
    bad = 0
    for c in CORPORA.values():
        has_archive = os.path.exists(c.archive_path)
        if not has_archive and not c.extracted():
            print(f"  [{c.key}] ⬜ 없다 — 검사할 것이 없다")
            continue
        any_found = True
        print(f"  [{c.key}] {c.title}")
        if has_archive:
            size = os.path.getsize(c.archive_path)
            if size != c.size:
                print(f"      ❌ 크기 {human(size)} ≠ {human(c.size)}")
                bad += 1
            else:
                got = md5_of(c.archive_path, label=c.key)
                ok = (got == c.md5)
                print(f"      {'✅' if ok else '❌'} md5 {got}{'' if ok else ' ≠ ' + c.md5}")
                if not ok:
                    bad += 1
        inv = inventory_one(c)
        if inv:
            print(f"      ✅ 풀림 — 파일 {inv['files']:,}개 · {human(inv['bytes'])} · {inv['by_ext']}")
        else:
            print("      ⬜ 아직 안 풀렸다")
    if not any_found:
        print("\n❌ 받아 둔 말뭉치가 하나도 없다. **검사할 것이 없는 것은 «통과»가 아니다.**")
        print("   먼저 무엇을 받을지 본다:  python scripts/fetch_wakeword_corpora.py --list")
        return 2
    write_manifest()
    print(f"\n{'✅ 전부 멀쩡하다' if bad == 0 else f'❌ {bad}건이 어긋난다'} · "
          f"목록을 data/corpora/manifest.json 에 적었다")
    return 0 if bad == 0 else 1


def cmd_fetch(keys, drop_archive, force, rounds=8):
    picked = [CORPORA[k] for k in keys]
    need_dl = sum(c.size for c in picked if force or not os.path.exists(c.archive_path))
    need_ex = sum(c.extracted_hint for c in picked if not c.extracted())
    free = free_bytes()
    print(f"받을 것: {', '.join(c.key for c in picked)}")
    print(f"필요 — 내려받기 {human(need_dl)} + 풀기 약 {human(need_ex)} = 약 "
          f"{human(need_dl + need_ex)} · 디스크 여유 {human(free)}\n")
    if free < need_dl + need_ex + MARGIN_BYTES:
        print("🚨 디스크가 모자란다. 10GB 를 받다가 중간에 죽는 것 자체가 사고다 — 시작하지 않는다.")
        print(f"   여유를 최소 {human(need_dl + need_ex + MARGIN_BYTES)} 만들거나, "
              f"하나씩 받아라 (예: rirs 부터 · {human(CORPORA['rirs'].size)})")
        return 2

    failed = []
    for c in picked:
        print(f"\n── [{c.key}] {c.title}")
        if not download(c, force=force, rounds=rounds):
            failed.append(c.key)
            continue
        print(f"  md5 를 검사한다 ({human(c.size)} 라 몇 분 걸린다)")
        got = md5_of(c.archive_path, label=c.key)
        if got != c.md5:
            print(f"  ❌ md5 가 다르다: {got} ≠ {c.md5}")
            print("     받다 만 것이 섞였을 수 있다. 지우고 다시 받아라:")
            print(f"       del data\\corpora\\{c.archive}")
            failed.append(c.key)
            continue
        print(f"  ✅ md5 {got}")
        if not extract(c):
            failed.append(c.key)
            continue
        if drop_archive:
            # 🔑 순서를 지킨다 — md5 가 맞고 **푼 것이 확인된 뒤에만** 지운다.
            #    (2026-09-18에 소크 원본 1.18GB 를 지울 때도 파생을 먼저 검증했다)
            os.remove(c.archive_path)
            print(f"  🗑️ 압축파일을 지웠다 ({human(c.size)} 회수). "
                  f"⚠️ 다시 필요하면 {human(c.size)} 를 다시 받아야 한다")

    m = write_manifest()
    print("\n── 결과")
    for k, v in m["말뭉치"].items():
        inv = v["내용"]
        if inv:
            print(f"  [{k}] ✅ 풀림 — 파일 {inv['files']:,}개 · {human(inv['bytes'])}")
        else:
            print(f"  [{k}] ⬜ 없음")
    if failed:
        print(f"\n❌ 실패: {', '.join(failed)} — 같은 명령을 다시 돌리면 이어받는다")
        return 1
    print("\n✅ 끝났다 · 목록은 data/corpora/manifest.json")
    print("   다음은 M7 4단계(증강·학습 파이프라인 재작성)다 — 🔒 9/23부터. "
          "그건 scripts/train_wakeword.py 를 고친다")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="웨이크워드 학습용 공개 말뭉치 내려받기 (M7 2단계)")
    # 🔑 `choices=` 를 쓰지 않는다 — nargs="*" 와 같이 쓰면 argparse 가 **아무것도 안 넘겼을 때
    #    기본값 자체를 choices 에 대조**해 «invalid choice: []» 로 죽는다. 직접 검사한다.
    ap.add_argument("keys", nargs="*", help=f"받을 것: {' '.join(CORPORA)}")
    ap.add_argument("--all", action="store_true", help="셋 다 받는다 (내려받기 약 21GB)")
    ap.add_argument("--list", action="store_true", help="무엇을 왜 받는지 + 용량 + 디스크 여유")
    ap.add_argument("--verify", action="store_true", help="받아 둔 것만 검사한다 (md5 + 풀렸는지)")
    ap.add_argument("--inventory", action="store_true", help="manifest.json 만 다시 쓴다")
    ap.add_argument("--drop-archive", action="store_true",
                    help="푼 것을 확인한 뒤 압축파일을 지운다 (디스크 회수)")
    ap.add_argument("--force", action="store_true", help="이미 있어도 처음부터 다시 받는다")
    ap.add_argument("--retries", type=int, default=8,
                    help="끊겼을 때 다시 붙는 횟수 (기본 8). 받은 것은 버리지 않는다")
    a = ap.parse_args()

    unknown = [k for k in a.keys if k not in CORPORA]
    if unknown:
        print(f"❌ 모르는 이름: {', '.join(unknown)} — 쓸 수 있는 것은 {', '.join(CORPORA)} 다")
        return 2

    if a.list or (not a.keys and not a.all and not a.verify and not a.inventory):
        return cmd_list()
    if a.inventory:
        m = write_manifest()
        print("✅ data/corpora/manifest.json 을 다시 썼다")
        for k, v in m["말뭉치"].items():
            print(f"  [{k}] {'풀림' if v['풀림'] else '없음'}")
        return 0
    if a.verify:
        return cmd_verify()
    keys = list(CORPORA) if a.all else list(dict.fromkeys(a.keys))
    return cmd_fetch(keys, a.drop_archive, a.force, a.retries)


if __name__ == "__main__":
    sys.exit(main())
