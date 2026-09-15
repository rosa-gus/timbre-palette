"""D1-backed outbox for recordings that still need enrichment."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from palette_api.domain import Track
from palette_api.album_catalog import demand_key


DISPATCH_BATCH_SIZE = 20
DISPATCH_LEASE_SECONDS = 120
DISPATCH_CONFIRMATION_SECONDS = 300


class QueueSender(Protocol):
    async def send(self, body: object, **kwargs: object) -> object: ...


class D1QueueEnrichmentScheduler:
    """Create jobs and publish them through a recoverable D1 outbox.

    D1 is the source of truth. Queue publication is retried by the cron
    sweeper when the HTTP request is interrupted, when ``send`` fails, or when
    no delivery confirmation is observed within the safety window. Duplicate
    publication is intentional: the consumer is idempotent.
    """

    def __init__(self, db: Any, queue: QueueSender) -> None:
        self._db = db
        self._queue = queue

    async def schedule(self, tracks: tuple[Track, ...]) -> None:
        by_key = {_job_key(track): track for track in tracks}
        if not by_key:
            return
        await self._record_demand(tuple(by_key.values()))
        keys = tuple(by_key)
        await self._ensure_jobs(tuple(by_key[key] for key in keys))
        # The request publishes only rows that are still waiting to be sent.
        # Stale queued rows are recovered by the scheduled sweeper instead of
        # multiplying messages on every API read.
        rows = await self._rows_for_keys(keys)
        await self._dispatch_rows(rows)

    async def schedule_release(
        self,
        release_mbid: str,
        *,
        artist: str = "",
        title: str = "",
    ) -> None:
        """Queue one prepared-album collection job through the same outbox."""

        release_mbid = release_mbid.strip()
        if not release_mbid:
            raise ValueError("release_mbid is required.")
        job_key = hashlib.sha256(f"release:{release_mbid}".encode()).hexdigest()
        await self._db.prepare(
            """
            INSERT OR IGNORE INTO enrichment_jobs
                (job_key, source_mbid, source_entity_type, artist, title,
                 job_type, target_mbid, stage, dispatch_status)
            VALUES (?, ?, 'unknown', ?, ?, 'release', ?, 'source', 'pending')
            """
        ).bind(
            job_key,
            release_mbid,
            artist or "Álbum",
            title or release_mbid,
            release_mbid,
        ).run()
        rows = await _all_rows(
            self._db.prepare(
                """
                SELECT job_key, generation, dispatch_status, job_type,
                       target_mbid, stage
                FROM enrichment_jobs
                WHERE job_key = ? AND status IN ('pending', 'failed')
                  AND dispatch_status IN ('pending', 'failed')
                  AND (next_dispatch_at IS NULL OR next_dispatch_at <= datetime('now'))
                LIMIT 1
                """
            ).bind(job_key)
        )
        await self._dispatch_release_rows(rows)

    async def recover_pending(self, limit: int = DISPATCH_BATCH_SIZE) -> int:
        """Publish due outbox rows; intended for a one-minute Cron Trigger."""

        query = """
            SELECT job_key, generation, dispatch_status, job_type,
                   target_mbid, stage
            FROM enrichment_jobs
            WHERE status IN ('pending', 'failed')
              AND (
                dispatch_status IN ('pending', 'failed')
                OR (dispatch_status = 'sending'
                    AND (dispatch_lease_until IS NULL OR dispatch_lease_until <= datetime('now')))
                OR (dispatch_status = 'queued'
                    AND next_dispatch_at IS NOT NULL AND next_dispatch_at <= datetime('now'))
              )
              AND (next_dispatch_at IS NULL OR next_dispatch_at <= datetime('now'))
            ORDER BY updated_at, id
            LIMIT ?
        """
        try:
            rows = await _all_rows(self._db.prepare(query).bind(limit))
        except Exception:
            # Fixtures created before migration 0009 contain only recording
            # jobs and use the smaller projection.
            rows = await _all_rows(
                self._db.prepare(
                    query.replace(
                        "SELECT job_key, generation, dispatch_status, job_type,\n                   target_mbid, stage",
                        "SELECT job_key, generation, dispatch_status",
                    )
                ).bind(limit)
            )
        release_rows = [
            row for row in rows if _text(_value(row, "job_type")) == "release"
        ]
        recording_rows = [
            row for row in rows if _text(_value(row, "job_type")) != "release"
        ]
        return await self._dispatch_rows(recording_rows) + await self._dispatch_release_rows(
            release_rows
        )

    async def _ensure_jobs(self, tracks: tuple[Track, ...]) -> None:
        for chunk in _chunks(tracks, DISPATCH_BATCH_SIZE):
            values = ", ".join("(?, ?, ?, ?, ?, 'pending')" for _ in chunk)
            params: list[object] = []
            for track in chunk:
                params.extend(
                    (
                        _job_key(track),
                        track.mbid,
                        "unknown" if track.mbid else None,
                        track.artist,
                        track.title,
                    )
                )
            await self._db.prepare(
                f"""
                INSERT OR IGNORE INTO enrichment_jobs
                    (job_key, source_mbid, source_entity_type, artist, title,
                     dispatch_status)
                VALUES {values}
                """
            ).bind(*params).run()

    async def _rows_for_keys(self, keys: tuple[str, ...]) -> list[Any]:
        placeholders = ", ".join("?" for _ in keys)
        statement = self._db.prepare(
            f"""
            SELECT job_key, generation, dispatch_status
            FROM enrichment_jobs
            WHERE job_key IN ({placeholders})
              AND status IN ('pending', 'failed')
              AND dispatch_status IN ('pending', 'failed')
              AND (next_dispatch_at IS NULL OR next_dispatch_at <= datetime('now'))
            ORDER BY updated_at, id
            """
        ).bind(*keys)
        return await _all_rows(statement)

    async def _dispatch_rows(self, rows: list[Any]) -> int:
        dispatched = 0
        for row in rows:
            job_key = _text(_value(row, "job_key"))
            generation = int(_value(row, "generation") or 1)
            dispatch_status = _text(_value(row, "dispatch_status"))
            if not job_key or not await self._claim_dispatch(
                job_key, generation, dispatch_status
            ):
                continue
            try:
                await self._queue.send(
                    {
                        "schema_version": 2,
                        "job_key": job_key,
                        "generation": generation,
                    }
                )
            except Exception as error:
                await self._mark_dispatch_failed(job_key, generation, str(error))
                _log_event(
                    "enrichment_dispatch_failed",
                    job_key=job_key,
                    generation=generation,
                    error_type=type(error).__name__,
                )
                continue
            await self._mark_dispatched(job_key, generation)
            dispatched += 1
            _log_event(
                "enrichment_dispatched",
                job_key=job_key,
                generation=generation,
            )
        return dispatched

    async def _dispatch_release_rows(self, rows: list[Any]) -> int:
        dispatched = 0
        for row in rows:
            job_key = _text(_value(row, "job_key"))
            generation = int(_value(row, "generation") or 1)
            dispatch_status = _text(_value(row, "dispatch_status"))
            target_mbid = _text(_value(row, "target_mbid"))
            if (
                not job_key
                or not target_mbid
                or not await self._claim_dispatch(job_key, generation, dispatch_status)
            ):
                continue
            try:
                await self._queue.send(
                    {
                        "schema_version": 2,
                        "job_key": job_key,
                        "generation": generation,
                        "job_type": "release",
                        "target_mbid": target_mbid,
                        "stage": _text(_value(row, "stage")) or "source",
                    }
                )
            except Exception as error:
                await self._mark_dispatch_failed(job_key, generation, str(error))
                _log_event(
                    "album_dispatch_failed",
                    job_key=job_key,
                    release_mbid=target_mbid,
                    error_type=type(error).__name__,
                )
                continue
            await self._mark_dispatched(job_key, generation)
            dispatched += 1
            _log_event(
                "album_dispatched",
                job_key=job_key,
                release_mbid=target_mbid,
                generation=generation,
            )
        return dispatched

    async def _record_demand(self, tracks: tuple[Track, ...]) -> None:
        """Aggregate missing tracks without storing usernames or histories."""

        try:
            for chunk in _chunks(tracks, DISPATCH_BATCH_SIZE):
                values = ", ".join("(?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))" for _ in chunk)
                params: list[object] = []
                for track in chunk:
                    params.extend(
                        (
                            demand_key(track.artist, track.title, track.mbid),
                            track.artist,
                            track.title,
                            track.mbid,
                            max(0, int(track.play_count)),
                        )
                    )
                await self._db.prepare(
                    f"""
                    INSERT INTO catalog_demand
                        (demand_key, artist, title, source_mbid, play_weight,
                         sightings, updated_at, last_seen_at)
                    VALUES {values}
                    ON CONFLICT(demand_key) DO UPDATE SET
                        play_weight = catalog_demand.play_weight + excluded.play_weight,
                        sightings = catalog_demand.sightings + 1,
                        last_seen_at = datetime('now'),
                        updated_at = datetime('now'),
                        status = CASE
                            WHEN catalog_demand.status = 'ignored' THEN 'ignored'
                            ELSE 'pending'
                        END
                    """
                ).bind(*params).run()
        except Exception as error:
            # Deployments must run migration 0009. This guard keeps the public
            # report available during a rolling local migration and surfaces
            # the omission in structured logs.
            _log_event("catalog_demand_unavailable", error_type=type(error).__name__)

    async def _claim_dispatch(
        self,
        job_key: str,
        generation: int,
        dispatch_status: str,
    ) -> bool:
        result = await self._db.prepare(
            """
            UPDATE enrichment_jobs
            SET dispatch_status = 'sending',
                dispatch_attempts = dispatch_attempts + 1,
                dispatch_lease_until = datetime('now', '+120 seconds'),
                updated_at = datetime('now')
            WHERE job_key = ? AND generation = ?
              AND status IN ('pending', 'failed')
              AND dispatch_status = ?
              AND (next_dispatch_at IS NULL OR next_dispatch_at <= datetime('now'))
              AND (
                dispatch_status IN ('pending', 'failed')
                OR (dispatch_status = 'sending'
                    AND (dispatch_lease_until IS NULL OR dispatch_lease_until <= datetime('now')))
                OR (dispatch_status = 'queued'
                    AND next_dispatch_at IS NOT NULL AND next_dispatch_at <= datetime('now'))
              )
            """
        ).bind(job_key, generation, dispatch_status).run()
        return _changes(result) > 0

    async def _mark_dispatched(self, job_key: str, generation: int) -> None:
        await self._db.prepare(
            """
            UPDATE enrichment_jobs
            SET dispatch_status = 'queued', queued_at = datetime('now'),
                next_dispatch_at = datetime('now', '+300 seconds'),
                dispatch_lease_until = NULL, dispatch_error = NULL,
                updated_at = datetime('now')
            WHERE job_key = ? AND generation = ? AND dispatch_status = 'sending'
            """
        ).bind(job_key, generation).run()

    async def _mark_dispatch_failed(
        self, job_key: str, generation: int, error: str
    ) -> None:
        await self._db.prepare(
            """
            UPDATE enrichment_jobs
            SET dispatch_status = 'failed', next_dispatch_at = datetime('now', '+30 seconds'),
                dispatch_lease_until = NULL, dispatch_error = ?, updated_at = datetime('now')
            WHERE job_key = ? AND generation = ? AND dispatch_status = 'sending'
            """
        ).bind(error[:1000], job_key, generation).run()


class D1PreparedAlbumPlanner:
    """Turns the curated album manifest into idempotent release jobs."""

    def __init__(self, db: Any, scheduler: D1QueueEnrichmentScheduler) -> None:
        self._db = db
        self._scheduler = scheduler

    async def enqueue_due(self, limit: int = DISPATCH_BATCH_SIZE) -> int:
        try:
            rows = await _all_rows(
                self._db.prepare(
                    """
                    SELECT release_mbid, artist, title
                    FROM prepared_album_targets
                    WHERE status = 'pending'
                    ORDER BY priority DESC, updated_at, id
                    LIMIT ?
                    """
                ).bind(limit)
            )
        except Exception as error:
            _log_event("album_targets_unavailable", error_type=type(error).__name__)
            return 0
        planned = 0
        for row in rows:
            release_mbid = _text(_value(row, "release_mbid"))
            if not release_mbid:
                continue
            await self._scheduler.schedule_release(
                release_mbid,
                artist=_text(_value(row, "artist")),
                title=_text(_value(row, "title")),
            )
            await self._db.prepare(
                """
                UPDATE prepared_album_targets
                SET status = 'planned', updated_at = datetime('now')
                WHERE release_mbid = ? AND status = 'pending'
                """
            ).bind(release_mbid).run()
            planned += 1
        if planned:
            _log_event("album_targets_planned", count=planned)
        return planned


def _job_key(track: Track) -> str:
    payload = {
        "mbid": track.mbid or "",
        "artist": _normalize(track.artist),
        "title": _normalize(track.title),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _chunks(items: tuple[Track, ...], size: int) -> list[tuple[Track, ...]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


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


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _changes(result: Any) -> int:
    meta = _value(result, "meta")
    changes = _value(meta, "changes") if meta is not None else None
    try:
        return int(changes or 0)
    except (TypeError, ValueError):
        return 0


def _log_event(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))
