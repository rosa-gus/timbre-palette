#!/usr/bin/env python3
"""Validate the v1 image manifest and prepare its treated assets in a batch."""

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image

from treat_instrument import treat_image


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


def prepare(manifest_path: Path, *, force: bool = False) -> int:
    manifest = load_manifest(manifest_path)
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    root = manifest_path.resolve().parents[1]
    defaults = manifest.get("defaults") if isinstance(manifest.get("defaults"), dict) else {}
    count = 0
    for item in manifest["images"]:
        source = root / str(item["input"])
        destination = root / str(item["output"])
        if destination.exists() and not force:
            print(f"skip {destination} (use --force to regenerate)")
            continue
        options = dict(defaults)
        options.update(manifest.get("family_tones", {}).get(item.get("family_slug"), {}))
        if isinstance(item.get("treatment"), dict):
            options.update(item["treatment"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            result = treat_image(image, **options)
        result.save(destination, format="PNG", optimize=True)
        count += 1
        print(f"generated {destination} ({result.width}×{result.height})")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("catalog/instrument-images.json"))
    parser.add_argument("--force", action="store_true", help="regenerate existing outputs")
    args = parser.parse_args()
    try:
        count = prepare(args.manifest, force=args.force)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"prepared {count} image(s)")


if __name__ == "__main__":
    main()
