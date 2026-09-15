"""Read-only queue of unresolved instrumental credits for editorial review."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EditorialCandidate:
    id: int
    recording_id: int
    title: str
    artist: str
    instrument_mbid: str | None
    instrument_name: str
    performer: str | None
    original_credit: str | None
    scope: str
    source: str
    source_url: str | None
    queue_priority: int
    queue_reason: str | None
    status: str


class D1EditorialCandidateQueue:
    """Exposes pending candidates in a deterministic review order.

    The queue is catalog-oriented: it does not persist usernames or complete
    listening histories. A caller can combine this list with a temporary
    profile snapshot when it needs to rank candidates by current play weight.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def pending(self, limit: int = 100) -> tuple[EditorialCandidate, ...]:
        if limit < 1:
            raise ValueError("The editorial queue limit must be positive.")
        limit = min(limit, 1000)
        statement = self._db.prepare(
            """
            SELECT candidate.id, candidate.recording_id,
                   recording.title, recording.artist,
                   candidate.instrument_mbid, candidate.instrument_name,
                   candidate.performer, candidate.original_credit,
                   candidate.scope, candidate.source, candidate.source_url,
                   candidate.queue_priority, candidate.queue_reason,
                   candidate.status
            FROM instrument_credit_candidates AS candidate
            JOIN recordings AS recording ON recording.id = candidate.recording_id
            WHERE candidate.status = 'pending'
            ORDER BY candidate.queue_priority DESC,
                     (
                         SELECT COUNT(*)
                         FROM instrument_credit_candidates AS sibling
                         WHERE sibling.recording_id = candidate.recording_id
                           AND sibling.status = 'pending'
                     ) DESC,
                     candidate.updated_at ASC,
                     candidate.id ASC
            LIMIT ?
            """
        ).bind(limit)
        rows = await _all_rows(statement)
        return tuple(
            EditorialCandidate(
                id=int(_value(row, "id")),
                recording_id=int(_value(row, "recording_id")),
                title=str(_value(row, "title") or ""),
                artist=str(_value(row, "artist") or ""),
                instrument_mbid=_optional_text(_value(row, "instrument_mbid")),
                instrument_name=str(_value(row, "instrument_name") or ""),
                performer=_optional_text(_value(row, "performer")),
                original_credit=_optional_text(_value(row, "original_credit")),
                scope=str(_value(row, "scope") or ""),
                source=str(_value(row, "source") or ""),
                source_url=_optional_text(_value(row, "source_url")),
                queue_priority=int(_value(row, "queue_priority") or 0),
                queue_reason=_optional_text(_value(row, "queue_reason")),
                status=str(_value(row, "status") or ""),
            )
            for row in rows
        )


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


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
