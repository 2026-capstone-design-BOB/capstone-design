# app/executor/interpreter_exec.py
import time
import os
import re
import subprocess
import psutil
from app.agents.supervisor_agent import SupervisorAgent
from app.executor.offline_executor import OfflineExecutor
from app.cache.command_cache import CommandCache
from app.security.ast_guard import check_code


# ── 프로세스 이름 매핑 ────────────────────────────────────────────
APP_PROCESS_MAP = {
    "notepad":    ["notepad.exe"],
    "calculator": ["calculatorapp.exe"],
    "chrome":     ["chrome.exe"],
    "edge":       ["msedge.exe"],
    "explorer":   ["explorer.exe"],
    "firefox":    ["firefox.exe"],
    "word":       ["winword.exe"],
    "excel":      ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "vscode":     ["code.exe"],
    "kakaotalk":  ["kakaotalk.exe"],
    "terminal":   ["wt.exe", "cmd.exe", "powershell.exe"],
}

# fallback 경로 (where 실패 시 직접 확인)
APP_FALLBACK_PATHS = {
    "chrome": [
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                     "Google/Chrome/Application/chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                     "Google/Chrome/Application/chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Google/Chrome/Application/chrome.exe"),
    ],
    "edge": [
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                     "Microsoft/Edge/Application/msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                     "Microsoft/Edge/Application/msedge.exe"),
    ],
    "firefox": [
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                     "Mozilla Firefox/firefox.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                     "Mozilla Firefox/firefox.exe"),
    ],
    "kakaotalk": [
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                     "Kakao/KakaoTalk/KakaoTalk.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Kakao/KakaoTalk/KakaoTalk.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                     "Kakao/KakaoTalk/KakaoTalk.exe"),
    ],
    "kakao": [
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                     "Kakao/KakaoTalk/KakaoTalk.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Kakao/KakaoTalk/KakaoTalk.exe"),
    ],
    "word": [
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                     "Microsoft Office/root/Office16/WINWORD.EXE"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                     "Microsoft Office/root/Office16/WINWORD.EXE"),
    ],
    "excel": [
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                     "Microsoft Office/root/Office16/EXCEL.EXE"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                     "Microsoft Office/root/Office16/EXCEL.EXE"),
    ],
    "powerpoint": [
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                     "Microsoft Office/root/Office16/POWERPNT.EXE"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                     "Microsoft Office/root/Office16/POWERPNT.EXE"),
    ],
    "vscode": [
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Programs/Microsoft VS Code/Code.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", "C:/Program Files"),
                     "Microsoft VS Code/Code.exe"),
    ],
}

MAX_ATTEMPTS = 3
_EXE_PATH_RE = re.compile(r'[A-Za-z]:[/\\][^\s"\']+\.exe', re.IGNORECASE)


# ── 앱 경로 탐색 ─────────────────────────────────────────────────

def _resolve_app_path(app_name: str, cache: CommandCache) -> str | None:
    """
    open_app 사전 검증용 경로 탐색.
    순서: DB → where → fallback → 레지스트리 → Program Files glob → None
    찾으면 DB에 저장 후 반환.
    """
    # 1. app_paths DB 조회
    path = cache.get_app_path(app_name)
    if path and os.path.exists(path):
        print(f"[AppResolver] DB 히트: {app_name} → {path}")
        return path

    # 2. where 명령으로 실시간 탐색
    exe_candidates = list({
        f"{app_name}.exe",
        APP_PROCESS_MAP.get(app_name.lower(), [f"{app_name}.exe"])[0],
    })
    for exe in exe_candidates:
        try:
            result = subprocess.run(
                ["where", exe], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                found = result.stdout.strip().splitlines()[0].replace("\\", "/")
                if os.path.exists(found):
                    print(f"[AppResolver] where 탐색 성공: {app_name} → {found}")
                    cache.save_app_path(app_name, found, verified=True)
                    return found
        except Exception:
            continue

    # 3. fallback 경로 직접 확인
    for fallback in APP_FALLBACK_PATHS.get(app_name.lower(), []):
        normalized = fallback.replace("\\", "/")
        if os.path.exists(normalized):
            print(f"[AppResolver] fallback 탐색 성공: {app_name} → {normalized}")
            cache.save_app_path(app_name, normalized, verified=True)
            return normalized

    # 4. 레지스트리 탐색
    try:
        import winreg
        reg_keys = [
            (winreg.HKEY_LOCAL_MACHINE,
             rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app_name}.exe"),
            (winreg.HKEY_CURRENT_USER,
             rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app_name}.exe"),
        ]
        for hkey, subkey in reg_keys:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    reg_path, _ = winreg.QueryValueEx(key, "")
                    reg_path = reg_path.replace("\\", "/")
                    if os.path.exists(reg_path):
                        print(f"[AppResolver] 레지스트리 탐색 성공: {app_name} → {reg_path}")
                        cache.save_app_path(app_name, reg_path, verified=True)
                        return reg_path
            except (FileNotFoundError, OSError):
                continue
    except ImportError:
        pass

    # 5. Program Files glob 탐색 (타임아웃 5초)
    import glob
    import concurrent.futures

    exe_name = f"{app_name}.exe"
    search_roots = [
        os.environ.get("PROGRAMFILES", "C:/Program Files"),
        os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("APPDATA", ""),
    ]

    def _glob_search():
        for root in search_roots:
            if not root or not os.path.exists(root):
                continue
            try:
                matches = glob.glob(
                    os.path.join(root, "**", exe_name),
                    recursive=True
                )
                if matches:
                    return matches[0].replace("\\", "/")
            except Exception:
                continue
        return None

    print(f"[AppResolver] glob 탐색 시작: {exe_name} (최대 5초)")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_glob_search)
            found = future.result(timeout=5)
            if found:
                print(f"[AppResolver] glob 탐색 성공: {app_name} → {found}")
                cache.save_app_path(app_name, found, verified=True)
                return found
    except concurrent.futures.TimeoutError:
        print(f"[AppResolver] glob 탐색 타임아웃: {app_name}")
    except Exception:
        pass

    print(f"[AppResolver] 찾기 실패: {app_name}")
    return None


def _extract_and_learn_path(app_name: str, code: str, cache: CommandCache):
    """성공한 코드에서 .exe 경로 추출 → app_paths 자동 학습."""
    for raw_path in _EXE_PATH_RE.findall(code):
        path = raw_path.replace("\\", "/")
        if os.path.exists(path):
            existing = cache.get_app_path(app_name)
            if not existing:
                cache.save_app_path(app_name, path, verified=True)
                print(f"[AppResolver] 경로 자동 학습: {app_name} → {path}")
            return


# ── 프로세스 확인 ─────────────────────────────────────────────────

def _is_process_running(app_name: str) -> bool:
    targets = APP_PROCESS_MAP.get(app_name.lower(), [f"{app_name}.exe"])
    running = {p.name().lower() for p in psutil.process_iter(["name"])}
    return any(t.lower() in running for t in targets)


# ── 실행 결과 검증 ────────────────────────────────────────────────

def _verify_result(command: dict, exec_result: dict) -> dict:
    if exec_result["status"] != "success":
        return {"verified": False, "reason": exec_result.get("message", "실행 오류")}

    action = command.get("action", "")
    params = command.get("params", {})

    if action == "open_app":
        app = params.get("app", "")
        time.sleep(0.5)
        if app and not _is_process_running(app):
            proc_names = APP_PROCESS_MAP.get(app.lower(), [f"{app}.exe"])
            return {
                "verified": False,
                "reason": (
                    f"'{app}' 프로세스({', '.join(proc_names)})가 "
                    f"실행 후 확인되지 않음. 경로가 틀렸거나 앱이 없을 수 있음."
                )
            }
        return {"verified": True, "reason": ""}

    if action == "close_app":
        app = params.get("app", "")
        time.sleep(0.3)
        if app and _is_process_running(app):
            return {"verified": False, "reason": f"앱 종료 확인 실패: {app}"}
        return {"verified": True, "reason": ""}

    if action in ("maximize_window", "minimize_window"):
        app = params.get("app", "")
        if app and not _is_process_running(app):
            return {
                "verified": False,
                "reason": f"창 제어 실패: '{app}'이 실행 중이지 않음"
            }
        # 실행 중인 경우 — 창 상태 확인은 복잡하므로 실행 중이면 통과
        return {"verified": True, "reason": ""}

    if action in ("create_file", "create_folder"):
        name = params.get("name", "")
        location = params.get("location", "")
        location_map = {
            "desktop":   os.path.join(os.path.expanduser("~"), "Desktop"),
            "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
            "documents": os.path.join(os.path.expanduser("~"), "Documents"),
        }
        base = location_map.get(location.lower(), os.path.expanduser("~"))
        full_path = os.path.join(base, name) if name else ""
        if full_path and not os.path.exists(full_path):
            return {"verified": False, "reason": f"생성 확인 실패: {full_path}"}
        return {"verified": True, "reason": ""}

    if action == "natural_language":
        stdout = exec_result.get("stdout", "")
        code   = exec_result.get("code", "")

        # ── Step 1. 실행 완료 stdout 확인 (소프트 검증) ──────────
        if "실행 완료" not in stdout:
            return {
                "verified": False,
                "reason": (
                    f"실행 완료 확인 불가 — stdout: {stdout.strip()[:80]!r}"
                    if stdout.strip()
                    else "실행 완료 확인 불가 — stdout 없음"
                )
            }

        # ── Step 2. 코드 분석 → 동작 유형 추론 → 하드 검증 ──────
        # 2-A. 앱 실행 감지: subprocess.Popen + .exe 경로 포함
        if "subprocess.Popen" in code and ".exe" in code.lower():
            exe_matches = _EXE_PATH_RE.findall(code)
            for raw_path in exe_matches:
                exe_name = os.path.basename(raw_path).lower()
                # APP_PROCESS_MAP 역방향으로 앱명 추론
                app_name = next(
                    (k for k, v in APP_PROCESS_MAP.items()
                     if any(exe_name == proc.lower() for proc in v)),
                    None
                )
                if app_name:
                    time.sleep(0.5)
                    if not _is_process_running(app_name):
                        proc_names = APP_PROCESS_MAP.get(app_name, [exe_name])
                        return {
                            "verified": False,
                            "reason": (
                                f"앱 실행 확인 실패: '{app_name}' 프로세스"
                                f"({', '.join(proc_names)})가 실행 후 감지되지 않음"
                            )
                        }
                    return {"verified": True, "reason": ""}

        # 2-B. 파일/폴더 생성 감지: open() 쓰기 모드 또는 os.makedirs/mkdir/Path.touch
        file_creation_patterns = (
            "open(", "Path(", "os.makedirs", "os.mkdir", ".touch(", ".write(",
        )
        if any(p in code for p in file_creation_patterns):
            # stdout에서 생성된 경로 추출 시도
            path_match = re.search(
                r'(?:생성|저장|만들|created)[^\n]*?([A-Za-z]:[/\\][^\s\'"]+)',
                stdout, re.IGNORECASE
            )
            if path_match:
                created_path = path_match.group(1).replace('\\', '/')
                if not os.path.exists(created_path):
                    return {
                        "verified": False,
                        "reason": f"파일/폴더 생성 확인 실패: {created_path}"
                    }
                return {"verified": True, "reason": ""}
            # 경로 추출 실패 — stdout 신뢰로 폴백
            return {"verified": True, "reason": ""}


        # 2-C. 그 외 (볼륨, 밝기, 스크린샷 등) — stdout 신뢰
        return {"verified": True, "reason": ""}

    return {"verified": True, "reason": ""}


# ── 메인 Executor ─────────────────────────────────────────────────

class InterpreterExecutor:
    def __init__(self):
        self.supervisor = SupervisorAgent()
        self.cache = CommandCache()
        self.offline = OfflineExecutor()
        # API 완전 불가 상태 추적 — True가 되면 이후 요청도 오프라인으로
        self._api_down = not self.supervisor.available
        print("[Executor] 초기화 완료")

    def run_from_cache(self, cached: dict, command: dict | None = None) -> dict:
        code = cached.get("code", "")
        start = time.time()
        result = self._execute_code(code)
        print(f"[시간] 캐시 코드 실행: {time.time()-start:.3f}초")

        if result["status"] == "blocked":
            return result

        if result["status"] in ("error", "syntax_error", "no_retry"):
            print(f"[run_from_cache] 실행 실패 — 캐시 무효화: {result.get('message')}")
            if command:
                self.cache.invalidate(command)
            return {"status": "error", "message": result.get("message", "실행 중 오류가 발생했습니다."), "from_cache": True}

        return {"status": "success", "message": "완료됐습니다.", "from_cache": True}

    def execute(self, command: dict, original_input: str = "") -> dict:
        start_total = time.time()
        try:
            action = command.get("action", "")
            params = command.get("params", {})
            resolved_path = None

            # ── 유형 A: open_app 사전 검증 ──────────────────────
            if action == "open_app":
                app = params.get("app", "")
                if app:
                    resolved_path = _resolve_app_path(app, self.cache)
                    if resolved_path is None:
                        print(f"[사전 검증 실패] '{app}' 앱을 찾을 수 없음 — LLM 호출 없이 종료")
                        return {
                            "status": "error",
                            "message": f"'{app}' 앱을 찾을 수 없습니다. 설치 여부를 확인하거나 정확한 앱 이름으로 다시 말씀해주세요.",
                            "from_cache": False,
                        }
                    original_input = f"{original_input} [실행 경로: {resolved_path}]"
                    print(f"[AppResolver] 경로 주입 완료: {resolved_path}")

            # ── 유형 B: open_url 사전 검증 ──────────────────────
            if action == "open_url":
                url = params.get("url", "")
                if url and not (url.startswith("http://") or url.startswith("https://")):
                    print(f"[사전 검증 실패] 잘못된 URL 형식: {url}")
                    return {
                        "status": "error",
                        "message": f"잘못된 URL 형식입니다: {url}",
                        "from_cache": False,
                    }

            # ── 유형 C: interpreter 사전 검증 ───────────────────
            if action in ("create_file", "create_folder", "find_file"):
                location = params.get("location", "")
                if location:
                    location_map = {
                        "desktop":   os.path.join(os.path.expanduser("~"), "Desktop"),
                        "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
                        "documents": os.path.join(os.path.expanduser("~"), "Documents"),
                    }
                    base = location_map.get(location.lower())
                    if base is None:
                        print(f"[사전 검증 실패] 지원하지 않는 경로: {location}")
                        return {
                            "status": "error",
                            "message": f"'{location}'은 지원하지 않는 경로입니다. desktop, downloads, documents 중 하나를 사용해주세요.",
                            "from_cache": False,
                        }
                    if not os.path.exists(base):
                        print(f"[사전 검증 실패] 경로 없음: {base}")
                        return {
                            "status": "error",
                            "message": f"'{location}' 폴더를 찾을 수 없습니다.",
                            "from_cache": False,
                        }

            # ── Step 1. 캐시 조회 ────────────────────────────────
            t = time.time()
            cached = self.cache.get(command)
            print(f"[시간] 캐시 조회: {time.time()-t:.3f}초")

            if cached:
                print(f"[Executor] 캐시 히트! 바로 실행: {self.cache._make_key(command)}")
                t = time.time()
                result = self._execute_code(cached["code"])
                print(f"[시간] 코드 실행: {time.time()-t:.3f}초")

                if result["status"] == "blocked":
                    return result

                # 되묻기 — 캐시 무효화 후 반환
                if result["status"] == "ask":
                    self.cache.invalidate(command)
                    return {"status": "ask", "message": result["message"], "from_cache": False}

                result["code"] = cached["code"]  # 하드 검증용 코드 주입
                verified = _verify_result(command, result)
                if not verified["verified"]:
                    print(f"[검증 실패] 캐시 코드 오작동 — 캐시 무효화 후 재생성: {verified['reason']}")
                    self.cache.invalidate(command)
                    # 캐시 무효화 후 Step 2로 fall-through — 재생성 시작
                    cache_miss_error_context = {
                        "type": "verification_failed",
                        "reason": verified["reason"],
                        "code": cached["code"],
                    }
                else:
                    print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 ✅ (캐시)")
                    return {"status": "success", "message": "완료됐습니다.", "from_cache": True}
            else:
                cache_miss_error_context = None

            # ── Step 2. 캐시 미스 → 코드 생성 + 에러 피드백 재시도 ──
            error_context = cache_miss_error_context

            # command에서 히스토리 추출 (_history는 라우팅에 영향 없는 메타 필드)
            history = command.pop("_history", None)

            # ── API 완전 불가 → 즉시 오프라인 폴백 ─────────────────
            if self._api_down:
                print("[Executor] API 불가 상태 → 오프라인 폴백 (Open Interpreter)")
                return self.offline.run(original_input)

            for attempt in range(MAX_ATTEMPTS):
                if attempt == 0:
                    label = "캐시 무효화 후 재생성 → " if cache_miss_error_context else "캐시 미스 → "
                else:
                    label = f"재시도 {attempt} → "
                print(f"[Executor] {label}Gemini 코드 생성 중...")
                t = time.time()
                try:
                    code = self.supervisor.generate_code(command, original_input, error_context, history)
                except Exception as api_err:
                    # API 완전 불가 오류 → 오프라인 전환 후 이후 요청도 오프라인
                    err_msg = str(api_err).lower()
                    is_permanent = any(t in err_msg for t in ("connection", "timeout", "unavailable", "overloaded", "api_key", "permission"))
                    if is_permanent:
                        print(f"[Executor] API 오류 감지 → 오프라인 전환: {type(api_err).__name__}")
                        self._api_down = True
                        return self.offline.run(original_input)
                    # 일시적 오류(429 등) → 재시도 계속
                    print(f"[Executor] 일시적 API 오류 (재시도 {attempt+1}/{MAX_ATTEMPTS}): {api_err}")
                    error_context = {"type": "error", "reason": str(api_err), "code": ""}
                    continue
                print(f"[시간] Gemini 코드 생성: {time.time()-t:.3f}초")

                if not code:
                    return {"status": "error", "message": "AI 서버가 혼잡합니다. 잠시 후 다시 시도해주세요."}

                print(f"[Gemini 생성 코드]\n{code}")
                t = time.time()
                result = self._execute_code(code)
                print(f"[시간] 코드 실행: {time.time()-t:.3f}초")

                if result["status"] == "blocked":
                    print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 (차단)")
                    return result

                # 되묻기 — 캐시 저장 없이 즉시 반환
                if result["status"] == "ask":
                    print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 (되묻기)")
                    return {"status": "ask", "message": result["message"], "from_cache": False}

                # 앱 미실행 등 재시도해도 의미 없는 케이스 — 즉시 에러 반환
                if result["status"] == "no_retry":
                    print(f"[Executor] 재시도 불필요 — 즉시 종료: {result['message']}")
                    return {"status": "error", "message": result["message"], "from_cache": False}

                if result["status"] in ("syntax_error", "error"):
                    error_context = {
                        "type": result["status"],
                        "reason": result.get("message", "실행 오류"),
                        "code": code,
                    }
                    print(f"[시도 {attempt+1}/{MAX_ATTEMPTS}] 실행 실패: {error_context['reason']}")
                    continue

                result["code"] = code  # 하드 검증용 코드 주입
                verified = _verify_result(command, result)
                if not verified["verified"]:
                    error_context = {
                        "type": "verification_failed",
                        "reason": verified["reason"],
                        "code": code,
                    }
                    print(f"[시도 {attempt+1}/{MAX_ATTEMPTS}] 검증 실패: {verified['reason']}")
                    continue

                # 검증 성공 → 경로 자동 학습 → 캐시 저장
                if action == "open_app":
                    _extract_and_learn_path(params.get("app", ""), code, self.cache)

                t = time.time()
                self.cache.save(command, code, original_input)
                print(f"[시간] 캐시 저장: {time.time()-t:.3f}초")
                print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 (캐시 미스, {attempt+1}회 시도)")
                msg = self.supervisor.explain_result(original_input, True)
                print(f"[결과] {msg}")
                return {"status": "success", "message": msg, "from_cache": False}

            # MAX_ATTEMPTS 모두 실패
            # API는 살아있으나 코드 생성 반복 실패 — 오프라인 폴백 안 함
            last_reason = error_context.get("reason", "알 수 없는 오류") if error_context else "알 수 없는 오류"
            print(f"[Executor] {MAX_ATTEMPTS}회 시도 모두 실패: {last_reason}")
            print(f"[시간] 총 소요: {time.time()-start_total:.3f}초 (최종 실패)")
            return {"status": "error", "message": f"명령 실행에 실패했습니다. 다시 시도해주세요.", "from_cache": False}

        except Exception as e:
            print(f"[Executor 오류] {e}")
            return {"status": "error", "message": str(e)}

    def _wrap_in_try_except(self, code: str) -> str:
        """
        try/except가 없는 코드를 자동으로 감싸서
        내부 실패가 조용히 묻히지 않도록 보장.
        """
        if "try:" in code and "except" in code:
            return code  # 이미 있으면 그대로
        indented = "\n".join("    " + line for line in code.splitlines())
        return (
            "try:\n"
            f"{indented}\n"
            "except Exception as e:\n"
            '    print(f"실행 실패: {e}")'
        )

    def _execute_code(self, code: str) -> dict:
        guard_result = check_code(code)
        if not guard_result["safe"]:
            if "문법 오류" in guard_result["message"] or "파싱 오류" in guard_result["message"]:
                return {"status": "syntax_error", "message": guard_result["message"]}
            return {"status": "blocked", "message": guard_result["message"]}

        # try/except 없는 코드 자동 래핑 — 내부 실패 감지 보장
        code = self._wrap_in_try_except(code)

        import io
        import sys
        stdout_capture = io.StringIO()
        try:
            # stdout 캡처 — except 블록의 print(f"실행 실패: {e}") 감지용
            sys.stdout = stdout_capture
            exec(code, {"__builtins__": __builtins__})
        except Exception as e:
            sys.stdout = sys.__stdout__
            captured = stdout_capture.getvalue()
            if captured.strip():
                print(captured.strip())
            print(f"[코드 실행 오류] {e}")
            return {"status": "error", "message": str(e)}
        finally:
            sys.stdout = sys.__stdout__

        captured = stdout_capture.getvalue()
        if captured.strip():
            print(captured.strip())  # 정상 출력도 터미널에 표시

        # "되묻기:" 패턴 감지 — 대상 불명 명령, 캐시 저장 안 함
        if "되묻기:" in captured:
            # "되묻기:" 이후 전체 문자열 보존 — 태그([최대화] 등) 포함
            question = captured.strip().split("되묻기:", 1)[-1].strip()
            full_msg = "되묻기:" + question  # TAG_PATTERN 매칭용으로 prefix 유지
            print(f"[되묻기] {question}")
            return {"status": "ask", "message": full_msg}

        # "실행 실패:" 패턴 감지 — try/except 내부에서 조용히 실패한 케이스
        if "실행 실패:" in captured:
            reason = captured.strip().split("실행 실패:", 1)[1].strip()
            print(f"[코드 실행 오류] 내부 실패 감지: {reason}")
            # 앱 미실행 케이스 — 코드 오류 아님, 재시도 불필요
            no_retry = ("프로세스가 실행 중이지 않습니다", "창을 찾을 수 없습니다")
            if any(k in reason for k in no_retry):
                return {"status": "no_retry", "message": reason}
            return {"status": "error", "message": f"실행 실패: {reason}"}

        return {"status": "success", "stdout": captured}