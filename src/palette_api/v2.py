"""API v2 analysis domain and its D1 snapshot projection reader.

The HTTP Worker reads only compact, versioned D1 projections. R2 is read by
the snapshot hydrator and is intentionally not a dependency of this module or
of the public request path.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from palette_api.application import EmptyListeningHistoryError, PaletteService
from palette_api.domain import (
    ClaimLevel,
    Confidence,
    DataSource,
    InstrumentLayer,
    ListeningHistory,
    ListeningHistoryProvider,
    ListeningPeriod,
    RecordingStatus,
    SoundNature,
    Track,
)
from palette_api.image_catalog import DEFAULT_IMAGE_CATALOG, InstrumentImageCatalog
from palette_api.schemas import (
    ArtistVocabulary,
    HydrationSummary,
    PaletteReport,
    ProfileAnalysisV2,
    SnapshotInfo,
    VocabularyAvailability,
    VocabularyEvidence,
    VocabularyFamily,
    VocabularyInstrument,
    VocabularyReach,
)


VOCABULARY_METHODOLOGY_VERSION = "artist-vocabulary-candidate-1"
SNAPSHOT_SCHEMA_VERSION = "musicbrainz-instrument-credits-serving-v2"
MIN_QUALIFYING_RECORDINGS = 3
MIN_REACH = 0.40
MIN_QUALIFIED_ARTISTS = 4
MAX_ARTIST_WEIGHT = 0.40
MAX_ARTIST_CONCENTRATION = 0.70


class SnapshotUnavailableError(RuntimeError):
    """Raised when D1 has no active, usable MusicBrainz snapshot."""


@dataclass(frozen=True, slots=True)
class HydrationTarget:
    kind: str
    mbid: str


@dataclass(frozen=True, slots=True)
class SnapshotVocabularyRow:
    artist_mbid: str
    instrument_slug: str
    instrument_name: str
    family_slug: str
    family_name: str
    distinct_recordings: int
    documented_recordings: int
    prevalence: float
    evidence_quality: float
    source_scope: str


@dataclass(frozen=True, slots=True)
class SnapshotPreparation:
    snapshot: SnapshotInfo
    history: ListeningHistory
    vocabulary_rows: tuple[SnapshotVocabularyRow, ...]
    pending_artist_mbids: frozenset[str]
    targets: tuple[HydrationTarget, ...]


class SnapshotProjectionProvider(Protocol):
    async def prepare(self, history: ListeningHistory) -> SnapshotPreparation: ...


class SnapshotHydrationScheduler(Protocol):
    async def schedule(
        self,
        snapshot_version: str,
        targets: tuple[HydrationTarget, ...],
    ) -> None: ...


class MockSnapshotProjectionProvider:
    """Deterministic provider for local API development.

    Mock listening fixtures already contain direct layers.  Keeping those
    fixtures in the v2 provider makes the endpoint usable without D1 while
    still exercising the real v2 envelope and methodology code.
    """

    async def prepare(self, history: ListeningHistory) -> SnapshotPreparation:
        snapshot = SnapshotInfo(
            snapshot_version="mock-20260912",
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            manifest_hash="mock",
            object_prefix="mock",
            methodology_version=VOCABULARY_METHODOLOGY_VERSION,
        )
        return SnapshotPreparation(
            snapshot=snapshot,
            history=history,
            vocabulary_rows=(),
            pending_artist_mbids=frozenset(),
            targets=(),
        )


class D1SnapshotProjectionProvider:
    """Read the active snapshot projection with bounded D1 queries."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def prepare(self, history: ListeningHistory) -> SnapshotPreparation:
        snapshot = await self._active_snapshot()
        track_mbids = tuple(
            sorted({track.mbid.strip().lower() for track in history.tracks if track.mbid})
        )
        aliases = await self._aliases(snapshot.snapshot_version, track_mbids)
        canonical_by_track = {
            mbid: aliases.get(mbid, mbid) for mbid in track_mbids
        }
        recording_mbids = tuple(sorted(set(canonical_by_track.values())))
        statuses = await self._recording_statuses(
            snapshot.snapshot_version, recording_mbids
        )
        layers_by_recording = await self._recording_layers(
            snapshot.snapshot_version, recording_mbids
        )

        targets: list[HydrationTarget] = []
        enriched_tracks: list[Track] = []
        for track in history.tracks:
            source_mbid = track.mbid.strip().lower() if track.mbid else None
            canonical_mbid = canonical_by_track.get(source_mbid) if source_mbid else None
            layers = layers_by_recording.get(canonical_mbid or "", ())
            state = statuses.get(canonical_mbid or "")
            if layers:
                status = RecordingStatus.RESOLVED
            elif state == "complete_empty":
                status = RecordingStatus.RESOLVED_WITHOUT_EVIDENCE
            elif state == "failed":
                status = RecordingStatus.TRANSIENT_FAILURE
            else:
                status = RecordingStatus.PENDING_ENRICHMENT
                if source_mbid:
                    targets.append(
                        HydrationTarget(
                            "recording" if source_mbid in statuses else "track",
                            source_mbid,
                        )
                    )
            enriched_tracks.append(
                Track(
                    title=track.title,
                    artist=track.artist,
                    play_count=track.play_count,
                    mbid=track.mbid,
                    lastfm_url=track.lastfm_url,
                    layers=layers,
                    recording_status=status,
                    recording_status_detail=track.recording_status_detail,
                    release_mbid=track.release_mbid,
                    artist_mbid=track.artist_mbid,
                )
            )

        enriched_history = ListeningHistory(
            username=history.username,
            period=history.period,
            tracks=tuple(enriched_tracks),
            history_source=history.history_source,
            instrumentation_source=DataSource.CATALOG,
            pending_enrichment=tuple(
                track
                for track in enriched_tracks
                if track.recording_status
                in {
                    RecordingStatus.PENDING_ENRICHMENT,
                    RecordingStatus.TRANSIENT_FAILURE,
                }
            ),
            catalog_version=snapshot.snapshot_version,
        )

        artist_mbids = tuple(
            sorted({
                track.artist_mbid.strip().lower()
                for track in history.tracks
                if track.artist_mbid
            })
        )
        vocabulary_rows, artist_statuses = await self._artist_vocabulary(
            snapshot.snapshot_version, artist_mbids
        )
        pending_artists = frozenset(
            artist_mbid
            for artist_mbid in artist_mbids
            if artist_statuses.get(artist_mbid) not in {"complete", "complete_empty"}
        )
        for artist_mbid in pending_artists:
            targets.append(HydrationTarget("artist", artist_mbid))

        return SnapshotPreparation(
            snapshot=snapshot,
            history=enriched_history,
            vocabulary_rows=tuple(vocabulary_rows),
            pending_artist_mbids=pending_artists,
            targets=tuple(dict.fromkeys(targets)),
        )

    async def _active_snapshot(self) -> SnapshotInfo:
        row = await _first(
            self._db.prepare(
                """
                SELECT snapshot_version, index_schema_version, manifest_hash,
                       object_prefix, methodology_version
                FROM musicbrainz_credit_index_snapshots
                WHERE status = 'active'
                ORDER BY published_at DESC, created_at DESC
                LIMIT 1
                """
            )
        )
        if row is None:
            raise SnapshotUnavailableError("No active MusicBrainz snapshot is published.")
        snapshot_version = _text(_value(row, "snapshot_version"))
        schema_version = _text(_value(row, "index_schema_version"))
        manifest_hash = _text(_value(row, "manifest_hash"))
        object_prefix = _text(_value(row, "object_prefix"))
        if not snapshot_version or not schema_version or not manifest_hash or not object_prefix:
            raise SnapshotUnavailableError("The active MusicBrainz snapshot is incomplete.")
        if schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise SnapshotUnavailableError(
                f"Unsupported active MusicBrainz snapshot schema: {schema_version}."
            )
        return SnapshotInfo(
            snapshot_version=snapshot_version,
            schema_version=schema_version,
            manifest_hash=manifest_hash,
            object_prefix=object_prefix,
            methodology_version=(
                _text(_value(row, "methodology_version"))
                or VOCABULARY_METHODOLOGY_VERSION
            ),
        )

    async def _aliases(
        self,
        snapshot_version: str,
        mbids: tuple[str, ...],
    ) -> dict[str, str]:
        if not mbids:
            return {}
        rows = await _all_rows(
            self._db.prepare(
                """
                SELECT track_mbid, recording_mbid
                FROM snapshot_track_aliases
                WHERE snapshot_version = ?
                  AND track_mbid IN (SELECT value FROM json_each(?))
                """
            ).bind(snapshot_version, json.dumps(mbids))
        )
        return {
            _text(_value(row, "track_mbid")).lower(): _text(
                _value(row, "recording_mbid")
            ).lower()
            for row in rows
            if _text(_value(row, "track_mbid")) and _text(_value(row, "recording_mbid"))
        }

    async def _recording_statuses(
        self,
        snapshot_version: str,
        mbids: tuple[str, ...],
    ) -> dict[str, str]:
        if not mbids:
            return {}
        rows = await _all_rows(
            self._db.prepare(
                """
                SELECT recording_mbid, status
                FROM snapshot_recordings
                WHERE snapshot_version = ?
                  AND recording_mbid IN (SELECT value FROM json_each(?))
                """
            ).bind(snapshot_version, json.dumps(mbids))
        )
        return {
            _text(_value(row, "recording_mbid")).lower(): _text(_value(row, "status"))
            for row in rows
            if _text(_value(row, "recording_mbid"))
        }

    async def _recording_layers(
        self,
        snapshot_version: str,
        mbids: tuple[str, ...],
    ) -> dict[str, tuple[InstrumentLayer, ...]]:
        if not mbids:
            return {}
        rows = await _all_rows(
            self._db.prepare(
                """
                SELECT projection.recording_mbid, projection.instrument_slug,
                       projection.family_slug, instruments.name AS instrument_name,
                       families.name AS family_name,
                       instruments.sound_nature AS sound_nature
                FROM snapshot_recording_instruments AS projection
                JOIN instruments ON instruments.slug = projection.instrument_slug
                JOIN instrument_families AS families
                  ON families.slug = projection.family_slug
                WHERE projection.snapshot_version = ?
                  AND projection.recording_mbid IN (SELECT value FROM json_each(?))
                  AND projection.scope IN ('recording', 'track')
                ORDER BY projection.recording_mbid, projection.instrument_slug
                """
            ).bind(snapshot_version, json.dumps(mbids))
        )
        layers: dict[str, dict[str, InstrumentLayer]] = defaultdict(dict)
        for row in rows:
            recording_mbid = _text(_value(row, "recording_mbid")).lower()
            instrument_slug = _text(_value(row, "instrument_slug"))
            family_slug = _text(_value(row, "family_slug"))
            if not recording_mbid or not instrument_slug or not family_slug:
                continue
            layer = InstrumentLayer(
                slug=instrument_slug,
                name=_text(_value(row, "instrument_name")) or instrument_slug,
                family_slug=family_slug,
                family_name=_text(_value(row, "family_name")) or family_slug,
                nature=_sound_nature(_value(row, "sound_nature")),
                role="",
                confidence=Confidence.DOCUMENTED,
                claim_level=ClaimLevel.INSTRUMENT,
            )
            layers[recording_mbid][instrument_slug] = layer
        return {
            recording_mbid: tuple(values.values())
            for recording_mbid, values in layers.items()
        }

    async def _artist_vocabulary(
        self,
        snapshot_version: str,
        artist_mbids: tuple[str, ...],
    ) -> tuple[list[SnapshotVocabularyRow], dict[str, str]]:
        if not artist_mbids:
            return [], {}
        statuses = await _all_rows(
            self._db.prepare(
                """
                SELECT artist_mbid, status
                FROM snapshot_artists
                WHERE snapshot_version = ?
                  AND artist_mbid IN (SELECT value FROM json_each(?))
                """
            ).bind(snapshot_version, json.dumps(artist_mbids))
        )
        status_by_artist = {
            _text(_value(row, "artist_mbid")).lower(): _text(_value(row, "status"))
            for row in statuses
            if _text(_value(row, "artist_mbid"))
        }
        rows = await _all_rows(
            self._db.prepare(
                """
                SELECT projection.artist_mbid, projection.instrument_slug,
                       projection.family_slug, instruments.name AS instrument_name,
                       families.name AS family_name, projection.distinct_recordings,
                       projection.documented_recordings, projection.prevalence,
                       projection.evidence_quality, projection.source_scope
                FROM snapshot_artist_instruments AS projection
                JOIN instruments ON instruments.slug = projection.instrument_slug
                JOIN instrument_families AS families
                  ON families.slug = projection.family_slug
                WHERE projection.snapshot_version = ?
                  AND projection.artist_mbid IN (SELECT value FROM json_each(?))
                ORDER BY projection.artist_mbid, projection.instrument_slug
                """
            ).bind(snapshot_version, json.dumps(artist_mbids))
        )
        values = [
            SnapshotVocabularyRow(
                artist_mbid=_text(_value(row, "artist_mbid")).lower(),
                instrument_slug=_text(_value(row, "instrument_slug")),
                instrument_name=_text(_value(row, "instrument_name")),
                family_slug=_text(_value(row, "family_slug")),
                family_name=_text(_value(row, "family_name")),
                distinct_recordings=int(_value(row, "distinct_recordings") or 0),
                documented_recordings=int(_value(row, "documented_recordings") or 0),
                prevalence=float(_value(row, "prevalence") or 0),
                evidence_quality=float(_value(row, "evidence_quality") or 0),
                source_scope=_text(_value(row, "source_scope")) or "recording",
            )
            for row in rows
            if _text(_value(row, "artist_mbid"))
        ]
        return values, status_by_artist


class D1SnapshotHydrationScheduler:
    """Record missing snapshot targets for the private Queue producer."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def schedule(
        self,
        snapshot_version: str,
        targets: tuple[HydrationTarget, ...],
    ) -> None:
        unique = tuple(dict.fromkeys(targets))
        if not unique:
            return
        payload = json.dumps(
            [
                {
                    "kind": target.kind,
                    "mbid": target.mbid,
                    "shard": _shard_key(target.kind, target.mbid),
                }
                for target in unique
            ]
        )
        await _run(
            self._db.prepare(
                """
                INSERT OR IGNORE INTO snapshot_hydration_jobs
                    (snapshot_version, target_kind, target_mbid, shard_key)
                SELECT ?,
                       json_extract(value, '$.kind'),
                       json_extract(value, '$.mbid'),
                       json_extract(value, '$.shard')
                FROM json_each(?)
                """
            ).bind(snapshot_version, payload)
        )


class VocabularyAnalyzer:
    """Pure methodology for the artist-vocabulary product."""

    def __init__(
        self,
        *,
        min_recordings: int = MIN_QUALIFYING_RECORDINGS,
        min_reach: float = MIN_REACH,
        min_qualified_artists: int = MIN_QUALIFIED_ARTISTS,
        max_artist_weight: float = MAX_ARTIST_WEIGHT,
        max_artist_concentration: float = MAX_ARTIST_CONCENTRATION,
    ) -> None:
        self.min_recordings = min_recordings
        self.min_reach = min_reach
        self.min_qualified_artists = min_qualified_artists
        self.max_artist_weight = max_artist_weight
        self.max_artist_concentration = max_artist_concentration

    def analyze(
        self,
        history: ListeningHistory,
        snapshot: SnapshotInfo,
        rows: tuple[SnapshotVocabularyRow, ...],
        pending_artist_mbids: frozenset[str],
    ) -> ArtistVocabulary:
        total_tracks = len(history.tracks)
        total_plays = sum(track.play_count for track in history.tracks)
        artist_keys = {
            (track.artist_mbid or f"name:{track.artist.casefold().strip()}").lower()
            for track in history.tracks
        }
        qualified_rows = [
            row for row in rows if row.distinct_recordings >= self.min_recordings
        ]
        rows_by_artist_family: dict[tuple[str, str], list[SnapshotVocabularyRow]] = defaultdict(list)
        for row in qualified_rows:
            rows_by_artist_family[(row.artist_mbid, row.family_slug)].append(row)
        qualified_artists = {
            artist_mbid for artist_mbid, _family in rows_by_artist_family
        }
        qualified_track_count = sum(
            1
            for track in history.tracks
            if (track.artist_mbid or "").strip().lower() in qualified_artists
        )
        qualified_play_count = sum(
            track.play_count
            for track in history.tracks
            if (track.artist_mbid or "").strip().lower() in qualified_artists
        )
        track_reach = qualified_track_count / total_tracks if total_tracks else 0
        play_reach = qualified_play_count / total_plays if total_plays else 0
        reach = VocabularyReach(
            track_reach=round(track_reach, 4),
            play_reach=round(play_reach, 4),
            qualified_artists=len(qualified_artists),
            total_artists=len(artist_keys),
            qualified_tracks=qualified_track_count,
            total_tracks=total_tracks,
            qualified_plays=qualified_play_count,
            total_plays=total_plays,
        )

        artist_plays: dict[str, int] = defaultdict(int)
        for track in history.tracks:
            if track.artist_mbid:
                artist_plays[track.artist_mbid.lower()] += track.play_count
        family_scores: dict[str, float] = defaultdict(float)
        family_rows: dict[str, list[SnapshotVocabularyRow]] = defaultdict(list)
        artist_scores: dict[str, float] = defaultdict(float)
        for (artist_mbid, family_slug), family_instruments in rows_by_artist_family.items():
            best = max(family_instruments, key=lambda row: row.prevalence)
            raw_weight = (
                artist_plays.get(artist_mbid, 0) / total_plays if total_plays else 0
            )
            contribution = (
                min(raw_weight, self.max_artist_weight)
                * best.prevalence
                * best.evidence_quality
            )
            family_scores[family_slug] += contribution
            artist_scores[artist_mbid] += contribution
            family_rows[family_slug].extend(family_instruments)

        total_score = sum(family_scores.values())
        concentration = (
            max(artist_scores.values()) / total_score
            if total_score and artist_scores
            else 0
        )
        families = []
        for family_slug, score in sorted(
            family_scores.items(), key=lambda item: (-item[1], item[0])
        ):
            family_instruments = _unique_instruments(family_rows[family_slug])
            families.append(
                VocabularyFamily(
                    slug=family_slug,
                    name=family_instruments[0].family_name,
                    score=round(score, 6),
                    share=round(score / total_score, 6) if total_score else 0,
                    prevalence=round(
                        max(row.prevalence for row in family_rows[family_slug]), 4
                    ),
                    supporting_artists=len({
                        row.artist_mbid for row in family_rows[family_slug]
                    }),
                    instruments=[
                        VocabularyInstrument(
                            slug=row.instrument_slug,
                            name=row.instrument_name,
                            distinct_recordings=row.distinct_recordings,
                            documented_recordings=row.documented_recordings,
                            prevalence=round(row.prevalence, 4),
                            evidence=VocabularyEvidence(
                                source="musicbrainz_snapshot",
                                scope=(
                                    "track"
                                    if row.source_scope == "track"
                                    else "recording"
                                ),
                                snapshot_version=snapshot.snapshot_version,
                                quality=round(row.evidence_quality, 4),
                                documented_recordings=row.documented_recordings,
                            ),
                        )
                        for row in family_instruments
                    ],
                )
            )

        required_artists = min(self.min_qualified_artists, len(artist_keys))
        reason = "available"
        status = "available"
        if pending_artist_mbids:
            status, reason = "pending", "snapshot_hydration_pending"
        elif not qualified_rows:
            status, reason = "insufficient", "no_mapped_evidence"
        elif track_reach < self.min_reach:
            status, reason = "insufficient", "insufficient_track_reach"
        elif play_reach < self.min_reach:
            status, reason = "insufficient", "insufficient_play_reach"
        elif len(qualified_artists) < required_artists:
            status, reason = "insufficient", "insufficient_artist_diversity"
        elif concentration > self.max_artist_concentration:
            status, reason = "insufficient", "excessive_artist_concentration"

        return ArtistVocabulary(
            status=status,
            methodology_version=VOCABULARY_METHODOLOGY_VERSION,
            availability=VocabularyAvailability(
                status=status,
                reason=reason,
                pending_artists=len(pending_artist_mbids),
                pending_tracks=0,
            ),
            reach=reach,
            concentration=round(concentration, 4),
            families=families,
            notice=(
                "Recorre em gravações documentadas destes artistas; não descreve "
                "necessariamente cada faixa ou a presença de um instrumento no áudio."
            ),
        )


class V2AnalysisService:
    """Compose direct palette and artist vocabulary without mixing products."""

    def __init__(
        self,
        history_provider: ListeningHistoryProvider,
        snapshot_provider: SnapshotProjectionProvider,
        hydration_scheduler: SnapshotHydrationScheduler | None = None,
        vocabulary_analyzer: VocabularyAnalyzer | None = None,
        image_catalog: InstrumentImageCatalog = DEFAULT_IMAGE_CATALOG,
    ) -> None:
        self._history_provider = history_provider
        self._snapshot_provider = snapshot_provider
        self._hydration_scheduler = hydration_scheduler
        self._vocabulary_analyzer = vocabulary_analyzer or VocabularyAnalyzer()
        self._image_catalog = image_catalog

    async def analyze(
        self,
        username: str,
        period: ListeningPeriod,
    ) -> ProfileAnalysisV2:
        history = await self._history_provider.get_history(username, period)
        if not history.tracks:
            raise EmptyListeningHistoryError(username)
        preparation = await self._snapshot_provider.prepare(history)
        if self._hydration_scheduler is not None:
            await self._hydration_scheduler.schedule(
                preparation.snapshot.snapshot_version,
                preparation.targets,
            )

        palette = PaletteService(
            history_provider=self._history_provider,
            image_catalog=self._image_catalog,
        ).build_report(
            preparation.history
        )
        vocabulary = self._vocabulary_analyzer.analyze(
            history,
            preparation.snapshot,
            preparation.vocabulary_rows,
            preparation.pending_artist_mbids,
        )
        palette_available = palette.analysis.status in {
            "ready",
            "partial",
        } and palette.analysis.section_availability.families == "available"
        vocabulary_available = vocabulary.status == "available"
        available_views = []
        if palette_available:
            available_views.append("track_palette")
        if vocabulary_available:
            available_views.append("artist_vocabulary")
        default_view = (
            "track_palette"
            if palette_available
            else "artist_vocabulary"
            if vocabulary_available
            else None
        )
        pending_recordings = sum(
            target.kind in {"track", "recording"}
            for target in preparation.targets
        )
        pending_aliases = sum(target.kind == "track" for target in preparation.targets)
        pending_artists = sum(target.kind == "artist" for target in preparation.targets)
        return ProfileAnalysisV2(
            profile=palette.profile,
            snapshot=preparation.snapshot,
            track_palette=palette,
            artist_vocabulary=vocabulary,
            available_views=available_views,
            default_view=default_view,
            hydration=HydrationSummary(
                status="pending"
                if preparation.targets
                else "complete",
                pending_recordings=pending_recordings,
                pending_artists=pending_artists,
                pending_aliases=pending_aliases,
            ),
        )


def _unique_instruments(rows: list[SnapshotVocabularyRow]) -> list[SnapshotVocabularyRow]:
    unique: dict[str, SnapshotVocabularyRow] = {}
    for row in rows:
        current = unique.get(row.instrument_slug)
        if current is None or row.prevalence > current.prevalence:
            unique[row.instrument_slug] = row
    return [unique[key] for key in sorted(unique)]


def _shard_key(kind: str, mbid: str) -> str:
    width = 3 if kind == "artist" else 4
    return mbid.strip().lower()[:width]


def _sound_nature(value: object) -> SoundNature | None:
    try:
        return SoundNature(str(value)) if value else None
    except ValueError:
        return None


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    value = getattr(row, key, None)
    if value is not None:
        return value
    try:
        return row[key]
    except Exception:
        return default


async def _first(statement: Any) -> Any:
    method = getattr(statement, "first", None)
    return await method() if callable(method) else None


async def _all_rows(statement: Any) -> list[Any]:
    method = getattr(statement, "all", None)
    result = await method() if callable(method) else None
    if result is None:
        return []
    rows = getattr(result, "results", result)
    return list(rows) if rows else []


async def _run(statement: Any) -> Any:
    method = getattr(statement, "run", None)
    if not callable(method):
        raise RuntimeError("The D1 binding does not provide command execution.")
    return await method()
