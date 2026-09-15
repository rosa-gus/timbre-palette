import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from palette_api.api import app, get_instrument_catalog, get_catalog_stats
from palette_api.catalog import D1InstrumentCatalog, D1InstrumentationProvider
from palette_api.domain import ClaimLevel, DataSource, ListeningHistory, ListeningPeriod, Track
from palette_api.editorial import D1EditorialCandidateQueue
from palette_api.enrichment import D1QueueEnrichmentScheduler


class MockD1Statement:
    def __init__(self, conn: sqlite3.Connection, query: str, params: tuple = ()) -> None:
        self._conn = conn
        self._query = query
        self._params = params

    def bind(self, *params: object) -> "MockD1Statement":
        return MockD1Statement(self._conn, self._query, params)

    async def first(self) -> dict | None:
        cur = self._conn.cursor()
        cur.execute(self._query, self._params)
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    async def all(self) -> object:
        cur = self._conn.cursor()
        cur.execute(self._query, self._params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        results = [dict(zip(cols, r)) for r in rows]

        class D1Result:
            def __init__(self, res: list[dict]) -> None:
                self.results = res

        return D1Result(results)

    async def run(self) -> object:
        cur = self._conn.cursor()
        cur.execute(self._query, self._params)
        self._conn.commit()
        return SimpleNamespace(meta=SimpleNamespace(changes=max(cur.rowcount, 0)))


class MockD1Database:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def prepare(self, query: str) -> MockD1Statement:
        return MockD1Statement(self._conn, query)


@pytest.mark.anyio
async def test_catalog_stats_counts_unique_recordings_with_accepted_evidence(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    from starlette.requests import Request
    import json

    conn = seeded_sqlite_conn
    baseline = json.loads((await get_catalog_stats(Request({
        "type": "http", "env": {"DB": MockD1Database(conn)},
    }))).body)["recordings_with_evidence"]
    for title, confidence, scopes in [
        ("Accepted", "documented", ["recording", "track"]),
        ("Release only", "documented", ["release"]),
        ("Tentative", "tentative", ["recording"]),
        ("No evidence", "documented", []),
    ]:
        recording_id = conn.execute(
            "INSERT INTO recordings (title, artist) VALUES (?, 'Test')", (title,),
        ).lastrowid
        claim_id = conn.execute(
            "INSERT INTO instrument_claims (recording_id, instrument_slug, confidence_level) VALUES (?, 'electric-guitar', ?)",
            (recording_id, confidence),
        ).lastrowid
        for scope in scopes:
            conn.execute(
                "INSERT INTO evidence_items (claim_id, source, scope, source_url) VALUES (?, 'musicbrainz', ?, 'https://example.com')",
                (claim_id, scope),
            )
    response = await get_catalog_stats(Request({
        "type": "http", "env": {"DB": MockD1Database(conn)},
    }))
    assert json.loads(response.body)["recordings_with_evidence"] == baseline + 1
    assert response.headers["cache-control"] == "public, max-age=300, s-maxage=300"


@pytest.fixture
def seeded_sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    project_root = Path(__file__).resolve().parent.parent
    migration_1 = project_root / "migrations" / "0001_initial_schema.sql"
    migration_2 = project_root / "migrations" / "0002_seed_taxonomy.sql"
    migration_3 = project_root / "migrations" / "0003_update_editorial_catalog.sql"
    migration_4 = project_root / "migrations" / "0004_editorial_claim_metadata.sql"
    migration_5 = project_root / "migrations" / "0005_analysis_contract.sql"
    migration_6 = project_root / "migrations" / "0006_enrichment_outbox.sql"
    migration_7 = project_root / "migrations" / "0007_family_claims_and_conservative_mapping.sql"
    migration_8 = project_root / "migrations" / "0008_methodology_020.sql"
    migration_10 = project_root / "migrations" / "0010_instrument_editorial_scope.sql"

    for migration in (
        migration_1,
        migration_2,
        migration_3,
        migration_4,
        migration_5,
        migration_6,
        migration_7,
        migration_8,
        migration_10,
    ):
        with open(migration, encoding="utf-8") as f:
            conn.executescript(f.read())

    yield conn
    conn.close()


@pytest.mark.anyio
async def test_d1_catalog_retrieves_instrument(seeded_sqlite_conn: sqlite3.Connection) -> None:
    db = MockD1Database(seeded_sqlite_conn)
    catalog = D1InstrumentCatalog(db)

    resource = await catalog.get("electric-guitar")
    assert resource is not None
    assert resource.slug == "electric-guitar"
    assert resource.name == "Guitarra elétrica"
    assert resource.kind == "instrument"
    assert resource.family_slug == "plucked-strings"
    assert resource.data_source == "catalog"
    assert resource.catalog_version == "0.1.4"
    assert "harmonia" in resource.common_roles
    assert "plucked-strings" in resource.related_slugs
    assert resource.sections == []
    assert resource.sources == []


@pytest.mark.anyio
async def test_d1_catalog_projects_sourced_block_with_verified_support(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    seeded_sqlite_conn.execute(
        """
        UPDATE editorial_content_blocks
        SET claim_support_verified = 1
        WHERE id = 'instrument-electric-guitar-curiosity'
        """
    )
    seeded_sqlite_conn.commit()

    resource = await D1InstrumentCatalog(MockD1Database(seeded_sqlite_conn)).get(
        "electric-guitar"
    )

    assert resource is not None
    assert [section.kind for section in resource.sections] == ["curiosity"]
    assert resource.sections[0].status == "sourced"
    assert resource.sections[0].review.source_metadata_verified is True
    assert resource.sections[0].review.claim_support_verified is True
    assert resource.sections[0].citations[0].source_id == "smithsonian-electric-guitar"
    assert resource.sources[0].publisher == "Smithsonian National Museum of American History"
    assert resource.sources[0].metadata_verified is True
    assert resource.sources[0].verified_at == "2026-09-12"


@pytest.mark.anyio
async def test_d1_catalog_hides_block_with_unverified_source_metadata(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    seeded_sqlite_conn.execute(
        """
        UPDATE editorial_content_blocks
        SET claim_support_verified = 1
        WHERE id = 'instrument-electric-guitar-curiosity'
        """
    )
    seeded_sqlite_conn.execute(
        """
        UPDATE editorial_sources
        SET metadata_verified = 0
        WHERE id = 'smithsonian-electric-guitar'
        """
    )
    seeded_sqlite_conn.commit()

    resource = await D1InstrumentCatalog(MockD1Database(seeded_sqlite_conn)).get(
        "electric-guitar"
    )

    assert resource is not None
    assert resource.sections == []
    assert resource.sources == []


@pytest.mark.anyio
async def test_d1_catalog_retrieves_family(seeded_sqlite_conn: sqlite3.Connection) -> None:
    db = MockD1Database(seeded_sqlite_conn)
    catalog = D1InstrumentCatalog(db)

    resource = await catalog.get("plucked-strings")
    assert resource is not None
    assert resource.slug == "plucked-strings"
    assert resource.name == "Cordas dedilhadas"
    assert resource.kind == "family"
    assert resource.family_slug is None
    assert resource.data_source == "catalog"
    assert "base rítmica" in resource.common_roles
    assert "electric-guitar" in resource.related_slugs


@pytest.mark.anyio
async def test_d1_catalog_resolves_legacy_slug_to_canonical_slug(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    catalog = D1InstrumentCatalog(MockD1Database(seeded_sqlite_conn))

    resource = await catalog.get("guitarra-eletrica")

    assert resource is not None
    assert resource.slug == "electric-guitar"


@pytest.mark.anyio
async def test_d1_catalog_does_not_project_draft_editorial_blocks(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    seeded_sqlite_conn.execute(
        """
        INSERT INTO editorial_content_blocks
            (id, instrument_slug, section_kind, text, status)
        VALUES ('draft-piano-block', 'piano', 'curiosity', 'Rascunho interno.', 'draft')
        """
    )
    seeded_sqlite_conn.commit()

    resource = await D1InstrumentCatalog(MockD1Database(seeded_sqlite_conn)).get("piano")

    assert resource is not None
    assert all(section.id != "draft-piano-block" for section in resource.sections)


@pytest.mark.anyio
async def test_instrument_sheet_without_curiosity_is_valid(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    seeded_sqlite_conn.execute("DELETE FROM editorial_content_blocks WHERE instrument_slug = 'piano'")
    resource = await D1InstrumentCatalog(MockD1Database(seeded_sqlite_conn)).get("piano")
    assert resource is not None
    assert resource.sections == []
    assert resource.sources == []
    assert resource.further_reading == []


def test_historical_origin_is_removed_from_the_database(seeded_sqlite_conn: sqlite3.Connection) -> None:
    for table in ("instruments", "instrument_families"):
        columns = {row[1] for row in seeded_sqlite_conn.execute(f"PRAGMA table_info({table})")}
        assert "origin" not in columns
    assert seeded_sqlite_conn.execute("SELECT COUNT(*) FROM editorial_content_blocks WHERE section_kind = 'origin'").fetchone()[0] == 0
    assert seeded_sqlite_conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.anyio
async def test_further_reading_only_exposes_reviewed_links(seeded_sqlite_conn: sqlite3.Connection) -> None:
    seeded_sqlite_conn.executemany(
        "INSERT INTO instrument_further_reading (id, instrument_slug, title, url, publisher, status) VALUES (?, 'piano', ?, ?, 'Instituição de teste', ?)",
        [("public-piano-link", "Artigo revisado", "https://example.com/piano", "reviewed"),
         ("draft-piano-link", "Rascunho", "https://example.com/draft", "draft")],
    )
    resource = await D1InstrumentCatalog(MockD1Database(seeded_sqlite_conn)).get("piano")
    assert resource is not None
    assert [link.title for link in resource.further_reading] == ["Artigo revisado"]
    assert str(resource.further_reading[0].url) == "https://example.com/piano"


@pytest.mark.anyio
async def test_d1_catalog_returns_none_for_unknown_slug(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    db = MockD1Database(seeded_sqlite_conn)
    catalog = D1InstrumentCatalog(db)

    resource = await catalog.get("inexistente")
    assert resource is None


@pytest.mark.anyio
async def test_d1_instrumentation_matches_mbid_and_returns_published_claims(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    seeded_sqlite_conn.execute(
        "INSERT INTO recordings (title, artist, canonical_mbid) VALUES (?, ?, ?)",
        ("Faixa catalogada", "Artista catalogado", "recording-mbid"),
    )
    recording_id = seeded_sqlite_conn.execute(
        "SELECT id FROM recordings WHERE canonical_mbid = ?",
        ("recording-mbid",),
    ).fetchone()[0]
    seeded_sqlite_conn.execute(
        """
        INSERT INTO recording_identifiers
            (recording_id, source, entity_type, external_id)
        VALUES (?, 'lastfm', 'track', ?)
        """,
        (recording_id, "lastfm-track-mbid"),
    )
    seeded_sqlite_conn.execute(
        """
        INSERT INTO instrument_claims
            (recording_id, instrument_slug, confidence_level, role, prominence)
        VALUES (?, 'electric-guitar', 'editorially_verified', ?, ?)
        """,
        (recording_id, "harmonia", 0.8),
    )
    guitar_claim_id = seeded_sqlite_conn.execute(
        "SELECT id FROM instrument_claims WHERE recording_id = ? AND instrument_slug = ?",
        (recording_id, "electric-guitar"),
    ).fetchone()[0]
    seeded_sqlite_conn.execute(
        """
        INSERT INTO evidence_items
            (claim_id, source, scope, source_url, original_credit)
        VALUES (?, 'musicbrainz', 'recording', ?, ?)
        """,
        (guitar_claim_id, "https://musicbrainz.org/recording/recording-mbid", "guitar"),
    )
    seeded_sqlite_conn.execute(
        """
        INSERT INTO instrument_claims
            (recording_id, instrument_slug, confidence_level, role, prominence)
        VALUES (?, 'electric-bass', 'release_context', ?, ?)
        """,
        (recording_id, "contexto", 1.0),
    )
    seeded_sqlite_conn.commit()

    provider = D1InstrumentationProvider(MockD1Database(seeded_sqlite_conn))
    history = await provider.enrich(
        ListeningHistory(
            username="listener",
            period=ListeningPeriod.SEVEN_DAYS,
            tracks=(
                Track(
                    title="Faixa catalogada",
                    artist="Artista catalogado",
                    play_count=3,
                    mbid="lastfm-track-mbid",
                ),
            ),
        )
    )

    assert history.instrumentation_source is DataSource.CATALOG
    assert history.catalog_version == "0.1.4"
    assert len(history.tracks[0].layers) == 1
    assert history.tracks[0].layers[0].slug == "electric-guitar"
    assert history.tracks[0].layers[0].confidence.value == "documented"


@pytest.mark.anyio
async def test_d1_instrumentation_marks_unknown_tracks_for_enrichment(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    provider = D1InstrumentationProvider(MockD1Database(seeded_sqlite_conn))
    history = await provider.enrich(
        ListeningHistory(
            username="listener",
            period=ListeningPeriod.SEVEN_DAYS,
            tracks=(Track("Unknown", "Artist", 1, mbid="unknown-mbid"),),
        )
    )

    assert history.tracks[0].layers == ()
    assert history.pending_enrichment == history.tracks


@pytest.mark.anyio
async def test_d1_instrumentation_projects_recording_family_claims(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    seeded_sqlite_conn.execute(
        "INSERT INTO recordings (title, artist, canonical_mbid) VALUES (?, ?, ?)",
        ("Faixa familiar", "Artista familiar", "family-recording"),
    )
    recording_id = seeded_sqlite_conn.execute(
        "SELECT id FROM recordings WHERE canonical_mbid = ?",
        ("family-recording",),
    ).fetchone()[0]
    seeded_sqlite_conn.execute(
        """
        INSERT INTO recording_identifiers
            (recording_id, source, entity_type, external_id)
        VALUES (?, 'lastfm', 'recording', ?)
        """,
        (recording_id, "family-lastfm"),
    )
    seeded_sqlite_conn.execute(
        """
        INSERT INTO instrument_claims
            (recording_id, family_slug, confidence_level, role, prominence)
        VALUES (?, 'percussion', 'documented', ?, ?)
        """,
        (recording_id, "pulso", 1.0),
    )
    family_claim_id = seeded_sqlite_conn.execute(
        "SELECT id FROM instrument_claims WHERE recording_id = ? AND family_slug = ?",
        (recording_id, "percussion"),
    ).fetchone()[0]
    seeded_sqlite_conn.execute(
        """
        INSERT INTO evidence_items
            (claim_id, source, scope, source_url, original_credit)
        VALUES (?, 'musicbrainz', 'recording', ?, ?)
        """,
        (family_claim_id, "https://musicbrainz.org/recording/family-recording", "drums"),
    )
    seeded_sqlite_conn.commit()

    history = await D1InstrumentationProvider(MockD1Database(seeded_sqlite_conn)).enrich(
        ListeningHistory(
            username="listener",
            period=ListeningPeriod.SEVEN_DAYS,
            tracks=(Track("Faixa familiar", "Artista familiar", 3, mbid="family-lastfm"),),
        )
    )

    assert len(history.tracks[0].layers) == 1
    layer = history.tracks[0].layers[0]
    assert layer.claim_level is ClaimLevel.FAMILY
    assert layer.slug == "percussion"
    assert layer.family_slug == "percussion"
    assert layer.nature is None


@pytest.mark.anyio
async def test_enrichment_scheduler_deduplicates_queue_messages(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    class Queue:
        def __init__(self) -> None:
            self.messages: list[object] = []

        async def send(self, body: object, **kwargs: object) -> None:
            self.messages.append(body)

    queue = Queue()
    scheduler = D1QueueEnrichmentScheduler(MockD1Database(seeded_sqlite_conn), queue)
    track = Track("Unknown", "Artist", 1, mbid="unknown-mbid")

    await scheduler.schedule((track,))
    await scheduler.schedule((track,))

    assert len(queue.messages) == 1
    assert seeded_sqlite_conn.execute(
        "SELECT COUNT(*) FROM enrichment_jobs"
    ).fetchone()[0] == 1


@pytest.mark.anyio
async def test_editorial_queue_prioritizes_unmapped_candidates(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    seeded_sqlite_conn.execute(
        "INSERT INTO recordings (id, title, artist, canonical_mbid) VALUES (?, ?, ?, ?)",
        (99, "Faixa pendente", "Artista", "recording-99"),
    )
    seeded_sqlite_conn.execute(
        """
        INSERT INTO instrument_credit_candidates
            (recording_id, source, instrument_name, performer, original_credit,
             scope, queue_priority, queue_reason)
        VALUES (99, 'musicbrainz', 'bass', 'Artista', 'bass', 'recording', 10,
                'unmapped_instrument_name')
        """
    )
    seeded_sqlite_conn.commit()

    queue = D1EditorialCandidateQueue(MockD1Database(seeded_sqlite_conn))
    candidates = await queue.pending()

    assert len(candidates) == 1
    assert candidates[0].instrument_name == "bass"
    assert candidates[0].queue_reason == "unmapped_instrument_name"
    assert candidates[0].title == "Faixa pendente"


@pytest.mark.anyio
async def test_instrument_endpoint_uses_d1_when_injected(
    seeded_sqlite_conn: sqlite3.Connection,
) -> None:
    db = MockD1Database(seeded_sqlite_conn)
    catalog = D1InstrumentCatalog(db)

    async def override_catalog() -> D1InstrumentCatalog:
        return catalog

    app.dependency_overrides[get_instrument_catalog] = override_catalog
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/instruments/drums")
            assert response.status_code == 200
            body = response.json()
            assert body["slug"] == "drums"
            assert body["data_source"] == "catalog"
            assert body["kind"] == "instrument"
            assert body["family_slug"] == "percussion"
    finally:
        app.dependency_overrides.clear()
