#!/usr/bin/env python3
"""Validate the v1 image manifest and prepare its treated assets in a batch."""

import argparse
from io import BytesIO
import json
from pathlib import Path
from typing import Any

from PIL import Image

if __package__:
    from .deprecated_treat_instrument import treat_image as legacy_treat_image
    from .treat_instrument import treat_image as rosa_treat_image
    from .image_provenance import file_digest, generation_record, now, output_info, recipe, write_json
else:
    from deprecated_treat_instrument import treat_image as legacy_treat_image
    from treat_instrument import treat_image as rosa_treat_image
    from image_provenance import file_digest, generation_record, now, output_info, recipe, write_json


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"manifest not found: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid manifest JSON: {error}") from error
    if manifest.get("schema_version") != 1:
        raise ValueError("only image manifest schema_version 1 is supported")
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    images = manifest.get("images")
    if not isinstance(images, list):
        raise ValueError("manifest images must be a list")
    assets = {item.get("slug") for item in images if isinstance(item, dict)}
    errors: list[str] = []
    for family, entry in (manifest.get("family_images") or {}).items():
        if not isinstance(entry, dict):
            errors.append(f"family {family}: entry must be an object")
        elif entry.get("asset_id") is not None and entry.get("asset_id") not in assets:
            errors.append(f"family {family}: unknown asset {entry.get('asset_id')}")
    for instrument, asset in (manifest.get("instrument_images") or {}).items():
        if asset not in assets:
            errors.append(f"instrument {instrument}: unknown asset {asset}")
    for instrument, asset in (manifest.get("instrument_fallbacks") or {}).items():
        if asset not in assets:
            errors.append(f"fallback {instrument}: unknown asset {asset}")
    for item in images:
        if not isinstance(item, dict) or not item.get("slug"):
            errors.append("each image must have a slug")
        elif not item.get("input") or not item.get("output"):
            errors.append(f"image {item.get('slug')}: input and output are required")
    return errors


def prepare(manifest_path: Path, *, force: bool = False,
            generation_manifest: Path | None = None) -> int:
    manifest = load_manifest(manifest_path)
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    root = manifest_path.resolve().parents[1]
    version = manifest.get("treatment_version")
    if version == "rosa-reticle-0.1.0":
        treat_image = rosa_treat_image
    elif version == "duotone-bayer4-v1":
        treat_image = legacy_treat_image
    else:
        raise ValueError(f"unsupported treatment_version: {version}")
    defaults = manifest.get("defaults") if isinstance(manifest.get("defaults"), dict) else {}
    audit_path = generation_manifest or root / "assets/treated/manifest.json"
    protected = {manifest_path.resolve()}
    protected.update((root / str(item[key])).resolve() for item in manifest["images"] for key in ("input", "output"))
    if audit_path.suffix.lower() != ".json" or audit_path.resolve() in protected:
        raise ValueError("Generation manifest must be a separate .json output")
    previous = {}
    if audit_path.exists():
        try:
            document = json.loads(audit_path.read_text())
            if document.get("schema_version") != 1 or not isinstance(document.get("images"), list):
                raise ValueError("unsupported generation manifest")
            previous = {entry["output"]["path"]: entry for entry in document["images"]}
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"Invalid generation manifest {audit_path}: {error}") from error
    entries = []
    for item in manifest["images"]:
        entry = dict(previous.get(str(item["output"]), {
            "provenance": "unknown", "slug": item["slug"], "output": {"path": str(item["output"])},
        }))
        entry["run_action"] = "pending"
        entries.append(entry)
    audit = {
        "schema_version": 1, "status": "in_progress", "started_at": now(),
        "catalog": {"path": str(manifest_path), "sha256": file_digest(manifest_path)},
        "generator": {"path": "scripts/prepare_images.py", "sha256": file_digest(Path(__file__))},
        "force": force, "expected_images": len(entries), "processed_images": 0,
        "generated_images": 0, "skipped_images": 0, "images": entries,
    }
    write_json(audit_path, audit)
    count = 0
    try:
        for index, item in enumerate(manifest["images"]):
            source = root / str(item["input"])
            destination = root / str(item["output"])
            if source.resolve() == destination.resolve():
                raise ValueError("Image source and output must be distinct")
            family_tone = manifest.get("family_tones", {}).get(item.get("family_slug"), {})
            options = {**defaults, **family_tone}
            if isinstance(item.get("treatment"), dict):
                options.update(item["treatment"])
            treatment = recipe(treat_image, version, options)
            if destination.exists() and not force:
                info = {"path": str(item["output"]), **output_info(destination)}
                old = previous.get(str(item["output"]), {})
                source_hash = file_digest(source) if source.is_file() else None
                request = {"source": {"path": str(item["input"]), "sha256": source_hash},
                           "treatment": treatment, "family_slug": item.get("family_slug"),
                           "family_tone": family_tone}
                if old.get("provenance") == "recorded" and old.get("output", {}).get("sha256") == info["sha256"]:
                    entry = dict(old)
                    entry.pop("current_request", None)
                    entry["matches_current_request"] = (
                        old.get("source", {}).get("sha256") == source_hash
                        and old.get("source", {}).get("path") == str(item["input"])
                        and old.get("treatment") == treatment
                        and old.get("family_slug") == item.get("family_slug")
                        and old.get("family_tone") == family_tone)
                else:
                    entry = {"provenance": "unknown", "slug": item["slug"],
                             "output": info, "matches_current_request": None}
                if not entry["matches_current_request"]:
                    entry["current_request"] = request
                entry["run_action"] = "skipped"
                audit["skipped_images"] += 1
                print(f"skip {destination} (use --force to regenerate)")
            else:
                source_bytes = source.read_bytes()
                destination.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(BytesIO(source_bytes)) as image:
                    result = treat_image(image, **options)
                    result.save(destination, format="PNG", optimize=True)
                    entry = generation_record(
                        slug=item["slug"], family=item.get("family_slug"), family_tone=family_tone,
                        source_path=str(item["input"]), source_bytes=source_bytes, source_image=image,
                        destination=destination, output_path=str(item["output"]), treatment=treatment)
                entry.update(run_action="generated", matches_current_request=True)
                count += 1
                audit["generated_images"] = count
                print(f"generated {destination} ({result.width}×{result.height})")
            entries[index] = entry
            audit["processed_images"] += 1
            write_json(audit_path, audit)
    except Exception as error:
        audit.update(status="failed", finished_at=now(), error=str(error))
        write_json(audit_path, audit)
        raise
    audit.update(status="complete", finished_at=now())
    write_json(audit_path, audit)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("catalog/instrument-images.json"))
    parser.add_argument("--force", action="store_true", help="regenerate existing outputs")
    parser.add_argument("--generation-manifest", type=Path, help="Generation log (default: assets/treated/manifest.json)")
    args = parser.parse_args()
    try:
        count = prepare(args.manifest, force=args.force, generation_manifest=args.generation_manifest)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"prepared {count} image(s)")


if __name__ == "__main__":
    main()
