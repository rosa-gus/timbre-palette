import {
  mapArtistEntries,
  mapRecordingClaims,
  type ArtistMappingResult,
  type RecordingMappingResult,
} from "./mapping";
import { readShard, ShardError, shardKey } from "./shards";
import {
  MAX_ATTEMPTS,
  PROCESSING_LEASE_MINUTES,
  type AliasShard,
  type JobRow,
  type RecordingShard,
  type TargetKind,
  type VocabularyShard,
} from "./types";

const DEFAULT_R2_READ_LIMIT = 9_000_000;
const DEFAULT_R2_DAILY_READ_LIMIT = 720;
const DEFAULT_D1_DAILY_WRITE_LIMIT = 50_000;
const RETRY_DELAYS_SECONDS = [60, 300, 1_800, 10_800, 43_200];

export default {
  async scheduled(
    controller: ScheduledController,
    env: Env,
    _ctx: ExecutionContext,
  ): Promise<void> {
    const started = performance.now();
    try {
      const result = await runOnce(env);
      console.log({
        event: "hydrator_run",
        cron: controller.cron,
        ...result,
        duration_ms: Math.round(performance.now() - started),
      });
    } catch (error) {
      console.error({
        event: "hydrator_run_failed",
        cron: controller.cron,
        error: errorMessage(error),
        duration_ms: Math.round(performance.now() - started),
      });
      throw error;
    }
  },
};

interface RunResult {
  status: "idle" | "completed" | "retrying" | "terminal" | "deferred";
  job_id?: number;
  target_kind?: TargetKind;
  target_mbid?: string;
  snapshot_version?: string;
  shard_key?: string;
  attempts?: number;
  mapped_rows?: number;
  discarded_rows?: number;
  error?: string;
}

async function runOnce(env: Env): Promise<RunResult> {
  const candidate = await findCandidate(env.DB);
  if (candidate === null) {
    return { status: "idle" };
  }

  const job = await claimCandidate(env.DB, candidate);
  if (job === null) {
    return { status: "idle" };
  }

  if (!(await reserveR2Read(env, currentDay()))) {
    await deferJob(env.DB, job.id, "daily R2 read budget exhausted");
    return {
      status: "deferred",
      job_id: job.id,
      target_kind: job.target_kind,
      target_mbid: job.target_mbid,
      snapshot_version: job.snapshot_version,
    };
  }

  try {
    const shard = await readShard(
      env.CREDIT_INDEX,
      job,
      job.target_kind,
      job.shard_key,
    );
    const result = await hydrateTarget(env, job, shard);
    return {
      status: "completed",
      job_id: job.id,
      target_kind: job.target_kind,
      target_mbid: job.target_mbid,
      snapshot_version: job.snapshot_version,
      shard_key: job.shard_key,
      attempts: job.attempts,
      ...result,
    };
  } catch (error) {
    if (error instanceof BudgetDeferredError) {
      return {
        status: "deferred",
        job_id: job.id,
        target_kind: job.target_kind,
        target_mbid: job.target_mbid,
        snapshot_version: job.snapshot_version,
      };
    }
    const terminal = error instanceof ShardError && error.terminal;
    const result = await recordFailure(env.DB, job, errorMessage(error), terminal);
    return {
      status: result.terminal ? "terminal" : "retrying",
      job_id: job.id,
      target_kind: job.target_kind,
      target_mbid: job.target_mbid,
      snapshot_version: job.snapshot_version,
      shard_key: job.shard_key,
      attempts: job.attempts,
      error: errorMessage(error),
    };
  }
}

async function hydrateTarget(
  env: Env,
  job: JobRow,
  shard: RecordingShard | AliasShard | VocabularyShard,
): Promise<{ mapped_rows?: number; discarded_rows?: number }> {
  if (job.target_kind === "recording") {
    const record = (shard as RecordingShard).records[job.target_mbid];
    if (record === undefined) {
      const empty: RecordingMappingResult = {
        claims: [],
        creditCount: 0,
        mappedCreditCount: 0,
        discardedCreditCount: 0,
      };
      await reserveWritesOrDefer(env, job, estimateRecordingWrites(empty));
      await commitRecording(env.DB, job, empty);
      return { mapped_rows: 0, discarded_rows: 0 };
    }
    const mapped = await mapRecordingClaims(env.DB, record.claims);
    await reserveWritesOrDefer(env, job, estimateRecordingWrites(mapped));
    await commitRecording(env.DB, job, mapped);
    return {
      mapped_rows: mapped.claims.length,
      discarded_rows: mapped.discardedCreditCount,
    };
  }

  if (job.target_kind === "track") {
    const alias = (shard as AliasShard).aliases[job.target_mbid] ?? null;
    await reserveWritesOrDefer(env, job, 5);
    await commitTrack(env.DB, job, alias);
    return { mapped_rows: alias === null ? 0 : 1, discarded_rows: 0 };
  }

  const artist = (shard as VocabularyShard).artists[job.target_mbid];
  const mapped: ArtistMappingResult = artist
    ? await mapArtistEntries(env.DB, artist)
    : {
        entries: [],
        entryCount: 0,
        mappedEntryCount: 0,
        discardedEntryCount: 0,
      };
  await reserveWritesOrDefer(env, job, estimateArtistWrites(mapped));
  await commitArtist(env.DB, job, mapped);
  return {
    mapped_rows: mapped.entries.length,
    discarded_rows: mapped.discardedEntryCount,
  };
}

async function findCandidate(db: D1Database): Promise<JobRow | null> {
  return db
    .prepare(
      `
      SELECT jobs.id, jobs.target_kind, jobs.target_mbid, jobs.shard_key,
             jobs.status, jobs.attempts,
             snapshots.snapshot_version, snapshots.index_schema_version,
             snapshots.manifest_hash, snapshots.object_prefix,
             snapshots.methodology_version
      FROM snapshot_hydration_jobs AS jobs
      JOIN musicbrainz_credit_index_snapshots AS snapshots
        ON snapshots.snapshot_version = jobs.snapshot_version
      WHERE snapshots.status = 'active'
        -- Keep this predicate aligned with idx_snapshot_hydration_open_order.
        -- Without it, SQLite cannot use the partial index and scans completed
        -- jobs before applying the eligibility branches below.
        AND jobs.status != 'complete'
        AND (
          (
            jobs.status IN ('pending', 'failed')
            AND jobs.attempts < ?
            AND (jobs.next_attempt_at IS NULL OR jobs.next_attempt_at <= datetime('now'))
          )
          OR (
            jobs.status = 'processing'
            AND jobs.attempts < ?
            AND jobs.updated_at <= datetime('now', ?)
          )
        )
      ORDER BY jobs.created_at, jobs.id
      LIMIT 1
      `,
    )
    .bind(
      MAX_ATTEMPTS,
      MAX_ATTEMPTS,
      `-${PROCESSING_LEASE_MINUTES} minutes`,
    )
    .first<JobRow>();
}

async function claimCandidate(db: D1Database, candidate: JobRow): Promise<JobRow | null> {
  return db
    .prepare(
      `
      UPDATE snapshot_hydration_jobs
      SET status = 'processing',
          attempts = attempts + 1,
          last_error = NULL,
          next_attempt_at = NULL,
          updated_at = datetime('now')
      WHERE id = ?
        AND (
          (
            status IN ('pending', 'failed')
            AND attempts < ?
            AND (next_attempt_at IS NULL OR next_attempt_at <= datetime('now'))
          )
          OR (
            status = 'processing'
            AND attempts < ?
            AND updated_at <= datetime('now', ?)
          )
        )
      RETURNING id, target_kind, target_mbid, shard_key, status, attempts
      `,
    )
    .bind(
      candidate.id,
      MAX_ATTEMPTS,
      MAX_ATTEMPTS,
      `-${PROCESSING_LEASE_MINUTES} minutes`,
    )
    .first<JobRow>()
    .then((claimed) => (claimed ? { ...candidate, ...claimed } : null));
}

async function reserveR2Read(env: Env, dayKey: string): Promise<boolean> {
  const monthlyLimit = positiveEnv(env.R2_READ_LIMIT, DEFAULT_R2_READ_LIMIT);
  const dailyLimit = positiveEnv(
    env.R2_DAILY_READ_LIMIT,
    DEFAULT_R2_DAILY_READ_LIMIT,
  );
  const periodKey = env.R2_USAGE_PERIOD.trim();
  if (!periodKey) {
    throw new Error("R2_USAGE_PERIOD is required");
  }
  const results = await env.DB.batch([
    env.DB
      .prepare(
        `
        INSERT OR IGNORE INTO snapshot_hydrator_usage
            (day_key, d1_write_limit, r2_read_limit)
        VALUES (?, ?, ?)
        `,
      )
      .bind(dayKey, positiveEnv(env.D1_DAILY_WRITE_LIMIT, DEFAULT_D1_DAILY_WRITE_LIMIT), dailyLimit),
    env.DB
      .prepare(
        `
        UPDATE snapshot_hydrator_usage
        SET r2_reads_reserved = r2_reads_reserved + 1,
            updated_at = datetime('now')
        WHERE day_key = ? AND r2_reads_reserved < r2_read_limit
        RETURNING r2_reads_reserved
        `,
      )
      .bind(dayKey),
    env.DB
      .prepare(
        `
        INSERT OR IGNORE INTO musicbrainz_credit_index_usage
            (period_key, read_limit)
        VALUES (?, ?)
        `,
      )
      .bind(periodKey, monthlyLimit),
    env.DB
      .prepare(
        `
        UPDATE musicbrainz_credit_index_usage
        SET reads_reserved = reads_reserved + 1,
            updated_at = datetime('now')
        WHERE period_key = ? AND reads_reserved < read_limit
        RETURNING reads_reserved
        `,
      )
      .bind(periodKey),
  ]);
  return rows(results[1]).length > 0 && rows(results[3]).length > 0;
}

async function reserveWritesOrDefer(
  env: Env,
  job: JobRow,
  estimate: number,
): Promise<void> {
  const db = env.DB;
  const dayKey = currentDay();
  const limit = positiveEnv(
    env.D1_DAILY_WRITE_LIMIT,
    DEFAULT_D1_DAILY_WRITE_LIMIT,
  );
  const result = await db.batch([
    db
      .prepare(
        `
        INSERT OR IGNORE INTO snapshot_hydrator_usage
            (day_key, d1_write_limit, r2_read_limit)
        VALUES (?, ?, ?)
        `,
      )
      .bind(dayKey, limit, DEFAULT_R2_DAILY_READ_LIMIT),
    db
      .prepare(
        `
        UPDATE snapshot_hydrator_usage
        SET d1_writes_reserved = d1_writes_reserved + ?,
            updated_at = datetime('now')
        WHERE day_key = ? AND d1_writes_reserved + ? <= d1_write_limit
        RETURNING d1_writes_reserved
        `,
      )
      .bind(estimate + 1, dayKey, estimate + 1),
  ]);
  if (rows(result[1]).length === 0) {
    await deferJob(db, job.id, "daily D1 write budget exhausted");
    throw new BudgetDeferredError();
  }
}

async function commitRecording(
  db: D1Database,
  job: JobRow,
  mapped: RecordingMappingResult,
): Promise<void> {
  const rows = mapped.claims.map((claim) => ({
    snapshot_version: job.snapshot_version,
    recording_mbid: job.target_mbid,
    claim_level: claim.claim_level,
    subject_slug: claim.subject_slug,
    instrument_slug: claim.instrument_slug,
    family_slug: claim.family_slug,
    scope: claim.scope,
    credit_count: claim.credit_count,
    performer_count: claim.performer_count,
    source_url: claim.source_url,
  }));
  const status = mapped.mappedCreditCount > 0 ? "complete" : "complete_empty";
  await db.batch([
    db
      .prepare(
        `DELETE FROM snapshot_recording_instruments
         WHERE snapshot_version = ? AND recording_mbid = ?`,
      )
      .bind(job.snapshot_version, job.target_mbid),
    db
      .prepare(
        `
        INSERT INTO snapshot_recordings
            (snapshot_version, recording_mbid, status, credit_count,
             mapped_credit_count, discarded_credit_count, last_error,
             hydrated_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL, datetime('now'), datetime('now'))
        ON CONFLICT(snapshot_version, recording_mbid) DO UPDATE SET
            status = excluded.status,
            credit_count = excluded.credit_count,
            mapped_credit_count = excluded.mapped_credit_count,
            discarded_credit_count = excluded.discarded_credit_count,
            last_error = NULL,
            hydrated_at = excluded.hydrated_at,
            updated_at = excluded.updated_at
        `,
      )
      .bind(
        job.snapshot_version,
        job.target_mbid,
        status,
        mapped.creditCount,
        mapped.mappedCreditCount,
        mapped.discardedCreditCount,
      ),
    db
      .prepare(
        `
        INSERT INTO snapshot_recording_instruments
            (snapshot_version, recording_mbid, claim_level, subject_slug,
             instrument_slug, family_slug, scope, credit_count,
             performer_count, source_url)
        SELECT json_extract(value, '$.snapshot_version'),
               json_extract(value, '$.recording_mbid'),
               json_extract(value, '$.claim_level'),
               json_extract(value, '$.subject_slug'),
               json_extract(value, '$.instrument_slug'),
               json_extract(value, '$.family_slug'),
               json_extract(value, '$.scope'),
               json_extract(value, '$.credit_count'),
               json_extract(value, '$.performer_count'),
               json_extract(value, '$.source_url')
        FROM json_each(?)
        WHERE true
        ON CONFLICT(snapshot_version, recording_mbid, claim_level, subject_slug, scope)
        DO UPDATE SET
            credit_count = excluded.credit_count,
            performer_count = excluded.performer_count,
            source_url = excluded.source_url
        `,
      )
      .bind(JSON.stringify(rows)),
    completeJobStatement(db, job.id),
  ]);
}

async function commitTrack(
  db: D1Database,
  job: JobRow,
  recordingMbid: string | null,
): Promise<void> {
  const canonicalRecording = recordingMbid ?? job.target_mbid;
  await db.batch([
    db
      .prepare(
        `
        INSERT INTO snapshot_track_aliases
            (snapshot_version, track_mbid, recording_mbid)
        SELECT json_extract(value, '$.snapshot_version'),
               json_extract(value, '$.track_mbid'),
               json_extract(value, '$.recording_mbid')
        FROM json_each(?)
        WHERE true
        ON CONFLICT(snapshot_version, track_mbid) DO UPDATE SET
            recording_mbid = excluded.recording_mbid,
            hydrated_at = datetime('now')
        `,
      )
      .bind(
        JSON.stringify(
          recordingMbid
            ? [
                {
                  snapshot_version: job.snapshot_version,
                  track_mbid: job.target_mbid,
                  recording_mbid: recordingMbid,
                },
              ]
            : [],
        ),
      ),
    db
      .prepare(
        `
        INSERT OR IGNORE INTO snapshot_hydration_jobs
            (snapshot_version, target_kind, target_mbid, shard_key,
             status, attempts, next_attempt_at)
        VALUES (?, 'recording', ?, ?, 'pending', 0, NULL)
        `,
      )
      .bind(
        job.snapshot_version,
        canonicalRecording,
        shardKey("recording", canonicalRecording),
      ),
    completeJobStatement(db, job.id),
  ]);
}

async function commitArtist(
  db: D1Database,
  job: JobRow,
  mapped: ArtistMappingResult,
): Promise<void> {
  const rows = mapped.entries.map((entry) => ({
    snapshot_version: job.snapshot_version,
    artist_mbid: job.target_mbid,
    ...entry,
  }));
  const status = mapped.mappedEntryCount > 0 ? "complete" : "complete_empty";
  await db.batch([
    db
      .prepare(
        `DELETE FROM snapshot_artist_instruments
         WHERE snapshot_version = ? AND artist_mbid = ?`,
      )
      .bind(job.snapshot_version, job.target_mbid),
    db
      .prepare(
        `
        INSERT INTO snapshot_artists
            (snapshot_version, artist_mbid, status, entry_count,
             mapped_entry_count, discarded_entry_count, last_error,
             hydrated_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL, datetime('now'), datetime('now'))
        ON CONFLICT(snapshot_version, artist_mbid) DO UPDATE SET
            status = excluded.status,
            entry_count = excluded.entry_count,
            mapped_entry_count = excluded.mapped_entry_count,
            discarded_entry_count = excluded.discarded_entry_count,
            last_error = NULL,
            hydrated_at = excluded.hydrated_at,
            updated_at = excluded.updated_at
        `,
      )
      .bind(
        job.snapshot_version,
        job.target_mbid,
        status,
        mapped.entryCount,
        mapped.mappedEntryCount,
        mapped.discardedEntryCount,
      ),
    db
      .prepare(
        `
        INSERT INTO snapshot_artist_instruments
            (snapshot_version, artist_mbid, instrument_slug, family_slug,
             distinct_recordings, documented_recordings, prevalence,
             evidence_quality, source_scope)
        SELECT json_extract(value, '$.snapshot_version'),
               json_extract(value, '$.artist_mbid'),
               json_extract(value, '$.instrument_slug'),
               json_extract(value, '$.family_slug'),
               json_extract(value, '$.distinct_recordings'),
               json_extract(value, '$.documented_recordings'),
               json_extract(value, '$.prevalence'),
               1.0,
               'recording'
        FROM json_each(?)
        WHERE true
        ON CONFLICT(snapshot_version, artist_mbid, instrument_slug)
        DO UPDATE SET
            family_slug = excluded.family_slug,
            distinct_recordings = excluded.distinct_recordings,
            documented_recordings = excluded.documented_recordings,
            prevalence = excluded.prevalence
        `,
      )
      .bind(JSON.stringify(rows)),
    completeJobStatement(db, job.id),
  ]);
}

function completeJobStatement(db: D1Database, jobId: number): D1PreparedStatement {
  return db
    .prepare(
      `
      UPDATE snapshot_hydration_jobs
      SET status = 'complete', last_error = NULL,
          next_attempt_at = NULL, updated_at = datetime('now')
      WHERE id = ? AND status = 'processing'
      `,
    )
    .bind(jobId);
}

async function recordFailure(
  db: D1Database,
  job: JobRow,
  message: string,
  terminalRequested: boolean,
): Promise<{ terminal: boolean }> {
  const terminal = terminalRequested || job.attempts >= MAX_ATTEMPTS;
  const error = message.slice(0, 500);
  const statements: D1PreparedStatement[] = [];
  if (terminal && job.target_kind === "recording") {
    statements.push(
      db
        .prepare(
          `
          INSERT INTO snapshot_recordings
              (snapshot_version, recording_mbid, status, last_error,
               updated_at)
          VALUES (?, ?, 'failed', ?, datetime('now'))
          ON CONFLICT(snapshot_version, recording_mbid) DO UPDATE SET
              status = 'failed', last_error = excluded.last_error,
              updated_at = excluded.updated_at
          `,
        )
        .bind(job.snapshot_version, job.target_mbid, error),
    );
  }
  if (terminal && job.target_kind === "artist") {
    statements.push(
      db
        .prepare(
          `
          INSERT INTO snapshot_artists
              (snapshot_version, artist_mbid, status, last_error,
               updated_at)
          VALUES (?, ?, 'failed', ?, datetime('now'))
          ON CONFLICT(snapshot_version, artist_mbid) DO UPDATE SET
              status = 'failed', last_error = excluded.last_error,
              updated_at = excluded.updated_at
          `,
        )
        .bind(job.snapshot_version, job.target_mbid, error),
    );
  }
  const delay = RETRY_DELAYS_SECONDS[Math.min(job.attempts - 1, RETRY_DELAYS_SECONDS.length - 1)] ?? 43_200;
  statements.push(
    db
      .prepare(
        `
      UPDATE snapshot_hydration_jobs
        SET status = 'failed',
            attempts = CASE WHEN ? = 1 THEN ? ELSE attempts END,
            last_error = ?,
            next_attempt_at = datetime('now', ?), updated_at = datetime('now')
        WHERE id = ? AND status = 'processing'
        `,
      )
      .bind(
        terminal ? 1 : 0,
        MAX_ATTEMPTS,
        error,
        terminal ? null : `+${delay} seconds`,
        job.id,
      ),
  );
  await db.batch(statements);
  return { terminal };
}

async function deferJob(db: D1Database, jobId: number, reason: string): Promise<void> {
  await db
    .prepare(
      `
      UPDATE snapshot_hydration_jobs
      SET status = 'pending', attempts = max(attempts - 1, 0),
          last_error = ?, next_attempt_at = datetime('now', '+2 minutes'),
          updated_at = datetime('now')
      WHERE id = ? AND status = 'processing'
      `,
    )
    .bind(reason, jobId)
    .run();
}

function estimateRecordingWrites(mapped: RecordingMappingResult): number {
  return mapped.claims.length + 4;
}

function estimateArtistWrites(mapped: ArtistMappingResult): number {
  return mapped.entries.length + 4;
}

function currentDay(): string {
  return new Date().toISOString().slice(0, 10);
}

function positiveEnv(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function rows<T>(result: D1Result | undefined): T[] {
  return (result?.results ?? []) as T[];
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

class BudgetDeferredError extends Error {
  constructor() {
    super("daily D1 write budget exhausted");
    this.name = "BudgetDeferredError";
  }
}
