"""Language-neutral report contract; independent of UI dictionaries."""

from typing import Literal

from pydantic import Field

from palette_api.domain import RecordingStatus, SoundNature
from palette_api.schemas import (
    ApiModel, AnalysisStatus, ProfileSummary, RecordingStatusCounts,
    SectionAvailabilitySummary, VocalPresence, ImageVariant, ImageTone,
    ImageCredit, Confidence, SoundBalance, SnapshotInfo, HydrationSummary,
    AnalysisV2Status, AnalysisView, VocabularyAvailability, VocabularyReach,
    VocabularyFamily, VocabularyFeaturedArtist,
)

REPORT_SCHEMA_VERSION = "profile-analysis-v3"
TemperamentRule = Literal[
    "recurring-percussion-synthesizers", "electric-plucked-strings",
    "recurring-sampled", "recurring-electronic", "dominant-acoustic",
    "dominant-electric", "dominant-electronic", "dominant-sampled", "dominant-hybrid",
]


class AnalysisSummary(ApiModel):
    status: AnalysisStatus
    data_source: Literal["mock", "hybrid", "catalog"]
    history_source: Literal["lastfm", "mock"]
    instrumentation_source: Literal["catalog", "mock"]
    methodology_version: str
    catalog_version: str | None = None
    coverage_tracks: float = Field(ge=0, le=1)
    coverage_plays: float = Field(ge=0, le=1)
    recording_status_counts: RecordingStatusCounts
    section_availability: SectionAvailabilitySummary
    vocal_presence: VocalPresence
    image_catalog_version: str


class AnalysisImage(ApiModel):
    asset_id: str
    resolution: Literal["exact", "related", "family"]
    depicted_instrument_slug: str
    depicted_name: str
    family_name: str
    alt: str | None = None
    variants: list[ImageVariant]
    tone: ImageTone
    credit: ImageCredit


class FamilyPresence(ApiModel):
    slug: str
    name: str
    share: float = Field(ge=0, le=1)
    evidence_count: int = Field(ge=0)
    confidence: Confidence
    image: AnalysisImage | None = None
    tone: ImageTone | None = None


class Discovery(ApiModel):
    instrument_slug: str
    instrument_name: str
    image: AnalysisImage | None = None


class Temperament(ApiModel):
    rule: TemperamentRule
    primary_family_slug: str
    primary_nature: SoundNature


class RecordingAnalysis(ApiModel):
    title: str
    artist: str
    play_count: int = Field(ge=0)
    mbid: str | None = None
    lastfm_url: str | None = None
    status: RecordingStatus


class PaletteReport(ApiModel):
    profile: ProfileSummary
    analysis: AnalysisSummary
    recordings: list[RecordingAnalysis]
    families: list[FamilyPresence]
    sound_balance: SoundBalance | None = None
    discovery: Discovery | None = None
    temperament: Temperament | None = None


class ArtistVocabulary(ApiModel):
    status: AnalysisV2Status
    methodology_version: str
    availability: VocabularyAvailability
    reach: VocabularyReach
    concentration: float = Field(ge=0, le=1)
    families: list[VocabularyFamily] = Field(default_factory=list)
    featured_artists: list[VocabularyFeaturedArtist] = Field(default_factory=list, max_length=3)


class ProfileAnalysisV3(ApiModel):
    report_schema_version: Literal["profile-analysis-v3"] = REPORT_SCHEMA_VERSION
    is_example: bool = False
    example_id: str | None = None
    profile: ProfileSummary
    snapshot: SnapshotInfo
    track_palette: PaletteReport
    artist_vocabulary: ArtistVocabulary
    available_views: list[AnalysisView]
    default_view: AnalysisView | None
    hydration: HydrationSummary
