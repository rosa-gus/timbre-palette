from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ListeningPeriod(str, Enum):
    OVERALL = "overall"
    SEVEN_DAYS = "7day"
    ONE_MONTH = "1month"
    THREE_MONTHS = "3month"
    SIX_MONTHS = "6month"
    TWELVE_MONTHS = "12month"


class Confidence(str, Enum):
    DOCUMENTED = "documented"
    STRONGLY_ASSOCIATED = "strongly_associated"
    ESTIMATED = "estimated"


class SoundNature(str, Enum):
    ACOUSTIC = "acoustic"
    ELECTRIC = "electric"
    ELECTRONIC = "electronic"
    SAMPLED = "sampled"
    HYBRID = "hybrid"


class ClaimLevel(str, Enum):
    INSTRUMENT = "instrument"
    FAMILY = "family"


class DataSource(str, Enum):
    LASTFM = "lastfm"
    CATALOG = "catalog"
    MOCK = "mock"


class EvidenceConfidence(str, Enum):
    DOCUMENTED = "documented"
    EDITORIALLY_VERIFIED = "editorially_verified"
    RELEASE_CONTEXT = "release_context"
    TENTATIVE = "tentative"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class EnrichmentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AnalysisStatus(str, Enum):
    PARTIAL = "partial"
    READY = "ready"
    INSUFFICIENT = "insufficient"


class RecordingStatus(str, Enum):
    """Public state of one recording inside a palette analysis.

    The values intentionally distinguish work that may still progress from
    terminal or editorial states.  The API uses these states instead of
    requiring clients to infer progress from a message string.
    """

    RESOLVED = "resolved"
    PENDING_ENRICHMENT = "pending_enrichment"
    AMBIGUOUS = "ambiguous"
    RESOLVED_WITHOUT_EVIDENCE = "resolved_without_evidence"
    TRANSIENT_FAILURE = "transient_failure"
    TERMINAL_FAILURE = "terminal_failure"


@dataclass(frozen=True, slots=True)
class InstrumentLayer:
    slug: str
    name: str
    family_slug: str
    family_name: str
    nature: SoundNature | None
    role: str
    confidence: Confidence
    prominence: float = 1.0
    unexpected: bool = False
    claim_level: ClaimLevel = ClaimLevel.INSTRUMENT


@dataclass(frozen=True, slots=True)
class Track:
    title: str
    artist: str
    play_count: int
    mbid: str | None = None
    lastfm_url: str | None = None
    layers: tuple[InstrumentLayer, ...] = ()
    recording_status: RecordingStatus | None = None
    recording_status_detail: str | None = None
    release_mbid: str | None = None
    artist_mbid: str | None = None


@dataclass(frozen=True, slots=True)
class ListeningHistory:
    username: str
    period: ListeningPeriod
    tracks: tuple[Track, ...]
    history_source: DataSource = DataSource.MOCK
    instrumentation_source: DataSource = DataSource.MOCK
    pending_enrichment: tuple[Track, ...] = ()
    catalog_version: str | None = None


class ListeningHistoryProvider(Protocol):
    async def get_history(
        self,
        username: str,
        period: ListeningPeriod,
    ) -> ListeningHistory: ...


class InstrumentationProvider(Protocol):
    async def enrich(self, history: ListeningHistory) -> ListeningHistory: ...


class EnrichmentScheduler(Protocol):
    async def schedule(self, tracks: tuple[Track, ...]) -> None: ...
