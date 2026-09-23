#!/usr/bin/env python3
"""Render the D1 publication SQL for a serving snapshot manifest."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any


SERVING_SCHEMA_VERSION = "musicbrainz-instrument-credits-serving-v2"
DEFAULT_METHODOLOGY_VERSION = "artist-vocabulary-candidate-2"
MANIFEST_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _required_text(manifest: Mapping[str, Any], field: str) -> str:
    value = manifest.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest field {field!r} must be a non-empty string")
    return value


def _nonnegative_integer(manifest: Mapping[str, Any], field: str) -> int:
    value = manifest.get(field)
    if type(value) is not int or value < 0:
        raise ValueError(f"manifest field {field!r} must be a non-negative integer")
    return value


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_publication_sql(
    manifest: Mapping[str, Any],
    *,
    methodology_version: str = DEFAULT_METHODOLOGY_VERSION,
) -> str:
    schema_version = _required_text(manifest, "schema_version")
    if schema_version != SERVING_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported serving schema {schema_version!r}; "
            f"expected {SERVING_SCHEMA_VERSION!r}"
        )

    snapshot_version = _required_text(manifest, "snapshot_version")
    source_url = _required_text(manifest, "source_url")
    license_name = _required_text(manifest, "license")
    attribution = _required_text(manifest, "attribution")
    generated_at = _required_text(manifest, "generated_at")
    object_prefix = _required_text(manifest, "object_prefix")
    manifest_hash = _required_text(manifest, "manifest_hash").lower()
    if not MANIFEST_HASH_PATTERN.fullmatch(manifest_hash):
        raise ValueError("manifest_hash must be a lowercase SHA-256 hexadecimal digest")
    methodology_version = methodology_version.strip()
    if not methodology_version:
        raise ValueError("methodology_version must be a non-empty string")

    record_count = _nonnegative_integer(manifest, "recording_count")
    credit_count = _nonnegative_integer(manifest, "credit_count")

    values = ",\n       ".join(
        (
            _sql_string(snapshot_version),
            _sql_string(schema_version),
            _sql_string(source_url),
            _sql_string(license_name),
            _sql_string(attribution),
            _sql_string(manifest_hash),
            str(record_count),
            str(credit_count),
            "'active'",
            _sql_string(generated_at),
            "datetime('now')",
            _sql_string(object_prefix),
            _sql_string(methodology_version),
        )
    )
    return f"""-- Generated from the serving snapshot manifest.
-- Review the manifest and target database before applying this SQL remotely.
-- No explicit BEGIN/COMMIT is included; apply this as a D1 SQL file.

UPDATE musicbrainz_credit_index_snapshots
SET status = 'superseded'
WHERE status = 'active'
  AND snapshot_version <> {_sql_string(snapshot_version)};

INSERT INTO musicbrainz_credit_index_snapshots (
    snapshot_version,
    index_schema_version,
    source_url,
    license,
    attribution,
    manifest_hash,
    record_count,
    credit_count,
    status,
    generated_at,
    published_at,
    object_prefix,
    methodology_version
) VALUES (
       {values}
)
ON CONFLICT(snapshot_version) DO UPDATE SET
    index_schema_version = excluded.index_schema_version,
    source_url = excluded.source_url,
    license = excluded.license,
    attribution = excluded.attribution,
    manifest_hash = excluded.manifest_hash,
    record_count = excluded.record_count,
    credit_count = excluded.credit_count,
    status = excluded.status,
    generated_at = excluded.generated_at,
    published_at = excluded.published_at,
    object_prefix = excluded.object_prefix,
    methodology_version = excluded.methodology_version;
"""


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except OSError as error:
        raise ValueError(f"cannot read manifest {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"manifest is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("manifest root must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render idempotent D1 SQL that publishes a serving snapshot."
    )
    parser.add_argument("manifest", type=Path, help="path to serving manifest.json")
    parser.add_argument(
        "--methodology-version",
        default=DEFAULT_METHODOLOGY_VERSION,
        help=f"methodology version (default: {DEFAULT_METHODOLOGY_VERSION})",
    )
    args = parser.parse_args()
    try:
        print(
            render_publication_sql(
                load_manifest(args.manifest),
                methodology_version=args.methodology_version,
            ),
            end="",
        )
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
