#!/usr/bin/env python3
"""rosa-reticle / photographic investigation 02 — EXPERIMENTAL stills only."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

if __package__:
    from .rosa_tonal import CURVE, PALETTE, photo_variants
else:
    from rosa_tonal import CURVE, PALETTE, photo_variants


SOURCES = {
    "family_voice": (0.52, 0.48),
    "family_sampled_sounds": (0.21, 0.33),
    "pandeiro": (0.55, 0.49),
    "synthesizer": (0.53, 0.63),
    "vegetacao": (0.53, 0.29),
}
VARIANTS = ("original", "bayer-current", "tonal-base", "selective", "dual")
LABELS = {"original": "ORIGINAL", "bayer-current": "BAYER ATUAL",
          "tonal-base": "BASE TONAL", "selective": "BAYER SELETIVO", "dual": "TRAMA DUPLA"}


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str,
         size: int = 18, fill: str = "#dddddd") -> None:
    draw.text(xy, value, font=ImageFont.load_default(size=size), fill=fill)


def crop_bounds(size: tuple[int, int], center: tuple[float, float]) -> tuple[int, int, int, int]:
    width, height = size
    left = max(0, min(width - 160, round(center[0] * width) - 80))
    top = max(0, min(height - 120, round(center[1] * height) - 60))
    return left, top, left + 160, top + 120


def review_sheet(name: str, variants: dict, center: tuple[float, float]) -> Image.Image:
    panel, gap, margin = 320, 20, 32
    sheet = Image.new("RGB", (panel * 5 + gap * 4 + margin * 2, 960), "#080808")
    draw = ImageDraw.Draw(sheet)
    text(draw, (margin, 22), f"ROSA-RETICLE / 02 / {name}", 28)
    text(draw, (margin, 66), "Experimental | mesmos enquadramentos | duotone rosa comum a todas as versoes tratadas", 17, "#aaaaaa")
    bounds = crop_bounds(variants["original"].size, center)
    for index, key in enumerate(VARIANTS):
        x = margin + index * (panel + gap)
        image = variants[key]
        text(draw, (x, 120), LABELS[key], 22)
        text(draw, (x, 153), "FOTO INTEIRA / 320 px", 15, "#aaaaaa")
        thumb = image.resize((panel, round(image.height * panel / image.width)), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x, 185))
        text(draw, (x, 441), "MESMO DETALHE / AMPLIACAO 2x", 15, "#aaaaaa")
        sheet.paste(image.crop(bounds).resize((320, 240), Image.Resampling.NEAREST), (x, 475))
        text(draw, (x, 753), "FOTO INTEIRA / 10%", 15, "#aaaaaa")
        far_size = (round(image.width * 0.1), round(image.height * 0.1))
        far = image.resize(far_size, Image.Resampling.LANCZOS)
        sheet.paste(far, (x + (panel - far.width) // 2, 790))
    text(draw, (margin, 920), "Base tonal isola a curva. Seletivo e dupla compartilham curva, paleta e mascara; somente a trama muda.",
         17, "#aaaaaa")
    return sheet


def overview(all_variants: dict) -> Image.Image:
    panel, gap, margin = 256, 16, 24
    sheet = Image.new("RGB", (panel * 5 + gap * 4 + margin * 2, 1244), "#080808")
    draw = ImageDraw.Draw(sheet)
    text(draw, (margin, 22), "ROSA-RETICLE / INVESTIGACAO FOTOGRAFICA 02", 28)
    text(draw, (margin, 65), "Bayer como referencia. Curva tonal, textura seletiva e trama em duas escalas. Experimental.", 17, "#aaaaaa")
    for index, key in enumerate(VARIANTS):
        text(draw, (margin + index * (panel + gap), 112), LABELS[key], 18)
    for row, (name, variants) in enumerate(all_variants.items()):
        y = 157 + row * 212
        text(draw, (margin, y), f"{name}.jpeg", 17, "#aaaaaa")
        for index, key in enumerate(VARIANTS):
            image = variants[key]
            target = (panel, round(image.height * panel / image.width))
            sheet.paste(image.resize(target, Image.Resampling.LANCZOS),
                        (margin + index * (panel + gap), y + 30))
    return sheet


def distance_metrics(variants: dict) -> dict:
    report = {}
    for key in ("tonal-base", "selective", "dual"):
        report[key] = {}
        for reference_key in ("bayer-current", "tonal-base"):
            values = {}
            for scale in (1, 0.5, 0.25, 0.1):
                image = variants[key]
                size = (round(image.width * scale), round(image.height * scale))
                a = image.resize(size, Image.Resampling.LANCZOS)
                b = variants[reference_key].resize(size, Image.Resampling.LANCZOS)
                stat = ImageStat.Stat(ImageChops.difference(a, b))
                values[str(scale)] = round(math.sqrt(sum(value**2 for value in stat.rms) / 3), 4)
            report[key][f"rms_rgb_vs_{reference_key}"] = values
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, default=Path("assets"))
    parser.add_argument("--output-dir", type=Path, default=Path("assets/treated/rosa-reticle-study-02"))
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Choose a new output directory; existing studies are preserved")
    for name in SOURCES:
        if not (args.assets_dir / f"{name}.jpeg").is_file():
            parser.error(f"Missing source: {name}.jpeg")
    args.output_dir.mkdir(parents=True)
    all_variants, sources = {}, {}
    for name, center in SOURCES.items():
        path = args.assets_dir / f"{name}.jpeg"
        original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as image:
            variants = photo_variants(image)
        root = args.output_dir / name
        root.mkdir()
        for key in VARIANTS[1:]:
            variants[key].save(root / f"{key}.png", optimize=True)
        review_sheet(name, variants, center).save(root / "study.png", optimize=True)
        sources[name] = {
            "source": str(path), "sha256": original_hash,
            "output_size": list(variants["original"].size),
            "detail_crop": list(crop_bounds(variants["original"].size, center)),
            "distance_metrics": distance_metrics(variants),
        }
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
        all_variants[name] = variants
        print(f"Generated {root}", flush=True)
    overview(all_variants).save(args.output_dir / "comparison.png", optimize=True)
    manifest = {
        "experiment": "rosa-reticle", "investigation": "02", "status": "experimental",
        "method": "Bayer-derived selective quantization residual over a continuous tonal base",
        "shadow": "#000000", "highlight": "#f29191", "width": 1200,
        "contrast": 1.1, "curve": CURVE, "quantization_stops": PALETTE,
        "baseline": {"pattern": "Bayer 4x4", "levels": 8, "strength": 0.35, "gamma": 1},
        "distance_metric_note": "RGB RMS is difference, not perceptual quality. Same-grade residual and full treatment difference are reported separately.",
        "sources": sources,
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(args.output_dir / "comparison.png")


if __name__ == "__main__":
    main()
