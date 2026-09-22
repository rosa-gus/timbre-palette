-- Final runtime contract for the snapshot hydrator.
-- The v2 projection is not production data yet, so the recording projection
-- is rebuilt with an explicit instrument/family subject instead of retaining a
-- compatibility table beside it.

PRAGMA foreign_keys = OFF;

CREATE TABLE snapshot_recording_claims (
    snapshot_version TEXT NOT NULL
        REFERENCES musicbrainz_credit_index_snapshots(snapshot_version)
        ON DELETE CASCADE,
    recording_mbid TEXT NOT NULL,
    claim_level TEXT NOT NULL CHECK (claim_level IN ('instrument', 'family')),
    subject_slug TEXT NOT NULL,
    instrument_slug TEXT REFERENCES instruments(slug) ON DELETE RESTRICT,
    family_slug TEXT NOT NULL REFERENCES instrument_families(slug) ON DELETE RESTRICT,
    scope TEXT NOT NULL CHECK (scope IN ('recording', 'track', 'release')),
    credit_count INTEGER NOT NULL DEFAULT 1 CHECK (credit_count > 0),
    performer_count INTEGER NOT NULL DEFAULT 0 CHECK (performer_count >= 0),
    source_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (snapshot_version, recording_mbid, claim_level, subject_slug, scope),
    FOREIGN KEY (snapshot_version, recording_mbid)
        REFERENCES snapshot_recordings(snapshot_version, recording_mbid)
        ON DELETE CASCADE,
    CHECK (
        (claim_level = 'instrument'
            AND instrument_slug IS NOT NULL
            AND subject_slug = instrument_slug)
        OR
        (claim_level = 'family'
            AND instrument_slug IS NULL
            AND subject_slug = family_slug)
    )
);

INSERT INTO snapshot_recording_claims
    (snapshot_version, recording_mbid, claim_level, subject_slug,
     instrument_slug, family_slug, scope, credit_count, performer_count,
     source_url, created_at)
SELECT snapshot_version,
       recording_mbid,
       'instrument',
       instrument_slug,
       instrument_slug,
       family_slug,
       scope,
       credit_count,
       performer_count,
       source_url,
       created_at
FROM snapshot_recording_instruments;

DROP TABLE snapshot_recording_instruments;
ALTER TABLE snapshot_recording_claims RENAME TO snapshot_recording_instruments;

CREATE INDEX idx_snapshot_recording_instruments_lookup
    ON snapshot_recording_instruments(snapshot_version, recording_mbid, scope);

CREATE INDEX idx_snapshot_recording_instruments_subject
    ON snapshot_recording_instruments(snapshot_version, claim_level, subject_slug);

CREATE TABLE IF NOT EXISTS snapshot_hydrator_usage (
    day_key TEXT PRIMARY KEY,
    d1_writes_reserved INTEGER NOT NULL DEFAULT 0 CHECK (d1_writes_reserved >= 0),
    d1_write_limit INTEGER NOT NULL CHECK (d1_write_limit >= 0),
    r2_reads_reserved INTEGER NOT NULL DEFAULT 0 CHECK (r2_reads_reserved >= 0),
    r2_read_limit INTEGER NOT NULL CHECK (r2_read_limit >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_snapshot_hydration_processing_lease
    ON snapshot_hydration_jobs(status, updated_at);

PRAGMA foreign_keys = ON;
