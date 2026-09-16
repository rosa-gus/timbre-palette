"""Build a compact MusicBrainz instrumental-credit index from a dump.

The input is the extracted ``mbdump`` directory or the original
``mbdump.tar.bz2`` archive.  Only the tables needed for artist-to-recording
instrument relationships are staged in a local SQLite file; the full dump is
never copied to R2.  The output is an R2-compatible directory containing one
small JSON object per recording plus a license/provenance manifest.

The dump tables are PostgreSQL COPY exports.  Their first columns are stable
for the current MusicBrainz schema; the relevant positions are kept here so
the ETL does not require a local MusicBrainz/PostgreSQL installation.
"""

from __future__ import annotations

import argparse
import bz2
import hashlib
import io
import json
import sqlite3
import sys
import tarfile
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from palette_api.musicbrainz_index import (
    INDEX_OBJECT_PREFIX,
    INDEX_SCHEMA_VERSION,
    object_key,
)


DEFAULT_SOURCE_URL = "https://musicbrainz.org/doc/MusicBrainz_Database/Download"
DEFAULT_ATTRIBUTION = "MusicBrainz; derived instrumental-credit index."
DEFAULT_LICENSE = "CC BY-NC-SA-3.0"
RELATION_TYPES = ("vocal", "vocals", "programming", "samples", "sampled")


class TableNotFound(FileNotFoundError):
    pass


class DumpSource:
    """Open named tables from an extracted dump or a tar/bz2 archive."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._directory_files: dict[str, Path] | None = None
        self._archive_members: tuple[str, ...] | None = None
        if path.is_dir():
            files: dict[str, Path] = {}
            for candidate in path.rglob("*"):
                if candidate.is_file():
                    files.setdefault(_normalized_table_name(candidate.name), candidate)
            self._directory_files = files
        elif path.is_file() and _is_archive(path):
            with tarfile.open(path, mode="r:*") as archive:
                self._archive_members = tuple(
                    member.name
                    for member in archive.getmembers()
                    if member.isfile()
                )

    def has_table(self, table_name: str) -> bool:
        try:
            self._find_table(table_name)
        except TableNotFound:
            return False
        return True

    @contextmanager
    def table(self, table_name: str) -> Iterator[TextIO]:
        location = self._find_table(table_name)
        if isinstance(location, Path):
            if location.suffix == ".bz2":
                with bz2.open(location, mode="rt", encoding="utf-8", newline="") as stream:
                    yield stream
            else:
                with location.open("r", encoding="utf-8", newline="") as stream:
                    yield stream
            return

        with tarfile.open(self.path, mode="r:*") as archive:
            extracted = archive.extractfile(location)
            if extracted is None:
                raise TableNotFound(table_name)
            with io.TextIOWrapper(extracted, encoding="utf-8", newline="") as stream:
                yield stream

    def _find_table(self, table_name: str) -> Path | str:
        normalized = _normalized_table_name(table_name)
        if self._directory_files is not None:
            path = self._directory_files.get(normalized)
            if path is None:
                raise TableNotFound(table_name)
            return path
        if self._archive_members is not None:
            for member in self._archive_members:
                if _normalized_table_name(Path(member).name) == normalized:
                    return member
            raise TableNotFound(table_name)
        if self.path.is_file() and _normalized_table_name(self.path.name) == normalized:
            return self.path
        raise TableNotFound(table_name)


def build_index(
    dump_path: Path,
    output_dir: Path,
    *,
    snapshot_version: str,
    source_url: str = DEFAULT_SOURCE_URL,
    license_name: str = DEFAULT_LICENSE,
    attribution: str = DEFAULT_ATTRIBUTION,
    include_release_relations: bool = True,
    staging_path: Path | None = None,
) -> dict[str, object]:
    """Build the index and return the generated manifest."""

    if not snapshot_version.strip():
        raise ValueError("snapshot_version is required.")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {output_dir}. Choose a new directory."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    source = DumpSource(dump_path)

    temporary_staging: tempfile.TemporaryDirectory[str] | None = None
    if staging_path is None:
        temporary_staging = tempfile.TemporaryDirectory(prefix="musicbrainz-index-")
        staging_path = Path(temporary_staging.name) / "staging.sqlite3"
    else:
        staging_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        connection = sqlite3.connect(staging_path)
        try:
            _create_staging_schema(connection)
            _load_required_tables(source, connection)
            has_release_tables = include_release_relations and _load_release_tables(
                source, connection
            )
            manifest = _write_index(
                connection,
                output_dir,
                snapshot_version=snapshot_version.strip(),
                source_url=source_url.strip(),
                license_name=license_name.strip(),
                attribution=attribution.strip(),
                include_release_relations=has_release_tables,
            )
        finally:
            connection.close()
    finally:
        if temporary_staging is not None:
            temporary_staging.cleanup()
    return manifest


def _create_staging_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = MEMORY;
        PRAGMA synchronous = OFF;
        CREATE TABLE artists (id INTEGER PRIMARY KEY, mbid TEXT NOT NULL);
        CREATE TABLE recordings (id INTEGER PRIMARY KEY, mbid TEXT NOT NULL);
        CREATE TABLE instruments (gid TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE link_types (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE links (id INTEGER PRIMARY KEY, link_type INTEGER NOT NULL);
        CREATE TABLE link_attributes (
            link INTEGER NOT NULL,
            attribute_type INTEGER NOT NULL,
            PRIMARY KEY (link, attribute_type)
        );
        CREATE TABLE attribute_types (
            id INTEGER PRIMARY KEY,
            gid TEXT,
            name TEXT NOT NULL
        );
        CREATE TABLE attribute_credits (
            link INTEGER NOT NULL,
            attribute_type INTEGER NOT NULL,
            credited_as TEXT,
            PRIMARY KEY (link, attribute_type)
        );
        CREATE TABLE releases (id INTEGER PRIMARY KEY, mbid TEXT NOT NULL);
        CREATE TABLE media (id INTEGER PRIMARY KEY, release_id INTEGER NOT NULL);
        CREATE TABLE tracks (recording_id INTEGER NOT NULL, medium_id INTEGER NOT NULL);
        CREATE TABLE artist_recording (
            link INTEGER NOT NULL,
            artist_id INTEGER NOT NULL,
            recording_id INTEGER NOT NULL
        );
        CREATE TABLE artist_release (
            link INTEGER NOT NULL,
            artist_id INTEGER NOT NULL,
            release_id INTEGER NOT NULL
        );
        CREATE INDEX idx_artist_recording_recording
            ON artist_recording(recording_id);
        CREATE INDEX idx_artist_release_release
            ON artist_release(release_id);
        CREATE INDEX idx_link_attributes_link
            ON link_attributes(link);
        CREATE INDEX idx_tracks_medium
            ON tracks(medium_id);
        """
    )


def _load_required_tables(source: DumpSource, connection: sqlite3.Connection) -> None:
    _load_table(
        source,
        "artist",
        connection,
        "INSERT OR IGNORE INTO artists(id, mbid) VALUES (?, ?)",
        lambda row: _first_values(row, 2),
    )
    _load_table(
        source,
        "recording",
        connection,
        "INSERT OR IGNORE INTO recordings(id, mbid) VALUES (?, ?)",
        lambda row: _first_values(row, 2),
    )
    _load_table(
        source,
        "instrument",
        connection,
        "INSERT OR IGNORE INTO instruments(gid, name) VALUES (?, ?)",
        lambda row: _values(row, (1, 2), integer_indexes=set()),
    )
    _load_table(
        source,
        "link_type",
        connection,
        "INSERT OR IGNORE INTO link_types(id, name) VALUES (?, ?)",
        lambda row: _values(row, (0, 6), integer_indexes={0}),
    )
    _load_table(
        source,
        "link",
        connection,
        "INSERT OR IGNORE INTO links(id, link_type) VALUES (?, ?)",
        lambda row: _values(row, (0, 1), integer_indexes={0, 1}),
    )
    _load_table(
        source,
        "link_attribute_type",
        connection,
        "INSERT OR IGNORE INTO attribute_types(id, gid, name) VALUES (?, ?, ?)",
        lambda row: _values(row, (0, 4, 5), integer_indexes={0}),
    )
    _load_table(
        source,
        "link_attribute",
        connection,
        "INSERT OR IGNORE INTO link_attributes(link, attribute_type) VALUES (?, ?)",
        lambda row: _values(row, (0, 1), integer_indexes={0, 1}),
    )
    _load_table(
        source,
        "l_artist_recording",
        connection,
        "INSERT INTO artist_recording(link, artist_id, recording_id) VALUES (?, ?, ?)",
        lambda row: _values(row, (1, 2, 3), integer_indexes={1, 2, 3}),
    )
    if source.has_table("link_attribute_credit"):
        _load_table(
            source,
            "link_attribute_credit",
            connection,
            "INSERT OR IGNORE INTO attribute_credits(link, attribute_type, credited_as) VALUES (?, ?, ?)",
            lambda row: _values(row, (0, 1, 2), integer_indexes={0, 1}),
        )


def _load_release_tables(source: DumpSource, connection: sqlite3.Connection) -> bool:
    required = ("release", "medium", "track", "l_artist_release")
    if not all(source.has_table(table) for table in required):
        print(
            "MusicBrainz release relation tables are incomplete; "
            "building recording-scoped credits only.",
            file=sys.stderr,
        )
        return False
    _load_table(
        source,
        "release",
        connection,
        "INSERT OR IGNORE INTO releases(id, mbid) VALUES (?, ?)",
        lambda row: _first_values(row, 2),
    )
    _load_table(
        source,
        "medium",
        connection,
        "INSERT OR IGNORE INTO media(id, release_id) VALUES (?, ?)",
        lambda row: _values(row, (0, 2), integer_indexes={0, 2}),
    )
    _load_table(
        source,
        "track",
        connection,
        "INSERT INTO tracks(recording_id, medium_id) VALUES (?, ?)",
        lambda row: _values(row, (2, 3), integer_indexes={2, 3}),
    )
    _load_table(
        source,
        "l_artist_release",
        connection,
        "INSERT INTO artist_release(link, artist_id, release_id) VALUES (?, ?, ?)",
        lambda row: _values(row, (1, 2, 3), integer_indexes={1, 2, 3}),
    )
    return True


def _load_table(
    source: DumpSource,
    table_name: str,
    connection: sqlite3.Connection,
    statement: str,
    transform,
) -> None:
    batch: list[tuple[object, ...]] = []
    try:
        with source.table(table_name) as stream:
            for row in _copy_rows(stream):
                values = transform(row)
                if values is None:
                    continue
                batch.append(values)
                if len(batch) >= 10_000:
                    connection.executemany(statement, batch)
                    batch.clear()
    except TableNotFound as error:
        raise RuntimeError(f"Required MusicBrainz dump table is missing: {table_name}") from error
    if batch:
        connection.executemany(statement, batch)
    connection.commit()


def _write_index(
    connection: sqlite3.Connection,
    output_dir: Path,
    *,
    snapshot_version: str,
    source_url: str,
    license_name: str,
    attribution: str,
    include_release_relations: bool,
) -> dict[str, object]:
    records_dir = output_dir / INDEX_OBJECT_PREFIX
    records_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    record_count = 0
    credit_count = 0

    relation_streams = [
        _relation_rows(
            connection,
            relation_table="artist_recording",
            scope="recording",
        )
    ]
    if include_release_relations:
        relation_streams.append(
            _relation_rows(
                connection,
                relation_table="artist_release",
                scope="release",
            )
        )

    merged_rows = _merge_sorted_rows(relation_streams)
    current_mbid: str | None = None
    current_credits: dict[tuple[object, ...], dict[str, object]] = {}

    def flush() -> None:
        nonlocal record_count, credit_count, current_mbid, current_credits
        if current_mbid is None or not current_credits:
            return
        credits = sorted(
            current_credits.values(),
            key=lambda credit: (
                str(credit.get("scope", "")),
                str(credit.get("artist_mbid", "")),
                str(credit.get("instrument_mbid", "")),
                str(credit.get("instrument_name", "")),
                str(credit.get("source_url", "")),
            ),
        )
        payload = {
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "recording_mbid": current_mbid,
            "snapshot_version": snapshot_version,
            "source_url": f"https://musicbrainz.org/recording/{current_mbid}",
            "credits": credits,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        target = output_dir / object_key(current_mbid)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        digest.update(current_mbid.encode("ascii"))
        digest.update(encoded)
        record_count += 1
        credit_count += len(credits)
        current_mbid = None
        current_credits = {}

    for row in merged_rows:
        recording_mbid = str(row[0])
        if current_mbid != recording_mbid:
            flush()
            current_mbid = recording_mbid
        credit = _row_to_credit(row, snapshot_version=snapshot_version)
        if credit is None:
            continue
        identity = (
            credit["artist_mbid"],
            credit["instrument_mbid"],
            credit["instrument_name"],
            credit["scope"],
            credit["original_credit"],
            credit["source_url"],
        )
        current_credits[identity] = credit
    flush()

    manifest = {
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "snapshot_version": snapshot_version,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "MusicBrainz",
        "source_url": source_url,
        "license": license_name,
        "attribution": attribution,
        "record_count": record_count,
        "credit_count": credit_count,
        "manifest_hash": digest.hexdigest(),
        "object_prefix": INDEX_OBJECT_PREFIX,
        "key_template": f"{INDEX_OBJECT_PREFIX}/{{recording_mbid}}.json",
        "includes_release_scoped_relations": include_release_relations,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "LICENSE-MUSICBRAINZ.txt").write_text(
        _license_notice(manifest), encoding="utf-8"
    )
    return manifest


def _relation_rows(
    connection: sqlite3.Connection,
    *,
    relation_table: str,
    scope: str,
) -> Iterator[tuple[object, ...]]:
    if relation_table == "artist_recording":
        relation_join = """
            JOIN artist_recording AS rel
              ON rel.link = l.id
            JOIN recordings AS recording
              ON recording.id = rel.recording_id
            JOIN artists AS artist
              ON artist.id = rel.artist_id
        """
        source_select = "'https://musicbrainz.org/recording/' || recording.mbid"
        source_group = "recording.mbid"
        order_by = "recording.mbid, artist.mbid, instrument.gid, rel.link"
    else:
        relation_join = """
            JOIN artist_release AS rel
              ON rel.link = l.id
            JOIN releases AS release
              ON release.id = rel.release_id
            JOIN media AS medium
              ON medium.release_id = release.id
            JOIN tracks AS track
              ON track.medium_id = medium.id
            JOIN recordings AS recording
              ON recording.id = track.recording_id
            JOIN artists AS artist
              ON artist.id = rel.artist_id
        """
        source_select = "'https://musicbrainz.org/release/' || release.mbid"
        source_group = "recording.mbid, release.mbid"
        order_by = "recording.mbid, artist.mbid, instrument.gid, release.mbid, rel.link"

    instrument_query = f"""
        SELECT recording.mbid, artist.mbid, instrument.gid, instrument.name,
               GROUP_CONCAT(DISTINCT all_attribute_type.name),
               MAX(credits.credited_as), 'instrument', ?,
               {source_select}, rel.link
        FROM links AS l
        JOIN link_types AS link_type ON link_type.id = l.link_type
        {relation_join}
        JOIN link_attributes AS instrument_attribute
          ON instrument_attribute.link = l.id
        JOIN attribute_types AS instrument_type
          ON instrument_type.id = instrument_attribute.attribute_type
        JOIN instruments AS instrument
          ON instrument.gid = instrument_type.gid
        JOIN link_attributes AS all_attribute
          ON all_attribute.link = l.id
        JOIN attribute_types AS all_attribute_type
          ON all_attribute_type.id = all_attribute.attribute_type
        LEFT JOIN attribute_credits AS credits
          ON credits.link = all_attribute.link
         AND credits.attribute_type = all_attribute.attribute_type
        WHERE lower(link_type.name) = 'instrument'
        GROUP BY recording.mbid, artist.mbid, instrument.gid,
                 instrument.name, {source_group}, rel.link
        ORDER BY {order_by}
    """
    yield from connection.execute(instrument_query, (scope,))

    other_query = f"""
        SELECT recording.mbid, artist.mbid, NULL, NULL,
               GROUP_CONCAT(DISTINCT all_attribute_type.name),
               MAX(credits.credited_as), lower(link_type.name), ?,
               {source_select}, rel.link
        FROM links AS l
        JOIN link_types AS link_type ON link_type.id = l.link_type
        {relation_join}
        LEFT JOIN link_attributes AS all_attribute
          ON all_attribute.link = l.id
        LEFT JOIN attribute_types AS all_attribute_type
          ON all_attribute_type.id = all_attribute.attribute_type
        LEFT JOIN attribute_credits AS credits
          ON credits.link = all_attribute.link
         AND credits.attribute_type = all_attribute.attribute_type
        WHERE lower(link_type.name) IN ({", ".join("?" for _ in RELATION_TYPES)})
          AND NOT EXISTS (
              SELECT 1
              FROM link_attributes AS instrument_attribute
              JOIN attribute_types AS instrument_type
                ON instrument_type.id = instrument_attribute.attribute_type
              JOIN instruments AS instrument
                ON instrument.gid = instrument_type.gid
              WHERE instrument_attribute.link = l.id
          )
        GROUP BY recording.mbid, artist.mbid, link_type.name,
                 {source_group}, rel.link
        ORDER BY recording.mbid, artist.mbid, lower(link_type.name), rel.link
    """
    yield from connection.execute(other_query, (scope, *RELATION_TYPES))


def _merge_sorted_rows(streams: Sequence[Iterator[tuple[object, ...]]]):
    import heapq

    return heapq.merge(*streams, key=lambda row: (str(row[0]), str(row[-1])))


def _row_to_credit(row: tuple[object, ...], *, snapshot_version: str) -> dict[str, object] | None:
    recording_mbid = str(row[0])
    artist_mbid = _optional_text(row[1])
    instrument_mbid = _optional_text(row[2])
    instrument_name = _optional_text(row[3])
    relation_type = _optional_text(row[6]) or "instrument"
    attributes = _split_attributes(row[4])
    if instrument_mbid and instrument_name:
        if instrument_name not in attributes:
            attributes = (*attributes, instrument_name)
    elif relation_type in {"vocal", "vocals"}:
        instrument_name = "voice"
        if "voice" not in attributes:
            attributes = (*attributes, "voice")
    elif relation_type in {"programming", "samples", "sampled"}:
        instrument_name = relation_type
    else:
        return None
    original_credit = _optional_text(row[5]) or instrument_name
    source_url = _optional_text(row[8])
    if not source_url:
        source_url = f"https://musicbrainz.org/recording/{recording_mbid}"
    return {
        "artist_mbid": artist_mbid,
        "instrument_mbid": instrument_mbid,
        "instrument_name": instrument_name,
        "attributes": list(dict.fromkeys(attributes)),
        "original_credit": original_credit,
        "scope": str(row[7]),
        "source_url": source_url,
        "snapshot_version": snapshot_version,
        "relation_type": relation_type,
        "production_method": (
            "programmed"
            if relation_type == "programming"
            else "sampled"
            if relation_type in {"samples", "sampled"}
            else "performed"
        ),
    }


def _copy_rows(stream: TextIO) -> Iterator[list[str | None]]:
    for line in stream:
        if not line.strip():
            continue
        fields = line.rstrip("\r\n").split("\t")
        yield [_decode_copy_field(field) for field in fields]


def _decode_copy_field(value: str) -> str | None:
    if value == r"\N":
        return None
    output: list[str] = []
    index = 0
    escapes = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            output.append(escapes.get(escaped, escaped))
            index += 2
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _first_values(row: list[str | None], count: int) -> tuple[object, ...] | None:
    if len(row) < count or any(row[index] in {None, ""} for index in range(count)):
        return None
    try:
        return int(str(row[0])), str(row[1])
    except (TypeError, ValueError):
        return None


def _values(
    row: list[str | None],
    indexes: tuple[int, ...],
    *,
    integer_indexes: set[int],
) -> tuple[object, ...] | None:
    if len(row) <= max(indexes) or any(row[index] in {None, ""} for index in indexes):
        return None
    values: list[object] = []
    for index in indexes:
        value = row[index]
        if index in integer_indexes:
            try:
                values.append(int(str(value)))
                continue
            except (TypeError, ValueError):
                return None
        values.append(str(value))
    return tuple(values)


def _split_attributes(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalized_table_name(name: str) -> str:
    normalized = name.rsplit("/", 1)[-1]
    for suffix in (".bz2", ".gz", ".tsv", ".txt"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def _is_archive(path: Path) -> bool:
    try:
        return tarfile.is_tarfile(path)
    except OSError:
        return False


def _license_notice(manifest: dict[str, object]) -> str:
    return (
        "This object set is derived from MusicBrainz data.\n"
        f"Attribution: {manifest['attribution']}\n"
        f"Source: {manifest['source_url']}\n"
        f"License: {manifest['license']}\n"
        f"Snapshot: {manifest['snapshot_version']}\n"
        "The corresponding derivative index must preserve this notice and the "
        "applicable share-alike/non-commercial conditions.\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="mbdump directory or mbdump.tar.bz2")
    parser.add_argument("output", type=Path, help="empty directory for the R2 index")
    parser.add_argument("--snapshot-version", required=True)
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--license", dest="license_name", default=DEFAULT_LICENSE)
    parser.add_argument("--attribution", default=DEFAULT_ATTRIBUTION)
    parser.add_argument(
        "--no-release-relations",
        action="store_true",
        help="exclude release-scoped credits and emit recording-scoped rows only",
    )
    parser.add_argument("--staging-path", type=Path)
    args = parser.parse_args(argv)
    manifest = build_index(
        args.dump,
        args.output,
        snapshot_version=args.snapshot_version,
        source_url=args.source_url,
        license_name=args.license_name,
        attribution=args.attribution,
        include_release_relations=not args.no_release_relations,
        staging_path=args.staging_path,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
