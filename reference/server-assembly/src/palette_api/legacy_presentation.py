"""Frozen Portuguese serialization for the retained v2 reference endpoints.

New report calculations and v3 responses never depend on this module.
"""

from palette_api.report import AnalysisImage, AnalysisSummary, PaletteReport, ProfileAnalysisV3
from palette_api.schemas import PaletteReport as LegacyPaletteReport, ProfileAnalysisV2

TEMPERAMENT_COPY = {'recurring-percussion-synthesizers': ('Movimento com atmosfera',
                                       'Sua escuta encontra impulso sem abrir mão de um lugar para '
                                       'permanecer.',
                                       'Percussão e sintetizadores aparecem juntos com presença recorrente, '
                                       'aproximando pulso e textura.'),
 'electric-plucked-strings': ('Corpo elétrico',
                              'Sua escuta tem uma assinatura elétrica: corpo amplificado e possibilidades de '
                              'timbre.',
                              'Cordas dedilhadas e fontes elétricas sustentam a maior parte da paleta.'),
 'recurring-sampled': ('Memória em recortes',
                       'Sua escuta encontra identidade nos recortes: sons que carregam outros contextos e '
                       'ganham novas leituras.',
                       'Sons sampleados têm participação recorrente na paleta deste período.'),
 'recurring-electronic': ('Textura eletrônica',
                          'Sua escuta encontra nos sons eletrônicos uma linguagem própria, feita de timbres '
                          'que podem ser moldados e transformados.',
                          'Fontes eletrônicas têm a maior participação entre as naturezas identificadas.'),
 'dominant-acoustic': ('Acústica com presença',
                       'Sua escuta encontra nas fontes acústicas uma marca própria, aproximando gesto, '
                       'vibração e matéria sonora.',
                       'Fontes acústicas têm a maior participação entre as naturezas identificadas.'),
 'dominant-electric': ('Corpo elétrico',
                       'Sua escuta tem uma assinatura elétrica: uma leitura de corpo amplificado e '
                       'possibilidades de timbre.',
                       'Fontes elétricas têm a maior participação entre as naturezas identificadas.'),
 'dominant-electronic': ('Textura eletrônica',
                         'Sua escuta encontra nos sons eletrônicos uma linguagem própria, feita de timbres '
                         'moldados e transformados.',
                         'Fontes eletrônicas têm a maior participação entre as naturezas identificadas.'),
 'dominant-sampled': ('Memória em recortes',
                      'Sua escuta encontra identidade nos recortes: sons que carregam outros contextos e '
                      'ganham novas leituras.',
                      'Sons sampleados têm a maior participação entre as naturezas identificadas.'),
 'dominant-hybrid': ('Orgânica e eletrônica',
                     'Sua escuta aproxima fontes orgânicas e processos eletrônicos, fazendo da mistura uma '
                     'marca própria.',
                     'Fontes híbridas têm a maior participação entre as naturezas identificadas.')}

DISCLAIMER = "Esta é uma interpretação lúdica do histórico musical, não uma avaliação psicológica ou científica da personalidade."
VOCABULARY_NOTICE = "Recorre em gravações documentadas destes artistas; não descreve necessariamente cada faixa ou a presença de um instrumento no áudio."
RECORDING_DETAILS = {
    "resolved_without_evidence": "The recording was resolved, but has no accepted instrumental evidence.",
    "unresolved_identity": "Last.fm did not provide a MusicBrainz identity for this recording.",
    "pending_enrichment": "The recording is awaiting snapshot hydration.",
    "ambiguous": "The match is ambiguous and awaiting review.",
    "transient_failure": "Snapshot hydration failed transiently and can be retried.",
    "terminal_failure": "Snapshot hydration ended without another automatic retry.",
}


def analysis_notice(analysis: AnalysisSummary) -> str:
    if analysis.history_source == "lastfm":
        source = (
            "O histórico foi obtido do Last.fm e relacionado às evidências instrumentais publicadas no catálogo do projeto."
            if analysis.instrumentation_source == "catalog"
            else "O histórico foi obtido do Last.fm. As evidências instrumentais ainda são fictícias e servem apenas para desenvolver o produto."
        )
    else:
        source = (
            "Escuta fictícia montada com gravações do catálogo e relacionada às evidências instrumentais publicadas no projeto."
            if analysis.instrumentation_source == "catalog"
            else "Histórico e evidências instrumentais fictícios. O contrato e o cálculo são funcionais."
        )
    if analysis.status == "insufficient":
        return source + " A cobertura aceita ainda não é suficiente para montar uma paleta."
    if analysis.status == "partial":
        return source + " A paleta usa a evidência publicada até agora; algumas interpretações permanecem restritas e podem ser ampliadas em uma visita futura."
    return source


def legacy_image(image: AnalysisImage | None) -> dict | None:
    if image is None:
        return None
    result = image.model_dump(mode="json", exclude={"depicted_name", "family_name"})
    instrument = image.depicted_name
    result["alt"] = image.alt if image.alt is not None else f"Imagem de {instrument}."
    result["caption"] = (
        f"Imagem ilustrativa da família {image.family_name}: {instrument}." if image.resolution == "family"
        else f"Imagem relacionada ao instrumento {instrument}." if image.resolution == "related"
        else f"Imagem do instrumento {instrument}."
    )
    return result


def legacy_palette(report: PaletteReport) -> LegacyPaletteReport:
    result = report.model_dump(mode="json")
    result["analysis"]["notice"] = analysis_notice(report.analysis)
    for recording in result["recordings"]:
        recording["status_detail"] = RECORDING_DETAILS.get(recording["status"])
    for family, original in zip(result["families"], report.families, strict=True):
        family["image"] = legacy_image(original.image)
    if report.discovery:
        discovery = report.discovery
        result["discovery"] = {
            "instrument_slug": discovery.instrument_slug,
            "title": f"Uma presença menos óbvia: {discovery.instrument_name}",
            "summary": f"{discovery.instrument_name} acrescenta uma cor particular à paleta e aparece fora do núcleo instrumental mais evidente.",
            "image": legacy_image(discovery.image),
        }
    if report.temperament:
        temperament = report.temperament
        title, invitation, basis = TEMPERAMENT_COPY[temperament.rule]
        family = next(f for f in report.families if f.slug == temperament.primary_family_slug)
        result["temperament"] = {
            "title": title,
            "summary": f"{invitation} {basis} A família com maior participação na paleta é a de {family.name.lower()}.",
            "disclaimer": DISCLAIMER,
        }
    return LegacyPaletteReport.model_validate(result)


def legacy_profile(report: ProfileAnalysisV3) -> ProfileAnalysisV2:
    result = report.model_dump(mode="json", exclude={"report_schema_version"})
    result["track_palette"] = legacy_palette(report.track_palette).model_dump(mode="json")
    result["artist_vocabulary"]["notice"] = VOCABULARY_NOTICE
    return ProfileAnalysisV2.model_validate(result)
