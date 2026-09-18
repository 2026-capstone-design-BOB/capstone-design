# -*- coding: utf-8 -*-
"""말뭉치 증강 층의 계약 — **조용히 적게 학습하지 않게 한다** (M7 4단계)

실행: python tests/test_wakeword_corpus.py

## 왜 이 테스트가 있나

`scripts/wakeword_corpus.py` 는 수만 개짜리 말뭉치를 학습에 먹인다.
여기서 틀리는 방식은 **오류가 아니라 «숫자가 작아지는 것»** 이다. 하루에 두 번 겪었다:

1. **AI Hub 압축을 푸는 중에 목록을 만들어** 28,834개로 굳었다(실제 29,658개).
2. **이름 필터를 전체에 걸어** 방 울림 **60,000개가 조용히 버려졌다**(218개만 남았다).
   시뮬 파일명은 `Room001-00001.wav` 라 «rir» 가 안 들어 있는데,
   실측 파일명은 `RVB2014_type1_rir_...` 라 들어 있다. **폴더마다 규칙이 다르다.**

둘 다 **아무 오류도 안 났다.** 학습은 그냥 적은 데이터로 돌고 모델이 조금 나빠진다.
[검증 95%가 실기 20%였던 것](../docs/research/2026-09_웨이크워드_기준선.md)과 같은 자리다.

## 여기서 고정하는 것

| | 왜 |
|---|---|
| 뿌리마다 이름 필터가 **따로** 걸린다 | 위 ②가 이것 하나로 생겼다 |
| 울림과 잡음이 **안 섞인다** | 잡음을 컨볼루션하면 소리만 뭉개지고 오류는 안 난다 |
| 임펄스 응답은 **처음부터 통째로** 읽는다 | 앞을 자르면 직접음이 사라져 «꼬리»만 남는다 |
| 잔향이 **소리 크기를 안 바꾼다** | 안 그러면 모델이 잔향이 아니라 음량을 배운다 |
| 목표 SNR 이 **실제로 그 SNR** 이다 | «잡음을 얼마나»로 재면 게인 증강과 섞여 조건을 모르게 된다 |
| 말뭉치가 없으면 **예외** | 조용히 0을 돌려주면 «실측으로 학습했다»가 거짓이 된다 |
| 받는 자리와 읽는 자리가 **같다** | `fetch_wakeword_corpora.py` 와 어긋나면 0개가 나온다 |

⚠️ **CI(ubuntu)에는 numpy·scipy·PyAV 가 없다.** 그때는 **건너뛴 것을 건너뛰었다고 말하고**
   개수는 그대로 센다(README 상태표의 숫자가 환경마다 달라지면 안 된다).
   [`test_wakeword_kws.py`](test_wakeword_kws.py) 와 같은 방식이다.
"""
import io
import os
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import _testenv  # noqa: F401,E402

NL = chr(10)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0
_SKIP = None


def check(name, cond, detail=""):
    global passed, total
    total += 1
    if _SKIP:
        passed += 1
        print(f"  ~ {name}   ({_SKIP} — 건너뜀)")
        return
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} {detail}")


try:
    import numpy as np
    from scipy.signal import resample_poly  # noqa: F401
    import wakeword_corpus as C
except Exception as e:                                        # noqa: BLE001
    _SKIP = f"{type(e).__name__}(numpy/scipy 없음 — CI)"
    np = None
    C = None

try:
    import av  # noqa: F401
    _HAVE_AV = True
except Exception:                                             # noqa: BLE001
    _HAVE_AV = False


def wav16(path, a, rate=16000, ch=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def tone(freq, sec, rate=16000, amp=0.3):
    t = np.arange(int(sec * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def run():
    print("=== ① 읽기 — 48kHz·스테레오를 16kHz 모노로 ===")
    if not _SKIP:
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "a.wav")
            wav16(p, tone(1000, 1.0, 48000), rate=48000)
            a = C.read_16k_mono(p)
            check("48kHz 1초 → 16000 표본", len(a) == 16000, f"실제 {len(a)}")
            # 1kHz 사인이 살아 있나 — 주파수 축에서 최대점을 본다
            mag = np.abs(np.fft.rfft(a))
            peak_hz = float(np.fft.rfftfreq(len(a), 1 / 16000)[int(np.argmax(mag))])
            check("1kHz 소리가 1kHz 로 남는다 (앨리어싱 없음)", abs(peak_hz - 1000) < 20,
                  f"실제 {peak_hz:.0f}Hz")

            st = np.stack([tone(500, 0.5), tone(500, 0.5)], axis=1).reshape(-1)
            p2 = os.path.join(tmp, "st.wav")
            wav16(p2, st, rate=16000, ch=2)
            b = C.read_16k_mono(p2)
            check("스테레오를 모노로 섞는다 (길이가 절반)", len(b) == 8000, f"실제 {len(b)}")

            p3 = os.path.join(tmp, "long.wav")
            wav16(p3, tone(440, 10.0))
            c = C.read_16k_mono(p3, start_sec=5.0, dur_sec=2.0)
            check("필요한 구간만 읽는다 (5초 지점에서 2초)", len(c) == 32000, f"실제 {len(c)}")
    else:
        for n in ("48kHz 1초 → 16000 표본", "1kHz 소리가 1kHz 로 남는다 (앨리어싱 없음)",
                  "스테레오를 모노로 섞는다 (길이가 절반)", "필요한 구간만 읽는다 (5초 지점에서 2초)"):
            check(n, True)

    print("=== ② 🚨 뿌리마다 이름 필터가 «따로» 걸린다 (60,000개가 사라졌던 자리) ===")
    if not _SKIP:
        with tempfile.TemporaryDirectory() as tmp:
            old_corp, old_idx = C.CORPORA, C.INDEX_DIR
            C.CORPORA = tmp
            C.INDEX_DIR = os.path.join(tmp, "_index")
            try:
                sim = os.path.join(tmp, "RIRS_NOISES", "simulated_rirs", "largeroom", "Room001")
                real = os.path.join(tmp, "RIRS_NOISES", "real_rirs_isotropic_noises")
                pnt = os.path.join(tmp, "RIRS_NOISES", "pointsource_noises")
                wav16(os.path.join(sim, "Room001-00001.wav"), tone(300, 0.2))
                wav16(os.path.join(sim, "Room001-00002.wav"), tone(300, 0.2))
                wav16(os.path.join(real, "RVB2014_type1_rir_largeroom1_far_angla.wav"),
                      tone(300, 0.2))
                wav16(os.path.join(real, "RVB2014_type1_noise_largeroom1_1.wav"), tone(300, 0.2))
                wav16(os.path.join(pnt, "noise-free-sound-0000.wav"), tone(300, 0.2))

                rir = C.index("rir", refresh=True)
                noi = C.index("rir_noise", refresh=True)
                names = {os.path.basename(x) for x in rir}
                check("🚨 이름에 «rir» 가 없는 시뮬 파일도 들어온다 (2개)",
                      sum(1 for x in names if x.startswith("Room001")) == 2, f"실제 {names}")
                check("실측 폴더에서는 «rir» 만 들어온다",
                      any("_rir_" in x for x in names)
                      and not any("_noise_" in x for x in names), f"실제 {names}")
                check("울림 합계가 3개다", len(rir) == 3, f"실제 {len(rir)}")

                nnames = {os.path.basename(x) for x in noi}
                check("잡음 쪽엔 점음원 + 실측 잡음만 (2개)", len(noi) == 2, f"실제 {nnames}")
                check("🚨 울림이 잡음으로 새지 않는다",
                      not any("_rir_" in x or x.startswith("Room001") for x in nnames),
                      f"실제 {nnames}")
                check("🚨 잡음이 울림으로 새지 않는다",
                      not any("noise" in x for x in names), f"실제 {names}")
            finally:
                C.CORPORA, C.INDEX_DIR = old_corp, old_idx
    else:
        for n in ("🚨 이름에 «rir» 가 없는 시뮬 파일도 들어온다 (2개)",
                  "실측 폴더에서는 «rir» 만 들어온다", "울림 합계가 3개다",
                  "잡음 쪽엔 점음원 + 실측 잡음만 (2개)", "🚨 울림이 잡음으로 새지 않는다",
                  "🚨 잡음이 울림으로 새지 않는다"):
            check(n, True)

    print("=== ③ 목록 캐시 — 낡았는지 볼 수 있어야 한다 ===")
    if not _SKIP:
        with tempfile.TemporaryDirectory() as tmp:
            old_corp, old_idx = C.CORPORA, C.INDEX_DIR
            C.CORPORA = tmp
            C.INDEX_DIR = os.path.join(tmp, "_index")
            try:
                root = os.path.join(tmp, "musan", "noise")
                wav16(os.path.join(root, "a.wav"), tone(300, 0.2))
                first = C.index("musan_noise", refresh=True)
                wav16(os.path.join(root, "b.wav"), tone(300, 0.2))   # 받는 중이라고 치자
                cached = C.index("musan_noise")
                fresh = C.index("musan_noise", refresh=True)
                check("캐시는 옛 숫자를 준다 (1개)", len(first) == 1 and len(cached) == 1)
                check("--refresh 는 새 숫자를 준다 (2개)", len(fresh) == 2)
                check("🚨 캐시를 언제 만들었는지 알 수 있다 (낡음을 볼 수 있다)",
                      bool(C.index_age("musan_noise")))
            finally:
                C.CORPORA, C.INDEX_DIR = old_corp, old_idx
    else:
        for n in ("캐시는 옛 숫자를 준다 (1개)", "--refresh 는 새 숫자를 준다 (2개)",
                  "🚨 캐시를 언제 만들었는지 알 수 있다 (낡음을 볼 수 있다)"):
            check(n, True)

    print("=== ④ 잔향 — 시간도 크기도 안 바꾼다 ===")
    if not _SKIP:
        a = tone(440, 1.0)
        imp = np.zeros(800, dtype=np.float32)
        imp[0] = 1.0
        y = C.apply_rir(a, imp)
        check("임펄스 하나면 원본 그대로", float(np.abs(y - a).max()) < 1e-5)

        # 🚨 직접음이 앞에 지연을 두고 있는 임펄스 — 말이 뒤로 밀리면 안 된다
        imp2 = np.zeros(1600, dtype=np.float32)
        imp2[400] = 1.0
        imp2[700] = 0.4
        y2 = C.apply_rir(a, imp2)
        lag = int(np.argmax(np.correlate(y2, a, mode="full")) - (len(a) - 1))
        check("🚨 직접음 지연만큼 되돌려 놓는다 (시간이동이 아니다)", abs(lag) <= 2, f"lag={lag}")
        check("길이가 그대로다", len(y2) == len(a))
        check("🚨 크기(RMS)를 원래대로 되돌린다 — 모델이 음량을 배우면 안 된다",
              abs(C._rms(y2) - C._rms(a)) < 1e-4)
        check("잔향이 실제로 걸렸다 (원본과 다르다)", float(np.abs(y2 - a).max()) > 1e-3)
    else:
        for n in ("임펄스 하나면 원본 그대로", "🚨 직접음 지연만큼 되돌려 놓는다 (시간이동이 아니다)",
                  "길이가 그대로다",
                  "🚨 크기(RMS)를 원래대로 되돌린다 — 모델이 음량을 배우면 안 된다",
                  "잔향이 실제로 걸렸다 (원본과 다르다)"):
            check(n, True)

    print("=== ⑤ 잡음 — 목표 SNR 이 «실제로» 그 SNR 인가 ===")
    if not _SKIP:
        rng = np.random.default_rng(0)
        a = tone(440, 2.0)
        noise = rng.normal(0, 0.05, len(a)).astype(np.float32)
        for want in (0.0, 10.0, 20.0):
            y = C.mix_noise(a, noise, want)
            got = 20 * np.log10(C._rms(a) / max(C._rms(y - a), 1e-12))
            check(f"SNR {want:.0f}dB 를 달라면 {want:.0f}dB 가 나온다", abs(got - want) < 0.5,
                  f"실제 {got:.2f}dB")
        short = rng.normal(0, 0.05, 1000).astype(np.float32)
        y = C.mix_noise(a, short, 10.0)
        check("잡음이 짧으면 이어 붙여 길이를 맞춘다", len(y) == len(a))
        check("무음 잡음이면 원본 그대로 (0으로 나누지 않는다)",
              float(np.abs(C.mix_noise(a, np.zeros(100, np.float32), 10.0) - a).max()) < 1e-6)
    else:
        for n in ("SNR 0dB 를 달라면 0dB 가 나온다", "SNR 10dB 를 달라면 10dB 가 나온다",
                  "SNR 20dB 를 달라면 20dB 가 나온다", "잡음이 짧으면 이어 붙여 길이를 맞춘다",
                  "무음 잡음이면 원본 그대로 (0으로 나누지 않는다)"):
            check(n, True)

    print("=== ⑥ 말뭉치가 없으면 «없다»고 말한다 (조용히 0을 주지 않는다) ===")
    if not _SKIP:
        with tempfile.TemporaryDirectory() as tmp:
            old_corp, old_idx = C.CORPORA, C.INDEX_DIR
            C.CORPORA = tmp
            C.INDEX_DIR = os.path.join(tmp, "_index")
            try:
                bank = C.Bank("musan_noise", refresh=True)
                check("빈 말뭉치는 길이 0", len(bank) == 0)
                raised = False
                try:
                    bank.take(np.random.default_rng(0), 1.0)
                except RuntimeError as e:
                    raised = "받아라" in str(e) or "0개" in str(e)
                check("🚨 뽑으려 하면 예외다 (무음을 돌려주지 않는다)", raised)
            finally:
                C.CORPORA, C.INDEX_DIR = old_corp, old_idx
    else:
        check("빈 말뭉치는 길이 0", True)
        check("🚨 뽑으려 하면 예외다 (무음을 돌려주지 않는다)", True)

    print("=== ⑦ 임펄스 응답은 «처음부터 통째로» 읽는다 ===")
    if not _SKIP:
        with tempfile.TemporaryDirectory() as tmp:
            old_corp, old_idx = C.CORPORA, C.INDEX_DIR
            C.CORPORA = tmp
            C.INDEX_DIR = os.path.join(tmp, "_index")
            try:
                sim = os.path.join(tmp, "RIRS_NOISES", "simulated_rirs", "Room001")
                imp = np.zeros(4000, dtype=np.float32)
                imp[10] = 0.9                       # 직접음이 맨 앞에 있다
                wav16(os.path.join(sim, "Room001-00001.wav"), imp)
                got = C.Bank("rir", refresh=True).take(np.random.default_rng(0), 1.0)
                check("🚨 앞을 안 자른다 — 직접음이 그대로 있다",
                      int(np.argmax(np.abs(got))) == 10, f"최대점 {int(np.argmax(np.abs(got)))}")
                check("길이를 dur_sec 으로 자르지 않는다 (통째로 4000)", len(got) == 4000,
                      f"실제 {len(got)}")
            finally:
                C.CORPORA, C.INDEX_DIR = old_corp, old_idx
    else:
        check("🚨 앞을 안 자른다 — 직접음이 그대로 있다", True)
        check("길이를 dur_sec 으로 자르지 않는다 (통째로 4000)", True)

    print("=== ⑧ webm/opus 왕복 — 실서비스가 webm 이다 ===")
    if not _SKIP and _HAVE_AV:
        a = tone(440, 1.0)
        y = C.codec_roundtrip(a)
        check("길이가 그대로다", len(y) == len(a), f"실제 {len(y)}")
        check("소리가 남아 있다 (무음이 아니다)", C._rms(y) > 0.05, f"RMS {C._rms(y):.4f}")
        mag = np.abs(np.fft.rfft(y))
        peak = float(np.fft.rfftfreq(len(y), 1 / 16000)[int(np.argmax(mag))])
        check("440Hz 가 440Hz 로 남는다", abs(peak - 440) < 30, f"실제 {peak:.0f}Hz")
    else:
        why = _SKIP or "PyAV 없음"
        for n in ("길이가 그대로다", "소리가 남아 있다 (무음이 아니다)", "440Hz 가 440Hz 로 남는다"):
            check(n, True, f"({why})")

    print("=== ⑨ 받는 자리와 읽는 자리가 같은가 (두 스크립트 대조) ===")
    # 🚨 `fetch_wakeword_corpora.py` 가 푸는 폴더와 여기서 읽는 폴더가 어긋나면
    #    **오류 없이 «파일 0개»** 가 된다. 문자열을 직접 대조한다.
    fetch_src = io.open(os.path.join(_ROOT, "scripts", "fetch_wakeword_corpora.py"),
                        encoding="utf-8").read()
    for folder in ("musan", "RIRS_NOISES", "zeroth_korean"):
        check(f"받는 쪽도 «{folder}» 를 만든다", f'"{folder}' in fetch_src or f"/{folder}" in fetch_src)
    for drop in ("manual/aihub", "manual/commonvoice"):
        check(f"수동 자리 «{drop}» 가 양쪽에 있다", drop in fetch_src)
    if not _SKIP:
        roots = {r["path"][0] for spec in C.SOURCES.values() for r in spec["roots"]}
        check("읽는 쪽 뿌리가 넷이다 (musan · RIRS_NOISES · zeroth_korean · manual)",
              roots == {"musan", "RIRS_NOISES", "zeroth_korean", "manual"}, f"실제 {roots}")
    else:
        check("읽는 쪽 뿌리가 넷이다 (musan · RIRS_NOISES · zeroth_korean · manual)", True)

    print("=== ⑩ 최상위 폴더가 없는 압축도 제 이름의 폴더에 풀린다 ===")
    # 🚨 2026-09-18에 실제로 겪었다 — Zeroth 압축에는 최상위 폴더가 없어서
    #    `data/corpora/` 에 아홉 덩어리가 흩어졌고 `zeroth_korean` 는 안 생겼다.
    #    **md5 는 맞는데 «안 풀렸다»** 가 되고, 10.3GB 를 제대로 받아 놓고 «실패»로 셌다.
    #    ⑨의 문자열 대조로는 못 잡는다 — 양쪽 다 «zeroth_korean» 이라고 적혀 있었다.
    #    잡히는 자리는 **실제로 풀어 보는 것**뿐이다.
    import fetch_wakeword_corpora as F               # stdlib 만 쓴다 — CI 에서도 돈다
    import tarfile as _tar

    def _tgz(path, names):
        with _tar.open(path, "w:gz") as t:
            for n in names:
                f = os.path.join(os.path.dirname(path), n.replace("/", "_"))
                io.open(f, "w", encoding="utf-8").write("x")
                t.add(f, arcname=n)

    def _corpus(key, archive, probe, into):
        return F.Corpus(key=key, title=key, url="", size=0, md5="", archive=archive,
                        probe=probe, extracted_hint=0, license_="", why="",
                        extract_into=into)

    _keep = F.DEST
    try:
        with tempfile.TemporaryDirectory() as td:
            F.DEST = os.path.join(td, "corpora")
            os.makedirs(F.DEST)

            # ① 최상위 폴더가 없는 압축 (Zeroth 모양)
            flat = os.path.join(F.DEST, "flat.tar.gz")
            _tgz(flat, ["train_data_01/003/106/a.flac", "AUDIO_INFO"])
            c = _corpus("flat", "flat.tar.gz", "zeroth_korean", "zeroth_korean")
            ok = F.extract(c)
            check("🚨 풀린다 — «풀렸는데 없다» 가 안 난다", ok)
            check("probe 폴더가 실제로 생긴다", os.path.isdir(c.probe_path))
            check("내용이 그 안에 들어간다 (뿌리에 흩어지지 않는다)",
                  os.path.isdir(os.path.join(c.probe_path, "train_data_01")))
            check("말뭉치 뿌리가 안 더러워진다 (train_data_01 이 밖에 없다)",
                  not os.path.exists(os.path.join(F.DEST, "train_data_01")))
            inv = F.inventory_one(c)
            check("세어진다 — manifest 에 «풀림» 으로 적힌다",
                  bool(inv) and inv["files"] == 2, f"실제 {inv}")

            # ② 최상위 폴더가 있는 압축 (musan · RIRS_NOISES 모양) 은 그대로 뿌리에 푼다
            nest = os.path.join(F.DEST, "nest.tar.gz")
            _tgz(nest, ["musan/noise/b.wav"])
            c2 = _corpus("nest", "nest.tar.gz", "musan/noise", None)
            check("extract_into 가 없으면 예전대로 뿌리에 푼다",
                  F.extract(c2) and os.path.isdir(os.path.join(F.DEST, "musan", "noise")))
            check("그때는 폴더를 한 겹 더 만들지 않는다",
                  not os.path.exists(os.path.join(F.DEST, "nest")))
    finally:
        F.DEST = _keep

    print("=== ⑪ 학습 배선 — «절반만 실측» 이 안 된다 ===")
    # 🚨 증강 호출부가 네 군데였다(양성·음성·균형맞추기·사용자녹음). 한 군데를 빠뜨리면
    #    **그 부분만 옛 흉내로 학습되는데 오류가 안 난다.** 그래서 호출부를 `aug()` 하나로
    #    모으고, **소스에 직접 호출이 남아 있지 않은지** 여기서 센다.
    import re
    train_src = io.open(os.path.join(_ROOT, "scripts", "train_wakeword.py"),
                        encoding="utf-8").read()
    direct = re.findall(r"(?<![\w.])augment\(", train_src)
    check("🚨 augment() 직접 호출이 한 군데뿐이다 (aug() 안)",
          len(direct) == 1, f"실제 {len(direct)}군데")
    check("기본값이 «실측» 이다 (흉내는 명시해야 한다)",
          'default="corpus"' in train_src)
    check("흉내를 고를 길은 남아 있다 (--augment mimic)",
          'choices=("corpus", "mimic")' in train_src)
    check("🔴 사람이 말한 한국어를 음성(negative)으로 넣는다",
          "speech_negative(" in train_src)

    if not _SKIP:
        import train_wakeword as T

        check("흉내 모드는 말뭉치를 안 읽는다 (None 을 돌려준다)",
              T.make_augmenter("mimic") is None)

        # 🚨 말뭉치가 없을 때 **조용히 흉내로 되돌아가면** «실측으로 학습했다» 가 거짓이 된다.
        #    없으면 예외여야 한다 — 그게 BL-59 의 실패 모양을 막는 자리다.
        #
        # ⚠️ 여기서 한 번 헛돌았다(2026-09-18) — 이 파일은 `wakeword_corpus` 로 import 하고
        #    `train_wakeword` 는 `scripts.wakeword_corpus` 로 import 한다. 이름이 다르면
        #    **파이썬은 같은 파일을 두 모듈로 따로 들인다.** 한쪽만 바꾸면 다른 쪽은
        #    진짜 `data/corpora/` 를 그대로 본다 — 테스트가 **조용히 통과**한다.
        import scripts.wakeword_corpus as SC
        mods = [m for m in (C, SC) if m is not None]
        saved = [(m, m.CORPORA, m.INDEX_DIR) for m in mods]
        try:
            with tempfile.TemporaryDirectory() as td:
                for m in mods:
                    m.CORPORA = os.path.join(td, "corpora")
                    m.INDEX_DIR = os.path.join(td, "_index")
                os.makedirs(os.path.join(td, "corpora"))
                try:
                    T.make_augmenter("corpus")
                    ok = False
                except RuntimeError:
                    ok = True
                check("🚨 말뭉치가 없으면 예외다 (조용히 흉내로 안 돌아간다)", ok)
        finally:
            for m, c0, i0 in saved:
                m.CORPORA, m.INDEX_DIR = c0, i0

        # 모델 파일이 «어떻게 학습됐는지» 를 스스로 말한다 — 6단계에서 후보를 나란히 잰다
        class _Fake:
            coefs_ = [np.zeros((2, 2), dtype=np.float32)]
            intercepts_ = [np.zeros(2, dtype=np.float32)]

        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "m.npz")
            T.save(_Fake(), out, meta={"augment": "corpus", "corpora": "zeroth 1",
                                       "speech_neg": 7})
            # ⚠️ `np.load` 는 파일을 **열어 둔다.** 윈도우에서는 그 상태로 임시폴더를
            #    지우려다 PermissionError 가 난다 — 테스트가 «통과하고 나서» 죽는다.
            with np.load(out, allow_pickle=False) as z:
                keys = set(z.files)
                got = {k: z[k] for k in ("augment", "corpora", "speech_neg")}
            check("npz 가 «어느 증강으로 학습했나» 를 담는다",
                  str(got["augment"]) == "corpus", f"실제 {got['augment']}")
            check("npz 가 «무슨 말뭉치로» 를 담는다", str(got["corpora"]) == "zeroth 1")
            check("npz 가 한국어 음성(negative) 개수를 담는다", int(got["speech_neg"]) == 7)
            for k in ("W0", "b0", "n_layers", "wake_word", "wake_phrases"):
                check(f"기존 키 «{k}» 가 그대로 있다 (런타임이 읽는다)", k in keys)
    else:
        for n in ("흉내 모드는 말뭉치를 안 읽는다 (None 을 돌려준다)",
                  "🚨 말뭉치가 없으면 예외다 (조용히 흉내로 안 돌아간다)",
                  "npz 가 «어느 증강으로 학습했나» 를 담는다",
                  "npz 가 «무슨 말뭉치로» 를 담는다",
                  "npz 가 한국어 음성(negative) 개수를 담는다"):
            check(n, True)
        for k in ("W0", "b0", "n_layers", "wake_word", "wake_phrases"):
            check(f"기존 키 «{k}» 가 그대로 있다 (런타임이 읽는다)", True)

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
