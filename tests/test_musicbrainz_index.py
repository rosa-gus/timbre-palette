import json
import sqlite3
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from palette_api.musicbrainz import D1IdentityRepository, MusicBrainzEnricher
from palette_api.musicbrainz_index import (
    CreditIndexEntry,
    D1RecentCreditIndex,
    R2CreditIndex,
)
from palette_api.domain import Track
from palette_api.tools.build_musicbrainz_index import build_index
from palette_api.tools.publish_musicbrainz_index import emit_sql, load_manifest


RECORDING_MBID = "11111111-1111-4111-8111-111111111111"
ARTIST_MBID = "22222222-2222-4222-8222-222222222222"
INSTRUMENT_MBID = "33333333-3333-4333-8333-333333333333"
RELEASE_MBID = "44444444-4444-4444-8444-444444444444"


def _write_dump(directory: Path) -> None:
    rows = {
        "artist": [f"1\t{ARTIST_MBID}\tArtist"],
        "recording": [f"1\t{RECORDING_MBID}\tSong"],
        "instrument": [f"1\t{INSTRUMENT_MBID}\tElectric guitar"],
        "link_type": ["1\t\\N\t0\tlink-type\tartist\trecording\tinstrument"],
        "link": ["1\t1", "2\t1"],
        "link_attribute_type": [
            f"1\t\\N\t14\t0\t{INSTRUMENT_MBID}\tElectric guitar"
        ],
        "link_attribute": ["1\t1", "2\t1"],
        "link_attribute_credit": ["1\t1\tguitar", "2\t1\tlead guitar"],
        "l_artist_recording": ["1\t1\t1\t1"],
        "release": [f"1\t{RELEASE_MBID}\tAlbum"],
        "medium": ["1\tmedium-mbid\t1\t1"],
        "track": ["1\ttrack-mbid\t1\t1\t1\t1\tSong"],
        "l_artist_release": ["2\t1\t1\t1"],
    }
    for name, lines in rows.items():
        (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_build_index_keeps_recording_and_release_scope(tmp_path: Path) -> None:
    dump = tmp_path / "dump"
    dump.mkdir()
    _write_dump(dump)
    archive = tmp_path / "mbdump.tar.bz2"
    with tarfile.open(archive, mode="w:bz2") as tar:
        for table in dump.iterdir():
            tar.add(table, arcname=f"mbdump/{table.name}")
    output = tmp_path / "index"

    manifest = build_index(
        archive,
        output,
        snapshot_version="schema-30-2026-09-12",
        source_url="https://example.test/musicbrainz-dump",
    )

    assert manifest["record_count"] == 1
    assert manifest["credit_count"] == 2
    payload = json.loads(
        (output / "musicbrainz/instrument-credits/v1/recordings" / f"{RECORDING_MBID}.json")
        .read_text(encoding="utf-8")
    )
    assert {credit["scope"] for credit in payload["credits"]} == {
        "recording",
        "release",
    }
    assert all(credit["artist_mbid"] == ARTIST_MBID for credit in payload["credits"])
    assert (output / "LICENSE-MUSICBRAINZ.txt").exists()


def test_index_manifest_emits_d1_publication_sql(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "index_schema_version": "musicbrainz-instrument-credits-v1",
                "snapshot_version": "schema-30",
                "source_url": "https://example.test/dump",
                "license": "CC BY-NC-SA-3.0",
                "attribution": "MusicBrainz",
                "manifest_hash": "abc123",
                "record_count": 1,
                "credit_count": 2,
                "generated_at": "2026-09-12T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    sql = emit_sql(load_manifest(manifest_path))
    assert "musicbrainz_credit_index_snapshots" in sql
    assert "CC BY-NC-SA-3.0" in sql
    assert "status = 'superseded'" in sql


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
