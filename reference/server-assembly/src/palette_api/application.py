from collections import Counter, defaultdict
from dataclasses import dataclass

from palette_api.domain import (
    AnalysisStatus,
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
from palette_api.methodology import DEFAULT_METHODOLOGY, MethodologyPolicy
from palette_api.image_catalog import DEFAULT_IMAGE_CATALOG, InstrumentImageCatalog
from palette_api.report import (
    AnalysisSummary, Discovery, FamilyPresence, AnalysisImage, PaletteReport,
    RecordingAnalysis, Temperament, TemperamentRule,
)
from palette_api.schemas import (
    ImageCredit,
    ImageVariant,
    ImageTone,
    ProfileSummary,
    RecordingStatusCounts,
    SectionAvailabilitySummary,
    SoundBalance,
    VocalPresence,
)


CONFIDENCE_WEIGHT = {
    Confidence.DOCUMENTED: 1.0,
    Confidence.STRONGLY_ASSOCIATED: 0.75,
    Confidence.ESTIMATED: 0.45,
}

METHODOLOGY_VERSION = DEFAULT_METHODOLOGY.version


class EmptyListeningHistoryError(Exception):
    pass


@dataclass(slots=True)
class _DiscoveryCandidate:
    layer: InstrumentLayer
    tracks: set[tuple[str, str, str]]
    artists: set[str]
    plays: int = 0



@dataclass(frozen=True, slots=True)
class _TemperamentSignals:
    family_shares: dict[str, float]
    family_track_sets: dict[str, frozenset[tuple[str, str, str]]]
    pair_track_share: dict[tuple[str, str], float]
    nature_shares: dict[SoundNature, float]


class PaletteService:
    def __init__(
        self,
        history_provider: ListeningHistoryProvider,
        methodology: MethodologyPolicy = DEFAULT_METHODOLOGY,
        image_catalog: InstrumentImageCatalog = DEFAULT_IMAGE_CATALOG,
    ) -> None:
        self._history_provider = history_provider
        self._methodology = methodology
        self._image_catalog = image_catalog

    async def analyze(
        self,
        username: str,
        period: ListeningPeriod,
    ) -> PaletteReport:
        history = await self._history_provider.get_history(username, period)
        if not history.tracks:
            raise EmptyListeningHistoryError(username)
        return self._build_report(history)

    def build_report(self, history: ListeningHistory) -> PaletteReport:
        """Build the direct-evidence report from an already prepared history.

        API v2 performs one Last.fm read and prepares both direct evidence and
        artist vocabulary from the same history.  Keeping this entry point
        public avoids fetching the profile twice while preserving the existing
        direct-palette calculation in one place.
        """
        if not history.tracks:
            raise EmptyListeningHistoryError(history.username)
        return self._build_report(history)

    def _build_report(self, history: ListeningHistory) -> PaletteReport:
        recording_statuses = tuple(
            self._recording_status(track, history) for track in history.tracks
        )
        status_counts = Counter(recording_statuses)
        total_tracks = len(history.tracks)
        total_plays = sum(track.play_count for track in history.tracks)
        covered_history = tuple(track for track in history.tracks if track.layers)
        covered_tracks = len(covered_history)
        covered_plays = sum(track.play_count for track in covered_history)
        coverage_tracks = round(covered_tracks / total_tracks, 4)
        coverage_plays = round(covered_plays / total_plays, 4) if total_plays else 0
        vocal_presence = self._calculate_vocal_presence(
            history.tracks,
            total_tracks=total_tracks,
            total_plays=total_plays,
        )
        covered_artists = {self._artist_key(track.artist) for track in covered_history}
        all_artists = {self._artist_key(track.artist) for track in history.tracks}
        palette_ready = self._methodology.meets_palette_gate(
            coverage_tracks=coverage_tracks,
            coverage_plays=coverage_plays,
            covered_tracks=covered_tracks,
            total_tracks=total_tracks,
            covered_artists=len(covered_artists),
            total_artists=len(all_artists),
        )
        palette_coverage_ready = self._methodology.meets_coverage_floor(
            coverage_tracks=coverage_tracks,
            coverage_plays=coverage_plays,
            covered_tracks=covered_tracks,
            total_tracks=total_tracks,
            track_ratio=self._methodology.palette_track_ratio,
            play_ratio=self._methodology.palette_play_ratio,
            track_floor=self._methodology.palette_track_floor,
        )
        interpretation_ready = self._methodology.meets_interpretation_gate(
            coverage_tracks=coverage_tracks,
            coverage_plays=coverage_plays,
            covered_tracks=covered_tracks,
            total_tracks=total_tracks,
            covered_artists=len(covered_artists),
            total_artists=len(all_artists),
        )
        interpretation_coverage_ready = self._methodology.meets_coverage_floor(
            coverage_tracks=coverage_tracks,
            coverage_plays=coverage_plays,
            covered_tracks=covered_tracks,
            total_tracks=total_tracks,
            track_ratio=self._methodology.interpretation_track_ratio,
            play_ratio=self._methodology.interpretation_play_ratio,
            track_floor=self._methodology.interpretation_track_floor,
        )
        status = self._methodology.status(
            palette_ready=palette_ready,
            has_published_evidence=covered_tracks > 0,
        )

        profile = ProfileSummary(
            username=history.username,
            period=history.period,
            tracks_analyzed=total_tracks,
            total_plays=total_plays,
            profile_url=history.profile.profile_url if history.profile else None,
            avatar_url=history.profile.avatar_url if history.profile else None,
            realname=history.profile.realname if history.profile else None,
            registered=history.profile.registered if history.profile else None,
        )
        recording_items = sorted(
            zip(history.tracks, recording_statuses, strict=True),
            key=lambda item: (
                self._artist_key(item[0].artist),
                self._title_key(item[0].title),
                item[0].mbid or "",
            ),
        )
        recordings = [
            RecordingAnalysis(
                title=track.title,
                artist=track.artist,
                play_count=track.play_count,
                mbid=track.mbid,
                lastfm_url=track.lastfm_url,
                status=recording_status,
            )
            for track, recording_status in recording_items
        ]

        if not palette_ready and covered_tracks == 0:
            availability = self._unavailable_sections(
                reason=(
                    "insufficient_diversity"
                    if palette_coverage_ready
                    else "insufficient_coverage"
                ),
            )
            analysis = self._analysis_summary(
                history=history,
                status=status,
                coverage_tracks=coverage_tracks,
                coverage_plays=coverage_plays,
                status_counts=status_counts,
                availability=availability,
                vocal_presence=vocal_presence,
            )
            return PaletteReport(
                profile=profile,
                analysis=analysis,
                recordings=recordings,
                families=[],
            )

        families, sound_balance, nature_scores = self._calculate_palette(covered_history)
        families = [
            family.model_copy(update={
                "image": self._image(family.slug, family.slug),
                "tone": self._tone(family.slug),
            })
            for family in families
        ]
        discovery_layer = (
            self._select_discovery(covered_history) if interpretation_ready else None
        )
        temperament = (
            self._build_temperament(
                families,
                nature_scores,
                sound_balance,
                covered_history,
            )
            if interpretation_ready
            and sound_balance is not None
            and self._temperament_is_supported(families)
            and nature_scores
            else None
        )
        availability = self._section_availability(
            interpretation_ready=interpretation_ready,
            sound_balance=sound_balance,
            discovery=discovery_layer,
            temperament=temperament,
            interpretation_coverage_ready=interpretation_coverage_ready,
        )
        analysis = self._analysis_summary(
            history=history,
            status=status,
            coverage_tracks=coverage_tracks,
            coverage_plays=coverage_plays,
            status_counts=status_counts,
            availability=availability,
            vocal_presence=vocal_presence,
        )
        return PaletteReport(
            profile=profile,
            analysis=analysis,
            recordings=recordings,
            families=families,
            sound_balance=sound_balance,
            discovery=(
                Discovery(
                    instrument_slug=discovery_layer.slug,
                    instrument_name=discovery_layer.name,
                    image=self._image(discovery_layer.slug, discovery_layer.family_slug),
                )
                if discovery_layer is not None
                else None
            ),
            temperament=temperament,
        )

    def _calculate_palette(
        self,
        covered_history: tuple[Track, ...],
    ) -> tuple[list[FamilyPresence], SoundBalance | None, dict[SoundNature, float]]:
        family_scores: dict[str, float] = defaultdict(float)
        family_confidence_scores: dict[str, float] = defaultdict(float)
        family_names: dict[str, str] = {}
        family_tracks: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        nature_scores: dict[SoundNature, float] = defaultdict(float)
        known_nature_score = 0.0

        for track in covered_history:
            layers_by_family: dict[str, list[InstrumentLayer]] = defaultdict(list)
            for layer in track.layers:
                layers_by_family[layer.family_slug].append(layer)
                family_names[layer.family_slug] = min(
                    family_names.get(layer.family_slug, layer.family_name),
                    layer.family_name,
                )
            strongest_by_family = {
                family_slug: max(
                    layers,
                    key=lambda layer: (
                        layer.prominence * CONFIDENCE_WEIGHT[layer.confidence],
                        layer.claim_level is ClaimLevel.INSTRUMENT,
                        layer.slug,
                    ),
                )
                for family_slug, layers in layers_by_family.items()
            }
            family_weights = {
                family_slug: layer.prominence * CONFIDENCE_WEIGHT[layer.confidence]
                for family_slug, layer in strongest_by_family.items()
            }
            total_family_weight = sum(family_weights.values())
            if total_family_weight <= 0:
                continue
            track_key = self._track_key(track)
            for family_slug, selected_layer in strongest_by_family.items():
                score = track.play_count * family_weights[family_slug] / total_family_weight
                family_scores[family_slug] += score
                family_confidence_scores[family_slug] += (
                    score * CONFIDENCE_WEIGHT[selected_layer.confidence]
                )
                family_tracks[family_slug].add(track_key)

                nature_layers = [
                    layer
                    for layer in layers_by_family[family_slug]
                    if layer.nature is not None
                ]
                if not nature_layers:
                    continue
                nature_weights: dict[SoundNature, float] = defaultdict(float)
                for layer in nature_layers:
                    nature_weights[layer.nature] += (
                        layer.prominence * CONFIDENCE_WEIGHT[layer.confidence]
                    )
                nature_weight_total = sum(nature_weights.values())
                if nature_weight_total <= 0:
                    continue
                known_nature_score += score
                for nature, nature_weight in nature_weights.items():
                    nature_scores[nature] += score * nature_weight / nature_weight_total

        total_score = sum(family_scores.values())
        ordered_families = sorted(
            family_scores,
            key=lambda slug: (-family_scores[slug], slug),
        )
        families = [
            FamilyPresence(
                slug=slug,
                name=family_names[slug],
                share=round(family_scores[slug] / total_score, 4),
                evidence_count=len(family_tracks[slug]),
                confidence=self._aggregate_confidence(
                    family_confidence_scores[slug] / family_scores[slug]
                ),
            )
            for slug in ordered_families
        ]
        sound_balance = None
        if (
            total_score > 0
            and known_nature_score / total_score >= self._methodology.known_nature_ratio
        ):
            balance_values = {
                nature: round(nature_scores[nature] / total_score, 4)
                for nature in SoundNature
            }
            unknown = round(max(0.0, 1.0 - sum(balance_values.values())), 4)
            sound_balance = SoundBalance(
                acoustic=balance_values[SoundNature.ACOUSTIC],
                electric=balance_values[SoundNature.ELECTRIC],
                electronic=balance_values[SoundNature.ELECTRONIC],
                sampled=balance_values[SoundNature.SAMPLED],
                hybrid=balance_values[SoundNature.HYBRID],
                unknown=unknown,
            )
        return families, sound_balance, nature_scores

    @classmethod
    def _calculate_vocal_presence(
        cls,
        tracks: tuple[Track, ...],
        *,
        total_tracks: int,
        total_plays: int,
    ) -> VocalPresence:
        """Count one vocal presence per recording from documented family claims.

        Vocalists and vocal roles are intentionally collapsed at recording level:
        a recording with lead and backing vocals still contributes one track,
        one artist, and its play count once.
        """

        vocal_tracks = tuple(
            track
            for track in tracks
            if any(
                layer.family_slug == "voice"
                and layer.claim_level is ClaimLevel.FAMILY
                and layer.confidence is Confidence.DOCUMENTED
                for layer in track.layers
            )
        )
        vocal_plays = sum(track.play_count for track in vocal_tracks)
        vocal_artists = {cls._artist_key(track.artist) for track in vocal_tracks}
        return VocalPresence(
            documented_tracks=len(vocal_tracks),
            documented_artists=len(vocal_artists),
            documented_plays=vocal_plays,
            track_ratio=round(len(vocal_tracks) / total_tracks, 4)
            if total_tracks
            else 0,
            play_ratio=round(vocal_plays / total_plays, 4) if total_plays else 0,
        )

    def _select_discovery(
        self, covered_history: tuple[Track, ...]
    ) -> InstrumentLayer | None:
        candidates: dict[str, _DiscoveryCandidate] = {}
        for track in covered_history:
            for layer in track.layers:
                if layer.claim_level is not ClaimLevel.INSTRUMENT:
                    continue
                candidate = candidates.setdefault(
                    layer.slug,
                    _DiscoveryCandidate(layer=layer, tracks=set(), artists=set()),
                )
                if (
                    layer.prominence * CONFIDENCE_WEIGHT[layer.confidence],
                    layer.role,
                ) > (
                    candidate.layer.prominence
                    * CONFIDENCE_WEIGHT[candidate.layer.confidence],
                    candidate.layer.role,
                ):
                    candidate.layer = layer
                candidate.tracks.add(self._track_key(track))
                candidate.artists.add(self._artist_key(track.artist))
                candidate.plays += track.play_count
        total_covered_plays = sum(track.play_count for track in covered_history)
        eligible = [
            candidate
            for candidate in candidates.values()
            if len(candidate.tracks) >= self._methodology.discovery_recording_floor
            and len(candidate.artists) >= self._methodology.discovery_artist_floor
            and (
                candidate.plays / total_covered_plays
                if total_covered_plays
                else 0
            )
            <= self._methodology.discovery_max_play_share
        ]
        if not eligible:
            return None
        eligible.sort(
            key=lambda candidate: (
                candidate.plays / total_covered_plays
                if total_covered_plays
                else 0,
                -len(candidate.tracks),
                -len(candidate.artists),
                candidate.layer.slug,
            )
        )
        return eligible[0].layer

    def _temperament_is_supported(self, families: list[FamilyPresence]) -> bool:
        supported = [
            family
            for family in families
            if family.evidence_count
            >= self._methodology.temperament_family_recording_floor
        ]
        return (
            len(supported) >= 2
            and supported[1].share >= self._methodology.temperament_contrast_share
        )

    def _tone(self, family_slug: str) -> ImageTone | None:
        tone = self._image_catalog.family_tone(family_slug)
        return ImageTone(**tone) if tone else None

    def _image(self, slug: str, family_slug: str | None) -> AnalysisImage | None:
        resolved = self._image_catalog.resolve(slug, family_slug)
        if resolved is None:
            return None
        return AnalysisImage(
            asset_id=resolved.asset_id,
            resolution=resolved.resolution,
            depicted_instrument_slug=resolved.depicted_instrument_slug,
            alt=resolved.authored_alt,
            depicted_name=resolved.depicted_name,
            family_name=resolved.family_name,
            variants=[
                ImageVariant(
                    name="detail",
                    url=resolved.url,
                    width=resolved.width,
                    height=resolved.height,
                )
            ],
            tone=ImageTone(shadow=resolved.shadow, highlight=resolved.highlight),
            credit=ImageCredit(
                **{
                    key: resolved.credit.get(key)
                    for key in ImageCredit.model_fields
                }
            ),
        )

    def _analysis_summary(
        self,
        *,
        history: ListeningHistory,
        status: AnalysisStatus,
        coverage_tracks: float,
        coverage_plays: float,
        status_counts: Counter[RecordingStatus],
        availability: SectionAvailabilitySummary,
        vocal_presence: VocalPresence,
    ) -> AnalysisSummary:
        return AnalysisSummary(
            status=status,
            data_source=self._data_source(history),
            history_source=history.history_source,
            instrumentation_source=history.instrumentation_source,
            methodology_version=self._methodology.version,
            catalog_version=history.catalog_version,
            image_catalog_version=self._image_catalog.version,
            coverage_tracks=coverage_tracks,
            coverage_plays=coverage_plays,
            recording_status_counts=RecordingStatusCounts(
                **{
                    recording_status.value: status_counts[recording_status]
                    for recording_status in RecordingStatus
                }
            ),
            section_availability=availability,
            vocal_presence=vocal_presence,
        )

    @staticmethod
    def _section_availability(
        *,
        interpretation_ready: bool,
        sound_balance: SoundBalance | None,
        discovery: InstrumentLayer | None,
        temperament: Temperament | None,
        interpretation_coverage_ready: bool,
    ) -> SectionAvailabilitySummary:
        return SectionAvailabilitySummary(
            families="available",
            sound_balance=(
                "available" if sound_balance is not None else "insufficient_nature_evidence"
            ),
            discovery=(
                "available"
                if discovery is not None
                else "insufficient_diversity"
                if interpretation_coverage_ready
                else "insufficient_coverage"
                if not interpretation_ready
                else "no_candidate"
            ),
            temperament=(
                "available"
                if temperament is not None
                else "insufficient_diversity"
                if interpretation_coverage_ready
                else "insufficient_coverage"
                if not interpretation_ready
                else "no_candidate"
            ),
        )

    @staticmethod
    def _unavailable_sections(*, reason: str) -> SectionAvailabilitySummary:
        value = reason
        return SectionAvailabilitySummary(
            families=value,
            sound_balance=value,
            discovery=value,
            temperament=value,
        )

    @staticmethod
    def _recording_status(track: Track, history: ListeningHistory) -> RecordingStatus:
        if track.layers:
            return RecordingStatus.RESOLVED
        if track.recording_status is not None:
            if track.recording_status is RecordingStatus.RESOLVED:
                return RecordingStatus.RESOLVED_WITHOUT_EVIDENCE
            return track.recording_status
        pending_keys = {
            PaletteService._track_key(pending_track)
            for pending_track in history.pending_enrichment
        }
        if PaletteService._track_key(track) in pending_keys:
            return RecordingStatus.PENDING_ENRICHMENT
        if not track.mbid:
            return RecordingStatus.UNRESOLVED_IDENTITY
        return RecordingStatus.RESOLVED_WITHOUT_EVIDENCE

    @staticmethod
    def _track_key(track: Track) -> tuple[str, str, str]:
        return (
            PaletteService._artist_key(track.artist),
            PaletteService._title_key(track.title),
            track.mbid or "",
        )

    @staticmethod
    def _artist_key(value: str) -> str:
        return " ".join(value.casefold().split())

    @staticmethod
    def _title_key(value: str) -> str:
        return " ".join(value.casefold().split())

    @staticmethod
    def _data_source(history: ListeningHistory) -> str:
        if (
            history.history_source is DataSource.MOCK
            and history.instrumentation_source is DataSource.MOCK
        ):
            return "mock"
        if history.instrumentation_source is DataSource.CATALOG:
            return "catalog"
        return "hybrid"

    @staticmethod
    def _aggregate_confidence(weighted_ratio: float) -> Confidence:
        if weighted_ratio >= 0.9:
            return Confidence.DOCUMENTED
        if weighted_ratio >= 0.65:
            return Confidence.STRONGLY_ASSOCIATED
        return Confidence.ESTIMATED

    def _temperament_signals(
        self,
        families: list[FamilyPresence],
        sound_balance: SoundBalance,
        covered_history: tuple[Track, ...],
    ) -> _TemperamentSignals:
        total_plays = sum(track.play_count for track in covered_history) or 1
        family_shares = {family.slug: family.share for family in families}
        family_track_sets: dict[str, frozenset[tuple[str, str, str]]] = {}
        for family in families:
            family_track_sets[family.slug] = frozenset(
                self._track_key(track)
                for track in covered_history
                if any(layer.family_slug == family.slug for layer in track.layers)
            )

        pair_track_share: dict[tuple[str, str], float] = {}
        family_slugs = sorted(family_shares)
        for index, first in enumerate(family_slugs):
            for second in family_slugs[index + 1 :]:
                shared_keys = family_track_sets[first] & family_track_sets[second]
                shared_plays = sum(
                    track.play_count
                    for track in covered_history
                    if self._track_key(track) in shared_keys
                )
                pair_track_share[(first, second)] = shared_plays / total_plays

        nature_shares = {
            SoundNature.ACOUSTIC: sound_balance.acoustic,
            SoundNature.ELECTRIC: sound_balance.electric,
            SoundNature.ELECTRONIC: sound_balance.electronic,
            SoundNature.SAMPLED: sound_balance.sampled,
            SoundNature.HYBRID: sound_balance.hybrid,
        }
        return _TemperamentSignals(
            family_shares=family_shares,
            family_track_sets=family_track_sets,
            pair_track_share=pair_track_share,
            nature_shares=nature_shares,
        )

    @staticmethod
    def _pair_share(
        signals: _TemperamentSignals,
        first: str,
        second: str,
    ) -> float:
        return signals.pair_track_share.get(tuple(sorted((first, second))), 0.0)

    def _build_temperament(
        self,
        families: list[FamilyPresence],
        nature_scores: dict[SoundNature, float],
        sound_balance: SoundBalance,
        covered_history: tuple[Track, ...],
    ) -> Temperament:
        signals = self._temperament_signals(families, sound_balance, covered_history)
        primary_family = families[0]
        primary_nature = max(
            nature_scores,
            key=lambda nature: (nature_scores[nature], nature.value),
        )

        # Pair identities come first: they say something about the relationship
        # in the listening history, rather than merely repeating its largest bar.
        rule: TemperamentRule | None = None
        if (
            signals.family_shares.get("percussion", 0.0)
            >= self._methodology.temperament_contrast_share
            and signals.family_shares.get("synthesizers", 0.0)
            >= self._methodology.temperament_contrast_share
            and len(
                signals.family_track_sets.get("percussion", frozenset())
                & signals.family_track_sets.get("synthesizers", frozenset())
            )
            >= self._methodology.temperament_family_recording_floor
            and self._pair_share(signals, "percussion", "synthesizers")
            >= self._methodology.temperament_pair_share
        ):
            rule = "recurring-percussion-synthesizers"
        elif (
            signals.family_shares.get("plucked-strings", 0.0)
            >= self._methodology.temperament_signal_share
            and signals.nature_shares.get(SoundNature.ELECTRIC, 0.0)
            >= self._methodology.temperament_signal_share
        ):
            rule = "electric-plucked-strings"
        elif (
            signals.nature_shares.get(SoundNature.SAMPLED, 0.0)
            >= self._methodology.temperament_sampled_signal_share
        ):
            rule = "recurring-sampled"
        elif (
            signals.nature_shares.get(SoundNature.ELECTRONIC, 0.0)
            >= self._methodology.temperament_signal_share
        ):
            rule = "recurring-electronic"

        return Temperament(
            rule=rule or f"dominant-{primary_nature.value}",
            primary_family_slug=primary_family.slug,
            primary_nature=primary_nature,
        )
