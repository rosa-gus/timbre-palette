export type Denial = { ok: false; code: string; retryAfter: number };
export type Permit = { ok: true; id: string };
export type HydrationTarget = { kind: "track" | "recording" | "artist"; mbid: string };

export interface GuardRpc {
  acquireLastfm(): Promise<Permit | Denial>;
  finishLastfm(id: string, outcome: "success" | "failure" | "rate_limited"): Promise<void>;
  reserveD1(reads: number, writes: number): Promise<Permit | Denial>;
  settleD1(id: string, reads: number, writes: number, certain: boolean): Promise<void>;
  scheduleHydration(version: string, targets: HydrationTarget[]): Promise<
    { ok: true; accepted: number; inserted: number } | Denial
  >;
}

export interface GuardNamespace {
  getByName(name: string): GuardRpc;
}

export class ProtectionError extends Error {
  constructor(readonly code: string, readonly retryAfter = 60, readonly status = 503) {
    super(code);
    this.name = "ProtectionError";
  }
}

export function setting(value: string | undefined, fallback: number, maximum = fallback): number {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? Math.min(parsed, maximum) : fallback;
}

export function secondsUntilTomorrow(now = Date.now()): number {
  return Math.max(1, Math.ceil((Date.UTC(
    new Date(now).getUTCFullYear(), new Date(now).getUTCMonth(), new Date(now).getUTCDate() + 1,
  ) - now) / 1000));
}

export const PROTECTION_MESSAGES: Record<string, string> = {
  rate_limited: "Too many requests. Please wait before trying again.",
  lastfm_busy: "Listening history requests are temporarily at capacity.",
  lastfm_rate_limited: "Last.fm is rate limiting requests.",
  hydration_busy: "New hydration jobs are temporarily paused.",
  hydration_daily_budget: "Today's new hydration target budget has been reached.",
  d1_busy: "Database queries are temporarily at capacity. Please try again shortly.",
  d1_daily_budget: "Today's database budget has been reached.",
  protection_unavailable: "Request protection is temporarily unavailable.",
  snapshot_unavailable: "The requested evidence snapshot is unavailable.",
  unsupported_snapshot_schema: "The evidence snapshot schema is not supported.",
  hydration_unavailable: "The hydration request could not be stored.",
};

export function protectionResponse(error: ProtectionError): Response {
  console.warn({ event: "request_protected", code: error.code, retry_after: error.retryAfter });
  return Response.json({ error: error.code, message: PROTECTION_MESSAGES[error.code] ?? error.message }, {
    status: error.status,
    headers: {
      "Cache-Control": "no-store",
      "Retry-After": String(error.retryAfter),
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Expose-Headers": "Retry-After",
    },
  });
}

export async function limitVisitor(request: Request, limiter: { limit(input: { key: string }): Promise<{ success: boolean }> }, resource: string): Promise<void> {
  // Only Cloudflare's trusted incoming header, never user-supplied username/X-Forwarded-For.
  const key = `${resource}:${request.headers.get("CF-Connecting-IP") ?? "unknown"}`;
  try {
    if (!(await limiter.limit({ key })).success) throw new ProtectionError("rate_limited", 60, 429);
  } catch (error) {
    if (error instanceof ProtectionError) throw error;
    throw new ProtectionError("protection_unavailable");
  }
}

export async function boundedText(body: ReadableStream<Uint8Array> | null, maxBytes: number): Promise<string> {
  if (!body) return "";
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        throw new ProtectionError("request_too_large", 60, 413);
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder().decode(bytes);
}

/** Every runtime D1 execution reserves headroom, then reports actual billed rows.
 * Failed/ambiguous executions retain their reservation. Never use D1 to count D1 usage.
 * Reservations are conservative estimates, not a bound on arbitrary SQL scans;
 * the account's Free-plan hard limits remain the final enforcement layer.
 */
export function budgetedDatabase(db: D1Database, namespace: GuardNamespace): D1Database {
  const guard = namespace.getByName("d1-daily-v1");
  const originals = new WeakMap<D1PreparedStatement, D1PreparedStatement>();
  const writeStatements = new WeakMap<D1PreparedStatement, boolean>();

  async function execute<T>(writes: boolean, count: number, action: () => Promise<D1Result<T>[]>): Promise<D1Result<T>[]> {
    let permit: Permit | Denial;
    try { permit = await guard.reserveD1(50_000 * count, writes ? 5_000 * count : 0); }
    catch { throw new ProtectionError("protection_unavailable"); }
    if (!permit.ok) throw new ProtectionError(permit.code, permit.retryAfter);
    let results: D1Result<T>[];
    try { results = await action(); }
    catch (error) {
      // No refund: the database may have consumed rows before reporting failure.
      console.error({ event: "d1_execution_failed", reservation_id: permit.id });
      throw error;
    }
    let reads = 0, written = 0;
    let certain = true;
    for (const result of results) {
      if (!Number.isSafeInteger(result.meta?.rows_read) || !Number.isSafeInteger(result.meta?.rows_written)) certain = false;
      reads += result.meta?.rows_read ?? 0;
      written += result.meta?.rows_written ?? 0;
    }
    try { await guard.settleD1(permit.id, reads, written, certain); }
    catch { throw new ProtectionError("protection_unavailable"); }
    console.log({ event: "d1_usage", rows_read: reads, rows_written: written, statements: count });
    return results;
  }

  function wrap(statement: D1PreparedStatement, writes: boolean): D1PreparedStatement {
    const wrapped = new Proxy(statement, {
      get(target, property) {
        if (property === "bind") return (...values: unknown[]) => wrap(target.bind(...values), writes);
        if (property === "all" || property === "run") return async () =>
          (await execute(writes, 1, async () => [await target.all()]))[0];
        if (property === "first") return async (column?: string) => {
          const row = (await execute(writes, 1, async () => [await target.all<Record<string, unknown>>()]))[0].results?.[0];
          return row ? (column === undefined ? row : row[column] ?? null) : null;
        };
        if (property === "raw") return () => { throw new ProtectionError("protection_unavailable"); };
        const value = Reflect.get(target, property);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
    originals.set(wrapped, statement);
    writeStatements.set(wrapped, writes);
    return wrapped;
  }

  return new Proxy(db, {
    get(target, property) {
      if (property === "prepare") return (query: string) => wrap(target.prepare(query), !/^\s*SELECT\b/i.test(query));
      if (property === "batch") return (statements: D1PreparedStatement[]) => {
        if (!statements.length) return Promise.resolve([]);
        if (statements.some((statement) => !originals.has(statement))) throw new ProtectionError("protection_unavailable");
        return execute(statements.some((statement) => writeStatements.get(statement)), statements.length,
          () => target.batch(statements.map((statement) => originals.get(statement)!)));
      };
      if (property === "exec" || property === "withSession" || property === "dump") return () => { throw new ProtectionError("protection_unavailable"); };
      const value = Reflect.get(target, property);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}
