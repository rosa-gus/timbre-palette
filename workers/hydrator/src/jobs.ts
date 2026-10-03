import { MAX_ATTEMPTS, PROCESSING_LEASE_MINUTES, type JobRow } from "./types";

// A quota pause can interrupt even the final attempt. Expired processing leases
// remain recoverable; replaying the final attempt is idempotent and does not
// exceed MAX_ATTEMPTS. Actual failures still become terminal in recordFailure.
export async function findCandidate(db: D1Database): Promise<JobRow | null> {
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
            AND jobs.attempts <= ?
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

export async function claimCandidate(db: D1Database, candidate: JobRow): Promise<JobRow | null> {
  return db
    .prepare(
      `
      UPDATE snapshot_hydration_jobs
      SET status = 'processing',
          attempts = CASE WHEN status = 'processing' AND attempts = ? THEN attempts ELSE attempts + 1 END,
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
            AND attempts <= ?
            AND updated_at <= datetime('now', ?)
          )
        )
      RETURNING id, target_kind, target_mbid, shard_key, status, attempts
      `,
    )
    .bind(
      MAX_ATTEMPTS,
      candidate.id,
      MAX_ATTEMPTS,
      MAX_ATTEMPTS,
      `-${PROCESSING_LEASE_MINUTES} minutes`,
    )
    .first<JobRow>()
    .then((claimed) => (claimed ? { ...candidate, ...claimed } : null));
}

