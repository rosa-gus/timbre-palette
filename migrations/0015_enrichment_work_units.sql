-- Group recording jobs into one durable Queue work unit. D1 remains the
-- source of truth; the Queue message carries only the work-unit identity.

CREATE TABLE IF NOT EXISTS enrichment_work_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_key TEXT NOT NULL UNIQUE,
    generation INTEGER NOT NULL DEFAULT 1 CHECK (generation > 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'failed', 'completed',
                          'recovery_required', 'terminal')),
    item_count INTEGER NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    attempts INTEGER NOT NULL DEFAULT 0,
    processing_attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_attempt_at TEXT,
    completed_at TEXT,
    dispatch_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (dispatch_status IN ('none', 'pending', 'sending', 'queued', 'failed')),
    dispatch_attempts INTEGER NOT NULL DEFAULT 0,
    next_dispatch_at TEXT,
    dispatch_lease_until TEXT,
    queued_at TEXT,
    processing_started_at TEXT,
    processing_lease_until TEXT,
    message_id TEXT,
    terminal_reason_code TEXT,
    terminal_detail TEXT,
    dispatch_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE enrichment_jobs ADD COLUMN work_unit_key TEXT;

CREATE TABLE IF NOT EXISTS enrichment_work_unit_items (
    work_unit_id INTEGER NOT NULL REFERENCES enrichment_work_units(id) ON DELETE CASCADE,
    job_key TEXT NOT NULL UNIQUE REFERENCES enrichment_jobs(job_key) ON DELETE CASCADE,
    item_order INTEGER NOT NULL CHECK (item_order >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (work_unit_id, job_key)
);

CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_work_unit
    ON enrichment_jobs(work_unit_key, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_enrichment_work_units_dispatch
    ON enrichment_work_units(dispatch_status, next_dispatch_at, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_enrichment_work_unit_items_order
    ON enrichment_work_unit_items(work_unit_id, item_order);

