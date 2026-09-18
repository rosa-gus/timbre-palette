import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from palette_api.musicbrainz import D1IdentityRepository, MusicBrainzEnricher
from palette_api.musicbrainz_index import (
    CreditIndexBudgetExceeded,
    CreditIndexEntry,
    CompositeCreditIndex,
    D1RecentCreditIndex,
    R2ReadBudget,
    R2CreditIndex,
)
from palette_api.domain import Track


RECORDING_MBID = "11111111-1111-4111-8111-111111111111"
ARTIST_MBID = "22222222-2222-4222-8222-222222222222"
INSTRUMENT_MBID = "33333333-3333-4333-8333-333333333333"
TRACK_MBID = "55555555-5555-4555-8555-555555555555"
@pytest.mark.anyio
async def test_r2_index_resolves_track_alias_to_recording() -> None:
    recording_payload = {
        "recording_mbid": RECORDING_MBID,
        "snapshot_version": "schema-30",
        "source_url": f"https://musicbrainz.org/recording/{RECORDING_MBID}",
        "credits": [],
    }
    alias_payload = {
        "track_mbid": TRACK_MBID,
        "recording_mbid": RECORDING_MBID,
        "snapshot_version": "schema-30",
        "source_url": f"https://musicbrainz.org/track/{TRACK_MBID}",
    }

    class Object:
        def __init__(self, payload: object) -> None:
            self.payload = payload

        async def json(self) -> object:
            return self.payload

    class Bucket:
        async def get(self, key: str) -> Object | None:
            if key.endswith(f"/tracks/{TRACK_MBID}.json"):
                return Object(alias_payload)
            if key.endswith(f"/recordings/{RECORDING_MBID}.json"):
                return Object(recording_payload)
            return None

    entry = await R2CreditIndex(Bucket()).lookup(TRACK_MBID)
    assert entry is not None
    assert entry.recording_mbid == RECORDING_MBID


@pytest.mark.anyio
async def test_r2_index_reads_one_recording_object() -> None:
    payload = {
        "recording_mbid": RECORDING_MBID,
        "snapshot_version": "schema-30",
        "source_url": f"https://musicbrainz.org/recording/{RECORDING_MBID}",
        "credits": [
            {
                "artist_mbid": ARTIST_MBID,
                "instrument_mbid": INSTRUMENT_MBID,
                "instrument_name": "Electric guitar",
                "attributes": ["Electric guitar"],
                "original_credit": "guitar",
                "scope": "recording",
                "source_url": "https://musicbrainz.org/recording/example",
            }
        ],
    }

    class Object:
        async def json(self) -> object:
            return payload

    class Bucket:
        async def get(self, key: str) -> Object:
            assert key.endswith(f"/{RECORDING_MBID}.json")
            return Object()

    entry = await R2CreditIndex(Bucket()).lookup(RECORDING_MBID)
    assert entry is not None
    assert entry.credits[0].artist_mbid == ARTIST_MBID
    assert entry.credits[0].scope == "recording"


@pytest.mark.anyio
async def test_r2_read_budget_blocks_before_the_next_bucket_get() -> None:
    payload = {
        "recording_mbid": RECORDING_MBID,
        "snapshot_version": "schema-30",
        "source_url": f"https://musicbrainz.org/recording/{RECORDING_MBID}",
        "credits": [],
    }

    class Object:
        async def json(self) -> object:
            return payload

    class Bucket:
        def __init__(self) -> None:
            self.gets = 0

        async def get(self, key: str) -> Object:
            self.gets += 1
            return Object()

    connection = _seed_db()
    bucket = Bucket()
    index = R2CreditIndex(
        bucket,
        read_budget=R2ReadBudget(
            Database(connection), period_key="test-period", max_reads=1
        ),
    )

    assert await index.lookup(RECORDING_MBID) is not None
    with pytest.raises(CreditIndexBudgetExceeded):
        await index.lookup(RECORDING_MBID)

    assert bucket.gets == 1
    assert connection.execute(
        "SELECT reads_reserved FROM musicbrainz_credit_index_usage "
        "WHERE period_key = 'test-period'"
    ).fetchone() == (1,)


@pytest.mark.anyio
async def test_budget_block_does_not_fall_through_to_musicbrainz_api() -> None:
    class Index:
        async def lookup(self, recording_mbid: str) -> CreditIndexEntry:
            raise CreditIndexBudgetExceeded("budget exhausted")

    class Resolver:
        async def resolve(self, track: Track) -> object:
            raise AssertionError("the API resolver must not run after a budget block")

    enricher = MusicBrainzEnricher(
        Resolver(),
        object(),
        credit_index=CompositeCreditIndex(Index()),
    )
    with pytest.raises(CreditIndexBudgetExceeded):
        await enricher.enrich_track(Track("Song", "Artist", 1, mbid=RECORDING_MBID))


@pytest.mark.anyio
async def test_offline_only_index_miss_does_not_call_musicbrainz_api() -> None:
    class Resolver:
        async def resolve(self, track: Track) -> object:
            raise AssertionError("offline-only mode must not call MusicBrainz")

    enricher = MusicBrainzEnricher(
        Resolver(),
        object(),
        credit_index=CompositeCreditIndex(),
        allow_upstream_api=False,
    )
    assert (
        await enricher.enrich_track(
            Track("Song", "Artist", 1, mbid=RECORDING_MBID)
        )
        is None
    )


class Statement:
    def __init__(self, connection: sqlite3.Connection, query: str, params: tuple = ()) -> None:
        self.connection = connection
        self.query = query
        self.params = params

    def bind(self, *params: object) -> "Statement":
        return Statement(self.connection, self.query, params)

    async def first(self) -> dict | None:
        cursor = self.connection.execute(self.query, self.params)
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([column[0] for column in cursor.description], row))

    async def all(self) -> SimpleNamespace:
        cursor = self.connection.execute(self.query, self.params)
        columns = [column[0] for column in cursor.description]
        return SimpleNamespace(
            results=[dict(zip(columns, row)) for row in cursor.fetchall()]
        )

    async def run(self) -> SimpleNamespace:
        cursor = self.connection.execute(self.query, self.params)
        self.connection.commit()
        return SimpleNamespace(meta=SimpleNamespace(changes=max(cursor.rowcount, 0)))


class Database:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def prepare(self, query: str) -> Statement:
        return Statement(self.connection, query)


def _seed_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    root = Path(__file__).resolve().parents[1]
    for migration in sorted((root / "migrations").glob("*.sql")):
        connection.executescript(migration.read_text(encoding="utf-8"))
    return connection


@pytest.mark.anyio
async def test_index_hit_is_persisted_without_resolver_request() -> None:
    connection = _seed_db()
    entry = CreditIndexEntry.from_payload(
        {
            "recording_mbid": RECORDING_MBID,
            "snapshot_version": "schema-30",
            "source_url": f"https://musicbrainz.org/recording/{RECORDING_MBID}",
            "credits": [
                {
                    "artist_mbid": ARTIST_MBID,
                    "instrument_mbid": None,
                    "instrument_name": "acoustic guitar",
                    "scope": "recording",
                    "original_credit": "acoustic guitar",
                }
            ],
        },
        requested_mbid=RECORDING_MBID,
    )

    class Resolver:
        async def resolve(self, track: Track) -> object:
            raise AssertionError("the API resolver must not run for an index hit")

    class Index:
        async def lookup(self, recording_mbid: str) -> CreditIndexEntry:
            assert recording_mbid == RECORDING_MBID
            return entry

    enricher = MusicBrainzEnricher(
        Resolver(), D1IdentityRepository(Database(connection)), credit_index=Index()
    )
    recording_id = await enricher.enrich_track(
        Track("Song", "Artist", 1, mbid=RECORDING_MBID)
    )

    assert recording_id is not None
    assert connection.execute(
        "SELECT snapshot_version, performer_mbid FROM instrument_credit_candidates"
    ).fetchone() == ("schema-30", ARTIST_MBID)
    assert connection.execute(
        "SELECT source_quality, snapshot_version FROM evidence_items"
    ).fetchone() == ("offline_snapshot", "schema-30")


@pytest.mark.anyio
async def test_recent_d1_index_returns_normalized_credit_without_r2() -> None:
    connection = _seed_db()
    connection.execute(
        "INSERT INTO recordings (id, title, artist, canonical_mbid) VALUES (1, 'Song', 'Artist', ?)",
        (RECORDING_MBID,),
    )
    connection.execute(
        "INSERT INTO enrichment_state (recording_id, status, completed_at, updated_at) "
        "VALUES (1, 'completed', datetime('now'), datetime('now'))"
    )
    connection.execute(
        """
        INSERT INTO instrument_credit_candidates
            (recording_id, source, instrument_mbid, instrument_name, performer,
             performer_mbid, original_credit, scope, source_url, snapshot_version,
             attributes_json, status)
        VALUES (1, 'musicbrainz', '', 'acoustic guitar', '', ?, 'guitar',
                'recording', 'https://example.test/recording', 'schema-30',
                '["guitar"]', 'promoted')
        """,
        (ARTIST_MBID,),
    )
    connection.commit()

    entry = await D1RecentCreditIndex(Database(connection)).lookup(RECORDING_MBID)

    assert entry is not None
    assert entry.snapshot_version == "schema-30"
    assert entry.credits[0].attributes == ("guitar",)
