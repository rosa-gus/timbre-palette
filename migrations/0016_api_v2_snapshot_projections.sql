-- API v2 uses compact, snapshot-versioned D1 projections.  R2 remains the
-- immutable source; only targets requested by an analysis are materialized.

ALTER TABLE musicbrainz_credit_index_snapshots
    ADD COLUMN object_prefix TEXT NOT NULL DEFAULT 'musicbrainz/instrument-credits/v2';

ALTER TABLE musicbrainz_credit_index_snapshots
    ADD COLUMN methodology_version TEXT NOT NULL DEFAULT 'artist-vocabulary-candidate-1';

CREATE TABLE IF NOT EXISTS snapshot_track_aliases (
    snapshot_version TEXT NOT NULL
        REFERENCES musicbrainz_credit_index_snapshots(snapshot_version)
        ON DELETE CASCADE,
    track_mbid TEXT NOT NULL,
    recording_mbid TEXT NOT NULL,
    hydrated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (snapshot_version, track_mbid)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_track_aliases_recording
    ON snapshot_track_aliases(snapshot_version, recording_mbid);

CREATE TABLE IF NOT EXISTS snapshot_recordings (
    snapshot_version TEXT NOT NULL
        REFERENCES musicbrainz_credit_index_snapshots(snapshot_version)
        ON DELETE CASCADE,
    recording_mbid TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'complete', 'complete_empty', 'failed')),
    credit_count INTEGER NOT NULL DEFAULT 0 CHECK (credit_count >= 0),
    mapped_credit_count INTEGER NOT NULL DEFAULT 0 CHECK (mapped_credit_count >= 0),
    discarded_credit_count INTEGER NOT NULL DEFAULT 0 CHECK (discarded_credit_count >= 0),
    last_error TEXT,
    hydrated_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (snapshot_version, recording_mbid)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_recordings_status
    ON snapshot_recordings(snapshot_version, status, updated_at);

CREATE TABLE IF NOT EXISTS snapshot_recording_instruments (
    snapshot_version TEXT NOT NULL,
    recording_mbid TEXT NOT NULL,
    instrument_slug TEXT NOT NULL REFERENCES instruments(slug) ON DELETE RESTRICT,
    family_slug TEXT NOT NULL REFERENCES instrument_families(slug) ON DELETE RESTRICT,
    scope TEXT NOT NULL CHECK (scope IN ('recording', 'track', 'release')),
    credit_count INTEGER NOT NULL DEFAULT 1 CHECK (credit_count > 0),
    performer_count INTEGER NOT NULL DEFAULT 0 CHECK (performer_count >= 0),
    source_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (snapshot_version, recording_mbid, instrument_slug, scope),
    FOREIGN KEY (snapshot_version, recording_mbid)
        REFERENCES snapshot_recordings(snapshot_version, recording_mbid)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_snapshot_recording_instruments_lookup
    ON snapshot_recording_instruments(snapshot_version, recording_mbid, scope);

CREATE TABLE IF NOT EXISTS snapshot_artists (
    snapshot_version TEXT NOT NULL
        REFERENCES musicbrainz_credit_index_snapshots(snapshot_version)
        ON DELETE CASCADE,
    artist_mbid TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'complete', 'complete_empty', 'failed')),
    entry_count INTEGER NOT NULL DEFAULT 0 CHECK (entry_count >= 0),
    mapped_entry_count INTEGER NOT NULL DEFAULT 0 CHECK (mapped_entry_count >= 0),
    discarded_entry_count INTEGER NOT NULL DEFAULT 0 CHECK (discarded_entry_count >= 0),
    last_error TEXT,
    hydrated_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (snapshot_version, artist_mbid)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_artists_status
    ON snapshot_artists(snapshot_version, status, updated_at);

CREATE TABLE IF NOT EXISTS snapshot_artist_instruments (
    snapshot_version TEXT NOT NULL,
    artist_mbid TEXT NOT NULL,
    instrument_slug TEXT NOT NULL REFERENCES instruments(slug) ON DELETE RESTRICT,
    family_slug TEXT NOT NULL REFERENCES instrument_families(slug) ON DELETE RESTRICT,
    distinct_recordings INTEGER NOT NULL CHECK (distinct_recordings >= 0),
    documented_recordings INTEGER NOT NULL CHECK (documented_recordings >= 0),
    prevalence REAL NOT NULL CHECK (prevalence >= 0 AND prevalence <= 1),
    evidence_quality REAL NOT NULL DEFAULT 1.0
        CHECK (evidence_quality >= 0 AND evidence_quality <= 1),
    source_scope TEXT NOT NULL DEFAULT 'recording'
        CHECK (source_scope IN ('recording', 'track')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (snapshot_version, artist_mbid, instrument_slug),
    FOREIGN KEY (snapshot_version, artist_mbid)
        REFERENCES snapshot_artists(snapshot_version, artist_mbid)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_snapshot_artist_instruments_lookup
    ON snapshot_artist_instruments(snapshot_version, artist_mbid, family_slug);

CREATE TABLE IF NOT EXISTS snapshot_hydration_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_version TEXT NOT NULL
        REFERENCES musicbrainz_credit_index_snapshots(snapshot_version)
        ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('track', 'recording', 'artist')),
    target_mbid TEXT NOT NULL,
    shard_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'complete', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    next_attempt_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (snapshot_version, target_kind, target_mbid)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_hydration_due
    ON snapshot_hydration_jobs(status, next_attempt_at, updated_at);

CREATE INDEX IF NOT EXISTS idx_snapshot_hydration_partition
    ON snapshot_hydration_jobs(snapshot_version, target_kind, shard_key, status);
