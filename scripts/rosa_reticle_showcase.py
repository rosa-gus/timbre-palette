#!/usr/bin/env python3
"""Build the documented rosa-reticle showcase from project photographs."""

import argparse
import math
from pathlib import Path
import platform

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps, __version__ as pillow_version

if __package__:
    from .rosa_reticle import (BAYER_4, CURVE, SHADOW_PALETTE, __version__,
                              curve_lut, duotone, pairs_gray, prepare_source,
                              quantized, treat_gray)
    from .image_provenance import file_digest, write_json
else:
    from rosa_reticle import (BAYER_4, CURVE, SHADOW_PALETTE, __version__,
                             curve_lut, duotone, pairs_gray, prepare_source,
                             quantized, treat_gray)
    from image_provenance import file_digest, write_json


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1424, 2072
MARGIN, PANEL, GAP = 40, 432, 24
BG, TEXT, MUTED, PINK = "#080808", "#eeeeee", "#aaaaaa", "#f29191"
SOURCES = {
    "voice": {"name": "family_voice.jpeg", "center": (.52, .50), "crop": (216, 168)},
    "synth": {"name": "synthesizer.jpeg", "center": (.39, .31), "crop": (216, 128)},
}


def bayer_reference(gray: Image.Image) -> Image.Image:
    """Standard 4x4 ordered quantization: 8 uniform tones, strength .35."""
    # Quantized intensities must round, matching the sRGB palette mapping.
    tables = [bytes(round(index * 255 / 7) for index in table) for table in (
        [max(0, min(7, math.floor(value / 255 * 7 + ((rank + .5) / 16 - .5) * .35 + .5)))
         for value in range(256)] for rank in range(16))]
    data = gray.tobytes()
    result = bytearray(len(data))
    for y in range(gray.height):
        start, end = y * gray.width, (y + 1) * gray.width
        for x in range(min(4, gray.width)):
            result[start + x:end:4] = data[start + x:end:4].translate(tables[BAYER_4[y % 4][x]])
    return Image.frombytes("L", gray.size, bytes(result))


def photo_variants(image: Image.Image) -> tuple[dict[str, Image.Image], tuple[int, int]]:
    rgb = prepare_source(image, width=1200)
    gray = ImageEnhance.Contrast(ImageOps.grayscale(rgb)).enhance(1.1)
    # Colorize after grayscale quantization: every column uses the exact same
    # black/pink mapping, including the reference's palette stops.
    return {"continuous": duotone(gray), "bayer": duotone(bayer_reference(gray)),
            "rosa": duotone(treat_gray(rgb))}, rgb.size


def crop_bounds(size: tuple[int, int], center: tuple[float, float],
                crop: tuple[int, int]) -> tuple[int, int, int, int]:
    w, h = size
    cw, ch = crop
    if w < cw or h < ch:
        raise ValueError("Showcase sources must be large enough for native detail crops")
    x = max(0, min(w-cw, round(w*center[0])-cw//2))
    y = max(0, min(h-ch, round(h*center[1])-ch//2))
    return x, y, x+cw, y+ch


def label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
          size: int = 18, fill: str = TEXT, max_width: int | None = None) -> None:
    font = ImageFont.load_default(size=size)
    if max_width is not None and draw.textbbox((0, 0), text, font=font)[2] > max_width:
        raise ValueError(f"Showcase label exceeds its column: {text}")
    draw.text(xy, text, font=font, fill=fill)


def columns(draw: ImageDraw.ImageDraw, y: int, labels: tuple[str, ...]) -> None:
    for i, text in enumerate(labels):
        label(draw, (MARGIN+i*(PANEL+GAP), y), text, 22, max_width=PANEL)


def section(draw: ImageDraw.ImageDraw, y: int, title: str, caption: str) -> None:
    draw.line((MARGIN, y, WIDTH-MARGIN, y), fill="#3b3030")
    label(draw, (MARGIN, y+15), title, 26)
    label(draw, (MARGIN, y+57), caption, 18, MUTED, WIDTH-2*MARGIN)


def render(photos: dict) -> Image.Image:
    board = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(board)
    label(draw, (MARGIN, 24), "TIMBRE PALETTE", 18, PINK)
    brand_width = draw.textlength("TIMBRE PALETTE", font=ImageFont.load_default(size=18))
    label(draw, (MARGIN+brand_width, 24), f" / IMAGE TREATMENT / v{__version__}", 18, MUTED)
    label(draw, (MARGIN, 58), "rosa-reticle", 60)
    label(draw, (MARGIN, 141), "A fine tonal screen: quiet blacks, textured shadows, continuous light. Inspired by Bayer.", 24)
    label(draw, (MARGIN, 180), "Same framing, 1200 px processing and #000000 / #f29191 colors in all photographic columns.", 18, MUTED)
    columns(draw, 226, ("CONTINUOUS DUOTONE", "BAYER 4x4", "ROSA-RETICLE"))
    for i, image in enumerate(photos["voice"]["variants"].values()):
        thumb = image.resize((PANEL, round(image.height*PANEL/image.width)), Image.Resampling.LANCZOS)
        board.paste(thumb, (MARGIN+i*(PANEL+GAP), 267))
    label(draw, (MARGIN, 577), "The photo comparison includes rosa's tonal curve. The lower control holds the curve constant.", 18, MUTED)

    section(draw, 623, "SHADOWS AND VOLUME", "Same face detail / 2x enlargement without smoothing")
    for i, image in enumerate(photos["voice"]["variants"].values()):
        board.paste(image.crop(photos["voice"]["bounds"]).resize((432, 336), Image.Resampling.NEAREST),
                    (MARGIN+i*(PANEL+GAP), 724))
    for i, caption in enumerate(("Continuous source gradients.", "Uniform tonal steps and a regular screen.", "Tonal curve, shadow masks and sparse pairs.")):
        label(draw, (MARGIN+i*(PANEL+GAP), 1075), caption, 18, MUTED, PANEL)

    section(draw, 1130, "SURFACES AND CONTOURS", "Same synthesizer detail / 2x enlargement without smoothing")
    for i, image in enumerate(photos["synth"]["variants"].values()):
        board.paste(image.crop(photos["synth"]["bounds"]).resize((432, 256), Image.Resampling.NEAREST),
                    (MARGIN+i*(PANEL+GAP), 1231))

    section(draw, 1540, "TONAL TRANSITIONS", "Shared curve; both screens use 9 stops. Bayer is unmasked; rosa uses tonal and detail masks.")
    columns(draw, 1642, ("CURVED BASE", "FINE BAYER / UNMASKED", "ROSA-RETICLE"))
    ramp = Image.frombytes("L", (PANEL, 88), bytes(round(x*255/(PANEL-1)) for x in range(PANEL))*88)
    base = ramp.point(curve_lut())
    controls = (duotone(base), duotone(quantized(base)), duotone(pairs_gray(base)))
    for i, image in enumerate(controls):
        board.paste(image, (MARGIN+i*(PANEL+GAP), 1688))
        board.paste(image.crop((8, 0, 224, 48)).resize((432, 96), Image.Resampling.NEAREST),
                    (MARGIN+i*(PANEL+GAP), 1820))
    label(draw, (MARGIN, 1789), "Shadow-to-mid-tone segment below / 2x, no smoothing", 16, MUTED)
    label(draw, (MARGIN, 1935), "PHOTO REFERENCE / Bayer: 8 uniform tones, strength .35, contrast 1.1, gamma 1. Rosa: versioned 0.1.0 pipeline.", 17, MUTED)
    label(draw, (MARGIN, 1970), "Photographs: Josh Rocklage (voice) / Anton Shuvalov (synthesizer) / Unsplash License.", 17, MUTED)
    label(draw, (MARGIN, 2002), "Each method expresses a different treatment. Enlarged crops expose structure; reduced views average fine marks.", 17, MUTED)
    return board


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, default=ROOT/"assets")
    parser.add_argument("--output", type=Path, default=ROOT/"docs/images/rosa-reticle-showcase.png")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    metadata_path = args.output.with_suffix(".json")
    if args.output.suffix.lower() != ".png":
        parser.error("Output must be a PNG")
    if not args.force and (args.output.exists() or metadata_path.exists()):
        parser.error("Showcase output exists; use --force to regenerate it")
    import json
    catalog = json.loads((ROOT/"catalog/instrument-images.json").read_text())
    credits = {Path(item["input"]).name: item["credit"] for item in catalog["images"]}
    photos, sources = {}, {}
    for key, config in SOURCES.items():
        path = args.assets_dir/config["name"]
        before = file_digest(path)
        with Image.open(path) as source:
            variants, size = photo_variants(source)
        bounds = crop_bounds(size, config["center"], config["crop"])
        photos[key] = {"variants": variants, "bounds": bounds}
        sources[key] = {"file": config["name"], "sha256": before, "prepared_size": size,
                        "detail_bounds": bounds, "credit": credits[config["name"]]}
        if file_digest(path) != before:
            raise ValueError(f"Source changed during generation: {path.name}")
    result = render(photos)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.save(args.output, optimize=True)
    write_json(metadata_path, {
        "schema_version": 1, "algorithm": "rosa-reticle", "algorithm_version": __version__,
        "runtime": {"python": platform.python_version(), "pillow": pillow_version},
        "sources": sources, "common": {"processing_width": 1200, "shadow": "#000000", "highlight": "#f29191"},
        "photo_reference": {"matrix": BAYER_4, "levels": 8, "strength": .35, "contrast": 1.1, "gamma": 1},
        "tonal_control": {"curve": CURVE, "palette": SHADOW_PALETTE,
                          "bayer": "unmasked", "rosa": "pairs_gray; tonal and detail masks"},
        "implementation": {"showcase_sha256": file_digest(Path(__file__)), "engine_sha256": file_digest(ROOT/"scripts/rosa_reticle.py")},
        "output": {"name": args.output.name, "dimensions": result.size, "sha256": file_digest(args.output)},
    })
    print(f"Generated {args.output} ({result.width}x{result.height})")


if __name__ == "__main__":
    main()
