# -*- coding: utf-8 -*-
"""hwp(5.0) 본문 텍스트 추출 — stdlib만 사용.

학과 산출물 양식(docs/documentations/*.hwp)의 목차·표 항목을 뽑아 md 작업본을
만들 때 썼다(2026-09-15). 양식이 개정되면 다시 쓴다.

    python scripts/hwp_extract.py "docs/documentations/*.hwp"

olefile·pyhwp 없이 돈다 — OLE(CFB) 컨테이너를 직접 읽고, BodyText/SectionN을
raw deflate로 풀어 HWPTAG_PARA_TEXT(67) 레코드의 UTF-16LE 텍스트만 모은다.
표 안의 글자도 같은 레코드로 나오므로 양식의 «칸 이름»이 그대로 뽑힌다.

⚠️ 본문 텍스트만 뽑는다. 표 구조·서식·이미지는 잃는다. 제출용 변환이 아니라
«양식이 무엇을 요구하는가»를 읽기 위한 도구다.
"""
import struct, zlib, sys, io, os, glob

FREESECT, ENDOFCHAIN, FATSECT, DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC


class CFB(object):
    def __init__(self, data):
        self.d = data
        assert data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 'not a CFB file'
        self.ssz = 1 << struct.unpack_from('<H', data, 0x1E)[0]
        self.mssz = 1 << struct.unpack_from('<H', data, 0x20)[0]
        nfat = struct.unpack_from('<I', data, 0x2C)[0]
        self.dir0 = struct.unpack_from('<I', data, 0x30)[0]
        self.cutoff = struct.unpack_from('<I', data, 0x38)[0]
        mini0 = struct.unpack_from('<I', data, 0x3C)[0]
        nmini = struct.unpack_from('<I', data, 0x40)[0]
        dif0 = struct.unpack_from('<I', data, 0x44)[0]
        ndif = struct.unpack_from('<I', data, 0x48)[0]

        # DIFAT: 109 entries in header, then chain
        difat = list(struct.unpack_from('<109I', data, 0x4C))
        sec, cnt = dif0, 0
        while sec not in (ENDOFCHAIN, FREESECT) and cnt < ndif + 8:
            raw = self._sector(sec)
            vals = struct.unpack_from('<%dI' % (self.ssz // 4), raw, 0)
            difat.extend(vals[:-1])
            sec = vals[-1]
            cnt += 1

        # FAT
        self.fat = []
        for s in difat[:nfat]:
            if s in (FREESECT, ENDOFCHAIN):
                continue
            self.fat.extend(struct.unpack_from('<%dI' % (self.ssz // 4), self._sector(s), 0))

        # MiniFAT
        self.mfat = []
        sec, cnt = mini0, 0
        while sec not in (ENDOFCHAIN, FREESECT) and cnt < nmini + 8:
            self.mfat.extend(struct.unpack_from('<%dI' % (self.ssz // 4), self._sector(sec), 0))
            sec = self.fat[sec] if sec < len(self.fat) else ENDOFCHAIN
            cnt += 1

        self._read_dir()

    def _sector(self, n):
        off = 512 + n * self.ssz
        return self.d[off:off + self.ssz]

    def _chain(self, start, fat):
        out, s, guard = [], start, 0
        while s not in (ENDOFCHAIN, FREESECT) and guard < 1 << 20:
            out.append(s)
            s = fat[s] if s < len(fat) else ENDOFCHAIN
            guard += 1
        return out

    def _read_dir(self):
        raw = b''.join(self._sector(s) for s in self._chain(self.dir0, self.fat))
        self.entries = []
        for i in range(len(raw) // 128):
            e = raw[i * 128:(i + 1) * 128]
            nlen = struct.unpack_from('<H', e, 64)[0]
            name = e[:max(0, nlen - 2)].decode('utf-16-le', 'ignore')
            self.entries.append({
                'name': name,
                'type': e[66],
                'start': struct.unpack_from('<I', e, 116)[0],
                'size': struct.unpack_from('<Q', e, 120)[0],
            })
        root = self.entries[0]
        self.ministream = b''.join(self._sector(s) for s in self._chain(root['start'], self.fat))

    def open(self, name):
        for e in self.entries:
            if e['name'] == name and e['type'] == 2:
                if e['size'] >= self.cutoff:
                    data = b''.join(self._sector(s) for s in self._chain(e['start'], self.fat))
                else:
                    data = b''.join(
                        self.ministream[s * self.mssz:(s + 1) * self.mssz]
                        for s in self._chain(e['start'], self.mfat))
                return data[:e['size']]
        return None

    def names(self):
        return [e['name'] for e in self.entries if e['type'] == 2]


# 8 wchar를 차지하는 확장 컨트롤 문자
EXT = set([1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23])
SINGLE = set([0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31])


def para_text(chunk):
    out, i, n = [], 0, len(chunk) // 2
    while i < n:
        c = struct.unpack_from('<H', chunk, i * 2)[0]
        if c in EXT:
            i += 8
            continue
        if c in SINGLE:
            if c in (10, 13):
                out.append('\n')
            i += 1
            continue
        out.append(chr(c))
        i += 1
    return ''.join(out)


def records(buf):
    i, n = 0, len(buf)
    while i + 4 <= n:
        v = struct.unpack_from('<I', buf, i)[0]
        tag, size = v & 0x3FF, (v >> 20) & 0xFFF
        i += 4
        if size == 0xFFF:
            size = struct.unpack_from('<I', buf, i)[0]
            i += 4
        yield tag, buf[i:i + size]
        i += size


def extract(path):
    cfb = CFB(open(path, 'rb').read())
    fh = cfb.open('FileHeader') or b''
    compressed = bool(fh[36] & 1) if len(fh) > 36 else True
    secs = sorted([n for n in cfb.names() if n.startswith('Section')],
                  key=lambda s: int(s[7:] or 0))
    paras = []
    for s in secs:
        raw = cfb.open(s)
        if compressed:
            try:
                raw = zlib.decompress(raw, -15)
            except Exception:
                raw = zlib.decompress(raw)
        for tag, body in records(raw):
            if tag == 67:  # HWPTAG_PARA_TEXT
                t = para_text(body).strip()
                if t:
                    paras.append(t)
    return paras


if __name__ == '__main__':
    for p in sorted(glob.glob(sys.argv[1])):
        print('\n' + '=' * 78)
        print('### ' + os.path.basename(p))
        print('=' * 78)
        try:
            for t in extract(p):
                print(t)
        except Exception as e:
            print('!! 실패: %r' % (e,))
