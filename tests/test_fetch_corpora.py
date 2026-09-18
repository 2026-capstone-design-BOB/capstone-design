# -*- coding: utf-8 -*-
"""말뭉치 내려받기의 계약 — **21GB를 받다 조용히 틀리지 않게 한다.** (M7 2단계)

실행: python tests/test_fetch_corpora.py

## 왜 이 테스트가 있나

`scripts/fetch_wakeword_corpora.py`는 **한 번에 10GB짜리 파일을 받아 풀고 지운다.**
이 종류의 코드가 틀리는 방식은 오류가 아니라 **조용한 손실**이다:

1. **«검사할 것이 없다»를 «통과»라고 말한다** — [BL-59](../docs/BACKLOG.md)의 실패 모양.
   그래서 `--verify` 는 받아 둔 것이 하나도 없으면 **0이 아닌 값으로 죽는다.**
2. **푼 것을 확인하기 전에 압축파일을 지운다** — 그러면 10GB를 다시 받아야 한다.
   2026-09-18에 소크 원본 1.18GB를 지울 때 «파생이 멀쩡한 것을 확인한 뒤에» 지운 것과
   같은 순서를 여기서도 고정한다.
3. **압축 안에 `../` 가 들어 있으면 저장소 밖에 파일을 쓴다.** 남이 만든 21GB짜리
   아카이브를 푸는 코드다. 경로 탈출을 막는지 **검사로** 고정한다.
4. **디스크가 모자란 채로 시작한다** — 9GB를 받다 중간에 죽는 것 자체가 사고다.

⚠️ **이 테스트는 망을 쓰지 않는다.** mock 스위트가 인터넷에 의존하면 안 되기 때문이다.
   실제 주소가 살아 있는지는 사람이 `--list` → 내려받기로 확인한다.
"""
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import time
import types
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import _testenv  # noqa: F401,E402

import fetch_wakeword_corpora as F  # noqa: E402

NL = chr(10)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

passed = 0
total = 0


def check(label, cond):
    global passed, total
    total += 1
    ok = bool(cond)
    if ok:
        passed += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def _quiet(fn, *a, **kw):
    """출력을 삼키고 (반환값, 출력) 을 준다."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rv = fn(*a, **kw)
    finally:
        sys.stdout = old
    return rv, buf.getvalue()


def _tar_gz(path, members):
    """members: {아카이브 안 경로: 내용(bytes)}"""
    with tarfile.open(path, "w:gz") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


def _fake(tmp, key="fake", probe="fake_corpus/sub", archive="fake.tar.gz"):
    return F.Corpus(
        key=key, title="테스트용", url="https://example.invalid/fake.tar.gz",
        size=0, md5="0" * 32, archive=archive, probe=probe,
        extracted_hint=1, license_="테스트", why="테스트",
    )


def run():
    print("=== 1. 표 자체가 말이 되는가 (추측으로 적히지 않았나) ===")
    check("말뭉치가 셋이다 (MUSAN · RIR · Zeroth)",
          set(F.CORPORA) == {"musan", "rirs", "zeroth"})
    for c in F.CORPORA.values():
        check(f"[{c.key}] md5 가 32자리 16진수",
              len(c.md5) == 32 and all(ch in "0123456789abcdef" for ch in c.md5))
        check(f"[{c.key}] 크기가 1GB 이상 (Content-Length 실측값)", c.size > F.GB)
        check(f"[{c.key}] 주소가 https 이고 예비 주소가 있다",
              c.url.startswith("https://") and len(c.mirrors) >= 1)
        check(f"[{c.key}] 라이선스를 적어 뒀다 (발표에 출처를 써야 한다)",
              bool(c.license) and len(c.license) > 3)
        check(f"[{c.key}] 왜 받는지가 적혀 있다", len(c.why) > 20)

    print("=== 2. 🚨 받은 것이 저장소에 올라가지 않는가 ===")
    check("받는 곳이 data/ 아래다",
          os.path.abspath(F.DEST).startswith(os.path.join(os.path.abspath(_ROOT), "data")))
    gi = io.open(os.path.join(_ROOT, ".gitignore"), encoding="utf-8").read()
    check("🚨 .gitignore 가 data/ 를 통째로 막는다",
          any(line.strip() == "data/" for line in gi.splitlines()))

    print("=== 3. 🚨 «검사할 것이 없다»는 «통과»가 아니다 (BL-59 모양) ===")
    with tempfile.TemporaryDirectory() as tmp:
        old_dest, old_manifest = F.DEST, F.MANIFEST
        F.DEST = tmp
        F.MANIFEST = os.path.join(tmp, "manifest.json")
        try:
            rv, out = _quiet(F.cmd_verify)
            check("빈 상태에서 --verify 가 0이 아닌 값으로 죽는다", rv != 0)
            # 문구에 «통과»라는 낱말은 나온다(«통과»가 아니다). 성공 표시가 없는지를 본다.
            check("성공했다고 말하지 않는다", "❌" in out and "✅" not in out)
            check("무엇을 하라고 알려 준다", "--list" in out)
        finally:
            F.DEST, F.MANIFEST = old_dest, old_manifest

    print("=== 4. 디스크가 모자라면 «시작하지 않는다» ===")
    with tempfile.TemporaryDirectory() as tmp:
        old_dest, old_free, old_dl = F.DEST, F.free_bytes, F.download
        F.DEST = tmp

        def _boom(*a, **kw):
            raise AssertionError("디스크가 모자란데 내려받기를 시작했다")

        F.free_bytes = lambda: 1 * F.GB       # 21GB 를 받겠다는데 1GB 밖에 없다
        F.download = _boom
        try:
            rv, out = _quiet(F.cmd_fetch, ["musan"], False, False)
            check("모자라면 0이 아닌 값으로 멈춘다", rv == 2)
            check("내려받기를 아예 시작하지 않는다 (_boom 이 안 불렸다)", True)
            check("얼마가 필요한지 말해 준다", "필요" in out and "여유" in out)
            check("가장 작은 것부터 받으라고 안내한다", "rirs" in out)
        finally:
            F.DEST, F.free_bytes, F.download = old_dest, old_free, old_dl

    print("=== 5. 압축을 푼다 — 그리고 «풀렸다»를 확인한다 ===")
    with tempfile.TemporaryDirectory() as tmp:
        old_dest = F.DEST
        F.DEST = tmp
        try:
            c = _fake(tmp)
            _tar_gz(c.archive_path, {"fake_corpus/sub/a.wav": b"0" * 100,
                                     "fake_corpus/sub/b.wav": b"1" * 200})
            rv, _ = _quiet(F.extract, c)
            check("풀리면 True", rv is True)
            check("probe 경로가 실제로 생겼다", os.path.isdir(c.probe_path))

            # 이미 풀려 있으면 압축파일이 없어도 건드리지 않는다
            os.remove(c.archive_path)
            rv, out = _quiet(F.extract, c)
            check("이미 풀려 있으면 다시 풀지 않는다", rv is True and "건너뛴다" in out)

            # probe 가 없으면 «풀렸다»고 말하지 않는다
            c2 = _fake(tmp, key="f2", probe="없는폴더/sub", archive="f2.tar.gz")
            _tar_gz(c2.archive_path, {"다른곳/x.wav": b"z" * 10})
            rv, out = _quiet(F.extract, c2)
            check("🚨 구조가 다르면 False 로 말한다", rv is False and "❌" in out)
        finally:
            F.DEST = old_dest

    print("=== 6. 🚨 압축 안의 ../ 가 밖으로 못 나간다 ===")
    with tempfile.TemporaryDirectory() as tmp:
        old_dest = F.DEST
        inner = os.path.join(tmp, "dest")
        os.makedirs(inner)
        F.DEST = inner
        try:
            c = _fake(inner)
            _tar_gz(c.archive_path, {"../탈출.txt": b"evil"})
            rv, _ = _quiet(F.extract, c)
            escaped = os.path.exists(os.path.join(tmp, "탈출.txt"))
            check("경로 탈출을 막는다 (밖에 파일이 안 생겼다)", not escaped)
            check("막았으면 True 라고 말하지 않는다", rv is False)
        finally:
            F.DEST = old_dest

    print("=== 7. md5 가 실제 md5 와 같은가 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "x.bin")
        data = b"pluiz" * 100000
        with open(p, "wb") as f:
            f.write(data)
        check("md5_of 가 hashlib 과 일치한다",
              F.md5_of(p) == hashlib.md5(data).hexdigest())

    print("=== 8. 🚨 푼 것을 «확인한 뒤에만» 압축파일을 지운다 ===")
    # 순서가 뒤집히면 10GB 를 다시 받아야 한다. 주석이 아니라 이 검사가 그걸 막는다.
    with tempfile.TemporaryDirectory() as tmp:
        old_dest, old_manifest = F.DEST, F.MANIFEST
        old_dl, old_ex, old_free = F.download, F.extract, F.free_bytes
        F.DEST = tmp
        F.MANIFEST = os.path.join(tmp, "manifest.json")
        payload = b"a" * 5000
        c = _fake(tmp)
        c.md5 = hashlib.md5(payload).hexdigest()
        F.CORPORA["fake"] = c
        try:
            with open(c.archive_path, "wb") as f:
                f.write(payload)
            F.free_bytes = lambda: 500 * F.GB
            F.download = lambda cc, force=False, rounds=8: True
            F.extract = lambda cc: False                 # 푸는 데 실패했다
            rv, out = _quiet(F.cmd_fetch, ["fake"], True, False)   # --drop-archive
            check("🚨 푸는 데 실패하면 압축파일을 안 지운다",
                  os.path.exists(c.archive_path))
            check("실패를 실패라고 말한다", rv == 1 and "실패" in out)

            F.extract = lambda cc: True                  # 이번엔 풀렸다
            rv, out = _quiet(F.cmd_fetch, ["fake"], True, False)
            check("풀린 뒤에는 지운다 (디스크 회수)", not os.path.exists(c.archive_path))

            # md5 가 다르면 풀지도 지우지도 않는다
            F.extract = lambda cc: (_ for _ in ()).throw(
                AssertionError("md5 가 틀렸는데 압축을 풀었다"))
            with open(c.archive_path, "wb") as f:
                f.write(b"different bytes")
            rv, out = _quiet(F.cmd_fetch, ["fake"], True, False)
            check("🚨 md5 가 다르면 풀지 않는다", rv == 1 and "md5 가 다르다" in out)
            check("md5 가 달라도 받은 파일을 멋대로 지우지 않는다",
                  os.path.exists(c.archive_path))
        finally:
            F.CORPORA.pop("fake", None)
            F.DEST, F.MANIFEST = old_dest, old_manifest
            F.download, F.extract, F.free_bytes = old_dl, old_ex, old_free

    print("=== 9. 이어받기 부기 — 받은 것을 버리지 않는다 ===")
    with tempfile.TemporaryDirectory() as tmp:
        old_dest, old_stream = F.DEST, F._stream
        F.DEST = tmp
        try:
            c = _fake(tmp)
            c.size = 1000
            # 크기가 맞으면 망에 나가지 않는다
            with open(c.archive_path, "wb") as f:
                f.write(b"x" * 1000)
            F._stream = lambda *a, **kw: (_ for _ in ()).throw(
                AssertionError("완전한 파일인데 다시 받으러 나갔다"))
            rv, out = _quiet(F.download, c)
            check("이미 완전하면 내려받지 않는다", rv is True and "건너뛴다" in out)

            # 크기가 다르면 .part 로 되돌려 «이어받을 거리»로 남긴다
            with open(c.archive_path, "wb") as f:
                f.write(b"x" * 400)
            calls = []

            def _fake_stream(opener, url, part, have, totalsz):
                calls.append(have)
                with open(part, "ab") as f:
                    f.write(b"x" * (totalsz - have))

            F._stream = _fake_stream
            rv, _ = _quiet(F.download, c)
            check("🚨 받다 만 400바이트를 버리지 않고 이어받는다", calls == [400])
            check("이어받아 완성되면 True", rv is True)
            check("완성되면 .part 가 아니라 본 이름이다",
                  os.path.exists(c.archive_path)
                  and not os.path.exists(c.archive_path + ".part")
                  and os.path.getsize(c.archive_path) == 1000)

            # ── 🚨 끊기면 **스스로 다시 붙는다** (2026-09-18) ──────────────
            # MUSAN 10GB 를 두 번 놓쳤다. 서버가 3MB/s → 370KB/s 로 떨어지다
            # 읽기 타임아웃으로 죽었고, **이어받기가 되는데도 사람이 같은 명령을
            # 다시 쳐야 했다.** 도구가 할 수 있는 일을 사람에게 미룬 것이다.
            os.remove(c.archive_path)
            tries = []

            def _flaky(opener, url, part, have, totalsz):
                tries.append(have)
                with open(part, "ab") as f:            # 조금 받다가
                    f.write(b"x" * 300)
                if len(tries) < 3:                     # 두 번은 끊긴다
                    raise OSError("읽기 시간 초과")
                with open(part, "ab") as f:
                    f.write(b"x" * (totalsz - have - 300))

            F._stream = _flaky
            rv, out = _quiet(F.download, c)
            check(f"🚨 끊겨도 스스로 다시 붙는다 (사람을 안 붙잡는다) · 시도 {tries}",
                  rv is True)
            check("다시 붙을 때도 받은 것을 안 버린다 (이어받는 지점이 는다)",
                  tries == sorted(tries) and tries[0] == 0 and tries[-1] > 0)
            check("다시 붙었다고 말한다 (조용히 재시도하지 않는다)", "다시 붙는다" in out)

            # ⚠️ 그런데 **한 바이트도 안 느는 상태에서는 멈춰야 한다.**
            #    안 그러면 망이 끊긴 자리에서 영원히 돈다 — «돌고 있는데
            #    아무 일도 안 일어나는» 것이 실패보다 나쁘다.
            #    🔑 다만 **한 번에 포기하지도 않는다**(2026-09-18 — 8.74GB 지점에서
            #    `getaddrinfo failed` 가 두 주소에 동시에 났다. 서버가 죽은 게 아니라
            #    이 PC의 이름 해석이 몇 초 끊긴 것이었다). 그래서 «몇 번까지 견디나»가
            #    상수(`STALL_LIMIT`)이고, 그 값이 실제로 상한인지를 여기서 본다.
            os.remove(c.archive_path)
            spins = []

            def _dead(opener, url, part, have, totalsz):
                spins.append(have)
                raise OSError("연결할 수 없다")

            F._stream = _dead
            old_time = F.time
            F.time = types.SimpleNamespace(       # 기다리는 시간을 테스트가 안 산다
                sleep=lambda *_a: None, time=time.time, strftime=time.strftime)
            try:
                rv, out = _quiet(F.download, c, rounds=99)
            finally:
                F.time = old_time
            check(f"🚨 안 늘면 결국 멈춘다 (영원히 안 돈다) · 시도 {len(spins)}회",
                  rv is False and len(spins) == F.STALL_LIMIT * len(c.urls))
            check("🔑 한 번에 포기하지도 않는다 (망 깜빡임을 견딘다)",
                  F.STALL_LIMIT >= 2 and "쉬었다 다시 본다" in out)
        finally:
            F.DEST, F._stream = old_dest, old_stream

    print("=== 9-B. 대체 주소가 «있다»가 아니라 «된다» 인가 ===")
    # 🚨 2026-09-18 — 본 주소가 끊긴 **바로 그 순간에** 대체 주소가 SSL 로 죽었다.
    #    `us.openslr.org` 는 인증서가 그 이름으로 발급돼 있지 않다(Hostname mismatch).
    #    «대체 주소가 있다»가 거짓이었고, **본 주소가 죽기 전까지 드러나지 않았다.**
    #    그래서 여기서 ①그 주소가 다시 안 들어왔는지 ②실측 기록이 소스에 남아 있는지를 본다.
    #    (망에는 안 나간다 — 나가면 테스트가 망 상태에 따라 흔들린다)
    src = io.open(os.path.join(_ROOT, "scripts", "fetch_wakeword_corpora.py"),
                  encoding="utf-8").read()
    check("🚨 인증서가 안 맞는 주소(us.openslr.org)가 다시 안 들어왔다",
          "us.openslr.org/resources" not in src)
    check("대체 주소를 직접 찔러 본 기록이 소스에 있다",
          "Hostname mismatch" in src and "206" in src)
    for c in F.CORPORA.values():
        hosts = {u.split("/")[2] for u in c.urls}
        check(f"[{c.key}] 대체 주소가 **다른 호스트**다 (같은 서버면 대체가 아니다)",
              len(hosts) == len(c.urls))

    print("=== 10. 목록(manifest) 이 4단계가 읽을 것을 담는가 ===")
    with tempfile.TemporaryDirectory() as tmp:
        old_dest, old_manifest = F.DEST, F.MANIFEST
        F.DEST = tmp
        F.MANIFEST = os.path.join(tmp, "manifest.json")
        try:
            os.makedirs(os.path.join(tmp, "musan", "noise"))
            for i in range(3):
                with open(os.path.join(tmp, "musan", "noise", f"{i}.wav"), "wb") as f:
                    f.write(b"0" * (10 + i))
            rv, _ = _quiet(F.write_manifest)
            m = json.load(io.open(F.MANIFEST, encoding="utf-8"))
            check("풀린 것을 «풀림»으로 적는다", m["말뭉치"]["musan"]["풀림"] is True)
            check("파일 수를 실제로 센다", m["말뭉치"]["musan"]["내용"]["files"] == 3)
            check("바이트도 센다", m["말뭉치"]["musan"]["내용"]["bytes"] == 10 + 11 + 12)
            check("확장자별로 센다 (4단계가 .wav/.flac 을 찾는다)",
                  m["말뭉치"]["musan"]["내용"]["by_ext"].get(".wav") == 3)
            check("안 받은 것은 «풀림» 이 아니다", m["말뭉치"]["zeroth"]["풀림"] is False)
            check("라이선스를 목록에도 박는다",
                  all(v["라이선스"] for v in m["말뭉치"].values()))
            check("자동으로 못 받는 것(AI Hub · Common Voice)도 적는다",
                  set(m["수동"]) == {"aihub", "commonvoice"})
        finally:
            F.DEST, F.MANIFEST = old_dest, old_manifest

    print("=== 11. 인자를 틀리게 줬을 때 ===")
    old_argv = sys.argv
    try:
        sys.argv = ["fetch_wakeword_corpora.py", "없는말뭉치"]
        rv, out = _quiet(F.main)
        check("모르는 이름이면 0이 아닌 값", rv == 2)
        check("쓸 수 있는 이름을 알려 준다", "musan" in out and "zeroth" in out)
    finally:
        sys.argv = old_argv

    print(f"{NL}결과: {passed}/{total} 통과")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
