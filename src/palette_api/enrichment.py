"""D1-backed outbox for recordings that still need enrichment."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from palette_api.domain import Track
from palette_api.album_catalog import demand_key


DISPATCH_BATCH_SIZE = 20
WORK_UNIT_SIZE = 10


class QueueSender(Protocol):
    async def send(self, body: object, **kwargs: object) -> object: ...


class D1QueueEnrichmentScheduler:
    """Create jobs and publish them through a recoverable D1 outbox.

    D1 is the source of truth. Queue publication is retried by the cron
    sweeper only for pending/failed sends or expired send leases. A successful
    send is not republished merely because processing takes time: the Queue
    delivery, not a timer, owns that retry lifecycle.
    """

    def __init__(
        self,
        db: Any,
        queue: QueueSender | None,
        *,
        dispatch_on_schedule: bool = True,
    ) -> None:
        self._db = db
        self._queue = queue
        self._dispatch_on_schedule = dispatch_on_schedule
        self._work_units_enabled: bool | None = None

    async def schedule(self, tracks: tuple[Track, ...]) -> None:
        by_key = {_job_key(track): track for track in tracks}
        if not by_key:
            return
        await self._record_demand(tuple(by_key.values()))
        keys = tuple(by_key)
        await self._ensure_jobs(tuple(by_key[key] for key in keys))
        if await self._ensure_work_units(keys):
            # Public requests only create durable work. The cron sweeper is the
            # sole producer in production, which prevents a burst of profile
            # requests from publishing the same work repeatedly.
            if self._dispatch_on_schedule:
                await self._dispatch_work_units_for_keys(keys)
            return
        if self._dispatch_on_schedule:
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
        if await self._ensure_work_units((job_key,)):
            if self._dispatch_on_schedule:
                await self._dispatch_work_units_for_keys((job_key,))
            return
        if self._dispatch_on_schedule:
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
        """Publish due outbox work; intended for a one-minute Cron Trigger."""

        if await self._ensure_work_units_for_pending(limit * WORK_UNIT_SIZE):
            await self._recover_expired_work_units()
            rows = await _all_rows(
                self._db.prepare(
                    """
                    SELECT work_key, generation, dispatch_status
                    FROM enrichment_work_units
                    WHERE status IN ('pending', 'failed')
                      AND (
                        dispatch_status IN ('pending', 'failed')
                        OR (dispatch_status = 'sending'
                            AND (dispatch_lease_until IS NULL
                                 OR dispatch_lease_until <= datetime('now')))
                      )
                      AND (next_dispatch_at IS NULL OR next_dispatch_at <= datetime('now'))
                    ORDER BY updated_at, id
                    LIMIT ?
                    """
                ).bind(limit)
            )
            return await self._dispatch_work_unit_rows(rows)

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

    async def _recover_expired_work_units(self) -> None:
        """Return abandoned processing leases to the durable outbox."""

        await self._db.prepare(
            """
            UPDATE enrichment_work_units
            SET status = 'failed', dispatch_status = 'pending',
                processing_lease_until = NULL, next_dispatch_at = NULL,
                updated_at = datetime('now')
            WHERE status = 'processing'
              AND (processing_lease_until IS NULL
                   OR processing_lease_until <= datetime('now'))
            """
        ).run()

    async def _ensure_work_units(self, keys: tuple[str, ...]) -> bool:
        """Attach unassigned jobs to deterministic, idempotent work units."""

        if not keys:
            return True
        try:
            rows = await _all_rows(
                self._db.prepare(
                    """
                    SELECT job_key, generation
                    FROM enrichment_jobs
                    WHERE job_key IN ({placeholders})
                      AND work_unit_key IS NULL
                      AND status IN ('pending', 'failed')
                      AND dispatch_status IN ('pending', 'failed')
                    ORDER BY generation, job_key
                    """.format(placeholders=", ".join("?" for _ in keys))
                ).bind(*keys)
            )
        except Exception as error:
            # Keep the v2 path usable during a rolling migration and in old
            # local fixtures that do not have migration 0015 yet.
            self._work_units_enabled = False
            _log_event("enrichment_work_units_unavailable", error_type=type(error).__name__)
            return False
        self._work_units_enabled = True
        by_generation: dict[int, list[str]] = {}
        for row in rows:
            job_key = _text(_value(row, "job_key"))
            if not job_key:
                continue
            generation = int(_value(row, "generation") or 1)
            by_generation.setdefault(generation, []).append(job_key)
        for generation in sorted(by_generation):
            for chunk in _chunks(tuple(by_generation[generation]), WORK_UNIT_SIZE):
                work_key = _work_unit_key(chunk, generation)
                await self._db.prepare(
                    """
                    INSERT OR IGNORE INTO enrichment_work_units
                        (work_key, generation, status, dispatch_status)
                    VALUES (?, ?, 'pending', 'pending')
                    """
                ).bind(work_key, generation).run()
                for item_order, job_key in enumerate(chunk):
                    await self._db.prepare(
                        """
                        INSERT OR IGNORE INTO enrichment_work_unit_items
                            (work_unit_id, job_key, item_order)
                        SELECT id, ?, ?
                        FROM enrichment_work_units
                        WHERE work_key = ?
                        """
                    ).bind(job_key, item_order, work_key).run()
                    await self._db.prepare(
                        """
                        UPDATE enrichment_jobs
                        SET work_unit_key = ?, updated_at = datetime('now')
                        WHERE job_key = ? AND work_unit_key IS NULL
                        """
                    ).bind(work_key, job_key).run()
                await self._db.prepare(
                    """
                    UPDATE enrichment_work_units
                    SET item_count = (
                            SELECT COUNT(*) FROM enrichment_work_unit_items AS items
                            WHERE items.work_unit_id = enrichment_work_units.id
                        ),
                        updated_at = datetime('now')
                    WHERE work_key = ?
                    """
                ).bind(work_key).run()
        return True

    async def _ensure_work_units_for_pending(self, limit: int) -> bool:
        try:
            rows = await _all_rows(
                self._db.prepare(
                    """
                    SELECT job_key
                    FROM enrichment_jobs
                    WHERE work_unit_key IS NULL
                      AND status IN ('pending', 'failed')
                      AND dispatch_status IN ('pending', 'failed')
                      AND (next_dispatch_at IS NULL OR next_dispatch_at <= datetime('now'))
                    ORDER BY updated_at, id
                    LIMIT ?
                    """
                ).bind(limit)
            )
        except Exception as error:
            self._work_units_enabled = False
            _log_event("enrichment_work_units_unavailable", error_type=type(error).__name__)
            return False
        self._work_units_enabled = True
        keys = tuple(
            _text(_value(row, "job_key")) for row in rows if _text(_value(row, "job_key"))
        )
        return await self._ensure_work_units(keys)

    async def _dispatch_work_units_for_keys(self, keys: tuple[str, ...]) -> int:
        placeholders = ", ".join("?" for _ in keys)
        rows = await _all_rows(
            self._db.prepare(
                f"""
                SELECT DISTINCT units.work_key, units.generation,
                                units.dispatch_status
                FROM enrichment_work_units AS units
                JOIN enrichment_jobs AS jobs
                  ON jobs.work_unit_key = units.work_key
                WHERE jobs.job_key IN ({placeholders})
                  AND units.status IN ('pending', 'failed')
                  AND units.dispatch_status IN ('pending', 'failed')
                  AND (units.next_dispatch_at IS NULL
                       OR units.next_dispatch_at <= datetime('now'))
                ORDER BY units.updated_at, units.id
                """
            ).bind(*keys)
        )
        return await self._dispatch_work_unit_rows(rows)

    async def _dispatch_work_unit_rows(self, rows: list[Any]) -> int:
        if self._queue is None:
            raise RuntimeError("The enrichment Queue binding is not configured.")
        dispatched = 0
        for row in rows:
            work_key = _text(_value(row, "work_key"))
            generation = int(_value(row, "generation") or 1)
            dispatch_status = _text(_value(row, "dispatch_status"))
            if not work_key or not await self._claim_work_unit_dispatch(
                work_key, generation, dispatch_status
            ):
                continue
            try:
                await self._queue.send(
                    {
                        "schema_version": 3,
                        "work_unit_key": work_key,
                        "generation": generation,
                    }
                )
            except Exception as error:
                await self._mark_work_unit_dispatch_failed(
                    work_key, generation, str(error)
                )
                _log_event(
                    "enrichment_work_unit_dispatch_failed",
                    work_unit_key=work_key,
                    generation=generation,
                    error_type=type(error).__name__,
                )
                continue
            await self._mark_work_unit_dispatched(work_key, generation)
            dispatched += 1
            _log_event(
                "enrichment_work_unit_dispatched",
                work_unit_key=work_key,
                generation=generation,
            )
        return dispatched

    async def _claim_work_unit_dispatch(
        self,
        work_key: str,
        generation: int,
        dispatch_status: str,
    ) -> bool:
        result = await self._db.prepare(
            """
            UPDATE enrichment_work_units
            SET dispatch_status = 'sending',
                dispatch_attempts = dispatch_attempts + 1,
                dispatch_lease_until = datetime('now', '+120 seconds'),
                updated_at = datetime('now')
            WHERE work_key = ? AND generation = ?
              AND status IN ('pending', 'failed')
              AND dispatch_status = ?
              AND (
                next_dispatch_at IS NULL OR next_dispatch_at <= datetime('now')
              )
            """
        ).bind(work_key, generation, dispatch_status).run()
        return _changes(result) > 0

    async def _mark_work_unit_dispatched(self, work_key: str, generation: int) -> None:
        await self._db.prepare(
            """
            UPDATE enrichment_work_units
            SET dispatch_status = 'queued', queued_at = datetime('now'),
                next_dispatch_at = NULL, dispatch_lease_until = NULL,
                dispatch_error = NULL, updated_at = datetime('now')
            WHERE work_key = ? AND generation = ? AND dispatch_status = 'sending'
            """
        ).bind(work_key, generation).run()

    async def _mark_work_unit_dispatch_failed(
        self, work_key: str, generation: int, error: str
    ) -> None:
        await self._db.prepare(
            """
            UPDATE enrichment_work_units
            SET dispatch_status = 'failed',
                next_dispatch_at = datetime('now', '+30 seconds'),
                dispatch_lease_until = NULL, dispatch_error = ?,
                updated_at = datetime('now')
            WHERE work_key = ? AND generation = ? AND dispatch_status = 'sending'
            """
        ).bind(error[:1000], work_key, generation).run()

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
            """
        ).bind(job_key, generation, dispatch_status).run()
        return _changes(result) > 0

    async def _mark_dispatched(self, job_key: str, generation: int) -> None:
        await self._db.prepare(
            """
            UPDATE enrichment_jobs
            SET dispatch_status = 'queued', queued_at = datetime('now'),
                next_dispatch_at = NULL,
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


class D1WorkUnitRepository:
    """Leases and completes grouped enrichment work in D1."""

    PROCESSING_LEASE_SECONDS = 600

    def __init__(self, db: Any) -> None:
        self._db = db

    async def get(self, work_key: str) -> Any:
        return await _first(
            self._db.prepare(
                """
                SELECT work_key, generation, status, item_count, attempts,
                       processing_attempts, last_error, processing_lease_until
                FROM enrichment_work_units
                WHERE work_key = ?
                LIMIT 1
                """
            ).bind(work_key)
        )

    async def job_keys(self, work_key: str) -> tuple[str, ...]:
        rows = await _all_rows(
            self._db.prepare(
                """
                SELECT job_key
                FROM enrichment_work_unit_items
                WHERE work_unit_id = (
                    SELECT id FROM enrichment_work_units WHERE work_key = ?
                )
                ORDER BY item_order, job_key
                """
            ).bind(work_key)
        )
        return tuple(
            value for row in rows if (value := _text(_value(row, "job_key")))
        )

    async def claim_processing(
        self,
        work_key: str,
        generation: int,
        message_id: str | None,
    ) -> str:
        result = await self._run(
            """
            UPDATE enrichment_work_units
            SET status = 'processing', attempts = attempts + 1,
                processing_attempts = processing_attempts + 1,
                last_attempt_at = datetime('now'),
                processing_started_at = datetime('now'),
                processing_lease_until = datetime('now', '+600 seconds'),
                message_id = ?, updated_at = datetime('now')
            WHERE work_key = ? AND generation = ?
              AND (
                status IN ('pending', 'failed')
                OR (status = 'processing'
                    AND (processing_lease_until IS NULL
                         OR processing_lease_until <= datetime('now')))
              )
            """,
            message_id,
            work_key,
            generation,
        )
        if _changes(result) > 0:
            return "claimed"
        current = await self.get(work_key)
        if current is None:
            return "missing"
        current_generation = int(_value(current, "generation") or 1)
        if current_generation != generation:
            return "stale"
        current_status = _text(_value(current, "status"))
        if current_status in {"completed", "terminal", "recovery_required"}:
            return "final"
        if current_status == "processing":
            return "busy"
        return "stale"

    async def mark_failed(self, work_key: str, generation: int, error: str) -> None:
        await self._run(
            """
            UPDATE enrichment_work_units
            SET status = 'failed', last_error = ?,
                processing_lease_until = NULL, dispatch_status = 'queued',
                next_dispatch_at = NULL, updated_at = datetime('now')
            WHERE work_key = ? AND generation = ?
            """,
            error[:1000],
            work_key,
            generation,
        )

    async def mark_completed(self, work_key: str, generation: int) -> None:
        await self._run(
            """
            UPDATE enrichment_work_units
            SET status = 'completed', completed_at = datetime('now'),
                last_error = NULL, processing_lease_until = NULL,
                dispatch_status = 'none', next_dispatch_at = NULL,
                updated_at = datetime('now')
            WHERE work_key = ? AND generation = ?
            """,
            work_key,
            generation,
        )

    async def mark_recovery_required(
        self, work_key: str, generation: int, error: str
    ) -> None:
        await self._run(
            """
            UPDATE enrichment_work_units
            SET status = 'recovery_required', last_error = ?,
                terminal_reason_code = 'retry_exhausted',
                terminal_detail = ?, processing_lease_until = NULL,
                dispatch_status = 'none', next_dispatch_at = NULL,
                updated_at = datetime('now')
            WHERE work_key = ? AND generation = ?
            """,
            error[:1000],
            error[:1000],
            work_key,
            generation,
        )

    async def _run(self, query: str, *params: object) -> Any:
        statement = self._db.prepare(query).bind(*params)
        run_fn = getattr(statement, "run", None)
        if not callable(run_fn):
            raise RuntimeError("The D1 binding does not provide command execution.")
        return await run_fn()


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


def _work_unit_key(job_keys: tuple[str, ...], generation: int) -> str:
    payload = f"work-unit:v2:{generation}:" + ":".join(sorted(job_keys))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


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


async def _first(statement: Any) -> Any:
    first_fn = getattr(statement, "first", None)
    return await first_fn() if callable(first_fn) else None


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
