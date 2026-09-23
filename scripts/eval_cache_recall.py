# -*- coding: utf-8 -*-
"""캐시 재현율 실측 — C안(사전 확장)의 천장을 «홀드아웃»으로 잰다. (M5 §6-3-D)

    python scripts/eval_cache_recall.py

## 이 스크립트의 요점은 «홀드아웃»이다

사전을 늘릴 때 **본 문장**으로 재면 재현율이 5/17 → 16/17로 뛴다. 그건 대부분
**과적합**이다. 같은 확장을 **처음 보는 문장**에 걸면 7/16 → 9/16 이다.

> **웨이크워드 검증셋이 학습셋과 같은 편향을 공유해 93.6%가 아무것도 보증하지
> 못했던 것과 같은 모양이다.** 그래서 여기 있는 문장들은 «사전을 늘릴 때 보지 않은»
> 것들이고, 부정 12개 중 5개는 `logs/pluiz.log`에서 그대로 가져왔다.

⚠️ **부정(오매칭)이 하나라도 늘면 그 확장은 채택하지 않는다.** 캐시는 승인 없이
   실행하므로, 미스는 LLM이 2.5초에 처리하지만 오매칭은 엉뚱한 실행이다.

⚠️ 제품 상태를 건드리지 않는다 — 캐시·로그를 임시 경로로 돌린다(BL-11 규율).
"""
import os, sys, io, importlib
SC = os.path.dirname(os.path.abspath(__file__))
os.environ["PLUIZ_CACHE_FILE"] = os.path.join(SC, "hold.json")
os.environ["PLUIZ_LOG_DIR"] = SC
sys.path.insert(0, r"C:\pluiz_v2")
for f in ["hold.json"]:
    p = os.path.join(SC, f)
    if os.path.exists(p): os.remove(p)
import core.command_cache as cc

# ── 홀드아웃 긍정 — 사전을 늘릴 때 **쓰지 않은** 표현 (도구 이름으로 판정)
HOLD_POS = [
    ("메모장 하나 띄워봐",           "open_app"),
    ("계산기 좀 실행해",             "open_app"),
    ("크롬 좀 띄워줄래",             "open_app"),
    ("탐색기 실행시켜",              "open_app"),
    ("메모장 이제 닫아줘",           "close_app"),
    ("소리 조금만 더 크게",          "volume_up"),
    ("볼륨 좀 낮춰봐",              "volume_down"),
    ("소리 안 들리게 해줘",          "mute_toggle"),
    ("화면이 어두워 밝게 좀",         "brightness_up"),
    ("화면 좀 어둡게 해줘",          "brightness_down"),
    ("지금 화면 캡처 좀",            "take_screenshot"),
    ("배터리 몇 프로 남았지",         "get_battery_status"),
    ("켜져 있는 앱 좀 보여줘",        "get_running_apps"),
    ("바탕화면 좀 띄워줘",           "show_desktop"),
    ("유튜브 켜줘",                 "open_url"),
    ("창 최대로 키워줘",             "maximize_window"),
]
# ── 홀드아웃 부정 — ★ 는 logs/pluiz.log 실제 발화
HOLD_NEG = [
    "아니 그게 아니고",                                   # ★
    "다시 한번 해 줄래",                                  # ★
    "또 해 봐 또",                                       # ★
    "날짜 말고 날씨 알려 달라고",                          # ★
    "안 열려 있는데 설정창",                               # ★
    "메모장에 회의록 정리해서 써줘",
    "계산기로 환율 계산 좀 해줘",
    "화면에 지금 뭐가 떠 있는지 봐줘",
    "소리가 왜 안 나지",
    "밝기 조절은 어디서 하는 거야",
    "이거 왜 이렇게 느려",
    "고마워",
]
TOOLS_OK = {"open_app","close_app","volume_up","volume_down","mute_toggle",
            "brightness_up","brightness_down","take_screenshot","get_battery_status",
            "get_running_apps","show_desktop","open_url","maximize_window","minimize_window",
            "get_current_time","open_recent_file"}

NEW_ENTITIES = [
    ("모니터","brightness"),("밝게","brightness"),("어둡","brightness"),
    ("화면 사진","screenshot"),("충전","battery"),
    ("소리 안 나","mute"),("소리 꺼","mute"),
    ("몇 시","time"),("실행 중인","apps"),("창","window"),
]
NEW_ACTIONS = {
    "volume_up":["최대로 올","올려"], "volume_down":["줄여줘"],
    "mute":["소리 안 나","소리 꺼","무음"],
    "brightness_up":["밝게"], "brightness_down":["어둡"],
    "screenshot":["사진 좀 찍","사진 찍"], "time":["몇 시인지"],
    "battery":["배터리 몇","충전 얼마","몇 퍼센트"],
    "running_apps":["실행 중인 프로그램","실행중인 프로그램"],
    "maximize":["꽉 채워","크게 해"], "show_desktop":["바탕화면 좀 보","바탕화면 보"],
    "open":["틀어"],
}

def build(expand):
    importlib.reload(cc)
    if expand:
        for surf, key in NEW_ENTITIES:
            cc.ALL_ENTITIES.insert(0, (surf, key))
        cc.ALL_ENTITIES.sort(key=lambda x: -len(x[0]))
        for act, trigs in NEW_ACTIONS.items():
            for i,(k,lst) in enumerate(cc.ACTION_PATTERNS):
                if k == act:
                    cc.ACTION_PATTERNS[i] = (k, trigs + lst); break
    b = io.StringIO(); r = sys.stdout; sys.stdout = b
    c = cc.CommandCache(); sys.stdout = r
    c._build_intent_index()
    return c

def run(c, label):
    hit = wrong = 0; miss=[]; fp=[]
    for t, want in HOLD_POS:
        b=io.StringIO(); r=sys.stdout; sys.stdout=b
        try:
            res=c.find(t); blocked = c.has_uncovered_command(t) if res else False
        finally: sys.stdout=r
        if res is None or blocked: miss.append(t)
        elif res[0].tool_calls and res[0].tool_calls[0]["name"]==want: hit+=1
        else: wrong+=1; miss.append(f"{t}(오답:{res[0].tool_calls[0]['name']})")
    for t in HOLD_NEG:
        b=io.StringIO(); r=sys.stdout; sys.stdout=b
        try:
            res=c.find(t); blocked = c.has_uncovered_command(t) if res else False
        finally: sys.stdout=r
        if res is not None and not blocked:
            fp.append((t, res[0].tool_calls[0]["name"], res[0].pattern))
    print(f"■ {label}")
    print(f"   재현율 {hit}/{len(HOLD_POS)} · 오답실행 {wrong} · 🚨오매칭 {len(fp)}/{len(HOLD_NEG)}")
    for t,g,p in fp: print(f"     🚨 {t!r:26} → {g}  «{p}»")
    if miss: print(f"     놓침: {miss}")
    print()
    return hit, wrong, len(fp)

print("=" * 84); print("홀드아웃 — 사전을 늘릴 때 보지 않은 문장"); print("=" * 84)
a = run(build(False), "현행")
b = run(build(True),  "C안 (사전 확장)")
print("=" * 84)
print(f"  홀드아웃 재현율 {a[0]}/{len(HOLD_POS)} → {b[0]}/{len(HOLD_POS)} · 오매칭 {a[2]} → {b[2]}")
