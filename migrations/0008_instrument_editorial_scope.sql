-- Historical origins are outside the current product. Remove their citations
-- and text, then remove the obsolete taxonomy columns.
DELETE FROM editorial_content_citations
WHERE block_id IN (SELECT id FROM editorial_content_blocks WHERE section_kind = 'origin');
DELETE FROM editorial_content_blocks WHERE section_kind = 'origin';
ALTER TABLE instruments DROP COLUMN origin;
ALTER TABLE instrument_families DROP COLUMN origin;
ALTER TABLE instruments DROP COLUMN curiosity;
ALTER TABLE instrument_families DROP COLUMN curiosity;

-- Curiosity remains optional: absence of a block is a valid instrument sheet.
CREATE TABLE instrument_further_reading (
    id TEXT PRIMARY KEY,
    instrument_slug TEXT REFERENCES instruments(slug) ON DELETE CASCADE,
    family_slug TEXT REFERENCES instrument_families(slug) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    url TEXT NOT NULL CHECK (url LIKE 'https://%' OR url LIKE 'http://%'),
    publisher TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'reviewed', 'published', 'deprecated')),
    reviewer TEXT,
    reviewed_at TEXT,
    editorial_note TEXT,
    CHECK ((instrument_slug IS NOT NULL AND family_slug IS NULL)
        OR (instrument_slug IS NULL AND family_slug IS NOT NULL))
);

CREATE INDEX idx_further_reading_instrument ON instrument_further_reading(instrument_slug, status);
CREATE INDEX idx_further_reading_family ON instrument_further_reading(family_slug, status);
