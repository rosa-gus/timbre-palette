"""Validate and render idempotent SQL for the editorial catalog snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
EDITORIAL_STATUSES = {"draft", "sourced", "reviewed", "published", "deprecated"}
SOURCE_TYPES = {
    "classification",
    "museum",
    "archive",
    "foundation",
    "institution",
    "manufacturer",
    "society",
    "university",
    "library",
    "book",
    "article",
    "primary",
    "government",
    "collaborative",
    "official",
    "other",
}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load either the editor seed array or an exported schema-v1 snapshot."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        instruments = payload
    elif isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION:
        instruments = payload.get("instruments")
    else:
        raise ValueError(
            "The editorial manifest must be an array or an exported schema_version 1 object."
        )
    if not isinstance(instruments, list) or not instruments:
        raise ValueError("The editorial manifest must contain at least one resource.")
    if not all(isinstance(item, dict) for item in instruments):
        raise ValueError("Every editorial manifest entry must be an object.")
    validate_manifest(instruments)
    return instruments


def validate_manifest(resources: list[dict[str, Any]]) -> None:
    seen_slugs: set[str] = set()
    seen_blocks: set[str] = set()
    seen_sources: dict[str, str] = {}
    for index, sheet in enumerate(resources, start=1):
        resource = sheet.get("resource")
        if not isinstance(resource, dict):
            raise ValueError(f"Resource {index} must contain an object named resource.")
        slug = _required_string(resource, "slug", f"resource {index}")
        if not SLUG.fullmatch(slug):
            raise ValueError(f"Invalid resource slug: {slug!r}.")
        if slug in seen_slugs:
            raise ValueError(f"Duplicated resource slug: {slug}.")
        seen_slugs.add(slug)
        kind = resource.get("kind")
        if kind not in {"instrument", "family"}:
            raise ValueError(f"{slug}: kind must be instrument or family.")
        if kind == "instrument" and not isinstance(resource.get("family_slug"), str):
            raise ValueError(f"{slug}: instrument resources require family_slug.")
        for field in ("name", "description", "sound_production"):
            _required_string(resource, field, slug)

        sources = resource.get("sources")
        if not isinstance(sources, list):
            raise ValueError(f"{slug}: sources must be an array.")
        for source_index, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                raise ValueError(f"{slug}: source {source_index} must be an object.")
            source_id = _required_string(source, "id", f"{slug} source {source_index}")
            source_json = _canonical_json(source)
            previous = seen_sources.get(source_id)
            if previous is not None and previous != source_json:
                raise ValueError(f"Source {source_id!r} has conflicting records.")
            seen_sources[source_id] = source_json
            _validate_source(source, slug)

        source_ids = {source["id"] for source in sources}
        text_citations = sheet.get("text_citations")
        if not isinstance(text_citations, dict):
            raise ValueError(f"{slug}: text_citations must be an object.")
        for field in ("description", "sound_production"):
            citations = text_citations.get(field, [])
            if not isinstance(citations, list):
                raise ValueError(f"{slug}: {field} citations must be an array.")
            if len(citations) != len(set(citations)):
                raise ValueError(f"{slug}: duplicated citation in {field}.")
            if any(not isinstance(source_id, str) or source_id not in source_ids for source_id in citations):
                raise ValueError(f"{slug}: {field} contains an unknown source.")

        review = sheet.get("review")
        if not isinstance(review, dict):
            raise ValueError(f"{slug}: review must be an object.")
        if review.get("claim_support_verified"):
            _require_review_identity(review, slug)

        sections = resource.get("sections")
        if not isinstance(sections, list):
            raise ValueError(f"{slug}: sections must be an array.")
        for section_index, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                raise ValueError(f"{slug}: section {section_index} must be an object.")
            block_id = _required_string(section, "id", f"{slug} section {section_index}")
            if block_id in seen_blocks:
                raise ValueError(f"Duplicated editorial block id: {block_id}.")
            seen_blocks.add(block_id)
            if section.get("kind") != "curiosity":
                raise ValueError(f"{block_id}: only curiosity sections are publishable.")
            _required_string(section, "text", block_id)
            status = section.get("status")
            if status not in EDITORIAL_STATUSES:
                raise ValueError(f"{block_id}: invalid editorial status {status!r}.")
            citations = section.get("citations")
            if not isinstance(citations, list):
                raise ValueError(f"{block_id}: citations must be an array.")
            citation_ids: set[str] = set()
            for citation in citations:
                if not isinstance(citation, dict):
                    raise ValueError(f"{block_id}: every citation must be an object.")
                source_id = citation.get("source_id")
                if not isinstance(source_id, str) or source_id not in source_ids:
                    raise ValueError(f"{block_id}: citation references an unknown source.")
                if source_id in citation_ids:
                    raise ValueError(f"{block_id}: duplicated citation for {source_id}.")
                citation_ids.add(source_id)
            if status != "draft" and not citations:
                raise ValueError(f"{block_id}: non-draft content requires a citation.")
            section_review = section.get("review")
            if not isinstance(section_review, dict):
                raise ValueError(f"{block_id}: review must be an object.")
            if status in {"reviewed", "published"} and not section_review.get("claim_support_verified"):
                raise ValueError(f"{block_id}: reviewed or published content requires verified claim support.")
            if status in {"sourced", "reviewed", "published"} and section_review.get("claim_support_verified"):
                if any(not _source_by_id(sources, citation["source_id"]).get("metadata_verified", False) for citation in citations):
                    raise ValueError(f"{block_id}: every cited source must have verified metadata.")
            if status in {"reviewed", "published"}:
                _require_review_identity(section_review, block_id)

        further_reading = resource.get("further_reading")
        if not isinstance(further_reading, list):
            raise ValueError(f"{slug}: further_reading must be an array.")
        for reading_index, reading in enumerate(further_reading, start=1):
            if not isinstance(reading, dict):
                raise ValueError(f"{slug}: further reading {reading_index} must be an object.")
            _required_string(reading, "title", f"{slug} further reading {reading_index}")
            url = _required_string(reading, "url", f"{slug} further reading {reading_index}")
            if not _is_http_url(url):
                raise ValueError(f"{slug}: further reading URL must use HTTP(S).")
            status = reading.get("status", "draft")
            if status not in {"draft", "reviewed", "published", "deprecated"}:
                raise ValueError(f"{slug}: invalid further reading status {status!r}.")
            if status in {"reviewed", "published"}:
                _require_review_identity(reading, f"{slug} further reading {reading_index}")


def emit_sql(
    resources: list[dict[str, Any]],
    *,
    revision: str,
    commit_sha: str,
    published_by: str,
) -> str:
    manifest_hash = manifest_digest(resources)
    statements = [
        "-- Generated by palette_api.tools.publish_editorial; do not edit.",
        f"-- Manifest SHA-256: {manifest_hash}",
        "PRAGMA foreign_keys = ON;",
        "INSERT INTO editorial_publications "
        "(revision, manifest_hash, commit_sha, published_by, status) VALUES "
        f"({sql_literal(revision)}, {sql_literal(manifest_hash)}, {sql_literal(commit_sha)}, "
        f"{sql_literal(published_by)}, 'staging') "
        "ON CONFLICT(revision) DO UPDATE SET manifest_hash=excluded.manifest_hash, "
        "commit_sha=excluded.commit_sha, published_by=excluded.published_by, "
        "status='staging', published_at=NULL;",
    ]
    block_ids: list[str] = []
    resource_predicates: list[str] = []
    for sheet in resources:
        resource = sheet["resource"]
        slug = resource["slug"]
        kind = resource["kind"]
        subject_column = "instrument_slug" if kind == "instrument" else "family_slug"
        resource_predicates.append(f"{subject_column}={sql_literal(slug)}")
        table = "instruments" if kind == "instrument" else "instrument_families"
        family_sql = sql_literal(resource.get("family_slug")) if kind == "instrument" else None
        if kind == "instrument":
            statements.append(
                f"UPDATE {table} SET name={sql_literal(resource['name'])}, "
                f"family_slug={family_sql}, description={sql_literal(resource['description'])}, "
                f"sound_production={sql_literal(resource['sound_production'])}, "
                "updated_at=datetime('now') WHERE slug=" + sql_literal(slug) + ";"
            )
        else:
            statements.append(
                f"UPDATE {table} SET name={sql_literal(resource['name'])}, "
                f"description={sql_literal(resource['description'])}, "
                f"sound_production={sql_literal(resource['sound_production'])}, "
                "updated_at=datetime('now') WHERE slug=" + sql_literal(slug) + ";"
            )

        for source in resource["sources"]:
            statements.append(_source_upsert(source))

        review = sheet["review"]
        statements.append(
            "INSERT INTO editorial_resource_reviews "
            "(resource_type, resource_slug, source_metadata_verified, claim_support_verified, "
            "reviewed_at, reviewer, editorial_note) VALUES "
            f"({sql_literal(kind)}, {sql_literal(slug)}, "
            f"{sql_literal(bool(review.get('source_metadata_verified', False)))}, "
            f"{sql_literal(bool(review.get('claim_support_verified', False)))}, "
            f"{sql_literal(review.get('reviewed_at'))}, {sql_literal(review.get('reviewer'))}, "
            f"{sql_literal(review.get('editorial_note'))}) "
            "ON CONFLICT(resource_type, resource_slug) DO UPDATE SET "
            "source_metadata_verified=excluded.source_metadata_verified, "
            "claim_support_verified=excluded.claim_support_verified, reviewed_at=excluded.reviewed_at, "
            "reviewer=excluded.reviewer, editorial_note=excluded.editorial_note, updated_at=datetime('now');"
        )
        for field in ("description", "sound_production"):
            statements.append(
                "DELETE FROM editorial_text_citations WHERE resource_type="
                f"{sql_literal(kind)} AND resource_slug={sql_literal(slug)} "
                f"AND field={sql_literal(field)};"
            )
            for source_id in sheet["text_citations"].get(field, []):
                statements.append(
                    "INSERT INTO editorial_text_citations "
                    "(resource_type, resource_slug, field, source_id) VALUES "
                    f"({sql_literal(kind)}, {sql_literal(slug)}, {sql_literal(field)}, "
                    f"{sql_literal(source_id)}) ON CONFLICT DO NOTHING;"
                )

        statements.append(
            f"UPDATE instrument_further_reading SET status='deprecated' "
            f"WHERE {subject_column}={sql_literal(slug)};"
        )
        for position, reading in enumerate(resource["further_reading"]):
            reading_id = reading.get("id") or reading_identifier(kind, slug, reading)
            subject_values = (
                f"{sql_literal(slug)}, NULL" if kind == "instrument"
                else f"NULL, {sql_literal(slug)}"
            )
            statements.append(
                "INSERT INTO instrument_further_reading "
                "(id, instrument_slug, family_slug, title, url, publisher, position, status, reviewer, reviewed_at, editorial_note) VALUES "
                f"({sql_literal(reading_id)}, {subject_values}, {sql_literal(reading['title'])}, "
                f"{sql_literal(reading['url'])}, {sql_literal(reading.get('publisher'))}, {position}, "
                f"{sql_literal(reading.get('status', 'draft'))}, {sql_literal(reading.get('reviewer'))}, "
                f"{sql_literal(reading.get('reviewed_at'))}, {sql_literal(reading.get('editorial_note'))}) "
                "ON CONFLICT(id) DO UPDATE SET instrument_slug=excluded.instrument_slug, "
                "family_slug=excluded.family_slug, title=excluded.title, url=excluded.url, "
                "publisher=excluded.publisher, position=excluded.position, status=excluded.status, "
                "reviewer=excluded.reviewer, reviewed_at=excluded.reviewed_at, "
                "editorial_note=excluded.editorial_note;"
            )

        for section in resource["sections"]:
            block_id = section["id"]
            block_ids.append(block_id)
            section_review = section["review"]
            subject_values = (
                f"{sql_literal(slug)}, NULL" if kind == "instrument"
                else f"NULL, {sql_literal(slug)}"
            )
            statements.append(
                "INSERT INTO editorial_content_blocks "
                "(id, instrument_slug, family_slug, section_kind, text, content_type, status, "
                "claim_support_verified, reviewed_at, reviewer, editorial_note) VALUES "
                f"({sql_literal(block_id)}, {subject_values}, 'curiosity', {sql_literal(section['text'])}, "
                f"{sql_literal(section.get('content_type', 'editorial_summary'))}, {sql_literal(section['status'])}, "
                f"{sql_literal(bool(section_review.get('claim_support_verified', False)))}, "
                f"{sql_literal(section_review.get('reviewed_at'))}, {sql_literal(section_review.get('reviewer'))}, "
                f"{sql_literal(section_review.get('editorial_note'))}) "
                "ON CONFLICT(id) DO UPDATE SET instrument_slug=excluded.instrument_slug, "
                "family_slug=excluded.family_slug, section_kind=excluded.section_kind, text=excluded.text, "
                "content_type=excluded.content_type, status=excluded.status, "
                "claim_support_verified=excluded.claim_support_verified, reviewed_at=excluded.reviewed_at, "
                "reviewer=excluded.reviewer, editorial_note=excluded.editorial_note, updated_at=datetime('now');"
            )
            statements.append(
                "DELETE FROM editorial_content_citations WHERE block_id="
                f"{sql_literal(block_id)};"
            )
            for citation in section["citations"]:
                statements.append(
                    "INSERT INTO editorial_content_citations "
                    "(block_id, source_id, locator, citation_note) VALUES "
                    f"({sql_literal(block_id)}, {sql_literal(citation['source_id'])}, "
                    f"{sql_literal(citation.get('locator'))}, {sql_literal(citation.get('note'))}) "
                    "ON CONFLICT(block_id, source_id) DO UPDATE SET locator=excluded.locator, "
                    "citation_note=excluded.citation_note;"
                )

    block_list = ", ".join(sql_literal(block_id) for block_id in block_ids)
    subject_predicate = " OR ".join(resource_predicates)
    statements.append(
        "UPDATE editorial_content_blocks SET status='deprecated', claim_support_verified=0, "
        "updated_at=datetime('now') WHERE section_kind='curiosity' AND ("
        f"{subject_predicate})"
        + (f" AND id NOT IN ({block_list})" if block_ids else "")
        + ";"
    )
    statements.extend(
        [
            "UPDATE editorial_publications SET status='superseded' "
            f"WHERE status='active' AND revision <> {sql_literal(revision)};",
            "UPDATE editorial_publications SET status='active', published_at=datetime('now') "
            f"WHERE revision={sql_literal(revision)};",
        ]
    )
    return "\n".join(statements) + "\n"


def manifest_digest(resources: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json(resources).encode("utf-8")).hexdigest()


def reading_identifier(kind: str, slug: str, reading: dict[str, Any]) -> str:
    identity = f"{kind}:{slug}:{reading['title']}:{reading['url']}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"editorial-{kind}-{slug}-reading-{digest}"


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _source_upsert(source: dict[str, Any]) -> str:
    contributors = source.get("contributors", [])
    contributors_json = json.dumps(contributors, ensure_ascii=False, separators=(",", ":"))
    return (
        "INSERT INTO editorial_sources "
        "(id, title, contributors_json, publisher, publication_date, url, accessed_at, source_locator, "
        "source_type, language, license, source_note, metadata_verified, verified_at) VALUES "
        f"({sql_literal(source['id'])}, {sql_literal(source['title'])}, {sql_literal(contributors_json)}, "
        f"{sql_literal(source.get('publisher'))}, {sql_literal(source.get('publication_date'))}, "
        f"{sql_literal(source.get('url'))}, {sql_literal(source['accessed_at'])}, {sql_literal(source.get('locator'))}, "
        f"{sql_literal(source['source_type'])}, {sql_literal(source.get('language', 'en'))}, "
        f"{sql_literal(source.get('license'))}, {sql_literal(source.get('note'))}, "
        f"{sql_literal(bool(source.get('metadata_verified', False)))}, {sql_literal(source.get('verified_at'))}) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, contributors_json=excluded.contributors_json, "
        "publisher=excluded.publisher, publication_date=excluded.publication_date, url=excluded.url, "
        "accessed_at=excluded.accessed_at, source_locator=excluded.source_locator, source_type=excluded.source_type, "
        "language=excluded.language, license=excluded.license, source_note=excluded.source_note, "
        "metadata_verified=excluded.metadata_verified, verified_at=excluded.verified_at, updated_at=datetime('now');"
    )


def _validate_source(source: dict[str, Any], slug: str) -> None:
    _required_string(source, "title", f"{slug} source")
    _required_string(source, "accessed_at", f"{slug} source")
    source_type = source.get("source_type")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"{slug}: invalid source type {source_type!r}.")
    contributors = source.get("contributors", [])
    if not isinstance(contributors, list) or any(not isinstance(item, str) for item in contributors):
        raise ValueError(f"{slug}: source contributors must be an array of strings.")
    url = source.get("url")
    if url is not None and (not isinstance(url, str) or not _is_http_url(url)):
        raise ValueError(f"{slug}: source URL must use HTTP(S).")
    if source.get("metadata_verified") and not _required_string(source, "verified_at", f"{slug} source"):
        raise ValueError(f"{slug}: verified source metadata requires verified_at.")


def _require_review_identity(review: dict[str, Any], label: str) -> None:
    _required_string(review, "reviewer", label)
    _required_string(review, "reviewed_at", label)


def _required_string(container: dict[str, Any], key: str, label: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: {key} must be a non-empty string.")
    return value.strip()


def _source_by_id(sources: list[dict[str, Any]], source_id: str) -> dict[str, Any]:
    return next(source for source in sources if source["id"] == source_id)


def _is_http_url(value: str) -> bool:
    return value.startswith("https://") or value.startswith("http://")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--sql", action="store_true", help="render idempotent SQL for D1")
    parser.add_argument("--revision", default="local", help="immutable editorial publication revision")
    parser.add_argument("--commit-sha", default="local", help="source commit associated with the revision")
    parser.add_argument("--published-by", default="local", help="actor associated with the publication")
    parser.add_argument("--output", type=Path, help="write SQL to a file instead of stdout")
    args = parser.parse_args()
    resources = load_manifest(args.manifest)
    if not args.sql:
        print(f"Editorial manifest valid: {len(resources)} resources.")
        print(f"Manifest SHA-256: {manifest_digest(resources)}")
        return
    sql = emit_sql(
        resources,
        revision=args.revision,
        commit_sha=args.commit_sha,
        published_by=args.published_by,
    )
    if args.output:
        args.output.write_text(sql, encoding="utf-8")
    else:
        print(sql, end="")


if __name__ == "__main__":
    main()
