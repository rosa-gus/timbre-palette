import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from palette_api.album_catalog import D1AlbumCatalogRepository
from palette_api.domain import Track
from palette_api.enrichment import D1QueueEnrichmentScheduler
from palette_api.musicbrainz import (
    D1IdentityRepository,
    InstrumentCredit,
    JsonHttpResponse,
    MusicBrainzAlbumCollector,
    ResolvedRecording,
)


class Statement:
    def __init__(self, conn: sqlite3.Connection, query: str, params: tuple = ()) -> None:
        self.conn = conn
        self.query = query
        self.params = params

    def bind(self, *params: object) -> "Statement":
        return Statement(self.conn, self.query, params)

    async def first(self) -> dict | None:
        cursor = self.conn.execute(self.query, self.params)
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([column[0] for column in cursor.description], row))

    async def all(self) -> object:
        cursor = self.conn.execute(self.query, self.params)
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        return SimpleNamespace(results=[dict(zip(columns, row)) for row in rows])

    async def run(self) -> object:
        cursor = self.conn.execute(self.query, self.params)
        self.conn.commit()
        return SimpleNamespace(meta=SimpleNamespace(changes=max(cursor.rowcount, 0)))


class Database:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def prepare(self, query: str) -> Statement:
        return Statement(self.conn, query)


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    root = Path(__file__).resolve().parent.parent
    for migration in sorted((root / "migrations").glob("*.sql")):
        conn.executescript(migration.read_text(encoding="utf-8"))
    return conn


class Transport:
    async def get_json(self, url: str) -> JsonHttpResponse:
        assert "/release/release-mbid?inc=" in url
        return JsonHttpResponse(
            200,
            {
                "id": "release-mbid",
                "title": "Prepared Album",
                "date": "1970-01-01",
                "country": "US",
                "status": "Official",
                "artist-credit": [{"name": "Prepared Artist"}],
                "release-group": {"id": "group-mbid"},
                "media": [
                    {
                        "position": 1,
                        "tracks": [
                            {
                                "position": 1,
                                "title": "Track One",
                                "length": 120000,
                                "recording": {
                                    "id": "recording-mbid",
                                    "title": "Track One",
                                    "artist-credit": [{"name": "Prepared Artist"}],
                                    "relations": [
                                        {
                                            "type": "instrument",
                                            "artist": {"name": "Player"},
                                            "attributes": ["electric guitar"],
                                        },
                                        {
                                            "type": "programming",
                                            "artist": {"name": "Producer"},
                                        },
                                    ],
                                },
                            }
                        ],
                    }
                ],
            },
        )


@pytest.mark.anyio
async def test_prepared_album_persists_tracks_observations_and_claims() -> None:
    conn = database()
    album = await MusicBrainzAlbumCollector(Transport()).collect("release-mbid")
    assert album is not None
    assert len(album.tracks) == 1
    assert {observation.relation_type for observation in album.tracks[0].observations} == {
        "instrument",
        "programming",
    }

    release_id = await D1AlbumCatalogRepository(Database(conn)).save(album)

    assert conn.execute("SELECT COUNT(*) FROM album_releases").fetchone()[0] == 1
    assert conn.execute(
        "SELECT album_release_id FROM album_tracks"
    ).fetchone()[0] == release_id
    assert conn.execute(
        "SELECT relation_type FROM credit_observations ORDER BY id"
    ).fetchall() == [("instrument",), ("programming",)]
    assert conn.execute(
        "SELECT instrument_slug FROM instrument_claims"
    ).fetchone()[0] == "electric-guitar"
    assert await D1AlbumCatalogRepository(Database(conn)).has_cached_release(
        "release-mbid"
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM catalog_publications WHERE status = 'active'"
    ).fetchone()[0] == 1


@pytest.mark.anyio
async def test_release_job_uses_album_message_contract() -> None:
    conn = database()

    class Queue:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        async def send(self, body: dict, **kwargs: object) -> None:
            self.messages.append(body)

    queue = Queue()
    await D1QueueEnrichmentScheduler(Database(conn), queue).schedule_release(
        "release-mbid", artist="Prepared Artist", title="Prepared Album"
    )

    assert len(queue.messages) == 1
    assert queue.messages[0]["schema_version"] == 3
    assert queue.messages[0]["generation"] == 1
    assert len(queue.messages[0]["work_unit_key"]) == 64
    assert conn.execute(
        "SELECT job_type, target_mbid, stage FROM enrichment_jobs"
    ).fetchone() == ("release", "release-mbid", "source")
    queue.messages.clear()
    # A successfully published unit is not republished by a timer.
    assert await D1QueueEnrichmentScheduler(Database(conn), queue).recover_pending() == 0
    assert queue.messages == []


@pytest.mark.anyio
async def test_visits_aggregate_demand_without_profile_data() -> None:
    conn = database()

    class Queue:
        async def send(self, body: dict, **kwargs: object) -> None:
            return None

    scheduler = D1QueueEnrichmentScheduler(Database(conn), Queue())
    track = Track("Demanded", "Artist", 7, mbid="recording-mbid")
    await scheduler.schedule((track,))
    await scheduler.schedule((track,))

    assert conn.execute(
        "SELECT artist, title, play_weight, sightings FROM catalog_demand"
    ).fetchone() == ("Artist", "Demanded", 14, 2)


@pytest.mark.anyio
async def test_catalog_aliases_promote_instrument_and_family_slugs() -> None:
    conn = database()
    repository = D1IdentityRepository(Database(conn))
    recording_id = await repository.save_enrichment(
        Track("Mapped", "Artist", 1, mbid="recording-mbid"),
        ResolvedRecording(
            mbid="recording-mbid",
            title="Mapped",
            artist="Artist",
            method="mbid_recording",
            confidence=1.0,
            source_mbid="recording-mbid",
            source_entity_type="recording",
            instrument_credits=(
                InstrumentCredit(None, "drums (drum set)", "Player"),
                InstrumentCredit(None, "electric bass guitar", "Player"),
                InstrumentCredit(None, "acoustic guitar", "Player"),
                InstrumentCredit(None, "vocals", "Singer"),
            ),
        ),
    )

    assert conn.execute(
        """
        SELECT instrument_slug, family_slug, resolution_method
        FROM instrument_credit_candidates
        ORDER BY id
        """
    ).fetchall() == [
        ("drums", None, "alias"),
        ("electric-bass", None, "alias"),
        ("acoustic-guitar", None, "alias"),
        (None, "voice", "family_alias"),
    ]
    assert conn.execute(
        "SELECT COUNT(*) FROM instrument_claims WHERE recording_id = ?",
        (recording_id,),
    ).fetchone()[0] == 4
    assert await repository.accepted_claim_count(recording_id) == 4


@pytest.mark.anyio
async def test_catalog_mapping_sources_and_seed() -> None:
    import json
    from palette_api.catalog import D1InstrumentCatalog
    from palette_api.mocks import MockInstrumentCatalog
    from palette_api.musicbrainz import D1InstrumentMapper
    from palette_api.tools.publish_editorial import emit_sql, load_manifest

    conn = database()
    root = Path(__file__).resolve().parents[1]
    resources = load_manifest(root / 'editorial/src/instruments.json')
    conn.executescript(
        emit_sql(
            resources,
            revision='catalog-test',
            commit_sha='pytest',
            published_by='pytest',
        )
    )
    db = Database(conn)
    mapper = D1InstrumentMapper(db)
    catalog = D1InstrumentCatalog(db)
    mock = MockInstrumentCatalog()
    manifest = json.loads((root / 'editorial/src/instruments.json').read_text())
    records = manifest['instruments'] if isinstance(manifest, dict) else manifest
    sheets = {sheet['resource']['slug']: sheet['resource'] for sheet in records}
    cases = [('acoustic guitar', 'acoustic-guitar'), ('classical guitar', 'acoustic-guitar'),
             ('cavaquinho', 'cavaquinho'), ('pandeiro', 'pandeiro'), ('surdo', 'surdo'),
             ('tamborim', 'tamborim'), ('cuíca', 'cuica')]
    for name, slug in cases:
        mapped = await mapper.resolve(InstrumentCredit(None, name, 'Player'))
        assert mapped and (mapped.target_kind, mapped.target_slug) == ('instrument', slug)
        conn.execute(
            "UPDATE editorial_content_blocks SET claim_support_verified = 1 "
            "WHERE id = ?",
            (f"instrument-{slug}-curiosity",),
        )
        conn.commit()
        resource = await catalog.get(slug)
        assert resource and resource.catalog_version == '0.1.6'
        section = resource.sections[0]
        source = resource.sources[0]
        expected_source = sheets[slug]['sources'][0]
        assert source.source_type == expected_source['source_type']
        assert source.url == expected_source['url']
        assert source.metadata_verified
        assert source.accessed_at == expected_source['accessed_at']
        assert section.citations[0].source_id == source.id
        expected_citation = sheets[slug]['sections'][0]['citations'][0]
        assert section.citations[0].locator == expected_citation.get('locator', '')
        assert section.status == 'sourced' and section.review.claim_support_verified
        mock_resource = await mock.get(slug)
        assert mock_resource
        assert mock_resource.sections[0].id == section.id
        assert sheets[slug]['sections'][0]['id'] == section.id
        assert sheets[slug]['sources'] == resource.model_dump(mode='json')['sources']
        expected_resolution = 'exact' if slug in {'acoustic-guitar', 'pandeiro'} else 'family'
        assert sheets[slug]['image']['resolution'] == expected_resolution
        family = await catalog.get(resource.family_slug)
        assert family and slug in family.related_slugs
    for name, family in [('vibraphone', 'percussion'), ('guitar', 'plucked-strings')]:
        mapped = await mapper.resolve(InstrumentCredit(None, name, 'Player'))
        assert mapped and (mapped.target_kind, mapped.target_slug) == ('family', family)
    assert await mapper.resolve(InstrumentCredit(None, 'unknown guitar', 'Player')) is None
    assert await catalog.get('vibraphone') is None
    assert await catalog.get('vibrafone') is None
    assert await mock.get('vibraphone') is None
    assert 'vibraphone' not in sheets
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []

    repository = D1IdentityRepository(db)
    recording_id = await repository.save_enrichment(
        Track('Samba', 'Artist', 1, mbid='samba-recording'),
        ResolvedRecording(
            mbid='samba-recording', title='Samba', artist='Artist', method='mbid_recording',
            confidence=1.0, source_mbid='samba-recording', source_entity_type='recording',
            instrument_credits=tuple(InstrumentCredit(None, name, 'Player') for name in
                                     ['acoustic guitar', 'cavaquinho', 'pandeiro', 'surdo',
                                      'tamborim', 'cuíca', 'vibraphone']),
        ),
    )
    claims = conn.execute(
        'SELECT instrument_slug, family_slug FROM instrument_claims WHERE recording_id = ?',
        (recording_id,),
    ).fetchall()
    assert set(claims) == {(slug, None) for slug in
                          ['acoustic-guitar', 'cavaquinho', 'pandeiro', 'surdo', 'tamborim', 'cuica']} | {(None, 'percussion')}
    assert await repository.accepted_claim_count(recording_id) == 7
