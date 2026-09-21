from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from palette_api.domain import (
    AnalysisStatus,
    Confidence,
    DataSource,
    ListeningPeriod,
    RecordingStatus,
)

class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileSummary(ApiModel):
    username: str
    period: ListeningPeriod
    tracks_analyzed: int = Field(ge=0)
    total_plays: int = Field(ge=0)


class RecordingStatusCounts(ApiModel):
    """Counts for every recording state, including zero-valued states."""

    resolved: int = Field(ge=0)
    unresolved_identity: int = Field(ge=0)
    pending_enrichment: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    resolved_without_evidence: int = Field(ge=0)
    transient_failure: int = Field(ge=0)
    terminal_failure: int = Field(ge=0)


SectionAvailability = Literal[
    "available",
    "insufficient_coverage",
    "insufficient_diversity",
    "insufficient_nature_evidence",
    "no_candidate",
]


class SectionAvailabilitySummary(ApiModel):
    families: SectionAvailability
    sound_balance: SectionAvailability
    discovery: SectionAvailability
    temperament: SectionAvailability


class VocalPresence(ApiModel):
    """Documented vocal presence aggregated at recording level."""

    documented_tracks: int = Field(ge=0)
    documented_artists: int = Field(ge=0)
    documented_plays: int = Field(ge=0)
    track_ratio: float = Field(ge=0, le=1)
    play_ratio: float = Field(ge=0, le=1)


class AnalysisSummary(ApiModel):
    status: AnalysisStatus
    data_source: Literal["mock", "hybrid", "catalog"]
    history_source: DataSource
    instrumentation_source: DataSource
    methodology_version: str
    catalog_version: str | None = None
    coverage_tracks: float = Field(ge=0, le=1)
    coverage_plays: float = Field(ge=0, le=1)
    recording_status_counts: RecordingStatusCounts
    notice: str
    section_availability: SectionAvailabilitySummary
    vocal_presence: VocalPresence
    image_catalog_version: str = "images-0.1.0"


class ImageVariant(ApiModel):
    name: str
    url: str
    width: int = Field(ge=0)
    height: int = Field(ge=0)


class ImageCredit(ApiModel):
    photographer: str | None = None
    provider: str | None = None
    photo_url: str | None = None
    photographer_url: str | None = None
    license: str | None = None
    license_url: str | None = None


class ImageTone(ApiModel):
    shadow: str
    highlight: str


class InstrumentImage(ApiModel):
    asset_id: str
    resolution: Literal["exact", "related", "family"]
    depicted_instrument_slug: str
    alt: str
    caption: str
    variants: list[ImageVariant]
    tone: ImageTone
    credit: ImageCredit


class FamilyPresence(ApiModel):
    slug: str
    name: str
    share: float = Field(ge=0, le=1)
    evidence_count: int = Field(ge=0)
    confidence: Confidence
    image: InstrumentImage | None = None
    tone: ImageTone | None = None


class SoundBalance(ApiModel):
    acoustic: float = Field(ge=0, le=1)
    electric: float = Field(ge=0, le=1)
    electronic: float = Field(ge=0, le=1)
    sampled: float = Field(ge=0, le=1)
    hybrid: float = Field(ge=0, le=1)
    unknown: float = Field(ge=0, le=1)


class Discovery(ApiModel):
    instrument_slug: str
    title: str
    summary: str
    image: InstrumentImage | None = None


class Temperament(ApiModel):
    title: str
    summary: str
    disclaimer: str


class RecordingAnalysis(ApiModel):
    title: str
    artist: str
    play_count: int = Field(ge=0)
    mbid: str | None = None
    lastfm_url: str | None = None
    status: RecordingStatus
    status_detail: str | None = None


EditorialStatus = Literal["draft", "sourced", "reviewed", "published", "deprecated"]


class EditorialReview(ApiModel):
    """Review state kept separate from the prose itself.

    ``source_metadata_verified`` means that the bibliographic record was
    checked.  ``claim_support_verified`` is intentionally independent: a
    source can be real and still not have been reviewed as sufficient support
    for the claim.
    """

    source_metadata_verified: bool
    claim_support_verified: bool
    reviewed_at: str | None = None
    reviewer: str | None = None
    editorial_note: str | None = None


class EditorialCitation(ApiModel):
    source_id: str
    locator: str | None = None
    note: str | None = None


class EditorialSection(ApiModel):
    id: str
    kind: Literal["curiosity"]
    text: str
    content_type: Literal["fact", "editorial_summary"]
    status: EditorialStatus
    review: EditorialReview
    citations: list[EditorialCitation] = Field(default_factory=list)


class EditorialSource(ApiModel):
    id: str
    title: str
    contributors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    publication_date: str | None = None
    url: str | None = None
    accessed_at: str | None = None
    verified_at: str | None = None
    locator: str | None = None
    source_type: str
    language: str = "en"
    license: str | None = None
    note: str | None = None
    metadata_verified: bool = False


class PaletteReport(ApiModel):
    profile: ProfileSummary
    analysis: AnalysisSummary
    recordings: list[RecordingAnalysis]
    families: list[FamilyPresence]
    sound_balance: SoundBalance | None = None
    discovery: Discovery | None = None
    temperament: Temperament | None = None


class FurtherReading(ApiModel):
    title: str = Field(min_length=1)
    url: HttpUrl
    publisher: str | None = None


class InstrumentResource(ApiModel):
    data_source: Literal["mock", "catalog"] = "mock"
    catalog_version: str = "mock-0.1.0"
    image_catalog_version: str = "images-0.1.0"
    slug: str
    name: str
    kind: Literal["instrument", "family"]
    family_slug: str | None = None
    description: str
    sound_production: str
    common_roles: list[str]
    related_slugs: list[str]
    sections: list[EditorialSection] = Field(default_factory=list)
    sources: list[EditorialSource] = Field(default_factory=list)
    further_reading: list[FurtherReading] = Field(default_factory=list)
    image: InstrumentImage | None = None
    tone: ImageTone | None = None


class ApiError(ApiModel):
    code: str
    message: str


# ---------------------------------------------------------------------------
# API v2 analysis contract
# ---------------------------------------------------------------------------

AnalysisV2Status = Literal["available", "pending", "insufficient"]
AnalysisView = Literal["track_palette", "artist_vocabulary"]


class SnapshotInfo(ApiModel):
    snapshot_version: str
    schema_version: str
    manifest_hash: str
    object_prefix: str
    methodology_version: str


class HydrationSummary(ApiModel):
    status: Literal["complete", "pending"]
    pending_recordings: int = Field(ge=0)
    pending_artists: int = Field(ge=0)
    pending_aliases: int = Field(ge=0)


class VocabularyReach(ApiModel):
    track_reach: float = Field(ge=0, le=1)
    play_reach: float = Field(ge=0, le=1)
    qualified_artists: int = Field(ge=0)
    total_artists: int = Field(ge=0)
    qualified_tracks: int = Field(ge=0)
    total_tracks: int = Field(ge=0)
    qualified_plays: int = Field(ge=0)
    total_plays: int = Field(ge=0)
    unresolved_artists: int = Field(ge=0)
    unresolved_tracks: int = Field(ge=0)


class VocabularyEvidence(ApiModel):
    source: Literal["musicbrainz_snapshot"]
    scope: Literal["recording", "track"]
    snapshot_version: str
    quality: float = Field(ge=0, le=1)
    documented_recordings: int = Field(ge=0)


class VocabularyInstrument(ApiModel):
    slug: str
    name: str
    distinct_recordings: int = Field(ge=0)
    documented_recordings: int = Field(ge=0)
    prevalence: float = Field(ge=0, le=1)
    evidence: VocabularyEvidence


class VocabularyFamily(ApiModel):
    slug: str
    name: str
    score: float = Field(ge=0)
    share: float = Field(ge=0, le=1)
    prevalence: float = Field(ge=0, le=1)
    supporting_artists: int = Field(ge=0)
    instruments: list[VocabularyInstrument] = Field(default_factory=list)


class VocabularyAvailability(ApiModel):
    status: AnalysisV2Status
    reason: str
    pending_artists: int = Field(ge=0)
    pending_tracks: int = Field(ge=0)


class ArtistVocabulary(ApiModel):
    status: AnalysisV2Status
    methodology_version: str
    availability: VocabularyAvailability
    reach: VocabularyReach
    concentration: float = Field(ge=0, le=1)
    families: list[VocabularyFamily] = Field(default_factory=list)
    notice: str


class ProfileAnalysisV2(ApiModel):
    profile: ProfileSummary
    snapshot: SnapshotInfo
    track_palette: PaletteReport
    artist_vocabulary: ArtistVocabulary
    available_views: list[AnalysisView]
    default_view: AnalysisView | None
    hydration: HydrationSummary
