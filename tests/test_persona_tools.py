# -*- coding: utf-8 -*-
"""페르소나 🟢 묶음 11개의 계약 — **늘린 만큼 규칙도 늘어야 한다**

실행: python tests/test_persona_tools.py

## 왜 이 테스트가 있나

2026-09-24 에 도구를 **47 → 58** 로 늘렸다([페르소나 §5](../docs/planning/페르소나_직장인.md)).
그런데 이 저장소가 도구를 늘릴 때마다 **같은 자리에서 세 번 데였다.**

| | 사고 | 남은 규칙 |
|---|---|---|
| ① | 쓰기만 만들고 읽기를 안 만들어 *"지금 밝기 얼마야"* 가 **값을 지어냈다**(BL-60·61) | 📏 **읽기·쓰기를 한 쌍으로** |
| ② | 토글 하나로 둬서 *"소리 켜 줘"* 가 **소리를 껐다**(2026-09-23 실기) | 📏 **방향을 도구 이름에** |
| ③ | 위험 도구를 `DANGEROUS_TOOLS` 에 **나중에 넣기로** 했다가 안 넣었다 | 📏 **만들 때 넣는다** |

🚨 **셋 다 «코드가 틀린 것»이 아니라 «규칙을 안 지킨 것»이다.** 그래서 여기서는
동작이 아니라 **규칙을 검사한다.**

## 여기서 고정하는 것 여섯

1. 🚨 **되돌릴 수 있나로 승인이 갈린다.** `move_file`·`rename_file` 은 승인 대상이고
   `copy_file` 은 아니다. 판별은 «원본이 남나» 한 줄이다.
2. 🚨 **옮기기·이름변경은 재귀 탐색을 안 한다.** 승인 질문은 이름만 보여주므로,
   하위 폴더의 다른 파일이 잡히면 사용자가 알 수 없다. `_locate_for_open` 이
   삭제에 대해 못 박아 둔 비대칭과 같은 자리다.
3. **알림은 방향을 가진 둘 + 읽는 하나.** ②의 사고를 되풀이하지 않는다.
4. **일정은 읽기·쓰기 한 쌍.** ①의 사고를 되풀이하지 않는다.
5. 🚨 **«못 읽었다»와 «없다»를 섞지 않는다.** 캘린더를 못 읽었는데 «일정이 없어요»가
   나가면 사용자가 회의를 놓친다.
6. 🚨 **검사 도구가 찾은 값을 되돌려주지 않는다.** 돌려주면 가리려고 만든 도구가
   응답·로그·TTS 로 새는 구멍이 된다.

## ⚠️ 여기서 실제로 시스템을 건드리지 않는다

알림 레지스트리도 안 쓰고, 파일도 임시 폴더에서만 만진다. 화면 유지는 걸지 않는다.
"""
import io
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")


def _src(rel):
    """🚨 encoding='utf-8' — 한글 소스를 cp949 로 읽으면 터진다 (CLAUDE.md 7)."""
    return io.open(os.path.join(_ROOT, rel), encoding="utf-8").read()


def run():
    from core.tool_registry import get_all_tools
    from core.graph import DANGEROUS_TOOLS, READONLY_RETRY_TOOLS
    import tools.filesystem as FS

    names = {t.name for t in get_all_tools()}
    FS_SRC = _src("tools/filesystem.py")

    print("=== ① 열한 개가 실제로 등록됐는가 ===")
    added = ["copy_file", "move_file", "rename_file", "switch_window",
             "list_calendar_events", "notifications_off", "notifications_on",
             "get_notifications_status", "keep_awake", "allow_sleep", "scan_sensitive"]
    for n in added:
        check(f"{n} 등록", n in names)
    check("이름이 겹치지 않는다", len(names) == len({t.name for t in get_all_tools()}))

    print(f"{NL}=== ② 🚨 승인은 «되돌릴 수 있나»로 갈린다 ===")
    check("🚨 move_file 은 승인 대상 (어디로 갔는지 모르면 못 되돌린다)",
          "move_file" in DANGEROUS_TOOLS)
    check("🚨 rename_file 은 승인 대상 (옛 이름을 모르면 못 되돌린다)",
          "rename_file" in DANGEROUS_TOOLS)
    check("🚨 copy_file 은 승인 대상이 **아니다** (원본이 그대로 남는다)",
          "copy_file" not in DANGEROUS_TOOLS)
    check("switch_window 도 승인 대상이 아니다 (아무것도 안 지운다)",
          "switch_window" not in DANGEROUS_TOOLS)
    check("알림·화면유지도 승인 대상이 아니다 (한 마디로 되돌아온다)",
          not ({"notifications_off", "notifications_on", "keep_awake",
                "allow_sleep"} & DANGEROUS_TOOLS))
    check("🚨 scan_sensitive 는 재시도 화이트리스트에 **없다** (클립보드를 또 읽는다)",
          "scan_sensitive" not in READONLY_RETRY_TOOLS)

    print(f"{NL}=== ③ 🚨 옮기기·이름변경은 재귀 탐색을 안 한다 ===")
    # 소스에서 각 함수 본문만 떼어 본다 — 문서가 아니라 **코드**가 지키는지 본다.
    def _body(fn, src=FS_SRC):
        i = src.index(f"def {fn}(")
        nxt = [src.find(f"{NL}@tool", i), src.find(f"{NL}def ", i + 10)]
        nxt = [x for x in nxt if x > 0]
        return src[i:min(nxt)] if nxt else src[i:]

    check("🚨 move_file 본문에 _locate_for_open 이 없다",
          "_locate_for_open" not in _body("move_file"))
    check("🚨 rename_file 본문에도 없다",
          "_locate_for_open" not in _body("rename_file"))
    check("copy_file 은 탐색을 쓴다 (원본이 안 사라져 최악이 «사본 하나»다)",
          "_locate_for_open" in _body("copy_file"))
    check("왜 가르는지가 코드 옆에 적혀 있다",
          "승인 질문은" in FS_SRC and "이름만" in FS_SRC)

    print(f"{NL}=== ④ 파일 셋이 실제로 계약대로 도는가 (임시 폴더) ===")
    tmp = tempfile.mkdtemp(prefix="pluiz_persona_")
    try:
        src_dir = os.path.join(tmp, "src")
        dst_dir = os.path.join(tmp, "dst")
        os.makedirs(src_dir)
        os.makedirs(dst_dir)
        a = os.path.join(src_dir, "보고서.txt")
        with io.open(a, "w", encoding="utf-8") as f:
            f.write("내용")

        r = FS.copy_file.invoke({"file_path": a, "destination": dst_dir})
        check("copy_file 성공 마커", r.startswith("✓"), r)
        check("🔑 원본이 그대로 있다 (그래서 승인이 없다)", os.path.exists(a))
        check("사본이 생겼다", os.path.exists(os.path.join(dst_dir, "보고서.txt")))

        r = FS.copy_file.invoke({"file_path": a, "destination": dst_dir})
        check("🚨 이미 있으면 덮어쓰지 않고 되묻는다", r.startswith("✗") and "덮어쓰지 않았어요" in r, r)

        b = os.path.join(src_dir, "메모.txt")
        with io.open(b, "w", encoding="utf-8") as f:
            f.write("ㄱ")
        r = FS.move_file.invoke({"file_path": b, "destination": dst_dir})
        check("move_file 성공 마커", r.startswith("✓"), r)
        check("🔑 원본 자리에서 사라졌다 (그래서 승인이 있다)", not os.path.exists(b))
        check("목적지에 있다", os.path.exists(os.path.join(dst_dir, "메모.txt")))

        c = os.path.join(src_dir, "초안.txt")
        with io.open(c, "w", encoding="utf-8") as f:
            f.write("ㄴ")
        r = FS.rename_file.invoke({"file_path": c, "new_name": "최종"})
        check("🔑 확장자를 안 적으면 원래 것을 이어 붙인다 (.txt 가 날아가지 않는다)",
              os.path.exists(os.path.join(src_dir, "최종.txt")), r)

        r = FS.rename_file.invoke({"file_path": os.path.join(src_dir, "최종.txt"),
                                   "new_name": "하위/최종.txt"})
        check("🚨 이름에 경로가 오면 거절한다 («이름 변경»으로 승인받고 옮기지 않는다)",
              r.startswith("✗") and "move_file" in r, r)

        r = FS.move_file.invoke({"file_path": os.path.join(src_dir, "없는파일.txt"),
                                 "destination": dst_dir})
        check("없는 파일은 실패 마커로 답한다", r.startswith("✗"), r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"{NL}=== ⑤ 🚨 방향과 짝 — 같은 사고를 두 번 안 낸다 ===")
    SYS = _src("tools/system.py")
    check("🚨 알림에 토글이 **없다** (방향을 이름이 말한다)",
          "def notifications_toggle" not in SYS)
    check("끄기·켜기가 둘 다 있다",
          "def notifications_off(" in SYS and "def notifications_on(" in SYS)
    check("🔑 읽는 도구가 같이 있다 (없으면 «지금 켜져 있어?»가 지어낸다)",
          "def get_notifications_status(" in SYS)
    check("🚨 쓰고 나서 **다시 읽어** 확인한다 (눌렀는데 안 바뀌던 사고)",
          "_read_notifications() is on" in SYS)
    check("이미 그 상태면 그렇게 말하고 안 건드린다 (멱등)",
          SYS.count("이미 꺼져 있어요") and SYS.count("이미 켜져 있어요"))
    check("못 읽으면 None — 모르면 모른다고 한다", "return None" in SYS)
    check("화면 유지도 걸기·풀기 둘이다",
          "def keep_awake(" in SYS and "def allow_sleep(" in SYS)

    CAL = _src("tools/calendar.py")
    check("🔑 캘린더도 읽기·쓰기 한 쌍",
          "def create_calendar_event(" in CAL and "def list_calendar_events(" in CAL)

    print(f"{NL}=== ⑥ 🚨 «못 읽었다»와 «없다»를 섞지 않는다 ===")
    check("자격증명이 없으면 «확인할 수 없어요»라고 한다 («없어요»가 아니다)",
          "지금은 일정을 확인할 수 없어요" in CAL)
    check("🚨 읽기 실패가 빈 목록으로 떨어지지 않는다",
          "캘린더를 읽지 못했어요" in CAL)
    check("왜 그러면 안 되는지 적혀 있다 (회의를 놓친다)",
          "회의를 놓친다" in CAL)
    check("일정이 진짜 없을 때만 «없어요»", "일정이 없어요" in CAL)

    print(f"{NL}=== ⑦ 🚨 검사 도구가 새지 않는가 ===")
    SEC = _src("core/security.py")
    IC = _src("tools/input_control.py")
    check("🚨 마스킹 정규식을 베끼지 않고 그대로 쓴다",
          "_SCAN_TARGETS" in SEC and "_RRN_RE" in SEC
          and not re.search(r"_SCAN_\w*_RE\s*=\s*re\.compile", SEC))
    check("🚨 찾은 «값»을 안 돌려준다 (건수만)",
          "찾은 값 자체는 돌려주지 않는다" in SEC)
    check("   그리고 실제로 건수만 담는다 (findall 의 결과를 len 으로)",
          "len(rx.findall(text))" in SEC)
    check("🚨 «안전하다»고 단정하지 않는다 (아는 패턴만 봤다)",
          "제가 아는 패턴" in IC and "회사 고유 번호 형식은 아직 못 봐요" in IC)
    check("걸리면 경고 마커를 쓴다", "⚠️ 보내기 전에 확인하세요" in IC)

    print(f"{NL}=== ⑧ 🚨 안 한 일을 했다고 말하지 않는가 ===")
    APP = _src("tools/app_control.py")
    sw = APP[APP.index("def switch_window("):]
    check("🚨 꺼져 있으면 실패 마커를 붙인다 (tool_failed 가 봐야 한다)",
          'return f"✗ \'{display}\'{eul} 지금 켜져 있지 않아요' in sw)
    check("🔑 대신 열어 주지 않는다 (다른 창을 보고 있다고 착각한다)",
          "여기서 대신 열지 않는다" in sw)
    check("🚨 포그라운드 전환이 거부되면 성공이라 안 한다",
          "앞으로 가져오지 못했어요" in sw)
    check("🔑 전환 로직을 복사하지 않고 _focus_window 를 쓴다",
          "_focus_window(app_key)" in sw)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
