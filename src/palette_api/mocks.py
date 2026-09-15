from dataclasses import replace

from palette_api.editorial_catalog import EDITORIAL_INSTRUMENTS

from palette_api.domain import (
    Confidence,
    DataSource,
    InstrumentLayer,
    ListeningHistory,
    ListeningPeriod,
    SoundNature,
    Track,
)
from palette_api.schemas import (
    EditorialCitation,
    EditorialReview,
    EditorialSection,
    EditorialSource,
    InstrumentResource,
)


class MockListeningHistoryProvider:
    """Deterministic fixture used until the Last.fm adapter is introduced."""

    async def get_history(
        self,
        username: str,
        period: ListeningPeriod,
    ) -> ListeningHistory:
        play_counts = {
            ListeningPeriod.OVERALL: (180, 132, 94),
            ListeningPeriod.TWELVE_MONTHS: (48, 37, 29),
            ListeningPeriod.SIX_MONTHS: (31, 24, 22),
            ListeningPeriod.THREE_MONTHS: (18, 17, 12),
            ListeningPeriod.ONE_MONTH: (9, 6, 8),
            ListeningPeriod.SEVEN_DAYS: (3, 1, 2),
        }[period]

        tracks = (
            Track(
                title="Arquitetura do Pulso",
                artist="Conjunto Imaginário",
                play_count=play_counts[0],
                layers=(
                    InstrumentLayer(
                        slug="electric-guitar",
                        name="Guitarra elétrica",
                        family_slug="plucked-strings",
                        family_name="Cordas dedilhadas",
                        nature=SoundNature.ELECTRIC,
                        role="Cria o movimento harmônico e ocupa o primeiro plano.",
                        confidence=Confidence.DOCUMENTED,
                    ),
                    InstrumentLayer(
                        slug="electric-bass",
                        name="Baixo elétrico",
                        family_slug="plucked-strings",
                        family_name="Cordas dedilhadas",
                        nature=SoundNature.ELECTRIC,
                        role="Ancora o pulso e aproxima ritmo e harmonia.",
                        confidence=Confidence.STRONGLY_ASSOCIATED,
                        prominence=0.9,
                    ),
                    InstrumentLayer(
                        slug="cuica",
                        name="Cuíca",
                        family_slug="percussion",
                        family_name="Percussão",
                        nature=SoundNature.ACOUSTIC,
                        role="Acrescenta uma ressonância inesperada ao pulso.",
                        confidence=Confidence.STRONGLY_ASSOCIATED,
                        prominence=0.35,
                        unexpected=True,
                    ),
                    InstrumentLayer(
                        slug="drums",
                        name="Bateria",
                        family_slug="percussion",
                        family_name="Percussão",
                        nature=SoundNature.ACOUSTIC,
                        role="Organiza o impulso físico da gravação.",
                        confidence=Confidence.DOCUMENTED,
                    ),
                    InstrumentLayer(
                        slug="synthesizer",
                        name="Sintetizador",
                        family_slug="synthesizers",
                        family_name="Sintetizadores",
                        nature=SoundNature.ELECTRONIC,
                        role="Sustenta uma camada atmosférica ao fundo.",
                        confidence=Confidence.STRONGLY_ASSOCIATED,
                        prominence=0.55,
                    ),
                ),
            ),
            Track(
                title="Quarto em Suspensão",
                artist="Dupla Imaginária",
                play_count=play_counts[1],
                layers=(
                    InstrumentLayer(
                        slug="piano",
                        name="Piano",
                        family_slug="acoustic-keys",
                        family_name="Teclas acústicas",
                        nature=SoundNature.ACOUSTIC,
                        role="Abre espaço harmônico entre as frases.",
                        confidence=Confidence.DOCUMENTED,
                    ),
                    InstrumentLayer(
                        slug="cello",
                        name="Violoncelo",
                        family_slug="bowed-strings",
                        family_name="Cordas friccionadas",
                        nature=SoundNature.ACOUSTIC,
                        role="Prolonga a tensão melódica.",
                        confidence=Confidence.STRONGLY_ASSOCIATED,
                        prominence=0.8,
                    ),
                    InstrumentLayer(
                        slug="electric-guitar",
                        name="Guitarra elétrica",
                        family_slug="plucked-strings",
                        family_name="Cordas dedilhadas",
                        nature=SoundNature.ELECTRIC,
                        role="Insere uma linha elétrica entre as frases.",
                        confidence=Confidence.DOCUMENTED,
                        prominence=0.55,
                    ),
                    InstrumentLayer(
                        slug="drums",
                        name="Bateria",
                        family_slug="percussion",
                        family_name="Percussão",
                        nature=SoundNature.ACOUSTIC,
                        role="Mantém um pulso discreto sob a suspensão.",
                        confidence=Confidence.DOCUMENTED,
                        prominence=0.45,
                    ),
                    InstrumentLayer(
                        slug="cuica",
                        name="Cuíca",
                        family_slug="percussion",
                        family_name="Percussão",
                        nature=SoundNature.ACOUSTIC,
                        role="Cria um brilho menos óbvio na transição.",
                        confidence=Confidence.STRONGLY_ASSOCIATED,
                        prominence=0.3,
                        unexpected=True,
                    ),
                ),
            ),
            Track(
                title="Luz Granulada",
                artist="Trio Imaginário",
                play_count=play_counts[2],
                layers=(
                    InstrumentLayer(
                        slug="cuica",
                        name="Cuíca",
                        family_slug="percussion",
                        family_name="Percussão",
                        nature=SoundNature.ACOUSTIC,
                        role="Introduz brilho e ressonância sem dominar o arranjo.",
                        confidence=Confidence.STRONGLY_ASSOCIATED,
                        prominence=0.65,
                        unexpected=True,
                    ),
                    InstrumentLayer(
                        slug="sampler",
                        name="Sampler",
                        family_slug="sampled-sounds",
                        family_name="Sons sampleados",
                        nature=SoundNature.SAMPLED,
                        role="Recorta pequenos gestos e reorganiza suas repetições.",
                        confidence=Confidence.ESTIMATED,
                        prominence=0.6,
                    ),
                    InstrumentLayer(
                        slug="synthesizer",
                        name="Sintetizador",
                        family_slug="synthesizers",
                        family_name="Sintetizadores",
                        nature=SoundNature.ELECTRONIC,
                        role="Preenche o fundo com uma textura contínua.",
                        confidence=Confidence.DOCUMENTED,
                        prominence=0.85,
                    ),
                    InstrumentLayer(
                        slug="electric-guitar",
                        name="Guitarra elétrica",
                        family_slug="plucked-strings",
                        family_name="Cordas dedilhadas",
                        nature=SoundNature.ELECTRIC,
                        role="Desenha uma borda elétrica para a textura.",
                        confidence=Confidence.DOCUMENTED,
                        prominence=0.45,
                    ),
                ),
            ),
        )

        return ListeningHistory(username=username, period=period, tracks=tracks)


class MockInstrumentationProvider:
    """Adds explicit fake layers to real tracks while the catalog is designed."""

    async def enrich(self, history: ListeningHistory) -> ListeningHistory:
        templates = await MockListeningHistoryProvider().get_history(
            username="instrumentation-template",
            period=history.period,
        )
        enriched_tracks = tuple(
            replace(track, layers=templates.tracks[index % len(templates.tracks)].layers)
            for index, track in enumerate(history.tracks)
        )
        return replace(
            history,
            tracks=enriched_tracks,
            instrumentation_source=DataSource.MOCK,
        )


class MockInstrumentCatalog:
    """Small editorial catalog for the first contract and UI integrations."""

    def __init__(self) -> None:
        resources = (
            InstrumentResource(
                slug="plucked-strings",
                name="Cordas dedilhadas",
                kind="family",
                description=(
                    "Família em que a corda vibra depois de ser puxada com dedos, "
                    "palheta ou mecanismo equivalente."
                ),
                sound_production="A corda é deslocada e solta, iniciando uma vibração livre.",
                common_roles=["harmonia", "melodia", "base rítmica"],
                related_slugs=["electric-guitar", "electric-bass", "acoustic-guitar", "cavaquinho"],
            ),
            InstrumentResource(
                slug="percussion",
                name="Percussão",
                kind="family",
                description=(
                    "Família de instrumentos acionados principalmente por impacto, "
                    "agitação ou raspagem."
                ),
                sound_production="Uma superfície ou corpo ressoa depois de receber energia.",
                common_roles=["pulso", "textura", "acentuação"],
                related_slugs=["drums", "pandeiro", "surdo", "tamborim", "cuica"],
            ),
            InstrumentResource(
                slug="synthesizers",
                name="Sintetizadores",
                kind="family",
                description=(
                    "Instrumentos eletrônicos que constroem ou transformam sinais sonoros."
                ),
                sound_production="Osciladores, amostras ou outros sinais são moldados eletronicamente.",
                common_roles=["textura", "harmonia", "melodia", "efeitos"],
                related_slugs=["synthesizer", "sampled-sounds"],
            ),
            InstrumentResource(
                slug="acoustic-keys",
                name="Teclas acústicas",
                kind="family",
                description="Instrumentos acústicos acionados por um sistema de teclas.",
                sound_production="A tecla transmite o gesto a outro mecanismo ressonante.",
                common_roles=["harmonia", "melodia", "acompanhamento"],
                related_slugs=["piano"],
            ),
            InstrumentResource(
                slug="bowed-strings",
                name="Cordas friccionadas",
                kind="family",
                description="Cordas mantidas em vibração principalmente pela fricção de um arco.",
                sound_production="O arco adere e solta a corda repetidamente, sustentando o som.",
                common_roles=["melodia", "sustentação", "textura"],
                related_slugs=["cello"],
            ),
            InstrumentResource(
                slug="sampled-sounds",
                name="Sons sampleados",
                kind="family",
                description="Gravações reutilizadas como matéria para uma nova composição.",
                sound_production="Um trecho gravado é recortado, disparado e transformado.",
                common_roles=["ritmo", "textura", "memória sonora"],
                related_slugs=["sampler", "synthesizers"],
            ),
            InstrumentResource(
                slug="woodwinds",
                name="Madeiras",
                kind="family",
                description="Instrumentos em que uma coluna de ar vibra dentro de um tubo, com furos, chaves ou palheta.",
                sound_production="O sopro põe o ar em vibração; a geometria do tubo e o modo de excitação definem a cor do som.",
                common_roles=["melodia", "contracanto", "textura"],
                related_slugs=[],
            ),
            InstrumentResource(
                slug="brass",
                name="Metais",
                kind="family",
                description="Instrumentos de sopro em que os lábios do intérprete excitam a coluna de ar no tubo.",
                sound_production="A vibração dos lábios é amplificada pelo tubo, e válvulas ou varas alteram o comprimento acústico.",
                common_roles=["melodia", "ataque", "sustentação"],
                related_slugs=[],
            ),
            InstrumentResource(
                slug="voice",
                name="Voz",
                kind="family",
                description="Presença vocal documentada em uma gravação, tratada como uma família própria do catálogo editorial.",
                sound_production="A vibração das pregas vocais é moldada pelo trato vocal e articulada em fala, canto ou coro.",
                common_roles=["melodia", "texto", "camada"],
                related_slugs=[],
            ),
            InstrumentResource(
                slug="electric-keys",
                name="Teclas elétricas e eletrônicas",
                kind="family",
                description="Instrumentos de teclas em que a captação, a amplificação ou a síntese participa da formação do som.",
                sound_production="O gesto das teclas dispara, modula ou amplifica uma fonte elétrica ou eletrônica.",
                common_roles=["harmonia", "melodia", "camada"],
                related_slugs=[],
            ),
            InstrumentResource(
                slug="electric-guitar",
                name="Guitarra elétrica",
                kind="instrument",
                family_slug="plucked-strings",
                description="Instrumento de cordas amplificado e aberto a amplo processamento.",
                sound_production="Captadores convertem a vibração das cordas em sinal elétrico.",
                common_roles=["harmonia", "melodia", "textura"],
                related_slugs=["plucked-strings", "electric-bass"],
            ),
            InstrumentResource(
                slug="electric-bass",
                name="Baixo elétrico",
                kind="instrument",
                family_slug="plucked-strings",
                description="Instrumento elétrico de registro grave ligado ao pulso e à harmonia.",
                sound_production="Captadores transformam a vibração de cordas graves em sinal elétrico.",
                common_roles=["base rítmica", "fundamento harmônico", "contracanto"],
                related_slugs=["plucked-strings", "electric-guitar"],
            ),
            InstrumentResource(
                slug="drums",
                name="Bateria",
                kind="instrument",
                family_slug="percussion",
                description="Conjunto de tambores e pratos organizado para um único intérprete.",
                sound_production="Baquetas, pedais e mãos acionam superfícies de diferentes materiais.",
                common_roles=["pulso", "dinâmica", "articulação formal"],
                related_slugs=["percussion", "cuica"],
            ),
            InstrumentResource(
                slug="synthesizer",
                name="Sintetizador",
                kind="instrument",
                family_slug="synthesizers",
                description="Instrumento eletrônico voltado à criação e transformação de timbres.",
                sound_production="Sinais são gerados ou reproduzidos e depois moldados por controles.",
                common_roles=["textura", "harmonia", "melodia", "efeitos"],
                related_slugs=["synthesizers", "sampler"],
            ),
            InstrumentResource(
                slug="piano",
                name="Piano",
                kind="instrument",
                family_slug="acoustic-keys",
                description="Instrumento de teclas em que martelos percutem cordas afinadas.",
                sound_production="Cada tecla lança um martelo contra uma corda e libera seu abafador.",
                common_roles=["harmonia", "melodia", "acompanhamento"],
                related_slugs=["acoustic-keys"],
            ),
            InstrumentResource(
                slug="cello",
                name="Violoncelo",
                kind="instrument",
                family_slug="bowed-strings",
                description="Instrumento de cordas friccionadas de registro grave e médio.",
                sound_production="O arco ou os dedos colocam suas cordas em vibração.",
                common_roles=["linha grave", "melodia", "sustentação"],
                related_slugs=["bowed-strings"],
            ),
            InstrumentResource(
                slug="sampler",
                name="Sampler",
                kind="instrument",
                family_slug="sampled-sounds",
                description="Instrumento que grava ou reproduz trechos sonoros controláveis.",
                sound_production="Áudio armazenado é disparado, recortado, repetido ou transformado.",
                common_roles=["ritmo", "textura", "colagem"],
                related_slugs=["sampled-sounds", "synthesizer"],
            ),
        )
        mock_source = EditorialSource(
            id="mock-editorial-source",
            title="Fonte editorial de desenvolvimento",
            contributors=["Timbre Palette"],
            publisher="Timbre Palette",
            accessed_at="2026-09-12",
            source_type="institution",
            language="pt-BR",
            metadata_verified=False,
            note="Mock sem verificação bibliográfica; substitua por uma fonte do catálogo.",
        )
        self._resources = {
            resource.slug: resource if resource.sections else resource.model_copy(
                update={
                    "sections": [
                        EditorialSection(
                            id=f"mock-{resource.slug}-editorial",
                            kind="curiosity",
                            text="Conteúdo editorial de desenvolvimento aguardando revisão.",
                            content_type="editorial_summary",
                            status="sourced",
                            review=EditorialReview(
                                source_metadata_verified=False,
                                claim_support_verified=False,
                            ),
                            citations=[
                                EditorialCitation(source_id="mock-editorial-source")
                            ],
                        )
                    ],
                    "sources": [mock_source],
                }
            )
            for resource in (*resources, *EDITORIAL_INSTRUMENTS)
        }

    async def get(self, slug: str) -> InstrumentResource | None:
        return self._resources.get(slug)
