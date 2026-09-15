-- Editorial claims and their reviewable source metadata.
--
-- A block is a claim-bearing piece of prose.  Its status is independent from
-- the source record: a source may be bibliographically verified while the
-- claim still awaits editorial review.  The current projection is therefore
-- deliberately `sourced`, not `published`.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS editorial_sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    contributors_json TEXT NOT NULL DEFAULT '[]',
    publisher TEXT,
    publication_date TEXT,
    url TEXT,
    accessed_at TEXT NOT NULL,
    source_locator TEXT,
    source_type TEXT NOT NULL CHECK (
        source_type IN (
            'classification', 'museum', 'archive', 'foundation',
            'institution', 'manufacturer', 'society', 'university',
            'library', 'book', 'article', 'primary', 'government',
            'collaborative', 'official', 'other'
        )
    ),
    language TEXT NOT NULL DEFAULT 'en',
    license TEXT,
    source_note TEXT,
    metadata_verified INTEGER NOT NULL DEFAULT 0
        CHECK (metadata_verified IN (0, 1)),
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS editorial_content_blocks (
    id TEXT PRIMARY KEY,
    instrument_slug TEXT REFERENCES instruments(slug) ON DELETE CASCADE,
    family_slug TEXT REFERENCES instrument_families(slug) ON DELETE CASCADE,
    section_kind TEXT NOT NULL CHECK (section_kind IN ('origin', 'curiosity')),
    text TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'editorial_summary'
        CHECK (content_type IN ('fact', 'editorial_summary')),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'sourced', 'reviewed', 'published', 'deprecated')),
    claim_support_verified INTEGER NOT NULL DEFAULT 0
        CHECK (claim_support_verified IN (0, 1)),
    reviewed_at TEXT,
    reviewer TEXT,
    editorial_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (
        (instrument_slug IS NOT NULL AND family_slug IS NULL)
        OR (instrument_slug IS NULL AND family_slug IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_editorial_blocks_instrument
    ON editorial_content_blocks(instrument_slug, section_kind);
CREATE INDEX IF NOT EXISTS idx_editorial_blocks_family
    ON editorial_content_blocks(family_slug, section_kind);
CREATE INDEX IF NOT EXISTS idx_editorial_blocks_status
    ON editorial_content_blocks(status);

CREATE TABLE IF NOT EXISTS editorial_content_citations (
    block_id TEXT NOT NULL REFERENCES editorial_content_blocks(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES editorial_sources(id) ON DELETE RESTRICT,
    locator TEXT,
    citation_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (block_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_editorial_citations_source
    ON editorial_content_citations(source_id);

-- Sources and access dates are explicit so the frontend can render provenance
-- without parsing prose.
INSERT OR IGNORE INTO editorial_sources
    (id, title, contributors_json, publisher, url, accessed_at, source_type,
     metadata_verified, verified_at)
VALUES
    ('icom-mimo-classification', 'Classification of Musical Instruments',
     '["ICOM","MIMO"]', 'ICOM / MIMO',
     'https://icom-music.mini.icom.museum/resources/classification-of-musical-instruments/',
     '2026-09-12', 'classification', 1, '2026-09-12'),
    ('met-sacred-lute', 'The Sacred Lute',
     '["The Metropolitan Museum of Art"]', 'The Metropolitan Museum of Art',
     'https://www.metmuseum.org/exhibitions/listings/2014/sacred-lute',
     '2026-09-12', 'museum', 1, '2026-09-12'),
    ('mim-geographic-galleries', 'Geographic Galleries',
     '["Musical Instrument Museum"]', 'Musical Instrument Museum',
     'https://mim.org/galleries/geographic-galleries/',
     '2026-09-12', 'museum', 1, '2026-09-12'),
    ('met-teponaztli', 'Drum (Teponaztli)',
     '["The Metropolitan Museum of Art"]', 'The Metropolitan Museum of Art',
     'https://www.metmuseum.org/art/collection/search/312583',
     '2026-09-12', 'museum', 1, '2026-09-12'),
    ('moog-timeline', 'Timeline of Synthesis History',
     '["Bob Moog Foundation"]', 'Bob Moog Foundation',
     'https://moogfoundation.org/timeline/',
     '2026-09-12', 'foundation', 1, '2026-09-12'),
    ('met-musical-terms', 'Musical Terms for the Seventeenth and Eighteenth Centuries',
     '["The Metropolitan Museum of Art"]', 'The Metropolitan Museum of Art',
     'https://www.metmuseum.org/essays/musical-terms-for-the-seventeenth-and-eighteenth-centuries',
     '2026-09-12', 'museum', 1, '2026-09-12'),
    ('met-keyboard-instruments', 'Keyboard Instruments',
     '["The Metropolitan Museum of Art"]', 'The Metropolitan Museum of Art',
     'https://resources.metmuseum.org/resources/metpublications/pdf/Keyboard_Instruments_The_Metropolitan_Museum_of_Art_Bulletin_v_47_no_1_Summer_1989.pdf',
     '2026-09-12', 'museum', 1, '2026-09-12'),
    ('loc-citizen-dj', 'Citizen DJ: About the Project',
     '["Library of Congress"]', 'Library of Congress',
     'https://citizen-dj.labs.loc.gov/about/',
     '2026-09-12', 'archive', 1, '2026-09-12'),
    ('smithsonian-electric-guitar', '5 Intriguing Electric Guitars in Our Collections',
     '["Smithsonian National Museum of American History"]',
     'Smithsonian National Museum of American History',
     'https://americanhistory.si.edu/blog/5-intriguing-electric-guitars-our-collections',
     '2026-09-12', 'museum', 1, '2026-09-12'),
    ('smithsonian-precision-bass', 'Fender Precision Bass',
     '["Smithsonian National Museum of American History"]',
     'Smithsonian National Museum of American History',
     'https://americanhistory.si.edu/collections/object/nmah_607619',
     '2026-09-12', 'museum', 1, '2026-09-12'),
    ('smithsonian-drum-set', 'The Birth of the Drum Set',
     '["Smithsonian Institution"]', 'Smithsonian Institution',
     'https://music.si.edu/story/birth-drum-set',
     '2026-09-12', 'institution', 1, '2026-09-12'),
    ('met-cristofori-piano', 'The Piano: The Pianofortes of Bartolomeo Cristofori',
     '["The Metropolitan Museum of Art"]', 'The Metropolitan Museum of Art',
     'https://www.metmuseum.org/essays/the-piano-the-pianofortes-of-bartolomeo-cristofori-1655-1731',
     '2026-09-12', 'museum', 1, '2026-09-12'),
    ('met-cello', 'Amaryllis Fleming Cello',
     '["The Metropolitan Museum of Art"]', 'The Metropolitan Museum of Art',
     'https://www.metmuseum.org/art/collection/search/898377',
     '2026-09-12', 'museum', 1, '2026-09-12'),
    ('nfsa-fairlight', 'Fairlight CMI',
     '["National Film and Sound Archive of Australia"]',
     'National Film and Sound Archive of Australia',
     'https://www.nfsa.gov.au/collection/item/103332-fairlight-cmi',
     '2026-09-12', 'archive', 1, '2026-09-12');

-- LABEET records used by the general instrument fichas. They document
-- contexts and passages, not an exclusive national origin for any instrument.
INSERT OR IGNORE INTO editorial_sources
    (id, title, contributors_json, publisher, publication_date, url,
     accessed_at, source_locator, source_type, language, source_note,
     metadata_verified, verified_at)
VALUES
    ('ufpb-labeet-reco-reco', 'Reco-reco — Acervo Brazil Instrumentarium',
     '["Alice L. Satomi", "Gabriel da Rosa Seixas (tradução)"]',
     'Universidade Federal da Paraíba — LABEET', '2016-09-12',
     'https://www.ctdr.ufpb.br/labeet/contents/paginas/acervo-brazinst/copy_of_idiofones/reco-reco',
     '2026-09-14', 'Verbete Reco-reco', 'university', 'pt-BR',
     'Fonte consultada diretamente. Citações limitadas aos conjuntos descritos no verbete; não é um verbete específico dos instrumentos citados.', 1, '2026-09-14'),
    ('ufpb-labeet-lapinha', 'Pastoril ou Lapinha — Acervo PDMCP', '[]',
     'Universidade Federal da Paraíba — LABEET', NULL,
     'https://www.ctdr.ufpb.br/labeet/contents/paginas/acervo-pdmcp/pastoril-ou-lapinha/',
     '2026-09-14', 'Audios: AFB 07, Tape 42 e Tape 43 — 3; T42 T43',
     'university', 'pt-BR',
     'Registro de catálogo da Lapinha de Valdemar, datado de 08/12/1972. A data da gravação não é a data de publicação da página; autoria individual não atribuída ao registro.', 1, '2026-09-14'),
    ('ufpb-labeet-pandeiro', 'Pandeiro — Acervo Brazil Instrumentarium',
     '["Gabriel da Rosa Seixas"]', 'Universidade Federal da Paraíba — LABEET',
     '2017-02-05',
     'https://www.ufpb.br/labeet/contents/acervos/categorias/membranofones/pandeiro',
     '2026-09-14', 'Verbete Pandeiro: descrição e classificação', 'university', 'pt-BR',
     'Verbete consultado diretamente; referências bibliográficas internas não são apresentadas como obras consultadas.', 1, '2026-09-14'),
    ('ufpb-labeet-tamborim', 'Tamborim — Acervo Brazil Instrumentarium',
     '["Alice L. Satomi", "Gabriel da Rosa Seixas (tradução)"]',
     'Universidade Federal da Paraíba — LABEET', '2016-10-10',
     'https://www.ctdr.ufpb.br/labeet/contents/acervos/categorias/membranofones/tamborim',
     '2026-09-14', 'Verbete Tamborim: primeiro e segundo tipos', 'university', 'pt-BR',
     'Verbete consultado diretamente; distingue o tipo artesanal do tamborim comercial das baterias de escolas de samba.', 1, '2026-09-14');

-- These claims have traceable sources, but no independent claim review yet.
INSERT OR IGNORE INTO editorial_content_blocks
    (id, family_slug, section_kind, text, status, claim_support_verified)
VALUES
    ('family-plucked-strings-origin', 'plucked-strings', 'origin',
     'Este é um agrupamento por modo de execução, não uma linhagem histórica única. Instrumentos de cordas dedilhadas aparecem há milênios em diferentes regiões; alaúdes de braço longo, por exemplo, são documentados na Ásia Central e Ocidental desde o terceiro milênio a.C.',
     'sourced', 0),
    ('family-plucked-strings-curiosity', 'plucked-strings', 'curiosity',
     'Dedilhar uma corda não exige contato direto dos dedos: no cravo, pressionar uma tecla levanta um pequeno plectro que pinça a corda.',
     'sourced', 0),
    ('family-percussion-origin', 'percussion', 'origin',
     'A percussão não possui uma origem única. Tambores, sinos, chocalhos e outros instrumentos percussivos aparecem em registros arqueológicos de sociedades muito distantes; o Musical Instrument Museum preserva, por exemplo, um tambor chinês com cerca de seis mil anos.',
     'sourced', 0),
    ('family-percussion-curiosity', 'percussion', 'curiosity',
     'Instrumentos de percussão nem sempre servem apenas para marcar o tempo. Entre os Mexica, o teponaztli participava de cerimônias religiosas, eventos reais, atividades militares e formas de comunicação.',
     'sourced', 0),
    ('family-synthesizers-origin', 'synthesizers', 'origin',
     'A síntese eletrônica nasceu de várias linhas de experimentação, não de um único aparelho. Entre seus antecedentes estão o Telharmonium, construído na passagem para o século XX, o Audion Piano de 1915 e instrumentos eletrônicos como o theremin.',
     'sourced', 0),
    ('family-synthesizers-curiosity', 'synthesizers', 'curiosity',
     'Um sintetizador não precisa ter teclado. O theremin é controlado por gestos, e outros sistemas usam placas de toque, sequenciadores ou módulos conectados por cabos.',
     'sourced', 0),
    ('family-acoustic-keys-origin', 'acoustic-keys', 'origin',
     'Teclas acústicas são uma categoria funcional: o teclado organiza o gesto, mas a fonte sonora pode ser uma corda, uma lâmina ou um tubo de ar. Essa solução aparece em diferentes linhagens de instrumentos europeus.',
     'sourced', 0),
    ('family-acoustic-keys-curiosity', 'acoustic-keys', 'curiosity',
     'A mesma tecla pode pinçar uma corda no cravo, lançar um martelo no piano ou abrir uma passagem de ar no órgão.',
     'sourced', 0),
    ('family-bowed-strings-origin', 'bowed-strings', 'origin',
     'É um agrupamento pelo uso do arco, não uma origem comum. As cordas friccionadas reúnem linhagens regionais que incluem a família do violino e instrumentos populares de muitas culturas.',
     'sourced', 0),
    ('family-bowed-strings-curiosity', 'bowed-strings', 'curiosity',
     'O arco sustenta a vibração e permite prolongar uma nota; os dedos também podem pinçar a corda, numa técnica chamada pizzicato.',
     'sourced', 0),
    ('family-sampled-sounds-origin', 'sampled-sounds', 'origin',
     'Sons sampleados unem gravação, edição e performance. A prática passa por fita magnética, turntablism, hip-hop e instrumentos digitais como o Fairlight CMI, apresentado em 1979.',
     'sourced', 0),
    ('family-sampled-sounds-curiosity', 'sampled-sounds', 'curiosity',
     'Um sample pode vir de música, fala, paisagem sonora, ruído ou arquivo público; a Biblioteca do Congresso reúne essas possibilidades no projeto Citizen DJ.',
     'sourced', 0);

INSERT OR IGNORE INTO editorial_content_blocks
    (id, instrument_slug, section_kind, text, status, claim_support_verified)
VALUES
    ('instrument-electric-guitar-origin', 'electric-guitar', 'origin',
     'A guitarra elétrica se consolidou entre as décadas de 1920 e 1930, quando músicos e fabricantes buscaram amplificar cordas para conjuntos cada vez mais altos.',
     'sourced', 0),
    ('instrument-electric-guitar-curiosity', 'electric-guitar', 'curiosity',
     'O captador não produz o som sozinho: ele converte a vibração da corda em sinal, que ainda pode ser filtrado, distorcido e espacializado.',
     'sourced', 0),
    ('instrument-electric-bass-origin', 'electric-bass', 'origin',
     'O baixo elétrico ganhou forma comercial no início da década de 1950, quando instrumentos de escala grave passaram a acompanhar conjuntos amplificados com mais projeção e portabilidade.',
     'sourced', 0),
    ('instrument-electric-bass-curiosity', 'electric-bass', 'curiosity',
     'O Fender Precision Bass, lançado em 1951, ajudou a tornar o baixo com trastes uma peça central do pulso em bandas elétricas.',
     'sourced', 0),
    ('instrument-drums-origin', 'drums', 'origin',
     'A bateria moderna cresceu quando músicos reuniram bumbo, caixa, pratos e outros tambores sob o controle de uma só pessoa, uma solução favorecida pelos conjuntos populares do século XX.',
     'sourced', 0),
    ('instrument-drums-curiosity', 'drums', 'curiosity',
     'Um único corpo de bateria pode articular pulso, contratempo, síncope e textura em todo o conjunto.',
     'sourced', 0),
    ('instrument-synthesizer-origin', 'synthesizer', 'origin',
     'O sintetizador moderno resulta de muitas experiências eletrônicas anteriores. Na década de 1960, sistemas modulares controlados por tensão, desenvolvidos por nomes como Bob Moog e Don Buchla, tornaram a síntese mais diretamente programável por músicos.',
     'sourced', 0),
    ('instrument-synthesizer-curiosity', 'synthesizer', 'curiosity',
     'Os primeiros sintetizadores podiam ocupar grandes estúdios e exigir cabos para conectar cada função. O Minimoog, apresentado em 1970, reuniu três osciladores e controles voltados à apresentação ao vivo em um formato compacto.',
     'sourced', 0),
    ('instrument-piano-origin', 'piano', 'origin',
     'O primeiro piano é atribuído a Bartolomeo Cristofori, que desenvolveu o instrumento em Florença por volta de 1700. Seu mecanismo usava martelos para atingir as cordas e permitia controlar a intensidade pelo toque.',
     'sourced', 0),
    ('instrument-piano-curiosity', 'piano', 'curiosity',
     'Apenas três pianos construídos por Cristofori são conhecidos atualmente. O exemplar de 1720 preservado pelo Metropolitan Museum é o mais antigo deles.',
     'sourced', 0),
    ('instrument-cello-origin', 'cello', 'origin',
     'O violoncelo começou a tomar forma no norte da Itália durante o século XVI, dentro das experiências que deram origem à família moderna do violino. Seus tamanhos e número de cordas ainda variavam bastante nesse período.',
     'sourced', 0),
    ('instrument-cello-curiosity', 'cello', 'curiosity',
     'Alguns dos primeiros violoncelos tinham três, quatro ou cinco cordas. Exemplares menores podiam ser sustentados por uma correia e tocados em pé ou em movimento.',
     'sourced', 0),
    ('instrument-sampler-origin', 'sampler', 'origin',
     'Samplers digitais tornaram possível gravar sons externos, armazená-los e tocá-los como material instrumental. O Fairlight CMI, criado na Austrália em 1979 por Kim Ryrie e Peter Vogel, foi um dos marcos iniciais dessa tecnologia.',
     'sourced', 0),
    ('instrument-sampler-curiosity', 'sampler', 'curiosity',
     'O som de vidro quebrando em “Babooshka”, de Kate Bush, veio de um Fairlight CMI e é citado como um dos primeiros usos marcantes do instrumento.',
     'sourced', 0);

INSERT INTO editorial_content_blocks
    (id, instrument_slug, section_kind, text, content_type, status,
     claim_support_verified)
VALUES
    ('instrument-acoustic-guitar-curiosity', 'acoustic-guitar', 'curiosity',
     'O acervo do LABEET registra o violão no conjunto que acompanhava a lambada paraense entre 1975 e 1978, ao lado de tambor carimbó, pandeiro, reco-reco, marimba e banjo. Sua presença no acervo vai além do samba e da MPB.',
     'editorial_summary', 'sourced', 0),
    ('instrument-cavaquinho-curiosity', 'cavaquinho', 'curiosity',
     'Na gravação da Lapinha de Valdemar de 8 de dezembro de 1972, catalogada pelo LABEET, o cavaquinho acompanha as pastoras junto de bandolim, violão e pandeiro. O registro documenta seu uso no pastoril, além dos contextos de samba e choro.',
     'editorial_summary', 'sourced', 0),
    ('instrument-pandeiro-curiosity', 'pandeiro', 'curiosity',
     'O verbete do LABEET mostra que o pandeiro pode funcionar como membranofone quando sua pele é tocada, ou como idiofone quando apenas as soalhas soam ao ser sacudido. Um mesmo instrumento reúne duas formas de produzir som.',
     'editorial_summary', 'sourced', 0),
    ('instrument-surdo-curiosity', 'surdo', 'curiosity',
     'No verbete de reco-reco, o LABEET situa o surdo em conjuntos de carnaval, sambas, marchinhas e samba de morro do Rio de Janeiro. Ali ele aparece ao lado de caixa, repique, tamborim, pandeiro e cuíca, compondo um conjunto de membranofones.',
     'editorial_summary', 'sourced', 0),
    ('instrument-tamborim-curiosity', 'tamborim', 'curiosity',
     'O LABEET distingue dois tipos de tamborim: um artesanal, de corpo de madeira mais profundo, usado em congada e moçambique, e outro comercial, de aro baixo de metal ou acrílico, comum nas baterias de escolas de samba.',
     'editorial_summary', 'sourced', 0),
    ('instrument-cuica-curiosity', 'cuica', 'curiosity',
     'A cuíca aparece no acervo Brazil Instrumentarium do LABEET entre os membranofones que acompanham o reco-reco industrial no carnaval, no samba, nas marchinhas e no samba de morro carioca. O registro evidencia seu lugar em conjuntos, junto de surdo, caixa e repique.',
     'editorial_summary', 'sourced', 0);

INSERT OR IGNORE INTO editorial_content_citations
    (block_id, source_id, citation_note)
VALUES
    ('family-plucked-strings-origin', 'icom-mimo-classification', 'Classificação por modo de execução.'),
    ('family-plucked-strings-origin', 'met-sacred-lute', 'Alaúdes de braço longo na Ásia Central e Ocidental.'),
    ('family-plucked-strings-curiosity', 'met-musical-terms', 'Mecanismo de plectro do cravo.'),
    ('family-percussion-origin', 'mim-geographic-galleries', 'Paigu chinês com cerca de seis mil anos.'),
    ('family-percussion-curiosity', 'met-teponaztli', 'Usos cerimoniais, militares e comunicacionais.'),
    ('family-synthesizers-origin', 'moog-timeline', 'Antecedentes históricos da síntese.'),
    ('family-synthesizers-curiosity', 'moog-timeline', 'Theremin e outras interfaces sem teclado.'),
    ('family-acoustic-keys-origin', 'met-keyboard-instruments', 'Diferentes fontes sonoras sob ação de teclas.'),
    ('family-acoustic-keys-curiosity', 'met-musical-terms', 'Ação de teclas em cordas e tubos.'),
    ('family-bowed-strings-origin', 'icom-mimo-classification', 'Classificação por fricção do arco.'),
    ('family-bowed-strings-curiosity', 'met-cello', 'Arco e pinçamento em cordas friccionadas.'),
    ('family-sampled-sounds-origin', 'nfsa-fairlight', 'Fairlight CMI em 1979.'),
    ('family-sampled-sounds-curiosity', 'loc-citizen-dj', 'Música, fala, campo e arquivos como material.'),
    ('instrument-electric-guitar-origin', 'smithsonian-electric-guitar', 'Amplificação e captadores no século XX.'),
    ('instrument-electric-guitar-curiosity', 'smithsonian-electric-guitar', 'Conversão da vibração em sinal elétrico.'),
    ('instrument-electric-bass-origin', 'smithsonian-precision-bass', 'Contexto do baixo elétrico comercial.'),
    ('instrument-electric-bass-curiosity', 'smithsonian-precision-bass', 'Precision Bass de 1951.'),
    ('instrument-drums-origin', 'smithsonian-drum-set', 'Formação da bateria moderna.'),
    ('instrument-drums-curiosity', 'smithsonian-drum-set', 'Funções simultâneas de uma bateria.'),
    ('instrument-synthesizer-origin', 'moog-timeline', 'Síntese modular controlada por tensão.'),
    ('instrument-synthesizer-curiosity', 'moog-timeline', 'Minimoog de 1970 e três osciladores.'),
    ('instrument-piano-origin', 'met-cristofori-piano', 'Cristofori e o piano por volta de 1700.'),
    ('instrument-piano-curiosity', 'met-cristofori-piano', 'Três pianos de Cristofori preservados.'),
    ('instrument-cello-origin', 'met-cello', 'Desenvolvimento italiano no século XVI.'),
    ('instrument-cello-curiosity', 'met-cello', 'Variação histórica de cordas e tamanhos.'),
    ('instrument-sampler-origin', 'nfsa-fairlight', 'Fairlight CMI e amostragem digital.'),
    ('instrument-sampler-curiosity', 'nfsa-fairlight', 'Uso de vidro quebrando em “Babooshka”.');

INSERT OR IGNORE INTO editorial_content_citations
    (block_id, source_id, locator, citation_note)
VALUES
    ('instrument-acoustic-guitar-curiosity', 'ufpb-labeet-reco-reco', 'Parágrafo sobre lambada do Pará (entre 1975 e 1978).', 'Resumo editorial da passagem indicada; não implica revisão acadêmica ou endosso institucional.'),
    ('instrument-cavaquinho-curiosity', 'ufpb-labeet-lapinha', 'Audios: AFB 07; gravação 08/12/1972; UFPB/BC-FR7003; T42 T43.', 'Resumo editorial da passagem indicada; não implica revisão acadêmica ou endosso institucional.'),
    ('instrument-pandeiro-curiosity', 'ufpb-labeet-pandeiro', 'Descrição da pele, das soalhas e classificação conforme a execução.', 'Resumo editorial da passagem indicada; não implica revisão acadêmica ou endosso institucional.'),
    ('instrument-surdo-curiosity', 'ufpb-labeet-reco-reco', 'Parágrafo sobre danças e músicas urbanas modernas e seus membranofones.', 'Resumo editorial da passagem indicada; não implica revisão acadêmica ou endosso institucional.'),
    ('instrument-tamborim-curiosity', 'ufpb-labeet-tamborim', 'Primeiro tipo artesanal e segundo tipo comercial.', 'Resumo editorial da passagem indicada; não implica revisão acadêmica ou endosso institucional.'),
    ('instrument-cuica-curiosity', 'ufpb-labeet-reco-reco', 'Parágrafo sobre danças e músicas urbanas modernas e seus membranofones.', 'Resumo editorial da passagem indicada; não implica revisão acadêmica ou endosso institucional.');

INSERT INTO catalog_versions
    (version, methodology_version, description, published_at)
VALUES
    ('0.1.2', '0.1.0',
     'Claims editoriais estruturados com status de revisão, citações e metadados de fontes.',
     '2026-09-12 00:01:00');
