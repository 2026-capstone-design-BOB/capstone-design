// POST /api/report — Pluiz 가 보낸 신고를 받는다.
//
// 🚨 **이것이 원본이 아니다.** 원본은 팀원 PC 의 `logs/사용_피드백_보고.md` 다.
//   여기는 «변소윤이 바로 보려고» 두는 사본이고, 이 함수가 죽어도 보고는 안 사라진다.
//   (Pluiz 쪽이 로컬에 먼저 쓰고 나서 보낸다 → core/feedback.py)
import { Redis } from "@upstash/redis";
import { sameSecret, readJson } from "./_guard.js";

const KEY = "pluiz:reports";
const MAX_KEEP = 500;          // 쌓아 둘 최대 개수. 넘으면 오래된 것부터 버린다
const MAX_BYTES = 64 * 1024;   // 보고 하나의 상한. 로그 35줄이면 한참 남는다

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "method_not_allowed" });
  }
  if (!sameSecret(req.headers["x-pluiz-key"], process.env.INGEST_KEY)) {
    // 🔒 왜 거부됐는지 자세히 말하지 않는다 — 열쇠를 맞춰 보는 데 쓰인다.
    return res.status(401).json({ error: "unauthorized" });
  }

  const body = readJson(req);
  if (!body || typeof body.markdown !== "string" || !body.markdown.trim()) {
    return res.status(400).json({ error: "markdown_required" });
  }
  if (Buffer.byteLength(body.markdown, "utf8") > MAX_BYTES) {
    return res.status(413).json({ error: "too_large" });
  }

  const item = {
    markdown: body.markdown,
    kind: String(body.kind || "bug").slice(0, 16),
    when: String(body.when || "").slice(0, 19),
    who: String(body.who || "").slice(0, 16),
    place: String(body.place || "").slice(0, 32),
    received_at: new Date().toISOString(),
  };

  try {
    const redis = Redis.fromEnv();
    await redis.lpush(KEY, JSON.stringify(item));   // 최신이 앞
    await redis.ltrim(KEY, 0, MAX_KEEP - 1);
    const count = await redis.llen(KEY);
    return res.status(200).json({ status: "ok", count });
  } catch (e) {
    // 🚨 **여기서 실패해도 팀원의 보고는 이미 로컬에 있다.** 그 사실을 그대로 알린다 —
    //   «보냈다»고 거짓말하면 팀원이 파일을 안 보낸다.
    return res.status(500).json({ error: "store_failed", detail: String(e).slice(0, 200) });
  }
}
