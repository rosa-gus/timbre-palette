#!/usr/bin/env python3
"""Prepare already treated images for static hosting; does not deploy them."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath


def publish(manifest_path: Path) -> int:
    root = manifest_path.resolve().parents[1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("only manifest v1 is supported")
    public_root = root / "public"
    prepared = []
    for item in manifest["images"]:
        if item.get("publication", {}).get("status") not in {"approved", "published"}:
            continue
        source = root / item["output"]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        variants = item["variants"]
        if len(variants) != 1:
            raise ValueError(f"{item['slug']}: one treated variant is currently supported")
        for variant in variants:
            path = variant["url"].replace("<hash>", digest)
            relative = PurePosixPath(path)
            if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "instruments":
                raise ValueError(f"invalid public path: {path}")
            variant["url"] = path
            prepared.append((source, public_root / path))
        item["publication"]["url"] = variants[0]["url"]
    # Validate all sources and paths before copying or replacing the index.
    for source, destination in prepared:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    index = root / "src" / "palette_api" / "_generated_image_catalog.json"
    index.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(prepared)} image(s) in {public_root}; generated {index.name}")
    return len(prepared)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("catalog/instrument-images.json"))
    args = parser.parse_args()
    try:
        publish(args.manifest)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
