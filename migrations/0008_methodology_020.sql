-- Publish a catalog projection compatible with methodology 0.2.0.
-- The taxonomy itself is unchanged; the version records the compatibility
-- boundary used by palette reports after the Phase 4 calculation changes.
ALTER TABLE instruments
    ADD COLUMN discovery_eligible INTEGER NOT NULL DEFAULT 0
    CHECK (discovery_eligible IN (0, 1));

INSERT INTO catalog_versions
    (version, methodology_version, description, published_at)
VALUES
    ('0.1.4', '0.2.0',
     'Projeção do catálogo compatível com os limiares, claims familiares e cálculo da metodologia 0.2.0.',
     '2026-09-12 00:03:00');
