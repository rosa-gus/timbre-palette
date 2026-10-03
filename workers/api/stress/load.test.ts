import { env } from "cloudflare:workers";
import { applyD1Migrations, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import worker from "../src/index";

const options = JSON.parse(env.STRESS_OPTIONS!) as { requests: number; concurrency: number; upstreamMs: number };
const version = "local-stress";
const mbid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const ip = (group: number, index: number) => `2001:db8:${group}::${(index + 1).toString(16)}`;
const histories = Array.from({ length: 50 }, (_, i) => ({ name: `Track ${i}`, mbid: mbid(i + 1),
  playcount: "2", artist: { name: "Synthetic artist", mbid: mbid(i + 100) } }));
const expectedRefusals = new Set(["rate_limited", "lastfm_busy", "lastfm_rate_limited", "hydration_busy", "hydration_daily_budget", "d1_busy", "d1_daily_budget"]);
let upstreamCalls = 0;
let upstreamActive = 0;
let upstreamPeak = 0;
let providerLimited = false;

function tracks(address: string): Request {
  return new Request("https://local-stress.invalid/v3/profiles/stress-user/tracks?period=1month&page=1", {
    headers: { "CF-Connecting-IP": address },
  });
}
function post(path: string, address: string, body: unknown): Request {
  return new Request(`https://local-stress.invalid${path}`, { method: "POST",
    headers: { "CF-Connecting-IP": address, "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
async function resetGuard(name: string): Promise<void> {
  await runInDurableObject(env.RESOURCE_GUARD.getByName(name), (_instance, ctx) => {
    ctx.storage.sql.exec("DELETE FROM guard_state");
  });
}
async function lastfmState(): Promise<{ leases: Record<string, unknown> }> {
  return runInDurableObject(env.RESOURCE_GUARD.getByName("lastfm-v1"), (_instance, ctx) => {
    return JSON.parse(ctx.storage.sql.exec<{ value: string }>("SELECT value FROM guard_state WHERE key = 'lastfm'").one().value);
  });
}

async function d1State(): Promise<{ reads: number; writes: number; operations: number }> {
  return runInDurableObject(env.RESOURCE_GUARD.getByName("d1-daily-v1"), (_instance, ctx) => {
    const key = `d1:${new Date().toISOString().slice(0, 10)}`;
    const row = ctx.storage.sql.exec<{ value: string }>("SELECT value FROM guard_state WHERE key = ?", key).toArray()[0];
    return row ? JSON.parse(row.value) : { reads: 0, writes: 0, operations: 0 };
  });
}

beforeAll(async () => {
  await applyD1Migrations(env.DB, env.TEST_MIGRATIONS!);
  await env.DB.prepare(`INSERT INTO musicbrainz_credit_index_snapshots
    (snapshot_version, status, index_schema_version, manifest_hash, source_url, license, attribution, object_prefix)
    VALUES (?, 'active', 'musicbrainz-instrument-credits-serving-v2', ?, 'https://local-stress.invalid', 'CC0', 'synthetic', 'local')`)
    .bind(version, "a".repeat(64)).run();
  await env.DB.prepare(`INSERT INTO snapshot_recordings (snapshot_version, recording_mbid, status)
    SELECT ?, value, 'complete_empty' FROM json_each(?)`)
    .bind(version, JSON.stringify(Array.from({ length: 1000 }, (_, i) => mbid(i + 1)))).run();
});
beforeEach(async () => {
  await env.DB.prepare("DELETE FROM snapshot_hydration_jobs").run();
  await Promise.all(["lastfm-v1", "hydration-v1", "d1-daily-v1"].map(resetGuard));
  upstreamCalls = upstreamActive = upstreamPeak = 0;
  providerLimited = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    if (url.origin !== "https://ws.audioscrobbler.com" || url.pathname !== "/2.0/") {
      throw new Error("External network access is forbidden in this local stress test.");
    }
    upstreamCalls++;
    upstreamPeak = Math.max(upstreamPeak, ++upstreamActive);
    try {
      await new Promise((resolve) => setTimeout(resolve, options.upstreamMs));
      return providerLimited ? Response.json({ error: 29 }) : Response.json({ toptracks: {
        track: histories, "@attr": { user: "stress-user", totalPages: "4" },
      } });
    } finally { upstreamActive--; }
  });
});
afterEach(() => vi.restoreAllMocks());

function percentile(values: number[], percent: number): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return Number(sorted[Math.max(0, Math.ceil(sorted.length * percent) - 1)].toFixed(2));
}
const emit = console.log.bind(console);
async function burst(scenario: string, makeRequest: (index: number) => Request, routeEnv: Env = env) {
  const statuses: Record<string, number> = {};
  const codes: Record<string, number> = {};
  const retryAfterSeconds: Record<string, { min: number; max: number }> = {};
  const latencies: number[] = [];
  const acceptedLatencies: number[] = [];
  let next = 0, accepted = 0, refused = 0, unexpected = 0;
  const upstreamBefore = upstreamCalls;
  const databaseBefore = await d1State();
  upstreamPeak = 0;
  const started = performance.now();
  await Promise.all(Array.from({ length: Math.min(options.requests, options.concurrency) }, async () => {
    while (next < options.requests) {
      const index = next++;
      const requestStarted = performance.now();
      try {
        const response = await worker.fetch(makeRequest(index), routeEnv);
        const body = await response.text();
        const elapsed = performance.now() - requestStarted;
        latencies.push(elapsed);
        statuses[response.status] = (statuses[response.status] ?? 0) + 1;
        if (response.ok) { accepted++; acceptedLatencies.push(elapsed); }
        else {
          const problem = JSON.parse(body) as { error?: string };
          const code = problem.error ?? "unknown";
          codes[code] = (codes[code] ?? 0) + 1;
          const retryAfter = Number(response.headers.get("Retry-After"));
          const previous = retryAfterSeconds[code];
          retryAfterSeconds[code] = { min: Math.min(previous?.min ?? retryAfter, retryAfter),
            max: Math.max(previous?.max ?? retryAfter, retryAfter) };
          if ((response.status === 429 || response.status === 503) && expectedRefusals.has(code) && retryAfter > 0) refused++;
          else unexpected++;
        }
      } catch { unexpected++; }
    }
  }));
  const elapsed = performance.now() - started;
  const databaseAfter = await d1State();
  const result = { scenario, requests: options.requests, concurrency: options.concurrency, accepted, refused, unexpected,
    statuses, refusal_codes: codes, retry_after_seconds: retryAfterSeconds, duration_ms: Number(elapsed.toFixed(2)),
    completed_per_second: Number((options.requests / elapsed * 1000).toFixed(2)),
    accepted_per_second: Number((accepted / elapsed * 1000).toFixed(2)),
    p50_ms: percentile(latencies, 0.5), p95_ms: percentile(latencies, 0.95), p99_ms: percentile(latencies, 0.99),
    accepted_p95_ms: percentile(acceptedLatencies, 0.95),
    upstream_calls: upstreamCalls - upstreamBefore, upstream_peak: upstreamPeak,
    d1_reads: databaseAfter.reads - databaseBefore.reads, d1_writes: databaseAfter.writes - databaseBefore.writes,
    d1_reservations: databaseAfter.operations - databaseBefore.operations };
  emit(`STRESS_RESULT ${JSON.stringify(result)}`);
  expect(unexpected, scenario).toBe(0);
  expect(accepted + refused).toBe(options.requests);
  return result;
}

// Comparison only: retain the native visitor limiter while bypassing Last.fm's
// shared guard. The production handler and configuration are never changed.
function ipOnlyEnv(): Env {
  return { ...env, RESOURCE_GUARD: new Proxy(env.RESOURCE_GUARD, {
    get(target, property) {
      if (property === "getByName") return (name: string) => {
        const stub = target.getByName(name);
        if (name !== "lastfm-v1") return stub;
        return new Proxy(stub, { get(object, key) {
          if (key === "acquireLastfm") return async () => ({ ok: true, id: crypto.randomUUID() });
          if (key === "finishLastfm") return async () => undefined;
          const value = Reflect.get(object, key);
          return typeof value === "function" ? value.bind(object) : value;
        } });
      };
      const value = Reflect.get(target, property);
      return typeof value === "function" ? value.bind(target) : value;
    },
  }) };
}

it("bounds an abrupt multi-IP Last.fm burst with the current protections", async () => {
  const result = await burst("lastfm-multiple-ips-global", (i) => tracks(ip(1, i)));
  expect(result.accepted).toBeGreaterThan(0);
  expect(result.refused).toBeGreaterThan(0);
  expect(result.upstream_peak).toBeLessThanOrEqual(Number(env.LASTFM_MAX_CONCURRENT));
  expect(result.upstream_calls).toBe(result.accepted);
  expect(Object.keys((await lastfmState()).leases)).toHaveLength(0);
});

it("measures the same multi-IP workload with only the visitor limiter", async () => {
  const result = await burst("lastfm-multiple-ips-only-ip", (i) => tracks(ip(2, i)), ipOnlyEnv());
  expect(result.accepted).toBe(options.requests);
  expect(result.upstream_calls).toBe(options.requests);
});

it("exposes the impact of visitors sharing one IP", async () => {
  const result = await burst("lastfm-shared-ip-only-ip", () => tracks(ip(3, 0)), ipOnlyEnv());
  expect(result.accepted).toBeGreaterThan(0);
  expect(result.refusal_codes.rate_limited).toBeGreaterThan(0);
  expect(result.upstream_calls).toBe(result.accepted);
});

it("stops upstream traffic during provider overload and serializes recovery", async () => {
  providerLimited = true;
  expect((await worker.fetch(tracks(ip(4, 0)), env)).status).toBe(503);
  const closed = await burst("lastfm-provider-cooldown", (i) => tracks(ip(5, i)));
  expect(closed.upstream_calls).toBe(0);
  expect(closed.refused).toBe(options.requests);
  await runInDurableObject(env.RESOURCE_GUARD.getByName("lastfm-v1"), (_instance, ctx) => {
    const value = JSON.parse(ctx.storage.sql.exec<{ value: string }>("SELECT value FROM guard_state WHERE key = 'lastfm'").one().value);
    value.openUntil = Date.now() - 1; // Advance the fixture's cooldown without waiting a real minute.
    ctx.storage.sql.exec("UPDATE guard_state SET value = ? WHERE key = 'lastfm'", JSON.stringify(value));
  });
  const guard = env.RESOURCE_GUARD.getByName("lastfm-v1");
  const probe = await guard.acquireLastfm();
  if (!probe.ok) throw new Error("Recovery probe was refused");
  const recovering = await burst("lastfm-recovery-probe-held", (i) => tracks(ip(6, i)));
  expect(recovering.upstream_calls).toBe(0);
  expect(recovering.refused).toBe(options.requests);
  await guard.finishLastfm(probe.id, "success");
  providerLimited = false;
  expect((await worker.fetch(tracks(ip(7, 0)), env)).status).toBe(200);
  expect(Object.keys((await lastfmState()).leases)).toHaveLength(0);
});

it("bounds concurrent hydration admissions and persisted jobs", async () => {
  const result = await burst("hydration-concurrent", (i) => post("/v3/hydration", ip(8, i), {
    snapshot_version: version, recording_targets: [{ kind: "recording", mbid: mbid(i + 2000) }], artist_mbids: [],
  }));
  expect(result.accepted).toBeGreaterThan(0);
  expect(result.refused).toBeGreaterThan(0);
  const count = await env.DB.prepare("SELECT COUNT(*) AS count FROM snapshot_hydration_jobs").first<{ count: number }>();
  expect(count?.count).toBe(result.accepted);
  expect(count!.count).toBeLessThanOrEqual(Number(env.HYDRATION_DAILY_NEW_UNITS));
});

it("refuses evidence requests before querying when the shared D1 budget is exhausted", async () => {
  const guard = env.RESOURCE_GUARD.getByName("d1-daily-v1");
  const reservation = await guard.reserveD1(Number(env.D1_DAILY_READ_BUDGET), 0);
  if (!reservation.ok) throw new Error("Failed to prepare exhausted-budget fixture");
  await guard.settleD1(reservation.id, Number(env.D1_DAILY_READ_BUDGET), 0, true);
  const result = await burst("evidence-d1-budget-exhausted", (i) => post("/v3/evidence", ip(9, i), {
    track_mbids: histories.map((track) => track.mbid), artist_mbids: histories.map((track) => track.artist.mbid),
  }));
  expect(result.refusal_codes.d1_daily_budget).toBe(options.requests);
  expect(result.d1_reservations).toBe(0);
  expect(result.d1_reads).toBe(0);
  expect(result.d1_writes).toBe(0);
  const available = await burst("documentation-and-health-during-budget-pause", (i) => new Request(
    `https://local-stress.invalid${["/health", "/docs", "/openapi.json"][i % 3]}`));
  expect(available.accepted).toBe(options.requests);
});

it("measures concurrent evidence batches against populated local D1 tables", async () => {
  const result = await burst("evidence-concurrent", (i) => post("/v3/evidence", ip(10, i), {
    track_mbids: Array.from({ length: 50 }, (_, n) => mbid((i * 50 + n) % 1000 + 1)), artist_mbids: [],
  }));
  expect(result.accepted).toBeGreaterThan(0);
  expect(result.d1_reservations).toBeGreaterThan(0);
  expect(result.d1_reads).toBeLessThanOrEqual(Number(env.D1_DAILY_READ_BUDGET));
  expect(result.d1_writes).toBe(0);
  expect(result.refusal_codes.d1_daily_budget ?? 0).toBe(0);
  if (result.refusal_codes.d1_busy) expect(result.retry_after_seconds.d1_busy).toEqual({ min: 5, max: 5 });
});

it("refuses hydration inserts when the shared D1 write budget is exhausted", async () => {
  const guard = env.RESOURCE_GUARD.getByName("d1-daily-v1");
  const reservation = await guard.reserveD1(0, Number(env.D1_DAILY_WRITE_BUDGET));
  if (!reservation.ok) throw new Error("Failed to prepare exhausted-write-budget fixture");
  await guard.settleD1(reservation.id, 0, Number(env.D1_DAILY_WRITE_BUDGET), true);
  const result = await burst("hydration-d1-write-budget-exhausted", (i) => post("/v3/hydration", ip(11, i), {
    snapshot_version: version, recording_targets: [{ kind: "recording", mbid: mbid(i + 9000) }], artist_mbids: [],
  }));
  expect(result.accepted).toBe(0);
  expect(result.refusal_codes.d1_daily_budget).toBeGreaterThan(0);
  expect(result.d1_writes).toBe(0);
  const count = await env.DB.prepare("SELECT COUNT(*) AS count FROM snapshot_hydration_jobs").first<{ count: number }>();
  expect(count?.count).toBe(0);
});
