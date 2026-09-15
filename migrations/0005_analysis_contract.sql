-- Public analysis states need to distinguish a terminal enrichment failure
-- from a retryable one. Existing jobs remain valid and keep their status.

PRAGMA foreign_keys = OFF;

ALTER TABLE enrichment_jobs RENAME TO enrichment_jobs_before_analysis_contract;

CREATE TABLE enrichment_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    source_mbid TEXT,
    source_entity_type TEXT CHECK (source_entity_type IN ('track', 'recording', 'unknown')),
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    recording_id INTEGER REFERENCES recordings(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'ambiguous', 'terminal')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_attempt_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO enrichment_jobs
    (id, job_key, source_mbid, source_entity_type, artist, title, recording_id,
     status, attempts, last_error, last_attempt_at, completed_at, created_at, updated_at)
SELECT id, job_key, source_mbid, source_entity_type, artist, title, recording_id,
       status, attempts, last_error, last_attempt_at, completed_at, created_at, updated_at
FROM enrichment_jobs_before_analysis_contract;

DROP TABLE enrichment_jobs_before_analysis_contract;

CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status
    ON enrichment_jobs(status, updated_at);

PRAGMA foreign_keys = ON;
