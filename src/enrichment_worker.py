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
CRON_DISPATCH_LIMIT = 3
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
                    delay_seconds=30,
                )
                message.retry(delaySeconds=30)
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
