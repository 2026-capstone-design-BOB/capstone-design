/* 매니페스트(json)를 받아 Blob 에 쓰고, WAV 가 올라갈 경로를 돌려준다.
 *
 * 매니페스트는 4KB 남짓이라 함수 본문 한도(4.5MB)에 걸리지 않는다.
 * WAV 만 클라이언트 업로드로 간다 → api/upload.js
 */
import { put } from '@vercel/blob';

/** 경로에 쓸 수 없는 문자를 걷어낸다. 한글은 남긴다(사람 이름이다). */
function safe(s) {
  return String(s || '').replace(/[^\w가-힣ㄱ-ㅎㅏ-ㅣ-]/g, '_').slice(0, 24) || '익명';
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });

  let meta;
  try {
    meta = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
  } catch {
    return res.status(400).json({ error: '매니페스트를 읽지 못했습니다' });
  }
  if (!meta || !meta.speaker) return res.status(400).json({ error: 'speaker 가 없습니다' });

  // 🔒 동의 없이 들어온 것은 저장하지 않는다. 페이지가 이미 막지만,
  //    **서버도 막아야 한다** — 페이지는 우회할 수 있고 약속은 우리가 한 것이다.
  if (meta.consent !== true) return res.status(400).json({ error: '동의가 없습니다' });

  // 같은 사람이 여러 번 해도 겹치지 않게 시각을 붙인다.
  const stamp = String(meta.recordedAt || new Date().toISOString())
    .slice(0, 19).replace(/[:T-]/g, '');
  const base = `pluiz_${safe(meta.speaker)}_${stamp}`;

  try {
    await put(`${base}.json`, JSON.stringify(meta), {
      access: 'private',
      contentType: 'application/json; charset=utf-8',
      addRandomSuffix: false,
      allowOverwrite: true,     // 같은 사람이 재시도하면 덮어쓴다(중복 파일을 안 만든다)
    });
  } catch (e) {
    return res.status(500).json({ error: '저장 실패: ' + (e.message || String(e)) });
  }
  return res.status(200).json({ base });
}
