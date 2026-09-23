/* 클라이언트 업로드 토큰 발급 — 브라우저가 Blob 으로 직행할 수 있게 해 준다.
 *
 * 🚨 이 함수는 **파일을 받지 않는다.** 받으면 4.5MB 한도에 걸린다.
 *    토큰만 주고, 실제 바이트는 브라우저 → Blob 으로 간다.
 *
 * ⚠️ 이 주소는 **모르는 사람에게 공개된다**(그게 목적이다). 그래서 토큰에
 *    제약을 건다 — wav 만, 12MB 까지, 정해진 이름 꼴만. 제약을 안 걸면
 *    남의 저장소에 아무거나 올릴 수 있는 문이 된다.
 */
import { handleUpload } from '@vercel/blob/client';

const MAX_BYTES = 12 * 1024 * 1024;              // 3분 16kHz 16bit ≈ 5.7MB. 여유 두 배.
const NAME = /^pluiz_[\w가-힣ㄱ-ㅎㅏ-ㅣ-]{1,24}_\d{14}\.wav$/;

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  try {
    const body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
    const json = await handleUpload({
      body,
      request: req,
      onBeforeGenerateToken: async pathname => {
        if (!NAME.test(pathname)) throw new Error('허용되지 않는 파일 이름입니다');
        return {
          allowedContentTypes: ['audio/wav'],
          maximumSizeInBytes: MAX_BYTES,
          addRandomSuffix: false,
          allowOverwrite: true,   // 전송 실패 후 재시도가 중복을 안 만들게
        };
      },
      // 업로드가 끝나면 Blob 이 여기로 알려 준다. 로그만 남긴다 —
      // 매니페스트는 이미 /api/meta 에서 저장됐다.
      onUploadCompleted: async ({ blob }) => {
        console.log('[collect] 업로드 완료', blob.pathname);
      },
    });
    return res.status(200).json(json);
  } catch (e) {
    return res.status(400).json({ error: e.message || String(e) });
  }
}
