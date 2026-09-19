-- Extend the editorial taxonomy for vocal and orchestral credits.
-- These are families only; instrument-specific fichas can be added later.

INSERT OR IGNORE INTO instrument_families
    (slug, name, sound_nature, description, sound_production)
VALUES
    (
        'woodwinds',
        'Madeiras',
        'acoustic',
        'Instrumentos em que uma coluna de ar é posta em vibração por sopro, aresta ou palheta.',
        'O sopro excita uma coluna de ar; a abertura e o fechamento de orifícios alteram suas frequências.'
    ),
    (
        'brass',
        'Metais',
        'acoustic',
        'Instrumentos de sopro cuja coluna de ar é iniciada pela vibração dos lábios.',
        'Os lábios vibram contra o bocal e o tubo ressonante é alterado por válvulas, vara ou chaves.'
    ),
    (
        'voice',
        'Voz',
        'acoustic',
        'Presença vocal documentada em uma gravação, incluindo canto, vocalização e coro.',
        'A vibração das pregas vocais excita o trato vocal, que molda o timbre e a articulação.'
    ),
    (
        'electric-keys',
        'Teclas elétricas e eletrônicas',
        'hybrid',
        'Instrumentos de teclas que dependem de captação, circuitos ou geração eletrônica do som.',
        'O gesto da tecla aciona uma fonte elétrica ou eletrônica que é amplificada, transformada ou sintetizada.'
    );

INSERT OR IGNORE INTO instrument_family_aliases
    (family_slug, source, locale, alias, normalized_alias)
VALUES
    ('woodwinds', 'musicbrainz', 'en', 'flute', 'flute'),
    ('woodwinds', 'musicbrainz', 'en', 'bass clarinet', 'bass clarinet'),
    ('woodwinds', 'musicbrainz', 'en', 'bassoon', 'bassoon'),
    ('woodwinds', 'musicbrainz', 'en', 'alto saxophone', 'alto saxophone'),
    ('woodwinds', 'musicbrainz', 'en', 'baritone saxophone', 'baritone saxophone'),
    ('woodwinds', 'musicbrainz', 'en', 'clarinet', 'clarinet'),
    ('woodwinds', 'musicbrainz', 'en', 'contrabassoon', 'contrabassoon'),
    ('woodwinds', 'musicbrainz', 'en', 'english horn', 'english horn'),
    ('woodwinds', 'musicbrainz', 'en', 'oboe', 'oboe'),
    ('woodwinds', 'musicbrainz', 'en', 'piccolo', 'piccolo'),
    ('woodwinds', 'musicbrainz', 'en', 'recorder', 'recorder'),
    ('woodwinds', 'musicbrainz', 'en', 'saxophone', 'saxophone'),
    ('woodwinds', 'musicbrainz', 'en', 'soprano saxophone', 'soprano saxophone'),
    ('woodwinds', 'musicbrainz', 'en', 'tenor saxophone', 'tenor saxophone'),
    ('brass', 'musicbrainz', 'en', 'brass', 'brass'),
    ('brass', 'musicbrainz', 'en', 'cornet', 'cornet'),
    ('brass', 'musicbrainz', 'en', 'euphonium', 'euphonium'),
    ('brass', 'musicbrainz', 'en', 'flugelhorn', 'flugelhorn'),
    ('brass', 'musicbrainz', 'en', 'french horn', 'french horn'),
    ('brass', 'musicbrainz', 'en', 'horn', 'horn'),
    ('brass', 'musicbrainz', 'en', 'trombone', 'trombone'),
    ('brass', 'musicbrainz', 'en', 'trumpet', 'trumpet'),
    ('brass', 'musicbrainz', 'en', 'tuba', 'tuba'),
    ('voice', 'musicbrainz', 'en', 'voice', 'voice'),
    ('voice', 'musicbrainz', 'en', 'vocal', 'vocal'),
    ('voice', 'musicbrainz', 'en', 'vocals', 'vocals'),
    ('voice', 'musicbrainz', 'en', 'lead vocals', 'lead vocals'),
    ('voice', 'musicbrainz', 'en', 'backing vocals', 'backing vocals'),
    ('voice', 'musicbrainz', 'en', 'background vocals', 'background vocals'),
    ('voice', 'musicbrainz', 'en', 'choir', 'choir'),
    ('voice', 'musicbrainz', 'en', 'chorus', 'chorus'),
    ('voice', 'musicbrainz', 'en', 'singer', 'singer'),
    ('electric-keys', 'musicbrainz', 'en', 'electric piano', 'electric piano'),
    ('electric-keys', 'musicbrainz', 'en', 'digital piano', 'digital piano'),
    ('electric-keys', 'musicbrainz', 'en', 'electric organ', 'electric organ'),
    ('electric-keys', 'musicbrainz', 'en', 'electronic piano', 'electronic piano'),
    ('electric-keys', 'musicbrainz', 'en', 'piano, electric', 'piano electric'),
    ('electric-keys', 'musicbrainz', 'en', 'keyboard', 'keyboard');

INSERT INTO instrument_common_roles (family_slug, role) VALUES
    ('woodwinds', 'melodia'),
    ('woodwinds', 'contracanto'),
    ('woodwinds', 'textura'),
    ('brass', 'melodia'),
    ('brass', 'ataque'),
    ('brass', 'sustentação'),
    ('voice', 'melodia'),
    ('voice', 'texto'),
    ('voice', 'camada'),
    ('electric-keys', 'harmonia'),
    ('electric-keys', 'melodia'),
    ('electric-keys', 'camada');

INSERT INTO catalog_versions
    (version, methodology_version, description, published_at)
VALUES
    ('0.1.6', '0.3.0',
     'Famílias de madeiras, metais, voz e teclas elétricas e eletrônicas.',
     '2026-09-14 00:00:00');
