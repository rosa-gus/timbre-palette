-- Runtime budget guard for R2 Class B reads made by the offline credit index.
-- The period key is intentionally supplied by deployment configuration so it
-- can be aligned manually with the account billing cycle. A new period key
-- is required to reset the budget; this is fail-closed by design.

CREATE TABLE IF NOT EXISTS musicbrainz_credit_index_usage (
    period_key TEXT PRIMARY KEY,
    read_limit INTEGER NOT NULL CHECK (read_limit >= 0),
    reads_reserved INTEGER NOT NULL DEFAULT 0 CHECK (reads_reserved >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_musicbrainz_credit_index_usage_updated
    ON musicbrainz_credit_index_usage(updated_at);
