import httpx
import pytest

from palette_api.api import app, get_v2_analysis_service
from palette_api.mocks import MockListeningHistoryProvider
from palette_api.v2 import MockSnapshotProjectionProvider, V2AnalysisService


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_reference_versions_preserve_values_but_separate_prose():
    async def service():
        return V2AnalysisService(MockListeningHistoryProvider(), MockSnapshotProjectionProvider())

    app.dependency_overrides[get_v2_analysis_service] = service
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            old = await client.get("/v2/profiles/example/analysis")
            new = await client.get("/v3/profiles/example/analysis")
    finally:
        app.dependency_overrides.clear()

    assert old.status_code == new.status_code == 200
    legacy, structured = old.json(), new.json()
    assert structured["report_schema_version"] == "profile-analysis-v3"
    assert "report_schema_version" not in legacy
    assert old.headers["cache-control"] == new.headers["cache-control"]
    for key in ("profile", "snapshot", "hydration", "available_views", "default_view"):
        assert structured[key] == legacy[key]
    assert "notice" not in structured["track_palette"]["analysis"]
    assert "notice" not in structured["artist_vocabulary"]
    assert isinstance(legacy["track_palette"]["analysis"]["notice"], str)
    assert isinstance(legacy["artist_vocabulary"]["notice"], str)
    for key in ("coverage_tracks", "coverage_plays", "vocal_presence", "recording_status_counts", "methodology_version"):
        assert structured["track_palette"]["analysis"][key] == legacy["track_palette"]["analysis"][key]
    for key in ("reach", "concentration", "families", "availability"):
        assert structured["artist_vocabulary"][key] == legacy["artist_vocabulary"][key]
    assert all("status_detail" not in recording for recording in structured["track_palette"]["recordings"])
    assert structured["track_palette"]["temperament"]["rule"]
    assert "title" not in structured["track_palette"]["temperament"]
    assert isinstance(legacy["track_palette"]["temperament"]["title"], str)


@pytest.mark.anyio
async def test_structured_example_is_reproducible_and_excludes_generated_prose():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = await client.get("/v3/examples/analysis?sample_id=localization&period=1month")
        second = await client.get("/v3/examples/analysis?sample_id=localization&period=1month")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.headers["cache-control"] == "no-store"
    report = first.json()
    assert report["is_example"] is True
    assert report["example_id"] == "localization"

    def check(value):
        if isinstance(value, dict):
            assert not {"notice", "summary", "disclaimer", "caption", "status_detail"}.intersection(value)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(report)
