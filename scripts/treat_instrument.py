#!/usr/bin/env python3
"""Treat an instrument photograph with rosa-reticle 0.1.0 and export a PNG."""

import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image

if __package__:
    from .rosa_reticle import __version__, duotone, treat_gray
    from .image_provenance import generation_record, recipe, write_json
else:
    from rosa_reticle import __version__, duotone, treat_gray
    from image_provenance import generation_record, recipe, write_json


def treat_image(image: Image.Image, *, width: int = 1200,
                shadow: str = "#000000", highlight: str = "#f29191") -> Image.Image:
    """Apply rosa-reticle, then map the result to the instrument's color pair."""
    return duotone(treat_gray(image, width), shadow=shadow, highlight=highlight)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--shadow", default="#000000")
    parser.add_argument("--highlight", default="#f29191")
    parser.add_argument("--version", action="version", version=f"rosa-reticle {__version__}")
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != ".png" or args.input.resolve() == args.output.resolve():
        parser.error("Choose a .png output distinct from the input")
    metadata_path = args.output.with_suffix(".json")
    if args.output.exists() or metadata_path.exists():
        parser.error("Output or generation record already exists; choose a new path")
    try:
        source_bytes = args.input.read_bytes()
        with Image.open(BytesIO(source_bytes)) as image:
            result = treat_image(image, width=args.width, shadow=args.shadow, highlight=args.highlight)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("xb") as output:
                result.save(output, format="PNG", optimize=True)
            record = generation_record(
                slug=None, family=None, family_tone={}, source_path=str(args.input),
                source_bytes=source_bytes, source_image=image, destination=args.output,
                output_path=str(args.output), treatment=recipe(treat_image, f"rosa-reticle-{__version__}",
                    {"width": args.width, "shadow": args.shadow, "highlight": args.highlight}))
            write_json(metadata_path, {"schema_version": 1, **record})
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Generated {args.output} ({result.width}×{result.height}; rosa-reticle {__version__})")


if __name__ == "__main__":
    main()
