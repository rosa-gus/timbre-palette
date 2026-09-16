import sqlite3
from pathlib import Path

import pytest

from palette_api.domain import Track
from palette_api.lastfm import JsonHttpResponse
from palette_api.musicbrainz import (
    D1IdentityRepository,
    InstrumentCredit,
    MusicBrainzEnricher,
    MusicBrainzInvalidResponseError,
    MusicBrainzResolver,
    MusicBrainzUnavailableError,
    ResolvedRecording,
    WorkersFetchJsonTransport,
)


class StubTransport:
    def __init__(self, responses: dict[str, JsonHttpResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    async def get_json(self, url: str) -> JsonHttpResponse:
        self.urls.append(url)
        for key, response in self.responses.items():
            if key in url:
                return response
        raise AssertionError(f"URL inesperada: {url}")


@pytest.mark.anyio
async def test_workers_transport_reserves_global_rate_gate_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workers

    class Response:
        status = 200
        headers = {}

        async def json(self) -> dict[str, str]:
            return {"id": "recording-mbid"}

    fetch_urls: list[str] = []

    async def fake_fetch(url: str, **kwargs: object) -> Response:
        fetch_urls.append(url)
        return Response()

    monkeypatch.setattr(workers, "fetch", fake_fetch, raising=False)

    class RateGate:
        def __init__(self) -> None:
            self.intervals: list[int] = []

        async def acquire_slot(self, minimum_interval_ms: int) -> dict[str, int]:
            self.intervals.append(minimum_interval_ms)
            return {"wait_ms": 37}

    waits: list[int] = []
    gate = RateGate()
    transport = WorkersFetchJsonTransport(
        user_agent="test-agent",
        minimum_interval_ms=1500,
        rate_gate=gate,
        wait=lambda delay_ms: _record_wait(waits, delay_ms),
    )

    response = await transport.get_json(
        "https://musicbrainz.org/ws/2/recording/recording-mbid?fmt=json"
    )

    assert response.status_code == 200
    assert fetch_urls == [
        "https://musicbrainz.org/ws/2/recording/recording-mbid?fmt=json"
    ]
    assert gate.intervals == [1500]
    assert waits == [37]


@pytest.mark.anyio
async def test_workers_transport_fails_closed_when_rate_gate_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workers

    fetch_called = False

    async def fake_fetch(url: str, **kwargs: object) -> object:
        nonlocal fetch_called
        fetch_called = True
        raise AssertionError("MusicBrainz must not be called without a rate slot.")

    monkeypatch.setattr(workers, "fetch", fake_fetch, raising=False)

    class RateGate:
        async def acquire_slot(self, minimum_interval_ms: int) -> object:
            raise RuntimeError("gate unavailable")

    transport = WorkersFetchJsonTransport(
        rate_gate=RateGate(),
        wait=lambda delay_ms: _record_wait([], delay_ms),
    )

    with pytest.raises(MusicBrainzUnavailableError) as raised:
        await transport.get_json(
            "https://musicbrainz.org/ws/2/recording/recording-mbid?fmt=json"
        )

    assert raised.value.reason_code == "rate_gate_unavailable"
    assert not fetch_called


async def _record_wait(target: list[int], delay_ms: int) -> None:
    target.append(delay_ms)


class D1Statement:
    def __init__(self, conn: sqlite3.Connection, query: str, params: tuple = ()) -> None:
        self.conn = conn
        self.query = query
        self.params = params

    def bind(self, *params: object) -> "D1Statement":
        return D1Statement(self.conn, self.query, params)

    async def first(self) -> dict | None:
        cursor = self.conn.execute(self.query, self.params)
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([column[0] for column in cursor.description], row))

    async def run(self) -> None:
        self.conn.execute(self.query, self.params)
        self.conn.commit()


class D1Database:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def prepare(self, query: str) -> D1Statement:
        return D1Statement(self.conn, query)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "reason_code"),
    ((429, "rate_limited"), (503, "upstream_server_error")),
)
async def test_resolver_preserves_upstream_error_context(
    status_code: int,
    reason_code: str,
) -> None:
    transport = StubTransport(
        {
            "/recording/recording-mbid": JsonHttpResponse(
                status_code,
                None,
                retry_after_seconds=120 if status_code == 429 else None,
            )
        }
    )

    with pytest.raises(MusicBrainzUnavailableError) as raised:
        await MusicBrainzResolver(transport).resolve(
            Track("Song", "Artist", 1, mbid="recording-mbid")
        )

    error = raised.value
    assert error.reason_code == reason_code
    assert error.operation == "recording_lookup"
    assert error.status_code == status_code
    assert error.retry_after_seconds == (120 if status_code == 429 else None)


@pytest.mark.anyio
async def test_resolver_wraps_transport_error_with_operation() -> None:
    class FailingTransport:
        async def get_json(self, url: str) -> JsonHttpResponse:
            raise TimeoutError("socket closed")

    with pytest.raises(MusicBrainzUnavailableError) as raised:
        await MusicBrainzResolver(FailingTransport()).resolve(
            Track("Song", "Artist", 1, mbid="recording-mbid")
        )

    error = raised.value
    assert error.reason_code == "transport_error"
    assert error.operation == "recording_lookup"
    assert isinstance(error.__cause__, TimeoutError)


@pytest.mark.anyio
async def test_resolver_marks_invalid_payload_with_operation() -> None:
    transport = StubTransport(
        {"/recording/recording-mbid": JsonHttpResponse(200, {"title": "Song"})}
    )

    with pytest.raises(MusicBrainzInvalidResponseError) as raised:
        await MusicBrainzResolver(transport).resolve(
            Track("Song", "Artist", 1, mbid="recording-mbid")
        )

    assert raised.value.reason_code == "invalid_response"
    assert raised.value.operation == "recording_lookup"


def seeded_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    root = Path(__file__).resolve().parent.parent
    conn.executescript((root / "migrations/0001_initial_schema.sql").read_text())
    conn.executescript((root / "migrations/0002_seed_taxonomy.sql").read_text())
    conn.executescript((root / "migrations/0005_analysis_contract.sql").read_text())
    conn.executescript((root / "migrations/0006_enrichment_outbox.sql").read_text())
    conn.executescript(
        (root / "migrations/0007_family_claims_and_conservative_mapping.sql").read_text()
    )
    return conn


def legacy_db_with_generic_claim() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    root = Path(__file__).resolve().parent.parent
    for migration in (
        "0001_initial_schema.sql",
        "0002_seed_taxonomy.sql",
        "0005_analysis_contract.sql",
        "0006_enrichment_outbox.sql",
    ):
        conn.executescript((root / "migrations" / migration).read_text())
    conn.execute(
        "INSERT INTO recordings (id, title, artist, canonical_mbid) "
        "VALUES (1, 'Song', 'Artist', 'recording-mbid')"
    )
    conn.execute(
        """
        INSERT INTO instrument_credit_candidates
            (recording_id, source, instrument_name, instrument_slug, performer,
             original_credit, scope, resolution_method, status)
        VALUES (1, 'musicbrainz', 'guitar', 'electric-guitar', 'Artist',
                'guitar', 'recording', 'alias', 'promoted')
        """
    )
    claim_id = conn.execute(
        """
        INSERT INTO instrument_claims
            (recording_id, instrument_slug, confidence_level, performer)
        VALUES (1, 'electric-guitar', 'documented', 'Artist')
        RETURNING id
        """
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO evidence_items
            (claim_id, source, source_url, original_credit, scope)
        VALUES (?, 'musicbrainz', 'https://musicbrainz.org/recording/recording-mbid',
                'guitar', 'recording')
        """,
        (claim_id,),
    )
    conn.commit()
    return conn


@pytest.mark.anyio
async def test_resolver_converts_track_mbid_to_recording() -> None:
    transport = StubTransport(
        {
            "/recording/track-mbid": JsonHttpResponse(404, {}),
            "query=tid%3Atrack-mbid": JsonHttpResponse(
                200, {"recordings": [{"id": "recording-mbid"}]}
            ),
            "/recording/recording-mbid": JsonHttpResponse(
                200,
                {
                    "id": "recording-mbid",
                    "title": "Song",
                    "artist-credit": [{"name": "Artist"}],
                    "relations": [
                        {
                            "type": "instrument",
                            "artist": {"name": "Artist"},
                            "attributes": ["electric guitar"],
                        }
                    ],
                },
            ),
        }
    )
    match = await MusicBrainzResolver(transport).resolve(
        Track("Song", "Artist", 2, mbid="track-mbid")
    )

    assert match is not None
    assert match.mbid == "recording-mbid"
    assert match.method == "mbid_track_converted"
    assert match.source_entity_type == "track"
    assert match.instrument_credits[0].instrument_name == "electric guitar"
    assert any(
        "/recording/recording-mbid?inc=artist-credits+artist-rels&fmt=json" in url
        for url in transport.urls
    )


@pytest.mark.anyio
async def test_resolver_promotes_vocal_relations_to_voice_credits() -> None:
    transport = StubTransport(
        {
            "/recording/recording-mbid": JsonHttpResponse(
                200,
                {
                    "id": "recording-mbid",
                    "title": "Song",
                    "artist-credit": [{"name": "Artist"}],
                    "relations": [
                        {"type": "vocal", "artist": {"name": "Singer"}},
                        {"type": "vocals", "artist": {"name": "Choir"}},
                    ],
                },
            )
        }
    )

    match = await MusicBrainzResolver(transport).resolve(
        Track("Song", "Artist", 2, mbid="recording-mbid")
    )

    assert match is not None
    assert [credit.instrument_name for credit in match.instrument_credits] == [
        "voice",
        "voice",
    ]


def test_migration_reclassifies_old_generic_claim_without_losing_evidence() -> None:
    conn = legacy_db_with_generic_claim()
    root = Path(__file__).resolve().parent.parent

    conn.executescript(
        (root / "migrations/0007_family_claims_and_conservative_mapping.sql").read_text()
    )

    assert conn.execute(
        "SELECT instrument_slug, family_slug FROM instrument_claims"
    ).fetchone() == (None, "plucked-strings")
    assert conn.execute(
        "SELECT original_credit, scope FROM evidence_items"
    ).fetchone() == ("guitar", "recording")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.anyio
async def test_resolver_uses_exact_search_when_mbid_is_missing() -> None:
    transport = StubTransport(
        {
            "/recording/?": JsonHttpResponse(
                200,
                {
                    "recordings": [
                        {
                            "id": "searched-mbid",
                            "title": "Song",
                            "artist-credit": [{"artist": {"name": "Artist"}}],
                        }
                    ]
                },
            ),
            "/recording/searched-mbid": JsonHttpResponse(
                200,
                {
                    "id": "searched-mbid",
                    "title": "Song",
                    "artist-credit": [{"artist": {"name": "Artist"}}],
                },
            ),
        }
    )
    match = await MusicBrainzResolver(transport).resolve(
        Track("Song", "Artist", 2)
    )

    assert match is not None
    assert match.method == "text_search_exact"
    assert match.confidence == 0.95


@pytest.mark.anyio
async def test_text_search_hydrates_instrument_relations() -> None:
    transport = StubTransport(
        {
            "/recording/?": JsonHttpResponse(
                200,
                {
                    "recordings": [
                        {
                            "id": "searched-mbid",
                            "title": "Song",
                            "artist-credit": [{"artist": {"name": "Artist"}}],
                        }
                    ]
                },
            ),
            "/recording/searched-mbid": JsonHttpResponse(
                200,
                {
                    "id": "searched-mbid",
                    "title": "Song",
                    "artist-credit": [{"artist": {"name": "Artist"}}],
                    "relations": [
                        {
                            "type": "instrument",
                            "artist": {"name": "Artist"},
                            "attributes": ["guitar"],
                        }
                    ],
                },
            ),
        }
    )

    match = await MusicBrainzResolver(transport).resolve(Track("Song", "Artist", 1))

    assert match is not None
    assert match.instrument_credits[0].original_credit == "guitar"
    assert any("/recording/searched-mbid?" in url for url in transport.urls)


@pytest.mark.anyio
async def test_text_search_without_mbid_persists_documented_credit() -> None:
    conn = seeded_db()
    transport = StubTransport(
        {
            "/recording/?": JsonHttpResponse(
                200,
                {
                    "recordings": [
                        {
                            "id": "searched-mbid",
                            "title": "Song",
                            "artist-credit": [{"artist": {"name": "Artist"}}],
                        }
                    ]
                },
            ),
            "/recording/searched-mbid": JsonHttpResponse(
                200,
                {
                    "id": "searched-mbid",
                    "title": "Song",
                    "artist-credit": [{"artist": {"name": "Artist"}}],
                    "relations": [
                        {
                            "type": "instrument",
                            "artist": {"name": "Artist"},
                            "attributes": ["electric guitar"],
                        }
                    ],
                },
            ),
        }
    )
    enricher = MusicBrainzEnricher(
        MusicBrainzResolver(transport), D1IdentityRepository(D1Database(conn))
    )

    await enricher.enrich_track(Track("Song", "Artist", 1))

    assert conn.execute(
        "SELECT instrument_slug, confidence_level FROM instrument_claims"
    ).fetchone() == ("electric-guitar", "documented")


@pytest.mark.anyio
async def test_identity_repository_persists_match_idempotently() -> None:
    conn = seeded_db()
    repository = D1IdentityRepository(D1Database(conn))
    track = Track("Song", "Artist", 2, mbid="lastfm-track")
    match = ResolvedRecording(
        mbid="recording-mbid",
        title="Song",
        artist="Artist",
        method="mbid_track_converted",
        confidence=0.98,
        source_mbid="lastfm-track",
        source_entity_type="track",
    )

    await repository.save_match(track, match)
    await repository.save_match(track, match)

    assert conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM recording_identifiers").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM identity_matches").fetchone()[0] == 1


@pytest.mark.anyio
async def test_enricher_persists_each_resolved_track() -> None:
    conn = seeded_db()
    resolver = MusicBrainzResolver(
        StubTransport(
            {
                "/recording/recording-mbid": JsonHttpResponse(
                    200,
                    {
                        "id": "recording-mbid",
                        "title": "Song",
                        "artist-credit": [{"name": "Artist"}],
                        "relations": [
                            {
                                "type": "instrument",
                                "artist": {"name": "Artist"},
                                "attributes": ["electric guitar"],
                            }
                        ],
                    },
                )
            }
        )
    )
    enricher = MusicBrainzEnricher(resolver, D1IdentityRepository(D1Database(conn)))

    from palette_api.domain import ListeningHistory, ListeningPeriod

    await enricher.enrich(
        ListeningHistory(
            username="listener",
            period=ListeningPeriod.SEVEN_DAYS,
            tracks=(Track("Song", "Artist", 1, mbid="recording-mbid"),),
        )
    )

    assert conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM instrument_credit_candidates").fetchone()[0] == 1
    candidate = conn.execute(
        """
        SELECT instrument_slug, resolution_method, status
        FROM instrument_credit_candidates
        """
    ).fetchone()
    assert candidate == ("electric-guitar", "alias", "promoted")
    assert conn.execute(
        "SELECT instrument_slug, confidence_level FROM instrument_claims"
    ).fetchone() == ("electric-guitar", "documented")
    assert conn.execute(
        "SELECT source, scope FROM evidence_items"
    ).fetchone() == ("musicbrainz", "recording")
    assert conn.execute("SELECT status FROM enrichment_state").fetchone()[0] == "completed"


@pytest.mark.anyio
async def test_external_instrument_mbid_mapping_takes_precedence() -> None:
    conn = seeded_db()
    conn.execute(
        """
        INSERT INTO instrument_external_identifiers
            (instrument_slug, source, external_id)
        VALUES ('electric-guitar', 'musicbrainz', 'instrument-mbid')
        """
    )
    conn.commit()
    repository = D1IdentityRepository(D1Database(conn))
    match = ResolvedRecording(
        mbid="recording-mbid",
        title="Song",
        artist="Artist",
        method="mbid_recording",
        confidence=1.0,
        source_mbid="recording-mbid",
        source_entity_type="recording",
        instrument_credits=(
            InstrumentCredit("instrument-mbid", "unknown external label", "Artist"),
        ),
    )

    await repository.save_enrichment(Track("Song", "Artist", 1), match)

    assert conn.execute(
        "SELECT instrument_slug, resolution_method FROM instrument_credit_candidates"
    ).fetchone() == ("electric-guitar", "external_id")


@pytest.mark.anyio
async def test_generic_guitar_is_published_as_family_claim() -> None:
    conn = seeded_db()
    repository = D1IdentityRepository(D1Database(conn))
    match = ResolvedRecording(
        mbid="recording-mbid",
        title="Song",
        artist="Artist",
        method="mbid_recording",
        confidence=1.0,
        source_mbid="recording-mbid",
        source_entity_type="recording",
        instrument_credits=(InstrumentCredit(None, "guitar", "Artist"),),
    )

    recording_id = await repository.save_enrichment(Track("Song", "Artist", 1), match)

    assert conn.execute(
        "SELECT instrument_slug, family_slug, resolution_method FROM instrument_credit_candidates"
    ).fetchone() == (None, "plucked-strings", "family_alias")
    assert conn.execute(
        "SELECT instrument_slug, family_slug, confidence_level FROM instrument_claims"
    ).fetchone() == (None, "plucked-strings", "documented")
    assert conn.execute(
        "SELECT original_credit, scope, source_quality FROM evidence_items"
    ).fetchone() == ("guitar", "recording", "direct_relation")
    assert await repository.accepted_claim_count(recording_id) == 1


@pytest.mark.anyio
async def test_generic_bass_stays_in_editorial_queue() -> None:
    conn = seeded_db()
    repository = D1IdentityRepository(D1Database(conn))
    match = ResolvedRecording(
        mbid="recording-mbid",
        title="Song",
        artist="Artist",
        method="mbid_recording",
        confidence=1.0,
        source_mbid="recording-mbid",
        source_entity_type="recording",
        instrument_credits=(InstrumentCredit(None, "bass", "Artist"),),
    )

    await repository.save_enrichment(Track("Song", "Artist", 1), match)

    assert conn.execute(
        "SELECT instrument_slug, family_slug, status, queue_reason "
        "FROM instrument_credit_candidates"
    ).fetchone() == (None, None, "pending", "unmapped_instrument_name")
    assert conn.execute("SELECT COUNT(*) FROM instrument_claims").fetchone()[0] == 0


@pytest.mark.anyio
async def test_release_scope_remains_context_only() -> None:
    conn = seeded_db()
    repository = D1IdentityRepository(D1Database(conn))
    match = ResolvedRecording(
        mbid="recording-mbid",
        title="Song",
        artist="Artist",
        method="mbid_recording",
        confidence=1.0,
        source_mbid="recording-mbid",
        source_entity_type="recording",
        instrument_credits=(
            InstrumentCredit(
                None,
                "guitar",
                "Artist",
                scope="release",
                source_url="https://example.test/release",
                source_quality="release_credit",
            ),
        ),
    )

    recording_id = await repository.save_enrichment(Track("Song", "Artist", 1), match)

    assert conn.execute(
        "SELECT family_slug, confidence_level FROM instrument_claims"
    ).fetchone() == ("plucked-strings", "release_context")
    assert conn.execute(
        "SELECT source_url, scope, source_quality FROM evidence_items"
    ).fetchone() == (
        "https://example.test/release",
        "release",
        "release_credit",
    )
    assert await repository.accepted_claim_count(recording_id) == 0
