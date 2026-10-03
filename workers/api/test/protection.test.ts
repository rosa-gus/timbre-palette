import { env } from "cloudflare:workers";
import { applyD1Migrations, runInDurableObject } from "cloudflare:test";
import { beforeAll, beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index";
import { budgetedDatabase, ProtectionError } from "../../shared/protection";
import { findCandidate, claimCandidate } from "../../hydrator/src/jobs";

const version = "guard-test";
const mbid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const post = (targets: { kind: string; mbid: string }[], artists: string[] = []) =>
  new Request("https://api.test/v3/hydration", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ snapshot_version: version, recording_targets: targets, artist_mbids: artists }) });
const allow = { limit: async () => ({ success: true }) };
const routeEnv = () => ({ ...env, LASTFM_VISITOR_LIMITER: allow, HYDRATION_VISITOR_LIMITER: allow, D1_VISITOR_LIMITER: allow });

async function resetGuard(name: string) {
  await runInDurableObject(env.RESOURCE_GUARD.getByName(name), async (_instance, ctx) => {
    ctx.storage.sql.exec("DELETE FROM guard_state");
  });
}

beforeAll(async () => {
  await applyD1Migrations(env.DB, env.TEST_MIGRATIONS!);
  await env.DB.prepare(`INSERT INTO musicbrainz_credit_index_snapshots
    (snapshot_version, status, index_schema_version, manifest_hash, source_url, license, attribution, object_prefix)
    VALUES (?, 'active', 'musicbrainz-instrument-credits-serving-v2', 'hash', 'https://test.invalid', 'CC0', 'test', 'test')`).bind(version).run();
});

beforeEach(async () => {
  await env.DB.prepare("DELETE FROM snapshot_hydration_jobs").run();
  await Promise.all(["lastfm-v1", "hydration-v1", "d1-daily-v1"].map(resetGuard));
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected external request"));
});
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe("Last.fm protection", () => {
  it("preserves successful Last.fm history payloads and releases their permits", async () => {
    const payload = { toptracks: { track: [{ name: "Example", mbid: mbid(1) }], "@attr": { page: "1" } } };
    vi.mocked(fetch).mockResolvedValueOnce(Response.json(payload));
    const response = await worker.fetch(new Request("https://api.test/v3/profiles/alice/tracks?period=1month&page=2"), routeEnv());
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.json()).toEqual(payload);
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
    await runInDurableObject(env.RESOURCE_GUARD.getByName("lastfm-v1"), async (_instance, ctx) => {
      const state = JSON.parse(ctx.storage.sql.exec<{ value: string }>("SELECT value FROM guard_state WHERE key = 'lastfm'").one().value);
      expect(Object.keys(state.leases)).toHaveLength(0);
      expect(state.calls).toBe(1);
    });
  });

  it("keeps profile-not-found separate from provider overload", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ error: 6 }));
    const response = await worker.fetch(new Request("https://api.test/v3/profiles/missing/tracks"), routeEnv());
    expect(response.status).toBe(404);
    expect((await env.RESOURCE_GUARD.getByName("lastfm-v1").acquireLastfm()).ok).toBe(true);
  });

  it("shares the concurrency limit across callers and reclaims abandoned leases", async () => {
    const guard = env.RESOURCE_GUARD.getByName("lastfm-v1");
    const permits = await Promise.all(Array.from({ length: 12 }, () => guard.acquireLastfm()));
    expect(permits.filter((permit) => permit.ok)).toHaveLength(8);
    expect(permits.filter((permit) => !permit.ok)).toHaveLength(4);
    await runInDurableObject(guard, async (_instance, ctx) => {
      const value = JSON.parse(ctx.storage.sql.exec<{ value: string }>("SELECT value FROM guard_state WHERE key = 'lastfm'").one().value);
      for (const lease of Object.values(value.leases) as { expires: number }[]) lease.expires = 0;
      ctx.storage.sql.exec("UPDATE guard_state SET value = ? WHERE key = 'lastfm'", JSON.stringify(value));
    });
    expect((await guard.acquireLastfm()).ok).toBe(true);
  });

  it("stops the world on provider error 29 even with HTTP 200", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ error: 29, message: "Too many requests" }));
    const response = await worker.fetch(new Request("https://api.test/v3/profiles/alice/tracks"), routeEnv());
    expect(response.status).toBe(503);
    expect(response.headers.get("Retry-After")).toBe("60");
    expect(await response.json()).toMatchObject({ error: "lastfm_rate_limited" });
    const second = await worker.fetch(new Request("https://api.test/v3/profiles/bob/metadata"), routeEnv());
    expect(second.status).toBe(503);
    expect(await second.json()).toMatchObject({ error: "lastfm_busy" });
  });

  it("opens on repeated failures and permits only one recovery probe", async () => {
    const guard = env.RESOURCE_GUARD.getByName("lastfm-v1");
    for (let i = 0; i < 5; i++) {
      const permit = await guard.acquireLastfm();
      if (!permit.ok) throw new Error("expected permit");
      await guard.finishLastfm(permit.id, "failure");
    }
    expect((await guard.acquireLastfm()).ok).toBe(false);
    await runInDurableObject(guard, async (_instance, ctx) => {
      const value = JSON.parse(ctx.storage.sql.exec<{ value: string }>("SELECT value FROM guard_state WHERE key = 'lastfm'").one().value);
      value.openUntil = Date.now() - 1;
      ctx.storage.sql.exec("UPDATE guard_state SET value = ? WHERE key = 'lastfm'", JSON.stringify(value));
    });
    const probe = await guard.acquireLastfm();
    expect(probe.ok).toBe(true);
    expect((await guard.acquireLastfm()).ok).toBe(false);
    if (!probe.ok) throw new Error("expected probe");
    await guard.finishLastfm(probe.id, "success");
    expect((await guard.acquireLastfm()).ok).toBe(true);
  });

  it("rejects visitors before upstream calls and leaves health/options available", async () => {
    const testEnv = { ...routeEnv(), LASTFM_VISITOR_LIMITER: { limit: async () => ({ success: false }) } };
    const response = await worker.fetch(new Request("https://api.test/v3/profiles/alice/tracks"), testEnv);
    expect(response.status).toBe(429);
    expect(response.headers.get("Access-Control-Expose-Headers")).toBe("Retry-After");
    expect((await worker.fetch(new Request("https://api.test/health"), testEnv)).status).toBe(200);
    expect((await worker.fetch(new Request("https://api.test/v3/hydration", { method: "OPTIONS" }), testEnv)).status).toBe(204);
  });
});

describe("hydration admission", () => {
  it("deduplicates inserts and does not spend the new-target budget on repeats", async () => {
    const targets = [{ kind: "track", mbid: mbid(1) }];
    const first = await worker.fetch(post(targets), routeEnv());
    expect(first.status).toBe(202);
    expect(await first.json()).toMatchObject({ accepted: 1, inserted: 1 });
    const repeat = await worker.fetch(post(targets), routeEnv());
    expect(repeat.status).toBe(202);
    expect(await repeat.json()).toMatchObject({ accepted: 1, inserted: 0 });
  });

  it("atomically caps daily new work and allows repeats after reaching the cap", async () => {
    const guard = env.RESOURCE_GUARD.getByName("hydration-v1");
    const artists = Array.from({ length: 200 }, (_, i) => ({ kind: "artist" as const, mbid: mbid(i + 1) }));
    expect((await guard.scheduleHydration(version, artists)).ok).toBe(true);
    const tracks = Array.from({ length: 50 }, (_, i) => ({ kind: "track" as const, mbid: mbid(i + 300) }));
    expect((await guard.scheduleHydration(version, tracks)).ok).toBe(true); // 300 units
    const refused = await guard.scheduleHydration(version, tracks.map((target) => ({ ...target, mbid: mbid(Number(target.mbid.slice(-12)) + 100) })));
    expect(refused.ok).toBe(false);
    expect(refused).toMatchObject({ code: "hydration_daily_budget" });
    expect((await guard.scheduleHydration(version, artists)).ok).toBe(true);
    expect((await env.DB.prepare("SELECT COUNT(*) AS count FROM snapshot_hydration_jobs").first<{ count: number }>())?.count).toBe(250);
  });

  it("rejects inactive snapshots and oversized bodies without inserting jobs", async () => {
    await env.DB.prepare("UPDATE musicbrainz_credit_index_snapshots SET status = 'superseded' WHERE snapshot_version = ?").bind(version).run();
    try {
      const response = await worker.fetch(post([{ kind: "recording", mbid: mbid(1) }]), routeEnv());
      expect(response.status).toBe(503);
    } finally {
      await env.DB.prepare("UPDATE musicbrainz_credit_index_snapshots SET status = 'active' WHERE snapshot_version = ?").bind(version).run();
    }
    const response = await worker.fetch(new Request("https://api.test/v3/hydration", { method: "POST", body: "é".repeat(9_000) }), routeEnv());
    expect(response.status).toBe(413);
    expect((await env.DB.prepare("SELECT COUNT(*) AS count FROM snapshot_hydration_jobs").first<{ count: number }>())?.count).toBe(0);
  });

  it("does not run D1 or queue work when the visitor is limited", async () => {
    const response = await worker.fetch(post([{ kind: "recording", mbid: mbid(1) }]), {
      ...routeEnv(), HYDRATION_VISITOR_LIMITER: { limit: async () => ({ success: false }) },
    });
    expect(response.status).toBe(429);
    expect((await env.DB.prepare("SELECT COUNT(*) AS count FROM snapshot_hydration_jobs").first<{ count: number }>())?.count).toBe(0);
  });

  it("refuses new work when the old backlog is full, but acknowledges repeats", async () => {
    await env.DB.prepare(`INSERT INTO snapshot_hydration_jobs (snapshot_version, target_kind, target_mbid, shard_key, created_at)
      SELECT ?, 'artist', value, '000', '2020-01-01 00:00:00' FROM json_each(?)`)
      .bind(version, JSON.stringify(Array.from({ length: 720 }, (_, i) => mbid(i + 1)))).run();
    await env.DB.prepare("UPDATE snapshot_hydration_jobs SET status = 'processing', attempts = 5 WHERE target_mbid = ?").bind(mbid(1)).run();
    const response = await worker.fetch(post([{ kind: "recording", mbid: mbid(999) }]), routeEnv());
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ error: "hydration_busy" });
    expect((await worker.fetch(post([], [mbid(1)]), routeEnv())).status).toBe(202);
  });

  it("bounds concurrent admission without multiplying inserted work", async () => {
    const guard = env.RESOURCE_GUARD.getByName("hydration-v1");
    const responses = await Promise.all(Array.from({ length: 10 }, (_, i) => guard.scheduleHydration(version, [{ kind: "recording", mbid: mbid(i + 1) }])));
    expect(responses.filter((response) => response.ok)).toHaveLength(1);
    expect((await env.DB.prepare("SELECT COUNT(*) AS count FROM snapshot_hydration_jobs").first<{ count: number }>())?.count).toBe(1);
  });
});

describe("shared D1 budget", () => {
  it("reserves capacity before concurrent operations and settles actual billed rows", async () => {
    const guard = env.RESOURCE_GUARD.getByName("d1-daily-v1");
    const permits = await Promise.all(Array.from({ length: 5 }, () => guard.reserveD1(1_000_000, 0)));
    expect(permits.filter((permit) => permit.ok)).toHaveLength(4);
    const first = permits.find((permit) => permit.ok)!;
    if (!first.ok) throw new Error("expected permit");
    await guard.settleD1(first.id, 100, 0, true);
    expect((await guard.reserveD1(50_000, 0)).ok).toBe(true);
  });

  it("retains uncertain reservations and stops when a query exceeds its estimate", async () => {
    const guard = env.RESOURCE_GUARD.getByName("d1-daily-v1");
    const permit = await guard.reserveD1(50_000, 0);
    if (!permit.ok) throw new Error("expected permit");
    await guard.settleD1(permit.id, 50_001, 0, true);
    expect((await guard.reserveD1(1, 0)).ok).toBe(false);
  });

  it("keeps daily accounting across object handles and starts a new UTC day", async () => {
    const guard = env.RESOURCE_GUARD.getByName("d1-daily-v1");
    expect((await guard.reserveD1(4_000_000, 0)).ok).toBe(true);
    expect((await env.RESOURCE_GUARD.getByName("d1-daily-v1").reserveD1(1, 0)).ok).toBe(false);
    await runInDurableObject(guard, async (_instance, ctx) => {
      const today = new Date().toISOString().slice(0, 10);
      const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
      ctx.storage.sql.exec("UPDATE guard_state SET key = ? WHERE key = ?", `d1:${yesterday}`, `d1:${today}`);
    });
    expect((await guard.reserveD1(50_000, 0)).ok).toBe(true);
  });

  it("blocks both API and background queries when their shared budget is exhausted", async () => {
    const guard = env.RESOURCE_GUARD.getByName("d1-daily-v1");
    expect((await guard.reserveD1(4_000_000, 70_000)).ok).toBe(true);
    const response = await worker.fetch(new Request("https://api.test/v3/evidence", { method: "POST",
      body: JSON.stringify({ track_mbids: [], artist_mbids: [] }) }), routeEnv());
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ error: "d1_daily_budget" });
    const db = budgetedDatabase(env.DB, env.RESOURCE_GUARD);
    await expect(db.prepare("SELECT 1").first()).rejects.toBeInstanceOf(ProtectionError);
  });

  it("counts first(), run(), and batch() metadata, including index writes", async () => {
    const db = budgetedDatabase(env.DB, env.RESOURCE_GUARD);
    await db.prepare("SELECT 1 AS value").first();
    await db.batch([db.prepare(`INSERT INTO snapshot_hydration_jobs
      (snapshot_version, target_kind, target_mbid, shard_key) VALUES (?, 'recording', ?, '0000')`).bind(version, mbid(1))]);
    await db.prepare("UPDATE snapshot_hydration_jobs SET status = 'complete'").run();
    await runInDurableObject(env.RESOURCE_GUARD.getByName("d1-daily-v1"), async (_instance, ctx) => {
      const state = JSON.parse(ctx.storage.sql.exec<{ value: string }>("SELECT value FROM guard_state WHERE key LIKE 'd1:%'").one().value);
      expect(state.writes).toBeGreaterThan(2);
      expect(state.writes).toBeLessThan(100);
      expect(state.operations).toBe(3);
      expect(Object.keys(state.reservations)).toHaveLength(0);
    });
  });

  it("fails closed when accounting is unavailable, without touching D1", async () => {
    const namespace = { getByName: () => ({ reserveD1: async () => { throw new Error("unavailable"); } }) };
    const rawStatement = env.DB.prepare("SELECT 1");
    const execute = vi.spyOn(rawStatement, "all");
    vi.spyOn(env.DB, "prepare").mockReturnValue(rawStatement);
    const db = budgetedDatabase(env.DB, namespace as never);
    const statement = db.prepare("SELECT 1");
    await expect(statement.first()).rejects.toMatchObject({ code: "protection_unavailable" });
    expect(execute).not.toHaveBeenCalled();
  });

  it("recovers a hydrator's final processing lease after a quota pause", async () => {
    await env.DB.prepare(`INSERT INTO snapshot_hydration_jobs
      (snapshot_version, target_kind, target_mbid, shard_key, status, attempts, updated_at)
      VALUES (?, 'recording', ?, '0000', 'processing', 5, '2020-01-01 00:00:00')`).bind(version, mbid(1)).run();
    const db = budgetedDatabase(env.DB, env.RESOURCE_GUARD);
    const candidate = await findCandidate(db);
    expect(candidate).not.toBeNull();
    const claimed = await claimCandidate(db, candidate!);
    expect(claimed?.attempts).toBe(5);
    expect(await findCandidate(db)).toBeNull(); // The renewed lease cannot be claimed twice.
  });
});
