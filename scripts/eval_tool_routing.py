# -*- coding: utf-8 -*-
"""도구 라우팅 실측 — «묶음을 고를 수 있나»를 숫자로 잰다 (2-9 설계의 1단계).

    conda activate pluiz
    python scripts/eval_tool_routing.py            # difflib + 임베딩(int8)
    python scripts/eval_tool_routing.py --e5       # multilingual-e5-small 로
    python scripts/eval_tool_routing.py --detail   # 틀린 발화를 전부 출력

## 이 스크립트가 답하는 질문

도구 44개를 매 턴 전부 넣지 말고 **필요한 묶음만** 넣자는 것이 2-9다.
그러려면 먼저 답해야 하는 것이 하나다 — *"발화만 보고 묶음을 고를 수 있나."*

[M5 §6-3-A](../docs/design/M5_임베딩_캐시.md)가 임베딩을 캐시에서 **강등**시켰다.
이유는 «임계가 없다»(마진 음수)였고, **순위는 셋 중 제일 좋았다**(e5 top-1 12/17).
라우팅이 필요로 하는 것은 정확히 그 순위 쪽이다. 그래서 다시 잰다.

🚨 **12/17 을 그대로 가져다 쓰지 않는다.** 그 표본은 «캐시가 어려우라고 고른 17개»고,
   묶음 고르기는 패턴 22개 중 1개가 아니라 **묶음 8개 중 1~3개**를 고르는 더 쉬운 문제다.
   «더 쉬울 것»은 짐작이라 재지 않으면 설계가 짐작 위에 선다.

## 무엇을 재나

  ① **묶음 recall@k** — 정답 도구가 속한 묶음이 상위 k 묶음 안에 **전부** 들어오나
     (하나라도 빠지면 그 턴은 «도구를 못 찾는» 턴이 된다. 부분 점수를 주지 않는다)
  ② **k별 적재 도구 수** — 절약이 실제로 얼마나 되나
  ③ **맥락 의존 발화** — 발화만으로는 원리상 못 푸는 것이 몇 %인가

## ⚠️ 평가셋 — 지어내지 않았다

이 저장소는 «검증셋이 학습셋과 같은 편향을 공유해» 웨이크워드 93.6%가 아무것도
보증하지 못한 적이 있다. 그래서 여기 발화는 **전부 `logs/*.log` 의 실사용 발화**고,
정답 라벨은 **그때 실제로 실행(요청)된 도구**다. 내가 고른 것은 표본이 아니라
«자립/맥락 의존» 분류뿐이다.

📌 로그는 `.gitignore` 대상이라 저장소에 없다. 그래서 추출 결과를 **여기 박아 둔다**
   (`eval_embed_threshold.py` 와 같은 방식 — 누구나 재현할 수 있어야 한다).
   추출에 쓴 정규식은 `scripts/analyze_tool_usage.py` 의 `_TURN` 과 같다.
"""
import argparse
import io
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ── 묶음 정의 ──────────────────────────────────────────────────────
# core/tool_registry.py 의 주석 구분과 같은 선으로 갈랐다. 44개가 전부 들어간다.
GROUPS = {
    "앱": ["open_app", "close_app", "maximize_window", "minimize_window", "show_desktop"],
    "웹": ["open_url", "web_search", "youtube_search", "map_search",
           "fetch_web_info", "crawl_page"],
    "날씨": ["get_weather"],
    "파일": ["create_file", "create_folder", "find_file", "list_directory",
             "open_recent_file", "open_file", "write_excel", "delete_file", "delete_folder"],
    "시스템": ["volume_up", "volume_down", "set_volume", "get_volume", "mute_toggle",
               "brightness_up", "brightness_down", "set_brightness", "get_brightness",
               "take_screenshot", "get_battery_status", "get_current_time",
               "get_running_apps"],
    "입력": ["type_text", "press_key", "get_clipboard_text", "click_ui_element"],
    "일정": ["create_calendar_event"],
    "화면": ["describe_screen", "find_ui_element", "point_at_element",
             "watch_screen", "stop_watching"],
}
TOOL_GROUP = {t: g for g, ts in GROUPS.items() for t in ts}
GROUP_NAMES = list(GROUPS)

# 묶음을 한 문장으로 적은 것 — «묶음문» 후보의 재료다.
# 도구 설명문을 쓰는 후보와 **나란히** 재기 위해 손으로 썼다.
GROUP_DESC = {
    "앱": "프로그램이나 앱을 열고 닫고 창을 최대화 최소화한다",
    "웹": "인터넷에서 검색하거나 웹사이트를 열고 웹 페이지 내용을 읽어 온다",
    "날씨": "오늘이나 어제 내일의 날씨 기온 비 눈 기상 정보를 알려준다",
    "파일": "파일과 폴더를 만들고 찾고 열고 목록을 보고 지운다",
    "시스템": "볼륨 소리 화면 밝기 배터리 시간 실행 중인 앱 스크린샷 같은 PC 상태를 보거나 바꾼다",
    "입력": "키보드로 글자를 입력하거나 키를 누르고 클립보드를 읽고 버튼을 클릭한다",
    "일정": "달력에 일정과 약속을 등록한다",
    "화면": "지금 화면에 무엇이 보이는지 설명하고 화면에서 위치를 찾아 표시하고 화면을 지켜본다",
}

# ── 평가셋 — logs/*.log 실사용 발화 (발화, 실행된 도구들) ─────────────
# 🔑 «자립»은 발화만으로 묶음이 정해지는 것. 라우팅이 답해야 하는 문제다.
SELF_CONTAINED = [
    ("지금 실행 중인 모든 창 정보 알려줘", ["get_running_apps"]),
    ("지금 켜져있는 앱 알려줘", ["get_running_apps"]),
    ("블루투스 어디서 켜는지 알려줘", ["point_at_element"]),
    ("블루투스 어디서 켜", ["point_at_element"]),
    ("블루투스 기능은 어디서 켜야 돼", ["point_at_element"]),
    ("비행기 모드 어디서 켜", ["point_at_element"]),
    ("와이파이 연결 리스트 보여줘", ["point_at_element"]),
    ("클립보드 내용 보여줘", ["get_clipboard_text"]),
    ("포토샵222_없는앱 열어줘", ["open_app"]),
    ("메모장 새로 켜 줘", ["open_app"]),
    ("메모장 새로 하나 열어줘", ["open_app"]),
    ("한글 실행해 줘", ["open_app"]),
    ("메모정도 열고 계산기도 열어줘", ["open_app"]),
    ("메모장 열고 그림판 열어줘", ["open_app"]),
    ("메모장 말고 파일탐색기 열어", ["open_app"]),
    ("오늘 날씨 어때", ["get_weather"]),
    ("오늘 날씨는 어때", ["get_weather"]),
    ("충청북도 날씨는 어때 청주 청주", ["get_weather"]),
    ("어제 청주 날씨는 어땠어", ["get_weather"]),
    ("부산 날씨 대구 날씨 서울 날씨 청주 날씨 알려줘", ["get_weather"]),
    ("강원도 날씨는", ["get_weather"]),
    ("오늘의 날씨는 어때 우리나라 말고 미국 날씨로 알려줘", ["get_weather"]),
    ("바탕화면에서 2026 campus axton 수료증 파일 찾아서 열어줘", ["find_file"]),
    ("바탕화면에서 갈릴레오 갈릴레이 PDF 파일 찾아서 열어줘", ["find_file"]),
    ("바탕화면에서 Long Time plains라고 되어 있는 이름의 텍스트 파일 열어줘", ["find_file"]),
    ("my firstapp 폴더 찾아줘", ["find_file"]),
    ("바탕화면에서 파이 엑셀 사이즈라는 이름의 폴더 찾아줘", ["find_file"]),
    ("a.txt 파일 찾아줘", ["find_file"]),
    ("a.txt 찾아줘", ["find_file"]),
    ("바탕화면에 있는 하이 엑서사이즈 폴더 지워 줘", ["delete_folder"]),
    ("지금 그러면 바탕화면에 있는 압축 폴더 이름들 줘 볼래 내가 골라 줄게", ["list_directory"]),
    ("a.t 텍스트 파일 지워 줘", ["delete_file"]),
    ("테스트 파일 지워 줘", ["delete_file"]),
    ("날씨 파일이랑 일정 파일 지워 줘", ["delete_file"]),
    ("지금 화면에 뭐 있어", ["describe_screen"]),
    ("지금 화면에 뭐 떠 있어", ["describe_screen"]),
    ("오류 뜨면 알려줘", ["watch_screen"]),
    ("화면 바뀌면 알려줘", ["watch_screen"]),
    ("그만 봐이 변태야", ["stop_watching"]),
    ("엔터 눌러 줘", ["press_key"]),
    ("지금 밝기는", ["get_brightness"]),
    ("화면 밝기 30% 만들어줘", ["set_brightness"]),
    ("소리는 지금 얼마야", ["get_volume"]),
    ("볼륨은 여기서 조금만 더 줄여 주라", ["volume_down"]),
    ("최대화 해 줘", ["maximize_window"]),
    ("아니 앱스 타임 사건에 대해서 그 뭐지 정리해 달라고", ["fetch_web_info"]),
    # 🔑 묶음이 둘 이상인 발화 — 라우팅이 **하나만 고르면 깨진다**
    ("텍스트 파일도 지워 주고 메모장 열어줘", ["delete_file", "open_app"]),
    ("계산기 열고 알파벳 최희로 시작하는 이름의 텍스트 파일 삭제해 줘", ["open_app", "delete_file"]),
    ("메모장 열고 테스트 점 txt 파일 지워 줘", ["open_app", "delete_file"]),
    ("메모장 닫고 d.t 지워 줘", ["close_app", "delete_file"]),
    ("메모장 열고 지금 켜져 있는 앱 알려줘", ["open_app", "get_running_apps"]),
    ("설정 창을 열고 최대화 해 줘", ["open_app", "maximize_window"]),
    ("어 그 PC 밝기 올려 주고 오늘 저녁 메뉴 좀 추천해 주라 소윤이 배고파", ["brightness_up"]),
    ("밝기 올리고 이번 년도가 우크라이나 러시아 전쟁 몇 년쨰인지 알려줘",
     ["brightness_up", "fetch_web_info"]),
    ("메모장 열고 거기에 2번 일주일 총 7일 날씨 정보를 깔끔하게 정리해 가지고 적어 줘",
     ["open_app", "get_weather", "type_text"]),
]

# 🚨 발화만으로는 **원리상** 못 푸는 것들. 전부 실제 로그다.
#    라우팅 층이 이것들을 «못 맞힌다»고 적는 것은 의미가 없다 —
#    설계가 답해야 할 것은 «이 턴에 무엇을 싣나»다.
CONTEXT_DEPENDENT = [
    ("그래", ["delete_file"]),
    ("어", ["delete_file"]),
    ("응 그래", ["delete_file"]),
    ("그래 삭제해 줘", ["delete_file"]),
    ("그래 지워 줘", ["delete_file"]),
    ("음", ["delete_file"]),
    ("아니", ["delete_file"]),
    ("어 맞아", ["open_file"]),
    ("어 그거 열어줘", ["open_file"]),
    ("그거 꺼 줘", ["close_app"]),
    ("그거 말고 다른 건 또 안 보여", ["describe_screen"]),
    ("그거 말고 더 다양하게 뭐가 있는지 알려줘", ["describe_screen"]),
    ("다시 해 봐", ["open_app"]),
    ("못한거 해줘", ["open_app"]),
    ("다시 한 번만 더 찾아 볼래", ["find_file"]),
    ("어 맞아. 어딨는지 알려줘", ["find_file"]),
    ("위치 표시해줘", ["point_at_element"]),
    ("그래 표시해 봐", ["point_at_element"]),
    ("네가 어디서 켜야 되는지 찾아가 달려 줘", ["point_at_element"]),
    ("몰라 네가 센스 있게 알아서 한번 써 봐", ["type_text"]),
    ("안 지워졌는데", ["describe_screen", "open_app", "press_key"]),
    ("아니 아니 하지 마 지워 줘", ["delete_file"]),
    ("어 그럼 그렇게 한번 해 봐", ["get_weather", "create_file"]),
    ("지금 지운 거 파일 혹시 그냥 다시 만들어 줄 수 있어", ["create_file"]),
]


def _norm(x):
    return x / np.clip(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12, None)


# ── 라우터 후보 ────────────────────────────────────────────────────
def _tool_descriptions() -> dict:
    """도구 이름 → 설명문. 라우팅 후보 ①의 재료다.

    ⚠️ 여기서 실제 `get_all_tools()` 를 부른다 — 설명문을 손으로 베끼면
    코드가 바뀌었을 때 **측정만 낡는다.** langchain 이 없으면 None 을 돌려준다.
    """
    try:
        from core.tool_registry import get_all_tools
    except Exception:
        return {}
    return {t.name: (t.description or "") for t in get_all_tools()}


def make_group_scorer(kind: str, encode, descs: dict):
    """발화 → np.ndarray(len(GROUP_NAMES),) 묶음 점수."""
    if kind == "묶음문":
        texts = [GROUP_DESC[g] for g in GROUP_NAMES]
        M = encode(texts)

        def score(q):
            return M @ encode([q])[0]
        return score

    if kind == "설명문":
        names, rows = [], []
        for g in GROUP_NAMES:
            for t in GROUPS[g]:
                d = descs.get(t)
                if not d:
                    continue
                names.append(g)
                # 파라미터 설명은 뺀다 — «level: 0-100» 같은 줄이 의미를 희석한다
                rows.append(d.split("\n")[0][:200])
        M = encode(rows)
        idx = [GROUP_NAMES.index(g) for g in names]

        def score(q):
            s = M @ encode([q])[0]
            out = np.full(len(GROUP_NAMES), -1.0)
            for i, v in zip(idx, s):          # 묶음 점수 = 소속 도구의 최고점
                out[i] = max(out[i], v)
            return out
        return score

    raise ValueError(kind)


def difflib_encode_factory():
    """임베딩 없이 글자 유사도로 같은 것을 한다 — **현행 자(尺)의 대조군**이다."""
    from difflib import SequenceMatcher

    def scorer(kind, descs):
        if kind == "묶음문":
            texts = [GROUP_DESC[g] for g in GROUP_NAMES]

            def score(q):
                return np.array([SequenceMatcher(None, q, t).ratio() for t in texts])
            return score
        names, rows = [], []
        for g in GROUP_NAMES:
            for t in GROUPS[g]:
                d = descs.get(t)
                if not d:
                    continue
                names.append(GROUP_NAMES.index(g))
                rows.append(d.split("\n")[0][:200])

        def score(q):
            out = np.full(len(GROUP_NAMES), -1.0)
            for i, t in zip(names, rows):
                out[i] = max(out[i], SequenceMatcher(None, q, t).ratio())
            return out
        return score
    return scorer


# ── 측정 ──────────────────────────────────────────────────────────
KS = (1, 2, 3, 4)


def measure(score_fn, label: str, dataset, detail: bool = False) -> dict:
    hit = {k: 0 for k in KS}
    loaded = {k: [] for k in KS}
    misses = {k: [] for k in KS}
    multi_total = multi_hit3 = 0

    for text, tools in dataset:
        gold = {TOOL_GROUP[t] for t in tools}
        s = score_fn(text)
        order = [GROUP_NAMES[i] for i in np.argsort(-s)]
        if len(gold) > 1:
            multi_total += 1
        for k in KS:
            picked = set(order[:k])
            ok = gold <= picked
            hit[k] += ok
            loaded[k].append(sum(len(GROUPS[g]) for g in order[:k]))
            if not ok:
                misses[k].append((text, sorted(gold), order[:k]))
            if k == 3 and len(gold) > 1 and ok:
                multi_hit3 += 1

    n = len(dataset)
    print("=" * 88)
    print(f"■ {label}   (발화 {n}개)")
    print("=" * 88)
    for k in KS:
        avg = float(np.mean(loaded[k]))
        print(f"  recall@{k}  {hit[k]:>3}/{n}  ({hit[k]/n*100:5.1f}%)"
              f"   적재 도구 평균 {avg:5.1f}/44  ({avg/44*100:4.1f}%)")
    if multi_total:
        print(f"  └ 묶음 2개 이상인 발화 {multi_total}개 중 recall@3 성공 {multi_hit3}개")
    if detail:
        for text, gold, picked in misses[3]:
            print(f"    @3 실패  {text[:44]!r:48} 정답 {gold} → 고른 것 {picked}")
    print()
    return {"label": label, "n": n,
            "recall": {k: hit[k] for k in KS},
            "loaded": {k: float(np.mean(loaded[k])) for k in KS}}


# ── 이어싣기 + 전체 폴백까지 넣은 실전 모의 ─────────────────────────
# 🔑 위 measure() 는 «발화 한 개»를 본다. 실제 라우팅은 **대화 순서** 위에서 돈다 —
#    직전 턴의 묶음을 이어싣는 것이 맥락 의존 발화의 유일한 답이기 때문이다.
#    그래서 로그를 **순서대로** 다시 돌린다.
#
# ⚠️ `logs/` 는 `.gitignore` 대상이라 저장소에 없다. 로그가 없으면 이 모드는 건너뛴다.
#    (`analyze_tool_usage.py` 와 같은 처지다 — 실사용 측정은 실사용 로그가 있어야 한다)
_LOG_TURN = re.compile(
    r"턴 완료 \| 입력=('[^']*'|\"[^\"]*\") \| (?:도구|요청)=(없음|\[[^\]]*\])"
    r"(?: \| 실행=(없음|\[[^\]]*\]))?")


def _log_turns():
    import glob
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in sorted(glob.glob(os.path.join(root, "logs", "*.log"))):
        turns = []
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _LOG_TURN.search(line)
                if not m:
                    continue
                used = m.group(3) if m.group(3) is not None else m.group(2)
                tools = [] if used == "없음" else re.findall(r"'([^']+)'", used)
                tools = [t for t in tools if t in TOOL_GROUP]   # «캐시» 같은 가짜 이름을 뺀다
                turns.append((m.group(1)[1:-1], tools))
        if turns:
            yield os.path.basename(path), turns


def simulate(score_fn, label: str, k: int, carry_n: int, always: tuple = ()) -> dict:
    """적재 = 상비 ∪ 직전 carry_n 개 도구 턴의 묶음 ∪ top-k. 로그를 순서대로 돌린다."""
    tot = miss = 0
    loaded = []
    sessions = 0
    for _name, turns in _log_turns():
        sessions += 1
        hist = []
        for text, tools in turns:
            if not tools:
                continue
            gold = {TOOL_GROUP[t] for t in tools}
            s = score_fn(text)
            order = [GROUP_NAMES[i] for i in np.argsort(-s)]
            picked = set(always) | set(order[:k])
            for g in hist[-carry_n:] if carry_n else []:
                picked |= g
            tot += 1
            miss += not (gold <= picked)
            loaded.append(sum(len(GROUPS[g]) for g in picked))
            hist.append(gold)
    if not tot:
        return {}
    avg = float(np.mean(loaded))
    n_all = sum(len(v) for v in GROUPS.values())
    # 폴백 = 못 고른 턴만 «전체 도구»로 한 번 더 부른다. 기대 적재량이 비용의 대리 지표다.
    rate = miss / tot
    expect = avg + rate * n_all
    print(f"  {label:<34} 실패 {miss:>3}/{tot}  ({rate*100:4.1f}%)"
          f"   적재 평균 {avg:5.1f}/{n_all}"
          f"   폴백 포함 기대 {expect:5.1f}  ({expect/n_all*100:4.1f}%)")
    return {"label": label, "miss": miss, "tot": tot, "avg": avg, "expect": expect}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e5", action="store_true", help="multilingual-e5-small 로 잰다")
    ap.add_argument("--detail", action="store_true", help="틀린 발화를 전부 출력")
    ap.add_argument("--context", action="store_true",
                    help="맥락 의존 발화까지 같이 잰다 (원리상 못 푸는 것의 크기를 본다)")
    ap.add_argument("--logs", action="store_true",
                    help="logs/*.log 를 **순서대로** 돌려 이어싣기·폴백까지 넣고 잰다")
    args = ap.parse_args()

    descs = _tool_descriptions()
    if not descs:
        print("⚠️ 도구 설명을 못 읽었다 (langchain_core 없음?) — «묶음문» 후보만 잰다.")

    print(f"도구 {sum(len(v) for v in GROUPS.values())}개 · 묶음 {len(GROUPS)}개 "
          f"· 자립 발화 {len(SELF_CONTAINED)}개 · 맥락 의존 {len(CONTEXT_DEPENDENT)}개")
    print(f"묶음 크기: " + " · ".join(f"{g} {len(t)}" for g, t in GROUPS.items()))
    print()

    rows = []
    dl = difflib_encode_factory()
    for kind in (["묶음문", "설명문"] if descs else ["묶음문"]):
        rows.append(measure(dl(kind, descs), f"difflib · {kind}", SELF_CONTAINED, args.detail))

    if args.e5:
        os.environ["PLUIZ_EMBED_DIR"] = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "models", "embed", "e5-small")
        os.environ["PLUIZ_EMBED_MODEL"] = "model.onnx"
    from core.embedder import get_embedder, reset_embedder
    reset_embedder()
    e = get_embedder()
    if not e.available:
        print("(건너뜀 — 임베딩 모델을 못 엽니다. scripts/fetch_embed_model.py)")
        _summary(rows)
        return
    print(f"임베딩: {e.describe()}\n")

    def encode(texts):
        # ⚠️ **한 문장씩** 넣는다 — 배치 패딩이 벡터를 흔든다(M5 §6-3의 버그).
        return np.stack([e.encode(t) for t in texts])

    tag = "e5-small" if args.e5 else "MiniLM int8"
    for kind in (["묶음문", "설명문"] if descs else ["묶음문"]):
        rows.append(measure(make_group_scorer(kind, encode, descs),
                            f"{tag} · {kind}", SELF_CONTAINED, args.detail))

    if args.context:
        print("─" * 88)
        print("■ 맥락 의존 발화 — **발화만으로는 원리상 못 푼다.** 크기를 보려고 잰다")
        print("─" * 88)
        measure(make_group_scorer("묶음문", encode, descs),
                f"{tag} · 묶음문 (맥락 의존)", CONTEXT_DEPENDENT, args.detail)

    if args.logs:
        print("=" * 88)
        print("■ 실전 모의 — 로그를 **순서대로**. 이어싣기와 전체 폴백을 넣는다")
        print("=" * 88)
        sf = make_group_scorer("묶음문", encode, descs)
        any_turn = False
        for k in (2, 3):
            for carry in (0, 1, 2):
                for always in ((), ("앱", "파일")):
                    a = "+상비(앱·파일)" if always else ""
                    r = simulate(sf, f"top-{k} · 이어싣기 {carry}턴{a}", k, carry, always)
                    any_turn = any_turn or bool(r)
        if not any_turn:
            print("  (건너뜀 — logs/*.log 에 `턴 완료` 줄이 없습니다)")
        print()
        print("  🔑 «폴백 포함 기대»가 44 보다 충분히 작아야 라우팅이 이득이다.")
        print("     폴백은 실패를 **비용으로 바꾼다** — 못 고른 턴만 전체 도구로 다시 부른다.")
        print()

    _summary(rows)


def _summary(rows):
    print("=" * 88)
    print("■ 요약 — **recall 이 100%에 닿는 k 에서 적재 도구가 몇 개인가**가 결론이다")
    print("=" * 88)
    print(f"  {'':<26}" + "".join(f"{'@'+str(k):>9}" for k in KS)
          + "     적재(@3)")
    for r in rows:
        line = f"  {r['label']:<26}"
        for k in KS:
            line += f"{r['recall'][k]:>5}/{r['n']:<3}"
        line += f"   {r['loaded'][3]:>5.1f}개"
        print(line)
    print()
    print("  🔑 recall 이 100%가 아니면 그 %만큼 «도구를 못 찾는» 턴이 생긴다.")
    print("     라우팅의 실패는 캐시의 실패와 성격이 다르다 —")
    print("     캐시는 못 잡으면 LLM 으로 흘러가지만, 라우팅은 못 고르면 **할 수 없다고 답한다.**")


if __name__ == "__main__":
    main()
