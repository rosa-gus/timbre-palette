"""Cloudflare Queue consumer and outbox sweeper for MusicBrainz enrichment."""

import json
import re
from collections.abc import Mapping
from time import monotonic

from workers import WorkerEntrypoint

from palette_api.album_catalog import D1AlbumCatalogRepository
from palette_api.domain import Track
from palette_api.enrichment import D1QueueEnrichmentScheduler
from palette_api.enrichment import D1PreparedAlbumPlanner
from palette_api.enrichment import D1WorkUnitRepository
from palette_api.musicbrainz import (
    D1EnrichmentJobRepository,
    D1IdentityRepository,
    MusicBrainzEnricher,
    MusicBrainzAlbumCollector,
    MusicBrainzInvalidResponseError,
    MusicBrainzUnavailableError,
    MusicBrainzResolver,
    WorkersFetchJsonTransport,
)
from palette_api.queue_contract import parse_enrichment_message, retry_delay_seconds


MAIN_QUEUE_NAME = "timbre-palette-enrichment"
DLQ_QUEUE_NAME = "timbre-palette-enrichment-dlq"
JOB_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
# Keep the scheduled sweep small: every row requires several sequential D1 and
# Queue operations, and the cron invocation has its own CPU budget.
CRON_ALBUM_PLAN_LIMIT = 1
CRON_DISPATCH_LIMIT = 6
MAX_QUEUE_RETRY_DELAY_SECONDS = 24 * 60 * 60


class Default(WorkerEntrypoint):
    async def queue(self, batch, env=None, ctx=None) -> None:
        jobs = D1EnrichmentJobRepository(self.env.DB)
        if _text(getattr(batch, "queue", None)) == DLQ_QUEUE_NAME:
            await self._consume_dead_letters(batch, jobs)
            return

        user_agent = _text(getattr(self.env, "MUSICBRAINZ_USER_AGENT", None))
        if not user_agent:
            _log_event(
                "enrichment_configuration_error",
                reason_code="missing_musicbrainz_user_agent",
            )
            raise RuntimeError("MUSICBRAINZ_USER_AGENT não configurado.")
        transport = WorkersFetchJsonTransport(user_agent=user_agent)
        resolver = MusicBrainzResolver(transport)
        enricher = MusicBrainzEnricher(resolver, D1IdentityRepository(self.env.DB))
        album_collector = MusicBrainzAlbumCollector(transport)

        for message in batch.messages:
            started_at = monotonic()
            message_id = _optional_text(getattr(message, "id", None))
            try:
                parsed = parse_enrichment_message(message.body)
            except ValueError as error:
                await self._reject_invalid_message(
                    message, jobs, str(error), message_id=message_id
                )
                continue

            if parsed.work_unit_key:
                await self._process_work_unit(
                    message,
                    parsed,
                    jobs,
                    enricher,
                    album_collector,
                    message_id=message_id,
                )
                continue
            if not parsed.job_key:
                await self._reject_invalid_message(
                    message,
                    jobs,
                    "A mensagem não contém job_key ou work_unit_key.",
                    message_id=message_id,
                )
                continue

            try:
                job = await jobs.get(parsed.job_key)
            except Exception as error:
                await self._retry_message(
                    message,
                    jobs,
                    parsed.job_key,
                    parsed.generation,
                    error,
                    message_id=message_id,
                    job_type=parsed.job_type,
                    target_mbid=parsed.target_mbid,
                    started_at=started_at,
                    operation="get_job",
                )
                continue
            if job is None:
                _log_event(
                    "enrichment_orphan_message",
                    job_key=parsed.job_key,
                    message_id=message_id,
                    job_type=parsed.job_type,
                    target_mbid=parsed.target_mbid,
                )
                message.ack()
                continue

            generation = int(_value(job, "generation") or 1)
            job_type = parsed.job_type
            target_mbid = parsed.target_mbid or _optional_text(
                _value(job, "source_mbid")
            )
            if parsed.generation != generation:
                _log_event(
                    "enrichment_stale_message",
                    job_key=parsed.job_key,
                    message_id=message_id,
                    message_generation=parsed.generation,
                    current_generation=generation,
                    job_type=job_type,
                    target_mbid=target_mbid,
                )
                message.ack()
                continue

            status = _text(_value(job, "status"))
            if status in {"completed", "ambiguous", "terminal"}:
                _log_event(
                    "enrichment_already_final",
                    job_key=parsed.job_key,
                    message_id=message_id,
                    job_type=job_type,
                    target_mbid=target_mbid,
                    status=status,
                )
                message.ack()
                continue

            try:
                claim = await jobs.claim_processing(
                    parsed.job_key,
                    generation,
                    message_id,
                )
            except Exception as error:
                await self._retry_message(
                    message,
                    jobs,
                    parsed.job_key,
                    generation,
                    error,
                    message_id=message_id,
                    job_type=job_type,
                    target_mbid=target_mbid,
                    started_at=started_at,
                    operation="claim_processing",
                )
                continue
            if claim == "final" or claim in {"missing", "stale"}:
                _log_event(
                    "enrichment_claim_skipped",
                    job_key=parsed.job_key,
                    message_id=message_id,
                    job_type=job_type,
                    target_mbid=target_mbid,
                    claim=claim,
                )
                message.ack()
                continue
            if claim == "busy":
                _log_event(
                    "enrichment_claim_busy",
                    job_key=parsed.job_key,
                    message_id=message_id,
                    job_type=job_type,
                    target_mbid=target_mbid,
                    action="ack_duplicate",
                )
                # The active delivery owns the lease. Retrying this duplicate
                # only creates another Queue read and can send it to the DLQ.
                message.ack()
                continue

            _log_event(
                "enrichment_started",
                job_key=parsed.job_key,
                message_id=message_id,
                job_type=job_type,
                target_mbid=target_mbid,
                attempt=int(getattr(message, "attempts", 1) or 1),
            )

            if parsed.job_type == "release":
                try:
                    album_repository = D1AlbumCatalogRepository(self.env.DB)
                    release_mbid = parsed.target_mbid or ""
                    if await album_repository.has_cached_release(release_mbid):
                        await album_repository.publish_cached_release()
                        await album_repository.mark_collected(release_mbid)
                        await jobs.mark_release_completed(parsed.job_key, generation)
                        _log_event(
                            "enrichment_processed",
                            job_key=parsed.job_key,
                            message_id=message_id,
                            job_type=job_type,
                            target_mbid=target_mbid,
                            result="completed_cached",
                            duration_ms=_duration_ms(started_at),
                        )
                        message.ack()
                        continue
                    album = await album_collector.collect(release_mbid)
                    if album is None:
                        await album_repository.mark_ignored(release_mbid)
                        await jobs.mark_ambiguous(
                            parsed.job_key,
                            "O lançamento não foi encontrado no MusicBrainz.",
                            generation,
                        )
                    else:
                        await album_repository.save(album)
                        await album_repository.mark_collected(album.release_mbid)
                        await jobs.mark_release_completed(parsed.job_key, generation)
                except (MusicBrainzUnavailableError, MusicBrainzInvalidResponseError) as error:
                    await self._retry_message(
                        message,
                        jobs,
                        parsed.job_key,
                        generation,
                        error,
                        message_id=message_id,
                        job_type=job_type,
                        target_mbid=target_mbid,
                        started_at=started_at,
                        operation="release_processing",
                    )
                    continue
                except Exception as error:
                    await self._retry_message(
                        message,
                        jobs,
                        parsed.job_key,
                        generation,
                        error,
                        message_id=message_id,
                        job_type=job_type,
                        target_mbid=target_mbid,
                        started_at=started_at,
                        operation="release_processing",
                    )
                    continue
                _log_event(
                    "enrichment_processed",
                    job_key=parsed.job_key,
                    message_id=message_id,
                    job_type=job_type,
                    target_mbid=target_mbid,
                    result="ambiguous" if album is None else "completed",
                    duration_ms=_duration_ms(started_at),
                )
                message.ack()
                continue

            track = Track(
                title=_text(_value(job, "title")),
                artist=_text(_value(job, "artist")),
                play_count=0,
                mbid=_optional_text(_value(job, "source_mbid")),
            )
            try:
                recording_id = await enricher.enrich_track(track)
                if recording_id is None:
                    result = "ambiguous"
                    await jobs.mark_ambiguous(
                        parsed.job_key,
                        "Nenhuma correspondência única foi encontrada.",
                        generation,
                    )
                elif await enricher.accepted_claim_count(recording_id) == 0:
                    result = "completed_without_evidence"
                    await jobs.mark_resolved_without_evidence(
                        parsed.job_key, recording_id, generation
                    )
                else:
                    result = "completed"
                    await jobs.mark_completed(
                        parsed.job_key, recording_id, generation
                    )
            except (MusicBrainzUnavailableError, MusicBrainzInvalidResponseError) as error:
                await self._retry_message(
                    message,
                    jobs,
                    parsed.job_key,
                    generation,
                    error,
                    message_id=message_id,
                    job_type=job_type,
                    target_mbid=target_mbid,
                    started_at=started_at,
                    operation="recording_processing",
                )
                continue
            except Exception as error:
                # Unknown adapter/D1 failures are treated as transient. Queue's
                # configured retry limit is the circuit breaker that moves the
                # message to the DLQ, where it becomes terminal.
                await self._retry_message(
                    message,
                    jobs,
                    parsed.job_key,
                    generation,
                    error,
                    message_id=message_id,
                    job_type=job_type,
                    target_mbid=target_mbid,
                    started_at=started_at,
                    operation="recording_processing",
                )
                continue
            _log_event(
                "enrichment_processed",
                job_key=parsed.job_key,
                message_id=message_id,
                job_type=job_type,
                target_mbid=target_mbid,
                result=result,
                duration_ms=_duration_ms(started_at),
            )
            message.ack()

    async def _process_work_unit(
        self,
        message,
        parsed,
        jobs: D1EnrichmentJobRepository,
        enricher: MusicBrainzEnricher,
        album_collector: MusicBrainzAlbumCollector,
        *,
        message_id: str | None,
    ) -> None:
        """Process up to WORK_UNIT_SIZE jobs with one Queue delivery.

        Completed items are skipped on redelivery. A transient error retries
        the work-unit message once, while the active item and the unit retain
        their D1 state. This keeps Queue retries proportional to work units,
        not to the number of tracks in a profile.
        """

        work_units = D1WorkUnitRepository(self.env.DB)
        work_key = parsed.work_unit_key
        generation = parsed.generation
        try:
            unit = await work_units.get(work_key)
        except Exception as error:
            await self._retry_work_unit(
                message,
                work_units,
                work_key,
                generation,
                error,
                message_id=message_id,
                operation="get_work_unit",
            )
            return
        if unit is None:
            _log_event(
                "enrichment_orphan_work_unit",
                work_unit_key=work_key,
                message_id=message_id,
            )
            message.ack()
            return

        current_generation = int(_value(unit, "generation") or 1)
        status = _text(_value(unit, "status"))
        if generation != current_generation or status in {
            "completed",
            "terminal",
            "recovery_required",
        }:
            _log_event(
                "enrichment_work_unit_skipped",
                work_unit_key=work_key,
                message_id=message_id,
                message_generation=generation,
                current_generation=current_generation,
                status=status,
            )
            message.ack()
            return

        try:
            claim = await work_units.claim_processing(
                work_key, current_generation, message_id
            )
        except Exception as error:
            await self._retry_work_unit(
                message,
                work_units,
                work_key,
                current_generation,
                error,
                message_id=message_id,
                operation="claim_work_unit",
            )
            return
        if claim in {"final", "missing", "stale", "busy"}:
            _log_event(
                "enrichment_work_unit_claim_skipped",
                work_unit_key=work_key,
                message_id=message_id,
                claim=claim,
                action="ack_duplicate" if claim == "busy" else "ack",
            )
            message.ack()
            return

        try:
            job_keys = await work_units.job_keys(work_key)
            if not job_keys:
                await work_units.mark_completed(work_key, current_generation)
                message.ack()
                return
            for job_key in job_keys:
                job = await jobs.get(job_key)
                if job is None:
                    continue
                job_generation = int(_value(job, "generation") or 1)
                if job_generation != current_generation:
                    continue
                job_status = _text(_value(job, "status"))
                if job_status in {"completed", "ambiguous", "terminal"}:
                    continue
                job_claim = await jobs.claim_processing(
                    job_key, current_generation, message_id
                )
                if job_claim in {"final", "missing", "stale", "busy"}:
                    continue
                started_at = monotonic()
                job_type = _text(_value(job, "job_type")) or "recording"
                target_mbid = _optional_text(
                    _value(job, "target_mbid") or _value(job, "source_mbid")
                )
                try:
                    result = await self._process_claimed_job(
                        jobs,
                        enricher,
                        album_collector,
                        job,
                        job_key,
                        current_generation,
                        job_type=job_type,
                        target_mbid=target_mbid,
                    )
                except Exception as error:
                    await self._retry_message(
                        message,
                        jobs,
                        job_key,
                        current_generation,
                        error,
                        message_id=message_id,
                        job_type=job_type,
                        target_mbid=target_mbid,
                        started_at=started_at,
                        operation=(
                            "release_processing"
                            if job_type == "release"
                            else "recording_processing"
                        ),
                        work_units=work_units,
                        work_unit_key=work_key,
                    )
                    return
                _log_event(
                    "enrichment_processed",
                    job_key=job_key,
                    work_unit_key=work_key,
                    message_id=message_id,
                    job_type=job_type,
                    target_mbid=target_mbid,
                    result=result,
                    duration_ms=_duration_ms(started_at),
                )
            await work_units.mark_completed(work_key, current_generation)
        except Exception as error:
            await self._retry_work_unit(
                message,
                work_units,
                work_key,
                current_generation,
                error,
                message_id=message_id,
                operation="work_unit_processing",
            )
            return
        message.ack()

    async def _process_claimed_job(
        self,
        jobs: D1EnrichmentJobRepository,
        enricher: MusicBrainzEnricher,
        album_collector: MusicBrainzAlbumCollector,
        job,
        job_key: str,
        generation: int,
        *,
        job_type: str,
        target_mbid: str | None,
    ) -> str:
        if job_type == "release":
            album_repository = D1AlbumCatalogRepository(self.env.DB)
            release_mbid = target_mbid or ""
            if await album_repository.has_cached_release(release_mbid):
                await album_repository.publish_cached_release()
                await album_repository.mark_collected(release_mbid)
                await jobs.mark_release_completed(job_key, generation)
                return "completed_cached"
            album = await album_collector.collect(release_mbid)
            if album is None:
                await album_repository.mark_ignored(release_mbid)
                await jobs.mark_ambiguous(
                    job_key,
                    "O lançamento não foi encontrado no MusicBrainz.",
                    generation,
                )
                return "ambiguous"
            await album_repository.save(album)
            await album_repository.mark_collected(album.release_mbid)
            await jobs.mark_release_completed(job_key, generation)
            return "completed"

        track = Track(
            title=_text(_value(job, "title")),
            artist=_text(_value(job, "artist")),
            play_count=0,
            mbid=_optional_text(_value(job, "source_mbid")),
        )
        recording_id = await enricher.enrich_track(track)
        if recording_id is None:
            await jobs.mark_ambiguous(
                job_key,
                "Nenhuma correspondência única foi encontrada.",
                generation,
            )
            return "ambiguous"
        if await enricher.accepted_claim_count(recording_id) == 0:
            await jobs.mark_resolved_without_evidence(job_key, recording_id, generation)
            return "completed_without_evidence"
        await jobs.mark_completed(job_key, recording_id, generation)
        return "completed"

    async def scheduled(self, controller, env, ctx) -> None:
        started_at = monotonic()
        scheduler = D1QueueEnrichmentScheduler(
            self.env.DB,
            self.env.ENRICHMENT_QUEUE,
        )
        try:
            planned_albums = await D1PreparedAlbumPlanner(
                self.env.DB, scheduler
            ).enqueue_due(limit=CRON_ALBUM_PLAN_LIMIT)
            dispatched = await scheduler.recover_pending(limit=CRON_DISPATCH_LIMIT)
        except Exception as error:
            _log_event(
                "enrichment_outbox_sweep_error",
                duration_ms=_duration_ms(started_at),
                **_error_fields(error),
            )
            raise
        _log_event(
            "enrichment_outbox_sweep",
            dispatched=dispatched,
            planned_albums=planned_albums,
            album_plan_limit=CRON_ALBUM_PLAN_LIMIT,
            dispatch_limit=CRON_DISPATCH_LIMIT,
            duration_ms=_duration_ms(started_at),
        )

    async def _retry_message(
        self,
        message,
        jobs: D1EnrichmentJobRepository,
        job_key: str,
        generation: int,
        error: Exception,
        *,
        message_id: str | None = None,
        job_type: str | None = None,
        target_mbid: str | None = None,
        started_at: float | None = None,
        operation: str | None = None,
        work_units: D1WorkUnitRepository | None = None,
        work_unit_key: str | None = None,
    ) -> None:
        attempts = int(getattr(message, "attempts", 1) or 1)
        error_message = _safe_error_message(error) or type(error).__name__
        try:
            await jobs.mark_failed(job_key, error_message, generation)
        except Exception as state_error:
            # The original failure is still retryable even when D1 cannot
            # persist the failure state. Keep the Queue delivery alive and
            # expose both failures in the tail.
            state_error_fields = _error_fields(state_error)
            state_error_fields.setdefault("operation", "mark_failed")
            _log_event(
                "enrichment_state_update_error",
                job_key=job_key,
                message_id=message_id,
                generation=generation,
                **state_error_fields,
            )

        if work_units is not None and work_unit_key:
            try:
                await work_units.mark_failed(work_unit_key, generation, error_message)
            except Exception as state_error:
                state_error_fields = _error_fields(state_error)
                state_error_fields.setdefault("operation", "mark_work_unit_failed")
                _log_event(
                    "enrichment_state_update_error",
                    work_unit_key=work_unit_key,
                    message_id=message_id,
                    generation=generation,
                    **state_error_fields,
                )

        base_delay = retry_delay_seconds(job_key, attempts)
        retry_after_seconds = _optional_nonnegative_int(
            getattr(error, "retry_after_seconds", None)
        )
        delay = min(
            MAX_QUEUE_RETRY_DELAY_SECONDS,
            max(base_delay, retry_after_seconds or 0),
        )
        error_fields = _error_fields(error)
        if operation:
            error_fields.setdefault("operation", operation)
        _log_event(
            "enrichment_retry",
            job_key=job_key,
            message_id=message_id,
            generation=generation,
            job_type=job_type,
            target_mbid=target_mbid,
            attempt=attempts,
            base_delay_seconds=base_delay,
            delay_seconds=delay,
            duration_ms=_duration_ms(started_at),
            **error_fields,
        )
        message.retry(delaySeconds=delay)

    async def _retry_work_unit(
        self,
        message,
        work_units: D1WorkUnitRepository,
        work_unit_key: str,
        generation: int,
        error: Exception,
        *,
        message_id: str | None,
        operation: str,
    ) -> None:
        error_message = _safe_error_message(error) or type(error).__name__
        try:
            await work_units.mark_failed(work_unit_key, generation, error_message)
        except Exception as state_error:
            state_error_fields = _error_fields(state_error)
            state_error_fields.setdefault("operation", "mark_work_unit_failed")
            _log_event(
                "enrichment_state_update_error",
                work_unit_key=work_unit_key,
                message_id=message_id,
                generation=generation,
                **state_error_fields,
            )
        attempts = int(getattr(message, "attempts", 1) or 1)
        delay = min(
            MAX_QUEUE_RETRY_DELAY_SECONDS,
            retry_delay_seconds(work_unit_key, attempts),
        )
        error_fields = _error_fields(error)
        error_fields.setdefault("operation", operation)
        _log_event(
            "enrichment_work_unit_retry",
            work_unit_key=work_unit_key,
            message_id=message_id,
            generation=generation,
            attempt=attempts,
            delay_seconds=delay,
            **error_fields,
        )
        message.retry(delaySeconds=delay)

    async def _consume_dead_letters(self, batch, jobs) -> None:
        for message in batch.messages:
            message_id = _optional_text(getattr(message, "id", None))
            try:
                parsed = parse_enrichment_message(message.body)
            except ValueError as error:
                _log_event(
                    "enrichment_invalid_dead_letter",
                    message_id=message_id,
                    **_error_fields(error),
                )
                message.ack()
                continue
            if parsed.work_unit_key:
                work_units = D1WorkUnitRepository(self.env.DB)
                try:
                    unit = await work_units.get(parsed.work_unit_key)
                    if unit is None:
                        message.ack()
                        continue
                    generation = int(_value(unit, "generation") or 1)
                    status = _text(_value(unit, "status"))
                    if parsed.generation != generation or status in {
                        "completed",
                        "terminal",
                        "recovery_required",
                    }:
                        message.ack()
                        continue
                    previous_error = _safe_error_message(
                        _value(unit, "last_error")
                    )
                    await work_units.mark_recovery_required(
                        parsed.work_unit_key,
                        generation,
                        previous_error
                        or "A unidade excedeu o limite de retentativas da Queue.",
                    )
                except Exception as error:
                    state_error_fields = _error_fields(error)
                    state_error_fields.setdefault(
                        "operation", "mark_work_unit_recovery_required"
                    )
                    _log_event(
                        "enrichment_dead_letter_state_error",
                        work_unit_key=parsed.work_unit_key,
                        message_id=message_id,
                        **state_error_fields,
                    )
                    message.retry(delaySeconds=60)
                    continue
                _log_event(
                    "enrichment_work_unit_dead_lettered",
                    work_unit_key=parsed.work_unit_key,
                    message_id=message_id,
                    generation=generation,
                    previous_error=previous_error,
                )
                message.ack()
                continue
            if not parsed.job_key:
                message.ack()
                continue
            try:
                job = await jobs.get(parsed.job_key)
            except Exception as error:
                state_error_fields = _error_fields(error)
                state_error_fields.setdefault("operation", "get_job")
                _log_event(
                    "enrichment_dead_letter_state_error",
                    job_key=parsed.job_key,
                    message_id=message_id,
                    **state_error_fields,
                )
                message.retry(delaySeconds=60)
                continue
            if job is None:
                message.ack()
                continue
            generation = int(_value(job, "generation") or 1)
            if parsed.generation != generation or _text(_value(job, "status")) in {
                "completed",
                "ambiguous",
                "terminal",
            }:
                message.ack()
                continue
            try:
                await jobs.mark_dead_lettered(
                    parsed.job_key,
                    "A mensagem excedeu o limite de retentativas da Queue.",
                    generation,
                )
            except Exception as error:
                state_error_fields = _error_fields(error)
                state_error_fields.setdefault("operation", "mark_dead_lettered")
                _log_event(
                    "enrichment_dead_letter_state_error",
                    job_key=parsed.job_key,
                    message_id=message_id,
                    generation=generation,
                    **state_error_fields,
                )
                message.retry(delaySeconds=60)
                continue
            _log_event(
                "enrichment_dead_lettered",
                job_key=parsed.job_key,
                message_id=message_id,
                generation=generation,
                job_type=parsed.job_type,
                target_mbid=parsed.target_mbid or _optional_text(
                    _value(job, "source_mbid")
                ),
                queue_attempts=int(getattr(message, "attempts", 0) or 0),
                processing_attempts=int(
                    _value(job, "processing_attempts") or 0
                ),
                previous_error=_safe_error_message(_value(job, "last_error")),
            )
            message.ack()

    async def _reject_invalid_message(
        self,
        message,
        jobs,
        error: str,
        *,
        message_id: str | None = None,
    ) -> None:
        body = message.body
        job_key = body.get("job_key") if isinstance(body, Mapping) else None
        if isinstance(job_key, str) and JOB_KEY_PATTERN.fullmatch(job_key):
            try:
                job = await jobs.get(job_key)
                if job is not None:
                    await jobs.mark_terminal(
                        job_key,
                        error,
                        int(_value(job, "generation") or 1),
                        reason_code="invalid_message",
                    )
            except Exception as state_error:
                state_error_fields = _error_fields(state_error)
                state_error_fields.setdefault("operation", "mark_terminal")
                _log_event(
                    "enrichment_invalid_message_state_error",
                    job_key=job_key,
                    message_id=message_id,
                    **state_error_fields,
                )
                message.retry(delaySeconds=30)
                return
        _log_event(
            "enrichment_invalid_message",
            job_key=job_key if isinstance(job_key, str) else None,
            message_id=message_id,
            reason_code="invalid_message",
            error_message=_safe_error_message(error),
        )
        message.ack()


def _value(row: object, key: str) -> object:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    text = _text(value)
    return text or None


def _optional_nonnegative_int(value: object) -> int | None:
    try:
        parsed = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return max(0, parsed) if parsed is not None else None


def _duration_ms(started_at: float | None) -> int | None:
    if started_at is None:
        return None
    return max(0, round((monotonic() - started_at) * 1000))


def _safe_error_message(error: object) -> str | None:
    message = " ".join(str(error).split())
    message = re.sub(r"https?://\S+", "<url>", message)
    return message[:300] or None


def _error_fields(error: Exception) -> dict[str, object]:
    fields: dict[str, object] = {
        "service": getattr(error, "service", "enrichment"),
        "error_type": type(error).__name__,
        "error_message": _safe_error_message(error),
        "reason_code": getattr(error, "reason_code", "unexpected_error"),
    }
    for attribute in ("operation", "status_code"):
        value = getattr(error, attribute, None)
        if value is not None:
            fields[attribute] = value
    retry_after_seconds = getattr(error, "retry_after_seconds", None)
    if retry_after_seconds is not None:
        fields["retry_after_seconds"] = retry_after_seconds
    cause = getattr(error, "__cause__", None)
    if isinstance(cause, Exception):
        fields["cause_type"] = type(cause).__name__
        fields["cause_message"] = _safe_error_message(cause)
    return fields


def _log_event(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))
