import { expect, it } from "vitest";
import { retryAfterSeconds } from "../src/api/retry-after";

it("handles seconds and HTTP dates without accepting invalid or past values", () => {
  const now = Date.UTC(2026, 9, 3);
  const parse = (value: string) => retryAfterSeconds(new Response(null, { headers: { "Retry-After": value } }), now);
  expect(parse("60")).toBe(60);
  expect(parse(new Date(now + 120_000).toUTCString())).toBe(120);
  expect(parse("9999999")).toBe(86_400);
  expect(parse("invalid")).toBeUndefined();
  expect(parse(new Date(now - 60_000).toUTCString())).toBeUndefined();
});
