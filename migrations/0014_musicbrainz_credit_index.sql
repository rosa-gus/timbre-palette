-- Offline MusicBrainz credit-index provenance.
--
-- The large snapshot stays in R2. D1 keeps only the normalized evidence that
-- was actually needed by the product, plus the manifest metadata needed to
-- explain which snapshot produced it.

ALTER TABLE instrument_credit_candidates ADD COLUMN performer_mbid TEXT;
ALTER TABLE instrument_credit_candidates ADD COLUMN snapshot_version TEXT;
ALTER TABLE instrument_credit_candidates ADD COLUMN attributes_json TEXT;
ALTER TABLE evidence_items ADD COLUMN snapshot_version TEXT;

CREATE TABLE IF NOT EXISTS musicbrainz_credit_index_snapshots (
    snapshot_version TEXT PRIMARY KEY,
    index_schema_version TEXT NOT NULL,
    source_url TEXT NOT NULL,
    license TEXT NOT NULL,
    attribution TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    credit_count INTEGER NOT NULL DEFAULT 0 CHECK (credit_count >= 0),
    status TEXT NOT NULL DEFAULT 'staging'
        CHECK (status IN ('staging', 'active', 'superseded')),
    generated_at TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_musicbrainz_credit_index_active
    ON musicbrainz_credit_index_snapshots(status)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_credit_candidates_snapshot
    ON instrument_credit_candidates(snapshot_version, recording_id);

CREATE INDEX IF NOT EXISTS idx_evidence_items_snapshot
    ON evidence_items(snapshot_version, claim_id);
