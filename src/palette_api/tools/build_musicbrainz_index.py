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
import math
import re
import sqlite3
import sys
import tarfile
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from palette_api.musicbrainz_index import (
    INDEX_OBJECT_PREFIX,
    INDEX_SCHEMA_VERSION,
    INDEX_TRACK_PREFIX,
    object_key,
)


DEFAULT_SOURCE_URL = "https://musicbrainz.org/doc/MusicBrainz_Database/Download"
DEFAULT_ATTRIBUTION = "MusicBrainz; derived instrumental-credit index."
DEFAULT_LICENSE = "CC0"
RELATION_TYPES = ("vocal", "vocals", "programming", "samples", "sampled")
CORE_TABLES = (
    "artist",
    "recording",
    "instrument",
    "link_type",
    "link",
    "link_attribute_type",
    "link_attribute",
    "l_artist_recording",
)
RELEASE_TABLES = ("release", "medium", "track", "l_artist_release")
_MBID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class IndexTargets:
    """The small slice of the dump that the catalog currently needs."""

    recording_mbids: frozenset[str] = frozenset()
    track_mbids: frozenset[str] = frozenset()
    release_mbids: frozenset[str] = frozenset()

    @classmethod
    def from_path(cls, path: Path) -> "IndexTargets":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("The target manifest must be a JSON object.")

        def values(key: str) -> frozenset[str]:
            raw = payload.get(key, [])
            if not isinstance(raw, list):
                raise ValueError(f"Target manifest field {key!r} must be a list.")
            result = {
                item.strip().lower()
                for item in raw
                if isinstance(item, str) and item.strip()
            }
            invalid = [item for item in result if not _is_mbid(item)]
            if invalid:
                raise ValueError(f"Invalid MusicBrainz MBID in {key}: {invalid[0]}")
            return frozenset(result)

        targets = cls(
            recording_mbids=values("recording_mbids"),
            track_mbids=values("track_mbids"),
            release_mbids=values("release_mbids"),
        )
        if not any((targets.recording_mbids, targets.track_mbids, targets.release_mbids)):
            raise ValueError("The target manifest does not contain any MBIDs.")
        return targets


class TableNotFound(FileNotFoundError):
    pass


class BuildProgress:
    """Periodic human-readable progress for the command-line ETL."""

    LOAD_PERCENT = 70.0

    def __init__(
        self,
        *,
        interval_seconds: float = 5.0,
        stream: TextIO | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        self.interval_seconds = interval_seconds
        self.stream = stream or sys.stderr
        self.started_at = time.monotonic()
        self.last_report_at = self.started_at
        self.total_tables = 1
        self.completed_tables = 0
        self.current_table = ""
        self.current_rows = 0
        self.current_table_bytes: int | None = None
        self.current_position: int | None = None
        self.output_records = 0
        self.output_credits = 0

    def start(self, total_tables: int) -> None:
        self.total_tables = max(1, total_tables)
        self._emit(0.0, f"iniciando ETL; {total_tables} tabelas previstas", force=True)

    def inspecting_dump(self, dump_path: Path) -> None:
        self._emit(0.0, f"inspecionando dump {dump_path.name}", force=True)

    def archive_member_scanned(self, member_count: int) -> None:
        if self._is_due():
            self._emit(0.0, f"catalogando dump: {member_count:,} entradas")

    def archive_scan_heartbeat(self, member_count: int) -> None:
        self._emit(
            0.0,
            f"catalogando dump: leitura em andamento ({member_count:,} entradas)",
            force=True,
        )

    def archive_catalogued(self, member_count: int) -> None:
        self._emit(
            0.0,
            f"dump catalogado: {member_count:,} entradas",
            force=True,
        )

    def start_table(self, table_name: str, *, total_bytes: int | None = None) -> None:
        self.current_table = table_name
        self.current_rows = 0
        self.current_table_bytes = total_bytes if total_bytes and total_bytes > 0 else None
        self.current_position = 0
        self._emit(self._load_percent(), f"carregando {table_name}", force=True)

    def row_processed(self) -> bool:
        self.current_rows += 1
        return self._is_due()

    def report_table(self, position: int | None = None) -> None:
        self.current_position = position
        self._emit(self._load_percent(), self._table_detail())

    def finish_table(self) -> None:
        self.current_position = self.current_table_bytes
        self.completed_tables += 1
        self._emit(
            self._load_percent(),
            f"{self.current_table}: {self.current_rows:,} linhas",
            force=True,
        )

    def start_writing(self) -> None:
        self._emit(self.LOAD_PERCENT, "gerando objetos do índice", force=True)

    def output_record(self, record_count: int, credit_count: int) -> None:
        self.output_records = record_count
        self.output_credits = credit_count
        if self._is_due():
            self._emit(
                self.LOAD_PERCENT,
                f"gerando objetos: {record_count:,} gravações, "
                f"{credit_count:,} créditos",
            )

    def complete(self, record_count: int, credit_count: int) -> None:
        elapsed = self._elapsed()
        self._emit(
            100.0,
            f"concluído: {record_count:,} gravações, {credit_count:,} créditos "
            f"em {elapsed:.0f}s",
            force=True,
        )

    def _load_percent(self) -> float:
        progress = float(self.completed_tables)
        if self.current_table_bytes and self.current_position is not None:
            progress += min(
                1.0,
                max(0.0, self.current_position / self.current_table_bytes),
            )
        return min(self.LOAD_PERCENT, self.LOAD_PERCENT * progress / self.total_tables)

    def _table_detail(self) -> str:
        if self.current_table_bytes and self.current_position is not None:
            table_percent = min(
                100.0,
                max(0.0, 100.0 * self.current_position / self.current_table_bytes),
            )
            return (
                f"carregando {self.current_table}: {table_percent:.1f}% da tabela, "
                f"{self.current_rows:,} linhas"
            )
        return f"carregando {self.current_table}: {self.current_rows:,} linhas"

    def _is_due(self) -> bool:
        return time.monotonic() - self.last_report_at >= self.interval_seconds

    def _elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def _emit(self, percent: float, detail: str, *, force: bool = False) -> None:
        if not force and not self._is_due():
            return
        self.last_report_at = time.monotonic()
        print(
            f"[{percent:5.1f}%] {detail} (decorrido {self._elapsed():.0f}s)",
            file=self.stream,
            flush=True,
        )


class DumpSource:
    """Open named tables from an extracted dump or a tar/bz2 archive."""

    def __init__(
        self,
        path: Path,
        *,
        progress: BuildProgress | None = None,
    ) -> None:
        self.path = path
        self._directory_files: dict[str, Path] | None = None
        self._archive_members: tuple[str, ...] | None = None
        self._archive_member_sizes: dict[str, int] | None = None
        if path.is_dir():
            files: dict[str, Path] = {}
            for candidate in path.rglob("*"):
                if candidate.is_file():
                    files.setdefault(_normalized_table_name(candidate.name), candidate)
            self._directory_files = files
        elif path.is_file() and _is_archive(path):
            members = []
            entry_count = 0
            heartbeat_stop: threading.Event | None = None
            heartbeat_thread: threading.Thread | None = None
            if progress is not None:
                heartbeat_stop = threading.Event()

                def report_heartbeat() -> None:
                    while not heartbeat_stop.wait(progress.interval_seconds):
                        progress.archive_scan_heartbeat(entry_count)

                heartbeat_thread = threading.Thread(
                    target=report_heartbeat,
                    name="musicbrainz-dump-progress",
                    daemon=True,
                )
                heartbeat_thread.start()
            try:
                with tarfile.open(path, mode="r:*") as archive:
                    while True:
                        member = archive.next()
                        if member is None:
                            break
                        entry_count += 1
                        if member.isfile():
                            members.append(member)
                        if progress is not None:
                            progress.archive_member_scanned(entry_count)
            finally:
                if heartbeat_stop is not None:
                    heartbeat_stop.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join()
            self._archive_members = tuple(member.name for member in members)
            self._archive_member_sizes = {
                _normalized_table_name(Path(member.name).name): member.size
                for member in members
            }
            if progress is not None:
                progress.archive_catalogued(entry_count)

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

    def table_size(self, table_name: str) -> int | None:
        location = self._find_table(table_name)
        if isinstance(location, Path):
            if location.suffix == ".bz2":
                return None
            try:
                return location.stat().st_size
            except OSError:
                return None
        if self._archive_member_sizes is None:
            return None
        return self._archive_member_sizes.get(
            _normalized_table_name(Path(location).name)
        )

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
    targets: IndexTargets | None = None,
    staging_path: Path | None = None,
    progress: BuildProgress | None = None,
) -> dict[str, object]:
    """Build the index and return the generated manifest."""

    if not snapshot_version.strip():
        raise ValueError("snapshot_version is required.")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {output_dir}. Choose a new directory."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    if progress is not None:
        progress.inspecting_dump(dump_path)
    source = DumpSource(dump_path, progress=progress)
    planned_tables = _planned_table_names(source, include_release_relations)
    if progress is not None:
        progress.start(len(planned_tables))

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
            if targets is None:
                _load_required_tables(source, connection, progress=progress)
                has_release_tables = include_release_relations and _load_release_tables(
                    source, connection, progress=progress
                )
                track_aliases: list[tuple[str, str]] = []
            else:
                has_release_tables, track_aliases = _load_targeted_tables(
                    source,
                    connection,
                    targets,
                    include_release_relations=include_release_relations,
                    progress=progress,
                )
            manifest = _write_index(
                connection,
                output_dir,
                snapshot_version=snapshot_version.strip(),
                source_url=source_url.strip(),
                license_name=license_name.strip(),
                attribution=attribution.strip(),
                include_release_relations=has_release_tables,
                progress=progress,
            )
            if targets is not None:
                alias_count = _write_track_aliases(
                    output_dir,
                    track_aliases,
                    snapshot_version=snapshot_version.strip(),
                )
                manifest.update(
                    {
                        "targeted": True,
                        "target_recording_count": len(targets.recording_mbids),
                        "target_track_count": len(targets.track_mbids),
                        "target_release_count": len(targets.release_mbids),
                        "track_alias_count": alias_count,
                        "estimated_class_a_operations": math.ceil(
                            (int(manifest["record_count"]) + alias_count) * 1.10
                        )
                        + 2,
                        "track_object_prefix": INDEX_TRACK_PREFIX,
                        "track_key_template": f"{INDEX_TRACK_PREFIX}/{{track_mbid}}.json",
                    }
                )
                (output_dir / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        finally:
            connection.close()
    finally:
        if temporary_staging is not None:
            temporary_staging.cleanup()
    if progress is not None:
        progress.complete(
            int(manifest["record_count"]),
            int(manifest["credit_count"]),
        )
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


def _load_targeted_tables(
    source: DumpSource,
    connection: sqlite3.Connection,
    targets: IndexTargets,
    *,
    include_release_relations: bool,
    progress: BuildProgress | None = None,
) -> tuple[bool, list[tuple[str, str]]]:
    """Stage only rows reachable from the requested MBIDs.

    The full dump is still streamed once per relevant table, but the large
    relation tables never enter SQLite and no object is emitted outside the
    requested recording/release/track slice. This is the important difference
    from the catalog-wide ETL path.
    """

    release_rows: list[tuple[int, str]] = []
    release_ids: set[int] = set()
    has_release_tables = include_release_relations and all(
        source.has_table(table_name) for table_name in RELEASE_TABLES
    )
    if has_release_tables:
        def collect_release(row: list[str | None]) -> None:
            values = _first_values(row, 2)
            if values is None or str(values[1]).lower() not in targets.release_mbids:
                return
            release_id = int(values[0])
            release_ids.add(release_id)
            release_rows.append((release_id, str(values[1]).lower()))

        _scan_table(source, "release", collect_release, progress=progress)
    elif include_release_relations:
        print(
            "MusicBrainz release relation tables are incomplete; "
            "targeted build will include recording-scoped credits only.",
            file=sys.stderr,
        )

    medium_rows: list[tuple[int, int]] = []
    medium_ids: set[int] = set()
    if has_release_tables:
        def collect_medium(row: list[str | None]) -> None:
            values = _values(row, (0, 2), integer_indexes={0, 2})
            if values is None or int(values[1]) not in release_ids:
                return
            medium_id, release_id = int(values[0]), int(values[1])
            medium_ids.add(medium_id)
            medium_rows.append((medium_id, release_id))

        _scan_table(source, "medium", collect_medium, progress=progress)

    raw_track_rows: list[tuple[str | None, int, int, int | None, str | None]] = []
    target_track_mbid_set = targets.track_mbids
    if has_release_tables:
        def collect_track(row: list[str | None]) -> None:
            if len(row) <= 3:
                return
            track_mbid = _optional_mbid(row[1])
            recording_id = _integer(row[2])
            medium_id = _integer(row[3])
            if recording_id is None or medium_id is None:
                return
            if track_mbid not in target_track_mbid_set and medium_id not in medium_ids:
                return
            position = _integer(row[4]) if len(row) > 4 else None
            title = _optional_text(row[6]) if len(row) > 6 else None
            raw_track_rows.append(
                (
                    track_mbid,
                    recording_id,
                    medium_id,
                    position,
                    title,
                )
            )

        _scan_table(source, "track", collect_track, progress=progress)
    elif targets.track_mbids:
        print(
            "Track targets were supplied but release tables are unavailable; "
            "track aliases cannot be built.",
            file=sys.stderr,
        )

    target_recording_ids = {row[1] for row in raw_track_rows}
    recording_rows: list[tuple[int, str]] = []

    def collect_recording(row: list[str | None]) -> None:
        values = _first_values(row, 2)
        if values is None:
            return
        recording_id, recording_mbid = int(values[0]), str(values[1]).lower()
        if recording_mbid not in targets.recording_mbids and recording_id not in target_recording_ids:
            return
        target_recording_ids.add(recording_id)
        recording_rows.append((recording_id, recording_mbid))

    _scan_table(source, "recording", collect_recording, progress=progress)
    recording_mbid_by_id = {recording_id: mbid for recording_id, mbid in recording_rows}

    recording_relation_rows: list[tuple[int, int, int]] = []
    release_relation_rows: list[tuple[int, int, int]] = []
    selected_link_ids: set[int] = set()
    selected_artist_ids: set[int] = set()

    def collect_recording_relation(row: list[str | None]) -> None:
        values = _values(row, (1, 2, 3), integer_indexes={1, 2, 3})
        if values is None or int(values[2]) not in target_recording_ids:
            return
        relation = (int(values[0]), int(values[1]), int(values[2]))
        recording_relation_rows.append(relation)
        selected_link_ids.add(relation[0])
        selected_artist_ids.add(relation[1])

    _scan_table(
        source,
        "l_artist_recording",
        collect_recording_relation,
        progress=progress,
    )

    if has_release_tables:
        def collect_release_relation(row: list[str | None]) -> None:
            values = _values(row, (1, 2, 3), integer_indexes={1, 2, 3})
            if values is None or int(values[2]) not in release_ids:
                return
            relation = (int(values[0]), int(values[1]), int(values[2]))
            release_relation_rows.append(relation)
            selected_link_ids.add(relation[0])
            selected_artist_ids.add(relation[1])

        _scan_table(
            source,
            "l_artist_release",
            collect_release_relation,
            progress=progress,
        )

    connection.executemany(
        "INSERT INTO recordings(id, mbid) VALUES (?, ?)", recording_rows
    )
    connection.executemany(
        "INSERT INTO releases(id, mbid) VALUES (?, ?)", release_rows
    )
    connection.executemany(
        "INSERT INTO media(id, release_id) VALUES (?, ?)", medium_rows
    )
    connection.executemany(
        "INSERT INTO tracks(recording_id, medium_id) VALUES (?, ?)",
        [(row[1], row[2]) for row in raw_track_rows],
    )
    connection.executemany(
        "INSERT INTO artist_recording(link, artist_id, recording_id) VALUES (?, ?, ?)",
        recording_relation_rows,
    )
    connection.executemany(
        "INSERT INTO artist_release(link, artist_id, release_id) VALUES (?, ?, ?)",
        release_relation_rows,
    )
    connection.commit()

    _load_table(
        source,
        "artist",
        connection,
        "INSERT OR IGNORE INTO artists(id, mbid) VALUES (?, ?)",
        lambda row: (
            _values(row, (0, 1), integer_indexes={0})
            if _integer(row[0]) in selected_artist_ids
            else None
        ),
        progress=progress,
    )
    _load_table(
        source,
        "instrument",
        connection,
        "INSERT OR IGNORE INTO instruments(gid, name) VALUES (?, ?)",
        lambda row: _values(row, (1, 2), integer_indexes=set()),
        progress=progress,
    )
    _load_table(
        source,
        "link_type",
        connection,
        "INSERT OR IGNORE INTO link_types(id, name) VALUES (?, ?)",
        lambda row: _values(row, (0, 6), integer_indexes={0}),
        progress=progress,
    )
    _load_table(
        source,
        "link",
        connection,
        "INSERT OR IGNORE INTO links(id, link_type) VALUES (?, ?)",
        lambda row: (
            _values(row, (0, 1), integer_indexes={0, 1})
            if _integer(row[0]) in selected_link_ids
            else None
        ),
        progress=progress,
    )
    _load_table(
        source,
        "link_attribute_type",
        connection,
        "INSERT OR IGNORE INTO attribute_types(id, gid, name) VALUES (?, ?, ?)",
        lambda row: _values(row, (0, 4, 5), integer_indexes={0}),
        progress=progress,
    )
    _load_table(
        source,
        "link_attribute",
        connection,
        "INSERT OR IGNORE INTO link_attributes(link, attribute_type) VALUES (?, ?)",
        lambda row: (
            _values(row, (0, 1), integer_indexes={0, 1})
            if _integer(row[0]) in selected_link_ids
            else None
        ),
        progress=progress,
    )
    if source.has_table("link_attribute_credit"):
        _load_table(
            source,
            "link_attribute_credit",
            connection,
            "INSERT OR IGNORE INTO attribute_credits(link, attribute_type, credited_as) VALUES (?, ?, ?)",
            lambda row: (
                _values(row, (0, 1, 2), integer_indexes={0, 1})
                if _integer(row[0]) in selected_link_ids
                else None
            ),
            progress=progress,
        )

    aliases = [
        (track_mbid, recording_mbid_by_id[recording_id])
        for track_mbid, recording_id, *_ in raw_track_rows
        if track_mbid and recording_id in recording_mbid_by_id
    ]
    return has_release_tables, aliases


def _scan_table(
    source: DumpSource,
    table_name: str,
    consumer,
    *,
    progress: BuildProgress | None = None,
) -> None:
    if progress is not None:
        progress.start_table(table_name, total_bytes=source.table_size(table_name))
    try:
        with source.table(table_name) as stream:
            for row in _copy_rows(stream):
                should_report = progress is not None and progress.row_processed()
                consumer(row)
                if should_report and progress is not None:
                    progress.report_table(_stream_position(stream))
    except TableNotFound as error:
        raise RuntimeError(f"Required MusicBrainz dump table is missing: {table_name}") from error
    if progress is not None:
        progress.finish_table()


def _write_track_aliases(
    output_dir: Path,
    aliases: list[tuple[str, str]],
    *,
    snapshot_version: str,
) -> int:
    written: set[str] = set()
    for track_mbid, recording_mbid in aliases:
        if not _is_mbid(track_mbid) or not _is_mbid(recording_mbid):
            continue
        normalized_track = track_mbid.lower()
        if normalized_track in written:
            continue
        payload = {
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "track_mbid": normalized_track,
            "recording_mbid": recording_mbid.lower(),
            "snapshot_version": snapshot_version,
            "source_url": f"https://musicbrainz.org/track/{normalized_track}",
        }
        target = output_dir / INDEX_TRACK_PREFIX / f"{normalized_track}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        written.add(normalized_track)
    return len(written)


def _planned_table_names(
    source: DumpSource,
    include_release_relations: bool,
) -> list[str]:
    planned = list(CORE_TABLES)
    if source.has_table("link_attribute_credit"):
        planned.append("link_attribute_credit")
    if include_release_relations and all(
        source.has_table(table_name) for table_name in RELEASE_TABLES
    ):
        planned.extend(RELEASE_TABLES)
    return planned


def _load_required_tables(
    source: DumpSource,
    connection: sqlite3.Connection,
    *,
    progress: BuildProgress | None = None,
) -> None:
    _load_table(
        source,
        "artist",
        connection,
        "INSERT OR IGNORE INTO artists(id, mbid) VALUES (?, ?)",
        lambda row: _first_values(row, 2),
        progress=progress,
    )
    _load_table(
        source,
        "recording",
        connection,
        "INSERT OR IGNORE INTO recordings(id, mbid) VALUES (?, ?)",
        lambda row: _first_values(row, 2),
        progress=progress,
    )
    _load_table(
        source,
        "instrument",
        connection,
        "INSERT OR IGNORE INTO instruments(gid, name) VALUES (?, ?)",
        lambda row: _values(row, (1, 2), integer_indexes=set()),
        progress=progress,
    )
    _load_table(
        source,
        "link_type",
        connection,
        "INSERT OR IGNORE INTO link_types(id, name) VALUES (?, ?)",
        lambda row: _values(row, (0, 6), integer_indexes={0}),
        progress=progress,
    )
    _load_table(
        source,
        "link",
        connection,
        "INSERT OR IGNORE INTO links(id, link_type) VALUES (?, ?)",
        lambda row: _values(row, (0, 1), integer_indexes={0, 1}),
        progress=progress,
    )
    _load_table(
        source,
        "link_attribute_type",
        connection,
        "INSERT OR IGNORE INTO attribute_types(id, gid, name) VALUES (?, ?, ?)",
        lambda row: _values(row, (0, 4, 5), integer_indexes={0}),
        progress=progress,
    )
    _load_table(
        source,
        "link_attribute",
        connection,
        "INSERT OR IGNORE INTO link_attributes(link, attribute_type) VALUES (?, ?)",
        lambda row: _values(row, (0, 1), integer_indexes={0, 1}),
        progress=progress,
    )
    _load_table(
        source,
        "l_artist_recording",
        connection,
        "INSERT INTO artist_recording(link, artist_id, recording_id) VALUES (?, ?, ?)",
        lambda row: _values(row, (1, 2, 3), integer_indexes={1, 2, 3}),
        progress=progress,
    )
    if source.has_table("link_attribute_credit"):
        _load_table(
            source,
            "link_attribute_credit",
            connection,
            "INSERT OR IGNORE INTO attribute_credits(link, attribute_type, credited_as) VALUES (?, ?, ?)",
            lambda row: _values(row, (0, 1, 2), integer_indexes={0, 1}),
            progress=progress,
        )


def _load_release_tables(
    source: DumpSource,
    connection: sqlite3.Connection,
    *,
    progress: BuildProgress | None = None,
) -> bool:
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
        progress=progress,
    )
    _load_table(
        source,
        "medium",
        connection,
        "INSERT OR IGNORE INTO media(id, release_id) VALUES (?, ?)",
        lambda row: _values(row, (0, 2), integer_indexes={0, 2}),
        progress=progress,
    )
    _load_table(
        source,
        "track",
        connection,
        "INSERT INTO tracks(recording_id, medium_id) VALUES (?, ?)",
        lambda row: _values(row, (2, 3), integer_indexes={2, 3}),
        progress=progress,
    )
    _load_table(
        source,
        "l_artist_release",
        connection,
        "INSERT INTO artist_release(link, artist_id, release_id) VALUES (?, ?, ?)",
        lambda row: _values(row, (1, 2, 3), integer_indexes={1, 2, 3}),
        progress=progress,
    )
    return True


def _load_table(
    source: DumpSource,
    table_name: str,
    connection: sqlite3.Connection,
    statement: str,
    transform,
    *,
    progress: BuildProgress | None = None,
) -> None:
    batch: list[tuple[object, ...]] = []
    if progress is not None:
        progress.start_table(table_name, total_bytes=source.table_size(table_name))
    try:
        with source.table(table_name) as stream:
            for row in _copy_rows(stream):
                should_report = progress is not None and progress.row_processed()
                values = transform(row)
                if should_report:
                    progress.report_table(_stream_position(stream))
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
    if progress is not None:
        progress.finish_table()


def _write_index(
    connection: sqlite3.Connection,
    output_dir: Path,
    *,
    snapshot_version: str,
    source_url: str,
    license_name: str,
    attribution: str,
    include_release_relations: bool,
    progress: BuildProgress | None = None,
) -> dict[str, object]:
    records_dir = output_dir / INDEX_OBJECT_PREFIX
    records_dir.mkdir(parents=True, exist_ok=True)
    if progress is not None:
        progress.start_writing()
    digest = hashlib.sha256()
    record_count = 0
    credit_count = 0
    record_bytes = 0

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
        nonlocal record_count, credit_count, record_bytes, current_mbid, current_credits
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
        record_bytes += len(encoded)
        if progress is not None:
            progress.output_record(record_count, credit_count)
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
        "record_bytes": record_bytes,
        "estimated_class_a_operations": record_count + 2,
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


def _stream_position(stream: TextIO) -> int | None:
    try:
        return int(stream.tell())
    except (OSError, ValueError):
        return None


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
        order_by = "recording.mbid, rel.link"
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
        order_by = "recording.mbid, rel.link"

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
        ORDER BY recording.mbid, rel.link
    """
    import heapq

    instrument_rows = connection.execute(instrument_query, (scope,))
    other_rows = connection.execute(other_query, (scope, *RELATION_TYPES))
    yield from heapq.merge(
        instrument_rows,
        other_rows,
        key=lambda row: (str(row[0]), str(row[-1])),
    )


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


def _integer(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _optional_mbid(value: object) -> str | None:
    normalized = _optional_text(value)
    if normalized is None or not _is_mbid(normalized):
        return None
    return normalized.lower()


def _is_mbid(value: str) -> bool:
    return bool(_MBID_RE.fullmatch(value))


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


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="mbdump directory or mbdump.tar.bz2")
    parser.add_argument("output", type=Path, help="empty directory for the R2 index")
    parser.add_argument(
        "--targets",
        type=Path,
        help=(
            "JSON manifest with recording_mbids, track_mbids and/or "
            "release_mbids; stages only this slice of the dump"
        ),
    )
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
    parser.add_argument(
        "--progress-interval",
        type=_positive_float,
        default=5.0,
        help="seconds between progress updates (default: 5)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable human-readable progress output on stderr",
    )
    args = parser.parse_args(argv)
    progress = (
        None
        if args.no_progress
        else BuildProgress(interval_seconds=args.progress_interval)
    )
    manifest = build_index(
        args.dump,
        args.output,
        snapshot_version=args.snapshot_version,
        source_url=args.source_url,
        license_name=args.license_name,
        attribution=args.attribution,
        include_release_relations=not args.no_release_relations,
        targets=IndexTargets.from_path(args.targets) if args.targets else None,
        staging_path=args.staging_path,
        progress=progress,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
