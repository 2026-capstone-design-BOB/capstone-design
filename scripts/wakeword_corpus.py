# -*- coding: utf-8 -*-
"""내려받은 말뭉치를 학습에 먹이는 층 — **«흉내»를 «실측»으로** (M7 4단계)

    python scripts/wakeword_corpus.py --check          # 무엇이 쓸 수 있는 상태인가
    python scripts/wakeword_corpus.py --check --deep   # 파일을 실제로 열어 본다 (느리다)
    python scripts/wakeword_corpus.py --demo out.wav   # 증강 한 번을 귀로 들어 본다

## 이 파일이 있는 이유

지금 증강(`scripts/wakeword_data.py` 의 `augment`)은 방을 **흉내** 낸다 —
백색잡음을 더하고 반사를 한 번 섞는다. 그래서 조용한 방에서 만든 자로 재면
검증 95%가 나오고 실기는 10번 중 2번이었다.

| 지금 (흉내) | 여기서 바꾸는 것 (실측) | 무엇으로 |
|---|---|---|
| 백색잡음 더하기 | **실제 잡음을 SNR 0~20dB로** | MUSAN |
| 반사 1회 | **실측 임펄스 응답 컨볼루션** | RIR and Noises |
| 음성(negative)이 합성음뿐 | **사람이 실제로 말한 한국어** | Zeroth · AI Hub |
| (없음) | **webm/opus 왕복** | 렌더러가 webm 으로 녹음한다 |

→ [M7 §5-1](../docs/design/M7_웨이크워드_재구축.md) · 말뭉치 받기는
[`fetch_wakeword_corpora.py`](fetch_wakeword_corpora.py)

## 🚨 없으면 **없다고 말한다**

말뭉치가 안 받아져 있으면 **조용히 백색잡음으로 되돌아가지 않는다.** 그러면
«실측으로 학습했다»고 적어 놓고 실제로는 옛날 흉내로 학습한 모델이 나온다 —
[BL-59](../docs/BACKLOG.md)로 적어 둔 실패 모양의 가장 비싼 판본이다.
`available()` 이 무엇이 없는지 말하고, **부르는 쪽이 판단한다.**

## 새 의존성을 안 쓴다

`numpy` · `scipy`(컨볼루션) · `av`(flac·48kHz·코덱) 는 이미 `pluiz` 환경에 있다.
`librosa` · `soundfile` 를 새로 들이지 않는다 — 이 저장소는 V2에서 torch 를 일부러 걷어냈다.
"""
import argparse
import io
import json
import os
import sys
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import numpy as np
except ImportError as e:                                     # noqa: BLE001
    sys.exit(f"[corpus] FATAL: numpy 없음 ({e})")

SR = 16000
CORPORA = os.path.join(ROOT, "data", "corpora")
INDEX_DIR = os.path.join(CORPORA, "_index")

#: 말뭉치별 뿌리와 확장자. `fetch_wakeword_corpora.py` 가 푸는 자리와 같아야 한다.
#: 🔑 두 곳에 적히므로 `tests/test_wakeword_corpus.py` 가 **대조한다**.
SOURCES = {
    "musan_noise":  {"roots": [{"path": ["musan", "noise"]}],  "ext": (".wav",),
                     "역할": "잡음 (SNR 증강)"},
    "musan_music":  {"roots": [{"path": ["musan", "music"]}],  "ext": (".wav",),
                     "역할": "음악 (SNR 증강)"},
    "musan_speech": {"roots": [{"path": ["musan", "speech"]}], "ext": (".wav",),
                     "역할": "말소리 — 여러 사람이 동시에 말하는 소리(babble)를 만든다"},

    # 🚨 RIRS_NOISES 안에는 **성격이 정반대인 둘**이 같이 들어 있다.
    #    울림(임펄스 응답)은 «컨볼루션할 것»이고 잡음은 «더할 것»이다.
    #    섞어 세면 잡음을 울림이라고 컨볼루션하게 되는데 **오류가 안 나고 소리만 뭉개진다.**
    #
    #    ⚠️ 그런데 이름 규칙이 폴더마다 다르다 — 2026-09-18에 여기서 한 번 데였다:
    #      · simulated_rirs/largeroom/Room001/Room001-00001.wav   ← 이름에 «rir» 가 없다
    #      · real_rirs_isotropic_noises/RVB2014_type1_rir_...wav  ← 여기만 «rir»/«noise» 가 있다
    #    전체에 «rir» 필터를 걸었더니 **60,000개가 조용히 버려지고 218개만 남았다.**
    #    오류가 안 나고 숫자만 작아진다. 그래서 필터는 **뿌리마다 따로** 건다.
    "rir":          {"roots": [{"path": ["RIRS_NOISES", "simulated_rirs"]},
                               {"path": ["RIRS_NOISES", "real_rirs_isotropic_noises"],
                                "name_has": "rir"}],
                     "ext": (".wav",), "whole": True,
                     "역할": "실측/시뮬 방 울림 — 컨볼루션한다"},
    "rir_noise":    {"roots": [{"path": ["RIRS_NOISES", "pointsource_noises"]},
                               {"path": ["RIRS_NOISES", "real_rirs_isotropic_noises"],
                                "name_has": "noise"}],
                     "ext": (".wav",),
                     "역할": "점음원·등방성 잡음 — 더한다 (MUSAN 보조)"},

    "zeroth":       {"roots": [{"path": ["zeroth_korean"]}],   "ext": (".flac", ".wav"),
                     "역할": "한국어 낭독 — 음성(negative)"},
    "aihub":        {"roots": [{"path": ["manual", "aihub"]}], "ext": (".wav", ".pcm", ".flac"),
                     "역할": "한국어 자유대화·명령 — 🔴 오탐의 출처와 같은 종류"},
    "commonvoice":  {"roots": [{"path": ["manual", "commonvoice"]}], "ext": (".mp3", ".wav"),
                     "역할": "한국어 낭독 (화자 다양성)"},
}

#: 안내문 파일 — 말뭉치 파일이 아니다. 세면 «받았다»가 거짓이 된다.
_NOTE_NAMES = ("여기에_넣으세요.txt",)


def _roots(name):
    return [os.path.join(CORPORA, *r["path"]) for r in SOURCES[name]["roots"]]


def _root_label(name):
    return " · ".join(os.path.relpath(r, ROOT) for r in _roots(name))


# ── 오디오 읽기 ────────────────────────────────────────────────────
def read_16k_mono(path, start_sec=0.0, dur_sec=None):
    """어떤 형식이든 16kHz mono float32 로 읽는다.

    **PCM wav 는 `wave` + scipy 로 직접 읽는다 — PyAV 보다 12배 빠르다**
    (2026-09-18 실측: AI Hub 48kHz 파일 32.9ms → 2.7ms, 결과 상관계수 1.0000).
    말뭉치가 수만 개라 이 차이가 학습 한 번에 수십 분이 된다.
    그리고 **필요한 구간만** 읽는다 — MUSAN 파일 하나가 수 분짜리다.

    flac(Zeroth) · mp3(Common Voice) 는 PyAV 로 넘긴다.
    """
    if path.lower().endswith(".wav"):
        try:
            a = _read_wav_fast(path, start_sec, dur_sec)
            if a is not None:
                return a
        except (wave.Error, EOFError, ValueError):
            pass                                  # 형식이 다르면 PyAV 로 넘어간다
    return _read_pyav(path, start_sec, dur_sec)


def _read_wav_fast(path, start_sec, dur_sec):
    """16bit PCM wav 전용 빠른 경로. 조건이 안 맞으면 None (부르는 쪽이 PyAV 로 간다)."""
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            return None
        rate, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        st = min(int(start_sec * rate), max(0, n - 1))
        cnt = n - st if dur_sec is None else min(int(dur_sec * rate), n - st)
        w.setpos(st)
        raw = w.readframes(max(0, cnt))
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)         # 모노로 섞는다
    if rate != SR:
        # 🔑 «간격을 띄워 뽑는» 다운샘플은 앨리어싱을 만든다. resample_poly 는
        #    저역통과를 같이 걸어 준다 — 위 실측의 상관계수 1.0000 이 그 값이다.
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(SR, rate)
        x = resample_poly(x, SR // g, rate // g).astype(np.float32)
    return np.ascontiguousarray(x, dtype=np.float32)


def _read_pyav(path, start_sec=0.0, dur_sec=None):
    try:
        import av
    except ImportError as e:                                  # noqa: BLE001
        raise RuntimeError(
            f"{os.path.basename(path)} 를 읽으려면 PyAV 가 필요하다 ({e}). "
            f"`pluiz` 환경인지 확인할 것") from e
    with av.open(path) as c:
        st = next((s for s in c.streams if s.type == "audio"), None)
        if st is None:
            raise RuntimeError(f"{os.path.basename(path)}: 오디오 스트림이 없다")
        if start_sec > 0 and st.duration is not None:
            try:
                c.seek(int(start_sec / float(st.time_base)), stream=st)
            except Exception:                                 # noqa: BLE001
                pass                                          # 못 건너뛰면 앞부터 읽는다
        rs = av.AudioResampler(format="flt", layout="mono", rate=SR)
        chunks, got = [], 0
        want = None if dur_sec is None else int(dur_sec * SR)
        for frame in c.decode(st):
            for out in rs.resample(frame):
                a = out.to_ndarray().reshape(-1).astype(np.float32)
                chunks.append(a)
                got += len(a)
                if want is not None and got >= want:
                    break
            if want is not None and got >= want:
                break
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    a = np.concatenate(chunks)
    return a if want is None else a[:want]


# ── 파일 목록 (한 번 훑고 캐시한다) ──────────────────────────────────
def index(name, refresh=False):
    """말뭉치 하나의 파일 목록. `data/corpora/_index/<name>.json` 에 캐시한다.

    Zeroth 는 flac 이 수만 개라 매번 훑으면 학습 한 번에 수십 초가 날아간다.

    🚨 **캐시가 낡으면 «조용히 적은 데이터로 학습»한다.** 2026-09-18에 실제로 겪었다 —
    AI Hub 압축을 푸는 중에 목록을 만들어 28,834개로 굳었는데 실제로는 29,658개였다.
    오류가 안 나고 **숫자만 작아진다.** 그래서 캐시를 쓸 때 **만든 시각을 같이 돌려주고**,
    부르는 쪽이 낡음을 볼 수 있게 한다. 받는 중이면 `--refresh` 다.
    """
    os.makedirs(INDEX_DIR, exist_ok=True)
    cache = os.path.join(INDEX_DIR, f"{name}.json")
    if not refresh and os.path.exists(cache):
        try:
            d = json.load(io.open(cache, encoding="utf-8"))
            if isinstance(d, dict) and "files" in d:
                return d["files"]
        except (ValueError, OSError):
            pass                                              # 깨졌으면 다시 훑는다
    spec = SOURCES[name]
    exts = spec["ext"]
    out = []
    for r in spec["roots"]:
        root, needle = os.path.join(CORPORA, *r["path"]), r.get("name_has")
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn in _NOTE_NAMES or not fn.lower().endswith(exts):
                    continue
                if needle and needle not in fn.lower():
                    continue
                out.append(os.path.relpath(os.path.join(dirpath, fn), CORPORA)
                           .replace("\\", "/"))
    out = sorted(set(out))
    with io.open(cache, "w", encoding="utf-8") as f:
        json.dump({"만든시각": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "뿌리": _root_label(name),
                   "개수": len(out), "files": out}, f, ensure_ascii=False)
    return out


def index_age(name):
    """캐시를 언제 만들었나. 없으면 None."""
    cache = os.path.join(INDEX_DIR, f"{name}.json")
    if not os.path.exists(cache):
        return None
    try:
        return json.load(io.open(cache, encoding="utf-8")).get("만든시각")
    except (ValueError, OSError):
        return None


def available(refresh=False):
    """무엇이 쓸 수 있는 상태인가. **판단은 부르는 쪽이 한다.**"""
    return {name: len(index(name, refresh)) for name in SOURCES}


# ── 증강 연산 ──────────────────────────────────────────────────────
def _rms(a):
    return float(np.sqrt(np.mean(a.astype(np.float64) ** 2))) if len(a) else 0.0


def mix_noise(a, noise, snr_db):
    """`a` 에 `noise` 를 목표 SNR 로 섞는다.

    🔑 «잡음을 얼마나 크게»가 아니라 **«신호 대비 얼마나»** 로 정한다. 게인 증강과
    같이 쓰면 전자는 SNR 이 제멋대로 흔들린다 — 실제로 어떤 조건을 학습했는지 모르게 된다.
    """
    if len(noise) == 0 or _rms(noise) <= 0 or _rms(a) <= 0:
        return a.astype(np.float32)
    if len(noise) < len(a):                       # 짧으면 이어 붙여 길이를 맞춘다
        noise = np.tile(noise, int(np.ceil(len(a) / len(noise))))
    noise = noise[:len(a)]
    scale = _rms(a) / (_rms(noise) * (10.0 ** (snr_db / 20.0)))
    return (a + noise * scale).astype(np.float32)


def apply_rir(a, rir):
    """실측 임펄스 응답을 컨볼루션한다 — 방 울림을 «흉내»가 아니라 그대로.

    ⚠️ 직접음 위치(임펄스의 최대점)만큼 앞을 잘라 낸다. 안 그러면 말이 **뒤로 밀려**
    창 안에서 위치가 바뀌고, 그건 잔향이 아니라 시간이동 증강이 된다.
    ⚠️ 크기는 원래 RMS 로 되돌린다. 컨볼루션은 에너지를 바꾸는데, 그대로 두면
    모델이 잔향이 아니라 **소리 크기**를 배운다.
    """
    if len(rir) == 0 or _rms(a) <= 0:
        return a.astype(np.float32)
    from scipy.signal import fftconvolve
    rir = rir.astype(np.float32)
    peak = int(np.argmax(np.abs(rir)))
    y = fftconvolve(a.astype(np.float32), rir)[peak:peak + len(a)]
    if len(y) < len(a):
        y = np.pad(y, (0, len(a) - len(y)))
    r = _rms(y)
    if r > 0:
        y = y * (_rms(a) / r)
    return y.astype(np.float32)


def codec_roundtrip(a, bitrate=24000):
    """webm/opus 로 인코딩했다 되돌린다 — **실서비스가 webm 이다.**

    렌더러가 `audio/webm` 으로 녹음해 보낸다. 학습이 깨끗한 wav 만 보면
    거기서 또 분포가 어긋난다(M7 §5-1의 각주).
    ⚠️ opus 는 48kHz 만 받는다. 올렸다 내리는 것까지가 실제 경로와 같다.
    """
    import av
    buf = io.BytesIO()
    with av.open(buf, mode="w", format="webm") as out:
        st = out.add_stream("libopus", rate=48000)
        st.bit_rate = bitrate
        rs = av.AudioResampler(format="s16", layout="mono", rate=48000)
        frame = av.AudioFrame.from_ndarray(
            (np.clip(a, -1, 1) * 32767).astype(np.int16).reshape(1, -1),
            format="s16", layout="mono")
        frame.sample_rate = SR
        for f in rs.resample(frame):
            for pkt in st.encode(f):
                out.mux(pkt)
        for pkt in st.encode(None):
            out.mux(pkt)
    buf.seek(0)
    with av.open(buf) as c:
        s = next(s for s in c.streams if s.type == "audio")
        rs = av.AudioResampler(format="flt", layout="mono", rate=SR)
        chunks = []
        for frame in c.decode(s):
            for o in rs.resample(frame):
                chunks.append(o.to_ndarray().reshape(-1).astype(np.float32))
    if not chunks:
        return a.astype(np.float32)
    y = np.concatenate(chunks)
    # opus 는 앞에 지연을 넣는다. 길이를 원래대로 맞춘다 (뒤가 짧으면 0으로 채운다)
    return (y[:len(a)] if len(y) >= len(a)
            else np.pad(y, (0, len(a) - len(y)))).astype(np.float32)


# ── 말뭉치에서 뽑기 ────────────────────────────────────────────────
class Bank:
    """말뭉치 하나에서 **무작위 구간**을 꺼내 주는 것.

    파일 전체를 안 읽는다 — 긴 파일은 필요한 초만 읽는다(`read_16k_mono`).
    """

    def __init__(self, name, refresh=False):
        self.name = name
        self.files = index(name, refresh)

    def __len__(self):
        return len(self.files)

    def take(self, rng, dur_sec, tries=4):
        """`dur_sec` 만큼 뽑는다. 못 읽으면 다른 파일로 몇 번 다시 시도한다.

        🚨 **끝까지 실패하면 예외다.** 조용히 0(무음)을 돌려주면 «실제 잡음으로
        학습했다»고 적히면서 실제로는 무음이 섞인다.
        """
        if not self.files:
            raise RuntimeError(
                f"[corpus] {self.name}: 파일이 0개다. 먼저 받아라 — "
                f"python scripts/fetch_wakeword_corpora.py --list")
        whole = SOURCES[self.name].get("whole", False)
        want = int(dur_sec * SR)
        last = None
        for _ in range(tries):
            p = os.path.join(CORPORA, self.files[int(rng.integers(len(self.files)))])
            # 🔑 임펄스 응답은 **통째로, 처음부터** 읽는다. 앞을 잘라 내면 직접음이
            #    사라져서 «방 울림»이 아니라 «꼬리만 남은 것»이 된다.
            #    긴 파일(잡음·말소리)은 반대로 무작위 지점에서 떠야 변화가 생긴다.
            try:
                if whole:
                    a = read_16k_mono(p)
                else:
                    a = read_16k_mono(p, start_sec=float(rng.random()) * 5.0, dur_sec=dur_sec)
                    if len(a) < want:
                        # 짧은 파일이었다. 건너뛴 만큼 손해 보지 말고 **처음부터** 다시 읽는다
                        a = read_16k_mono(p, dur_sec=dur_sec)
            except Exception as e:                            # noqa: BLE001
                last = f"{os.path.basename(p)}: {e}"
                continue
            if _rms(a) <= 1e-5:
                last = f"{os.path.basename(p)}: 무음"
                continue
            if whole:
                # 🔑 **앞은 안 자르고 뒤만 자른다.** 직접음은 맨 앞에 있다.
                #    상한을 두는 건 비용 때문이 아니라 **길이가 결과에 안 새게** 하려는 것이다 —
                #    실측(2026-09-18)으로 임펄스는 중앙 1.00초·최대 2.00초이고,
                #    꼬리를 잘라도 컨볼루션은 1.36ms → 1.12ms로 **거의 안 빨라진다.**
                #    ⚠️ 여기에 «27배 빨라진다»고 적었다가 고쳤다. 그 81ms 는 꼬리가 아니라
                #       **scipy 첫 호출 준비 비용**이었다(예열 없이 재서 생긴 착각).
                return a[:want].astype(np.float32) if len(a) > want else a.astype(np.float32)
            if len(a) >= want * 0.5:
                if len(a) < want:
                    a = np.pad(a, (0, want - len(a)))
                return a[:want]
            last = f"{os.path.basename(p)}: 너무 짧다 ({len(a)/SR:.2f}초)"
        raise RuntimeError(f"[corpus] {self.name}: {tries}번 시도했으나 못 읽었다 ({last})")

    def babble(self, rng, dur_sec, n=4):
        """여러 사람이 동시에 말하는 소리를 만든다 — **전시회장에 가장 가깝다.**

        전시회 소음은 미리 못 구한다(M7 §7). 가장 가까운 대체가 이것이고
        MUSAN speech 로 만든다.
        """
        mix = np.zeros(int(dur_sec * SR), dtype=np.float32)
        for _ in range(max(2, n)):
            mix += self.take(rng, dur_sec)
        r = _rms(mix)
        return (mix / r * 0.1).astype(np.float32) if r > 0 else mix


class Augmenter:
    """말뭉치로 증강하는 것. **한 번 만들어 두고 계속 쓴다**(목록 훑기가 비싸다).

    `scripts/wakeword_data.py` 의 `augment` 와 **같은 자리**를 대신한다. 다른 점은
    잡음·잔향이 «흉내»가 아니라 실제 녹음이라는 것뿐이고, 속도·게인은 그대로 둔다.

    🚨 **없는 것을 조용히 건너뛰지 않는다.** `require()` 를 통과해야 쓸 수 있고,
    무엇이 없어서 무엇을 못 하는지 `missing` 에 남는다.
    """

    #: 이것들이 있어야 «실측 증강»이라고 말할 수 있다.
    REQUIRED = ("rir",)
    #: 잡음은 이 중 **아무거나 하나** 있으면 된다 (MUSAN 이 가장 좋다).
    NOISE_ANY = ("musan_noise", "musan_music", "rir_noise")
    #: 음성(negative)도 아무거나 하나.
    SPEECH_ANY = ("zeroth", "aihub", "commonvoice", "musan_speech")

    def __init__(self, refresh=False, snr_range=(0.0, 20.0), codec_prob=0.35):
        self.banks = {}
        self.missing = []
        for name in SOURCES:
            b = Bank(name, refresh)
            if len(b):
                self.banks[name] = b
            else:
                self.missing.append(name)
        self.snr_range = snr_range
        self.codec_prob = codec_prob

    def _any(self, names):
        return [self.banks[n] for n in names if n in self.banks]

    def require(self):
        """쓸 수 있는 상태인가. **아니면 왜 아닌지 말하고 예외.**"""
        lack = [n for n in self.REQUIRED if n not in self.banks]
        if not self._any(self.NOISE_ANY):
            lack.append("잡음(" + "·".join(self.NOISE_ANY) + " 중 하나)")
        if not self._any(self.SPEECH_ANY):
            lack.append("음성(" + "·".join(self.SPEECH_ANY) + " 중 하나)")
        if lack:
            raise RuntimeError(
                "[corpus] 실측 증강을 할 수 없다 — 없는 것: " + ", ".join(lack) +
                "\n  python scripts/fetch_wakeword_corpora.py --list")
        return self

    def describe(self):
        return " · ".join(f"{k} {len(v):,}" for k, v in self.banks.items())

    def one(self, audio, rng):
        """클립 하나 → 변형 하나. **순서가 실제 신호 경로와 같다.**

        입 → **방(잔향)** → 마이크(게인) → **주변 잡음** → **코덱**.
        순서를 바꾸면(예: 잡음을 먼저 넣고 잔향을 걸면) 잡음까지 그 방에서 울린 것이
        되는데, 실제로는 잡음도 마이크 앞에서 따로 들어온다.
        """
        a = np.asarray(audio, dtype=np.float32)

        # ① 속도 — 말 빠르기 (기존 증강에서 그대로 가져온다)
        speed = rng.uniform(0.9, 1.12)
        if abs(speed - 1.0) > 0.01:
            idx = np.arange(0, len(a), speed)
            a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)

        # ② 방 울림 — 실측 임펄스 응답
        if rng.random() < 0.7:
            a = apply_rir(a, self.banks["rir"].take(rng, 1.0))

        # ③ 게인 — 마이크 입력 레벨 차이. 실측에서 사용자 마이크 최대 진폭이 0.126이었다
        a = a * rng.uniform(0.15, 1.4)

        # ④ 주변 잡음 — 목표 SNR 로
        noise_banks = self._any(self.NOISE_ANY)
        if noise_banks and rng.random() < 0.85:
            b = noise_banks[int(rng.integers(len(noise_banks)))]
            dur = max(0.2, len(a) / SR)
            if b.name == "musan_speech" and rng.random() < 0.5:
                noise = b.babble(rng, dur)          # 전시회장에 가장 가까운 것
            else:
                noise = b.take(rng, dur)
            a = mix_noise(a, noise, float(rng.uniform(*self.snr_range)))

        # ⑤ 코덱 — 렌더러가 webm 으로 보낸다
        if rng.random() < self.codec_prob:
            try:
                a = codec_roundtrip(a)
            except Exception:                                 # noqa: BLE001
                pass            # 코덱은 있으면 좋은 것이다. 없다고 증강 전체를 버리지 않는다
        return np.clip(a, -1.0, 1.0).astype(np.float32)

    def many(self, audio, rng, n=3):
        return [self.one(audio, rng) for _ in range(n)]

    def speech_negative(self, rng, dur_sec=2.0):
        """**사람이 실제로 말한 한국어** 한 조각 — 음성(negative) 표본.

        🔴 오탐의 출처가 «자유 발화»였다. 합성음만으로는 이 자리를 못 메운다.
        """
        banks = self._any(self.SPEECH_ANY)
        if not banks:
            raise RuntimeError("[corpus] 음성(negative)으로 쓸 말뭉치가 없다")
        return banks[int(rng.integers(len(banks)))].take(rng, dur_sec)


# ── 점검 ───────────────────────────────────────────────────────────
def cmd_check(deep=False, refresh=False):
    # 🔑 점검은 **항상 새로 훑는다.** 캐시를 보여 주면 «받는 중»일 때 낡은 숫자를 말하고,
    #    그게 곧 «조용히 적은 데이터로 학습»의 입구다(`index` 의 주석).
    print("말뭉치 상태 — M7 4단계가 쓰는 것   (목록을 새로 훑는다)\n")
    avail = available(refresh=True)
    ok = 0
    for name, n in avail.items():
        mark = "✅" if n else "⬜"
        print(f"  {mark} {name:14s} 파일 {n:>7,}개   {SOURCES[name]['역할']}")
        print(f"      {_root_label(name)}")
        if n:
            ok += 1
    print()
    if deep:
        print("  🔍 실제로 열어 본다 (말뭉치마다 1개씩)")
        rng = np.random.default_rng(0)
        for name, n in avail.items():
            if not n:
                continue
            try:
                a = Bank(name).take(rng, 1.0)
                print(f"      ✅ {name:14s} 1초 읽음 · RMS {_rms(a):.4f}")
            except Exception as e:                            # noqa: BLE001
                print(f"      ❌ {name:14s} {e}")
        print()

    # 🚨 «있는 것만 세고 됐다»고 말하지 않는다. 무엇이 없으면 무엇을 못 하는지 말한다.
    need = {
        "musan_noise":  "실제 잡음 SNR 증강",
        "musan_speech": "babble(여러 사람 말소리) — 전시회장 대체재",
        "rir":          "실측 방 울림",
    }
    # 🔑 한국어 음성(negative)은 **둘 중 하나만 있으면 된다.** 둘 다 없을 때만 막힌다.
    if not (avail.get("zeroth") or avail.get("aihub")):
        need["zeroth"] = "한국어 음성(negative) — Zeroth 나 AI Hub 둘 중 하나"
    missing = [f"{k}({v})" for k, v in need.items() if not avail.get(k)]
    if missing:
        print("  ⚠️ 아직 못 하는 것:")
        for m in missing:
            print(f"      - {m}")
        print("\n  👉 python scripts/fetch_wakeword_corpora.py --list")
        return 1
    print("  ✅ 실측 증강에 필요한 것이 다 있다.")
    if not avail.get("aihub"):
        print("  💡 AI Hub 는 아직 없다 — 없어도 돌지만, 🔴 오탐의 출처(자유 발화)와"
              " 같은 종류라 들어오면 값이 가장 크다")
    return 0


def cmd_demo(out_path, seed=0):
    """증강 한 번을 파일로 떨어뜨린다 — **귀로 들어 보는 것이 검사보다 빠를 때가 있다.**"""
    rng = np.random.default_rng(seed)
    base = np.zeros(int(2.0 * SR), dtype=np.float32)
    t = np.arange(len(base)) / SR
    base[int(0.4 * SR):int(1.2 * SR)] = (
        0.3 * np.sin(2 * np.pi * 220 * t[:int(0.8 * SR)])).astype(np.float32)
    steps = [("원본", base)]
    try:
        a = apply_rir(base, Bank("rir").take(rng, 0.5))
        steps.append(("방 울림", a))
    except Exception as e:                                    # noqa: BLE001
        print(f"  ⚠️ 방 울림 건너뜀: {e}")
        a = base
    try:
        a = mix_noise(a, Bank("musan_noise").take(rng, 2.0), snr_db=10.0)
        steps.append(("잡음 SNR 10dB", a))
    except Exception as e:                                    # noqa: BLE001
        print(f"  ⚠️ 잡음 건너뜀: {e}")
    try:
        a = codec_roundtrip(a)
        steps.append(("webm/opus 왕복", a))
    except Exception as e:                                    # noqa: BLE001
        print(f"  ⚠️ 코덱 건너뜀: {e}")
    for label, x in steps:
        print(f"  {label:18s} RMS {_rms(x):.4f} · 최대 {float(np.abs(x).max()):.3f}")
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"\n  저장 → {out_path}  (마지막 단계까지 거친 것)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="말뭉치 증강 층 (M7 4단계)")
    ap.add_argument("--check", action="store_true", help="무엇이 쓸 수 있는 상태인가")
    ap.add_argument("--deep", action="store_true", help="--check 와 같이: 파일을 실제로 열어 본다")
    ap.add_argument("--refresh", action="store_true", help="파일 목록 캐시를 다시 만든다")
    ap.add_argument("--demo", metavar="OUT.wav", help="증강 한 번을 파일로 떨어뜨린다")
    a = ap.parse_args()
    if a.demo:
        return cmd_demo(a.demo)
    return cmd_check(a.deep, a.refresh)


if __name__ == "__main__":
    sys.exit(main())
