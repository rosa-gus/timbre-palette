"""Instrument catalog providers and D1 repository."""

import json
from collections.abc import Mapping
from typing import Any, Protocol

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
