-- Make queue publication recoverable without coupling the HTTP request to the
-- lifetime of a Queue delivery. `status` remains the job lifecycle; the
-- dispatch columns form a small D1-backed outbox state machine.

ALTER TABLE enrichment_jobs ADD COLUMN dispatch_status TEXT NOT NULL DEFAULT 'none'
    CHECK (dispatch_status IN ('none', 'pending', 'sending', 'queued', 'failed'));
ALTER TABLE enrichment_jobs ADD COLUMN generation INTEGER NOT NULL DEFAULT 1
    CHECK (generation > 0);
ALTER TABLE enrichment_jobs ADD COLUMN dispatch_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE enrichment_jobs ADD COLUMN processing_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE enrichment_jobs ADD COLUMN next_dispatch_at TEXT;
ALTER TABLE enrichment_jobs ADD COLUMN dispatch_lease_until TEXT;
ALTER TABLE enrichment_jobs ADD COLUMN queued_at TEXT;
ALTER TABLE enrichment_jobs ADD COLUMN processing_started_at TEXT;
ALTER TABLE enrichment_jobs ADD COLUMN processing_lease_until TEXT;
ALTER TABLE enrichment_jobs ADD COLUMN message_id TEXT;
ALTER TABLE enrichment_jobs ADD COLUMN terminal_reason_code TEXT;
ALTER TABLE enrichment_jobs ADD COLUMN terminal_detail TEXT;
ALTER TABLE enrichment_jobs ADD COLUMN dispatch_error TEXT;

-- Existing local rows need to be picked up by the sweeper.
UPDATE enrichment_jobs
SET dispatch_status = CASE status
    WHEN 'pending' THEN 'pending'
    WHEN 'failed' THEN 'failed'
    ELSE 'none'
END,
    processing_attempts = attempts;

UPDATE enrichment_jobs
SET terminal_reason_code = 'ambiguous_match'
WHERE status = 'ambiguous' AND terminal_reason_code IS NULL;

UPDATE enrichment_jobs
SET terminal_reason_code = 'migrated_terminal'
WHERE status = 'terminal' AND terminal_reason_code IS NULL;

CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_dispatch
    ON enrichment_jobs(dispatch_status, next_dispatch_at, status, updated_at);

-- Redelivery must not create a second logical identity-match record even when
-- two Queue deliveries race before either one observes the other.
DELETE FROM identity_matches
WHERE id NOT IN (
    SELECT MIN(id)
    FROM identity_matches
    GROUP BY recording_id, method, ifnull(source_mbid, ''), ifnull(source_entity_type, ''), resolver_version
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_identity_matches_idempotency
    ON identity_matches(
        recording_id,
        method,
        ifnull(source_mbid, ''),
        ifnull(source_entity_type, ''),
        resolver_version
    );
