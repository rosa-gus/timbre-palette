"""Fail-closed cost preflight for a generated MusicBrainz R2 index."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

from palette_api.musicbrainz_index import INDEX_OBJECT_PREFIX, INDEX_TRACK_PREFIX


# These are deliberately below the current R2 Standard free-tier allowances.
# They are local publication guards, not a statement of Cloudflare pricing.
DEFAULT_MAX_BYTES = 8_000_000_000
DEFAULT_MAX_RECORDS = 700_000
DEFAULT_MAX_CLASS_A_OPERATIONS = 700_000
CLASS_A_OVERHEAD_FACTOR = 1.10


def preflight_index(
    index_dir: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_class_a_operations: int = DEFAULT_MAX_CLASS_A_OPERATIONS,
) -> dict[str, object]:
    """Inspect a generated index and return a machine-readable report."""

    max_bytes = _bounded_limit(max_bytes, DEFAULT_MAX_BYTES)
    max_records = _bounded_limit(max_records, DEFAULT_MAX_RECORDS)
    max_class_a_operations = _bounded_limit(
        max_class_a_operations, DEFAULT_MAX_CLASS_A_OPERATIONS
    )
    if not index_dir.is_dir():
        raise ValueError(f"Index directory does not exist: {index_dir}")
    manifest_path = index_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Index manifest is missing: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as error:
        raise ValueError(f"Could not read index manifest: {manifest_path}") from error
    if not isinstance(manifest, Mapping):
        raise ValueError("The MusicBrainz index manifest must be a JSON object.")

    records_dir = index_dir / INDEX_OBJECT_PREFIX
    object_paths = sorted(records_dir.rglob("*.json")) if records_dir.is_dir() else []
    object_count = len(object_paths)
    tracks_dir = index_dir / INDEX_TRACK_PREFIX
    track_paths = sorted(tracks_dir.rglob("*.json")) if tracks_dir.is_dir() else []
    track_object_count = len(track_paths)
    total_object_count = object_count + track_object_count
    total_bytes = sum(
        path.stat().st_size
        for path in index_dir.rglob("*")
        if path.is_file()
    )
    estimated_class_a_operations = (
        math.ceil(total_object_count * CLASS_A_OVERHEAD_FACTOR) + 2
    )
    manifest_record_count = _nonnegative_int(manifest.get("record_count"))
    errors: list[str] = []
    if object_count != manifest_record_count:
        errors.append(
            "record_count does not match the number of recording objects "
            f"({manifest_record_count} != {object_count})"
        )
    manifest_track_count = _nonnegative_int(manifest.get("track_alias_count", 0))
    if track_object_count != manifest_track_count:
        errors.append(
            "track_alias_count does not match the number of track alias objects "
            f"({manifest_track_count} != {track_object_count})"
        )
    if total_bytes > max_bytes:
        errors.append(
            f"index size {total_bytes} bytes exceeds the {max_bytes}-byte guard"
        )
    if total_object_count > max_records:
        errors.append(
            f"total object count {total_object_count} exceeds the {max_records}-object guard"
        )
    if estimated_class_a_operations > max_class_a_operations:
        errors.append(
            "estimated Class A upload operations "
            f"{estimated_class_a_operations} exceed the {max_class_a_operations}-operation guard"
        )

    return {
        "ok": not errors,
        "index_dir": str(index_dir),
        "snapshot_version": str(manifest.get("snapshot_version", "")),
        "record_count": manifest_record_count,
        "credit_count": _nonnegative_int(manifest.get("credit_count")),
        "object_count": object_count,
        "track_object_count": track_object_count,
        "total_object_count": total_object_count,
        "total_bytes": total_bytes,
        "estimated_class_a_operations": estimated_class_a_operations,
        "limits": {
            "max_bytes": max_bytes,
            "max_records": max_records,
            "max_class_a_operations": max_class_a_operations,
        },
        "errors": errors,
    }


def _nonnegative_int(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError("Manifest counts must be non-negative integers.") from error
    if parsed < 0:
        raise ValueError("Manifest counts must be non-negative integers.")
    return parsed


def _bounded_limit(value: int, ceiling: int) -> int:
    return min(ceiling, max(0, int(value)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path, help="generated R2 index directory")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument(
        "--max-class-a-operations",
        type=int,
        default=DEFAULT_MAX_CLASS_A_OPERATIONS,
    )
    args = parser.parse_args(argv)
    try:
        report = preflight_index(
            args.index,
            max_bytes=args.max_bytes,
            max_records=args.max_records,
            max_class_a_operations=args.max_class_a_operations,
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
