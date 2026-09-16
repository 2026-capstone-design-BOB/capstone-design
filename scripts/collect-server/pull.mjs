/* 모인 녹음을 내려받는다 → data/wakeword_raw/
 *
 *     vercel env pull .env.local     # BLOB_READ_WRITE_TOKEN 을 받아 온다
 *     npm run pull
 *
 * 그 다음은 기존 경로 그대로다:
 *     python scripts/ingest_wakeword.py --list
 *
 * 🔒 `access: 'private'` 이라 토큰 없이는 못 읽는다. 그래서 이 스크립트는
 *    **내 컴퓨터에서만** 돈다 — 서버에 목록 API 를 열지 않는다.
 *    목록 API 를 열면 그게 곧 «누가 녹음했는지 공개»가 된다.
 */
import { list, get } from '@vercel/blob';
import { mkdir, writeFile, readFile, access } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const DEST = join(HERE, '..', '..', 'data', 'wakeword_raw');

// .env.local 을 직접 읽는다 — node 는 자동으로 안 읽는다
if (!process.env.BLOB_READ_WRITE_TOKEN) {
  try {
    const env = await readFile(join(HERE, '.env.local'), 'utf8');
    for (const line of env.split('\n')) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*"?([^"\n\r]*)"?\s*$/);
      if (m) process.env[m[1]] ??= m[2];
    }
  } catch { /* 없으면 아래에서 안내한다 */ }
}
if (!process.env.BLOB_READ_WRITE_TOKEN) {
  console.error('✗ BLOB_READ_WRITE_TOKEN 이 없습니다.');
  console.error('  scripts/collect-server 에서 `vercel env pull .env.local` 를 먼저 돌리세요.');
  process.exit(1);
}

await mkdir(DEST, { recursive: true });
const exists = async p => { try { await access(p); return true; } catch { return false; } };

let cursor, total = 0, skipped = 0, pairs = new Map();
do {
  const page = await list({ cursor, limit: 500 });
  cursor = page.cursor;
  for (const b of page.blobs) {
    const name = b.pathname.split('/').pop();
    const dst = join(DEST, name);
    const base = name.replace(/\.(wav|json)$/, '');
    pairs.set(base, (pairs.get(base) || 0) + 1);
    if (await exists(dst)) { skipped++; continue; }
    const r = await get(b.url);          // private 이라 토큰이 필요하다
    const buf = Buffer.from(await new Response(r.body ?? r).arrayBuffer());
    await writeFile(dst, buf);
    total++;
    console.log('  ↓ ' + name + ' (' + (buf.length / 1024 / 1024).toFixed(1) + 'MB)');
  }
} while (cursor);

// 🚨 짝이 안 맞는 것을 **말한다.** wav 만 있고 json 이 없으면 라벨이 없어
//    그 녹음은 못 쓴다 — 조용히 넘어가면 «왜 데이터가 적지»가 된다.
const lonely = [...pairs].filter(([, n]) => n !== 2).map(([b]) => b);
console.log(`\n새로 받은 것 ${total}개 · 이미 있던 것 ${skipped}개 · 화자 세션 ${pairs.size}개`);
if (lonely.length) {
  console.log(`\n⚠️ 짝이 안 맞는 세션 ${lonely.length}개 (wav 나 json 하나가 없다):`);
  lonely.forEach(b => console.log('   · ' + b));
  console.log('   → 그 사람에게 다시 부탁해야 합니다. 라벨이 없으면 학습에 못 씁니다.');
}
console.log('\n다음: python scripts/ingest_wakeword.py --list');
