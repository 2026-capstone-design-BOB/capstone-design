# -*- coding: utf-8 -*-
"""화면에 보여줄 글 → **소리로 읽을 글** (2-2 ⓒ)

    from services.speech_text import to_speech
    to_speech("✓ '메모.txt' 파일을 바탕화면에 생성했습니다.\\n경로: C:/Users/a/Desktop/메모.txt")
    # → "'메모.txt' 파일을 바탕화면에 생성했습니다."

## 왜 이 모듈이 있나

`main.py` 가 응답 문자열을 **그대로** TTS 에 넘기고 있었다. 정제하는 곳이 한 군데도 없다.
그런데 우리 응답에는 **눈으로 볼 것**이 섞여 있다:

    ✓ '메모.txt' 파일을 바탕화면에 생성했습니다.
    경로: C:\\Users\\byeonsoyun\\Desktop\\메모.txt      ← 이걸 또박또박 읽는다

🔑 **이건 «응답이 길다»가 아니라 «말할 것과 보여줄 것을 안 갈랐다»는 문제다.**
2026-09-23 실측: 응답 221턴 중 **87%가 80자 이하**고 중앙값이 35자다. 길이 자체는
문제가 아니었고, 긴 꼬리(13%)도 대부분 정당했다 — 사용자가 *"용어가 어려워서
이해를 못 하겠어"* 라고 물은 턴이 688자인 것은 **맞는 답**이다.

📌 **지도교수가 실제 음성 사용자다**(9/22 피드백 ③). 화면을 안 보는 사람에게
경로와 기호는 **소음**이다.

## 🔑 한 곳에만 둔다

`services/tts.py::to_bytes_async()` 가 **모든** 음성 경로의 길목이다
(`/voice` · `/ws` · 감시 알림 · `speak_async`). 거기 한 번 걸면 호출부는 몰라도 된다.

🚨 **호출부 네 곳에 각각 넣지 않았다.** 감사 G-13·G-14 가 정확히 그 모양이었다 —
마스킹 호출이 «정상 완료» 한 곳에만 있었고 턴이 끝나는 길은 여덟이었다.
그때 배운 것이 *«호출을 일곱 군데 더 넣지 않는다. 관문을 만든다»* 이고,
`main.py::_broadcast` 에 이미 **`.replace(눈 이모지, " ")` 한 줄이 따로 박혀 있던 것**이
그 사고의 씨앗이다(복사본 하나가 먼저 생겨 있었다).

## 🚫 하지 않는 것

- **자르지 않는다.** 길이 상한은 «조용한 절단»이고 [BL-15](../docs/BACKLOG.md)가 그걸로 데인 자리다.
  말이 길면 길게 읽는다 — 짧게 만드는 것은 프롬프트의 몫이지 여기가 아니다.
- **말을 더하지 않는다.** 마커(`✓`/`✗`)를 떼되 «실패했어요» 같은 말을 **지어내지 않는다.**
  [BL-29 계약](../docs/design/BL-29_도구_결과_계약.md)상 `✗` 뒤에는 이미 사유 문장이 온다.
- **화면 텍스트를 바꾸지 않는다.** 이 함수의 결과는 **오직 TTS 입력**이다.
  경로는 화면에 그대로 남는다 — 사용자가 복사해야 할 수도 있다.
"""
from __future__ import annotations

import re

#: 상태 마커. **뜻은 뒤따르는 문장이 이미 담고 있다** — 기호만 뗀다.
#: 🚨 `✗`·`⚠️` 를 떼도 «실패가 성공처럼 들리지» 않는 이유가 여기다
#:   (BL-29 계약: 마커 뒤에는 사유 문장이 온다). 말을 **더하지는 않는다.**
_MARKERS = re.compile(r"[✓✗⚠️❌✅🔴🟡🟢🚨🔑📌⚡️▶️⏸️🆕🔄⏭️🎯🙋]")

#: 그 밖의 이모지·기호 (감정·그림 문자 영역). 읽을 수 없거나 읽으면 이상하다.
_EMOJI = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF" "\U0000FE0F" "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF" "]"
)

#: `경로: C:\\...` 줄 통째로. **화면에는 남는다.**
_PATH_LINE = re.compile(r"^\s*(?:경로|저장\s*위치|파일\s*경로)\s*[:：].*$", re.MULTILINE)

#: 문장 안에 박힌 절대 경로 → 파일 이름만. (`C:\a\b\메모.txt` → `메모.txt`)
_INLINE_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"]+")

#: URL → 도메인만. 전체를 읽으면 슬래시·물음표까지 다 읽는다.
_URL = re.compile(r"https?://([^\s/'\"]+)\S*")

#: 마크다운 강조·코드·머리글·표 구분선
_MD_EMPH = re.compile(r"(\*\*|__|\*|`+|~~)")
_MD_HEAD = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_RULE = re.compile(r"^\s*[-=*_]{3,}\s*$", re.MULTILINE)
_MD_BULLET = re.compile(r"^\s*[-*·•]\s+", re.MULTILINE)
_TABLE_PIPE = re.compile(r"\s*\|\s*")

#: 반복 공백·빈 줄
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{2,}")


def to_speech(text: str) -> str:
    """소리로 읽을 글만 남긴다. 화면 텍스트는 건드리지 않는다.

    ⚠️ **빈 문자열을 돌려줄 수 있다** — 응답이 마커와 경로뿐이었던 경우다.
      호출부(`to_bytes_async`)는 그때 **원문을 쓴다.** 침묵보다는 낫다.
    """
    if not text:
        return ""

    s = str(text)
    s = _PATH_LINE.sub("", s)
    s = _URL.sub(lambda m: m.group(1), s)
    s = _INLINE_PATH.sub(_basename, s)
    s = _MARKERS.sub(" ", s)
    s = _EMOJI.sub(" ", s)
    s = _MD_RULE.sub("", s)
    s = _MD_HEAD.sub("", s)
    s = _MD_BULLET.sub("", s)
    s = _MD_EMPH.sub("", s)

    # 표는 소리로 못 읽는다 — 칸 구분만 쉼표로 바꾼다
    if "|" in s:
        s = _TABLE_PIPE.sub(", ", s)

    s = _BLANKS.sub("\n", s)
    # 줄바꿈은 **문장 끝**처럼 읽혀야 한다. 마침표가 이미 있으면 덧붙이지 않는다.
    s = "\n".join(_end_sentence(ln.strip()) for ln in s.split("\n") if ln.strip())
    s = s.replace("\n", " ")
    s = _SPACES.sub(" ", s).strip()
    # 마커를 뗀 자리에 남는 군더더기
    s = re.sub(r"\s+([.,!?])", r"\1", s)
    s = re.sub(r"^[,.\s]+", "", s)
    return s


def _basename(m: re.Match) -> str:
    """경로에서 마지막 조각만. 폴더로 끝나면 그 폴더 이름."""
    raw = m.group(0).replace("\\", "/").rstrip("/")
    return raw.rsplit("/", 1)[-1] or raw


def _end_sentence(line: str) -> str:
    """줄 끝이 문장부호가 아니면 마침표를 붙인다 — 안 붙이면 다음 줄과 붙어 읽힌다."""
    if not line:
        return line
    return line if line[-1] in ".!?…:;," else line + "."
