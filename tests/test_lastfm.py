from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from palette_api.api import app, get_v2_analysis_service
from palette_api.domain import DataSource, ListeningPeriod
from palette_api.lastfm import (
    JsonHttpResponse,
    LastFmConfigurationError,
    LastFmInvalidResponseError,
    LastFmListeningHistoryProvider,
    LastFmProfileNotFoundError,
    LastFmRateLimitError,
    LastFmUnavailableError,
)
from palette_api.v2 import MockSnapshotProjectionProvider, V2AnalysisService


SUCCESS_RESPONSE = {
    "toptracks": {
        "track": [
            {
                "name": "Everything In Its Right Place",
                "playcount": "42",
                "mbid": "test-track-mbid",
                "url": "https://www.last.fm/music/Radiohead/_/Everything+In+Its+Right+Place",
                "artist": {
                    "name": "Radiohead",
                    "mbid": "test-artist-mbid",
                },
                "album": {
                    "mbid": "test-release-mbid",
                },
            },
            {
                "name": "Svefn-g-englar",
                "playcount": "21",
                "mbid": "",
                "url": "https://www.last.fm/music/Sigur+R%C3%B3s/_/Svefn-g-englar",
                "artist": {"name": "Sigur Rós"},
            },
        ],
        "@attr": {
            "user": "CanonicalUser",
            "page": "1",
            "perPage": "200",
            "totalPages": "1",
            "total": "2",
        },
    }
}

PROFILE_RESPONSE = {
    "user": {
        "url": "https://www.last.fm/user/CanonicalUser",
        "realname": "Pessoa Canônica",
        "image": [
            {"size": "small", "#text": "https://last.fm/small.jpg"},
            {"size": "large", "#text": "https://last.fm/large.jpg"},
        ],
        "playcount": "1234",
    }
}


class StubJsonTransport:
    def __init__(
        self,
        response: JsonHttpResponse,
        responses: list[JsonHttpResponse] | None = None,
    ) -> None:
        self.response = response
        self.responses = responses or [response]
        self.requested_url: str | None = None
        self.requested_urls: list[str] = []

    async def get_json(self, url: str) -> JsonHttpResponse:
        self.requested_urls.append(url)
        if self.requested_url is None:
            self.requested_url = url
        index = len(self.requested_urls) - 1
        return self.responses[min(index, len(self.responses) - 1)]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_lastfm_provider_builds_request_and_parses_top_tracks() -> None:
    transport = StubJsonTransport(JsonHttpResponse(200, SUCCESS_RESPONSE))
    provider = LastFmListeningHistoryProvider("test-api-key", transport)

    history = await provider.get_history(
        username="name with spaces",
        period=ListeningPeriod.SIX_MONTHS,
    )

    assert transport.requested_url is not None
    query = parse_qs(urlparse(transport.requested_url).query)
    assert query == {
        "method": ["user.gettoptracks"],
        "user": ["name with spaces"],
        "api_key": ["test-api-key"],
        "format": ["json"],
        "period": ["6month"],
        "limit": ["200"],
        "page": ["1"],
    }
    assert history.username == "CanonicalUser"
    assert history.history_source is DataSource.LASTFM
    assert len(history.tracks) == 2
    assert history.tracks[0].artist == "Radiohead"
    assert history.tracks[0].play_count == 42
    assert history.tracks[0].mbid == "test-track-mbid"
    assert history.tracks[0].release_mbid == "test-release-mbid"
    assert history.tracks[0].artist_mbid == "test-artist-mbid"
    assert history.tracks[1].mbid is None
    assert history.tracks[0].layers == ()


@pytest.mark.anyio
async def test_lastfm_provider_parses_optional_profile_metadata() -> None:
    transport = StubJsonTransport(
        JsonHttpResponse(200, SUCCESS_RESPONSE),
        responses=[
            JsonHttpResponse(200, SUCCESS_RESPONSE),
            JsonHttpResponse(200, PROFILE_RESPONSE),
        ],
    )
    provider = LastFmListeningHistoryProvider("test-api-key", transport)

    history = await provider.get_history("listener", ListeningPeriod.OVERALL)

    assert history.profile is not None
    assert history.profile.profile_url == "https://www.last.fm/user/CanonicalUser"
    assert history.profile.avatar_url == "https://last.fm/large.jpg"
    assert history.profile.realname == "Pessoa Canônica"
    assert history.profile.total_scrobbles == 1234
    assert len(transport.requested_urls) == 2
    assert parse_qs(urlparse(transport.requested_urls[1]).query)["method"] == [
        "user.getinfo"
    ]


@pytest.mark.anyio
async def test_lastfm_provider_keeps_history_when_optional_profile_read_fails() -> None:
    transport = StubJsonTransport(
        JsonHttpResponse(200, SUCCESS_RESPONSE),
        responses=[
            JsonHttpResponse(200, SUCCESS_RESPONSE),
            JsonHttpResponse(503, {"error": 29, "message": "Rate limit exceeded"}),
        ],
    )
    provider = LastFmListeningHistoryProvider("test-api-key", transport)

    history = await provider.get_history("listener", ListeningPeriod.OVERALL)

    assert history.tracks
    assert history.profile is None


def test_lastfm_provider_rejects_a_candidate_limit_above_two_hundred() -> None:
    with pytest.raises(ValueError, match="between 1 and 200"):
        LastFmListeningHistoryProvider(
            "test-api-key",
            StubJsonTransport(JsonHttpResponse(200, SUCCESS_RESPONSE)),
            limit=201,
        )


@pytest.mark.anyio
async def test_lastfm_provider_keeps_at_most_two_hundred_candidates() -> None:
    tracks = [
        {
            "name": f"Track {index}",
            "playcount": "1",
            "artist": {"name": "Artist"},
        }
        for index in range(205)
    ]
    provider = LastFmListeningHistoryProvider(
        "test-api-key",
        StubJsonTransport(JsonHttpResponse(200, {"toptracks": {"track": tracks}})),
    )

    history = await provider.get_history("listener", ListeningPeriod.OVERALL)

    assert len(history.tracks) == 200
    assert history.tracks[-1].title == "Track 199"


@pytest.mark.anyio
async def test_lastfm_provider_accepts_a_single_track_object() -> None:
    body = {
        "toptracks": {
            "track": SUCCESS_RESPONSE["toptracks"]["track"][0],
            "@attr": {"user": "one-track-user"},
        }
    }
    provider = LastFmListeningHistoryProvider(
        "test-api-key",
        StubJsonTransport(JsonHttpResponse(200, body)),
    )

    history = await provider.get_history("one-track-user", ListeningPeriod.OVERALL)

    assert len(history.tracks) == 1


@pytest.mark.anyio
async def test_lastfm_provider_maps_profile_not_found() -> None:
    provider = LastFmListeningHistoryProvider(
        "test-api-key",
        StubJsonTransport(
            JsonHttpResponse(200, {"error": 6, "message": "User not found"})
        ),
    )

    with pytest.raises(LastFmProfileNotFoundError):
        await provider.get_history("missing", ListeningPeriod.OVERALL)


@pytest.mark.anyio
async def test_lastfm_provider_maps_rate_limit() -> None:
    provider = LastFmListeningHistoryProvider(
        "test-api-key",
        StubJsonTransport(
            JsonHttpResponse(200, {"error": 29, "message": "Rate limit exceeded"})
        ),
    )

    with pytest.raises(LastFmRateLimitError):
        await provider.get_history("listener", ListeningPeriod.OVERALL)


@pytest.mark.anyio
async def test_lastfm_provider_maps_invalid_key() -> None:
    provider = LastFmListeningHistoryProvider(
        "test-api-key",
        StubJsonTransport(
            JsonHttpResponse(200, {"error": 10, "message": "Invalid API key"})
        ),
    )

    with pytest.raises(LastFmConfigurationError):
        await provider.get_history("listener", ListeningPeriod.OVERALL)


@pytest.mark.anyio
async def test_lastfm_provider_rejects_invalid_payload() -> None:
    provider = LastFmListeningHistoryProvider(
        "test-api-key",
        StubJsonTransport(JsonHttpResponse(200, {"unexpected": []})),
    )

    with pytest.raises(LastFmInvalidResponseError):
        await provider.get_history("listener", ListeningPeriod.OVERALL)


@pytest.mark.anyio
async def test_lastfm_provider_maps_http_failure() -> None:
    provider = LastFmListeningHistoryProvider(
        "test-api-key",
        StubJsonTransport(JsonHttpResponse(503, {})),
    )

    with pytest.raises(LastFmUnavailableError):
        await provider.get_history("listener", ListeningPeriod.OVERALL)


@pytest.mark.anyio
async def test_v2_endpoint_combines_lastfm_history_with_snapshot_projection() -> None:
    service = V2AnalysisService(
        history_provider=LastFmListeningHistoryProvider(
            "test-api-key",
            StubJsonTransport(
                JsonHttpResponse(200, SUCCESS_RESPONSE),
                responses=[
                    JsonHttpResponse(200, SUCCESS_RESPONSE),
                    JsonHttpResponse(200, PROFILE_RESPONSE),
                ],
            ),
        ),
        snapshot_provider=MockSnapshotProjectionProvider(),
    )

    async def get_test_analysis_service() -> V2AnalysisService:
        return service

    app.dependency_overrides[get_v2_analysis_service] = get_test_analysis_service
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.get("/v2/profiles/listener/analysis")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["username"] == "CanonicalUser"
    assert body["profile"]["profile_url"] == "https://www.last.fm/user/CanonicalUser"
    assert body["profile"]["avatar_url"] == "https://last.fm/large.jpg"
    assert body["profile"]["realname"] == "Pessoa Canônica"
    assert body["profile"]["total_scrobbles"] == 1234
    assert body["track_palette"]["analysis"]["history_source"] == "lastfm"
    assert body["track_palette"]["analysis"]["instrumentation_source"] == "mock"
    assert any(track["artist"] == "Radiohead" for track in body["track_palette"]["recordings"])
    assert all(track["lastfm_url"].startswith("https://www.last.fm/") for track in body["track_palette"]["recordings"])
