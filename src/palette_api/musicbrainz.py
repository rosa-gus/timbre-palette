"""MusicBrainz identity resolution and D1 persistence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
import unicodedata
from urllib.parse import quote, urlencode

from palette_api.domain import ListeningHistory, Track
from palette_api.lastfm import JsonHttpResponse


MUSICBRAINZ_API_URL = "https://musicbrainz.org/ws/2"
RESOLVER_VERSION = "musicbrainz-0.2.0"
DEFAULT_USER_AGENT = "timbre-palette-api/0.2"


class MusicBrainzError(Exception):
    """Base error for MusicBrainz adapter failures."""


class MusicBrainzUnavailableError(MusicBrainzError):
    pass


class MusicBrainzInvalidResponseError(MusicBrainzError):
    pass


class AsyncJsonTransport(Protocol):
    async def get_json(self, url: str) -> JsonHttpResponse: ...


class WorkersFetchJsonTransport:
    """HTTP transport backed by the native asynchronous Workers Fetch API."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        *,
        minimum_interval_ms: int = 1100,
        wait: Callable[[int], Awaitable[object]] | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._minimum_interval_ms = minimum_interval_ms
        self._wait = wait

    async def get_json(self, url: str) -> JsonHttpResponse:
        from workers import fetch

        await self._pace()
        try:
            response = await fetch(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self._user_agent,
                },
            )
            body = await response.json()
        except Exception as error:
            raise MusicBrainzUnavailableError(
                "Could not access MusicBrainz."
            ) from error
        return JsonHttpResponse(status_code=int(response.status), body=body)

    async def _pace(self) -> None:
        if self._minimum_interval_ms <= 0:
            return
        if self._wait is not None:
            await self._wait(self._minimum_interval_ms)
            return
        # Workers' scheduler.wait keeps the isolate suspended without burning
        # CPU. The import is local so repository/unit-test environments do not
        # need the Workers JS bridge.
        from js import scheduler

        await scheduler.wait(self._minimum_interval_ms)


@dataclass(frozen=True, slots=True)
class ResolvedRecording:
    mbid: str
    title: str
    artist: str
    method: str
    confidence: float
    source_mbid: str | None
    source_entity_type: str | None
    instrument_credits: tuple["InstrumentCredit", ...] = ()
    observations: tuple[CreditObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class InstrumentCredit:
    instrument_mbid: str | None
    instrument_name: str
    performer: str | None
    original_credit: str | None = None
    scope: str = "recording"
    source_url: str | None = None
    source_quality: str | None = "direct_relation"
    relation_type: str = "instrument"
    production_method: str = "performed"
    sound_nature: str | None = None


@dataclass(frozen=True, slots=True)
class CreditObservation:
    """A source relation preserved before it is mapped to the public taxonomy."""

    relation_type: str
    instrument_mbid: str | None
    instrument_name: str | None
    performer: str | None
    original_credit: str | None
    scope: str
    production_method: str = "unknown"
    sound_nature: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedAlbumTrack:
    position: int
    disc_number: int
    title: str
    recording_mbid: str
    artist: str
    length_ms: int | None
    observations: tuple[CreditObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedAlbum:
    release_mbid: str
    release_title: str
    artist: str
    album_group_mbid: str
    release_date: str | None
    country: str | None
    status: str | None
    source_url: str
    raw_payload: Mapping[str, object]
    tracks: tuple[PreparedAlbumTrack, ...]
    artist_mbid: str | None = None


@dataclass(frozen=True, slots=True)
class InstrumentMapping:
    target_slug: str
    target_kind: str
    method: str

    @property
    def instrument_slug(self) -> str | None:
        """Compatibility accessor for callers that only handle instruments."""

        return self.target_slug if self.target_kind == "instrument" else None

    @property
    def family_slug(self) -> str | None:
        return self.target_slug if self.target_kind == "family" else None


class D1InstrumentMapper:
    """Maps external credits to controlled instrument or family slugs."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def resolve(self, credit: InstrumentCredit) -> InstrumentMapping | None:
        if credit.instrument_mbid:
            row = await _first(
                self._db.prepare(
                    """
                    SELECT instrument_slug
                    FROM instrument_external_identifiers
                    WHERE source = 'musicbrainz' AND external_id = ?
                    LIMIT 1
                    """
                ).bind(credit.instrument_mbid)
            )
            slug = _value(row, "instrument_slug") if row is not None else None
            if slug:
                return InstrumentMapping(str(slug), "instrument", "external_id")

        normalized_alias = _normalize_instrument_alias(credit.instrument_name)
        if not normalized_alias:
            return None
        row = await _first(
            self._db.prepare(
                """
                SELECT instrument_slug
                FROM instrument_aliases
                WHERE source = 'musicbrainz'
                  AND locale = 'en'
                  AND normalized_alias = ?
                LIMIT 1
                """
            ).bind(normalized_alias)
        )
        slug = _value(row, "instrument_slug") if row is not None else None
        if slug:
            return InstrumentMapping(str(slug), "instrument", "alias")

        family_row = await _first(
            self._db.prepare(
                """
                SELECT family_slug
                FROM instrument_family_aliases
                WHERE source = 'musicbrainz'
                  AND locale = 'en'
                  AND normalized_alias = ?
                LIMIT 1
                """
            ).bind(normalized_alias)
        )
        family_slug = (
            _value(family_row, "family_slug") if family_row is not None else None
        )
        return (
            InstrumentMapping(str(family_slug), "family", "family_alias")
            if family_slug
            else None
        )


class MusicBrainzResolver:
    """Resolves a Last.fm track to a canonical MusicBrainz recording."""

    def __init__(
        self,
        transport: AsyncJsonTransport,
        *,
        api_url: str = MUSICBRAINZ_API_URL,
    ) -> None:
        self._transport = transport
        self._api_url = api_url.rstrip("/")

    async def resolve(self, track: Track) -> ResolvedRecording | None:
        if track.mbid:
            recording = await self._get_recording(track.mbid)
            if recording is not None:
                return self._from_entity(
                    recording,
                    method="mbid_recording",
                    confidence=1.0,
                    source_mbid=track.mbid,
                    source_entity_type="recording",
                )

            recording_id = await self._get_recording_from_track(track.mbid)
            if recording_id:
                recording = await self._get_recording(recording_id)
                if recording is not None:
                    return self._from_entity(
                        recording,
                        method="mbid_track_converted",
                        confidence=0.98,
                        source_mbid=track.mbid,
                        source_entity_type="track",
                    )

        return await self._search_recording(track)

    async def _get_recording(self, mbid: str) -> Mapping[str, object] | None:
        response = await self._request(
            f"/recording/{quote(mbid, safe='')}?inc=artist-credits+artist-rels"
        )
        if response.status_code == 404:
            return None
        payload = self._valid_mapping(response)
        if "id" not in payload:
            raise MusicBrainzInvalidResponseError(
                "MusicBrainz did not return a recording identifier."
            )
        return payload

    async def _get_recording_from_track(self, mbid: str) -> str | None:
        query = urlencode({"query": f"tid:{mbid}", "limit": "5"})
        response = await self._request(f"/recording/?{query}")
        payload = self._valid_mapping(response)
        recordings = payload.get("recordings")
        if not isinstance(recordings, list):
            return None
        ids = [
            candidate.get("id")
            for candidate in recordings
            if isinstance(candidate, Mapping) and isinstance(candidate.get("id"), str)
        ]
        unique_ids = list(dict.fromkeys(ids))
        return unique_ids[0] if len(unique_ids) == 1 else None

    async def _search_recording(self, track: Track) -> ResolvedRecording | None:
        query = (
            f'recording:"{_escape_search_value(track.title)}" '
            f'AND artist:"{_escape_search_value(track.artist)}"'
        )
        response = await self._request(
            f"/recording/?{urlencode({'query': query, 'limit': '5'})}"
        )
        payload = self._valid_mapping(response)
        recordings = payload.get("recordings")
        if not isinstance(recordings, list):
            raise MusicBrainzInvalidResponseError(
                "MusicBrainz did not return the expected recording collection."
            )

        normalized_title = _normalize(track.title)
        normalized_artist = _normalize(track.artist)
        candidates = [
            candidate
            for candidate in recordings
            if isinstance(candidate, Mapping)
            and _normalize(_text(candidate.get("title"))) == normalized_title
            and _artist_matches(candidate, normalized_artist)
        ]
        if not candidates:
            return None

        unique_candidates = {
            _text(candidate.get("id")): candidate
            for candidate in candidates
            if _text(candidate.get("id"))
        }
        if len(unique_candidates) != 1:
            return None
        candidate = next(iter(unique_candidates.values()))
        # Search responses are intentionally lightweight and commonly omit
        # artist/instrument relations. Hydrate the canonical recording before
        # extracting evidence so a text match has the same semantics as an
        # MBID lookup.
        candidate_mbid = _text(candidate.get("id"))
        if not candidate_mbid:
            raise MusicBrainzInvalidResponseError(
                "The matched recording does not contain a valid MBID."
            )
        complete_recording = await self._get_recording(candidate_mbid)
        if complete_recording is None:
            return None
        return self._from_entity(
            complete_recording,
            method=(
                "text_search_exact"
                if _text(candidate.get("title")) == track.title
                else "text_search_normalized"
            ),
            confidence=0.95,
            source_mbid=track.mbid,
            source_entity_type="track" if track.mbid else None,
        )

    async def _request(self, path: str) -> JsonHttpResponse:
        separator = "?" if "?" not in path else "&"
        response = await self._transport.get_json(
            f"{self._api_url}{path}{separator}fmt=json"
        )
        if response.status_code >= 500:
            raise MusicBrainzUnavailableError(
                f"MusicBrainz responded with HTTP {response.status_code}."
            )
        if response.status_code >= 400 and response.status_code != 404:
            raise MusicBrainzUnavailableError(
                f"MusicBrainz responded with HTTP {response.status_code}."
            )
        return response

    @staticmethod
    def _valid_mapping(response: JsonHttpResponse) -> Mapping[str, object]:
        if not isinstance(response.body, Mapping):
            raise MusicBrainzInvalidResponseError(
                "MusicBrainz returned an unexpected JSON document."
            )
        return response.body

    @staticmethod
    def _from_entity(
        entity: Mapping[str, object],
        *,
        method: str,
        confidence: float,
        source_mbid: str | None,
        source_entity_type: str | None,
    ) -> ResolvedRecording:
        mbid = _text(entity.get("id"))
        title = _text(entity.get("title"))
        artist = _artist_name(entity)
        if not mbid or not title or not artist:
            raise MusicBrainzInvalidResponseError(
                "The MusicBrainz recording does not contain a complete identity."
            )
        return ResolvedRecording(
            mbid=mbid,
            title=title,
            artist=artist,
            method=method,
            confidence=confidence,
            source_mbid=source_mbid,
            source_entity_type=source_entity_type,
            instrument_credits=_instrument_credits(entity),
            observations=_credit_observations(entity),
        )


class MusicBrainzAlbumCollector:
    """Fetches one complete release and keeps release context explicit.

    A release is fetched as a single source document. Its recordings are then
    persisted by ``D1AlbumCatalogRepository``; no release credit is silently
    copied to a recording claim.
    """

    RELEASE_INCLUDES = (
        "release-groups+recordings+artist-credits+recording-level-rels+"
        "artist-rels+recording-rels+work-rels+url-rels"
    )
    PARSER_VERSION = "musicbrainz-release-0.1.0"

    def __init__(
        self,
        transport: AsyncJsonTransport,
        *,
        api_url: str = MUSICBRAINZ_API_URL,
    ) -> None:
        self._transport = transport
        self._api_url = api_url.rstrip("/")

    async def collect(self, release_mbid: str) -> PreparedAlbum | None:
        response = await self._transport.get_json(
            f"{self._api_url}/release/{quote(release_mbid, safe='')}"
            f"?inc={self.RELEASE_INCLUDES}&fmt=json"
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 500:
            raise MusicBrainzUnavailableError(
                f"MusicBrainz responded with HTTP {response.status_code}."
            )
        if response.status_code >= 400:
            raise MusicBrainzUnavailableError(
                f"MusicBrainz responded with HTTP {response.status_code}."
            )
        if not isinstance(response.body, Mapping):
            raise MusicBrainzInvalidResponseError(
                "MusicBrainz returned an unexpected release."
            )
        return self._parse_release(response.body, release_mbid)

    @classmethod
    def _parse_release(
        cls, entity: Mapping[str, object], requested_mbid: str
    ) -> PreparedAlbum:
        release_mbid = _text(entity.get("id")) or requested_mbid
        title = _text(entity.get("title"))
        artist = _artist_name(entity)
        if not title or not artist:
            raise MusicBrainzInvalidResponseError(
                "The MusicBrainz release does not contain a complete identity."
            )
        group = entity.get("release-group")
        group_mbid = (
            _text(group.get("id"))
            if isinstance(group, Mapping)
            else ""
        ) or release_mbid
        media = entity.get("media")
        if not isinstance(media, list):
            raise MusicBrainzInvalidResponseError(
                "The MusicBrainz release does not contain media."
            )
        tracks: list[PreparedAlbumTrack] = []
        for media_index, medium in enumerate(media, start=1):
            if not isinstance(medium, Mapping):
                continue
            raw_tracks = medium.get("tracks")
            if not isinstance(raw_tracks, list):
                continue
            for track_index, track in enumerate(raw_tracks, start=1):
                if not isinstance(track, Mapping):
                    continue
                recording = track.get("recording")
                if not isinstance(recording, Mapping):
                    continue
                recording_mbid = _text(recording.get("id"))
                track_title = _text(track.get("title")) or _text(recording.get("title"))
                if not recording_mbid or not track_title:
                    continue
                track_artist = _artist_name(recording) or artist
                tracks.append(
                    PreparedAlbumTrack(
                        position=_positive_int(track.get("position"), track_index),
                        disc_number=_positive_int(medium.get("position"), media_index),
                        title=track_title,
                        recording_mbid=recording_mbid,
                        artist=track_artist,
                        length_ms=_optional_int(
                            track.get("length") or recording.get("length")
                        ),
                        observations=_credit_observations(
                            recording, scope="recording"
                        ),
                    )
                )
        return PreparedAlbum(
            release_mbid=release_mbid,
            release_title=title,
            artist=artist,
            album_group_mbid=group_mbid,
            release_date=_optional_text(entity.get("date")),
            country=_optional_text(entity.get("country")),
            status=_optional_text(
                entity.get("status")
                if isinstance(entity.get("status"), str)
                else None
            ),
            source_url=f"https://musicbrainz.org/release/{release_mbid}",
            raw_payload=entity,
            tracks=tuple(tracks),
            artist_mbid=_artist_mbid(entity),
        )


class D1IdentityRepository:
    """Persists canonical recordings and identity matches idempotently."""

    def __init__(
        self,
        db: Any,
        instrument_mapper: D1InstrumentMapper | None = None,
    ) -> None:
        self._db = db
        self._instrument_mapper = instrument_mapper or D1InstrumentMapper(db)

    async def save_match(self, track: Track, match: ResolvedRecording) -> int:
        recording_id = await self._recording_id(match.mbid)
        if recording_id is None:
            recording_id = await self._insert_recording(match)

        await self._run(
            """
            INSERT OR IGNORE INTO recording_identifiers
                (recording_id, source, entity_type, external_id)
            VALUES (?, 'musicbrainz', 'recording', ?)
            """,
            recording_id,
            match.mbid,
        )
        if track.mbid:
            entity_type = match.source_entity_type or "track"
            await self._run(
                """
                INSERT OR IGNORE INTO recording_identifiers
                    (recording_id, source, entity_type, external_id)
                VALUES (?, 'lastfm', ?, ?)
                """,
                recording_id,
                entity_type,
                track.mbid,
            )
        await self._run(
            """
            INSERT OR IGNORE INTO identity_matches
                (recording_id, method, confidence, resolver_version,
                 source_artist, source_title, source_mbid, source_entity_type)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM identity_matches
                WHERE recording_id = ? AND method = ? AND source_mbid IS ?
            )
            """,
            recording_id,
            match.method,
            match.confidence,
            RESOLVER_VERSION,
            track.artist,
            track.title,
            match.source_mbid,
            match.source_entity_type,
            recording_id,
            match.method,
            match.source_mbid,
        )
        return recording_id

    async def save_enrichment(self, track: Track, match: ResolvedRecording) -> int:
        """Persist identity and publish only controlled instrument mappings.

        D1 does not expose a callback transaction API to Python. Every write is
        therefore idempotent and guarded by unique indexes from the initial schema;
        a retry can safely replay the complete sequence.
        """
        recording_id = await self.save_match(track, match)
        for credit in match.instrument_credits:
            performer = credit.performer or ""
            original_credit = credit.original_credit or credit.instrument_name
            scope = (
                credit.scope
                if credit.scope in {"recording", "track", "release"}
                else None
            )
            if scope is None:
                raise MusicBrainzInvalidResponseError(
                    "The instrumental evidence scope is invalid."
                )
            source_url = credit.source_url or (
                f"https://musicbrainz.org/recording/{match.mbid}"
            )
            await self._run(
                """
                INSERT OR IGNORE INTO instrument_credit_candidates
                    (recording_id, source, instrument_mbid, instrument_name,
                     performer, original_credit, scope, source_url, status,
                     queue_priority, queue_reason)
                VALUES (?, 'musicbrainz', ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                recording_id,
                credit.instrument_mbid or "",
                credit.instrument_name,
                performer,
                original_credit,
                scope,
                source_url,
                20 if credit.instrument_mbid else 10,
                "unmapped_instrument_mbid"
                if credit.instrument_mbid
                else "unmapped_instrument_name",
            )
            mapping = await self._instrument_mapper.resolve(credit)
            if mapping is not None:
                await self._promote_mapped_credit(
                    recording_id=recording_id,
                    credit=credit,
                    performer=performer,
                    original_credit=original_credit,
                    scope=scope,
                    source_url=source_url,
                    mapping=mapping,
                )
        await self._run(
            """
            INSERT INTO enrichment_state
                (recording_id, status, attempts, last_attempt_at, completed_at,
                 last_error, updated_at)
            VALUES (?, 'completed', 1, datetime('now'), datetime('now'), NULL, datetime('now'))
            ON CONFLICT(recording_id) DO UPDATE SET
                status = 'completed',
                attempts = enrichment_state.attempts + 1,
                last_attempt_at = datetime('now'),
                completed_at = datetime('now'),
                last_error = NULL,
                updated_at = datetime('now')
            """,
            recording_id,
        )
        try:
            from palette_api.album_catalog import demand_key

            await self._run(
                """
                UPDATE catalog_demand
                SET status = 'covered', updated_at = datetime('now')
                WHERE demand_key = ?
                """,
                demand_key(track.artist, track.title, track.mbid),
            )
        except Exception:
            # The demand projection is introduced by migration 0009; identity
            # persistence remains valid if a local database is mid-migration.
            pass
        return recording_id

    async def accepted_claim_count(self, recording_id: int) -> int:
        row = await _first(
            self._db.prepare(
                """
                SELECT COUNT(*) AS count
                FROM instrument_claims
                WHERE recording_id = ?
                  AND (instrument_slug IS NOT NULL OR family_slug IS NOT NULL)
                  AND confidence_level IN ('documented', 'editorially_verified')
                """
            ).bind(recording_id)
        )
        value = _value(row, "count") if row is not None else 0
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    async def _promote_mapped_credit(
        self,
        *,
        recording_id: int,
        credit: InstrumentCredit,
        performer: str,
        original_credit: str,
        scope: str,
        source_url: str,
        mapping: InstrumentMapping,
    ) -> None:
        await self._run(
            """
            UPDATE instrument_credit_candidates
            SET instrument_slug = ?, family_slug = ?, resolution_method = ?,
                status = 'promoted', queue_reason = NULL,
                updated_at = datetime('now')
            WHERE recording_id = ? AND source = 'musicbrainz'
              AND instrument_mbid = ? AND instrument_name = ? AND performer = ?
            """,
            mapping.instrument_slug,
            mapping.family_slug,
            mapping.method,
            recording_id,
            credit.instrument_mbid or "",
            credit.instrument_name,
            performer,
        )
        await self._run(
            """
            INSERT OR IGNORE INTO instrument_claims
                (recording_id, instrument_slug, family_slug, confidence_level,
                 performer, role, prominence)
            VALUES (?, ?, ?, ?, ?, NULL, 1.0)
            """,
            recording_id,
            mapping.instrument_slug,
            mapping.family_slug,
            "documented" if scope in {"recording", "track"} else "release_context",
            performer,
        )
        if scope in {"recording", "track"}:
            # A later direct/track credit must strengthen a claim that was
            # initially created from release context, without downgrading an
            # editorially verified claim.
            await self._run(
                """
                UPDATE instrument_claims
                SET confidence_level = 'documented', updated_at = datetime('now')
                WHERE recording_id = ?
                  AND instrument_slug IS ? AND family_slug IS ?
                  AND ifnull(performer, '') = ? AND role IS NULL
                  AND confidence_level = 'release_context'
                """,
                recording_id,
                mapping.instrument_slug,
                mapping.family_slug,
                performer,
            )
        claim = await _first(
            self._db.prepare(
                """
                SELECT id
                FROM instrument_claims
                WHERE recording_id = ?
                  AND instrument_slug IS ? AND family_slug IS ?
                  AND ifnull(performer, '') = ? AND role IS NULL
                LIMIT 1
                """
            ).bind(
                recording_id,
                mapping.instrument_slug,
                mapping.family_slug,
                performer,
            )
        )
        claim_id = _value(claim, "id") if claim is not None else None
        if claim_id is None:
            raise MusicBrainzInvalidResponseError(
                "Could not locate the published instrumental claim."
            )
        await self._run(
            """
            INSERT INTO evidence_items
                (claim_id, source, source_url, original_credit, scope,
                 source_quality, verified_at)
            SELECT ?, 'musicbrainz', ?, ?, ?, ?, datetime('now')
            WHERE NOT EXISTS (
                SELECT 1 FROM evidence_items
                WHERE claim_id = ? AND source = 'musicbrainz'
                  AND ifnull(source_url, '') = ?
                  AND ifnull(original_credit, '') = ?
                  AND scope = ?
            )
            """,
            int(claim_id),
            source_url,
            original_credit,
            scope,
            credit.source_quality or "direct_relation",
            int(claim_id),
            source_url,
            original_credit,
            scope,
        )

    async def _recording_id(self, mbid: str) -> int | None:
        row = await _first(
            self._db.prepare(
                "SELECT id FROM recordings WHERE canonical_mbid = ? LIMIT 1"
            ).bind(mbid)
        )
        return int(_value(row, "id")) if row is not None else None

    async def _insert_recording(self, match: ResolvedRecording) -> int:
        await self._run(
            """
            INSERT OR IGNORE INTO recordings (title, artist, canonical_mbid)
            VALUES (?, ?, ?)
            """,
            match.title,
            match.artist,
            match.mbid,
        )
        recording_id = await self._recording_id(match.mbid)
        if recording_id is None:
            raise MusicBrainzInvalidResponseError(
                "Could not persist the resolved recording."
            )
        return recording_id

    async def _run(self, query: str, *params: object) -> None:
        statement = self._db.prepare(query).bind(*params)
        run_fn = getattr(statement, "run", None)
        if not callable(run_fn):
            raise RuntimeError("The D1 binding does not provide command execution.")
        await run_fn()


class D1EnrichmentJobRepository:
    """Tracks job lifecycle independently from Queue delivery state."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def get(self, job_key: str) -> Any:
        return await _first(
            self._db.prepare(
                """
                SELECT job_key, source_mbid, artist, title, recording_id, status,
                       generation, attempts, processing_attempts, last_error,
                       terminal_reason_code, terminal_detail
                FROM enrichment_jobs
                WHERE job_key = ?
                LIMIT 1
                """
            ).bind(job_key)
        )

    async def status(self, job_key: str) -> str | None:
        row = await self.get(job_key)
        value = _value(row, "status") if row is not None else None
        return str(value) if value is not None else None

    async def claim_processing(
        self,
        job_key: str,
        generation: int,
        message_id: str | None,
    ) -> str:
        result = await self._run(
            """
            UPDATE enrichment_jobs
            SET status = 'processing',
                attempts = attempts + 1,
                processing_attempts = processing_attempts + 1,
                last_attempt_at = datetime('now'),
                processing_started_at = datetime('now'),
                processing_lease_until = datetime('now', '+120 seconds'),
                message_id = ?,
                updated_at = datetime('now')
            WHERE job_key = ? AND generation = ?
              AND (
                status IN ('pending', 'failed')
                OR (
                    status = 'processing'
                    AND (processing_lease_until IS NULL
                         OR processing_lease_until <= datetime('now'))
                )
              )
            """,
            message_id,
            job_key,
            generation,
        )
        if _changes(result) > 0:
            return "claimed"
        current = await self.get(job_key)
        if current is None:
            return "missing"
        current_status = str(_value(current, "status") or "")
        if current_status in {"completed", "ambiguous", "terminal"}:
            return "final"
        if current_status == "processing":
            return "busy"
        return "stale"

    async def mark_processing(self, job_key: str) -> None:
        """Compatibility helper for direct callers; Queue uses claim_processing."""

        await self.claim_processing(job_key, 1, None)

    async def mark_completed(
        self, job_key: str, recording_id: int, generation: int = 1
    ) -> None:
        await self._run(
            """
            UPDATE enrichment_jobs
            SET status = 'completed', recording_id = ?, completed_at = datetime('now'),
                last_error = NULL, terminal_reason_code = NULL,
                terminal_detail = NULL, processing_lease_until = NULL,
                dispatch_status = 'none', next_dispatch_at = NULL,
                updated_at = datetime('now')
            WHERE job_key = ? AND generation = ?
            """,
            recording_id,
            job_key,
            generation,
        )

    async def mark_release_completed(self, job_key: str, generation: int = 1) -> None:
        await self._run(
            """
            UPDATE enrichment_jobs
            SET status = 'completed', completed_at = datetime('now'),
                last_error = NULL, terminal_reason_code = NULL,
                terminal_detail = NULL, processing_lease_until = NULL,
                dispatch_status = 'none', next_dispatch_at = NULL,
                updated_at = datetime('now')
            WHERE job_key = ? AND generation = ? AND job_type = 'release'
            """,
            job_key,
            generation,
        )

    async def mark_resolved_without_evidence(
        self,
        job_key: str,
        recording_id: int,
        generation: int = 1,
    ) -> None:
        await self._run(
            """
            UPDATE enrichment_jobs
            SET status = 'completed', recording_id = ?, completed_at = datetime('now'),
                last_error = NULL,
                terminal_reason_code = 'no_accepted_instrument_claims',
                terminal_detail = 'A gravação foi resolvida, mas não possui afirmações instrumentais aceitas.',
                processing_lease_until = NULL, dispatch_status = 'none',
                next_dispatch_at = NULL, updated_at = datetime('now')
            WHERE job_key = ? AND generation = ?
            """,
            recording_id,
            job_key,
            generation,
        )

    async def mark_ambiguous(
        self, job_key: str, error: str | None = None, generation: int = 1
    ) -> None:
        await self._run(
            """
            UPDATE enrichment_jobs
            SET status = 'ambiguous', last_error = ?,
                terminal_reason_code = 'ambiguous_match', terminal_detail = ?,
                processing_lease_until = NULL, dispatch_status = 'none',
                next_dispatch_at = NULL, updated_at = datetime('now')
            WHERE job_key = ? AND generation = ?
            """,
            error,
            error,
            job_key,
            generation,
        )

    async def mark_failed(
        self, job_key: str, error: str, generation: int = 1
    ) -> None:
        await self._run(
            """
            UPDATE enrichment_jobs
            SET status = 'failed', last_error = ?,
                processing_lease_until = NULL, dispatch_status = 'queued',
                updated_at = datetime('now')
            WHERE job_key = ? AND generation = ?
            """,
            error[:1000],
            job_key,
            generation,
        )

    async def mark_terminal(
        self,
        job_key: str,
        error: str,
        generation: int = 1,
        reason_code: str = "terminal_failure",
    ) -> None:
        await self._run(
            """
            UPDATE enrichment_jobs
            SET status = 'terminal', last_error = ?,
                terminal_reason_code = ?, terminal_detail = ?,
                processing_lease_until = NULL, dispatch_status = 'none',
                next_dispatch_at = NULL, updated_at = datetime('now')
            WHERE job_key = ? AND generation = ?
            """,
            error[:1000],
            reason_code,
            error[:1000],
            job_key,
            generation,
        )

    async def mark_dead_lettered(
        self, job_key: str, error: str, generation: int = 1
    ) -> None:
        await self.mark_terminal(
            job_key,
            error,
            generation,
            reason_code="retry_exhausted",
        )

    async def _run(self, query: str, *params: object) -> Any:
        statement = self._db.prepare(query).bind(*params)
        run_fn = getattr(statement, "run", None)
        if not callable(run_fn):
            raise RuntimeError("The D1 binding does not provide command execution.")
        return await run_fn()


class MusicBrainzEnricher:
    """Resolves unknown tracks and stores identity data for later catalog reads."""

    def __init__(
        self,
        resolver: MusicBrainzResolver,
        repository: D1IdentityRepository,
    ) -> None:
        self._resolver = resolver
        self._repository = repository

    async def enrich_track(self, track: Track) -> int | None:
        match = await self._resolver.resolve(track)
        if match is None:
            return None
        return await self._repository.save_enrichment(track, match)

    async def accepted_claim_count(self, recording_id: int) -> int:
        return await self._repository.accepted_claim_count(recording_id)

    async def enrich(self, history: ListeningHistory) -> ListeningHistory:
        for track in history.tracks:
            await self.enrich_track(track)
        return history


async def _first(statement: Any) -> Any:
    first_fn = getattr(statement, "first", None)
    return await first_fn() if callable(first_fn) else None


def _value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _changes(result: Any) -> int:
    meta = _value(result, "meta")
    changes = _value(meta, "changes") if meta is not None else None
    try:
        return int(changes or 0)
    except (TypeError, ValueError):
        return 0


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalize_instrument_alias(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(
        "".join(char if char.isalnum() else " " for char in without_marks).split()
    )


def _escape_search_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _artist_name(entity: Mapping[str, object]) -> str:
    artist_credit = entity.get("artist-credit")
    if not isinstance(artist_credit, list):
        return ""
    names: list[str] = []
    for credit in artist_credit:
        if not isinstance(credit, Mapping):
            continue
        name = _text(credit.get("name"))
        artist = credit.get("artist")
        if not name and isinstance(artist, Mapping):
            name = _text(artist.get("name"))
        if name:
            names.append(name)
        joinphrase = credit.get("joinphrase")
        if isinstance(joinphrase, str):
            names.append(joinphrase)
    return "".join(names)


def _artist_mbid(entity: Mapping[str, object]) -> str | None:
    artist_credit = entity.get("artist-credit")
    if not isinstance(artist_credit, list):
        return None
    for credit in artist_credit:
        if not isinstance(credit, Mapping):
            continue
        artist = credit.get("artist")
        if isinstance(artist, Mapping):
            mbid = _text(artist.get("id"))
            if mbid:
                return mbid
    return None


def _artist_matches(entity: Mapping[str, object], normalized_artist: str) -> bool:
    return _normalize(_artist_name(entity)) == normalized_artist


def _instrument_credits(entity: Mapping[str, object]) -> tuple[InstrumentCredit, ...]:
    return tuple(
        InstrumentCredit(
            instrument_mbid=observation.instrument_mbid,
            instrument_name=observation.instrument_name or "",
            performer=observation.performer,
            original_credit=observation.original_credit,
            scope=observation.scope,
            relation_type=observation.relation_type,
            production_method=observation.production_method,
            sound_nature=observation.sound_nature,
        )
        for observation in _credit_observations(entity)
        if observation.relation_type in {"instrument", "vocal", "vocals"}
        and observation.instrument_name
    )


def _credit_observations(
    entity: Mapping[str, object], *, scope: str = "recording"
) -> tuple[CreditObservation, ...]:
    raw_relations = entity.get("relations")
    if isinstance(raw_relations, Mapping):
        relations: list[object] = [
            relation
            for value in raw_relations.values()
            if isinstance(value, list)
            for relation in value
        ]
    elif isinstance(raw_relations, list):
        relations = raw_relations
    else:
        return ()

    observations: list[CreditObservation] = []
    supported_types = {
        "instrument",
        "vocal",
        "vocals",
        "programming",
        "samples",
        "sampled",
    }
    for relation in relations:
        if not isinstance(relation, Mapping):
            continue
        relation_type = _text(relation.get("type")).casefold()
        if relation_type not in supported_types:
            continue
        artist = relation.get("artist")
        performer = _text(artist.get("name")) if isinstance(artist, Mapping) else ""
        target = relation.get("instrument") or relation.get("target")
        instrument_mbid = None
        if relation_type == "instrument" and isinstance(target, Mapping):
            candidate_id = target.get("id")
            instrument_mbid = candidate_id if isinstance(candidate_id, str) else None

        names: list[str] = []
        attributes = relation.get("attributes")
        if isinstance(attributes, list):
            names.extend(value for value in attributes if isinstance(value, str))
        attribute_values = relation.get("attribute-values")
        if isinstance(attribute_values, Mapping):
            names.extend(
                value for value in attribute_values.values() if isinstance(value, str)
            )
        if relation_type == "instrument" and isinstance(target, Mapping):
            target_name = target.get("name")
            if isinstance(target_name, str):
                names.append(target_name)
        unique_names = tuple(dict.fromkeys(name.strip() for name in names if name.strip()))
        if relation_type in {"vocal", "vocals"} and not unique_names:
            unique_names = ("voice",)
        if not unique_names and relation_type in {"programming", "samples", "sampled"}:
            unique_names = (relation_type,)
        production_method = {
            "programming": "programmed",
            "samples": "sampled",
            "sampled": "sampled",
        }.get(relation_type, "performed")
        for name in unique_names or (None,):
            observations.append(
                CreditObservation(
                    relation_type=relation_type,
                    instrument_mbid=instrument_mbid,
                    instrument_name=name,
                    performer=performer or None,
                    original_credit=name,
                    scope=scope,
                    production_method=production_method,
                    sound_nature="sampled" if production_method == "sampled" else None,
                )
            )
    return tuple(observations)


def _optional_text(value: object) -> str | None:
    text = _text(value)
    return text or None


def _optional_int(value: object) -> int | None:
    try:
        parsed = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_int(value: object, fallback: int) -> int:
    parsed = _optional_int(value)
    return parsed if parsed is not None else max(1, fallback)
