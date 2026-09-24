# -*- coding: utf-8 -*-
"""음성 인식률 자(尺)의 계약 — **자가 틀리면 결론이 틀린다** (2-10)

실행: python tests/test_eval_stt.py

## 왜 이 테스트가 있나

`scripts/eval_stt.py` 가 내는 CER 은 *«평소에 얼마나 잘 알아듣나»* 에 답하는
숫자다. 그리고 이 종류의 코드는 [`eval_wakeword`](test_eval_wakeword.py) ·
[`analyze_cache_savings`](test_cache_savings.py) 와 **같은 자리**에 있다 —
🚨 **틀려도 오류가 안 난다. 그냥 다른 숫자가 나온다.**

이 저장소는 이미 두 번 그 사고를 겪었다. 2026-09-08 «검증 95.0%»(합성음으로
배우고 합성음으로 채점), 2026-09-24 «고정 20문장 100%»(자를 할 일 목록으로 씀).
**둘 다 코드가 아니라 자가 틀린 것이다.**

🚨 **그리고 실제로 한 번 틀렸다.** 2026-09-24 첫 실측에서 두 화자의 CER 이 92% 로
나왔는데, 엔진이 틀린 게 아니라 **오디오에 문장이 두 번 들어 있었다**(녹음 슬롯 4초를
채우느라). 자를 만든 당일에 자가 틀린 것이 나왔다 — 그래서 ⑨ 가 있다.

## 여기서 고정하는 것 여덟

1. 🚨 **코퍼스 CER 은 «오류 합 / 글자 합» 이다.** 발화별 비율을 평균하면 짧은
   발화가 과대 대표된다 — «켜» 한 글자가 틀리면 100%, 40자의 한 글자는 2.5% 다.
2. 🚨 **`freetalk` 는 채점에 안 쓴다.** 그 칸의 `text` 는 정답이 아니라
   *"어제 하루 뭐 하셨는지 쭉 말해 주세요"* 같은 **주제**다. 쓰면 전부 오답이 된다.
3. **빈 결과는 «CER 100%」이자 «빈결과 1건»** — 둘 다 세야 한다. 한쪽만 세면
   *"인식하지 못했어요"* 가 나가는 비율이 평균 뒤로 숨는다.
4. **대조군 표본은 결정적이다.** 난수를 쓰면 다음에 다시 재서 비교할 수가 없다.
5. **엔진을 여기서 다시 구현하지 않는다** — `services/stt.py` 에서 import 한다.
   복제하면 이 자는 런타임이 아니라 **자기 자신**을 재게 된다.
6. 🚨 **표본의 편향을 문서 아닌 코드가 말한다.** 우리 60발화는 «플루이즈와
   헷갈리라고» 고른 문장이라 STT 에게 유난히 어렵다. 그 경고가 스크립트
   안에 있어야 숫자만 떼어 가는 것을 막는다.
7. 🚨 **반복 발화 판정은 «오디오»로 한다. 「엔진이 뱉은 글」로 하지 않는다.**
   출력을 보고 봐주면 재는 게 아니라 **맞춰 주는 것**이고, Whisper 는 스스로
   같은 구절을 되풀이하는 실패 모드가 있어(BL-53 과 이웃한 자리) 그러면
   **진짜 결함을 용서한다.**
8. 🚨 **새 구간 라벨(`command`)이 조용히 사라지지 않는다.** 녹음 페이지 · 학습 적재 ·
   웨이크워드 오탐 분모 · 이 측정기까지 **넷이 같은 라벨을 알아야** 한다. 하나라도
   빠지면 소리는 들어오는데 안 세진다 — 2026-09-23 «녹음 6명을 통째로 안 읽은»
   사고와 같은 모양이고, 오탐 분모에서 빠지면 **성적이 좋아 보인다.**

## ⚠️ 여기서 STT 를 실제로 부르지 않는다

망도 오디오도 안 탄다. 순수 함수(정규화·편집거리·집계)와 **소스의 계약**만 본다.
실제 인식은 `python scripts/eval_stt.py` 가 한다.
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _testenv  # noqa: F401,E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import numpy as np  # noqa: E402
import eval_stt as E  # noqa: E402

NL = chr(10)
# 🚨 한글이 든 소스를 Windows 기본 cp949 로 읽으면 UnicodeDecodeError 다 (CLAUDE.md 7)
_SRC = io.open(os.path.join(_ROOT, "scripts", "eval_stt.py"), encoding="utf-8").read()

passed = total = 0


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")


def _row(truth, hyp, sec=1.0):
    """집계에 넣을 수 있는 최소 행."""
    return {"sec": sec, "score": E.score(truth, hyp), "raw_score": E.score(truth, hyp)}


def run():
    print("=== ① 편집거리 — 자의 바닥 ===")
    check("같으면 0", E.edit_distance("블루투스", "블루투스") == 0)
    check("한 글자 치환은 1", E.edit_distance("가나다", "가라다") == 1)
    check("한 글자 삭제도 1", E.edit_distance("가나다", "가다") == 1)
    check("한 글자 삽입도 1", E.edit_distance("가다", "가나다") == 1)
    check("빈 쪽이 있으면 다른 쪽 길이", E.edit_distance("", "가나다") == 3)
    check("둘 다 비면 0", E.edit_distance("", "") == 0)
    check("대칭이다", E.edit_distance("플루이즈", "플레이즈")
          == E.edit_distance("플레이즈", "플루이즈"))
    check("어절 리스트로도 돈다 (WER 이 같은 함수를 쓴다)",
          E.edit_distance(["가", "나"], ["가", "다"]) == 1)

    print(f"{NL}=== ② 정규화 — 무엇을 «틀렸다»로 세나 ===")
    check("문장부호를 지운다", E._norm("블루투스 어디서 켜?", True) == "블루투스 어디서 켜")
    check("연속 공백을 하나로", E._norm("블루투스   어디서", True) == "블루투스 어디서")
    check("앞뒤 공백을 턴다", E._norm("  켜 줘  ", True) == "켜 줘")
    check("keep_space=False 면 공백을 없앤다",
          E._norm("블루투스 어디서 켜", False) == "블루투스어디서켜")
    check("None 도 빈 문자열로 받는다", E._norm(None, False) == "")
    check("물결·가운뎃점도 문장부호다", E._norm("아~ 그거·이거", False) == "아그거이거")
    check("🚨 띄어쓰기만 다르면 CER 0 이다 (한국어 STT 는 여기가 흔들린다)",
          E.score("블루투스 연결해 줄래", "블루투스 연결해줄래")["cer_err"] == 0)
    check("   그래도 공백 포함 CER 은 1 로 잡힌다 (둘 다 찍는 이유)",
          E.score("블루투스 연결해 줄래", "블루투스 연결해줄래")["cers_err"] == 1)

    print(f"{NL}=== ③ 한 발화 채점 ===")
    s = E.score("블루투스 어디서 켜", "블루투스 어디서 켜")
    check("완전히 같으면 오류 0 · 정확일치", s["cer_err"] == 0 and s["exact"])
    check("분모는 공백을 뺀 글자 수", s["cer_chars"] == len("블루투스어디서켜"))
    s = E.score("블루투스 어디서 켜", "")
    check("🚨 빈 결과는 오류가 «정답 길이» 만큼 (= CER 100%)",
          s["cer_err"] == s["cer_chars"] and s["cer_chars"] > 0)
    check("🚨 빈 결과는 empty 로도 센다 (평균 뒤로 숨지 않게)", s["empty"] and not s["exact"])
    check("빈 정답은 정확일치로 치지 않는다", not E.score("", "")["exact"])
    check("WER 분모는 어절 수", E.score("가 나 다", "가 나")["wer_words"] == 3)

    print(f"{NL}=== ④ 집계 — 🚨 코퍼스 CER 은 «비율의 평균»이 아니다 ===")
    # 짧은 발화 1개(전부 틀림) + 긴 발화 1개(전부 맞음).
    #   · 발화별 비율의 평균 → (100 + 0) / 2 = **50%**
    #   · 코퍼스 CER       → 오류 2 / 글자 (2 + 15) = **11.8%**
    # 같은 자료를 두고 5배가 갈린다. 어느 쪽으로 세는지가 결론을 바꾼다.
    short_truth, long_truth = "켜줘", "블루투스스피커를켜주시겠어요오"
    rows = [_row(short_truth, ""), _row(long_truth, long_truth)]
    m = E.aggregate(rows)
    check(f"오류 합 / 글자 합 으로 낸다 (여기서는 {m['cer']}%)",
          m["cer"] == round(100.0 * len(short_truth)
                            / (len(short_truth) + len(long_truth)), 1))
    check("🚨 발화별 비율의 평균(50.0%)이 아니다", m["cer"] != 50.0)
    check("정확일치는 발화 수 기준", m["정확일치"] == 50.0)
    check("빈결과도 발화 수 기준", m["빈결과"] == 50.0)
    check("n 은 행 수", m["n"] == 2)
    check("빈 묶음은 빈 dict (0으로 나누지 않는다)", E.aggregate([]) == {})
    check("분모가 0이면 비율을 지어내지 않는다 (None)",
          E.aggregate([_row("", "")])["cer"] is None)

    lat = E.aggregate([_row("가", "가", sec=s) for s in (0.1, 5.0, 0.2, 0.3, 0.4)])
    check("지연은 중앙값을 쓴다 (평균은 한 건에 끌린다)", lat["지연중앙"] == 0.3)
    check("p90 도 같이 낸다 (전시장에서 걸리는 건 꼬리다)", lat["지연p90"] == 5.0)

    print(f"{NL}=== ⑤ 표본 — 정답이 없는 칸을 채점하지 않는다 ===")
    check("🚨 freetalk 이 기본 라벨이 아니다 (그 칸의 text 는 «주제»다)",
          re.search(r'"--labels", default="negative"', _SRC) is not None)
    check("   왜 뺐는지가 코드 옆에 적혀 있다",
          "정답이 아니라" in _SRC and "freetalk" in _SRC)
    check("빈 text 인 구간은 버린다", "if not text:" in _SRC)
    check("라벨을 인자로 열어 둔다 (positive 도 따로 재 볼 수 있게)",
          "labels" in E.samples_ours.__code__.co_varnames)

    print(f"{NL}=== ⑥ 대조군 — 다시 재서 비교할 수 있어야 한다 ===")
    check("🚨 난수를 안 쓴다 (같은 N 이면 같은 표본)",
          "random" not in _SRC and "shuffle" not in _SRC)
    check("정렬로 순서를 고정한다", "sorted(glob.glob" in _SRC)
    check("화자를 고루 가져온다 (한 사람으로 몰리지 않게)", "by_speaker" in _SRC)
    check("왜 난수를 안 쓰는지 적혀 있다", "다시 재서 비교할 수 있어야" in _SRC)
    check("코퍼스가 없으면 조용히 0이 아니라 «없다»고 말한다",
          "대조군을 건너뜁니다" in _SRC)

    print(f"{NL}=== ⑦ 런타임을 다시 구현하지 않았는가 ===")
    check("🚨 STT 엔진을 services/stt.py 에서 가져온다",
          "from services.stt import STTService" in _SRC)
    check("🚨 후처리 교정도 런타임 것을 쓴다 (_postprocess 를 베끼지 않았다)",
          "_postprocess" in _SRC and "_CORRECTIONS" not in _SRC)
    check("구간 자르기도 학습 쪽 것을 쓴다 (같은 소리를 봐야 한다)",
          "from ingest_wakeword import" in _SRC and "cut" in _SRC)
    check("🚨 샘플레이트를 직접 적어 두지 않았다",
          not re.search(r"^SR\s*=\s*[0-9]", _SRC, re.M) and E.SR == 16000)
    check("Whisper 를 측정 전에 올린다 (모델 로딩이 지연에 안 섞이게)",
          "측정에서 뺀다" in _SRC and "_get_whisper()" in _SRC)
    check("한 엔진이 죽어도 나머지는 계속 잰다", "엔진이 죽어도" in _SRC)

    print(f"{NL}=== ⑧ 🚨 숫자만 떼어 가지 못하게 — 경고가 코드 안에 있다 ===")
    check("표본이 «어려우라고 고른 것»임을 스크립트가 말한다",
          "웨이크워드 오탐" in _SRC and "유난히 어렵다" in _SRC)
    check("나쁘게 적는 것도 틀린 것이라고 못 박는다",
          "유리하게 적는 것만큼이나 틀린" in _SRC)
    check("표본이 둘인 이유(표본 탓 ↔ 엔진 탓)를 적는다",
          "표본 탓" in _SRC and "엔진 탓" in _SRC)
    check("🚨 «명령 인식률»이 아니라는 것을 결과 출력에도 찍는다",
          "«명령을 얼마나 알아듣나»는 아니다" in _SRC)
    check("아무것도 실행하지 않는다는 성질을 맨 위에 적는다",
          "아무것도 실행하지 않는다" in _SRC)
    check("실행 코드가 실제로 도구를 안 부른다 (execute 계열이 없다)",
          "execute_sync" not in _SRC and "resolve_fast_path" not in _SRC)

    print(f"{NL}=== ⑨ 🚨 반복 발화 — 자가 틀렸던 자리 ===")
    # 0.5초 말하고 0.5초 쉬는 신호를 만든다. 진폭은 화자마다 다르게 준다 —
    # 판정이 «상대 에너지»여야 마이크 음량에 안 흔들린다.
    sr = E.SR

    def say(n_take, amp=0.3, word=0.5, gap=0.5):
        t = np.arange(int(sr * word)) / sr
        burst = (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        silence = np.zeros(int(sr * gap), dtype=np.float32)
        out = []
        for _ in range(n_take):
            out += [burst, silence]
        return np.concatenate([silence] + out)

    check("🚨 한 번 말하면 구간 1개", len(E.speech_bursts(say(1))) == 1)
    check("🚨 두 번 말하면 구간 2개", len(E.speech_bursts(say(2))) == 2)
    check("음량이 1/10 이어도 구간 수는 같다 (상대 에너지로 잰다)",
          len(E.speech_bursts(say(2, amp=0.03))) == 2)
    check("아주 짧은 잡음은 «말»로 안 센다",
          len(E.speech_bursts(say(1, word=0.05))) == 0)
    check("무음은 구간 0개", len(E.speech_bursts(np.zeros(sr, dtype=np.float32))) == 0)
    check("빈 배열도 죽지 않는다", E.speech_bursts(np.zeros(0, dtype=np.float32)) == [])

    # 한 번 말한 사람 넷 + 두 번 말한 사람 하나 → 뒤엣것만 takes=2
    truth = "블루투스 켜"
    pool = [(f"1x{i}", truth, say(1), {}) for i in range(4)]
    pool.append(("2x", truth, say(2), {}))
    takes = E.estimate_takes(pool)
    check("🚨 두 번 말한 발화만 takes=2 로 잡는다",
          takes["2x"] == 2 and all(takes[f"1x{i}"] == 1 for i in range(4)))
    check("표본이 전부 1회면 아무도 안 건드린다",
          set(E.estimate_takes(pool[:4]).values()) == {1})
    check("🚨 기준선을 상수로 박아 두지 않았다 (표본에서 구한다)",
          "sorted(rates)[len(rates) // 2]" in _SRC)
    check(f"아무리 봐줘도 {E._TAKE_MAX}번까지만 늘린다", E._TAKE_MAX <= 3)

    check("🚨 takes 를 반영하면 «두 번 적은» 출력이 정답이 된다",
          E.score(truth, truth + " " + truth, takes=2)["cer_err"] == 0)
    check("🚨 반영을 안 하면 그게 전부 오류로 잡힌다 (틀렸던 그 모양)",
          E.score(truth, truth + " " + truth, takes=1)["cer_err"] > 0)
    check("takes=2 인데 한 번만 적었으면 여전히 틀린 것이다",
          E.score(truth, truth, takes=2)["cer_err"] > 0)
    check("takes 기본값은 1 (부르는 쪽이 정하지 않으면 라벨 그대로)",
          E.score(truth, truth)["cer_err"] == 0)

    check("🚨 판정에 엔진 출력을 안 쓴다 (estimate_takes 가 hyp 를 안 받는다)",
          "hyp" not in E.estimate_takes.__code__.co_varnames
          and "raw" not in E.estimate_takes.__code__.co_varnames)
    check("   왜 출력으로 판정하면 안 되는지 적혀 있다",
          "맞춰 주는 것" in _SRC and "진짜 결함을 용서" in _SRC)
    check("보정 전/후를 둘 다 남긴다 (어느 쪽을 본 건지 알 수 있게)",
          '"raw_score":   score(truth, hyp, 1)' in _SRC and '"score":' in _SRC)
    check("보정을 끌 수 있다 (--no-takes 로 라벨 그대로도 재진다)",
          '"--no-takes"' in _SRC)
    check("보정한 발화 수를 조용히 넘기지 않고 찍는다", "반복 발화 {repeated}" in _SRC)
    check("원인(녹음 슬롯 4초)을 코드 옆에 적어 뒀다",
          "SLOT = 4.0" in _SRC and "남는 시간을 한 번 더 말해서" in _SRC)

    print(f"{NL}=== ⑩ 🚨 `command` 라벨이 조용히 사라지지 않는가 ===")
    # 2026-09-24 에 녹음 페이지가 «컴퓨터에게 시키는 말»(label: command)을 받기 시작했다.
    # 🚨 이 라벨을 아는 곳이 한 군데라도 빠지면 **소리는 들어오는데 안 세진다** —
    #    2026-09-23 «녹음 6명을 통째로 안 읽은» 사고와 정확히 같은 모양이다.
    def _src_of(name):
        return io.open(os.path.join(_ROOT, "scripts", name), encoding="utf-8").read()

    page = _src_of("플루이즈_녹음.html")
    check("녹음 페이지가 명령 문장을 받는다 (CMD_LINES)",
          "const CMD_LINES" in page and "label: 'command'" in page)
    check("🚨 «한 번만» 이 안내에 들어 있다 (정답표가 깨졌던 자리)",
          page.count("한 번만") >= 2)
    check("요약표가 명령 칸을 센다 (0으로 조용히 안 남게)",
          "command: 0" in page and "seen.command" in page)

    ingest = _src_of("ingest_wakeword.py")
    check("🚨 학습 적재가 command 를 «세는» 라벨로 안다",
          '"command": 0' in ingest)
    check("   그리고 모르는 라벨은 음성으로 보낸다 (소리 자체는 안 버린다)",
          'else "negative"' in ingest)

    ev = _src_of("eval_wakeword.py")
    check("🚨 웨이크워드 오탐 분모에 command 가 들어 있다",
          '"command"' in ev and "NEGATIVE_LABELS" in ev)
    check("   왜 빠지면 안 되는지(성적이 좋아 보인다) 적혀 있다",
          "성적이 **좋아 보인다**" in ev or "좋아 보인다" in ev)
    check("라벨별 표에 이름이 있다 (KeyError 로 죽지 않는다)",
          '"command": "컴퓨터에게"' in ev)

    check("이 측정 도구가 구간 종류별로 따로 찍는다",
          '("label", "구간 종류")' in _SRC)
    check("🚨 기본 라벨을 미리 command 로 바꾸지 않았다 (표본 0개를 «쟀다»로 읽지 않게)",
          'default="negative"' in _SRC and "기본을 미리 바꾸면" in _SRC)

    print(f"{NL}=== ⑪ 산출물 ===")
    check("JSON 을 utf-8 로 쓴다", 'io.open(args.json, "w", encoding="utf-8")' in _SRC)
    check("ensure_ascii=False (한글이 \\uXXXX 로 굳지 않게)", "ensure_ascii=False" in _SRC)
    check("요약과 발화별 원자료를 둘 다 남긴다",
          '"요약"' in _SRC and '"발화"' in _SRC)
    check("임시 wav 를 지운다 (측정이 디스크를 남기지 않는다)",
          "os.unlink(f)" in _SRC and "os.rmdir(tmpdir)" in _SRC)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
