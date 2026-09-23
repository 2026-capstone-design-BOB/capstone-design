# -*- coding: utf-8 -*-
"""망이 지금 살아 있는가 — **추측이 아니라 한 번 찔러 본다**

`core/graph_agent.py` 안에 있던 것을 2026-09-18에 여기로 옮겼다.

## 왜 옮겼나

[BL-58](../docs/BACKLOG.md) 을 고치려면 **`tools/web.py` 도 이 판정을 봐야 한다** —
오프라인에서 브라우저를 띄워 놓고 *«✓ 검색했어요»* 라고 말하던 결함이다.
그런데 `tools/` 가 `core/graph_agent.py` 를 부르면 **import 고리가 생긴다**
(graph_agent → tool_registry → tools). 그래서 **아무것도 import 하지 않는 자리**로
내렸다. 여기는 표준 라이브러리만 쓴다.

⚠️ `graph_agent` 는 예전 이름(`_offline_now` 등)을 **그대로 다시 내보낸다** —
   테스트가 `ga._offline_now` 를 갈아끼우고 있고, 그 방식이 계속 통해야 한다.
"""
import socket
import time

#: `looks_offline()` 결과를 이 초만큼 재사용한다. (ts, offline)
#  매 턴 소켓을 여는 것을 막으려는 것이고, 10초면 «방금 Wi-Fi를 켰다»도 곧 반영된다.
_OFFLINE_TTL = 10.0
_offline_probe: tuple[float, bool] = (0.0, False)


def looks_offline(timeout: float = 1.5) -> bool:
    """지금 인터넷이 끊겨 있나. **추측이 아니라 한 번 찔러 본다.**

    🚨 **왜 필요한가 (2026-09-11 실기).** 오프라인에서 LLM을 부르면 SDK가 내부
    재시도를 돌다가 **네트워크 오류를 던지기 전에 `agent_timeout`(45초)이 먼저**
    터졌다. 그래서 `_is_network_error()` 분기가 한 번도 타지 않고, 사용자는
    *"처리가 너무 오래 걸려서 중단했어요"* 를 받았다 — **끊긴 걸 알려주지도,
    캐시 제안을 내지도 못했다.** 실기에서 오프라인 턴 6개가 전부 이렇게 죽었다.

    ⚠️ **실패는 «온라인»으로 읽는다.** 판정 실패로 «오프라인 문구»를 내보내면
      **멀쩡한 네트워크에 거짓말을 하는 셈**이라 더 나쁘다.

    🚨 **이 탐침은 `8.8.8.8:53`·`1.1.1.1:53` 에 TCP로 붙는다.** 학교·전시장 망이
      53을 막으면 **인터넷이 되는데도 «오프라인»으로 읽는다.** 그 위험은
      [TASKS](../docs/TASKS.md) D-1 점검에 항목으로 들어 있다 —
      BL-58 수정으로 **그 오탐의 피해 범위가 웹 도구까지 넓어졌다.**
    """
    for host, port in (("8.8.8.8", 53), ("1.1.1.1", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return False                      # 한 곳이라도 닿으면 온라인
        except Exception:
            continue
    return True


def offline_now(ttl: float = _OFFLINE_TTL) -> bool:
    """지금 오프라인인가 — **TTL 캐시를 쓴다.** 턴 시작마다 불러도 싸다.

    🚨 **왜 이게 필요한가 (2026-09-11 2차 실기).** 오프라인 판정을 «타임아웃이 난 뒤»에만
    했더니 **응답이 여전히 45초**였다. 사용자 지적: *"오프라인 응답시간 너무 길다."*
    맞는 지적이다 — 문구만 고쳤고 **기다리는 시간은 그대로**였다.

    그래서 **턴이 시작될 때** 한 번 보고, 오프라인이면 LLM 타임아웃을 짧게 잡는다.
    캐시 실행은 그 안에 넉넉히 들어가고, LLM이 필요한 턴은 **45초가 아니라 8초에**
    정직한 답으로 끝난다.
    """
    global _offline_probe
    ts, val = _offline_probe
    now = time.monotonic()
    if now - ts < ttl:
        return val
    val = looks_offline(timeout=0.8)
    _offline_probe = (now, val)
    return val


def offline_confirmed() -> bool:
    """**두 번 본다** — 캐시된 판정 하나로 사람에게 «안 된다»고 말하지 않는다.

    `graph_agent` 가 단락 직전에 쓰던 방식과 **같은 것**이다(거기서 가져왔다).
    첫 번째는 TTL 캐시, 두 번째는 **새로 찌른다**. 둘 다 오프라인일 때만 참이다.

    🔑 BL-58 수정이 이걸 쓴다. 웹 도구를 막는 판단은 **되돌릴 수 없는 거절**이라
    («못 해요»라고 말해 버리면 사용자는 다시 말해야 한다) 한 번 더 본다.
    """
    return offline_now() and offline_now(ttl=0.0)


def reset_offline_probe():
    """테스트용 — TTL 캐시를 비운다."""
    global _offline_probe
    _offline_probe = (0.0, False)
