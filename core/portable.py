# -*- coding: utf-8 -*-
"""내보내기 / 가져오기 — 캐시와 즐겨찾기를 zip 하나로 옮긴다.

→ ADR: `docs/design/M6_내보내기_가져오기.md`

**왜 있나.** 2026-09-08에 클라우드 동기화를 «안 함»으로 확정했다. 그러면
*"PC를 바꾸면 학습한 게 다 날아가나요?"* 에 답할 수 없는데, 파일 하나로 옮길 수
있으면 답이 된다 — *"설계상 로컬 우선이고, 이동은 파일로 합니다."*

## 🚨 이 파일에서 제일 중요한 줄 — **가져오기는 학습의 다른 입구다**

2026-09-10에 BL-27을 고쳤다. 승인 응답 `'그래'`가 `close_app`으로 학습돼 있었고
`is_learnable_utterance()`로 막았다. **그 필터는 `learn()` 경로에만 있다.**

가져오기가 캐시 파일을 그대로 받으면 **다른 PC에서 오염된 엔트리가 필터를 우회한다.**
그 PC가 BL-27 이전 버전이었다면 `'그래' → close_app`이 그대로 오고,
**오늘 고친 것이 파일 하나로 되돌려진다.**

그래서 `import_bundle()`은 들어오는 엔트리를 **`learn()`과 똑같은 게이트**에
통과시킨다. 버린 것은 조용히 버리지 않고 **몇 개를 왜 버렸는지 보고한다.**

## `.env`는 «빼는» 게 아니라 «넣을 수 없다»

블록리스트로 거르면 다음에 민감한 파일이 생겼을 때 조용히 새어 나간다.
그래서 `_EXPORTABLE`에 **적힌 것만** 담긴다 — 새 파일은 적어야 담긴다.
(BL-29에서 «보장하는 건 구조다»라고 한 것과 같은 모양)
"""

from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from datetime import datetime
from typing import Any, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 번들 형식 버전. 구조가 바뀌면 올린다 — 못 읽으면 **거절하되 왜인지 말한다.**
BUNDLE_VERSION = 1

MANIFEST_NAME = "manifest.json"

#: 🔒 **allowlist.** 여기 적힌 것만 담긴다.
#:   (이름, 저장소 안 경로, 기본으로 담는가)
#:   ⚠️ `.env`·`logs/`·토큰 파일은 **목록에 없어서** 담기지 않는다. 거르는 게 아니다.
_EXPORTABLE: tuple[tuple[str, str, bool], ...] = (
    ("command_cache", os.path.join("cache", "command_cache.json"), True),
    ("favorites", os.path.join("cache", "favorites.json"), True),
    # 히스토리는 «사용자가 실제로 한 말»이라 성격이 다르다 → 기본 제외 (ADR §2-1)
    ("history", os.path.join("memory", "session.db"), False),
)

# ⚠️ **경로를 하드코딩하지 말 것.** 처음엔 `_ROOT` 기준으로 박아 뒀는데,
#    그러면 `PLUIZ_CACHE_FILE`(테스트가 쓰는 것)을 무시해서 **테스트가 사용자의
#    실제 캐시와 즐겨찾기를 고쳤다.** BL-11이 `_testenv`로 막아 둔 사고가
#    «새 모듈이 그 규약을 안 따라서» 되살아난 것이다. 반드시 이 함수를 거친다.


def cache_file() -> str:
    """캐시 파일 경로. `PLUIZ_CACHE_FILE`을 존중한다(command_cache와 같은 값)."""
    from core.command_cache import CACHE_FILE
    return CACHE_FILE


def favorites_file() -> str:
    return os.environ.get("PLUIZ_FAVORITES_FILE") or _abs(
        os.path.join("cache", "favorites.json"))


def history_file() -> str:
    return os.environ.get("PLUIZ_SESSION_DB") or _abs(
        os.path.join("memory", "session.db"))


def _path_for(name: str, rel: str) -> str:
    return {"command_cache": cache_file,
            "favorites": favorites_file,
            "history": history_file}.get(name, lambda: _abs(rel))()


class BundleError(Exception):
    """번들이 우리 것이 아니거나 읽을 수 없다. **아무것도 안 하고** 이걸 던진다."""


def _abs(rel: str) -> str:
    return os.path.join(_ROOT, rel)


# ── 내보내기 ─────────────────────────────────────────────────────

def _dynamic_entries(cache_path: str) -> dict[str, Any]:
    """동적 학습분만 골라낸다.

    시드(`is_seed=True`) 37개는 **코드가 제공한다.** 내보낸 시드를 다른 PC에 넣으면
    그 PC의 시드 버전과 충돌하고, 시드가 바뀌었을 때 **낡은 시드가 새 시드를 덮는다.**
    사용자의 «것»은 동적 학습분이다.
    """
    if not os.path.exists(cache_path):
        return {}
    with open(cache_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(v, dict) and not v.get("is_seed")
            and v.get("source", "dynamic") == "dynamic"}


def build_bundle(include_history: bool = False,
                 cache_path: Optional[str] = None) -> tuple[bytes, dict]:
    """번들 zip을 **메모리에서** 만든다. (바이트, 매니페스트)를 반환.

    파일로 떨구지 않는다 — 서버가 그대로 스트리밍하면 되고, 임시 파일이
    남지 않는다(`take_screenshot`이 임시파일을 안 남기는 것과 같은 이유).
    """
    cache_path = cache_path or cache_file()
    items: dict[str, int] = {}
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, rel, default_on in _EXPORTABLE:
            if name == "history" and not include_history:
                continue
            if name == "command_cache":
                entries = _dynamic_entries(cache_path)
                z.writestr("command_cache.json",
                           json.dumps(entries, ensure_ascii=False, indent=2))
                items["command_cache"] = len(entries)
                continue

            src = _path_for(name, rel)
            if not os.path.exists(src):
                continue
            arc = os.path.basename(rel)
            z.write(src, arc)
            if name == "favorites":
                try:
                    with open(src, encoding="utf-8") as f:
                        items["favorites"] = len(json.load(f) or [])
                except Exception:
                    items["favorites"] = 0
            else:
                items[name] = 1

        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "product": "pluiz",
            "created": datetime.now().isoformat(timespec="seconds"),
            "items": items,
            "includes_history": bool(include_history),
        }
        z.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))

    return buf.getvalue(), manifest


def suggested_filename(now: Optional[datetime] = None) -> str:
    return f"pluiz-export-{(now or datetime.now()).strftime('%Y%m%d-%H%M')}.zip"


# ── 가져오기 ─────────────────────────────────────────────────────

def read_manifest(data: bytes) -> dict:
    """매니페스트를 읽고 **우리 것인지** 확인한다.

    ⚠️ 아무 zip이나 받으면 사용자가 엉뚱한 파일을 넣었을 때 **조용히 이상해진다.**
      그래서 여기서 거절하고, **왜 거절했는지 말한다.**
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if MANIFEST_NAME not in z.namelist():
                raise BundleError(
                    "Pluiz 내보내기 파일이 아닙니다 (manifest.json이 없어요).")
            m = json.loads(z.read(MANIFEST_NAME).decode("utf-8"))
    except BundleError:
        raise
    except zipfile.BadZipFile:
        raise BundleError("zip 파일이 아니거나 깨져 있어요.")
    except Exception as e:
        raise BundleError(f"파일을 읽지 못했어요: {e}")

    if m.get("product") != "pluiz":
        raise BundleError("Pluiz 내보내기 파일이 아닙니다.")
    ver = m.get("bundle_version")
    if ver != BUNDLE_VERSION:
        # 반쯤 가져오는 것보다 거절이 낫다 (ADR §7)
        raise BundleError(
            f"이 파일은 형식 버전 {ver}인데 지금은 {BUNDLE_VERSION}만 읽을 수 있어요.")
    return m


def backup_file(path: str) -> Optional[str]:
    """되돌릴 수 없는 변경 앞에서 되돌릴 길을 만든다. 백업 경로를 반환.

    🚨 **같은 초에 두 번 부르면 첫 백업이 덮였다 (BL-49, 2026-09-12).**
      이름표가 `%Y%m%d-%H%M%S`로 **초 단위**라 두 번째 호출이 같은 경로를 만들고
      `shutil.copy2`가 조용히 덮어썼다. 실측:

          b1 = backup_file(p)   # {'첫번째': 1} 을 백업
          b2 = backup_file(p)   # {'두번째': 2} 를 백업
          b1 == b2              # True — 파일이 **하나**뿐이고 내용은 '두번째'

      **되돌릴 길을 만드는 함수가 되돌릴 길을 지우고 있었다.** 가져오기를
      연달아 두 번 하면(파일을 잘못 골라 바로 다시 하는 건 흔한 일이다)
      **원래 상태로 가는 유일한 사본이 사라진다.**

    🔑 **초를 더 잘게 쪼개는 대신 «있으면 비켜 간다».** 마이크로초를 붙이면
      이름이 읽기 어려워지고 **그래도 충돌 가능성은 0이 아니다** — 존재 확인이
      확실하고, 사람이 읽는 이름도 지킨다.
    """
    if not os.path.exists(path):
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root, ext = os.path.splitext(path)
    base = f"{root}.backup-{stamp}"
    dst, n = f"{base}{ext}", 2
    while os.path.exists(dst):
        dst = f"{base}-{n}{ext}"
        n += 1
    shutil.copy2(path, dst)
    return dst


def merge_cache_entries(current: dict, incoming: dict, cache,
                        mode: str = "merge") -> dict:
    """들어온 엔트리를 **게이트에 통과시켜** 병합한다.

    반환: {"added": n, "kept": n, "rejected": [(패턴, 사유), …], "replaced": n}

    🚨 **여기가 이 모듈의 존재 이유다.** `cache.is_learnable_utterance()`는
      `learn()`에만 걸려 있어서, 이 검사를 빼면 가져오기가 **BL-27 필터의 우회로**가
      된다. 오염된 캐시를 담은 zip 하나로 오늘 고친 게 되돌려진다.

    ⚠️ 시드는 **절대 덮지 않는다.** `mode="replace"` 여도 마찬가지다 —
      시드는 사용자의 것이 아니라 코드가 제공하는 것이다.
    """
    added = kept = replaced = 0
    rejected: list[tuple[str, str]] = []

    for pattern, entry in (incoming or {}).items():
        if not isinstance(entry, dict):
            rejected.append((str(pattern), "형식이 아님"))
            continue

        # ① 발화 게이트 (BL-27) — learn()이 쓰는 것과 **같은 함수**
        why = cache.is_learnable_utterance(pattern)
        if why:
            rejected.append((pattern, why))
            continue

        # ② 도구 게이트 — learn()이 쓰는 것과 같은 함수
        calls = entry.get("tool_calls") or []
        if not cache._is_learnable(calls):
            rejected.append((pattern, "학습 대상 도구가 아님"))
            continue

        # ③ 조회 게이트 (BL-60) — 역시 learn()이 쓰는 것과 **같은 함수**
        # 🚨 ①이 못 막는다. `is_learnable_utterance()` 는 **발화만** 보는데,
        #   «밝기 알려줘 → brightness_up» 이 나쁜 이유는 발화가 아니라 **짝**이다.
        #   이 줄이 없으면 가져오기가 BL-60 게이트의 우회로가 된다(①과 같은 논리).
        if cache.query_conflict(pattern, calls):
            rejected.append((pattern, "L5:묻는 말↛조작 도구"))
            continue

        key = cache._normalize(pattern)
        existing = current.get(pattern) or current.get(key)
        if existing:
            if existing.get("is_seed"):
                kept += 1                      # 시드는 절대 안 덮는다
                continue
            if mode == "replace":
                current[pattern] = entry
                replaced += 1
            else:
                kept += 1                      # 병합 기본 = **기존 우선**
            continue

        e = dict(entry)
        e["is_seed"] = False
        e["source"] = "dynamic"
        e["imported"] = True                   # 어디서 왔는지 남긴다
        current[pattern] = e
        added += 1

    return {"added": added, "kept": kept, "replaced": replaced, "rejected": rejected}


def import_bundle(data: bytes, cache, mode: str = "merge",
                  include_history: bool = False,
                  cache_path: Optional[str] = None) -> dict:
    """번들을 가져온다. **무엇을 몇 개 했는지** 돌려준다.

    절차 (ADR §5-2): 매니페스트 확인 → **백업** → 게이트 → 병합 → 보고.
    """
    manifest = read_manifest(data)           # 실패하면 여기서 끝. 아무것도 안 건드린다.
    cache_path = cache_path or cache_file()
    report: dict[str, Any] = {"manifest": manifest, "backups": []}

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())

        # ── 캐시 ────────────────────────────────────────────
        if "command_cache.json" in names:
            backup = backup_file(cache_path)
            if backup:
                report["backups"].append(os.path.basename(backup))

            current: dict = {}
            if os.path.exists(cache_path):
                with open(cache_path, encoding="utf-8") as f:
                    current = json.load(f) or {}

            incoming = json.loads(z.read("command_cache.json").decode("utf-8"))
            result = merge_cache_entries(current, incoming, cache, mode=mode)

            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            report["cache"] = result

        # ── 즐겨찾기 ────────────────────────────────────────
        if "favorites.json" in names:
            fav_path = favorites_file()
            backup = backup_file(fav_path)
            if backup:
                report["backups"].append(os.path.basename(backup))
            cur: list = []
            if os.path.exists(fav_path):
                try:
                    with open(fav_path, encoding="utf-8") as f:
                        cur = json.load(f) or []
                except Exception:
                    cur = []
            inc = json.loads(z.read("favorites.json").decode("utf-8")) or []
            # 같은 것을 두 번 넣지 않는다 (dict는 순서를 유지하니 원래 순서가 보존된다)
            seen = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in cur}
            n = 0
            for item in inc:
                k = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if k not in seen:
                    cur.append(item)
                    seen.add(k)
                    n += 1
            with open(fav_path, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
            report["favorites"] = {"added": n, "total": len(cur)}

        # ── 히스토리 ────────────────────────────────────────
        # ⚠️ SQLite라 **병합하지 않는다.** 켰을 때 파일을 통째로 바꾼다(ADR §7).
        #    대화 두 벌을 시간순으로 섞는 건 이 기능이 감당할 일이 아니다.
        if include_history and "session.db" in names:
            db_path = history_file()
            backup = backup_file(db_path)
            if backup:
                report["backups"].append(os.path.basename(backup))
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            with open(db_path, "wb") as f:
                f.write(z.read("session.db"))
            report["history"] = "replaced"

    return report


def describe_report(report: dict) -> str:
    """사람이 읽을 한 문단. **버린 게 있으면 반드시 말한다.**"""
    parts = []
    c = report.get("cache")
    if c:
        parts.append(f"명령 {c['added']}개를 새로 가져왔어요"
                     + (f" (이미 있던 {c['kept']}개는 그대로 뒀어요)" if c["kept"] else "")
                     + (f" · {c['replaced']}개는 덮어썼어요" if c["replaced"] else ""))
        if c["rejected"]:
            parts.append(f"⚠️ {len(c['rejected'])}개는 캐시에 넣을 수 없는 표현이라 "
                         f"거르고 넣지 않았어요")
    f = report.get("favorites")
    if f:
        parts.append(f"즐겨찾기 {f['added']}개를 더했어요")
    if report.get("history"):
        parts.append("대화 기록을 바꿨어요")
    if report.get("backups"):
        parts.append(f"바꾸기 전 상태는 {', '.join(report['backups'])}에 백업했어요")
    return ". ".join(parts) + "." if parts else "가져올 것이 없었어요."
