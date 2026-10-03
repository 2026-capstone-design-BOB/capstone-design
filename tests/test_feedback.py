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
check("🚩 화면이 **그 턴을 가둬 둔다** (나중에 읽으면 다른 사건이 된다)",
      "const said = lastUserText, answered = text, when = repStamp()" in _UI)
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


print(f"{NL}결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
