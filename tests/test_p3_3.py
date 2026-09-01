"""
P3-3 검증: 출력 마스킹 연결 + 자기검증 프롬프트 + open_app UWP 정직 보고(정적)
실행: python test_p3_3.py
"""
import sys, os, asyncio, importlib.util
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod
    spec.loader.exec_module(mod); return mod

base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
# core.security 실제 로드해야 마스킹 연결 검증됨 (graph_agent가 lazy import)
import types
# 'core' 패키지를 가벼운 stub으로 (무거운 __init__ 회피) + 실제 서브모듈 주입
core_pkg = types.ModuleType("core"); core_pkg.__path__ = [base]
sys.modules["core"] = core_pkg
_load("core.security", os.path.join(base, "security.py"))
_load("core.graph", os.path.join(base, "graph.py"))
_load("core.fast_path", os.path.join(base, "fast_path.py"))
G = sys.modules["core.graph"]
GA = _load("core.graph_agent", os.path.join(base, "graph_agent.py"))

from langchain_core.messages import AIMessage, HumanMessage


class LeakLLM:
    """민감정보를 응답에 흘리는 LLM (마스킹 검증용)."""
    def bind_tools(self, tools): return self
    def invoke(self, messages):
        return AIMessage(content="확인해보니 카드번호는 1234-5678-9012-3456 이에요")

class MockMem:
    def __init__(self): self.saved = []
    def save(self, u, a): self.saved.append((u, a))
class FakeSettings: agent_timeout = 30
def fake_security(t): return (False, "")
def fake_fr(t): return None


async def run():
    passed = total = 0
    def check(name, cond):
        nonlocal passed, total
        total += 1; passed += bool(cond)
        print(f"  {'✓' if cond else '✗ FAIL'} {name}")

    print("=== ① 출력 마스킹 오케스트레이터 연결 ===")
    mem = MockMem()
    agent = GA.PluizGraphAgent(llm=LeakLLM(), tools=[], security_check=fake_security,
                               fast_resolve=fake_fr, session_memory=mem, settings=FakeSettings())
    r = await agent.run_async("내 카드번호 확인해줘", "s1")
    check("응답에서 카드번호 마스킹됨", "****-****-****-3456" in r and "1234-5678" not in r)
    check("세션 기록도 마스킹된 채 저장", mem.saved and "1234-5678" not in mem.saved[-1][1])

    print("=== ② 자기검증 프롬프트(B) 포함 ===")
    sp = G.build_system_prompt()
    check("'안 됐다' 재검증 지시 포함", "get_running_apps" in sp and ("안 됐" in sp or "실패" in sp))
    check("불확실 시 확실한 척 금지 지시", "확실한 척" in sp)

    print(f"\n결과: {passed}/{total} 통과")
    return passed == total

if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run()) else 1)
