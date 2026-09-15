-- Editorial publication metadata and citations for the base resource text.
-- Editorial revisions are data releases; schema changes remain migrations.

CREATE TABLE IF NOT EXISTS editorial_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision TEXT NOT NULL UNIQUE,
    manifest_hash TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    published_by TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('staging', 'active', 'superseded')),
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_editorial_publication_active
    ON editorial_publications(status)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS editorial_resource_reviews (
    resource_type TEXT NOT NULL CHECK (resource_type IN ('instrument', 'family')),
    resource_slug TEXT NOT NULL,
    source_metadata_verified INTEGER NOT NULL DEFAULT 0
        CHECK (source_metadata_verified IN (0, 1)),
    claim_support_verified INTEGER NOT NULL DEFAULT 0
        CHECK (claim_support_verified IN (0, 1)),
    reviewed_at TEXT,
    reviewer TEXT,
    editorial_note TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (resource_type, resource_slug)
);

CREATE TABLE IF NOT EXISTS editorial_text_citations (
    resource_type TEXT NOT NULL CHECK (resource_type IN ('instrument', 'family')),
    resource_slug TEXT NOT NULL,
    field TEXT NOT NULL CHECK (field IN ('description', 'sound_production')),
    source_id TEXT NOT NULL REFERENCES editorial_sources(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (resource_type, resource_slug, field, source_id)
);

CREATE INDEX IF NOT EXISTS idx_editorial_text_citations_source
    ON editorial_text_citations(source_id);
