-- Prepared album catalog with expanded data collection.
-- Editorial identity (album/release/track) is kept separate from the
-- instrumental evidence published in instrument_claims.

CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_mbid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS album_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_mbid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    artist_mbid TEXT,
    first_release_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS album_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    album_group_id INTEGER NOT NULL REFERENCES album_groups(id) ON DELETE CASCADE,
    canonical_mbid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    country TEXT,
    release_date TEXT,
    status TEXT,
    source_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_album_releases_group
    ON album_releases(album_group_id, release_date);

CREATE TABLE IF NOT EXISTS album_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    album_release_id INTEGER NOT NULL REFERENCES album_releases(id) ON DELETE CASCADE,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE RESTRICT,
    disc_number INTEGER NOT NULL DEFAULT 1 CHECK (disc_number > 0),
    position INTEGER NOT NULL CHECK (position > 0),
    title TEXT NOT NULL,
    length_ms INTEGER,
    source_mbid TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(album_release_id, disc_number, position)
);

CREATE INDEX IF NOT EXISTS idx_album_tracks_recording
    ON album_tracks(recording_id);

CREATE TABLE IF NOT EXISTS source_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('musicbrainz', 'discogs', 'editorial')),
    entity_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    source_url TEXT NOT NULL,
    body_json TEXT,
    body_hash TEXT,
    parser_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'fetched'
        CHECK (status IN ('pending', 'fetched', 'not_found', 'unavailable', 'invalid')),
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    error TEXT,
    UNIQUE(source, entity_type, external_id, request_key, parser_version)
);

CREATE INDEX IF NOT EXISTS idx_source_documents_external
    ON source_documents(source, entity_type, external_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS credit_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    album_release_id INTEGER REFERENCES album_releases(id) ON DELETE SET NULL,
    source_document_id INTEGER NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    instrument_mbid TEXT NOT NULL DEFAULT '',
    instrument_name TEXT NOT NULL DEFAULT '',
    performer TEXT NOT NULL DEFAULT '',
    original_credit TEXT,
    scope TEXT NOT NULL CHECK (scope IN ('recording', 'track', 'release')),
    production_method TEXT CHECK (production_method IN ('performed', 'programmed', 'sampled', 'unknown')),
    sound_nature TEXT CHECK (sound_nature IN ('acoustic', 'electric', 'electronic', 'sampled', 'hybrid')),
    status TEXT NOT NULL DEFAULT 'observed'
        CHECK (status IN ('observed', 'candidate', 'accepted', 'rejected')),
    observed_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(recording_id, source_document_id, relation_type,
           instrument_mbid, instrument_name, performer, scope)
);

CREATE INDEX IF NOT EXISTS idx_credit_observations_recording
    ON credit_observations(recording_id, status);

CREATE TABLE IF NOT EXISTS catalog_demand (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demand_key TEXT NOT NULL UNIQUE,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    source_mbid TEXT,
    play_weight INTEGER NOT NULL DEFAULT 0 CHECK (play_weight >= 0),
    sightings INTEGER NOT NULL DEFAULT 0 CHECK (sightings >= 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'planned', 'covered', 'ignored')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    next_planned_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_catalog_demand_priority
    ON catalog_demand(status, play_weight DESC, sightings DESC, updated_at);

CREATE TABLE IF NOT EXISTS prepared_album_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_mbid TEXT NOT NULL UNIQUE,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    genre TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'planned', 'collected', 'ignored')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_prepared_album_targets_due
    ON prepared_album_targets(status, priority DESC, updated_at);

CREATE TABLE IF NOT EXISTS catalog_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision TEXT NOT NULL UNIQUE,
    manifest_hash TEXT NOT NULL,
    methodology_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('staging', 'active', 'superseded')),
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_catalog_publication_active
    ON catalog_publications(status)
    WHERE status = 'active';

ALTER TABLE enrichment_jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'recording'
    CHECK (job_type IN ('recording', 'release'));
ALTER TABLE enrichment_jobs ADD COLUMN target_mbid TEXT;
ALTER TABLE enrichment_jobs ADD COLUMN stage TEXT NOT NULL DEFAULT 'source'
    CHECK (stage IN ('identity', 'source', 'observe', 'publish'));

CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_target
    ON enrichment_jobs(job_type, target_mbid, stage, status);

INSERT OR IGNORE INTO catalog_publications
    (revision, manifest_hash, methodology_version, status, published_at)
VALUES ('0.1.4-initial', 'bootstrap', '0.2.0', 'active', datetime('now'));
