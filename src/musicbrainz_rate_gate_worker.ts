import { DurableObject, WorkerEntrypoint } from "cloudflare:workers";

const RATE_GATE_NAME = "musicbrainz";
const MINIMUM_INTERVAL_MS = 1_000;
const MAXIMUM_INTERVAL_MS = 60_000;

interface RateGateEnvironment {
  MUSICBRAINZ_RATE_GATE: DurableObjectNamespace<MusicBrainzRateGate>;
}

interface RateGateReservation {
  wait_ms: number;
  reserved_until_ms: number;
}

interface RateGateRow {
  wait_ms: number;
  reserved_until_ms: number;
}

/**
 * Serializes MusicBrainz request slots across all Worker invocations.
 *
 * The next slot is persisted in SQLite so an isolate restart cannot reset the
 * limiter and cause a burst of requests.
 */
export class MusicBrainzRateGate extends DurableObject<RateGateEnvironment> {
  constructor(ctx: DurableObjectState, env: RateGateEnvironment) {
    super(ctx, env);
    void ctx.blockConcurrencyWhile(async () => {
      this.ctx.storage.sql.exec(`
        CREATE TABLE IF NOT EXISTS rate_gate_state (
          name TEXT PRIMARY KEY,
          next_allowed_at_ms INTEGER NOT NULL
        )
      `);
    });
  }

  acquire_slot(minimum_interval_ms: number): RateGateReservation {
    const interval_ms = normalizeInterval(minimum_interval_ms);
    const now_ms = Date.now();
    const row = this.ctx.storage.sql
      .exec<RateGateRow>(
        `
          INSERT INTO rate_gate_state (name, next_allowed_at_ms)
          VALUES (?, ? + ?)
          ON CONFLICT(name) DO UPDATE SET
            next_allowed_at_ms =
              max(rate_gate_state.next_allowed_at_ms, ?) + ?
          RETURNING
            max(0, next_allowed_at_ms - ? - ?) AS wait_ms,
            next_allowed_at_ms AS reserved_until_ms
        `,
        RATE_GATE_NAME,
        now_ms,
        interval_ms,
        now_ms,
        interval_ms,
        now_ms,
        interval_ms,
      )
      .one();

    return {
      wait_ms: Math.max(0, Math.round(Number(row.wait_ms))),
      reserved_until_ms: Math.round(Number(row.reserved_until_ms)),
    };
  }
}

/**
 * Private RPC facade used by the Python enrichment service.
 */
export class RateGateService extends WorkerEntrypoint<RateGateEnvironment> {
  async acquire_slot(minimum_interval_ms: number): Promise<RateGateReservation> {
    const gate = this.env.MUSICBRAINZ_RATE_GATE.getByName(RATE_GATE_NAME);
    return gate.acquire_slot(normalizeInterval(minimum_interval_ms));
  }
}

export default {
  async fetch(): Promise<Response> {
    return new Response("Not found.", { status: 404 });
  },
} satisfies ExportedHandler<RateGateEnvironment>;

function normalizeInterval(value: number): number {
  if (!Number.isFinite(value)) {
    return MINIMUM_INTERVAL_MS;
  }
  return Math.min(
    MAXIMUM_INTERVAL_MS,
    Math.max(MINIMUM_INTERVAL_MS, Math.round(value)),
  );
}
