# app/main.py
import os
from dotenv import load_dotenv
load_dotenv()

import sys
import subprocess
import time
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.router.command_router import CommandRouter
from app.services.stt import STTService
from app.memory.context_memory import ContextMemory
from app.executor.async_executor import AsyncExecutor
from app.executor.multistep_executor import MultistepExecutor
from app.cache.command_cache import CommandCache
from app.cache.multistep_cache import MultiStepCache

CANCEL_KEYWORDS = {
    "취소", "취소해", "취소해줘", "취소해주세요",
    "중단", "중단해", "중단해줘", "중단해주세요",
    "스톱", "stop", "멈춰", "멈춰줘", "그만", "그만해", "그만해줘",
    "취소할게", "그냥 취소", "그냥 취소해줘", "됐어", "됐습니다",
}

# 순수 반복 지시어 — Gemini 호출 없이 직전 명령 재실행
REPEAT_KEYWORDS = {
    "다시 해줘", "또 해줘", "한 번 더", "다시해줘", "또해줘", "한번더",
    "다시", "또",
}
CANCEL_PARTIAL = ("취소", "중단", "멈춰", "그만해", "스톱")

HISTORY_QUERY_KEYWORDS = (
    "아까 뭐 했어", "방금 뭐 했어", "이전 명령", "직전 명령",
    "최근에 뭐 했어", "지금 뭐 했어",
)

APP_KEYWORDS = {
    "크롬", "chrome", "엣지", "edge", "메모장", "notepad",
    "계산기", "calculator", "탐색기", "explorer", "파일탐색기",
    "카카오톡", "카톡", "kakao", "워드", "word", "엑셀", "excel",
    "파워포인트", "powerpoint", "ppt", "vscode", "파이어폭스", "firefox",
    "터미널", "terminal",
}

TAG_PATTERN = re.compile(r'되묻기:\[(.+?)\]\s*(.*)', re.DOTALL)


def _is_cancel(user_input: str) -> bool:
    stripped = user_input.strip()
    return stripped in CANCEL_KEYWORDS or any(k in stripped for k in CANCEL_PARTIAL)


def _is_history_query(user_input: str) -> bool:
    return any(k in user_input for k in HISTORY_QUERY_KEYWORDS)


def _parse_ask_tag(msg: str):
    m = TAG_PATTERN.match(msg)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, msg


def _make_command(user_input: str, history: list) -> dict:
    return {
        "type":     "interpreter",
        "action":   "natural_language",
        "params":   {"input": user_input},
        "_history": history,
    }


def _execute(user_input: str, async_executor, memory) -> dict:
    """모든 명령을 동기 실행."""
    history = memory.get_recent()
    command = _make_command(user_input, history)
    result = async_executor.submit_sync(user_input, command)
    return result, command


def main():
    router             = CommandRouter()
    stt                = STTService(mode="google")
    memory             = ContextMemory()
    cache              = CommandCache()
    multistep_cache    = MultiStepCache()
    async_executor     = AsyncExecutor(router, memory)
    multistep_executor = MultistepExecutor(async_executor, cache, multistep_cache)

    print("Pluiz V2 시작")
    print("1: 음성 입력 | 2: 텍스트 입력 | quit: 종료")
    print("-" * 40)

    pending_ask  = None
    # 직전 실행 추적 — 반복 지시어 재실행용
    last_single    = None  # {input, command, result}
    last_multistep = None  # {input, steps}

    while True:
        mode = input("입력 방식 선택 (1/2/quit): ").strip()

        if mode == "quit":
            break
        elif mode == "1":
            user_input = stt.listen_and_transcribe()
            if not user_input:
                continue
        elif mode == "2":
            user_input = input("명령어: ").strip()
            if not user_input:
                continue
        else:
            continue

        print(f"입력: {user_input}")
        start = time.time()

        # ── Step 0. 되묻기 대기 중 처리 ───────────────────────────
        if pending_ask:
            if _is_cancel(user_input):
                pending_ask = None
                print("되묻기 취소")
                print("-" * 40)
                continue

            stripped = user_input.strip().lower()
            if not any(k in stripped for k in APP_KEYWORDS):
                action_word = pending_ask["action"]
                print(f"❓ 앱 이름을 말씀해주세요. 어떤 앱을 {action_word}할까요? (예: 크롬, 메모장, 엣지)")
                print("-" * 40)
                continue

            action_word = pending_ask["action"]
            composed = f"{user_input} {action_word}"
            print(f"[되묻기 응답] 재구성된 명령: {composed}")

            result, command = _execute(composed, async_executor, memory)
            print(f"[시간] 총 소요: {time.time()-start:.3f}초")

            no_retry_hints = ("프로세스가 실행 중이지 않습니다", "창을 찾을 수 없습니다")
            if result.get("status") == "error" and any(h in result.get("message", "") for h in no_retry_hints):
                print(f"❓ {action_word}할 앱이 실행 중이지 않습니다. 다른 앱을 말씀해주세요. (예: 크롬, 메모장, 엣지)")
            else:
                print(f"실행 결과: {result}")
                pending_ask = None
                if result.get("status") != "ask":
                    memory.save(composed, command, result)

            print("-" * 40)
            continue

        # ── Step 1. 취소 ───────────────────────────────────────────
        if _is_cancel(user_input):
            async_executor.cancel_all()
            last_single    = None  # 케이스 1: 취소 시 직전 명령 초기화
            last_multistep = None
            print("실행 중단됨")
            print("-" * 40)
            continue

        # ── Step 2. 히스토리 조회 ──────────────────────────────────
        if _is_history_query(user_input):
            last = memory.get_last_input()
            msg = f"마지막 명령: {last}" if last else "이전 명령이 없습니다."
            print(f"[히스토리] {msg}")
            memory.save(user_input, {"type": "system", "action": "history_response", "params": {}}, {"status": "success"})
            print("-" * 40)
            continue

        # ── Step 3. 반복 지시어 — Gemini 없이 직전 명령 재실행 ──────
        if user_input.strip() in REPEAT_KEYWORDS:
            # 케이스 4: history_response는 재실행 제외
            skip_actions = {"history_response"}
            last_cmd = memory.get_last_command()
            if last_cmd and last_cmd.get("action") in skip_actions:
                last_single = None

            if last_multistep:
                # 케이스 3: 직전이 멀티스텝 → 전체 재실행
                print(f"[반복] 직전 멀티스텝 재실행: {last_multistep['input']}")
                steps = last_multistep["steps"]
                collected = []
                done_event = __import__('threading').Event()
                def _on_repeat_done(r):
                    collected.append(r)
                    if len(collected) == len(steps):
                        done_event.set()
                multistep_executor.execute(last_multistep["input"], steps, callback=_on_repeat_done)
                done_event.wait(timeout=30)
                print(f"[시간] 총 소요: {time.time()-start:.3f}초")
                success_count = sum(1 for r in collected if r.get('status') == 'success')
                print(f"[멀티스텝 반복 결과] {success_count}/{len(steps)} 성공")
                # 케이스 5: 반복 명령 자체는 저장 안 함
            elif last_single:
                # 케이스 2: 직전 단일 명령 실패 시 안내
                if last_single["result"].get("status") != "success":
                    print(f"이전 명령이 실패했습니다: {last_single['result'].get('message', '')}")
                    print(f"다시 시도하려면 명령을 다시 말씀해주세요.")
                else:
                    print(f"[반복] 직전 단일 명령 재실행: {last_single['input']}")
                    result, command = _execute(last_single["input"], async_executor, memory)
                    print(f"[시간] 총 소요: {time.time()-start:.3f}초")
                    print(f"실행 결과: {result}")
                    # 케이스 5: 반복 명령 자체는 저장 안 함
            else:
                print("이전 명령이 없습니다. 실행할 명령을 먼저 말씀해주세요.")
            print("-" * 40)
            continue

        # ── Step 4. 일반 명령 — 멀티스텝 or 단일 실행 ──────────────
        MULTISTEP_HINTS = ("열고", "하고 나서", "그리고 나서", "다음에", "그 다음",
                           "이랑", "랑", "도", "하고", "같이", "함께")
        is_multistep_hint = any(h in user_input for h in MULTISTEP_HINTS)

        if is_multistep_hint:
            print("[멀티스텝 힌트 감지] → 스텝 분리 시도")
            steps = router.interpreter.supervisor.classify_steps(user_input)
        else:
            steps = None

        if steps:
            print(f"[멀티스텝] {len(steps)}개 스텝으로 분리 → MultistepExecutor")
            collected = []
            done_event = __import__('threading').Event()

            def _on_step_done(result):
                collected.append(result)
                if len(collected) == len(steps):
                    done_event.set()

            multistep_executor.execute(user_input, steps, callback=_on_step_done)
            done_event.wait(timeout=30)
            print(f"[시간] 총 소요: {time.time()-start:.3f}초")
            success_count = sum(1 for r in collected if r.get('status') == 'success')
            print(f"[멀티스텝 결과] {success_count}/{len(steps)} 성공")
            for i, r in enumerate(collected):
                print(f"  스텝 {i+1}: {r.get('status')} — {r.get('message', '')}")
            # 멀티스텝 직전 실행 추적
            last_multistep = {"input": user_input, "steps": steps}
            last_single    = None

        else:
            if is_multistep_hint:
                print("[멀티스텝] 분리 불가 → 단일 명령으로 처리")
            result, command = _execute(user_input, async_executor, memory)
            print(f"[시간] 총 소요: {time.time()-start:.3f}초")

            if result.get("status") == "ask":
                msg = result["message"]
                action_word, clean_msg = _parse_ask_tag(msg)
                if action_word:
                    pending_ask = {"action": action_word}
                    print(f"❓ {clean_msg}")
                else:
                    print(f"❓ {msg}")
            else:
                print(f"실행 결과: {result}")
                memory.save(user_input, command, result)
                # 단일 명령 직전 실행 추적
                last_single    = {"input": user_input, "command": command, "result": result}
                last_multistep = None

        print("-" * 40)


if __name__ == "__main__":
    main()