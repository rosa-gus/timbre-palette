"""Versioned, deterministic rules for turning catalog evidence into a report."""

from dataclasses import dataclass

from palette_api.domain import AnalysisStatus, RecordingStatus


@dataclass(frozen=True, slots=True)
class MethodologyPolicy:
    """The complete public methodology for one API result.

    Coverage is deliberately conjunctive: a conclusion must have enough
    covered recordings *and* enough covered plays. Absolute floors keep a very
    small period from producing an apparently authoritative portrait.
    """

    version: str = "0.3.0"
    palette_track_ratio: float = 0.20
    palette_play_ratio: float = 0.20
    interpretation_track_ratio: float = 0.40
    interpretation_play_ratio: float = 0.40
    palette_track_floor: int = 5
    interpretation_track_floor: int = 8
    palette_artist_floor: int = 3
    interpretation_artist_floor: int = 4
    known_nature_ratio: float = 0.80
    discovery_recording_floor: int = 3
    discovery_artist_floor: int = 2
    temperament_family_recording_floor: int = 3
    temperament_contrast_share: float = 0.15
    temperament_pair_share: float = 0.15
    temperament_signal_share: float = 0.25
    temperament_sampled_signal_share: float = 0.15

    def minimum_tracks(self, total_tracks: int, ratio: float, floor: int) -> int:
        if total_tracks <= 0:
            return 0
        return min(total_tracks, max(floor, _ceil(total_tracks * ratio)))

    def minimum_artists(self, total_artists: int, floor: int) -> int:
        return min(total_artists, floor)

    def meets_palette_gate(
        self,
        *,
        coverage_tracks: float,
        coverage_plays: float,
        covered_tracks: int,
        total_tracks: int,
        covered_artists: int,
        total_artists: int,
    ) -> bool:
        return self.meets_coverage_floor(
            coverage_tracks=coverage_tracks,
            coverage_plays=coverage_plays,
            covered_tracks=covered_tracks,
            total_tracks=total_tracks,
            track_ratio=self.palette_track_ratio,
            play_ratio=self.palette_play_ratio,
            track_floor=self.palette_track_floor,
        ) and self.meets_diversity_floor(
            covered_artists=covered_artists,
            total_artists=total_artists,
            artist_floor=self.palette_artist_floor,
        )

    def meets_interpretation_gate(
        self,
        *,
        coverage_tracks: float,
        coverage_plays: float,
        covered_tracks: int,
        total_tracks: int,
        covered_artists: int,
        total_artists: int,
    ) -> bool:
        return self.meets_coverage_floor(
            coverage_tracks=coverage_tracks,
            coverage_plays=coverage_plays,
            covered_tracks=covered_tracks,
            total_tracks=total_tracks,
            track_ratio=self.interpretation_track_ratio,
            play_ratio=self.interpretation_play_ratio,
            track_floor=self.interpretation_track_floor,
        ) and self.meets_diversity_floor(
            covered_artists=covered_artists,
            total_artists=total_artists,
            artist_floor=self.interpretation_artist_floor,
        )

    def meets_coverage_floor(
        self,
        *,
        coverage_tracks: float,
        coverage_plays: float,
        covered_tracks: int,
        total_tracks: int,
        track_ratio: float,
        play_ratio: float,
        track_floor: int,
    ) -> bool:
        return (
            coverage_tracks >= track_ratio
            and coverage_plays >= play_ratio
            and covered_tracks >= self.minimum_tracks(total_tracks, track_ratio, track_floor)
        )

    def meets_diversity_floor(
        self,
        *,
        covered_artists: int,
        total_artists: int,
        artist_floor: int,
    ) -> bool:
        return covered_artists >= self.minimum_artists(total_artists, artist_floor)

    def status(
        self,
        *,
        palette_ready: bool,
        interpretation_ready: bool,
        progress_capable: bool,
        has_published_evidence: bool,
    ) -> AnalysisStatus:
        # A public request must never wait for asynchronous enrichment. A
        # report with any published evidence is immediately useful and can be
        # refined on a later visit; only a report with no evidence at all is
        # insufficient.
        if not palette_ready:
            return (
                AnalysisStatus.PARTIAL
                if has_published_evidence
                else AnalysisStatus.INSUFFICIENT
            )
        if not interpretation_ready or progress_capable:
            return AnalysisStatus.PARTIAL
        return AnalysisStatus.READY

    @staticmethod
    def progress_capable_statuses() -> frozenset[RecordingStatus]:
        return frozenset(
            {
                RecordingStatus.PENDING_ENRICHMENT,
                RecordingStatus.TRANSIENT_FAILURE,
            }
        )


def _ceil(value: float) -> int:
    integer = int(value)
    return integer if value == integer else integer + 1


DEFAULT_METHODOLOGY = MethodologyPolicy()
