"""Prepared album catalog persistence and demand planning.

Album collection is deliberately separate from public palette calculation:
the collector stores a complete source document and raw observations first;
only snapshot-projected evidence is read by the v2 analysis service.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from palette_api.domain import Track
from palette_api.musicbrainz import (
    D1IdentityRepository,
    InstrumentCredit,
    PreparedAlbum,
    ResolvedRecording,
)


PARSER_VERSION = "musicbrainz-release-0.1.0"


class D1AlbumCatalogRepository:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def has_cached_release(self, release_mbid: str) -> bool:
        row = await _first(
            self._db.prepare(
                """
                SELECT id FROM source_documents
                WHERE source = 'musicbrainz' AND entity_type = 'release'
                  AND external_id = ? AND parser_version = ? AND status = 'fetched'
                ORDER BY fetched_at DESC
                LIMIT 1
                """
            ).bind(release_mbid, PARSER_VERSION)
        )
        return row is not None

    async def publish_cached_release(self) -> None:
        """Finish publication after a retry that already has the source body."""

        await self._publish_revision()

    async def save(self, album: PreparedAlbum) -> int:
        """Upsert an album snapshot and all its recording links idempotently."""

        source_document_id = await self._save_source_document(album)
        if album.artist_mbid:
            await self._run(
                """
                INSERT INTO artists (canonical_mbid, name, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(canonical_mbid) DO UPDATE SET
                    name = excluded.name, updated_at = datetime('now')
                """,
                album.artist_mbid,
                album.artist,
            )
        await self._run(
            """
            INSERT INTO album_groups
                (canonical_mbid, title, artist, artist_mbid,
                 first_release_date, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(canonical_mbid) DO UPDATE SET
                title = excluded.title,
                artist = excluded.artist,
                artist_mbid = excluded.artist_mbid,
                first_release_date = COALESCE(
                    excluded.first_release_date, album_groups.first_release_date
                ),
                updated_at = datetime('now')
            """,
            album.album_group_mbid,
            album.release_title,
            album.artist,
            album.artist_mbid,
            album.release_date,
        )
        group = await _first(
            self._db.prepare(
                "SELECT id FROM album_groups WHERE canonical_mbid = ? LIMIT 1"
            ).bind(album.album_group_mbid)
        )
        group_id = _required_int(group, "id", "album")
        await self._run(
            """
            INSERT INTO album_releases
                (album_group_id, canonical_mbid, title, country, release_date,
                 status, source_url, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(canonical_mbid) DO UPDATE SET
                album_group_id = excluded.album_group_id,
                title = excluded.title,
                country = excluded.country,
                release_date = excluded.release_date,
                status = excluded.status,
                source_url = excluded.source_url,
                updated_at = datetime('now')
            """,
            group_id,
            album.release_mbid,
            album.release_title,
            album.country,
            album.release_date,
            album.status,
            album.source_url,
        )
        release = await _first(
            self._db.prepare(
                "SELECT id FROM album_releases WHERE canonical_mbid = ? LIMIT 1"
            ).bind(album.release_mbid)
        )
        release_id = _required_int(release, "id", "edição")

        identity_repository = D1IdentityRepository(self._db)
        for track in album.tracks:
            await self._run(
                """
                INSERT INTO recordings (title, artist, canonical_mbid, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(canonical_mbid) DO UPDATE SET
                    title = excluded.title,
                    artist = excluded.artist,
                    updated_at = datetime('now')
                """,
                track.title,
                track.artist,
                track.recording_mbid,
            )
            recording = await _first(
                self._db.prepare(
                    "SELECT id FROM recordings WHERE canonical_mbid = ? LIMIT 1"
                ).bind(track.recording_mbid)
            )
            recording_id = _required_int(recording, "id", "recording")
            await self._run(
                """
                INSERT OR IGNORE INTO recording_identifiers
                    (recording_id, source, entity_type, external_id)
                VALUES (?, 'musicbrainz', 'recording', ?)
                """,
                recording_id,
                track.recording_mbid,
            )
            await self._run(
                """
                INSERT INTO album_tracks
                    (album_release_id, recording_id, disc_number, position,
                     title, length_ms, source_mbid, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(album_release_id, disc_number, position) DO UPDATE SET
                    recording_id = excluded.recording_id,
                    title = excluded.title,
                    length_ms = excluded.length_ms,
                    source_mbid = excluded.source_mbid,
                    updated_at = datetime('now')
                """,
                release_id,
                recording_id,
                track.disc_number,
                track.position,
                track.title,
                track.length_ms,
                track.recording_mbid,
            )
            for observation in track.observations:
                await self._run(
                    """
                    INSERT OR IGNORE INTO credit_observations
                        (recording_id, album_release_id, source_document_id,
                         relation_type, instrument_mbid, instrument_name,
                         performer, original_credit, scope, production_method,
                         sound_nature, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'observed')
                    """,
                    recording_id,
                    release_id,
                    source_document_id,
                    observation.relation_type,
                    observation.instrument_mbid or "",
                    observation.instrument_name or "",
                    observation.performer or "",
                    observation.original_credit,
                    observation.scope,
                    observation.production_method,
                    observation.sound_nature,
                )
            instrument_credits = tuple(
                InstrumentCredit(
                    instrument_mbid=observation.instrument_mbid or None,
                    instrument_name=observation.instrument_name or "",
                    performer=observation.performer,
                    original_credit=observation.original_credit,
                    scope=observation.scope,
                    source_url=album.source_url,
                    source_quality="album_recording_relation",
                    relation_type=observation.relation_type,
                    production_method=observation.production_method,
                    sound_nature=observation.sound_nature,
                )
                for observation in track.observations
                if observation.relation_type in {"instrument", "vocal", "vocals"}
                and observation.instrument_name
            )
            await identity_repository.save_enrichment(
                Track(track.title, track.artist, 0),
                ResolvedRecording(
                    mbid=track.recording_mbid,
                    title=track.title,
                    artist=track.artist,
                    method="mbid_recording",
                    confidence=1.0,
                    source_mbid=track.recording_mbid,
                    source_entity_type="recording",
                    instrument_credits=instrument_credits,
                ),
            )
        await self._run(
            """
            UPDATE source_documents
            SET status = 'fetched', fetched_at = datetime('now')
            WHERE id = ?
            """,
            source_document_id,
        )
        await self._publish_revision()
        return release_id

    async def mark_collected(self, release_mbid: str) -> None:
        await self._run(
            """
            UPDATE prepared_album_targets
            SET status = 'collected', updated_at = datetime('now')
            WHERE release_mbid = ?
            """,
            release_mbid,
        )

    async def mark_ignored(self, release_mbid: str) -> None:
        await self._run(
            """
            UPDATE prepared_album_targets
            SET status = 'ignored', updated_at = datetime('now')
            WHERE release_mbid = ?
            """,
            release_mbid,
        )

    async def _save_source_document(self, album: PreparedAlbum) -> int:
        body = json.dumps(
            album.raw_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        await self._run(
            """
            INSERT INTO source_documents
                (source, entity_type, external_id, request_key, source_url,
                 body_json, body_hash, parser_version, status)
            VALUES ('musicbrainz', 'release', ?, ?, ?, ?, ?, ?, 'pending')
            ON CONFLICT(source, entity_type, external_id, request_key, parser_version)
            DO UPDATE SET
                source_url = excluded.source_url,
                body_json = excluded.body_json,
                body_hash = excluded.body_hash,
                status = 'pending',
                error = NULL,
                fetched_at = datetime('now')
            """,
            album.release_mbid,
            MusicBrainzRequestKey(album.release_mbid),
            album.source_url,
            body,
            digest,
            PARSER_VERSION,
        )
        document = await _first(
            self._db.prepare(
                """
                SELECT id FROM source_documents
                WHERE source = 'musicbrainz' AND entity_type = 'release'
                  AND external_id = ? AND request_key = ? AND parser_version = ?
                LIMIT 1
                """
            ).bind(album.release_mbid, MusicBrainzRequestKey(album.release_mbid), PARSER_VERSION)
        )
        return _required_int(document, "id", "documento de fonte")

    async def _publish_revision(self) -> None:
        documents = await _all_rows(
            self._db.prepare(
                """
                SELECT body_hash FROM source_documents
                WHERE status = 'fetched' AND body_hash IS NOT NULL
                ORDER BY id
                """
            )
        )
        digest_input = "\n".join(str(_value(row, "body_hash")) for row in documents)
        if not digest_input:
            return
        manifest_hash = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
        revision = f"catalog-{manifest_hash[:16]}"
        await self._run(
            "UPDATE catalog_publications SET status = 'superseded' WHERE status = 'active'"
        )
        await self._run(
            """
            INSERT INTO catalog_publications
                (revision, manifest_hash, methodology_version, status, published_at)
            VALUES (?, ?, '0.2.0', 'active', datetime('now'))
            ON CONFLICT(revision) DO UPDATE SET
                status = 'active', published_at = datetime('now')
            """,
            revision,
            manifest_hash,
        )

    async def _run(self, query: str, *params: object) -> Any:
        statement = self._db.prepare(query).bind(*params)
        run_fn = getattr(statement, "run", None)
        if not callable(run_fn):
            raise RuntimeError("The D1 binding does not provide command execution.")
        return await run_fn()


class MusicBrainzRequestKey(str):
    """Stable key for the exact release include set used by the collector."""

    def __new__(cls, release_mbid: str) -> "MusicBrainzRequestKey":
        return str.__new__(cls, f"release:{release_mbid}:" + PARSER_VERSION)


def demand_key(artist: str, title: str, source_mbid: str | None = None) -> str:
    payload = {
        "artist": " ".join(artist.casefold().split()),
        "title": " ".join(title.casefold().split()),
        "mbid": source_mbid or "",
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


async def _first(statement: Any) -> Any:
    first_fn = getattr(statement, "first", None)
    return await first_fn() if callable(first_fn) else None


async def _all_rows(statement: Any) -> list[Any]:
    all_fn = getattr(statement, "all", None)
    result = await all_fn() if callable(all_fn) else None
    if result is None:
        return []
    rows = getattr(result, "results", result)
    return list(rows) if rows else []


def _value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _required_int(row: Any, key: str, label: str) -> int:
    value = _value(row, key) if row is not None else None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"Could not locate {label} in the catalog.") from error
