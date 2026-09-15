"""Cloudflare Queue consumer and outbox sweeper for MusicBrainz enrichment."""

import json
import re
from collections.abc import Mapping

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


class Default(WorkerEntrypoint):
    async def queue(self, batch, env=None, ctx=None) -> None:
        jobs = D1EnrichmentJobRepository(self.env.DB)
        if _text(getattr(batch, "queue", None)) == DLQ_QUEUE_NAME:
            await self._consume_dead_letters(batch, jobs)
            return

        user_agent = _text(getattr(self.env, "MUSICBRAINZ_USER_AGENT", None))
        if not user_agent:
            raise RuntimeError("MUSICBRAINZ_USER_AGENT não configurado.")
        transport = WorkersFetchJsonTransport(user_agent=user_agent)
        resolver = MusicBrainzResolver(transport)
        enricher = MusicBrainzEnricher(resolver, D1IdentityRepository(self.env.DB))
        album_collector = MusicBrainzAlbumCollector(transport)

        for message in batch.messages:
            try:
                parsed = parse_enrichment_message(message.body)
            except ValueError as error:
                await self._reject_invalid_message(message, jobs, str(error))
                continue

            job = await jobs.get(parsed.job_key)
            if job is None:
                _log_event(
                    "enrichment_orphan_message",
                    job_key=parsed.job_key,
                    message_id=_optional_text(getattr(message, "id", None)),
                )
                message.ack()
                continue

            generation = int(_value(job, "generation") or 1)
            if parsed.generation != generation:
                _log_event(
                    "enrichment_stale_message",
                    job_key=parsed.job_key,
                    message_generation=parsed.generation,
                    current_generation=generation,
                )
                message.ack()
                continue

            status = _text(_value(job, "status"))
            if status in {"completed", "ambiguous", "terminal"}:
                message.ack()
                continue

            claim = await jobs.claim_processing(
                parsed.job_key,
                generation,
                _optional_text(getattr(message, "id", None)),
            )
            if claim == "final" or claim in {"missing", "stale"}:
                message.ack()
                continue
            if claim == "busy":
                message.retry(delaySeconds=30)
                continue

            if parsed.job_type == "release":
                try:
                    album_repository = D1AlbumCatalogRepository(self.env.DB)
                    release_mbid = parsed.target_mbid or ""
                    if await album_repository.has_cached_release(release_mbid):
                        await album_repository.publish_cached_release()
                        await album_repository.mark_collected(release_mbid)
                        await jobs.mark_release_completed(parsed.job_key, generation)
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
                        message, jobs, parsed.job_key, generation, error
                    )
                    continue
                except Exception as error:
                    await self._retry_message(
                        message, jobs, parsed.job_key, generation, error
                    )
                    continue
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
                    await jobs.mark_ambiguous(
                        parsed.job_key,
                        "Nenhuma correspondência única foi encontrada.",
                        generation,
                    )
                elif await enricher.accepted_claim_count(recording_id) == 0:
                    await jobs.mark_resolved_without_evidence(
                        parsed.job_key, recording_id, generation
                    )
                else:
                    await jobs.mark_completed(
                        parsed.job_key, recording_id, generation
                    )
            except (MusicBrainzUnavailableError, MusicBrainzInvalidResponseError) as error:
                await self._retry_message(message, jobs, parsed.job_key, generation, error)
                continue
            except Exception as error:
                # Unknown adapter/D1 failures are treated as transient. Queue's
                # configured retry limit is the circuit breaker that moves the
                # message to the DLQ, where it becomes terminal.
                await self._retry_message(message, jobs, parsed.job_key, generation, error)
                continue
            message.ack()

    async def scheduled(self, controller, env, ctx) -> None:
        scheduler = D1QueueEnrichmentScheduler(
            self.env.DB,
            self.env.ENRICHMENT_QUEUE,
        )
        planned_albums = await D1PreparedAlbumPlanner(
            self.env.DB, scheduler
        ).enqueue_due()
        dispatched = await scheduler.recover_pending()
        _log_event(
            "enrichment_outbox_sweep",
            dispatched=dispatched,
            planned_albums=planned_albums,
        )

    async def _retry_message(
        self,
        message,
        jobs: D1EnrichmentJobRepository,
        job_key: str,
        generation: int,
        error: Exception,
    ) -> None:
        await jobs.mark_failed(job_key, str(error), generation)
        attempts = int(getattr(message, "attempts", 1) or 1)
        delay = retry_delay_seconds(job_key, attempts)
        _log_event(
            "enrichment_retry",
            job_key=job_key,
            generation=generation,
            attempt=attempts,
            delay_seconds=delay,
            error_type=type(error).__name__,
        )
        message.retry(delaySeconds=delay)

    async def _consume_dead_letters(self, batch, jobs) -> None:
        for message in batch.messages:
            try:
                parsed = parse_enrichment_message(message.body)
            except ValueError as error:
                _log_event("enrichment_invalid_dead_letter", error=str(error))
                message.ack()
                continue
            job = await jobs.get(parsed.job_key)
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
            await jobs.mark_dead_lettered(
                parsed.job_key,
                "A mensagem excedeu o limite de retentativas da Queue.",
                generation,
            )
            _log_event(
                "enrichment_dead_lettered",
                job_key=parsed.job_key,
                generation=generation,
                attempts=int(getattr(message, "attempts", 0) or 0),
            )
            message.ack()

    async def _reject_invalid_message(self, message, jobs, error: str) -> None:
        body = message.body
        job_key = body.get("job_key") if isinstance(body, Mapping) else None
        if isinstance(job_key, str) and JOB_KEY_PATTERN.fullmatch(job_key):
            job = await jobs.get(job_key)
            if job is not None:
                await jobs.mark_terminal(
                    job_key,
                    error,
                    int(_value(job, "generation") or 1),
                    reason_code="invalid_message",
                )
        _log_event(
            "enrichment_invalid_message",
            job_key=job_key if isinstance(job_key, str) else None,
            error=error,
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


def _log_event(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))
