// 수신기를 **실제로 불러** 돌린다 — 소스 대조가 아니다 (BL-83 의 교훈).
//
//     cd feedback-web && npm test
//
// 🚨 Redis 는 가짜를 끼운다. 진짜를 쓰면 **사람이 보낸 보고를 건드린다.**
// 🔑 이 파일이 지키는 핵심은 **비밀 둘이 서로 못 넘나든다**는 것이다 —
//   보내기 키로 보기가 되면 팀원 PC 의 키 하나로 남의 보고를 전부 읽는다.
import { createRequire } from "node:module";
process.env.INGEST_KEY = "ingest-secret-0123456789";
process.env.VIEW_PASSWORD = "view-password-0123456789";
process.env.UPSTASH_REDIS_REST_URL = "https://fake.local";
process.env.UPSTASH_REDIS_REST_TOKEN = "fake";

// @upstash/redis 를 가짜로 바꾼다
const store = [];
const { Redis } = await import("@upstash/redis");
Redis.fromEnv = () => ({
  lpush: async (_k, v) => store.unshift(v),
  ltrim: async () => {},
  llen: async () => store.length,
  lrange: async () => store.slice(0, 200),
});

const report = (await import("./api/report.js")).default;
const list = (await import("./api/list.js")).default;

let checks = 0, fails = 0;

function expect(label, got, want) {
  checks += 1;
  const ok = got === want;
  if (!ok) fails += 1;
  console.log(`  ${ok ? "✓" : "✗ FAIL"} ${label}  (${got}, 기대 ${want})`);
}

function res() {
  const o = { code: 0, body: null };
  o.status = (c) => { o.code = c; return o; };
  o.json = (b) => { o.body = b; return o; };
  return o;
}
const show = (label, r, want) => expect(label, r.code, want);

let r;
r = res(); await report({ method: "GET", headers: {}, body: {} }, r);
show("GET 으로 보내면 거부", r, 405);

r = res(); await report({ method: "POST", headers: {}, body: { markdown: "### x" } }, r);
show("키 없으면 401", r, 401);

r = res(); await report({ method: "POST", headers: { "x-pluiz-key": "틀린키입니다아아아아아아아아아아" }, body: { markdown: "### x" } }, r);
show("키 틀리면 401", r, 401);

r = res(); await report({ method: "POST", headers: { "x-pluiz-key": process.env.VIEW_PASSWORD }, body: { markdown: "### x" } }, r);
show("🚨 보기 비번으로 넣기 거부", r, 401);

r = res(); await report({ method: "POST", headers: { "x-pluiz-key": process.env.INGEST_KEY }, body: {} }, r);
show("본문 없으면 400", r, 400);

r = res(); await report({ method: "POST", headers: { "x-pluiz-key": process.env.INGEST_KEY }, body: { markdown: "x".repeat(70000) } }, r);
show("너무 크면 413", r, 413);

r = res(); await report({ method: "POST", headers: { "x-pluiz-key": process.env.INGEST_KEY },
  body: { markdown: "### ⬜ 안 되거나 이상해요 — 2026-10-03 14:32:10", kind: "bug", who: "팀원 A", place: "카페" } }, r);
show("✅ 제대로 보내면 저장", r, 200);

r = res(); await list({ method: "GET", headers: {}, query: {} }, r);
show("보기 비번 없으면 401", r, 401);

r = res(); await list({ method: "GET", headers: { "x-view-key": process.env.INGEST_KEY }, query: {} }, r);
show("🚨 보내기 키로 보기 거부", r, 401);

r = res(); await list({ method: "GET", headers: { "x-view-key": process.env.VIEW_PASSWORD }, query: {} }, r);
show("✅ 보기 비번이면 목록", r, 200);

if (fails) { console.error(`${fails}건 실패`); process.exit(1); }
console.log(`${checks}/${checks} 통과`);
