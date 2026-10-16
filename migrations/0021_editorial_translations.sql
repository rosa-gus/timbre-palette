-- Text releases are separate from neutral catalog identities and UI dictionaries.
ALTER TABLE editorial_publications ADD COLUMN content_schema_version INTEGER NOT NULL DEFAULT 1;
CREATE TRIGGER editorial_publication_revision_immutable
BEFORE UPDATE OF manifest_hash ON editorial_publications
WHEN OLD.manifest_hash <> NEW.manifest_hash
BEGIN
    SELECT RAISE(ABORT, 'Editorial publication revisions are immutable');
END;

CREATE TABLE editorial_resource_translations (
    resource_type TEXT NOT NULL CHECK (resource_type IN ('instrument', 'family')),
    resource_slug TEXT NOT NULL,
    locale TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    content_revision TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'reviewed', 'published', 'deprecated', 'stale')),
    reviewer TEXT,
    reviewed_at TEXT,
    content_json TEXT NOT NULL CHECK (json_valid(content_json)),
    publication_revision TEXT NOT NULL REFERENCES editorial_publications(revision),
    PRIMARY KEY (publication_revision, resource_type, resource_slug, locale)
);
CREATE TABLE editorial_block_translations (
    publication_revision TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_slug TEXT NOT NULL,
    locale TEXT NOT NULL,
    block_id TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    review_json TEXT NOT NULL CHECK (json_valid(review_json)),
    PRIMARY KEY (publication_revision, resource_type, resource_slug, locale, block_id),
    FOREIGN KEY (publication_revision, resource_type, resource_slug, locale)
        REFERENCES editorial_resource_translations(publication_revision, resource_type, resource_slug, locale)
);
CREATE TABLE editorial_translation_history (
    publication_revision TEXT NOT NULL REFERENCES editorial_publications(revision),
    resource_type TEXT NOT NULL,
    resource_slug TEXT NOT NULL,
    locale TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    content_revision TEXT NOT NULL,
    snapshot_json TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    PRIMARY KEY (publication_revision, resource_type, resource_slug, locale)
);
