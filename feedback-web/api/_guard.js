// 공통 문지기. 🚨 **두 비밀을 섞지 않는다** —
//   `INGEST_KEY` 는 «보낼 수 있는 자격», `VIEW_PASSWORD` 는 «볼 수 있는 자격»이다.
//   하나로 합치면 팀원 PC 에 깔린 키 하나로 **남의 보고를 전부 읽을 수 있다.**
import { timingSafeEqual } from "node:crypto";

export function sameSecret(given, expected) {
  if (!expected) return false;              // 서버에 비밀이 없으면 전부 거부(fail-closed)
  const a = Buffer.from(String(given ?? ""), "utf8");
  const b = Buffer.from(expected, "utf8");
  // 🔑 길이가 다르면 `timingSafeEqual` 이 던진다. 길이까지 상수시간으로 감추진
  //   못하지만, 적어도 **내용 비교에서 글자 수가 새지 않게** 한다.
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export function readJson(req) {
  // Vercel Node 함수는 Content-Type: application/json 이면 req.body 를 파싱해 준다.
  if (req.body && typeof req.body === "object") return req.body;
  try {
    return JSON.parse(req.body || "{}");
  } catch {
    return null;
  }
}
