import httpx
import pytest

from palette_api.api import app, get_palette_service
from palette_api.application import PaletteService
from palette_api.domain import (
    Confidence,
    DataSource,
    InstrumentLayer,
    ListeningHistory,
    ListeningPeriod,
    RecordingStatus,
    SoundNature,
    Track,
)
from palette_api.lastfm import LastFmProfileNotFoundError
from palette_api.mocks import MockListeningHistoryProvider


async def get_mock_palette_service() -> PaletteService:
    return PaletteService(MockListeningHistoryProvider())


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app.dependency_overrides[get_palette_service] = get_mock_palette_service
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_palette_returns_a_mocked_but_computed_report(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/v1/profiles/ouvinte-exemplo/palette",
        params={"period": "12month"},
    )

    assert response.status_code == 200
    body = response.json()
    assert app.version == "0.3.1"
    assert body["profile"]["username"] == "ouvinte-exemplo"
    assert body["profile"]["period"] == "12month"
    assert body["analysis"]["data_source"] == "mock"
    assert body["analysis"]["history_source"] == "mock"
    assert body["analysis"]["instrumentation_source"] == "mock"
    assert body["analysis"]["status"] == "ready"
    assert body["analysis"]["methodology_version"] == "0.3.0"
    assert "coverage" not in body["analysis"]
    assert body["analysis"]["coverage_tracks"] == 1
    assert body["analysis"]["coverage_plays"] == 1
    assert body["analysis"]["vocal_presence"] == {
        "documented_tracks": 0,
        "documented_artists": 0,
        "documented_plays": 0,
        "track_ratio": 0,
        "play_ratio": 0,
    }
    assert body["analysis"]["section_availability"]["families"] == "available"
    assert body["analysis"]["recording_status_counts"]["resolved"] == 3
    assert body["families"][0]["slug"] == "plucked-strings"
    assert body["discovery"]["instrument_slug"] == "cuica"
    assert "não uma avaliação psicológica" in body["temperament"]["disclaimer"]
    assert "representative_track" not in body
    assert "representative_track" not in body["analysis"]["section_availability"]
    assert response.headers["cache-control"] == "public, max-age=300, s-maxage=300"


@pytest.mark.anyio
async def test_palette_changes_play_count_for_the_requested_period(
    client: httpx.AsyncClient,
) -> None:
    week = (
        await client.get(
            "/v1/profiles/ouvinte-exemplo/palette",
            params={"period": "7day"},
        )
    ).json()
    overall = (
        await client.get(
            "/v1/profiles/ouvinte-exemplo/palette",
            params={"period": "overall"},
        )
    ).json()

    assert week["profile"]["total_plays"] == 6
    assert overall["profile"]["total_plays"] == 406


@pytest.mark.anyio
async def test_family_colors_and_images_are_shared_between_profiles(client: httpx.AsyncClient) -> None:
    expected = {
        "acoustic-keys": "#F29191",
        "plucked-strings": "#E7AE86",
        "percussion": "#D5C18D",
        "bowed-strings": "#A9C4AE",
        "sampled-sounds": "#9EBBD1",
        "synthesizers": "#B7A5CC",
    }
    first = (await client.get("/v1/profiles/first/palette")).json()
    second = (await client.get("/v1/profiles/second/palette")).json()
    assert first["families"] == second["families"]
    assert {family["slug"] for family in first["families"]} == set(expected)
    for family in first["families"]:
        assert family["tone"] == {"shadow": "#000000", "highlight": expected[family["slug"]]}
        assert family["image"]["tone"] == family["tone"]
        assert family["image"]["resolution"] == "family"
        assert family["image"]["variants"][0]["width"] == 1200
    drums = (await client.get("/v1/instruments/drums")).json()
    cuica = (await client.get("/v1/instruments/cuica")).json()
    assert cuica["image"]["resolution"] == "family"
    assert drums["image"]["resolution"] == "exact"
    assert cuica["image"]["asset_id"] == drums["image"]["asset_id"]
    assert cuica["tone"] == drums["tone"] == {"shadow": "#000000", "highlight": "#D5C18D"}


@pytest.mark.anyio
@pytest.mark.parametrize("base_url", [
    "http://127.0.0.1:5173/",
    "https://rosa-gus.github.io/repository-example/",
])
async def test_image_hosting_base_applies_to_report_and_resource(base_url: str) -> None:
    async def app_with_environment(scope, receive, send):
        scope["env"] = {"PALETTE_API_MODE": "mock", "IMAGE_ASSET_BASE_URL": base_url}
        await app(scope, receive, send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_with_environment), base_url="http://testserver",
    ) as client:
        report = (await client.get("/v1/profiles/listener/palette")).json()
        piano = (await client.get("/v1/instruments/piano")).json()
    for family in report["families"]:
        url = family["image"]["variants"][0]["url"]
        assert url.startswith(base_url + "instruments/")
        assert "<hash>" not in url
    family = next(f for f in report["families"] if f["slug"] == "acoustic-keys")
    assert family["image"]["variants"] == piano["image"]["variants"]


@pytest.mark.anyio
async def test_palette_rejects_an_unknown_period(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/v1/profiles/ouvinte-exemplo/palette",
        params={"period": "yesterday"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


@pytest.mark.anyio
async def test_instrument_returns_editorial_resource(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/v1/instruments/cuica")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300, s-maxage=300"
    body = response.json()
    assert body["slug"] == "cuica"
    assert body["data_source"] == "mock"
    assert body["kind"] == "instrument"
    assert body["family_slug"] == "percussion"
    assert body["catalog_version"] == "mock-0.1.0"
    assert body["sections"][0]["status"] == "sourced"
    assert body["sections"][0]["review"]["source_metadata_verified"] is True
    assert body["sections"][0]["review"]["claim_support_verified"] is False
    assert body["sources"][0]["metadata_verified"] is True
    assert body["sources"][0]["source_type"] == "university"
    assert (await client.get("/v1/instruments/vibraphone")).status_code == 404

    voice = (await client.get("/v1/instruments/voice")).json()
    assert voice["kind"] == "family"
    assert voice["name"] == "Voz"
    assert voice["common_roles"] == ["melodia", "texto", "camada"]


@pytest.mark.anyio
async def test_unknown_instrument_returns_not_found(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/v1/instruments/inexistente")

    assert response.status_code == 404
    assert response.json()["code"] == "instrument_not_found"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_every_report_resource_is_available_in_the_mock_catalog(
    client: httpx.AsyncClient,
) -> None:
    report = (await client.get("/v1/profiles/example/palette")).json()
    slugs = {family["slug"] for family in report["families"]}
    slugs.add(report["discovery"]["instrument_slug"])

    responses = [await client.get(f"/v1/instruments/{slug}") for slug in slugs]

    assert all(response.status_code == 200 for response in responses)


@pytest.mark.anyio
async def test_openapi_exposes_palette_instruments_and_catalog_stats(
    client: httpx.AsyncClient,
) -> None:
    paths = set((await client.get("/openapi.json")).json()["paths"])

    assert paths == {
        "/v1/catalog/stats",
        "/v1/instruments/{slug}",
        "/v1/profiles/{username}/palette",
    }


@pytest.mark.anyio
async def test_palette_reports_missing_lastfm_configuration() -> None:
    app.dependency_overrides.clear()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as unconfigured_client:
        response = await unconfigured_client.get("/v1/profiles/example/palette")

    assert response.status_code == 503
    assert response.json()["code"] == "lastfm_not_configured"


@pytest.mark.anyio
async def test_palette_returns_immediately_when_catalog_enrichment_is_pending() -> None:
    class PendingHistoryProvider:
        async def get_history(self, username: str, period: ListeningPeriod) -> ListeningHistory:
            track = Track("Unknown", "Artist", 1, mbid="unknown")
            return ListeningHistory(
                username=username,
                period=period,
                tracks=(track,),
                history_source=DataSource.LASTFM,
                pending_enrichment=(track,),
            )

    async def get_pending_service() -> PaletteService:
        return PaletteService(PendingHistoryProvider())

    app.dependency_overrides[get_palette_service] = get_pending_service
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/profiles/example/palette")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["status"] == "insufficient"
    assert body["analysis"]["recording_status_counts"]["pending_enrichment"] == 1
    assert body["recordings"][0]["status"] == "pending_enrichment"
    assert body["families"] == []
    assert body["sound_balance"] is None


@pytest.mark.anyio
async def test_palette_distinguishes_existing_history_without_catalog_evidence() -> None:
    class UninstrumentedHistoryProvider:
        async def get_history(self, username: str, period: ListeningPeriod) -> ListeningHistory:
            return ListeningHistory(
                username=username,
                period=period,
                tracks=(Track("Known", "Artist", 1),),
                history_source=DataSource.LASTFM,
                pending_enrichment=(),
            )

    async def get_uninstrumented_service() -> PaletteService:
        return PaletteService(UninstrumentedHistoryProvider())

    app.dependency_overrides[get_palette_service] = get_uninstrumented_service
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/profiles/example/palette")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["status"] == "insufficient"
    assert body["analysis"]["recording_status_counts"]["resolved_without_evidence"] == 1
    assert body["recordings"][0]["status"] == "resolved_without_evidence"
    assert body["families"] == []
    assert body["temperament"] is None


@pytest.mark.anyio
async def test_palette_returns_a_partial_report_with_the_same_envelope() -> None:
    covered = tuple(
        Track(
            f"Covered {index}",
            f"Artist {index}",
            3,
            layers=(
                InstrumentLayer(
                    slug="piano",
                    name="Piano",
                    family_slug="acoustic-keys",
                    family_name="Teclas acústicas",
                    nature=SoundNature.ACOUSTIC,
                    role="harmonia",
                    confidence=Confidence.DOCUMENTED,
                ),
            ),
        )
        for index in range(5)
    )

    class PartialHistoryProvider:
        async def get_history(self, username: str, period: ListeningPeriod) -> ListeningHistory:
            return ListeningHistory(
                username=username,
                period=period,
                tracks=covered
                + tuple(
                    Track(f"Uncovered {index}", f"Other {index}", 1)
                    for index in range(5)
                ),
                history_source=DataSource.LASTFM,
            )

    async def get_partial_service() -> PaletteService:
        return PaletteService(PartialHistoryProvider())

    app.dependency_overrides[get_palette_service] = get_partial_service
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/profiles/example/palette")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["status"] == "partial"
    assert body["analysis"]["coverage_tracks"] == 0.5
    assert body["analysis"]["coverage_plays"] == 0.75
    assert body["analysis"]["section_availability"]["temperament"] == "insufficient_coverage"
    assert body["recordings"][5]["status"] == "resolved_without_evidence"
    assert "representative_track" not in body


@pytest.mark.anyio
async def test_terminal_recording_state_is_insufficient() -> None:
    class TerminalHistoryProvider:
        async def get_history(self, username: str, period: ListeningPeriod) -> ListeningHistory:
            return ListeningHistory(
                username=username,
                period=period,
                tracks=(Track(
                    "Broken",
                    "Artist",
                    1,
                    recording_status=RecordingStatus.TERMINAL_FAILURE,
                ),),
                history_source=DataSource.LASTFM,
            )

    async def get_terminal_service() -> PaletteService:
        return PaletteService(TerminalHistoryProvider())

    app.dependency_overrides[get_palette_service] = get_terminal_service
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/profiles/example/palette")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["analysis"]["status"] == "insufficient"
    assert response.json()["recordings"][0]["status"] == "terminal_failure"


@pytest.mark.anyio
async def test_palette_exposes_each_recording_state() -> None:
    covered = Track(
        "Resolved",
        "Artist",
        1,
        layers=(
            InstrumentLayer(
                slug="piano",
                name="Piano",
                family_slug="acoustic-keys",
                family_name="Teclas acústicas",
                nature=SoundNature.ACOUSTIC,
                role="harmonia",
                confidence=Confidence.DOCUMENTED,
            ),
        ),
    )

    class StatesHistoryProvider:
        async def get_history(self, username: str, period: ListeningPeriod) -> ListeningHistory:
            return ListeningHistory(
                username=username,
                period=period,
                tracks=(
                    covered,
                    Track("Pending", "Artist", 1, recording_status=RecordingStatus.PENDING_ENRICHMENT),
                    Track("Ambiguous", "Artist", 1, recording_status=RecordingStatus.AMBIGUOUS),
                    Track("No evidence", "Artist", 1, recording_status=RecordingStatus.RESOLVED_WITHOUT_EVIDENCE),
                    Track("Transient", "Artist", 1, recording_status=RecordingStatus.TRANSIENT_FAILURE),
                    Track("Terminal", "Artist", 1, recording_status=RecordingStatus.TERMINAL_FAILURE),
                ),
            )

    async def get_states_service() -> PaletteService:
        return PaletteService(StatesHistoryProvider())

    app.dependency_overrides[get_palette_service] = get_states_service
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/profiles/example/palette")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["status"] == "partial"
    assert body["families"]
    assert {
        recording["status"] for recording in body["recordings"]
    } == {
        "resolved",
        "pending_enrichment",
        "ambiguous",
        "resolved_without_evidence",
        "transient_failure",
        "terminal_failure",
    }


@pytest.mark.anyio
async def test_palette_reports_unknown_profile_as_an_error() -> None:
    class MissingProfileProvider:
        async def get_history(self, username: str, period: ListeningPeriod) -> ListeningHistory:
            raise LastFmProfileNotFoundError(username)

    async def get_missing_profile_service() -> PaletteService:
        return PaletteService(MissingProfileProvider())

    app.dependency_overrides[get_palette_service] = get_missing_profile_service
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/profiles/missing/palette")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["code"] == "lastfm_profile_not_found"


@pytest.mark.anyio
async def test_palette_reports_empty_history_as_an_error() -> None:
    class EmptyHistoryProvider:
        async def get_history(self, username: str, period: ListeningPeriod) -> ListeningHistory:
            return ListeningHistory(username=username, period=period, tracks=())

    async def get_empty_service() -> PaletteService:
        return PaletteService(EmptyHistoryProvider())

    app.dependency_overrides[get_palette_service] = get_empty_service
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/profiles/empty/palette")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["code"] == "empty_listening_history"
