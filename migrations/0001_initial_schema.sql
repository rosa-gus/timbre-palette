-- Initial schema for Timbre Palette (Cloudflare D1 / SQLite)
PRAGMA foreign_keys = ON;

-- =============================================================================
-- Taxonomy and Editorial Catalog
-- =============================================================================

CREATE TABLE IF NOT EXISTS instrument_families (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sound_nature TEXT NOT NULL CHECK (sound_nature IN ('acoustic', 'electric', 'electronic', 'sampled', 'hybrid')),
    description TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT '',
    sound_production TEXT NOT NULL DEFAULT '',
    curiosity TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS instruments (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    family_slug TEXT NOT NULL REFERENCES instrument_families(slug) ON DELETE RESTRICT,
    sound_nature TEXT NOT NULL CHECK (sound_nature IN ('acoustic', 'electric', 'electronic', 'sampled', 'hybrid')),
    description TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT '',
    sound_production TEXT NOT NULL DEFAULT '',
    curiosity TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_instruments_family_slug ON instruments(family_slug);

CREATE TABLE IF NOT EXISTS instrument_common_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_slug TEXT REFERENCES instruments(slug) ON DELETE CASCADE,
    family_slug TEXT REFERENCES instrument_families(slug) ON DELETE CASCADE,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK ((instrument_slug IS NOT NULL AND family_slug IS NULL) OR (instrument_slug IS NULL AND family_slug IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_common_roles_instrument ON instrument_common_roles(instrument_slug);
CREATE INDEX IF NOT EXISTS idx_common_roles_family ON instrument_common_roles(family_slug);

CREATE TABLE IF NOT EXISTS instrument_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_slug TEXT NOT NULL,
    target_slug TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_slug, target_slug)
);

CREATE INDEX IF NOT EXISTS idx_instrument_relations_source ON instrument_relations(source_slug);

CREATE TABLE IF NOT EXISTS instrument_slug_aliases (
    alias_slug TEXT PRIMARY KEY,
    canonical_slug TEXT NOT NULL REFERENCES instruments(slug) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS family_slug_aliases (
    alias_slug TEXT PRIMARY KEY,
    canonical_slug TEXT NOT NULL REFERENCES instrument_families(slug) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS instrument_external_identifiers (
    instrument_slug TEXT NOT NULL REFERENCES instruments(slug) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('musicbrainz', 'discogs')),
    external_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_instrument_external_identifiers_slug
    ON instrument_external_identifiers(instrument_slug);

CREATE TABLE IF NOT EXISTS instrument_aliases (
    instrument_slug TEXT NOT NULL REFERENCES instruments(slug) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('musicbrainz', 'discogs', 'editorial')),
    locale TEXT NOT NULL DEFAULT 'en',
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source, locale, normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_instrument_aliases_slug
    ON instrument_aliases(instrument_slug);

-- =============================================================================
-- Recordings, Identifiers, and Identity Matching
-- =============================================================================

CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    canonical_mbid TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_recordings_artist_title ON recordings(artist, title);
CREATE INDEX IF NOT EXISTS idx_recordings_canonical_mbid ON recordings(canonical_mbid);

CREATE TABLE IF NOT EXISTS recording_identifiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('lastfm', 'musicbrainz', 'discogs')),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('recording', 'track', 'release')),
    external_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, entity_type, external_id)
);

CREATE INDEX IF NOT EXISTS idx_recording_identifiers_lookup ON recording_identifiers(source, entity_type, external_id);
CREATE INDEX IF NOT EXISTS idx_recording_identifiers_recording_id ON recording_identifiers(recording_id);

CREATE TABLE IF NOT EXISTS identity_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    method TEXT NOT NULL CHECK (method IN ('mbid_recording', 'mbid_track_converted', 'text_search_exact', 'text_search_normalized', 'manual_curation')),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    resolver_version TEXT NOT NULL,
    source_artist TEXT,
    source_title TEXT,
    source_mbid TEXT,
    source_entity_type TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_identity_matches_recording_id ON identity_matches(recording_id);

-- =============================================================================
-- Claims and Evidences
-- =============================================================================

CREATE TABLE IF NOT EXISTS instrument_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    instrument_slug TEXT NOT NULL REFERENCES instruments(slug) ON DELETE RESTRICT,
    confidence_level TEXT NOT NULL CHECK (confidence_level IN ('documented', 'editorially_verified', 'release_context', 'tentative', 'estimated', 'unknown')),
    performer TEXT,
    role TEXT,
    prominence REAL NOT NULL DEFAULT 1.0 CHECK (prominence >= 0.0 AND prominence <= 1.0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_instrument_claims_recording_id ON instrument_claims(recording_id);
CREATE INDEX IF NOT EXISTS idx_instrument_claims_instrument_slug ON instrument_claims(instrument_slug);

CREATE TABLE IF NOT EXISTS evidence_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL REFERENCES instrument_claims(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('musicbrainz', 'discogs', 'editorial', 'acoustic_inference')),
    source_url TEXT,
    original_credit TEXT,
    scope TEXT NOT NULL CHECK (scope IN ('recording', 'track', 'release')),
    source_quality TEXT,
    verified_at TEXT,
    editorial_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_evidence_items_claim_id ON evidence_items(claim_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_instrument_claims_idempotency
    ON instrument_claims(
        recording_id,
        instrument_slug,
        ifnull(performer, ''),
        ifnull(role, '')
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_items_idempotency
    ON evidence_items(
        claim_id,
        source,
        ifnull(source_url, ''),
        ifnull(original_credit, ''),
        scope
    );

CREATE TABLE IF NOT EXISTS instrument_credit_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('musicbrainz', 'discogs', 'editorial')),
    instrument_mbid TEXT NOT NULL DEFAULT '',
    instrument_name TEXT NOT NULL,
    instrument_slug TEXT REFERENCES instruments(slug) ON DELETE SET NULL,
    performer TEXT NOT NULL DEFAULT '',
    original_credit TEXT,
    scope TEXT NOT NULL CHECK (scope IN ('recording', 'track', 'release')),
    source_url TEXT,
    resolution_method TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'reviewed', 'promoted', 'rejected')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(recording_id, source, instrument_mbid, instrument_name, performer)
);

CREATE INDEX IF NOT EXISTS idx_instrument_credit_candidates_recording
    ON instrument_credit_candidates(recording_id, status);

-- =============================================================================
-- Enrichment Queue & State Tracking
-- =============================================================================

CREATE TABLE IF NOT EXISTS enrichment_state (
    recording_id INTEGER PRIMARY KEY REFERENCES recordings(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'skipped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_error TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_enrichment_state_status ON enrichment_state(status);

CREATE TABLE IF NOT EXISTS enrichment_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    source_mbid TEXT,
    source_entity_type TEXT CHECK (source_entity_type IN ('track', 'recording', 'unknown')),
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    recording_id INTEGER REFERENCES recordings(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'ambiguous')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_attempt_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status
    ON enrichment_jobs(status, updated_at);

-- =============================================================================
-- Catalog Versioning
-- =============================================================================

CREATE TABLE IF NOT EXISTS catalog_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL UNIQUE,
    methodology_version TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT (datetime('now'))
);
