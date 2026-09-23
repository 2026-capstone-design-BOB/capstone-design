/* 배포본을 굽는다 — 녹음 페이지 + 업로더 번들 → public/
 *
 * 🔑 **페이지는 한 벌만 관리한다.** `scripts/플루이즈_녹음.html` 이 원본이고,
 *    여기서는 `<script src="uploader.js">` 한 줄을 끼워 넣을 뿐이다.
 *    두 벌로 나누면 반드시 한쪽만 갱신된다 — 이 저장소가 반복해서 데인 모양이다.
 *
 * 그 페이지는 `window.PLUIZ_SEND` 가 있으면 «보내기», 없으면 «파일로 받기» 다.
 * 즉 **같은 파일이 오프라인 모드와 배포 모드 둘 다** 된다.
 */
import { build } from 'esbuild';
import { mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = join(HERE, '..', '플루이즈_녹음.html');
const OUT = join(HERE, 'public');

const MARK = '<script src="uploader.js"></script>';

await rm(OUT, { recursive: true, force: true });
await mkdir(OUT, { recursive: true });

// ① 업로더 번들 (@vercel/blob/client 를 한 파일로)
await build({
  entryPoints: [join(HERE, 'src', 'uploader.js')],
  bundle: true, minify: true, format: 'iife', target: 'es2020',
  outfile: join(OUT, 'uploader.js'),
});

// ② 페이지에 업로더를 끼운다. **페이지 스크립트보다 먼저** 실려야
//    `sender()` 가 처음부터 참이 된다.
let html = await readFile(PAGE, 'utf8');
if (!html.includes('<script>')) throw new Error('페이지에서 <script> 를 찾지 못했습니다');
if (html.includes(MARK)) throw new Error('이미 번들이 끼워져 있습니다(원본이 오염됐다)');
html = html.replace('<script>', MARK + '\n<script>');

await writeFile(join(OUT, 'index.html'), html, 'utf8');
console.log('✓ public/index.html · public/uploader.js');
