"""Instrument catalog providers and D1 repository."""

import json
from collections.abc import Mapping
from typing import Any, Protocol

from palette_api.domain import (
    ClaimLevel,
    Confidence,
    DataSource,
    InstrumentLayer,
    ListeningHistory,
    SoundNature,
    RecordingStatus,
    Track,
)
from palette_api.enrichment import _job_key
from palette_api.schemas import (
    EditorialCitation,
    EditorialReview,
    EditorialSection,
    EditorialSource,
    FurtherReading,
    InstrumentResource,
)


def _get_val(row: Any, key: str, default: Any = None) -> Any:
    """Extract value from row whether it is a dict, sqlite3.Row, or JS object."""
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    val = getattr(row, key, None)
    if val is not None:
        return val
    try:
        return row[key]
    except Exception:
        return default


class InstrumentCatalogProvider(Protocol):
    """Reads editorial information about instruments and families."""

    async def get(self, slug: str) -> InstrumentResource | None: ...


class D1InstrumentationProvider:
    """Enriches Last.fm tracks from published D1 instrument claims."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def enrich(self, history: ListeningHistory) -> ListeningHistory:
        recording_ids = await self._find_recording_ids(history.tracks)
        layers_by_recording = await self._get_layers_by_recording(
            tuple(recording_id for recording_id in recording_ids if recording_id is not None)
        )
        job_states = await self._get_job_states(history.tracks)
        catalog_version = await self._get_catalog_version()

        enriched_tracks = tuple(
            replace_track(
                track,
                layers_by_recording.get(recording_id, ()),
                recording_status=(
                    RecordingStatus.RESOLVED
                    if recording_id is not None
                    and layers_by_recording.get(recording_id)
                    else (
                        RecordingStatus.RESOLVED_WITHOUT_EVIDENCE
                        if recording_id is not None
                        else _recording_status_for_job(
                            job_states.get(_job_key(track))
                        )
                    )
                ),
                recording_status_detail=(
                    None
                    if recording_id is not None
                    else _job_state_detail(job_states.get(_job_key(track)))
                ),
            )
            for track, recording_id in zip(history.tracks, recording_ids, strict=True)
        )
        pending_enrichment = tuple(
            track
            for track in enriched_tracks
            if track.recording_status
            in {
                RecordingStatus.PENDING_ENRICHMENT,
                RecordingStatus.TRANSIENT_FAILURE,
            }
        )
        return ListeningHistory(
            username=history.username,
            period=history.period,
            tracks=enriched_tracks,
            history_source=history.history_source,
            instrumentation_source=DataSource.CATALOG,
            pending_enrichment=pending_enrichment,
            catalog_version=catalog_version or history.catalog_version,
        )

    async def _get_job_states(
        self,
        tracks: tuple[Track, ...],
    ) -> dict[str, dict[str, Any]]:
        keys = tuple(dict.fromkeys(_job_key(track) for track in tracks))
        if not keys:
            return {}
        placeholders = ", ".join("?" for _ in keys)
        statement = self._db.prepare(
            f"""
            SELECT job_key, status, attempts, last_error, terminal_reason_code
            FROM enrichment_jobs
            WHERE job_key IN ({placeholders})
            """
        ).bind(*keys)
        return {
            str(_get_val(row, "job_key")): {
                "status": str(_get_val(row, "status") or ""),
                "attempts": int(_get_val(row, "attempts") or 0),
                "last_error": _get_val(row, "last_error"),
                "terminal_reason_code": _get_val(row, "terminal_reason_code"),
            }
            for row in await _all_rows(statement)
            if _get_val(row, "job_key")
        }

    async def _get_catalog_version(self) -> str | None:
        try:
            publication = await _first_row(
                self._db.prepare(
                    """
                    SELECT revision
                    FROM catalog_publications
                    WHERE status = 'active'
                    ORDER BY published_at DESC, id DESC
                    LIMIT 1
                    """
                )
            )
            revision = _get_val(publication, "revision") if publication else None
            if revision:
                return str(revision)
        except Exception:
            # Databases are migrated in order; the fallback keeps fixtures and
            # a running local process readable during the migration boundary.
            pass
        statement = self._db.prepare(
            """
            SELECT version
            FROM catalog_versions
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """
        )
        row = await _first_row(statement)
        value = _get_val(row, "version") if row is not None else None
        return str(value) if value else None

    async def _find_recording_ids(
        self,
        tracks: tuple[Track, ...],
    ) -> tuple[int | None, ...]:
        """Resolve all tracks in a small number of D1 reads.

        The API normally receives at most 50 tracks. Resolving one track with
        three sequential statements would exceed the free D1 per-invocation
        query limit, so identifiers and exact title/artist fallbacks are read
        in bulk before claims are fetched.
        """
        by_mbid: dict[str, int] = {}
        mbids = sorted({track.mbid for track in tracks if track.mbid})
        if mbids:
            placeholders = ", ".join("?" for _ in mbids)
            statement = self._db.prepare(
                f"""
                SELECT external_id, recording_id
                FROM recording_identifiers
                WHERE external_id IN ({placeholders})
                  AND (
                    (source = 'lastfm' AND entity_type IN ('track', 'recording'))
                    OR (source = 'musicbrainz' AND entity_type = 'recording')
                  )
                ORDER BY id
                """
            ).bind(*mbids)
            for row in await _all_rows(statement):
                external_id = _get_val(row, "external_id")
                recording_id = _get_val(row, "recording_id")
                if external_id and recording_id is not None:
                    by_mbid.setdefault(str(external_id), int(recording_id))

        unresolved = [
            track
            for track in tracks
            if not track.mbid or track.mbid not in by_mbid
        ]
        by_title_artist: dict[tuple[str, str], set[int]] = {}
        if unresolved:
            clauses: list[str] = []
            params: list[str] = []
            for track in unresolved:
                clauses.append(
                    "(lower(trim(title)) = lower(trim(?)) "
                    "AND lower(trim(artist)) = lower(trim(?)))"
                )
                params.extend((track.title, track.artist))
            statement = self._db.prepare(
                "SELECT DISTINCT r.id, r.title, r.artist "
                "FROM recordings AS r "
                "JOIN identity_matches AS im ON im.recording_id = r.id "
                "WHERE im.confidence >= 0.9 AND ("
                + " OR ".join(clauses)
                + ")"
            ).bind(*params)
            for row in await _all_rows(statement):
                key = _normalized_track_key(
                    str(_get_val(row, "artist") or ""),
                    str(_get_val(row, "title") or ""),
                )
                recording_id = _get_val(row, "id")
                if recording_id is not None:
                    by_title_artist.setdefault(key, set()).add(int(recording_id))

        return tuple(
            by_mbid.get(track.mbid)
            if track.mbid and track.mbid in by_mbid
            else _unique_recording_id(
                by_title_artist.get(_normalized_track_key(track.artist, track.title), set())
            )
            for track in tracks
        )

    async def _get_layers_by_recording(
        self,
        recording_ids: tuple[int, ...],
    ) -> dict[int, tuple[InstrumentLayer, ...]]:
        if not recording_ids:
            return {}
        unique_ids = tuple(sorted(set(recording_ids)))
        placeholders = ", ".join("?" for _ in unique_ids)
        statement = self._db.prepare(
            f"""
            SELECT ic.instrument_slug, ic.family_slug,
                   COALESCE(i.family_slug, ic.family_slug) AS resolved_family_slug,
                   i.name AS instrument_name,
                   f.name AS family_name,
                   i.sound_nature AS instrument_nature,
                   COALESCE(i.discovery_eligible, 0) AS discovery_eligible,
                   ic.confidence_level, ic.role, ic.prominence,
                   ic.recording_id
            FROM instrument_claims AS ic
            LEFT JOIN instruments AS i ON i.slug = ic.instrument_slug
            JOIN instrument_families AS f
              ON f.slug = COALESCE(i.family_slug, ic.family_slug)
            WHERE ic.recording_id IN ({placeholders})
              AND ic.confidence_level IN ('documented', 'editorially_verified')
              AND EXISTS (
                  SELECT 1
                  FROM evidence_items AS ei
                  WHERE ei.claim_id = ic.id
                    AND ei.scope IN ('recording', 'track')
              )
            ORDER BY ic.id
            """
        ).bind(*unique_ids)
        rows = await _all_rows(statement)
        layers: dict[int, dict[str, InstrumentLayer]] = {}
        for row in rows:
            recording_id = _get_val(row, "recording_id")
            instrument_slug = _get_val(row, "instrument_slug")
            family_slug = _get_val(row, "resolved_family_slug")
            if recording_id is None or not family_slug:
                continue
            is_family_claim = instrument_slug is None
            slug = str(instrument_slug or family_slug)
            layer = InstrumentLayer(
                slug=slug,
                name=str(
                    _get_val(row, "family_name")
                    if is_family_claim
                    else _get_val(row, "instrument_name") or slug
                ),
                family_slug=str(family_slug),
                family_name=str(_get_val(row, "family_name") or family_slug),
                nature=(
                    _sound_nature(_get_val(row, "instrument_nature"))
                    if not is_family_claim
                    else None
                ),
                role=str(_get_val(row, "role") or ""),
                confidence=_confidence(_get_val(row, "confidence_level")),
                prominence=float(_get_val(row, "prominence", 1.0)),
                claim_level=(
                    ClaimLevel.FAMILY if is_family_claim else ClaimLevel.INSTRUMENT
                ),
                unexpected=(
                    not is_family_claim
                    and bool(_get_val(row, "discovery_eligible", 0))
                ),
            )
            recording_layers = layers.setdefault(int(recording_id), {})
            layer_key = f"{layer.claim_level.value}:{layer.slug}"
            existing = recording_layers.get(layer_key)
            if existing is None or layer.prominence > existing.prominence:
                recording_layers[layer_key] = layer
        return {
            recording_id: tuple(recording_layers.values())
            for recording_id, recording_layers in layers.items()
        }


def replace_track(
    track: Track,
    layers: tuple[InstrumentLayer, ...],
    *,
    recording_status: RecordingStatus | None = None,
    recording_status_detail: str | None = None,
) -> Track:
    return Track(
        title=track.title,
        artist=track.artist,
        play_count=track.play_count,
        mbid=track.mbid,
        lastfm_url=track.lastfm_url,
        layers=layers,
        recording_status=recording_status or track.recording_status,
        recording_status_detail=recording_status_detail
        if recording_status_detail is not None
        else track.recording_status_detail,
    )


async def _first_row(statement: Any) -> Any:
    first_fn = getattr(statement, "first", None)
    return await first_fn() if callable(first_fn) else None


async def _all_rows(statement: Any) -> list[Any]:
    all_fn = getattr(statement, "all", None)
    result = await all_fn() if callable(all_fn) else None
    if result is None:
        return []
    rows = getattr(result, "results", result)
    return list(rows) if rows else []


def _contributors(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return [str(value)]
    return [str(item) for item in parsed] if isinstance(parsed, list) else [str(parsed)]


def _confidence(value: Any) -> Confidence:
    if value in {"documented", "editorially_verified"}:
        return Confidence.DOCUMENTED
    return Confidence.ESTIMATED


def _sound_nature(value: Any) -> SoundNature:
    return SoundNature(str(value))


def _normalized_track_key(artist: str, title: str) -> tuple[str, str]:
    return (" ".join(artist.casefold().split()), " ".join(title.casefold().split()))


def _unique_recording_id(recording_ids: set[int]) -> int | None:
    return next(iter(recording_ids)) if len(recording_ids) == 1 else None


def _recording_status_for_job(job: dict[str, Any] | None) -> RecordingStatus:
    if job is None:
        return RecordingStatus.PENDING_ENRICHMENT
    status = job.get("status")
    if status in {"pending", "processing"}:
        return RecordingStatus.PENDING_ENRICHMENT
    if status == "failed":
        return RecordingStatus.TRANSIENT_FAILURE
    if status == "ambiguous":
        return RecordingStatus.AMBIGUOUS
    if status == "terminal":
        return RecordingStatus.TERMINAL_FAILURE
    return RecordingStatus.TERMINAL_FAILURE


def _job_state_detail(job: dict[str, Any] | None) -> str | None:
    if job is None:
        return None
    detail = job.get("last_error")
    return str(detail) if detail else None


class D1InstrumentCatalog:
    """Reads instrument and family data from Cloudflare D1."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def get(self, slug: str) -> InstrumentResource | None:
        normalized_slug = slug.strip().lower()
        normalized_slug = await self._resolve_slug_alias(normalized_slug)

        # Try instrument first
        stmt = self._db.prepare(
            "SELECT slug, name, family_slug, sound_nature, "
            "description, sound_production "
            "FROM instruments WHERE slug = ?"
        ).bind(normalized_slug)
        first_fn = getattr(stmt, "first", None)
        row = await first_fn() if callable(first_fn) else None

        kind = "instrument"
        family_slug = None

        if row is None:
            # Try family
            stmt = self._db.prepare(
                "SELECT slug, name, sound_nature, "
                "description, sound_production "
                "FROM instrument_families WHERE slug = ?"
            ).bind(normalized_slug)
            first_fn = getattr(stmt, "first", None)
            row = await first_fn() if callable(first_fn) else None

            if row is None:
                return None
            kind = "family"
        else:
            family_slug = _get_val(row, "family_slug")

        catalog_version = await self._get_catalog_version()

        # Retrieve common roles
        if kind == "instrument":
            roles_stmt = self._db.prepare(
                "SELECT role FROM instrument_common_roles WHERE instrument_slug = ? ORDER BY id"
            ).bind(normalized_slug)
        else:
            roles_stmt = self._db.prepare(
                "SELECT role FROM instrument_common_roles WHERE family_slug = ? ORDER BY id"
            ).bind(normalized_slug)

        all_fn = getattr(roles_stmt, "all", None)
        roles_result = await all_fn() if callable(all_fn) else None

        common_roles: list[str] = []
        if roles_result is not None:
            raw_results = getattr(roles_result, "results", roles_result)
            if raw_results:
                for r in raw_results:
                    role = _get_val(r, "role")
                    if role:
                        common_roles.append(str(role))

        # Retrieve related slugs
        relations_stmt = self._db.prepare(
            "SELECT target_slug FROM instrument_relations WHERE source_slug = ? ORDER BY id"
        ).bind(normalized_slug)
        rel_all_fn = getattr(relations_stmt, "all", None)
        relations_result = await rel_all_fn() if callable(rel_all_fn) else None

        related_slugs: list[str] = []
        if relations_result is not None:
            raw_rel_results = getattr(relations_result, "results", relations_result)
            if raw_rel_results:
                for r in raw_rel_results:
                    target = _get_val(r, "target_slug")
                    if target:
                        related_slugs.append(str(target))

        sections, sources = await self._get_editorial_content(normalized_slug, kind)
        further_reading = await self._get_further_reading(normalized_slug, kind)

        return InstrumentResource(
            data_source="catalog",
            catalog_version=catalog_version or "unknown",
            slug=_get_val(row, "slug"),
            name=_get_val(row, "name"),
            kind=kind,
            family_slug=family_slug,
            description=_get_val(row, "description", "") or "",
            sound_production=_get_val(row, "sound_production", "") or "",
            common_roles=common_roles,
            related_slugs=related_slugs,
            sections=sections,
            sources=sources,
            further_reading=further_reading,
        )

    async def _get_further_reading(self, slug: str, kind: str) -> list[FurtherReading]:
        subject_column = "instrument_slug" if kind == "instrument" else "family_slug"
        statement = self._db.prepare(
            f"""
            SELECT title, url, publisher
            FROM instrument_further_reading
            WHERE {subject_column} = ? AND status IN ('reviewed', 'published')
            ORDER BY position, id
            """
        ).bind(slug)
        try:
            rows = await _all_rows(statement)
        except Exception as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return [FurtherReading(
            title=str(_get_val(row, "title")),
            url=str(_get_val(row, "url")),
            publisher=_get_val(row, "publisher"),
        ) for row in rows]

    async def _get_catalog_version(self) -> str | None:
        statement = self._db.prepare(
            """
            SELECT version
            FROM catalog_versions
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """
        )
        row = await _first_row(statement)
        value = _get_val(row, "version") if row is not None else None
        return str(value) if value else None

    async def _get_editorial_content(
        self,
        slug: str,
        kind: str,
    ) -> tuple[list[EditorialSection], list[EditorialSource]]:
        """Read claims, review state, and source metadata for one catalog item.

        The editorial tables were introduced after the base taxonomy.  The
        missing-table fallback keeps a partially migrated local database
        readable while deployments apply migrations in order.
        """

        subject_column = "instrument_slug" if kind == "instrument" else "family_slug"
        statement = self._db.prepare(
            f"""
            SELECT b.id AS block_id, b.section_kind, b.text, b.content_type,
                   b.status, b.claim_support_verified, b.reviewed_at,
                   b.reviewer, b.editorial_note,
                   c.source_id, c.locator, c.citation_note,
                   s.title AS source_title, s.contributors_json,
                   s.publisher, s.publication_date, s.url,
                   s.accessed_at, s.source_locator, s.source_type,
                   s.language, s.license, s.source_note,
                   s.metadata_verified, s.verified_at
            FROM editorial_content_blocks AS b
            LEFT JOIN editorial_content_citations AS c ON c.block_id = b.id
            LEFT JOIN editorial_sources AS s ON s.id = c.source_id
            WHERE b.{subject_column} = ?
              AND b.section_kind = 'curiosity'
              AND length(trim(b.text)) > 0
              AND b.status IN ('sourced', 'reviewed', 'published')
              AND b.claim_support_verified = 1
              AND EXISTS (
                  SELECT 1
                  FROM editorial_content_citations AS eligible_citation
                  WHERE eligible_citation.block_id = b.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM editorial_content_citations AS ineligible_citation
                  LEFT JOIN editorial_sources AS ineligible_source
                    ON ineligible_source.id = ineligible_citation.source_id
                  WHERE ineligible_citation.block_id = b.id
                    AND COALESCE(ineligible_source.metadata_verified, 0) <> 1
              )
            ORDER BY b.id, c.source_id
            """
        ).bind(slug)
        try:
            rows = await _all_rows(statement)
        except Exception as exc:
            if "no such table" in str(exc).lower():
                return [], []
            raise

        blocks: dict[str, dict[str, Any]] = {}
        source_resources: dict[str, EditorialSource] = {}
        source_verified: dict[str, bool] = {}
        for row in rows:
            block_id = _get_val(row, "block_id")
            if not block_id:
                continue
            block_id = str(block_id)
            block = blocks.setdefault(
                block_id,
                {
                    "id": block_id,
                    "kind": str(_get_val(row, "section_kind") or "curiosity"),
                    "text": str(_get_val(row, "text") or ""),
                    "content_type": str(
                        _get_val(row, "content_type") or "editorial_summary"
                    ),
                    "status": str(_get_val(row, "status") or "draft"),
                    "claim_support_verified": bool(
                        _get_val(row, "claim_support_verified", 0)
                    ),
                    "reviewed_at": _get_val(row, "reviewed_at"),
                    "reviewer": _get_val(row, "reviewer"),
                    "editorial_note": _get_val(row, "editorial_note"),
                    "citations": [],
                },
            )
            source_id = _get_val(row, "source_id")
            if not source_id:
                continue
            source_id = str(source_id)
            block["citations"].append(
                EditorialCitation(
                    source_id=source_id,
                    locator=_get_val(row, "locator"),
                    note=_get_val(row, "citation_note"),
                )
            )
            source_metadata_verified = bool(_get_val(row, "metadata_verified", 0))
            source_verified[source_id] = (
                source_verified.get(source_id, True) and source_metadata_verified
            )
            if source_id not in source_resources:
                source_resources[source_id] = EditorialSource(
                    id=source_id,
                    title=str(_get_val(row, "source_title") or source_id),
                    contributors=_contributors(_get_val(row, "contributors_json")),
                    publisher=_get_val(row, "publisher"),
                    publication_date=_get_val(row, "publication_date"),
                    url=_get_val(row, "url"),
                    accessed_at=_get_val(row, "accessed_at"),
                    verified_at=_get_val(row, "verified_at"),
                    locator=_get_val(row, "source_locator"),
                    source_type=str(_get_val(row, "source_type") or "unknown"),
                    language=str(_get_val(row, "language") or "en"),
                    license=_get_val(row, "license"),
                    note=_get_val(row, "source_note"),
                    metadata_verified=source_metadata_verified,
                )

        sections = [
            EditorialSection(
                id=block["id"],
                kind=block["kind"],
                text=block["text"],
                content_type=block["content_type"],
                status=block["status"],
                review=EditorialReview(
                    source_metadata_verified=bool(block["citations"])
                    and all(
                        source_verified.get(citation.source_id, False)
                        for citation in block["citations"]
                    ),
                    claim_support_verified=block["claim_support_verified"],
                    reviewed_at=block["reviewed_at"],
                    reviewer=block["reviewer"],
                    editorial_note=block["editorial_note"],
                ),
                citations=block["citations"],
            )
            for block in blocks.values()
        ]
        return sections, list(source_resources.values())

    async def _resolve_slug_alias(self, slug: str) -> str:
        """Accept legacy/localized slugs while returning the canonical slug."""
        statement = self._db.prepare(
            """
            SELECT canonical_slug
            FROM instrument_slug_aliases
            WHERE alias_slug = ?
            UNION ALL
            SELECT canonical_slug
            FROM family_slug_aliases
            WHERE alias_slug = ?
            LIMIT 1
            """
        ).bind(slug, slug)
        row = await _first_row(statement)
        value = _get_val(row, "canonical_slug") if row is not None else None
        return str(value) if value else slug
