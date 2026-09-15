-- Seed initial taxonomy and editorial catalog
-- Foundational taxonomy and editorial catalog for the development build.

-- =============================================================================
-- Families
-- =============================================================================

INSERT INTO instrument_families (slug, name, sound_nature, description, origin, sound_production, curiosity) VALUES
(
    'plucked-strings',
    'Cordas dedilhadas',
    'acoustic',
    'Família em que a corda vibra depois de ser puxada com dedos, palheta ou mecanismo equivalente.',
    'Reúne tradições instrumentais de diferentes épocas e regiões.',
    'A corda é deslocada e solta, iniciando uma vibração livre.',
    'O ataque curto deixa evidente o instante em que cada nota começa.'
),
(
    'percussion',
    'Percussão',
    'acoustic',
    'Família de instrumentos acionados principalmente por impacto, agitação ou raspagem.',
    'É uma das formas mais antigas e diversas de produção musical.',
    'Uma superfície ou corpo ressoa depois de receber energia.',
    'Nem toda percussão marca o tempo; muitas criam cor e espaço.'
),
(
    'synthesizers',
    'Sintetizadores',
    'electronic',
    'Instrumentos eletrônicos que constroem ou transformam sinais sonoros.',
    'Desenvolveram-se a partir de experimentos eletrônicos do século XX.',
    'Osciladores, amostras ou outros sinais são moldados eletronicamente.',
    'Um sintetizador pode imitar fontes acústicas ou evitar imitá-las por completo.'
),
(
    'acoustic-keys',
    'Teclas acústicas',
    'acoustic',
    'Instrumentos acústicos acionados por um sistema de teclas.',
    'A família reúne mecanismos de cordas, lâminas e tubos de ar.',
    'A tecla transmite o gesto a outro mecanismo ressonante.',
    'Teclas semelhantes podem acionar fontes sonoras muito diferentes.'
),
(
    'bowed-strings',
    'Cordas friccionadas',
    'acoustic',
    'Cordas mantidas em vibração principalmente pela fricção de um arco.',
    'A família atravessa tradições eruditas e populares de muitas regiões.',
    'O arco adere e solta a corda repetidamente, sustentando o som.',
    'O arco permite prolongar uma nota sem um novo ataque evidente.'
),
(
    'sampled-sounds',
    'Sons sampleados',
    'sampled',
    'Gravações reutilizadas como matéria para uma nova composição.',
    'A prática moderna une técnicas de estúdio, hip-hop e música eletrônica.',
    'Um trecho gravado é recortado, disparado e transformado.',
    'Um sample pode ser reconhecível ou reduzido a uma textura abstrata.'
);

-- =============================================================================
-- Instruments
-- =============================================================================

INSERT INTO instruments (slug, name, family_slug, sound_nature, description, origin, sound_production, curiosity) VALUES
(
    'electric-guitar',
    'Guitarra elétrica',
    'plucked-strings',
    'electric',
    'Instrumento de cordas amplificado e aberto a amplo processamento.',
    'Consolidou-se durante o século XX com a amplificação elétrica.',
    'Captadores convertem a vibração das cordas em sinal elétrico.',
    'Grande parte de sua identidade pode nascer depois dos captadores.'
),
(
    'electric-bass',
    'Baixo elétrico',
    'plucked-strings',
    'electric',
    'Instrumento elétrico de registro grave ligado ao pulso e à harmonia.',
    'Popularizou-se em conjuntos amplificados a partir do século XX.',
    'Captadores transformam a vibração de cordas graves em sinal elétrico.',
    'Uma linha de baixo pode ser sentida fisicamente antes de ser percebida como melodia.'
),
(
    'drums',
    'Bateria',
    'percussion',
    'acoustic',
    'Conjunto de tambores e pratos organizado para um único intérprete.',
    'Sua configuração moderna cresceu com conjuntos populares do século XX.',
    'Baquetas, pedais e mãos acionam superfícies de diferentes materiais.',
    'A bateria reúne vários instrumentos em uma única prática corporal.'
),
(
    'synthesizer',
    'Sintetizador',
    'synthesizers',
    'electronic',
    'Instrumento eletrônico voltado à criação e transformação de timbres.',
    'Resulta de diferentes linhagens de pesquisa eletrônica do século XX.',
    'Sinais são gerados ou reproduzidos e depois moldados por controles.',
    'O mesmo instrumento pode produzir sons percussivos, contínuos ou quase vocais.'
),
(
    'piano',
    'Piano',
    'acoustic-keys',
    'acoustic',
    'Instrumento de teclas em que martelos percutem cordas afinadas.',
    'Sua forma moderna deriva de instrumentos europeus dos séculos XVII e XVIII.',
    'Cada tecla lança um martelo contra uma corda e libera seu abafador.',
    'O gesto é indireto: o pianista não toca as cordas com as mãos.'
),
(
    'cello',
    'Violoncelo',
    'bowed-strings',
    'acoustic',
    'Instrumento de cordas friccionadas de registro grave e médio.',
    'Integra a família moderna do violino desenvolvida na Europa.',
    'O arco ou os dedos colocam suas cordas em vibração.',
    'Seu registro se aproxima de diferentes regiões da voz humana.'
),
(
    'acoustic-guitar',
    'Violão',
    'plucked-strings',
    'acoustic',
    'Instrumento de cordas dedilhadas com caixa de ressonância acústica.',
    'Instrumento de circulação ampla, mantido aqui por sua construção e modo de produção sonora.',
    'As cordas vibram ao serem dedilhadas ou palhetadas; o tampo e a caixa de ressonância irradiam o som.',
    'A mesma ficha cobre usos musicais distintos sem presumir uma origem nacional única.'
),
(
    'cavaquinho',
    'Cavaquinho',
    'plucked-strings',
    'acoustic',
    'Pequeno instrumento de cordas dedilhadas e caixa de ressonância acústica.',
    'Instrumento de circulação ampla, mantido aqui por sua construção e modo de produção sonora.',
    'As cordas dedilhadas ou palhetadas transmitem a vibração ao tampo e à caixa de ressonância.',
    'Seu pequeno corpo não limita seu papel harmônico em conjuntos de diferentes tradições.'
),
(
    'pandeiro',
    'Pandeiro',
    'percussion',
    'acoustic',
    'Tambor de aro com uma membrana e pequenas peças metálicas chamadas soalhas.',
    'Instrumento de circulação ampla, mantido aqui por sua construção e modo de produção sonora.',
    'Golpes e fricção excitam a membrana; o movimento do aro também faz vibrar as soalhas.',
    'Uma mesma execução pode combinar membrana e soalhas como fontes sonoras.'
),
(
    'surdo',
    'Surdo',
    'percussion',
    'acoustic',
    'Tambor de registro grave usado para marcação rítmica em conjuntos de percussão.',
    'Instrumento de circulação ampla, mantido aqui por sua construção e modo de produção sonora.',
    'A percussão da membrana põe em vibração a pele e o ar do corpo ressonante.',
    'Seu registro grave pode organizar o pulso sem esgotar as funções da percussão.'
),
(
    'tamborim',
    'Tamborim',
    'percussion',
    'acoustic',
    'Pequeno tambor de aro e uma membrana, tocado com baqueta.',
    'Instrumento de circulação ampla, mantido aqui por sua construção e modo de produção sonora.',
    'A baqueta percute a membrana esticada sobre o aro, produzindo ataques curtos e definidos.',
    'Há construções artesanais e comerciais com corpos, profundidades e contextos diferentes.'
),
(
    'cuica',
    'Cuíca',
    'percussion',
    'acoustic',
    'Tambor de fricção com uma haste presa à membrana pelo lado interno.',
    'Instrumento de circulação ampla, mantido aqui por sua construção e modo de produção sonora.',
    'A fricção da haste transmite vibração à membrana; a pressão dos dedos sobre a pele modifica o som.',
    'A altura percebida muda com a pressão aplicada à membrana durante a fricção.'
),
(
    'sampler',
    'Sampler',
    'sampled-sounds',
    'sampled',
    'Instrumento que grava ou reproduz trechos sonoros controláveis.',
    'Tornou-se central em diferentes práticas eletrônicas e no hip-hop.',
    'Áudio armazenado é disparado, recortado, repetido ou transformado.',
    'Uma gravação cotidiana pode se tornar material instrumental.'
);

-- =============================================================================
-- Common Roles
-- =============================================================================

-- Family roles
INSERT INTO instrument_common_roles (family_slug, role) VALUES
('plucked-strings', 'harmonia'),
('plucked-strings', 'melodia'),
('plucked-strings', 'base rítmica'),
('percussion', 'pulso'),
('percussion', 'textura'),
('percussion', 'acentuação'),
('synthesizers', 'textura'),
('synthesizers', 'harmonia'),
('synthesizers', 'melodia'),
('synthesizers', 'efeitos'),
('acoustic-keys', 'harmonia'),
('acoustic-keys', 'melodia'),
('acoustic-keys', 'acompanhamento'),
('bowed-strings', 'melodia'),
('bowed-strings', 'sustentação'),
('bowed-strings', 'textura'),
('sampled-sounds', 'ritmo'),
('sampled-sounds', 'textura'),
('sampled-sounds', 'memória sonora');

-- Instrument roles
INSERT INTO instrument_common_roles (instrument_slug, role) VALUES
('electric-guitar', 'harmonia'),
('electric-guitar', 'melodia'),
('electric-guitar', 'textura'),
('electric-bass', 'base rítmica'),
('electric-bass', 'fundamento harmônico'),
('electric-bass', 'contracanto'),
('drums', 'pulso'),
('drums', 'dinâmica'),
('drums', 'articulação formal'),
('synthesizer', 'textura'),
('synthesizer', 'harmonia'),
('synthesizer', 'melodia'),
('synthesizer', 'efeitos'),
('piano', 'harmonia'),
('piano', 'melodia'),
('piano', 'acompanhamento'),
('cello', 'linha grave'),
('cello', 'melodia'),
('cello', 'sustentação'),
('acoustic-guitar', 'harmonia'),
('acoustic-guitar', 'melodia'),
('acoustic-guitar', 'acompanhamento'),
('cavaquinho', 'harmonia'),
('cavaquinho', 'ritmo'),
('cavaquinho', 'acompanhamento'),
('pandeiro', 'ritmo'),
('pandeiro', 'acentuação'),
('pandeiro', 'textura'),
('surdo', 'ritmo'),
('surdo', 'marcação'),
('surdo', 'linha grave'),
('tamborim', 'ritmo'),
('tamborim', 'acentuação'),
('tamborim', 'contracanto'),
('cuica', 'ritmo'),
('cuica', 'fraseado'),
('cuica', 'textura'),
('sampler', 'ritmo'),
('sampler', 'textura'),
('sampler', 'colagem');

-- =============================================================================
-- Relations
-- =============================================================================

INSERT INTO instrument_relations (source_slug, target_slug) VALUES
('plucked-strings', 'electric-guitar'),
('plucked-strings', 'electric-bass'),
('plucked-strings', 'acoustic-guitar'),
('plucked-strings', 'cavaquinho'),
('percussion', 'drums'),
('percussion', 'pandeiro'),
('percussion', 'surdo'),
('percussion', 'tamborim'),
('percussion', 'cuica'),
('synthesizers', 'synthesizer'),
('synthesizers', 'sampled-sounds'),
('acoustic-keys', 'piano'),
('bowed-strings', 'cello'),
('sampled-sounds', 'sampler'),
('sampled-sounds', 'synthesizers'),
('electric-guitar', 'plucked-strings'),
('electric-guitar', 'electric-bass'),
('electric-bass', 'plucked-strings'),
('electric-bass', 'electric-guitar'),
('acoustic-guitar', 'plucked-strings'),
('cavaquinho', 'plucked-strings'),
('drums', 'percussion'),
('pandeiro', 'percussion'),
('surdo', 'percussion'),
('tamborim', 'percussion'),
('cuica', 'percussion'),
('synthesizer', 'synthesizers'),
('synthesizer', 'sampler'),
('piano', 'acoustic-keys'),
('cello', 'bowed-strings'),
('sampler', 'sampled-sounds'),
('sampler', 'synthesizer');

-- Legacy public slugs remain readable while canonical identifiers stay in English.
INSERT INTO instrument_slug_aliases (alias_slug, canonical_slug) VALUES
    ('guitarra-eletrica', 'electric-guitar'),
    ('baixo-eletrico', 'electric-bass'),
    ('bateria', 'drums'),
    ('sintetizador', 'synthesizer'),
    ('violoncelo', 'cello');

INSERT INTO family_slug_aliases (alias_slug, canonical_slug) VALUES
    ('cordas-dedilhadas', 'plucked-strings'),
    ('percussao', 'percussion'),
    ('sintetizadores', 'synthesizers'),
    ('teclas-acusticas', 'acoustic-keys'),
    ('cordas-friccionadas', 'bowed-strings'),
    ('sons-sampleados', 'sampled-sounds');

-- Controlled external names; no arbitrary slugification is performed at runtime.
INSERT INTO instrument_aliases
    (instrument_slug, source, locale, alias, normalized_alias)
VALUES
    ('electric-guitar', 'musicbrainz', 'en', 'electric guitar', 'electric guitar'),
    ('electric-guitar', 'musicbrainz', 'en', 'guitar, electric', 'guitar electric'),
    ('electric-guitar', 'musicbrainz', 'en', 'guitar', 'guitar'),
    ('electric-bass', 'musicbrainz', 'en', 'electric bass', 'electric bass'),
    ('electric-bass', 'musicbrainz', 'en', 'bass guitar', 'bass guitar'),
    ('electric-bass', 'musicbrainz', 'en', 'bass', 'bass'),
    ('drums', 'musicbrainz', 'en', 'drum kit', 'drum kit'),
    ('drums', 'musicbrainz', 'en', 'drums', 'drums'),
    ('drums', 'musicbrainz', 'en', 'drum', 'drum'),
    ('synthesizer', 'musicbrainz', 'en', 'synthesizer', 'synthesizer'),
    ('synthesizer', 'musicbrainz', 'en', 'synth', 'synth'),
    ('piano', 'musicbrainz', 'en', 'piano', 'piano'),
    ('cello', 'musicbrainz', 'en', 'cello', 'cello'),
    ('sampler', 'musicbrainz', 'en', 'sampler', 'sampler'),
    ('acoustic-guitar', 'musicbrainz', 'en', 'acoustic guitar', 'acoustic guitar'),
    ('acoustic-guitar', 'musicbrainz', 'en', 'classical guitar', 'classical guitar'),
    ('acoustic-guitar', 'musicbrainz', 'en', 'nylon string guitar', 'nylon string guitar'),
    ('cavaquinho', 'musicbrainz', 'en', 'cavaquinho', 'cavaquinho'),
    ('pandeiro', 'musicbrainz', 'en', 'pandeiro', 'pandeiro'),
    ('surdo', 'musicbrainz', 'en', 'surdo', 'surdo'),
    ('tamborim', 'musicbrainz', 'en', 'tamborim', 'tamborim'),
    ('cuica', 'musicbrainz', 'en', 'cuíca', 'cuica'),
    ('electric-guitar', 'editorial', 'pt-BR', 'guitarra elétrica', 'guitarra eletrica'),
    ('electric-bass', 'editorial', 'pt-BR', 'baixo elétrico', 'baixo eletrico'),
    ('drums', 'editorial', 'pt-BR', 'bateria', 'bateria'),
    ('synthesizer', 'editorial', 'pt-BR', 'sintetizador', 'sintetizador'),
    ('piano', 'editorial', 'pt-BR', 'piano', 'piano'),
    ('cello', 'editorial', 'pt-BR', 'violoncelo', 'violoncelo'),
    ('sampler', 'editorial', 'pt-BR', 'sampler', 'sampler');

-- =============================================================================
-- Initial Catalog Version
-- =============================================================================

INSERT INTO catalog_versions (version, methodology_version, description) VALUES
('0.1.0', '0.1.0', 'Taxonomia inicial com famílias, fichas editoriais e mapeamentos externos controlados.');
