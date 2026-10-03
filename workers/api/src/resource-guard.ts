import { DurableObject } from "cloudflare:workers";
import {
  budgetedDatabase, ProtectionError, secondsUntilTomorrow, setting,
  type Denial, type Permit, type HydrationTarget,
} from "../../shared/protection";

type LastfmState = {
  tokens: number; updated: number; day: string; calls: number;
  failures: number; openUntil: number;
  leases: Record<string, { expires: number; probe: boolean }>;
};
type D1State = {
  reads: number; writes: number; operations: number; stopped: boolean;
  reservations: Record<string, { reads: number; writes: number; expires: number }>;
};

/** One instance per scarce resource, behind the inexpensive visitor limiter.
 * All accounting is SQLite-backed (available on Free), never stored in D1.
 */
export class ResourceGuard extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS guard_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
  }

  private load<T>(key: string, fallback: T): T {
    const row = this.ctx.storage.sql.exec<{ value: string }>("SELECT value FROM guard_state WHERE key = ?", key).toArray()[0];
    return row ? JSON.parse(row.value) as T : fallback;
  }

  private save(key: string, value: unknown): void {
    this.ctx.storage.sql.exec("INSERT INTO guard_state VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", key, JSON.stringify(value));
  }

  acquireLastfm(): Permit | Denial {
    const now = Date.now();
    const day = new Date(now).toISOString().slice(0, 10);
    const burst = setting(this.env.LASTFM_GLOBAL_BURST, 10, 20);
    const state = this.load<LastfmState>("lastfm", {
      tokens: burst, updated: now, day, calls: 0, failures: 0, openUntil: 0, leases: {},
    });
    if (state.day !== day) { state.day = day; state.calls = 0; }
    for (const [id, lease] of Object.entries(state.leases)) {
      if (lease.expires <= now) delete state.leases[id];
    }
    if (state.calls >= setting(this.env.LASTFM_DAILY_CALL_LIMIT, 5_000, 5_000)) {
      return { ok: false, code: "lastfm_busy", retryAfter: secondsUntilTomorrow(now) };
    }
    if (state.openUntil > now) return { ok: false, code: "lastfm_busy", retryAfter: Math.ceil((state.openUntil - now) / 1000) };
    const leases = Object.values(state.leases);
    const probe = state.openUntil > 0;
    if (leases.length >= setting(this.env.LASTFM_MAX_CONCURRENT, 8, 16) ||
        (probe && leases.some((lease) => lease.probe))) {
      return { ok: false, code: "lastfm_busy", retryAfter: 5 };
    }
    const rate = setting(this.env.LASTFM_GLOBAL_PER_MINUTE, 120, 120) / 60_000;
    state.tokens = Math.min(burst, state.tokens + Math.max(0, now - state.updated) * rate);
    state.updated = now;
    if (state.tokens < 1) return { ok: false, code: "lastfm_busy", retryAfter: Math.max(1, Math.ceil((1 - state.tokens) / rate / 1000)) };
    const id = crypto.randomUUID();
    state.tokens--;
    state.calls++;
    state.leases[id] = { expires: now + 15_000, probe };
    this.save("lastfm", state);
    return { ok: true, id };
  }

  finishLastfm(id: string, outcome: "success" | "failure" | "rate_limited"): void {
    const state = this.load<LastfmState | null>("lastfm", null);
    if (!state || !state.leases[id]) return;
    const lease = state.leases[id];
    delete state.leases[id];
    if (outcome === "rate_limited" || outcome === "failure") {
      state.failures++;
      if (outcome === "rate_limited" || lease.probe || state.failures >= 5) {
        state.openUntil = Math.max(state.openUntil, Date.now() + 60_000);
        console.warn({ event: "lastfm_circuit_open", outcome, retry_after: 60 });
      }
    } else if (lease.probe || state.openUntil === 0) {
      // Successful requests started before a trip must not close the circuit.
      if (lease.probe && state.openUntil <= Date.now()) state.openUntil = 0;
      state.failures = 0;
    }
    this.save("lastfm", state);
  }

  reserveD1(reads: number, writes: number): Permit | Denial {
    if (!Number.isSafeInteger(reads) || !Number.isSafeInteger(writes) || reads < 0 || writes < 0) {
      return { ok: false, code: "protection_unavailable", retryAfter: 60 };
    }
    const now = Date.now();
    const day = new Date(now).toISOString().slice(0, 10);
    const key = `d1:${day}`;
    const state = this.load<D1State>(key, { reads: 0, writes: 0, operations: 0, stopped: false, reservations: {} });
    for (const [id, reservation] of Object.entries(state.reservations)) {
      // Expired reservations stay charged; only their bookkeeping is removed.
      if (reservation.expires <= now) delete state.reservations[id];
    }
    if (state.stopped || state.operations >= 5_000 ||
        state.reads + reads > setting(this.env.D1_DAILY_READ_BUDGET, 4_000_000, 4_000_000) ||
        state.writes + writes > setting(this.env.D1_DAILY_WRITE_BUDGET, 70_000, 70_000)) {
      return { ok: false, code: "d1_daily_budget", retryAfter: secondsUntilTomorrow(now) };
    }
    const id = `${day}:${crypto.randomUUID()}`;
    state.reads += reads;
    state.writes += writes;
    state.operations++;
    state.reservations[id] = { reads, writes, expires: now + 120_000 };
    this.save(key, state);
    // Keep only today's and yesterday's accounting for requests across midnight.
    this.ctx.storage.sql.exec("DELETE FROM guard_state WHERE key LIKE 'd1:%' AND key < ?", `d1:${new Date(now - 86_400_000).toISOString().slice(0, 10)}`);
    return { ok: true, id };
  }

  settleD1(id: string, reads: number, writes: number, certain: boolean): void {
    const key = `d1:${id.slice(0, 10)}`;
    const state = this.load<D1State | null>(key, null);
    const reservation = state?.reservations[id];
    if (!state || !reservation) return;
    if (certain && Number.isSafeInteger(reads) && Number.isSafeInteger(writes) && reads >= 0 && writes >= 0) {
      state.reads += reads - reservation.reads;
      state.writes += writes - reservation.writes;
      if (reads > reservation.reads || writes > reservation.writes) {
        state.stopped = true;
        console.error({ event: "d1_reservation_exceeded", rows_read: reads, rows_written: writes });
      }
    } else {
      state.stopped = true;
      console.error({ event: "d1_accounting_uncertain" });
    }
    delete state.reservations[id];
    this.save(key, state);
  }

  async scheduleHydration(version: string, targets: HydrationTarget[]): Promise<
    { ok: true; accepted: number; inserted: number } | Denial
  > {
    // Reserve a small shared global request budget before any D1 work. A busy
    // guard never builds an in-memory queue of outstanding admission requests.
    const now = Date.now();
    const day = new Date(now).toISOString().slice(0, 10);
    const state = this.load("hydration", { day, calls: 0, busyUntil: 0 });
    if (state.busyUntil > now) return { ok: false, code: "hydration_busy", retryAfter: 5 };
    if (state.day !== day) { state.day = day; state.calls = 0; }
    if (state.calls >= 1_000) return { ok: false, code: "hydration_daily_budget", retryAfter: secondsUntilTomorrow(now) };
    state.calls++;
    state.busyUntil = now + 300_000;
    this.save("hydration", state);

    const db = budgetedDatabase(this.env.DB, this.env.RESOURCE_GUARD);
    try {
      const snapshot = await db.prepare(`SELECT snapshot_version, index_schema_version
        FROM musicbrainz_credit_index_snapshots WHERE snapshot_version = ? AND status = 'active' LIMIT 1`).bind(version).first<{ index_schema_version: string }>();
      if (!snapshot) return { ok: false, code: "snapshot_unavailable", retryAfter: 60 };
      if (snapshot.index_schema_version !== "musicbrainz-instrument-credits-serving-v2") return { ok: false, code: "unsupported_snapshot_schema", retryAfter: 60 };
      if (!targets.length) return { ok: true, accepted: 0, inserted: 0 };
      // The atomic SQL gate also covers changes made by the hydrator. Track
      // targets reserve two queue units for their later recording job.
      const result = await db.prepare(`
        WITH incoming AS MATERIALIZED (
          SELECT DISTINCT json_extract(value, '$.kind') AS kind, json_extract(value, '$.mbid') AS mbid FROM json_each(?)
        ), fresh AS MATERIALIZED (
          SELECT kind, mbid FROM incoming
          WHERE NOT EXISTS (SELECT 1 FROM snapshot_hydration_jobs WHERE snapshot_version = ? AND target_kind = kind AND target_mbid = mbid)
        ), backlog AS MATERIALIZED (
          SELECT COALESCE(SUM(CASE WHEN target_kind = 'track' THEN 2 ELSE 1 END), 0) AS units
          FROM snapshot_hydration_jobs WHERE snapshot_version = ? AND status != 'complete' AND (status = 'processing' OR attempts < 5)
        ), usage AS MATERIALIZED (
          SELECT COALESCE(SUM(CASE WHEN target_kind = 'track' THEN 2 ELSE 1 END), 0) AS units
          FROM snapshot_hydration_jobs WHERE created_at >= ? AND created_at < ?
        )
        INSERT OR IGNORE INTO snapshot_hydration_jobs (snapshot_version, target_kind, target_mbid, shard_key)
        SELECT ?, kind, mbid, substr(mbid, 1, CASE WHEN kind = 'artist' THEN 3 ELSE 4 END)
        FROM fresh WHERE (SELECT units FROM backlog) + (SELECT COALESCE(SUM(CASE WHEN kind = 'track' THEN 2 ELSE 1 END), 0) FROM fresh) <= ?
          AND (SELECT units FROM usage) + (SELECT COALESCE(SUM(CASE WHEN kind = 'track' THEN 2 ELSE 1 END), 0) FROM fresh) <= ?
        RETURNING target_mbid
      `).bind(JSON.stringify(targets), version, version, `${day} 00:00:00`, `${day} 23:59:59.999`, version,
        setting(this.env.HYDRATION_MAX_PENDING_UNITS, 720, 720),
        setting(this.env.HYDRATION_DAILY_NEW_UNITS, 360, 360)).all();
      const inserted = result.results.length;
      if (!inserted && targets.length) {
        // Distinguish an idempotent repeat from refusal without re-inserting.
        const existing = await db.prepare(`SELECT COUNT(jobs.id) AS count,
          COALESCE(SUM(CASE WHEN jobs.id IS NULL THEN
            CASE WHEN json_extract(incoming.value, '$.kind') = 'track' THEN 2 ELSE 1 END ELSE 0 END), 0) AS missing_units,
          (SELECT COALESCE(SUM(CASE WHEN target_kind = 'track' THEN 2 ELSE 1 END), 0)
            FROM snapshot_hydration_jobs WHERE created_at >= ? AND created_at < ?) AS daily_units
          FROM json_each(?) AS incoming
          LEFT JOIN snapshot_hydration_jobs AS jobs ON jobs.snapshot_version = ?
          AND jobs.target_kind = json_extract(incoming.value, '$.kind')
          AND jobs.target_mbid = json_extract(incoming.value, '$.mbid')`)
          .bind(`${day} 00:00:00`, `${day} 23:59:59.999`, JSON.stringify(targets), version)
          .first<{ count: number; missing_units: number; daily_units: number }>();
        if (existing?.count !== targets.length) {
          if (existing && existing.missing_units + existing.daily_units > setting(this.env.HYDRATION_DAILY_NEW_UNITS, 360, 360)) {
            return { ok: false, code: "hydration_daily_budget", retryAfter: secondsUntilTomorrow(now) };
          }
          return { ok: false, code: "hydration_busy", retryAfter: 120 };
        }
      }
      return { ok: true, accepted: targets.length, inserted };
    } catch (error) {
      if (error instanceof ProtectionError) return { ok: false, code: error.code, retryAfter: error.retryAfter };
      console.error({ event: "hydration_guard_failed" });
      return { ok: false, code: "hydration_unavailable", retryAfter: 60 };
    } finally {
      state.busyUntil = 0;
      this.save("hydration", state);
    }
  }
}
