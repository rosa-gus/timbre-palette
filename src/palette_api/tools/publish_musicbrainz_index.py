"""Emit an idempotent D1 publication statement for an index manifest."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from palette_api.musicbrainz_index import INDEX_SCHEMA_VERSION


def load_manifest(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("The MusicBrainz index manifest must be a JSON object.")
    required = (
        "snapshot_version",
        "index_schema_version",
        "source_url",
        "license",
        "attribution",
        "manifest_hash",
        "record_count",
        "credit_count",
    )
    missing = [key for key in required if not str(payload.get(key, "")).strip()]
    if missing:
        raise ValueError(f"Manifest fields are missing: {', '.join(missing)}")
    if payload["index_schema_version"] != INDEX_SCHEMA_VERSION:
        raise ValueError("The manifest index schema version is not supported.")
    return payload


def emit_sql(manifest: Mapping[str, object], *, status: str = "active") -> str:
    if status not in {"staging", "active"}:
        raise ValueError("status must be staging or active")
    lines: list[str] = []
    if status == "active":
        lines.append(
            "UPDATE musicbrainz_credit_index_snapshots "
            "SET status = 'superseded' WHERE status = 'active';"
        )
    lines.append(
        "INSERT INTO musicbrainz_credit_index_snapshots "
        "(snapshot_version, index_schema_version, source_url, license, attribution, "
        "manifest_hash, record_count, credit_count, status, generated_at, published_at) "
        f"VALUES ({_sql(manifest['snapshot_version'])}, "
        f"{_sql(manifest['index_schema_version'])}, "
        f"{_sql(manifest['source_url'])}, "
        f"{_sql(manifest['license'])}, "
        f"{_sql(manifest['attribution'])}, "
        f"{_sql(manifest['manifest_hash'])}, "
        f"{_integer(manifest['record_count'])}, "
        f"{_integer(manifest['credit_count'])}, "
        f"{_sql(status)}, "
        f"{_sql(manifest.get('generated_at'))}, datetime('now')) "
        "ON CONFLICT(snapshot_version) DO UPDATE SET "
        "index_schema_version = excluded.index_schema_version, "
        "source_url = excluded.source_url, license = excluded.license, "
        "attribution = excluded.attribution, manifest_hash = excluded.manifest_hash, "
        "record_count = excluded.record_count, credit_count = excluded.credit_count, "
        "status = excluded.status, generated_at = excluded.generated_at, "
        "published_at = excluded.published_at;"
    )
    return "\n".join(lines) + "\n"


def _sql(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _integer(value: object) -> str:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError("Manifest counts must be integers.") from error
    if parsed < 0:
        raise ValueError("Manifest counts cannot be negative.")
    return str(parsed)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--status", choices=("staging", "active"), default="active")
    args = parser.parse_args(argv)
    print(emit_sql(load_manifest(args.manifest), status=args.status), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
