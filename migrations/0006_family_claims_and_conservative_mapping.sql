-- Instrument claims may reference a specific instrument or a family when
-- the evidence does not support greater precision.
--
-- Previous migrations are immutable. The tables are rebuilt with foreign keys
-- disabled only during the swap to preserve claim IDs and evidence_items
-- references.

PRAGMA foreign_keys = OFF;

CREATE TABLE instrument_claims_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    instrument_slug TEXT REFERENCES instruments(slug) ON DELETE RESTRICT,
    family_slug TEXT REFERENCES instrument_families(slug) ON DELETE RESTRICT,
    confidence_level TEXT NOT NULL CHECK (
        confidence_level IN (
            'documented', 'editorially_verified', 'release_context',
            'tentative', 'estimated', 'unknown'
        )
    ),
    performer TEXT,
    role TEXT,
    prominence REAL NOT NULL DEFAULT 1.0 CHECK (prominence >= 0.0 AND prominence <= 1.0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (
        (instrument_slug IS NOT NULL AND family_slug IS NULL)
        OR (instrument_slug IS NULL AND family_slug IS NOT NULL)
    )
);

INSERT INTO instrument_claims_v2
    (id, recording_id, instrument_slug, confidence_level, performer, role,
     prominence, created_at, updated_at)
SELECT id, recording_id, instrument_slug, confidence_level, performer, role,
       prominence, created_at, updated_at
FROM instrument_claims;

DROP TABLE instrument_claims;
ALTER TABLE instrument_claims_v2 RENAME TO instrument_claims;

CREATE INDEX IF NOT EXISTS idx_instrument_claims_recording_id
    ON instrument_claims(recording_id);
CREATE INDEX IF NOT EXISTS idx_instrument_claims_instrument_slug
    ON instrument_claims(instrument_slug);
CREATE INDEX IF NOT EXISTS idx_instrument_claims_family_slug
    ON instrument_claims(family_slug);
CREATE UNIQUE INDEX IF NOT EXISTS idx_instrument_claims_instrument_idempotency
    ON instrument_claims(
        recording_id,
        instrument_slug,
        ifnull(performer, ''),
        ifnull(role, '')
    )
    WHERE instrument_slug IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_instrument_claims_family_idempotency
    ON instrument_claims(
        recording_id,
        family_slug,
        ifnull(performer, ''),
        ifnull(role, '')
    )
    WHERE family_slug IS NOT NULL;

ALTER TABLE instrument_credit_candidates
    ADD COLUMN family_slug TEXT REFERENCES instrument_families(slug) ON DELETE SET NULL;
ALTER TABLE instrument_credit_candidates
    ADD COLUMN queue_priority INTEGER NOT NULL DEFAULT 0;
ALTER TABLE instrument_credit_candidates
    ADD COLUMN queue_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_instrument_credit_candidates_queue
    ON instrument_credit_candidates(status, queue_priority DESC, updated_at, id);

CREATE TABLE instrument_family_aliases (
    family_slug TEXT NOT NULL REFERENCES instrument_families(slug) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('musicbrainz', 'discogs', 'editorial')),
    locale TEXT NOT NULL DEFAULT 'en',
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source, locale, normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_instrument_family_aliases_slug
    ON instrument_family_aliases(family_slug);

-- Names that do not support a specific electrical configuration are retained
-- only at family level. "bass" remains unresolved because it can denote
-- distinct instruments or even a vocal register.
DELETE FROM instrument_aliases
WHERE source = 'musicbrainz'
  AND locale = 'en'
  AND normalized_alias IN ('guitar', 'drum', 'drums', 'bass');

INSERT INTO instrument_family_aliases
    (family_slug, source, locale, alias, normalized_alias)
VALUES
    ('plucked-strings', 'musicbrainz', 'en', 'guitar', 'guitar'),
    ('percussion', 'musicbrainz', 'en', 'drum', 'drum'),
    ('percussion', 'musicbrainz', 'en', 'drums', 'drums');

-- Reclassify data produced solely by the old generic aliases. The evidence,
-- source URL and original credit remain attached to the same claim id.
UPDATE instrument_claims
SET instrument_slug = NULL,
    family_slug = CASE
        WHEN lower(ifnull(instrument_slug, '')) = 'electric-guitar'
            THEN 'plucked-strings'
        WHEN lower(ifnull(instrument_slug, '')) = 'drums'
            THEN 'percussion'
    END,
    updated_at = datetime('now')
WHERE id IN (
    SELECT ic.id
    FROM instrument_claims AS ic
    JOIN instrument_credit_candidates AS candidate
      ON candidate.recording_id = ic.recording_id
     AND candidate.instrument_slug = ic.instrument_slug
     AND ifnull(candidate.performer, '') = ifnull(ic.performer, '')
    WHERE candidate.source = 'musicbrainz'
      AND candidate.resolution_method = 'alias'
      AND lower(candidate.instrument_name) IN ('guitar', 'drum', 'drums')
      AND ic.instrument_slug IN ('electric-guitar', 'drums')
);

UPDATE instrument_claims
SET confidence_level = 'unknown',
    updated_at = datetime('now')
WHERE id IN (
    SELECT ic.id
    FROM instrument_claims AS ic
    JOIN instrument_credit_candidates AS candidate
      ON candidate.recording_id = ic.recording_id
     AND candidate.instrument_slug = ic.instrument_slug
     AND ifnull(candidate.performer, '') = ifnull(ic.performer, '')
    WHERE candidate.source = 'musicbrainz'
      AND candidate.resolution_method = 'alias'
      AND lower(candidate.instrument_name) = 'bass'
      AND ic.instrument_slug = 'electric-bass'
);

UPDATE instrument_credit_candidates
SET instrument_slug = NULL,
    family_slug = CASE
        WHEN lower(instrument_name) = 'guitar' THEN 'plucked-strings'
        WHEN lower(instrument_name) IN ('drum', 'drums') THEN 'percussion'
        ELSE NULL
    END,
    resolution_method = CASE
        WHEN lower(instrument_name) IN ('guitar', 'drum', 'drums')
            THEN 'family_alias'
        ELSE NULL
    END,
    status = CASE
        WHEN lower(instrument_name) = 'bass' THEN 'pending'
        ELSE status
    END,
    queue_reason = CASE
        WHEN lower(instrument_name) = 'bass'
            THEN 'generic_name_requires_instrument_or_family_review'
        ELSE queue_reason
    END,
    updated_at = datetime('now')
WHERE source = 'musicbrainz'
  AND resolution_method = 'alias'
  AND lower(instrument_name) IN ('guitar', 'drum', 'drums', 'bass');

INSERT INTO catalog_versions
    (version, methodology_version, description, published_at)
VALUES
    ('0.1.3', '0.1.0',
     'Claims familiares, aliases genéricos conservadores e fila editorial de créditos não mapeados.',
     '2026-09-12 00:02:00');

PRAGMA foreign_keys = ON;
