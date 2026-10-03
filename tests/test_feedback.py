# -*- coding: utf-8 -*-
"""🚩 신고하기 — **규칙을 부탁하지 않고 구조로 지킨다** (2026-10-03 신설)

실행: python tests/test_feedback.py

## 왜 이 테스트가 있나

`docs/teamwork/사용_피드백.md` 는 적을 때 지킬 것 **셋**을 부탁하고 있었다.

| | 부탁 | 안 지켜지면 |
|---|---|---|
| ① | 증상만. **원인은 적지 마세요** | 추측을 먼저 믿고 엉뚱한 데를 판다 (2026-10-02 에 셋 다 틀리게 짚었다) |
| ② | **말한 그대로** | 「좀」 같은 군말에서 실제로 걸린 적이 있다 (BL-43·48) |
| ③ | **시각을 분까지** | 로그에서 못 찾아 **적어 준 것이 버려진다** |

🔑 셋 다 «부탁»이었다. 이 저장소가 반복해서 적어 둔 문장이 그 자리다 —
*«프롬프트는 확률을 올릴 뿐이고 보장하는 건 구조다»*.

**그래서 이 테스트는 «잘 적혔나»가 아니라 «못 어기게 돼 있나»를 센다.**
①은 **칸이 없는가**, ②③은 **앱이 채우는가**로 잰다.

## ⚠️ 사람이 쓴 보고를 건드리지 않는다

`_testenv` 가 `PLUIZ_FEEDBACK_FILE` 을 임시 경로로 돌린다(BL-11 계열).
그게 실제로 돌아갔는지도 ⑥에서 **센다** — 안 돌면 이 테스트가 사용자 파일을 고친다.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

import core.feedback as F  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)
_SRC = io.open(os.path.join(_ROOT, "core", "feedback.py"), encoding="utf-8").read()
_MAIN = io.open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
_UI = io.open(os.path.join(_ROOT, "electron-ui", "renderer", "index.html"),
              encoding="utf-8").read()

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ FAIL {name}" + (f"   → {detail}" if detail else ""))


# ═══ ① 🚨 **«원인»을 적을 칸이 없다** ══════════════════════════════
#
#   이게 이 기능의 핵심이다. 칸이 있으면 언젠가 채워지고, 채워지면 믿게 된다.
print(f"{NL}=== ① \U0001f6a8 「왜 그런 것 같나」를 받는 칸이 없다 ===")
import inspect  # noqa: E402
_params = set(inspect.signature(F.build_report).parameters)
for bad in ("cause", "reason", "why", "guess", "원인"):
    check(f"`{bad}` 라는 인자가 **없다**", bad not in _params, str(sorted(_params)))
check("🚨 서버도 원인을 안 받는다 (FeedbackRequest)",
      "cause" not in _MAIN.split("class FeedbackRequest")[1].split("def ")[0])
check("🚨 화면에도 원인 칸이 없다",
      "rep-cause" not in _UI and "원인" not in _UI.split('id="rep-view"')[1].split("</div>")[0])
check("왜 없는지 **적어 뒀다** (다음 사람이 «빠뜨린 것»으로 보고 추가하지 않게)",
      "칸을 만들지 않는다" in _SRC or "없는 칸은 못 채운다" in _SRC)


# ═══ ② 🚨 **말한 그대로와 시각은 앱이 채운다** ══════════════════════
print(f"{NL}=== ② \U0001f6a8 사람이 옮겨 적지 않는다 ===")
md = F.build_report("bug", said="볼륨 좀 올려줘", answered="볼륨을 올렸어요",
                    when="2026-10-03 14:32:10", expected="소리가 커질 줄 알았어요")
check("🚨 **군말이 그대로 남는다** («좀» 을 다듬지 않는다)", "볼륨 좀 올려줘" in md, md)
check("시각이 **분·초까지** 들어간다", "2026-10-03 14:32:10" in md, md)
check("기대한 것이 들어간다", "소리가 커질 줄 알았어요" in md, md)
check("🚩 화면이 **내가 한 말을 그 자리에서 가둔다** (나중에 읽으면 다른 사건이 된다)",
      "const said = (" in _UI and "const when = repStamp()" in _UI)
check("   시각을 **보는 그 순간** 찍는다", "function repStamp()" in _UI)

# 시각을 안 주면 **지금**으로 채운다 — 비는 일이 없어야 한다
_blank = F.build_report("bug", "x", "y")
check("🚨 시각을 안 줘도 **비지 않는다**",
      "| **언제** | 20" in _blank, _blank)


# ═══ ③ 🔒 **이름을 받지 않는다** ════════════════════════════════════
#
#   저장소가 public 이다. 실명이 한 번 들어가면 커밋 기록에 남는다.
print(f"{NL}=== ③ \U0001f512 고를 수 없는 것은 적을 수도 없다 ===")
check("고를 수 있는 표시가 정해져 있다", F.WHO == ("팀원 A", "팀원 B", "개발자"), str(F.WHO))
check("🚨 **목록에 없는 이름은 안 들어간다**",
      "변소윤" not in F.build_report("bug", "x", "y", who="변소윤"))
check("   대신 기본 표시로 떨어진다",
      "팀원 A" in F.build_report("bug", "x", "y", who="변소윤"))
check("화면도 **고르는 상자**다 (자유 입력이 아니다)",
      '<select class="fav-input" id="rep-who">' in _UI)


# ═══ ④ 🚨 **로그는 마스킹을 거친다** ════════════════════════════════
#
#   `.env.example` 이 *«로그는 출력 마스킹을 거치지 않습니다»* 라고 적어 뒀다.
#   보고서로 나갈 때는 거쳐야 한다.
print(f"{NL}=== ④ \U0001f6a8 나갈 때는 가린다 ===")
_key = "AIza" + "B" * 30
_secret = F.build_report("bug", said=f"키가 {_key} 야", answered="네")
check("🚨 **API 키가 보고서에 그대로 안 나간다**", _key not in _secret, _secret)
check("   가렸다고 표시한다", "마스킹됨" in _secret, _secret)
_rrn = F.build_report("bug", said="950101-1234567", answered="네")
check("🚨 주민번호도 가린다", "1234567" not in _rrn, _rrn)


# ═══ ⑤ 보고는 **쌓인다** (덮어쓰지 않는다) ══════════════════════════
print(f"{NL}=== ⑤ 하나를 잃으면 그 일은 없던 일이 된다 ===")
if os.path.exists(F.REPORT_PATH):
    os.remove(F.REPORT_PATH)
F.append_report(F.build_report("bug", "첫 번째", "답1", "2026-10-03 10:00:00"))
F.append_report(F.build_report("good", "두 번째", "답2", "2026-10-03 11:00:00"))
_all = F.read_all()
check("둘 다 남아 있다", "첫 번째" in _all and "두 번째" in _all, _all[:200])
check("🚨 **최신이 위다**", _all.index("두 번째") < _all.index("첫 번째"))
check("개수를 센다", F.count() == 2, str(F.count()))
check("머리말이 **한 번만** 있다", _all.count("# 써 보고 느낀 것") == 1)
check("🚨 머리말이 **저장소에 올리지 말라**고 말한다", ".gitignore" in _all)

_gi = io.open(os.path.join(_ROOT, ".gitignore"), encoding="utf-8").read()
check("🚨 **실제로 `.gitignore` 에 걸려 있다**", "사용_피드백_보고.md" in _gi)
check("   사본까지 막는다 (`*`) — 10-02 에 이름이 조금 다른 사본이 빠져나갔다",
      "사용_피드백_보고.md*" in _gi)


# ═══ ⑥ 🔒 **사람이 쓴 보고를 건드리지 않는다** ══════════════════════
print(f"{NL}=== ⑥ \U0001f512 테스트가 사용자 파일을 고치지 않는다 ===")
check("🚨 **임시 경로로 돌아가 있다** (안 그러면 지금 사용자 파일을 고친 것이다)",
      os.path.join("logs", "사용_피드백_보고.md") not in F.REPORT_PATH, F.REPORT_PATH)
check("환경변수를 **존중한다**", "PLUIZ_FEEDBACK_FILE" in _SRC)
check("_testenv 가 그 변수를 돌린다",
      "PLUIZ_FEEDBACK_FILE" in io.open(
          os.path.join(_ROOT, "tests", "_testenv.py"), encoding="utf-8").read())


# ═══ ⑦ 로그가 없어도 **보고를 막지 않는다** ═════════════════════════
print(f"{NL}=== ⑦ 로그를 못 읽어도 신고는 된다 ===")
_keep = os.environ.get("PLUIZ_LOG_DIR")
os.environ["PLUIZ_LOG_DIR"] = os.path.join(_ROOT, "없는폴더_테스트용")
try:
    check("로그가 없으면 **빈 목록**을 준다 (죽지 않는다)",
          F.log_excerpt("2026-10-03 10:00:00") == [])
    _no_log = F.build_report("bug", "x", "y", log_lines=[])
    check("   그래도 보고서는 만들어진다", "| **언제** |" in _no_log)
    check("   로그 칸은 아예 안 붙는다", "<details>" not in _no_log)
finally:
    if _keep is None:
        os.environ.pop("PLUIZ_LOG_DIR", None)
    else:
        os.environ["PLUIZ_LOG_DIR"] = _keep


# ═══ ⑧ 🚨 **도구로 만들지 않았다** ══════════════════════════════════
#
#   음성으로 «신고해줘»를 부를 수 있으면 LLM 이 사용자의 말을 **요약해서**
#   넣는다. 그러면 ②(말한 그대로)가 그 자리에서 깨진다.
print(f"{NL}=== ⑧ \U0001f6a8 LLM 이 대신 적지 않는다 ===")
from core.tool_registry import get_all_tools  # noqa: E402
_names = {t.name for t in get_all_tools()}
check("🚨 **신고 도구가 없다**",
      not any("feedback" in n or "report_bug" in n for n in _names), str(sorted(_names)[:5]))
check("왜 안 만들었는지 적어 뒀다", "도구로 만들지 않았다" in _MAIN)


# ═══ ⑨ 화면이 **보낼 내용을 먼저 보여준다** (🙋 2026-10-03 결정) ════
print(f"{NL}=== ⑨ 보내기 전에 눈으로 본다 ===")
check("로그 미리보기 칸이 있다", 'id="rep-log"' in _UI)
check("🚨 **끌 수 있다**", 'id="rep-with-log"' in _UI)
check("   끄면 다시 그린다", 'onchange="refreshDraft()"' in _UI)
check("서버가 **쓰지 않고 만들어만 주는** 길이 따로 있다",
      '@app.post("/api/feedback/draft")' in _MAIN)
# 🚨 `[0]` 이다 — draft 데코레이터 **다음부터 그 다음 데코레이터 전까지**가
#   그 함수의 몸이다. `[1]` 로 잡으면 **저장 쪽을 보게 돼서** 이 줄이
#   «파일을 건드린다»고 거짓 경보를 울린다 (처음에 그렇게 적어서 깨졌다).
_draft_body = _MAIN.split('@app.post("/api/feedback/draft")')[1].split("@app.")[0]
check("   그 길은 파일을 안 건드린다",
      "append_report" not in _draft_body, _draft_body[:120])
check("🚨 클릭이 삼켜지지 않게 **no-drag 를 적었다** (10-02 에 겪은 CSS)",
      ".rep-btn" in _UI and "-webkit-app-region: no-drag" in
      _UI.split(".rep-btn {")[1].split("}")[0])


# ═══ ⑩ 보낸 뒤 **어디로 갔는지 말한다** ═════════════════════════════
print(f"{NL}=== ⑩ 보냈는데 어디 갔는지 모르면 전달을 못 한다 ===")
check("저장하면 **경로를 돌려준다**", '"path": path' in _MAIN)
check("   누적 개수도", '"count": feedback.count()' in _MAIN)
check("화면이 그 경로를 **보여준다**", "data.path" in _UI)
check("🔑 **전부 복사**도 된다 (파일을 찾는 것보다 쉽다)",
      "copyAllReports" in _UI and "clipboard.writeText" in _UI)


# ═══ ⑪ 🚨 **답을 «누를 때» 읽는다** (2026-10-03 같은 날 잡음) ════════
#
#   처음에 만들 때 가뒀더니 **스트리밍이 빈 답을 신고**했다.
#   텍스트 명령은 `type:'start'` 에서 `addMsg('a', '')` 로 **빈 칸부터** 만들고
#   조각을 채운다. 즉 만드는 순간의 `text` 는 **언제나 빈 문자열**이다.
#
#   🔑 테스트가 «46/46 통과» 였는데도 못 잡았다. ②가 `build_report` 에
#     넘긴 값만 봤고, **화면이 무엇을 넘기는지**는 안 봤기 때문이다 —
#     BL-92 에서 배운 *«안 고르는 쪽만 세고 좁히는 쪽을 안 쟀다»* 와 같은 모양이다.
print(f"{NL}=== ⑪ \U0001f6a8 스트리밍이 빈 답을 신고하지 않는다 ===")
_add = _UI.split("function addMsg(")[1].split(f"{NL}    function esc(")[0]

check("🚨 **누를 때 말풍선에서 읽는다**",
      "const bbl = el.querySelector('.bbl')" in _add
      and "openReport(said, bbl ? bbl.textContent : text, when, flag)" in _add, _add[:200])
check("🚨 **만들 때 답을 가두지 않는다** (가두면 빈 문자열이다)",
      "answered = text" not in _add, _add[:200])
check("   왜 그런지 적어 뒀다 (다음 사람이 «최적화»로 되돌리지 않게)",
      "빈 답을 신고" in _add)
check("스트리밍이 실제로 **빈 칸부터** 만든다 (이 전제가 깨지면 위가 무의미해진다)",
      "addMsg('a', '')" in _UI)

# 반대로 **내가 한 말과 시각은** 만들 때 가둬야 한다 — 양쪽을 같이 센다.
check("🔒 반대로 **내가 한 말은 지금** 가둔다", "const said = (" in _add)
check("🔒 **시각도 지금** 찍는다", "const when = repStamp()" in _add)


# ═══ ⑫ 🚨 **꾸민 글자가 «말한 그대로»에 안 섞인다** ══════════════════
print(f"{NL}=== ⑫ \U0001f6a8 음성·알림이 엉뚱한 말을 싣지 않는다 ===")
check("🚨 음성은 화면엔 `🎤`, 신고엔 **말 그대로**",
      "addMsg('u', '🎤 ' + data.text, { raw: data.text })" in _UI, "")
check("   `raw` 가 실제로 쓰인다", "('raw' in o) ? (o.raw || '') : text" in _add, _add[:300])
check("🚨 **알림은 «시킨 턴»이 아니다** — 직전 말을 안 싣는다",
      "addMsg('a', m.text || '', { said: '' })" in _UI)
check("   마이크 실패도 마찬가지 (말한 적이 없다)",
      "마이크 접근 실패: ' + err.message, { said: '' }" in _UI)
check("   `said` 를 비우면 **비운 채로** 간다 (기본값으로 안 떨어진다)",
      "('said' in o) ? (o.said || '') : lastUserText" in _add, _add[:300])

# 말이 없는 신고도 **보고서가 만들어져야** 한다 — 알림이 그 경우다.
_quiet = F.build_report("bug", said="", answered="물 마실 시간이에요",
                        when="2026-10-03 15:00:00")
check("말 없이 일어난 일도 보고서가 된다",
      "말 없이 일어났어요" in _quiet and "물 마실 시간이에요" in _quiet, _quiet)

# ═══ ⑬ 🚨 **못 보낸 것과 못 적은 것은 다른 일이다** (수신기 · 2026-10-03) ══
#
#   «보냈다»고 거짓말하면 팀원이 파일을 안 보낸다 — 그러면 보고가 그 PC 에서
#   끝난다. 이 저장소가 «안 한 걸 했다고 말하기»로 반복해 데인 자리다
#   (BL-12 · BL-19 · BL-26 · BL-35).
print(f"{NL}=== ⑬ \U0001f6a8 보내기가 실패해도 보고는 남는다 ===")
_WEB = os.path.join(_ROOT, "feedback-web")

check("🚨 **기본이 «안 보냄»이다** (설정 안 하면 밖으로 안 나간다)",
      F.send_report("### 아무거나")[0] is False)
check("   왜 못 보냈는지 말한다", "설정" in F.send_report("### 아무거나")[1],
      F.send_report("### 아무거나")[1])

_keep = os.environ.get("PLUIZ_FEEDBACK_ENDPOINT")
os.environ["PLUIZ_FEEDBACK_ENDPOINT"] = "http://127.0.0.1:9/없는주소"
os.environ["PLUIZ_FEEDBACK_KEY"] = "x"
try:
    _ok, _why = F.send_report("### 아무거나")
    check("🚨 **닿지 못해도 예외를 올리지 않는다**", _ok is False and bool(_why), _why)
finally:
    os.environ.pop("PLUIZ_FEEDBACK_KEY", None)
    if _keep is None:
        os.environ.pop("PLUIZ_FEEDBACK_ENDPOINT", None)
    else:
        os.environ["PLUIZ_FEEDBACK_ENDPOINT"] = _keep

# 🚨 순서가 계약이다 — 파일에 **먼저** 쓰고 그 다음에 보낸다.
_save_body = _MAIN.split('@app.post("/api/feedback")')[1].split("@app.")[0]
check("🚨 **파일에 먼저 쓰고 나서 보낸다** (순서가 뒤집히면 보고를 잃는다)",
      _save_body.index("append_report") < _save_body.index("send_report"), "")
check("   보냈는지를 **따로** 돌려준다",
      '"sent": sent' in _save_body and '"sent_error": why' in _save_body)
check("🚨 화면이 **«적었다»와 «보냈다»를 가른다**",
      "data.sent" in _UI and "전달은 안 됐어요" in _UI)
check("   못 보냈으면 **파일을 보내라고** 안내한다",
      "이 파일을 변소윤에게 보내거나" in _UI)


# ═══ ⑭ 🔒 **수신기의 비밀이 둘이다** ════════════════════════════════
#
#   하나로 합치면 팀원 PC 에 깔린 키로 **남의 보고를 전부 읽을 수 있다.**
print(f"{NL}=== ⑭ \U0001f512 보내는 키로는 볼 수 없다 ===")


def _web(*parts):
    return io.open(os.path.join(_WEB, *parts), encoding="utf-8").read()


check("수신기가 저장소에 있다", os.path.isdir(_WEB))
_report_js, _list_js = _web("api", "report.js"), _web("api", "list.js")
check("🚨 **보내기는 `INGEST_KEY`**", "process.env.INGEST_KEY" in _report_js)
check("🚨 **보기는 `VIEW_PASSWORD`** (다른 비밀이다)",
      "process.env.VIEW_PASSWORD" in _list_js)
# 🔑 **`process.env.` 까지 보고 센다.** 그냥 이름만 찾으면 «왜 둘로 갈랐는지»
#   적어 둔 주석에 걸려 깨진다 — 설명을 지우게 만드는 테스트는 나쁜 테스트다.
check("   보기 쪽이 `INGEST_KEY` 를 **안 읽는다**",
      "process.env.INGEST_KEY" not in _list_js)
check("   보내기 쪽이 `VIEW_PASSWORD` 를 **안 읽는다**",
      "process.env.VIEW_PASSWORD" not in _report_js)
check("🔒 비밀 비교가 **상수시간**이다 (한 글자씩 맞춰 보지 못하게)",
      "timingSafeEqual" in _web("api", "_guard.js"))
check("🚨 서버에 비밀이 없으면 **전부 거부**한다 (fail-closed)",
      "if (!expected) return false" in _web("api", "_guard.js"))
check("🔒 검색엔진에 안 걸리게 해 뒀다", "noindex" in _web("vercel.json"))
check("🔒 보기 비밀번호를 **주소줄에 안 싣는다** (URL 은 기록에 남는다)",
      "'x-view-key': pw" in _web("public", "index.html"))
check("보고 크기에 상한이 있다 (한 건으로 저장소를 채우지 못하게)",
      "MAX_BYTES" in _report_js and "413" in _report_js)
check("쌓이는 개수에도 상한이 있다", "ltrim" in _report_js)

check("🚨 비밀이 **저장소에 안 올라간다**",
      "INGEST_KEY=" not in io.open(os.path.join(_ROOT, ".env.example"),
                                   encoding="utf-8").read())
_gi_web = io.open(os.path.join(_WEB, ".gitignore"), encoding="utf-8").read()
check("   수신기 쪽도 `.env` 를 막아 뒀다", ".env" in _gi_web)
check("올리는 법이 적혀 있다 (다음 사람이 처음부터 알아내지 않게)",
      "vercel env add INGEST_KEY" in _web("README.md"))
check("🚨 **여기가 원본이 아니라는 것**을 README 가 못 박는다",
      "원본이 아닙니다" in _web("README.md"))

# 🔑 **소스 대조로 끝내지 않는다**(BL-83). 수신기를 실제로 불러 돌리는 검사가
#   따로 있다 — `cd feedback-web && npm test`. 파이썬 스위트가 node 를 부르지
#   않는 이유는 CI(ubuntu·python만)와 설치 환경을 묶지 않기 위해서다.
check("수신기에 **실제로 돌려 보는 검사**가 있다",
      os.path.exists(os.path.join(_WEB, "test.mjs")))
check("   그 검사가 **비밀 둘이 서로 못 넘나든다**를 센다",
      "보내기 키로 보기 거부" in _web("test.mjs")
      and "보기 비번으로 넣기 거부" in _web("test.mjs"))
check("   `npm test` 로 돌아간다",
      '"test": "node test.mjs"' in _web("package.json"))
check("🔒 그 검사가 **진짜 Redis 를 안 쓴다** (사람이 보낸 보고를 건드리면 안 된다)",
      "Redis.fromEnv = () =>" in _web("test.mjs"))

# ═══ ⑮ 🚨 **`.env` 에 적은 것이 실제로 닿는다** (2026-10-03 같은 날 잡음) ══
#
#   처음엔 `os.environ` 만 봤다. 그런데 이 프로젝트의 `.env` 는 pydantic 이
#   **설정 객체로만** 읽고 `os.environ` 에는 **안 넣는다.** 그래서 팀원이
#   `.env` 에 적어도 **조용히 안 보냈다** — «설정했는데 안 되고, 왜 안 되는지도
#   안 보이는» 가장 나쁜 모양이다.
#
#   🔑 그리고 이름도 틀렸었다. pydantic 은 필드 `feedback_endpoint` 를
#     **`FEEDBACK_ENDPOINT`** 로 찾는데 `PLUIZ_FEEDBACK_ENDPOINT` 라고 적어 뒀다.
#     `GEMINI_API_KEY` 처럼 **접두사가 없는 것**이 이 프로젝트의 규약이다.
print(f"{NL}=== ⑮ \U0001f6a8 .env 에 적은 것이 send_report 까지 닿는다 ===")
import shutil, tempfile  # noqa: E402

_work = os.path.join(tempfile.gettempdir(), "pluiz_fb_envtest")
shutil.rmtree(_work, ignore_errors=True)
os.makedirs(_work)
io.open(os.path.join(_work, ".env"), "w", encoding="utf-8").write(
    "FEEDBACK_ENDPOINT=https://example.invalid/api/report" + NL
    + "FEEDBACK_KEY=from-dotenv" + NL)

_cwd = os.getcwd()
_saved = {v: os.environ.pop(v, None) for v in (F.ENDPOINT_ENV, F.KEY_ENV)}
try:
    os.chdir(_work)                      # pydantic 은 **현재 폴더**의 .env 를 읽는다
    from config.settings import get_settings  # noqa: E402
    get_settings.cache_clear()           # 절대규칙 4 — 안 하면 옛 값이 그대로다
    _u, _k = F._destination()
    check("🚨 **`.env` 에서 주소를 읽는다** (`os.environ` 만 보면 안 된다)",
          _u == "https://example.invalid/api/report", _u)
    check("🚨 `.env` 에서 키도 읽는다", _k == "from-dotenv", _k)
    check("   그래서 **실제로 보내기를 시도한다**",
          F.send_report("### x")[1].startswith("수신기에"), F.send_report("### x")[1])
finally:
    os.chdir(_cwd)
    for v, old in _saved.items():
        if old is not None:
            os.environ[v] = old
    get_settings.cache_clear()
    shutil.rmtree(_work, ignore_errors=True)

_cfg = io.open(os.path.join(_ROOT, "config", "settings.py"), encoding="utf-8").read()
check("설정에 **필드가 있다** (없으면 `.env` 를 아예 안 읽는다)",
      "feedback_endpoint: str" in _cfg and "feedback_key: str" in _cfg)
check("🚨 `.env.example` 이 **접두사 없는 이름**으로 안내한다",
      "# FEEDBACK_ENDPOINT=" in io.open(os.path.join(_ROOT, ".env.example"),
                                        encoding="utf-8").read())
check("   `PLUIZ_` 가 붙은 이름으로 **잘못 안내하지 않는다**",
      "PLUIZ_FEEDBACK_ENDPOINT=" not in io.open(
          os.path.join(_ROOT, ".env.example"), encoding="utf-8").read())
check("   수신기 README 도 같은 이름을 쓴다",
      "FEEDBACK_ENDPOINT=" in _web("README.md")
      and "PLUIZ_FEEDBACK_ENDPOINT" not in _web("README.md"))
check("🔑 `os.environ` 쪽 이름은 **덮어쓰기용**이라고 적어 뒀다",
      "덮어쓰기용" in _SRC)

print(f"{NL}결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
