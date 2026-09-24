# -*- coding: utf-8 -*-
"""메일 읽기 — *"밤새 온 메일 있어?"* (페르소나 §3-D · 2026-09-24)

인증은 [`tools/google_auth.py`](google_auth.py) 한 곳에서 받는다.
사용자 안내: [`docs/구글_연결.md`](../docs/구글_연결.md)

## 🔒 읽기만 한다 — 두 겹으로

| 겹 | 무엇 |
|---|---|
| ① 권한 | `gmail.readonly` — **보내기·초안·삭제가 계정 수준에서 불가능하다** |
| ② 도구 | `gmail_send` 라는 도구를 **아예 만들지 않았다** — 모델이 부를 수단이 없다 |

🔑 **둘 중 하나만으로는 부족하다.** 권한만 조이면 나중에 누가 범위를 넓히는 순간
도구가 생기고, 도구만 안 만들면 권한이 남아 있다. `close_app`/`force_close_app` 을
이름이 다른 도구로 가른 것과 같은 규칙이다.

## 🚨 여기가 이 저장소에서 **가장 사적인 자료**를 다루는 자리다

메일 본문은 화면 캡처보다 민감하다. 그리고 도구 결과는 **LLM 으로 그대로 올라가고**,
응답은 **TTS 로 소리 내어 읽힌다.** 사무실에서 쓰는 도구라는 것을 생각하면 그 둘이 다
위험이다. 그래서 셋을 지킨다.

1. 🚨 **나가기 전에 가린다.** 주민번호·카드번호·API 키를 **도구 안에서** 마스킹한다.
   그래프의 4층 마스킹은 **최종 응답**에만 걸리는데, 도구 결과는 그 전에 **이미 모델로
   올라가 있다.** 가리려면 여기서 가려야 한다.
2. 🚨 **분량을 자른다.** 목록은 제목·보낸이·시각까지, 본문은 앞부분만.
   «전부 읽어 주기»는 이 도구의 일이 아니다.
3. 🚨 **내용을 로그에 안 남긴다.** 몇 통인지까지만 남긴다.
   `logs/pluiz.log` 는 공유될 수 있는 파일이다.
"""
import base64
import logging
import re
from langchain_core.tools import tool

log = logging.getLogger("pluiz.gmail")

#: 한 번에 몇 통까지 보나. 목록이 길면 읽어 주기도 어렵고 토큰도 는다.
MAX_LIST = 15
#: 본문을 몇 글자까지 주나. 넘으면 잘렸다고 **말한다**.
MAX_BODY = 1500
#: 미리보기(목록에 붙는 한 줄)를 몇 글자까지.
MAX_SNIPPET = 60


def _mask(text: str) -> str:
    """🚨 **모델로 올라가기 전에** 가린다. (§위 ①)"""
    try:
        from core.security import mask_sensitive_output
        return mask_sensitive_output(text)
    except Exception as e:                                    # noqa: BLE001
        # 조용히 넘어가지 않는다 — 여기서 실패하면 **안 가린 채로 올라간다.**
        log.error("[메일] 마스킹 실패 — 안 가린 채로 나간다 | %s: %s",
                  type(e).__name__, e)
        return text


def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _pretty_sender(raw: str) -> str:
    """'홍길동 <a@b.com>' → '홍길동'. 이름이 없으면 주소 앞부분만."""
    raw = (raw or "").strip()
    m = re.match(r'^\s*"?([^"<]+?)"?\s*<', raw)
    if m:
        return m.group(1).strip()
    if "@" in raw:
        return raw.split("@")[0].strip("< ")
    return raw


def _when(msg: dict) -> str:
    """'화 14:03' 정도로. 정확한 날짜는 안 준다 — 목록이 읽기 어려워진다."""
    from datetime import datetime
    try:
        ts = int(msg.get("internalDate", "0")) / 1000
        d = datetime.fromtimestamp(ts)
        return d.strftime("%m/%d %H:%M")
    except Exception:
        return ""


def _build_query(sender: str, keyword: str, unread_only: bool, days: int) -> str:
    """구조화된 인자 → Gmail 검색어.

    🚨 **모델에게 검색어 문법을 맡기지 않는다.** `from:`·`newer_than:` 을 LLM 이 직접
      쓰게 하면 조용히 틀린 질의가 나가고, 그러면 **«메일 없어요»가 거짓말이 된다.**
      메일이 없는 것과 질의가 틀린 것은 사용자에게 똑같아 보인다.
    """
    parts = []
    if sender.strip():
        parts.append(f'from:({sender.strip()})')
    if keyword.strip():
        parts.append(f'({keyword.strip()})')
    if unread_only:
        parts.append("is:unread")
    if days and days > 0:
        parts.append(f"newer_than:{int(days)}d")
    return " ".join(parts) or "in:inbox"


def _fetch(service, query: str, limit: int) -> list[dict]:
    res = service.users().messages().list(
        userId="me", q=query, maxResults=max(1, min(limit, MAX_LIST))).execute()
    out = []
    for ref in res.get("messages", []):
        m = service.users().messages().get(
            userId="me", id=ref["id"], format="metadata",
            metadataHeaders=["From", "Subject"]).execute()
        out.append(m)
    return out


@tool
def list_emails(sender: str = "", keyword: str = "", unread_only: bool = False,
                days: int = 0, limit: int = 10) -> str:
    """받은 메일을 찾아 목록으로 알려줍니다. 본문은 주지 않고 보낸이·제목·시각만 봅니다.
    "밤새 온 메일 있어?", "김 팀장한테 온 메일 있어?", "안 읽은 메일 뭐 있어?" 에 씁니다.

    sender: 보낸 사람 이름이나 메일 주소 일부 (예: 김철수, @company.com)
    keyword: 제목·본문에 들어간 말
    unread_only: 안 읽은 것만 볼지
    days: 며칠 이내 것만 볼지 (0이면 제한 없음. "밤새"는 1)
    limit: 몇 통까지 (최대 15)
    """
    from tools.google_auth import NotConnected, get_service, message_for

    query = _build_query(sender, keyword, unread_only, days)
    try:
        service = get_service("gmail", "v1")
    except NotConnected as e:
        # 🚨 **막힌 이유마다 할 일이 다르므로 문장도 다르다.** 뭉뚱그리면
        #   설정을 제대로 끝낸 사람에게 «다시 하세요»라고 하게 된다(2026-09-24).
        return message_for(e)
    except Exception as e:                                    # noqa: BLE001
        return f"✗ 메일에 연결하지 못했어요 ({type(e).__name__}). 직접 확인해 보시겠어요?"

    try:
        msgs = _fetch(service, query, limit)
    except Exception as e:                                    # noqa: BLE001
        # 🚨 «메일이 없어요»로 떨어지지 않는다 — 못 읽은 것과 없는 것은 다르다.
        return f"✗ 메일을 읽지 못했어요 ({type(e).__name__}). 직접 확인해 보시겠어요?"

    # 🚨 몇 통인지까지만 남긴다. 제목도 보낸이도 로그에 안 쓴다.
    log.info("[메일] 목록 조회 | 조건=%r | %d통", query, len(msgs))

    if not msgs:
        what = []
        if sender.strip():
            what.append(f"'{sender.strip()}'님이 보낸")
        if unread_only:
            what.append("안 읽은")
        if days:
            what.append(f"{days}일 이내")
        label = " ".join(what) or "받은"
        return f"✓ {label} 메일이 없어요."

    lines = []
    for m in msgs:
        who = _pretty_sender(_header(m, "From"))
        subj = _header(m, "Subject") or "(제목 없음)"
        snip = (m.get("snippet") or "").strip()
        if len(snip) > MAX_SNIPPET:
            snip = snip[:MAX_SNIPPET] + "…"
        unread = "●" if "UNREAD" in (m.get("labelIds") or []) else " "
        piece = f"  {unread} {_when(m)} {who} — {subj}"
        if snip:
            piece += f"\n      {snip}"
        lines.append(piece)

    head = f"✓ 메일 {len(msgs)}통이에요 (● 는 안 읽은 것):"
    return _mask(head + "\n" + "\n".join(lines))


@tool
def read_email(sender: str = "", keyword: str = "") -> str:
    """메일 하나를 찾아 내용을 읽어 줍니다. "그 메일 뭐라고 왔어?", "요약해줘" 에 씁니다.
    조건에 맞는 메일이 여럿이면 읽지 않고 어느 것인지 되묻습니다.

    sender: 보낸 사람 이름이나 메일 주소 일부
    keyword: 제목·본문에 들어간 말
    """
    from tools.google_auth import NotConnected, get_service, message_for

    if not (sender.strip() or keyword.strip()):
        return "✗ 어느 메일인지 알려 주시겠어요? 보낸 사람이나 제목의 한 부분이면 돼요."

    try:
        service = get_service("gmail", "v1")
    except NotConnected as e:
        return message_for(e)
    except Exception as e:                                    # noqa: BLE001
        return f"✗ 메일에 연결하지 못했어요 ({type(e).__name__})."

    query = _build_query(sender, keyword, False, 0)
    try:
        res = service.users().messages().list(
            userId="me", q=query, maxResults=5).execute()
        refs = res.get("messages", [])
    except Exception as e:                                    # noqa: BLE001
        return f"✗ 메일을 읽지 못했어요 ({type(e).__name__})."

    if not refs:
        return "✓ 조건에 맞는 메일이 없어요."

    if len(refs) > 1:
        # 🚨 **여럿이면 고르지 않는다.** 엉뚱한 메일을 읽어 주면 그 내용이
        #   모델로도 가고 소리로도 나간다 — 되돌릴 수 없다.
        try:
            brief = []
            for r in refs[:4]:
                m = service.users().messages().get(
                    userId="me", id=r["id"], format="metadata",
                    metadataHeaders=["From", "Subject"]).execute()
                brief.append(f"  · {_pretty_sender(_header(m, 'From'))} — "
                             f"{_header(m, 'Subject') or '(제목 없음)'}")
            return _mask(f"✗ 조건에 맞는 메일이 {len(refs)}통이에요. 어느 것인가요?\n"
                         + "\n".join(brief))
        except Exception:
            return f"✗ 조건에 맞는 메일이 {len(refs)}통이에요. 좀 더 좁혀 주시겠어요?"

    try:
        full = service.users().messages().get(
            userId="me", id=refs[0]["id"], format="full").execute()
    except Exception as e:                                    # noqa: BLE001
        return f"✗ 메일을 읽지 못했어요 ({type(e).__name__})."

    body = _extract_body(full)
    who = _pretty_sender(_header(full, "From"))
    subj = _header(full, "Subject") or "(제목 없음)"

    truncated = ""
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY]
        truncated = f"\n\n(길어서 앞 {MAX_BODY}자까지만 읽었어요)"

    # 🚨 본문을 로그에 안 남긴다 — 길이만.
    log.info("[메일] 본문 조회 | %d자", len(body))

    return _mask(f"✓ {who}님이 보낸 '{subj}'\n\n{body.strip()}{truncated}")


def _extract_body(msg: dict) -> str:
    """본문 텍스트. HTML 만 있으면 태그를 걷어낸다."""
    def walk(part) -> str:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            return _decode(data)
        for p in part.get("parts", []) or []:
            got = walk(p)
            if got:
                return got
        if data and mime == "text/html":
            return re.sub(r"<[^>]+>", " ", _decode(data))
        return ""

    text = walk(msg.get("payload", {}) or {})
    if not text:
        text = msg.get("snippet", "") or ""
    # 빈 줄이 줄줄이 오는 메일이 많다 — 읽어 주기 좋게 줄인다
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")
    except Exception:
        return ""


# ── 📬 메일 기다리기 (백그라운드 · 2026-09-25) ─────────────────────
#
# *"메일 오면 알려줘"* — 페르소나 §3-J 의 마지막 빈칸이다. 화면 감시(`watch_screen`)
# 는 **화면에 보이는 것**만 볼 수 있어서 이 자리를 못 메운다.
#
# 🚨 **엔진은 `core/worker.py` 다 — 그래프 밖이다.** 노드를 async 로 만들면 승인이
#   깨진다(절대규칙 1). 여기 도구는 약속을 «얹고» 즉시 끝난다.
#
# 🔑 **지금 있는 메일은 안 알린다.** 처음 확인할 때 본 것을 «기준»으로 잡고,
#   그 뒤에 새로 생긴 것만 알린다. *"오면"* 은 미래를 가리키는 말이다 —
#   쌓여 있던 메일을 새 메일이라고 하면 그게 거짓말이다.

#: 한 번 확인할 때 몇 통까지 보나. 기다리기는 **몇 통 왔나**가 아니라
#: **왔나 안 왔나**를 보는 일이라 작게 잡는다(할당량·토큰 둘 다).
WATCH_PEEK = 5


class _InboxWatch:
    """받은 메일함을 되풀이해서 들여다보는 «확인 한 번». 워커가 주기적으로 부른다.

    반환은 `core/worker.py` 의 계약이다 —
    `{"done": False}` 면 «아직», `{"done": True, "text": …}` 면 «찾았다».
    """

    def __init__(self, sender: str = "", keyword: str = ""):
        self.sender = sender.strip()
        self.keyword = keyword.strip()
        self.query = _build_query(self.sender, self.keyword, False, 0)
        self.seen: set = set()
        self.baseline_done = False
        self.failures = 0

    #: 연속으로 이만큼 실패하면 **포기하고 알린다.** 계속 실패하면서 조용히
    #: 도는 것이 «기다리는 줄 알았는데 안 보고 있었다»가 된다.
    MAX_FAILURES = 3

    def __call__(self) -> dict:
        from tools.google_auth import NotConnected, get_service, message_for

        try:
            service = get_service("gmail", "v1")
            msgs = _fetch(service, self.query, WATCH_PEEK)
        except NotConnected as e:
            # 🔑 연결이 안 된 것은 **재시도해도 안 풀린다.** 바로 접고 이유를 말한다.
            return {"done": True,
                    "text": "📬 메일을 기다리려 했는데 막혔어요.\n"
                            + message_for(e)}
        except Exception as e:                                # noqa: BLE001
            self.failures += 1
            log.warning("[메일] 확인 실패 %d/%d | %s",
                        self.failures, self.MAX_FAILURES, type(e).__name__)
            if self.failures >= self.MAX_FAILURES:
                return {"done": True,
                        "text": f"⚠️ 메일을 {self.MAX_FAILURES}번 연속으로 확인하지 못해서 "
                                "기다리기를 멈췄어요. 직접 확인해 보시겠어요?"}
            return {"done": False}

        self.failures = 0
        ids = [m.get("id") for m in msgs if m.get("id")]

        if not self.baseline_done:
            # 첫 확인은 **기준을 잡는 것**이다. 알리지 않는다.
            self.seen = set(ids)
            self.baseline_done = True
            log.info("[메일] 기다리기 시작 | 조건=%r | 기준 %d통", self.query, len(ids))
            return {"done": False}

        fresh = [m for m in msgs if m.get("id") not in self.seen]
        self.seen.update(ids)
        if not fresh:
            return {"done": False}

        log.info("[메일] 새 메일 %d통", len(fresh))
        return {"done": True, "text": self._announce(fresh)}

    def _announce(self, msgs: list) -> str:
        lines = []
        for m in msgs:
            who = _pretty_sender(_header(m, "From"))
            subj = _header(m, "Subject") or "(제목 없음)"
            lines.append(f"  · {who} — {subj}")
        head = (f"📬 새 메일 {len(msgs)}통이 왔어요:" if len(msgs) > 1
                else "📬 새 메일이 왔어요:")
        # 🚨 본문은 안 싣는다. 이 문장은 **소리로도 읽힌다** — 알림은 «왔다»까지다.
        return _mask(head + "\n" + "\n".join(lines)
                     + '\n\n읽어 드릴까요? ("그 메일 읽어줘")')


@tool
def watch_inbox(sender: str = "", keyword: str = "", minutes: int = 60) -> str:
    """새 메일이 오면 먼저 알려줍니다. 지금 있는 메일은 알리지 않고,
    이제부터 새로 오는 것만 봅니다.
    "메일 오면 알려줘", "김 팀장한테 답장 오면 알려줘" 에 사용하세요.

    sender: 특정 사람이 보낸 것만 기다릴 때 (이름이나 메일 주소 일부)
    keyword: 제목·본문에 이 말이 든 것만 기다릴 때
    minutes: 몇 분까지 기다릴지 (기본 60분, 최대 60분)

    정해진 시간이 지나면 스스로 멈추고, 멈췄다고 알려줍니다.
    """
    from core.worker import KIND_POLL, get_worker
    from config.settings import get_settings

    s = get_settings()
    interval = int(getattr(s, "inbox_watch_interval", 120) or 120)
    cap = int(getattr(s, "inbox_watch_max_minutes", 60) or 60)
    minutes = max(1, min(int(minutes or cap), cap))

    what = "메일"
    if sender.strip():
        what = f"{sender.strip()}님 메일"
    if keyword.strip():
        what += f" ('{keyword.strip()}')"

    res = get_worker().add(
        kind=KIND_POLL,
        what=what,
        run=_InboxWatch(sender, keyword),
        delay=0.0,
        interval=interval,
        max_minutes=minutes,
        detail="메일 기다리기",
    )

    if res.get("added"):
        return (f"✓ {what}이(가) 오면 알려드릴게요.\n"
                f"{interval // 60}분마다 확인하고, {minutes}분 뒤에는 스스로 멈춰요. "
                "지금 와 있는 메일은 세지 않아요.\n"
                "⚠️ Pluiz 를 닫으면 기다리기도 멈춰요.\n"
                '그만두려면 "메일 기다리지 마" 라고 말씀해 주세요.')

    from tools.background import _add_failed
    return _add_failed(res)
