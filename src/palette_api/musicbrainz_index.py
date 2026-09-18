"""Offline MusicBrainz credit-index readers.

The full MusicBrainz database stays outside the request path.  The ETL tool
publishes one small JSON object per recording to R2.  This module contains the
runtime readers for that object layout and the short-lived D1 projection that
avoids calling MusicBrainz again for a recently enriched recording.
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


INDEX_SCHEMA_VERSION = "musicbrainz-instrument-credits-v1"
INDEX_OBJECT_PREFIX = "musicbrainz/instrument-credits/v1/recordings"
INDEX_TRACK_PREFIX = "musicbrainz/instrument-credits/v1/tracks"
DEFAULT_RECENT_INDEX_MAX_AGE_DAYS = 30
MAX_SAFE_R2_READS = 8_000_000
_MBID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class IndexedCredit:
    """One relation extracted from the MusicBrainz snapshot."""

    artist_mbid: str | None
    instrument_mbid: str | None
    instrument_name: str
    attributes: tuple[str, ...] = ()
    original_credit: str | None = None
    scope: str = "recording"
    source_url: str | None = None
    snapshot_version: str | None = None
    relation_type: str = "instrument"
    production_method: str = "performed"
    sound_nature: str | None = None
    performer: str | None = None


@dataclass(frozen=True, slots=True)
class CreditIndexEntry:
    """The compact payload stored under one recording MBID."""

    recording_mbid: str
    snapshot_version: str
    credits: tuple[IndexedCredit, ...]
    source_url: str

    @classmethod
    def from_payload(cls, payload: object, *, requested_mbid: str) -> "CreditIndexEntry":
        if not isinstance(payload, Mapping):
            raise ValueError("The MusicBrainz credit index object is not a JSON object.")
        index_schema_version = _text(payload.get("index_schema_version"))
        if index_schema_version and index_schema_version != INDEX_SCHEMA_VERSION:
            raise ValueError("The MusicBrainz credit index schema is not supported.")
        recording_mbid = _text(payload.get("recording_mbid")) or requested_mbid
        snapshot_version = _text(payload.get("snapshot_version"))
        source_url = _text(payload.get("source_url"))
        raw_credits = payload.get("credits")
        if not snapshot_version or not source_url or not isinstance(raw_credits, list):
            raise ValueError("The MusicBrainz credit index object is incomplete.")

        credits: list[IndexedCredit] = []
        for raw_credit in raw_credits:
            credit = _parse_credit(
                raw_credit,
                snapshot_version=snapshot_version,
                fallback_source_url=source_url,
            )
            if credit is not None:
                credits.append(credit)
        return cls(
            recording_mbid=recording_mbid,
            snapshot_version=snapshot_version,
            credits=tuple(credits),
            source_url=source_url,
        )

    def to_resolved_recording(self, title: str, artist: str, source_mbid: str | None):
        """Adapt the index entry to the existing D1 enrichment contract."""

        # Import lazily: musicbrainz_index is also used by the MusicBrainz
        # adapter and importing its dataclasses at module load would create a
        # circular import.
        from palette_api.musicbrainz import InstrumentCredit, ResolvedRecording

        return ResolvedRecording(
            mbid=self.recording_mbid,
            title=title,
            artist=artist,
            method="mbid_recording",
            confidence=1.0,
            source_mbid=source_mbid,
            source_entity_type="recording",
            resolver_version=INDEX_SCHEMA_VERSION,
            instrument_credits=tuple(
                InstrumentCredit(
                    instrument_mbid=credit.instrument_mbid,
                    instrument_name=credit.instrument_name,
                    performer=credit.performer,
                    performer_mbid=credit.artist_mbid,
                    original_credit=credit.original_credit,
                    scope=credit.scope,
                    source_url=credit.source_url or self.source_url,
                    source_quality="offline_snapshot",
                    relation_type=credit.relation_type,
                    production_method=credit.production_method,
                    sound_nature=credit.sound_nature,
                    snapshot_version=credit.snapshot_version,
                    attributes=credit.attributes,
                )
                for credit in self.credits
            ),
        )


class CreditIndex(Protocol):
    async def lookup(self, recording_mbid: str) -> CreditIndexEntry | None: ...


class CreditIndexBudgetError(RuntimeError):
    """Fail-closed errors raised before an R2 read is attempted."""

    reason_code = "musicbrainz_credit_index_budget_error"
    retry_after_seconds = 3600


class CreditIndexBudgetExceeded(CreditIndexBudgetError):
    reason_code = "musicbrainz_credit_index_budget_exceeded"


class CreditIndexBudgetUnavailable(CreditIndexBudgetError):
    reason_code = "musicbrainz_credit_index_budget_unavailable"


class R2ReadBudget:
    """Reserve a bounded number of R2 reads in D1 before calling R2.

    The period key is supplied by deployment configuration instead of being
    inferred from the calendar. This avoids accidentally resetting the guard
    before the Cloudflare billing period has ended.
    """

    def __init__(self, db: Any, *, period_key: str, max_reads: int) -> None:
        self._db = db
        self._period_key = period_key.strip()
        self._max_reads = min(MAX_SAFE_R2_READS, max(0, int(max_reads)))

    async def reserve(self) -> None:
        if not self._period_key:
            raise CreditIndexBudgetUnavailable(
                "MUSICBRAINZ_CREDIT_INDEX_USAGE_PERIOD is required."
            )
        if self._max_reads <= 0:
            raise CreditIndexBudgetExceeded(
                "The MusicBrainz R2 credit-index read budget is disabled."
            )
        try:
            await _run(
                self._db.prepare(
                    """
                    INSERT OR IGNORE INTO musicbrainz_credit_index_usage
                        (period_key, read_limit)
                    VALUES (?, ?)
                    """
                ).bind(self._period_key, self._max_reads)
            )
            result = await _run(
                self._db.prepare(
                    """
                    UPDATE musicbrainz_credit_index_usage
                    SET reads_reserved = reads_reserved + 1,
                        updated_at = datetime('now')
                    WHERE period_key = ?
                      AND reads_reserved < MIN(read_limit, ?)
                    """
                ).bind(self._period_key, self._max_reads)
            )
        except Exception as error:
            raise CreditIndexBudgetUnavailable(
                "The MusicBrainz R2 credit-index budget could not be reserved."
            ) from error

        if _changes(result) == 1:
            return

        try:
            row = await _first(
                self._db.prepare(
                    """
                    SELECT read_limit, reads_reserved
                    FROM musicbrainz_credit_index_usage
                    WHERE period_key = ?
                    """
                ).bind(self._period_key)
            )
        except Exception as error:
            raise CreditIndexBudgetUnavailable(
                "The MusicBrainz R2 credit-index budget status could not be read."
            ) from error
        if row is None:
            raise CreditIndexBudgetUnavailable(
                "The MusicBrainz R2 credit-index budget row is missing."
            )
        limit = _value(row, "read_limit")
        reads = _value(row, "reads_reserved")
        raise CreditIndexBudgetExceeded(
            f"The MusicBrainz R2 credit-index read budget is exhausted "
            f"({reads}/{min(int(limit or 0), self._max_reads)})."
        )


class R2CreditIndex:
    """Reads one compact recording object from an R2 binding."""

    def __init__(
        self,
        bucket: Any,
        *,
        object_prefix: str = INDEX_OBJECT_PREFIX,
        track_prefix: str = INDEX_TRACK_PREFIX,
        read_budget: R2ReadBudget | None = None,
    ) -> None:
        self._bucket = bucket
        self._object_prefix = object_prefix.rstrip("/")
        self._track_prefix = track_prefix.rstrip("/")
        self._read_budget = read_budget

    async def lookup(self, recording_mbid: str) -> CreditIndexEntry | None:
        requested_mbid = recording_mbid.strip().lower()
        if not _MBID_PATTERN.fullmatch(requested_mbid):
            return None
        entry = await self._lookup_object(
            f"{self._object_prefix}/{requested_mbid}.json",
            requested_mbid=requested_mbid,
        )
        if entry is not None:
            return entry

        # Last.fm can provide a MusicBrainz track MBID while the useful
        # relation lives on the canonical recording. Targeted ETL publishes
        # this tiny alias instead of forcing a live /recording/?query=tid:...
        # request for every track.
        alias = await self._lookup_object(
            f"{self._track_prefix}/{requested_mbid}.json",
            requested_mbid=requested_mbid,
            allow_alias=True,
        )
        if not isinstance(alias, Mapping):
            return None
        recording_mbid = _text(alias.get("recording_mbid"))
        if not recording_mbid or not _MBID_PATTERN.fullmatch(recording_mbid):
            return None
        return await self._lookup_object(
            f"{self._object_prefix}/{recording_mbid.lower()}.json",
            requested_mbid=requested_mbid,
        )

    async def _lookup_object(
        self,
        key: str,
        *,
        requested_mbid: str,
        allow_alias: bool = False,
    ) -> object | None:
        if self._read_budget is not None:
            await self._read_budget.reserve()
        obj = await self._bucket.get(key)
        if obj is None:
            return None
        json_method = getattr(obj, "json", None)
        if callable(json_method):
            payload = json_method()
            if inspect.isawaitable(payload):
                payload = await payload
        else:
            text_method = getattr(obj, "text", None)
            if not callable(text_method):
                raise ValueError("The R2 credit index object has no JSON reader.")
            payload = text_method()
            if inspect.isawaitable(payload):
                payload = await payload
            payload = json.loads(payload)
        if allow_alias and isinstance(payload, Mapping) and "credits" not in payload:
            return payload
        return CreditIndexEntry.from_payload(payload, requested_mbid=requested_mbid)


class D1RecentCreditIndex:
    """Uses recently normalized D1 evidence before consulting R2/API."""

    def __init__(
        self,
        db: Any,
        *,
        max_age_days: int = DEFAULT_RECENT_INDEX_MAX_AGE_DAYS,
    ) -> None:
        self._db = db
        self._max_age_days = max(0, int(max_age_days))

    async def lookup(self, recording_mbid: str) -> CreditIndexEntry | None:
        try:
            row = await _first(
                self._db.prepare(
                    """
                    SELECT r.id, r.canonical_mbid, es.status, es.updated_at
                    FROM recordings AS r
                    JOIN enrichment_state AS es ON es.recording_id = r.id
                    WHERE r.canonical_mbid = ?
                      AND es.status = 'completed'
                      AND es.updated_at >= datetime('now', ?)
                    LIMIT 1
                    """
                ).bind(recording_mbid, f"-{self._max_age_days} days")
            )
        except Exception:
            # The projection is optional during a rolling migration or in a
            # local database created from an older schema.
            return None
        if row is None:
            return None

        recording_id = _value(row, "id")
        canonical_mbid = _text(_value(row, "canonical_mbid")) or recording_mbid
        try:
            recording_id = int(recording_id)
        except (TypeError, ValueError):
            return None

        try:
            rows = await _all_rows(
                self._db.prepare(
                    """
                    SELECT instrument_mbid, instrument_name, performer,
                           performer_mbid, original_credit, scope, source_url,
                           snapshot_version, attributes_json
                    FROM instrument_credit_candidates
                    WHERE recording_id = ? AND source = 'musicbrainz'
                      AND status IN ('pending', 'promoted', 'reviewed')
                    ORDER BY id
                    """
                ).bind(recording_id)
            )
        except Exception:
            try:
                rows = await _all_rows(
                    self._db.prepare(
                        """
                    SELECT instrument_mbid, instrument_name, performer,
                               original_credit, scope, source_url
                        FROM instrument_credit_candidates
                        WHERE recording_id = ? AND source = 'musicbrainz'
                          AND status IN ('pending', 'promoted', 'reviewed')
                        ORDER BY id
                        """
                    ).bind(recording_id)
                )
            except Exception:
                return None

        credits: list[IndexedCredit] = []
        snapshot_versions: set[str] = set()
        source_url = f"https://musicbrainz.org/recording/{canonical_mbid}"
        for candidate in rows:
            instrument_name = _text(_value(candidate, "instrument_name"))
            if not instrument_name:
                continue
            snapshot_version = _optional_text(_value(candidate, "snapshot_version"))
            if snapshot_version:
                snapshot_versions.add(snapshot_version)
            candidate_url = _optional_text(_value(candidate, "source_url"))
            if candidate_url:
                source_url = candidate_url
            attributes = _attributes_from_json(_value(candidate, "attributes_json"))
            credits.append(
                IndexedCredit(
                    artist_mbid=_optional_text(
                        _value(candidate, "performer_mbid")
                    ),
                    instrument_mbid=_optional_text(
                        _value(candidate, "instrument_mbid")
                    ),
                    instrument_name=instrument_name,
                    original_credit=_optional_text(
                        _value(candidate, "original_credit")
                    ),
                    scope=_text(_value(candidate, "scope")) or "recording",
                    source_url=candidate_url or source_url,
                    snapshot_version=snapshot_version,
                    performer=_optional_text(_value(candidate, "performer")),
                    attributes=attributes,
                )
            )

        snapshot_version = next(iter(snapshot_versions), "d1-recent")
        return CreditIndexEntry(
            recording_mbid=canonical_mbid,
            snapshot_version=snapshot_version,
            credits=tuple(credits),
            source_url=source_url,
        )


class CompositeCreditIndex:
    """Try normalized recent D1 evidence, then the immutable R2 snapshot."""

    def __init__(self, *indexes: CreditIndex) -> None:
        self._indexes = tuple(indexes)

    async def lookup(self, recording_mbid: str) -> CreditIndexEntry | None:
        for index in self._indexes:
            try:
                entry = await index.lookup(recording_mbid)
            except CreditIndexBudgetError as error:
                _log_event(
                    "musicbrainz_credit_index_budget_blocked",
                    index_type=type(index).__name__,
                    error_type=type(error).__name__,
                    reason_code=error.reason_code,
                )
                raise
            except Exception as error:
                _log_event(
                    "musicbrainz_credit_index_error",
                    index_type=type(index).__name__,
                    error_type=type(error).__name__,
                )
                continue
            if entry is not None:
                return entry
        return None


def object_key(recording_mbid: str) -> str:
    """Return the canonical R2 key used by the offline publisher."""

    if not _MBID_PATTERN.fullmatch(recording_mbid.strip()):
        raise ValueError("recording_mbid must be a canonical MusicBrainz UUID.")
    return f"{INDEX_OBJECT_PREFIX}/{recording_mbid.lower()}.json"


def _parse_credit(
    raw_credit: object,
    *,
    snapshot_version: str,
    fallback_source_url: str,
) -> IndexedCredit | None:
    if not isinstance(raw_credit, Mapping):
        return None
    instrument_name = _text(raw_credit.get("instrument_name"))
    relation_type = _text(raw_credit.get("relation_type")) or "instrument"
    if not instrument_name:
        return None
    raw_attributes = raw_credit.get("attributes")
    attributes = tuple(
        value.strip()
        for value in raw_attributes
        if isinstance(value, str) and value.strip()
    ) if isinstance(raw_attributes, list) else ()
    scope = _text(raw_credit.get("scope")) or "recording"
    if scope not in {"recording", "track", "release"}:
        return None
    return IndexedCredit(
        artist_mbid=_optional_text(raw_credit.get("artist_mbid")),
        instrument_mbid=_optional_text(raw_credit.get("instrument_mbid")),
        instrument_name=instrument_name,
        attributes=tuple(dict.fromkeys(attributes)),
        original_credit=_optional_text(raw_credit.get("original_credit")),
        scope=scope,
        source_url=_optional_text(raw_credit.get("source_url")) or fallback_source_url,
        snapshot_version=_text(raw_credit.get("snapshot_version")) or snapshot_version,
        relation_type=relation_type,
        production_method=_text(raw_credit.get("production_method")) or "performed",
        sound_nature=_optional_text(raw_credit.get("sound_nature")),
        performer=_optional_text(raw_credit.get("performer")),
    )


async def _first(statement: Any) -> Any:
    first_fn = getattr(statement, "first", None)
    return await first_fn() if callable(first_fn) else None


async def _run(statement: Any) -> Any:
    run_fn = getattr(statement, "run", None)
    if not callable(run_fn):
        raise RuntimeError("The D1 binding does not provide command execution.")
    return await run_fn()


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


def _optional_text(value: object) -> str | None:
    text = _text(value)
    return text or None


def _changes(result: Any) -> int:
    meta = _value(result, "meta")
    changes = _value(meta, "changes") if meta is not None else None
    try:
        return int(changes or 0)
    except (TypeError, ValueError):
        return 0


def _attributes_from_json(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        return ()
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(dict.fromkeys(
        item.strip() for item in parsed if isinstance(item, str) and item.strip()
    ))


def _log_event(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))
