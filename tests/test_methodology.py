from dataclasses import replace
import json
from pathlib import Path

import pytest

from palette_api.application import PaletteService
from palette_api.domain import (
    ClaimLevel,
    Confidence,
    DataSource,
    InstrumentLayer,
    ListeningHistory,
    ListeningPeriod,
    Track,
)
from palette_api.methodology import DEFAULT_METHODOLOGY


def test_research_profile_snapshots_do_not_get_promoted_to_full_reports() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "methodology_profiles.json"
    profiles = json.loads(fixture_path.read_text(encoding="utf-8"))

    for profile in profiles.values():
        palette = DEFAULT_METHODOLOGY.meets_palette_gate(
            coverage_tracks=profile["coverage_tracks"],
            coverage_plays=profile["coverage_plays"],
            covered_tracks=profile["covered_tracks"],
            total_tracks=profile["total_tracks"],
            covered_artists=profile["covered_artists"],
            total_artists=profile["total_artists"],
        )
        interpretation = DEFAULT_METHODOLOGY.meets_interpretation_gate(
            coverage_tracks=profile["coverage_tracks"],
            coverage_plays=profile["coverage_plays"],
            covered_tracks=profile["covered_tracks"],
            total_tracks=profile["total_tracks"],
            covered_artists=profile["covered_artists"],
            total_artists=profile["total_artists"],
        )
        assert palette is (profile["expected_gate"] == "palette")
        assert not interpretation


def test_methodology_requires_both_coverage_dimensions_and_diversity() -> None:
    policy = DEFAULT_METHODOLOGY

    assert policy.meets_palette_gate(
        coverage_tracks=0.5,
        coverage_plays=0.5,
        covered_tracks=5,
        total_tracks=10,
        covered_artists=3,
        total_artists=5,
    )
    assert not policy.meets_palette_gate(
        coverage_tracks=0.5,
        coverage_plays=0.19,
        covered_tracks=5,
        total_tracks=10,
        covered_artists=3,
        total_artists=5,
    )
    assert not policy.meets_palette_gate(
        coverage_tracks=0.5,
        coverage_plays=0.5,
        covered_tracks=5,
        total_tracks=10,
        covered_artists=2,
        total_artists=5,
    )


def _layer(
    slug: str,
    family: str,
    *,
    nature: str | None = "acoustic",
    prominence: float = 1.0,
    claim_level: ClaimLevel = ClaimLevel.INSTRUMENT,
    unexpected: bool = False,
) -> InstrumentLayer:
    from palette_api.domain import SoundNature

    return InstrumentLayer(
        slug=slug,
        name=slug,
        family_slug=family,
        family_name=family,
        nature=SoundNature(nature) if nature else None,
        role="função documentada",
        confidence=Confidence.DOCUMENTED,
        prominence=prominence,
        claim_level=claim_level,
        unexpected=unexpected,
    )


class StaticHistoryProvider:
    def __init__(self, tracks: tuple[Track, ...]) -> None:
        self.tracks = tracks

    async def get_history(self, username: str, period: ListeningPeriod) -> ListeningHistory:
        return ListeningHistory(
            username=username,
            period=period,
            tracks=self.tracks,
            history_source=DataSource.LASTFM,
        )


async def _report(tracks: tuple[Track, ...]):
    return await PaletteService(StaticHistoryProvider(tracks)).analyze(
        "listener", ListeningPeriod.OVERALL
    )


@pytest.mark.anyio
async def test_family_claim_is_counted_once_and_does_not_invent_sound_nature() -> None:
    tracks = tuple(
        Track(
            f"track-{index}",
            "artist",
            1,
            layers=(
                _layer("electric-guitar", "plucked-strings", nature="electric"),
                _layer("electric-bass", "plucked-strings", nature="electric", prominence=0.8),
                _layer("drums", "percussion"),
            ),
        )
        for index in range(5)
    )
    report = await _report(tracks)

    assert report.analysis.status.value == "ready"
    assert report.families[0].share == report.families[1].share == 0.5
    assert report.sound_balance is not None
    assert report.sound_balance.unknown == 0

    family_only = tuple(
        replace(track, layers=(_layer("percussion", "percussion", nature=None, claim_level=ClaimLevel.FAMILY),))
        for track in tracks
    )
    family_report = await _report(family_only)
    assert family_report.analysis.status.value == "ready"
    assert family_report.sound_balance is None
    assert family_report.analysis.section_availability.sound_balance == "insufficient_nature_evidence"


@pytest.mark.anyio
async def test_vocal_presence_counts_documented_recordings_artists_and_plays_once() -> None:
    def layers_for(index: int) -> tuple[InstrumentLayer, ...]:
        layers = [
            _layer("voice", "voice", nature=None, claim_level=ClaimLevel.FAMILY),
        ] if index < 3 else []
        if index == 0:
            layers.append(
                _layer("voice", "voice", nature=None, claim_level=ClaimLevel.FAMILY)
            )
        layers.append(_layer("electric-guitar", "plucked-strings", nature="electric"))
        return tuple(layers)

    tracks = tuple(
        Track(
            f"track-{index}",
            f"artist-{index % 2}",
            index + 1,
            layers=layers_for(index),
        )
        for index in range(10)
    )

    report = await _report(tracks)

    assert report.analysis.vocal_presence.model_dump() == {
        "documented_tracks": 3,
        "documented_artists": 2,
        "documented_plays": 6,
        "track_ratio": 0.3,
        "play_ratio": 0.1091,
    }
    assert report.sound_balance is not None
    assert report.analysis.section_availability.sound_balance == "available"


@pytest.mark.anyio
async def test_discovery_requires_recurrence_and_interpretation_coverage() -> None:
    tracks = tuple(
        Track(
            f"track-{index}",
            f"artist-{index % 4}",
            2,
            layers=(
                _layer(
                    "cuica",
                    "percussion",
                    unexpected=index in {0, 1, 2},
                ),
            )
            if index < 5
            else (),
        )
        for index in range(10)
    )
    report = await _report(tracks)

    assert report.analysis.status.value == "partial"
    assert report.discovery is None
    assert report.analysis.section_availability.discovery == "insufficient_coverage"


@pytest.mark.anyio
async def test_report_is_invariant_to_track_order() -> None:
    tracks = tuple(
        Track(
            f"track-{index}",
            f"artist-{index % 4}",
            index + 1,
            layers=(
                _layer("guitar", "plucked-strings", nature="electric"),
                _layer("drums", "percussion"),
            ),
        )
        for index in range(10)
    )
    first = await _report(tracks)
    second = await _report(tuple(reversed(tracks)))

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


@pytest.mark.anyio
async def test_temperament_recognizes_recurrent_movement_with_atmosphere() -> None:
    tracks = tuple(
        Track(
            f"track-{index}",
            f"artist-{index % 4}",
            2,
            layers=(
                _layer("drums", "percussion", nature="acoustic"),
                _layer("synth", "synthesizers", nature="electronic"),
                _layer("guitar", "plucked-strings", nature="electric"),
            ),
        )
        for index in range(10)
    )

    report = await _report(tracks)

    assert report.temperament is not None
    assert report.temperament.title == "Movimento com atmosfera"
    assert "Percussão e sintetizadores" in report.temperament.summary


@pytest.mark.anyio
async def test_temperament_falls_back_to_acoustic_identity() -> None:
    tracks = tuple(
        Track(
            f"track-{index}",
            f"artist-{index % 4}",
            1,
            layers=(
                _layer("piano", "keys", nature="acoustic"),
                _layer("cello", "bowed-strings", nature="acoustic"),
            ),
        )
        for index in range(10)
    )

    report = await _report(tracks)

    assert report.temperament is not None
    assert report.temperament.title == "Acústica com presença"
    assert "fontes acústicas" in report.temperament.summary


@pytest.mark.parametrize(
    ("nature", "expected_title"),
    (
        ("electric", "Corpo elétrico"),
        ("electronic", "Textura eletrônica"),
        ("sampled", "Memória em recortes"),
        ("hybrid", "Orgânica e eletrônica"),
    ),
)
@pytest.mark.anyio
async def test_temperament_has_a_nature_identity_fallback(
    nature: str,
    expected_title: str,
) -> None:
    tracks = tuple(
        Track(
            f"track-{index}",
            f"artist-{index % 4}",
            1,
            layers=(
                _layer("family-a", "family-a", nature=nature),
                _layer("family-b", "family-b", nature=nature),
            ),
        )
        for index in range(10)
    )

    report = await _report(tracks)

    assert report.temperament is not None
    assert report.temperament.title == expected_title


@pytest.mark.anyio
async def test_temperament_does_not_call_movement_without_pair_recurrence() -> None:
    tracks = tuple(
        Track(
            f"track-{index}",
            f"artist-{index % 4}",
            1,
            layers=(
                (_layer("drums", "percussion", nature="acoustic"),)
                if index < 5
                else (_layer("synth", "synthesizers", nature="electronic"),)
            ),
        )
        for index in range(10)
    )

    report = await _report(tracks)

    assert report.temperament is not None
    assert report.temperament.title != "Movimento com atmosfera"
