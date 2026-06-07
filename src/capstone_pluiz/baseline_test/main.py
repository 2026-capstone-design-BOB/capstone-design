# baseline_test/main.py
# 순수 Gemini API 성능 확인용
# 분류 → 코드 생성 → 안전장치 → 실행

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agent    import BaselineAgent
from executor import BaselineExecutor

def main():
    agent    = BaselineAgent()
    executor = BaselineExecutor()

    if not agent.available or not executor.available:
        print("API 키 확인 필요 (.env에 GEMINI_API_KEY 설정)")
        return

    print("=" * 50)
    print("Pluiz V2 - Baseline 실행 테스트")
    print("순수 Gemini API | 프롬프트 최적화 없음")
    print("캐싱 없음 | AST 보안 없음")
    print("(블랙리스트 + 실행 전 확인은 적용)")
    print("quit: 종료")
    print("=" * 50)

    while True:
        user_input = input("\n명령어: ").strip()

        if user_input.lower() == "quit":
            break
        if not user_input:
            continue

        # Step 1. 분류
        print("\n[명령 분류 중...]")
        command = agent.analyze_command(user_input)
        print(f"분류 결과: {command}")

        cmd_type = command.get("type", "unknown")

        # unknown이면 실행 불가
        if cmd_type == "unknown":
            print("→ 명령을 이해하지 못했어요. 다시 입력해주세요.")
            continue

        # Step 2. 코드 생성 → 안전장치 → 실행
        result = executor.run(user_input)

        # Step 3. 결과 출력
        status = result["status"]
        if status == "success":
            print("✅ 실행 완료")
        elif status == "blocked":
            print(f"⛔ 자동 차단됨: {result['output']}")
        elif status == "rejected":
            print("↩️  실행 취소됨")
        elif status == "error":
            print(f"❌ 오류: {result['output']}")

        print("-" * 50)

if __name__ == "__main__":
    main()
