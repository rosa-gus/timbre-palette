-- Update editorial origin and curiosity texts using the researched references.
-- Sources consulted on 2026-09-12:
--   ICOM/MIMO: https://icom-music.mini.icom.museum/resources/classification-of-musical-instruments/
--   The Met, The Sacred Lute: https://www.metmuseum.org/exhibitions/listings/2014/sacred-lute
--   MIM, Geographic Galleries: https://mim.org/galleries/geographic-galleries/
--   The Met, Drum (Teponaztli): https://www.metmuseum.org/art/collection/search/312583
--   Bob Moog Foundation, Timeline of Synthesis: https://moogfoundation.org/timeline/
--   The Met, Musical Terms: https://www.metmuseum.org/essays/musical-terms-for-the-seventeenth-and-eighteenth-centuries
--   The Met, Keyboard Instruments: https://resources.metmuseum.org/resources/metpublications/pdf/Keyboard_Instruments_The_Metropolitan_Museum_of_Art_Bulletin_v_47_no_1_Summer_1989.pdf
--   Library of Congress, Citizen DJ: https://citizen-dj.labs.loc.gov/about/
--   Smithsonian, Electric Guitars: https://americanhistory.si.edu/blog/5-intriguing-electric-guitars-our-collections
--   Smithsonian, Precision Bass: https://americanhistory.si.edu/collections/object/nmah_607619
--   Smithsonian Music, Drum Set: https://music.si.edu/story/birth-drum-set
--   The Met, Cristofori Piano: https://www.metmuseum.org/essays/the-piano-the-pianofortes-of-bartolomeo-cristofori-1655-1731
--   The Met, Amaryllis Fleming Cello: https://www.metmuseum.org/art/collection/search/898377
--   NFSA, Fairlight CMI: https://www.nfsa.gov.au/collection/item/103332-fairlight-cmi

-- Families
UPDATE instrument_families
SET origin = 'Este é um agrupamento por modo de execução, não uma linhagem histórica única. Instrumentos de cordas dedilhadas aparecem há milênios em diferentes regiões; alaúdes de braço longo, por exemplo, são documentados na Ásia Central e Ocidental desde o terceiro milênio a.C.',
    curiosity = 'Dedilhar uma corda não exige contato direto dos dedos: no cravo, pressionar uma tecla levanta um pequeno plectro que pinça a corda.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'plucked-strings';

UPDATE instrument_families
SET origin = 'A percussão não possui uma origem única. Tambores, sinos, chocalhos e outros instrumentos percussivos aparecem em registros arqueológicos de sociedades muito distantes; o Musical Instrument Museum preserva, por exemplo, um tambor chinês com cerca de seis mil anos.',
    curiosity = 'Instrumentos de percussão nem sempre servem apenas para marcar o tempo. Entre os Mexica, o teponaztli participava de cerimônias religiosas, eventos reais, atividades militares e formas de comunicação.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'percussion';

UPDATE instrument_families
SET origin = 'A síntese eletrônica nasceu de várias linhas de experimentação, não de um único aparelho. Entre seus antecedentes estão o Telharmonium, construído na passagem para o século XX, o Audion Piano de 1915 e instrumentos eletrônicos como o theremin.',
    curiosity = 'Um sintetizador não precisa ter teclado. O theremin é controlado por gestos próximos a antenas, enquanto outros sistemas adotaram placas de toque, sequenciadores e conexões modulares.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'synthesizers';

UPDATE instrument_families
SET origin = 'Teclas acústicas são uma categoria funcional do projeto. O teclado surgiu como uma interface capaz de controlar diferentes mecanismos e, ao longo da história, foi aplicado a tubos, cordas e outros corpos sonoros.',
    curiosity = 'Teclas visualmente semelhantes podem produzir som de maneiras muito diferentes: pinçando uma corda no cravo, golpeando-a no piano ou liberando ar em um tubo de órgão.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'acoustic-keys';

UPDATE instrument_families
SET origin = 'Esta categoria reúne instrumentos pelo uso do arco, e não por uma origem histórica comum. Na taxonomia do projeto, ela aproxima linhagens regionais distintas que mantêm a corda em vibração por fricção.',
    curiosity = 'Pertencer a esta família não significa ser tocado exclusivamente com arco: violino, viola, violoncelo e contrabaixo também podem ter as cordas pinçadas, técnica conhecida como pizzicato.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'bowed-strings';

UPDATE instrument_families
SET origin = 'A criação com sons gravados passou por montagem em fita, práticas de DJ e instrumentos digitais. No fim da década de 1970, equipamentos como o Fairlight CMI permitiram gravar, manipular e tocar digitalmente sons do mundo real.',
    curiosity = 'Um sample pode vir de música, fala, gravações de campo ou ruídos cotidianos. Ao ser recortado e reorganizado, esse material pode formar uma composição inteiramente nova.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'sampled-sounds';

-- Instruments
UPDATE instruments
SET origin = 'A guitarra elétrica surgiu de experiências das décadas de 1920 e 1930 para tornar a guitarra audível em conjuntos maiores. Captadores eletromagnéticos e, depois, corpos sólidos ajudaram a resolver esse problema de volume.',
    curiosity = 'A mudança decisiva não foi uma nova maneira de dedilhar: foi transformar a vibração das cordas em sinal elétrico, permitindo amplificação e novas etapas de tratamento sonoro.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'electric-guitar';

UPDATE instruments
SET origin = 'O formato moderno do baixo elétrico ganhou impulso com o Fender Precision Bass, lançado em 1951. O instrumento combinava braço com trastes, amplificação e um corpo mais fácil de transportar que o contrabaixo acústico.',
    curiosity = 'O nome “Precision” fazia referência aos trastes: eles permitiam localizar as notas com uma precisão diferente daquela exigida pelo espelho sem trastes do contrabaixo acústico.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'electric-bass';

UPDATE instruments
SET origin = 'A bateria tomou forma entre o fim do século XIX e o começo do XX, quando tambores, pratos e acessórios antes distribuídos entre vários percussionistas passaram a ser reunidos para uma só pessoa.',
    curiosity = 'Pedais permitiram que pés e mãos assumissem partes diferentes ao mesmo tempo. Um único intérprete passou a articular pulso, contratempo, síncope e textura em todo o conjunto.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'drums';

UPDATE instruments
SET origin = 'O sintetizador moderno resulta de muitas experiências eletrônicas anteriores. Na década de 1960, sistemas modulares controlados por tensão, desenvolvidos por nomes como Bob Moog e Don Buchla, tornaram a síntese mais diretamente programável por músicos.',
    curiosity = 'Os primeiros sintetizadores podiam ocupar grandes estúdios e exigir cabos para conectar cada função. O Minimoog, apresentado em 1970, reuniu três osciladores e controles voltados à apresentação ao vivo em um formato compacto.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'synthesizer';

UPDATE instruments
SET origin = 'O primeiro piano é atribuído a Bartolomeo Cristofori, que desenvolveu o instrumento em Florença por volta de 1700. Seu mecanismo usava martelos para atingir as cordas e permitia controlar a intensidade pelo toque.',
    curiosity = 'Apenas três pianos construídos por Cristofori são conhecidos atualmente. O exemplar de 1720 preservado pelo Metropolitan Museum é o mais antigo deles.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'piano';

UPDATE instruments
SET origin = 'O violoncelo começou a tomar forma no norte da Itália durante o século XVI, dentro das experiências que deram origem à família moderna do violino. Seus tamanhos e número de cordas ainda variavam bastante nesse período.',
    curiosity = 'Alguns dos primeiros violoncelos tinham três, quatro ou cinco cordas. Exemplares menores podiam ser sustentados por uma correia e tocados em pé ou em movimento.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'cello';

UPDATE instruments
SET origin = 'Samplers digitais tornaram possível gravar sons externos, armazená-los e tocá-los como material instrumental. O Fairlight CMI, criado na Austrália em 1979 por Kim Ryrie e Peter Vogel, foi um dos marcos iniciais dessa tecnologia.',
    curiosity = 'O som de vidro quebrando em “Babooshka”, de Kate Bush, veio de um Fairlight CMI e é citado como um dos primeiros usos marcantes do instrumento.',
    updated_at = '2026-09-12 00:00:00'
WHERE slug = 'sampler';

-- The initial seed used the migration execution time. Pin it to the date when
-- version 0.1.0 entered the repository so fresh databases preserve chronology.
UPDATE catalog_versions
SET published_at = '2026-09-11 18:53:35'
WHERE version = '0.1.0';

INSERT INTO catalog_versions
    (version, methodology_version, description, published_at)
VALUES
    ('0.1.1', '0.1.0', 'Atualização editorial de origin e curiosity com referências institucionais e especializadas.', '2026-09-12 00:00:00');
