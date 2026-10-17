#!/usr/bin/env python3
"""Still-only vinyl study: photographic duotone dissolving into localized ASCII.

Run: python3 scripts/compose_vinyl_study.py assets/vinil.mp4 output.png
Uses the first frame for video inputs. Does not encode or modify videos.
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

from deprecated_treat_instrument import treat_image


def smoothstep(start: float, end: float, value: float) -> float:
    value = max(0.0, min(1.0, (value - start) / (end - start)))
    return value * value * (3 - 2 * value)


def compose(image: Image.Image) -> Image.Image:
    # More tonal gradations and gentler contrast keep the dark record's grooves,
    # needle, and surrounding objects recognizable before adding the treatment.
    treatment = dict(width=1920, levels=64, contrast=1.05, gamma=1.45)
    photo = treat_image(image, strength=0, **treatment)
    ascii_image = treat_image(
        image, pattern="ascii", ascii_cell=32, strength=1, **treatment,
    )
    width, height = photo.size
    horizontal = Image.new("L", (width, 1))
    horizontal.putdata([
        round(255 * (1 - smoothstep(0.16, 0.68, x / width)))
        for x in range(width)
    ])
    vertical = Image.new("L", (1, height))
    vertical.putdata([
        round(255 * (1 - smoothstep(0.20, 0.55, y / height)))
        for y in range(height)
    ])
    # Deliberate art direction for this shot: only the upper-left environment
    # dissolves. The lower turntable and the right-hand needle stay photographic.
    mask = ImageChops.multiply(
        horizontal.resize(photo.size), vertical.resize(photo.size),
    )
    return Image.composite(ascii_image, photo, mask)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".png":
        parser.error("Output must be a PNG still")
    if args.output.exists() or args.input.resolve() == args.output.resolve():
        parser.error("Choose a new output distinct from the input")
    try:
        with tempfile.TemporaryDirectory(prefix="vinyl-still-") as directory:
            source = args.input
            if source.suffix.lower() in (".mp4", ".webm", ".mov", ".mkv"):
                frame = Path(directory) / "first.png"
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-i", str(source.resolve()), "-map", "0:v:0", "-frames:v", "1",
                    str(frame),
                ], check=True)
                source = frame
            with Image.open(source) as image:
                result = compose(image)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("xb") as output:
                result.save(output, format="PNG", optimize=True)
            print(f"Generated {args.output} ({result.width}×{result.height})")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
