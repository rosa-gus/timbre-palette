import httpx
import pytest

from palette_api.api import app, get_v2_analysis_service
from palette_api.domain import (
    ClaimLevel,
    Confidence,
    DataSource,
    InstrumentLayer,
    ListeningHistory,
    ListeningPeriod,
    SoundNature,
    Track,
)
from palette_api.mocks import MockListeningHistoryProvider
from palette_api.schemas import SnapshotInfo
from palette_api.v2 import (
    MockSnapshotProjectionProvider,
    SnapshotPreparation,
    SnapshotVocabularyRow,
    HydrationTarget,
    V2AnalysisService,
    _bounded_hydration_targets,
    _shard_key,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_hydration_targets_use_serving_snapshot_shard_widths() -> None:
    mbid = "abcdef12-3456-4789-abcd-ef1234567890"

    assert _shard_key("recording", mbid) == "abcd"
    assert _shard_key("track", mbid) == "abcd"
    assert _shard_key("artist", mbid) == "abc"


def test_recording_hydration_is_bounded_but_artist_targets_are_deduplicated() -> None:
    recording_targets = [
        HydrationTarget("recording", f"recording-{index}")
        for index in range(60)
    ]
    artist_targets = [
        HydrationTarget("artist", f"artist-{index}")
        for index in range(3)
    ]

    selected = _bounded_hydration_targets(
        recording_targets + artist_targets + [recording_targets[0]]
    )

    assert len(selected) == 53
    assert selected[:2] == (
        HydrationTarget("recording", "recording-0"),
        HydrationTarget("recording", "recording-1"),
    )
    assert selected[49] == HydrationTarget("recording", "recording-49")
    assert selected[50:] == tuple(artist_targets)


@pytest.mark.anyio
async def test_v2_mock_analysis_has_two_separate_products() -> None:
    async def service() -> V2AnalysisService:
        return V2AnalysisService(
            MockListeningHistoryProvider(), MockSnapshotProjectionProvider()
        )

    app.dependency_overrides[get_v2_analysis_service] = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v2/profiles/example/analysis")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "profile",
        "snapshot",
        "track_palette",
        "artist_vocabulary",
        "available_views",
        "default_view",
        "hydration",
    }
    assert body["default_view"] == "track_palette"
    assert body["available_views"] == ["track_palette"]
    assert body["artist_vocabulary"]["status"] == "insufficient"


@pytest.mark.anyio
async def test_v1_is_not_registered() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v1/profiles/example/palette")
        openapi = await client.get("/openapi.json")

    assert response.status_code == 404
    assert "/v1/profiles/{username}/palette" not in openapi.json()["paths"]
    assert "/v2/profiles/{username}/analysis" in openapi.json()["paths"]


class StaticVocabularyProvider:
    async def prepare(self, history: ListeningHistory) -> SnapshotPreparation:
        snapshot = SnapshotInfo(
            snapshot_version="test-snapshot",
            schema_version="musicbrainz-instrument-credits-serving-v2",
            manifest_hash="test-hash",
            object_prefix="test-prefix",
            methodology_version="artist-vocabulary-candidate-2",
        )
        rows = tuple(
            SnapshotVocabularyRow(
                artist_mbid=track.artist_mbid or "",
                instrument_slug="piano",
                instrument_name="Piano",
                family_slug="acoustic-keys",
                family_name="Teclas acústicas",
                distinct_recordings=3,
                documented_recordings=10,
                prevalence=0.3,
                evidence_quality=1.0,
                source_scope="recording",
            )
            for track in history.tracks[:4]
        )
        return SnapshotPreparation(
            snapshot=snapshot,
            history=history,
            vocabulary_rows=rows,
            pending_artist_mbids=frozenset(),
            targets=(),
        )


@pytest.mark.anyio
async def test_vocabulary_can_become_the_default_view() -> None:
    artist_mbids = tuple(
        f"00000000-0000-0000-0000-00000000000{index}" for index in range(1, 5)
    )
    history = ListeningHistory(
        username="listener",
        period=ListeningPeriod.OVERALL,
        tracks=tuple(
            Track(
                title=f"Track {index}",
                artist=f"Artist {index % 4}",
                play_count=10,
                artist_mbid=artist_mbids[index % 4],
                layers=(
                    InstrumentLayer(
                        slug="piano",
                        name="Piano",
                        family_slug="acoustic-keys",
                        family_name="Teclas acústicas",
                        nature=SoundNature.ACOUSTIC,
                        role="",
                        confidence=Confidence.DOCUMENTED,
                        claim_level=ClaimLevel.INSTRUMENT,
                    ),
                )
                if index == 0
                else (),
            )
            for index in range(8)
        ),
        history_source=DataSource.MOCK,
    )

    class StaticHistoryProvider:
        async def get_history(self, username: str, period: ListeningPeriod):
            return history

    async def service() -> V2AnalysisService:
        return V2AnalysisService(StaticHistoryProvider(), StaticVocabularyProvider())

    app.dependency_overrides[get_v2_analysis_service] = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v2/profiles/listener/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["artist_vocabulary"]["status"] == "available"
    featured = body["artist_vocabulary"]["featured_artists"]
    assert len(featured) == 3
    assert [artist["mbid"] for artist in featured] == list(artist_mbids[:3])
    assert [artist["name"] for artist in featured] == [
        "Artist 0", "Artist 1", "Artist 2"
    ]
    assert featured[0]["families"] == [{
        "slug": "acoustic-keys",
        "name": "Teclas acústicas",
        "instruments": ["Piano"],
        "tone": {"shadow": "#000000", "highlight": "#F29191"},
    }]
    assert body["artist_vocabulary"]["families"][0]["tone"] == {
        "shadow": "#000000", "highlight": "#F29191"
    }
    assert body["default_view"] == "artist_vocabulary"
    assert body["available_views"] == ["track_palette", "artist_vocabulary"]
    assert body["track_palette"]["analysis"]["status"] == "partial"


@pytest.mark.anyio
async def test_pending_vocabulary_is_available_when_materialized_rows_already_pass() -> None:
    artist_mbids = tuple(
        f"10000000-0000-0000-0000-00000000000{index}" for index in range(1, 4)
    )
    history = ListeningHistory(
        username="listener",
        period=ListeningPeriod.OVERALL,
        tracks=tuple(
            Track(
                title=f"Track {index}",
                artist=f"Artist {index % 3}",
                play_count=10,
                artist_mbid=artist_mbids[index % 3],
            )
            for index in range(10)
        ),
        history_source=DataSource.MOCK,
    )

    class PendingVocabularyProvider:
        async def prepare(self, _history: ListeningHistory) -> SnapshotPreparation:
            snapshot = SnapshotInfo(
                snapshot_version="test-snapshot",
                schema_version="musicbrainz-instrument-credits-serving-v2",
                manifest_hash="test-hash",
                object_prefix="test-prefix",
                methodology_version="artist-vocabulary-candidate-2",
            )
            rows = tuple(
                SnapshotVocabularyRow(
                    artist_mbid=artist_mbid,
                    instrument_slug="piano",
                    instrument_name="Piano",
                    family_slug="acoustic-keys",
                    family_name="Teclas acústicas",
                    distinct_recordings=3,
                    documented_recordings=10,
                    prevalence=0.3,
                    evidence_quality=1.0,
                    source_scope="recording",
                )
                for artist_mbid in artist_mbids
            )
            return SnapshotPreparation(
                snapshot=snapshot,
                history=_history,
                vocabulary_rows=rows,
                pending_artist_mbids=frozenset({
                    "20000000-0000-0000-0000-000000000001"
                }),
                targets=(
                    HydrationTarget(
                        "artist", "20000000-0000-0000-0000-000000000001"
                    ),
                ),
            )

    class StaticHistoryProvider:
        async def get_history(self, username: str, period: ListeningPeriod):
            return history

    async def service() -> V2AnalysisService:
        return V2AnalysisService(StaticHistoryProvider(), PendingVocabularyProvider())

    app.dependency_overrides[get_v2_analysis_service] = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v2/profiles/listener/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["artist_vocabulary"]["status"] == "available"
    assert body["artist_vocabulary"]["availability"]["reason"] == (
        "available_with_pending_hydration"
    )


@pytest.mark.anyio
async def test_missing_track_mbid_is_unresolved_identity_not_pending_hydration() -> None:
    class StaticHistoryProvider:
        async def get_history(self, username: str, period: ListeningPeriod):
            return ListeningHistory(
                username=username,
                period=period,
                tracks=(Track("Track", "Artist", 1),),
                history_source=DataSource.MOCK,
            )

    async def service() -> V2AnalysisService:
        return V2AnalysisService(
            StaticHistoryProvider(), MockSnapshotProjectionProvider()
        )

    app.dependency_overrides[get_v2_analysis_service] = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v2/profiles/listener/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["hydration"] == {
        "status": "complete",
        "pending_recordings": 0,
        "pending_artists": 0,
        "pending_aliases": 0,
    }
    assert body["track_palette"]["recordings"][0]["status"] == (
        "unresolved_identity"
    )
    assert body["track_palette"]["analysis"]["recording_status_counts"][
        "unresolved_identity"
    ] == 1
    assert body["artist_vocabulary"]["reach"]["unresolved_artists"] == 1
    assert body["artist_vocabulary"]["reach"]["unresolved_tracks"] == 1
