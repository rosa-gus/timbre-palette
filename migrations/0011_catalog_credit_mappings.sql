-- Complete the controlled MusicBrainz -> catalog projection for future
-- enrichment runs.
--
-- The mappings are explicit. Names that are ambiguous or have no matching
-- editorial family remain pending for review; they are not slugified or
-- guessed from text.

INSERT OR IGNORE INTO instrument_aliases
    (instrument_slug, source, locale, alias, normalized_alias)
VALUES
    ('drums', 'musicbrainz', 'en', 'drums (drum set)', 'drums drum set'),
    ('electric-bass', 'musicbrainz', 'en', 'electric bass guitar', 'electric bass guitar');

INSERT OR IGNORE INTO instrument_family_aliases
    (family_slug, source, locale, alias, normalized_alias)
VALUES
    ('plucked-strings', 'musicbrainz', 'en', '12 string guitar', '12 string guitar'),
    ('plucked-strings', 'musicbrainz', 'en', 'banjo', 'banjo'),
    ('plucked-strings', 'musicbrainz', 'en', 'baritone guitar', 'baritone guitar'),
    ('plucked-strings', 'musicbrainz', 'en', 'electric sitar', 'electric sitar'),
    ('plucked-strings', 'musicbrainz', 'en', 'mandocello', 'mandocello'),
    ('plucked-strings', 'musicbrainz', 'en', 'mandolin', 'mandolin'),
    ('plucked-strings', 'musicbrainz', 'en', 'pedal steel guitar', 'pedal steel guitar'),
    ('plucked-strings', 'musicbrainz', 'en', 'tenor guitar', 'tenor guitar'),
    ('percussion', 'musicbrainz', 'en', 'membranophone', 'membranophone'),
    ('percussion', 'musicbrainz', 'en', 'percussion', 'percussion'),
    ('bowed-strings', 'musicbrainz', 'en', 'double bass', 'double bass'),
    ('bowed-strings', 'musicbrainz', 'en', 'sarangi', 'sarangi'),
    ('bowed-strings', 'musicbrainz', 'en', 'viola', 'viola'),
    ('bowed-strings', 'musicbrainz', 'en', 'violin', 'violin'),
    ('acoustic-keys', 'musicbrainz', 'en', 'reed organ', 'reed organ'),
    ('percussion', 'musicbrainz', 'en', 'vibraphone', 'vibraphone');
INSERT INTO catalog_versions
    (version, methodology_version, description, published_at)
VALUES
    ('0.1.5', '0.2.0',
     'Aliases explícitos do MusicBrainz para novos créditos do enriquecimento.',
     '2026-09-14 00:00:00');
