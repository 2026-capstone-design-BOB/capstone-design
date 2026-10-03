// GET /api/list?key=… — 쌓인 신고를 돌려준다. 🔒 보기 비밀번호가 필요하다.
import { Redis } from "@upstash/redis";
import { sameSecret } from "./_guard.js";

const KEY = "pluiz:reports";

export default async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "method_not_allowed" });
  }
  // 🚨 **보내는 키로는 못 본다.** 팀원 PC 에 깔린 `INGEST_KEY` 하나로
  //    남의 보고를 전부 읽을 수 있으면 안 된다.
  const given = req.headers["x-view-key"] ?? req.query.key;
  if (!sameSecret(given, process.env.VIEW_PASSWORD)) {
    return res.status(401).json({ error: "unauthorized" });
  }

  try {
    const redis = Redis.fromEnv();
    const raw = await redis.lrange(KEY, 0, 199);
    const items = raw.map((r) => (typeof r === "string" ? JSON.parse(r) : r));
    return res.status(200).json({ count: items.length, items });
  } catch (e) {
    return res.status(500).json({ error: "read_failed", detail: String(e).slice(0, 200) });
  }
}
