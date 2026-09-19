import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from palette_api.api import app, get_instrument_catalog, get_catalog_stats
from palette_api.catalog import D1InstrumentCatalog


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
    conn.execute(
        """
        INSERT INTO musicbrainz_credit_index_snapshots
            (snapshot_version, index_schema_version, source_url, license,
             attribution, manifest_hash, status, published_at)
        VALUES ('snapshot-v2', 'musicbrainz-instrument-credits-serving-v1',
                'https://example.test/musicbrainz', 'CC0', 'MusicBrainz',
                'manifest', 'active', datetime('now'))
        """
    )
    conn.execute(
        """
        INSERT INTO snapshot_recordings
            (snapshot_version, recording_mbid, status, mapped_credit_count)
        VALUES ('snapshot-v2', 'recording-accepted', 'complete', 1)
        """
    )
    conn.commit()
    baseline = json.loads((await get_catalog_stats(Request({
        "type": "http", "env": {"DB": MockD1Database(conn)},
    }))).body)["recordings_with_evidence"]
    conn.execute(
        """
        INSERT INTO snapshot_recordings
            (snapshot_version, recording_mbid, status, mapped_credit_count)
        VALUES ('snapshot-v2', 'recording-second', 'complete', 2)
        """
    )
    conn.execute(
        """
        INSERT INTO snapshot_recordings
            (snapshot_version, recording_mbid, status, mapped_credit_count)
        VALUES ('snapshot-v2', 'recording-empty', 'complete_empty', 0)
        """
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
    migration_5 = project_root / "migrations" / "0005_enrichment_outbox.sql"
    migration_6 = project_root / "migrations" / "0006_family_claims_and_conservative_mapping.sql"
    migration_8 = project_root / "migrations" / "0008_instrument_editorial_scope.sql"
    migration_14 = project_root / "migrations" / "0014_musicbrainz_credit_index.sql"
    migration_15 = project_root / "migrations" / "0015_musicbrainz_credit_index_usage.sql"
    migration_16 = project_root / "migrations" / "0016_api_v2_snapshot_projections.sql"

    for migration in (
        migration_1,
        migration_2,
        migration_3,
        migration_4,
        migration_5,
        migration_6,
        migration_8,
        migration_14,
        migration_15,
        migration_16,
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
    assert resource.catalog_version == "0.1.3"
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
            response = await client.get("/v2/instruments/drums")
            assert response.status_code == 200
            body = response.json()
            assert body["slug"] == "drums"
            assert body["data_source"] == "catalog"
            assert body["kind"] == "instrument"
            assert body["family_slug"] == "percussion"
    finally:
        app.dependency_overrides.clear()
