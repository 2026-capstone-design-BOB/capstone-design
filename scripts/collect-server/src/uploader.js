/* 배포본에만 실리는 «전송기».
 *
 * 🚨 왜 그냥 POST 하지 않는가 — **Vercel 함수 본문 한도가 4.5MB인데 WAV가 5.7MB다.**
 *    그냥 올리면 413으로 막힌다. 그래서 브라우저가 Blob 저장소로 **직접** 올리고
 *    함수는 토큰만 발급한다(`handleUpload`). 이게 이 구조의 유일한 이유다.
 *
 * 🔒 `access: 'private'` 이다. 사람 목소리라 URL을 아는 사람이 들을 수 있으면 안 된다 —
 *    동의 문구가 «공개하지 않는다» 이고, 그 약속을 코드가 지켜야 한다.
 *
 * 순서: ① 매니페스트(작다) 를 /api/meta 로 먼저 보내 경로를 받는다
 *       ② 그 경로로 WAV 를 클라이언트 업로드한다
 *    매니페스트를 먼저 보내는 건 **누가 시도했는지라도 남기기 위해서**다.
 *    ②가 실패해도 «누가 어디까지 했다»가 서버에 남아 다시 부탁할 수 있다.
 */
import { upload } from '@vercel/blob/client';

window.PLUIZ_SEND = async function (out, onProgress) {
  // ① 매니페스트 먼저
  const r = await fetch('/api/meta', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: out.json,
  });
  if (!r.ok) {
    const t = await r.text().catch(() => '');
    throw new Error('메타 ' + r.status + (t ? ' · ' + t.slice(0, 80) : ''));
  }
  const { base } = await r.json();
  if (!base) throw new Error('서버가 저장 경로를 주지 않았습니다');

  // ② WAV 는 브라우저 → Blob 직행 (함수 본문 한도를 우회한다)
  await upload(base + '.wav', out.wav, {
    access: 'private',
    contentType: 'audio/wav',
    handleUploadUrl: '/api/upload',
    clientPayload: base,
    onUploadProgress: p => { if (onProgress) onProgress(Math.round(p.percentage)); },
  });
};
