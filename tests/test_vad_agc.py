"""AGC 끄기 + VAD 결과 기록 — BL-81 의 회귀 자물쇠 (2026-10-01).

## 왜 이 테스트가 생겼나

2026-10-01 실기에서 **사용자가 먼저 알아챘다** — *"웨이크워드로 깼을 때 계속 노래를
입력으로 받으니까 입력 최대 시간 30초 동안 계속 노래를 들으려고 함."*
로그를 보니 WAKE 16:24:30 → STT 16:25:01 로 **상한까지 간 뒤**에야 끝났고,
노래를 받아적은 *'보수 수술을 사'* 가 명령으로 들어갔다.

🔑 **원인은 임계값이 아니라 자동 볼륨 조절(AGC)이었다.** AGC 가 하는 일이 정확히
  «레벨 차이를 없애는 것»인데, 발화 종료 감지는 **그 레벨 차이로 판정한다.**
  말을 멈추면 AGC 가 배경 음악을 끌어올려서 «아직 소리가 난다»로 만든다.

  가공 안 된 소리에서는 대비가 12배다(같은 날 소크 실측):
      음악    중앙 RMS 0.0026 · 종료임계(0.012) 위 비율 **0.0%**
      목소리  최대 RMS 0.032 ~ 0.073

  즉 **지금의 0.012 는 원래 잘 맞는 값**이고, 그 사이를 AGC 가 메웠다.

🚨 처음엔 «종료 임계를 바닥에 맞춰 올리자»와 «상한을 12초로 줄이자»를 제안했는데
  **사용자가 반려했다** — *"본질적인 해결방안이 아닌 것 같아, 12초로 제한하는 건
  진짜 별로"*. 맞는 지적이었다. 앞엣것은 **같은 크기 비교**를 다른 숫자로 하는 것이고,
  뒤엣것은 고치는 게 아니라 **피해를 줄이면서 긴 명령을 자르는** 것이었다.

⚠️ 브라우저를 띄우지 않는다. 소스를 읽어 대조하고, 엔드포인트만 실제로 태운다.

실행: python tests/test_vad_agc.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = total = 0


def check(label, cond, detail=""):
    global passed, total
    total += 1
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ FAIL {label}" + (f"   → {detail}" if detail else ""))


def _src(*parts):
    # ⚠️ 절대규칙 7 — 한글이 든 소스는 utf-8 로 연다.
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


_UI = _src("electron-ui", "renderer", "index.html")
_MAIN = _src("main.py")


# ═══ ① AGC 를 끈다 ════════════════════════════════════════════════
print("=== ① 자동 볼륨 조절(AGC)을 끈다 ===")
check("`getUserMedia` 가 `autoGainControl: false` 를 요청한다",
      "autoGainControl: false" in _UI)
check("🚨 `{ audio: true }` 로 되돌아가지 않았다",
      "getUserMedia({ audio: true })" not in _UI)
check("🔑 **잡음 제거·에코 제거는 건드리지 않는다** — 레벨 대비를 지우지 않으므로",
      "noiseSuppression: false" not in _UI and "echoCancellation: false" not in _UI)
check("왜 끄는지가 **숫자로** 적혀 있다",
      "0.0026" in _UI and "0.012" in _UI)
check("🚨 대가도 적혀 있다 (멀리서 작게 말하면 더 작게 들어온다)",
      "멀리서 작게 말하면" in _UI)


# ═══ ② 추정하지 않고 **확인**한다 ═════════════════════════════════
#
# 🔑 브라우저가 요청을 무시할 수도 있다. 그러면 위 판단의 전제가 무너지는데,
#   기록이 없으면 그걸 영영 모른다.
print("\n=== ② 마이크 설정을 기록한다 ===")
check("실제 트랙 설정을 읽는다", "getSettings" in _UI)
check("세 가지를 다 담는다",
      all(k in _UI for k in ("autoGainControl", "noiseSuppression", "echoCancellation")))
check("🚨 읽기에 실패해도 녹음이 안 깨진다 (try/catch)",
      "catch (e) { micSettings = {}; }" in _UI)


# ═══ ③ VAD 결과가 **서버 로그**로 간다 ════════════════════════════
#
# 🚨 지금까지 `[VAD]` 줄이 브라우저 콘솔에만 찍혔다. 그래서 사용자가 증상을 먼저
#   알아챘는데도 `logs/pluiz.log` 에는 한 줄도 없어서 왜인지 못 봤다.
#   2026-09-24 에 음성 인식 폴백 사유를 콘솔에서 로그로 옮긴 것과 같은 이유다.
print("\n=== ③ 녹음 한 판의 결말이 서버 로그에 남는다 ===")
check("렌더러가 `/api/vad-report` 로 보낸다", "/api/vad-report" in _UI)
check("종료될 때마다 보낸다 (endVad 안에서)", "reportVad(reason)" in _UI)
check("🚨 **기록 때문에 녹음이 깨지지 않는다** (catch 로 삼킨다)",
      "}).catch(() => {});" in _UI)
check("보내는 것에 **왜인지 알 만한 값**이 다 있다",
      all(k in _UI for k in ("reason", "floor", "start_rms", "peak", "auto")))

check("서버에 엔드포인트가 있다", '@app.post("/api/vad-report")' in _MAIN)
check("🚨 **아무것도 바꾸지 않는다** — 기록 전용이라고 적혀 있다",
      "아무것도 바꾸지 않는다" in _MAIN)
check("로그에 사유·길이·바닥·시작임계·최대가 다 나온다",
      "사유=%s" in _MAIN and "바닥 %.4f" in _MAIN and "시작임계" in _MAIN)
check("🔑 마이크 설정도 같이 찍는다 (AGC 가 정말 꺼졌는지)",
      "autoGainControl" in _MAIN)


# ═══ ④ 실제로 도는가 ══════════════════════════════════════════════
print("\n=== ④ 엔드포인트를 실제로 태운다 ===")
try:
    from fastapi.testclient import TestClient
    import main as _m
    import core.auth as _auth

    with TestClient(_m.app, base_url="http://127.0.0.1:8765") as c:
        H = {_auth.HEADER_NAME: _m._AUTH_TOKEN}
        r = c.post("/api/vad-report", headers=H, json={
            "reason": "max", "ms": 30000, "floor": 0.0182, "start_rms": 0.0546,
            "peak": 0.0611, "auto": True,
            "mic": {"autoGainControl": False, "noiseSuppression": True}})
        check("정상 보고가 200 이다", r.status_code == 200, f"→ {r.status_code} {r.text[:80]}")

        r2 = c.post("/api/vad-report", headers=H, json={"reason": "nospeech"})
        check("🔑 **값이 빠져도 안 터진다** — 기록이 녹음을 깨면 안 된다",
              r2.status_code == 200, f"→ {r2.status_code}")

        r3 = c.post("/api/vad-report", json={"reason": "max"})
        check("🔒 토큰 없이는 막힌다 (다른 엔드포인트와 같다)",
              r3.status_code == 401, f"→ {r3.status_code}")
except Exception as e:                                        # noqa: BLE001
    check("엔드포인트를 태운다", False, f"{type(e).__name__}: {e}")


# ═══ ⑤ 반려된 안으로 되돌아가지 않았다 ════════════════════════════
print("\n=== ⑤ 사용자가 반려한 안으로 안 갔다 ===")
_vad = _UI[_UI.find("const VAD = {"):_UI.find("const CIRCUM")]
check("🚨 상한(MAX_MS)이 **30초 그대로다** — 12초로 줄이지 않았다",
      "MAX_MS: 30000" in _vad, "긴 명령을 자르는 쪽이라 사용자가 반려했다")
check("🔒 히스테리시스가 그대로다 (START_RMS > KEEP_RMS)",
      "START_RMS: 0.020" in _vad and "KEEP_RMS: 0.012" in _vad)
check("🔑 상한을 지우지도 않았다 — 끝나지 않는 녹음의 마지막 방어선이다",
      "MAX_MS" in _vad)


print(f"\n결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
