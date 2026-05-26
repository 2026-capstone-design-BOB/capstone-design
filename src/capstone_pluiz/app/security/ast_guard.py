# app/security/ast_guard.py
import ast
import re
import logging
import os
from datetime import datetime

# ──────────────────────────────────────────
# 로그 설정 (SEC-05)
# ──────────────────────────────────────────

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "security.log")

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)

def _log_block(violations: list, code: str):
    """차단 이벤트 로그 기록"""
    code_preview = code[:100].replace("\n", " ")
    for v in violations:
        logging.warning(f"BLOCKED - {v} | 코드: {code_preview}")

# ──────────────────────────────────────────
# 차단 패턴 정의
# ──────────────────────────────────────────

BLOCKED_MODULES = {
    "winreg", "ctypes", "socket", "ftplib", "telnetlib"
}

BLOCKED_FUNCTIONS = {
    "exec", "eval", "compile", "__import__"
}

BLOCKED_ATTRIBUTES = {
    "remove", "unlink", "rmdir", "rmtree",
    "system", "popen"
}

ALLOWED_SUBPROCESS = {
    "Popen", "run", "call", "check_output", "check_call"
}

BLOCKED_SUBPROCESS_COMMANDS = {
    "format", "rd /s", "del /f", "rmdir /s",
    "reg delete", "netsh", "bcdedit"
}

# ──────────────────────────────────────────
# AST 분석기
# ──────────────────────────────────────────

class SecurityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.violations = []

    def visit_Import(self, node):
        for alias in node.names:
            module = alias.name.split(".")[0]
            if module in BLOCKED_MODULES:
                self.violations.append(
                    f"위험 모듈 import 감지: {alias.name}"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            module = node.module.split(".")[0]
            if module in BLOCKED_MODULES:
                self.violations.append(
                    f"위험 모듈 import 감지: {node.module}"
                )
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in BLOCKED_FUNCTIONS:
                self.violations.append(
                    f"위험 함수 호출 감지: {node.func.id}()"
                )

        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr

            if isinstance(node.func.value, ast.Name):
                if node.func.value.id == "subprocess":
                    if attr not in ALLOWED_SUBPROCESS:
                        self.violations.append(
                            f"위험 subprocess 함수 감지: subprocess.{attr}()"
                        )
                    else:
                        self._check_subprocess_args(node)
                    self.generic_visit(node)
                    return

            if attr in BLOCKED_ATTRIBUTES:
                self.violations.append(
                    f"위험 메서드 호출 감지: .{attr}()"
                )

        self.generic_visit(node)

    def _check_subprocess_args(self, node):
        for arg in ast.walk(node):
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                lower = arg.value.lower()
                for cmd in BLOCKED_SUBPROCESS_COMMANDS:
                    if cmd in lower:
                        self.violations.append(
                            f"위험 시스템 명령어 감지: '{arg.value}'"
                        )

    def visit_Attribute(self, node):
        if isinstance(node, ast.Attribute):
            if node.attr in BLOCKED_ATTRIBUTES:
                if isinstance(node.value, ast.Name):
                    if node.value.id == "subprocess":
                        self.generic_visit(node)
                        return
                self.violations.append(
                    f"위험 속성 접근 감지: .{node.attr}"
                )
        self.generic_visit(node)


# ──────────────────────────────────────────
# 메인 검사 함수
# ──────────────────────────────────────────

def check_code(code: str) -> dict:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {
            "safe": False,
            "violations": [f"코드 파싱 오류: {e}"],
            "message": "코드 문법 오류로 실행할 수 없습니다."
        }

    visitor = SecurityVisitor()
    visitor.visit(tree)

    getattr_violations = _check_getattr_patterns(code)
    visitor.violations.extend(getattr_violations)

    if visitor.violations:
        violation_str = "\n".join(f"  - {v}" for v in visitor.violations)
        print(f"[AST Guard] 🚨 위험 코드 차단:\n{violation_str}")

        # SEC-05: 로그 기록
        _log_block(visitor.violations, code)

        return {
            "safe": False,
            "violations": visitor.violations,
            "message": f"보안상 실행할 수 없는 코드가 감지됐습니다.\n{violation_str}"
        }

    print(f"[AST Guard] ✅ 코드 안전 확인")
    return {
        "safe": True,
        "violations": [],
        "message": "안전한 코드입니다."
    }


def _check_getattr_patterns(code: str) -> list:
    violations = []
    dangerous_strings = [
        "remove", "unlink", "rmtree", "rmdir",
        "system", "format", "delete"
    ]
    getattr_pattern = re.compile(r'getattr\s*\(.*?,\s*["\'](\w+)["\']')
    for match in getattr_pattern.finditer(code):
        attr = match.group(1)
        if attr in dangerous_strings:
            violations.append(f"getattr 우회 패턴 감지: getattr(..., '{attr}')")
    return violations