#!/usr/bin/env python3
"""rosa-reticle 03: expressive shadow transitions. EXPERIMENTAL stills only."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

if __package__:
    from .rosa_tonal import (curve_lut, duotone, photo_variants, quantized,
                             smoothstep)
    from .rosa_photo_study import text
else:
    from rosa_tonal import (curve_lut, duotone, photo_variants, quantized,
                            smoothstep)
    from rosa_photo_study import text


# Wider adjacent tonal intervals make the ordered marks visibly intentional.
# Only the transition band receives this palette, not the full photograph.
SHADOW_PALETTE = (0, 0.02, 0.065, 0.16, 0.31, 0.49, 0.68, 0.82, 1)
CENTERS = {"family_voice": (0.52, 0.50), "family_sampled_sounds": (0.21, 0.35),
           "pandeiro": (0.59, 0.57), "synthesizer": (0.39, 0.31),
           "vegetacao": (0.25, 0.32)}
LABELS = {"bayer-current": "BAYER ATUAL", "selective": "ANTERIOR / 02",
          "shadow-fine": "SOMBRAS / 1 px", "shadow-medium": "SOMBRAS / 2 px"}


def shadow_weight(base: Image.Image) -> Image.Image:
    tone = base.point([
        round(255 * smoothstep(0.025, 0.10, v / 255)
              * (1 - smoothstep(0.32, 0.58, v / 255)))
        for v in range(256)
    ])
    detail = ImageChops.difference(base, base.filter(ImageFilter.GaussianBlur(1)))
    # Retain at least 85% of the screen at detailed edges; the previous
    # study retained as little as 30%, making texture disappear there.
    protection = detail.point([
        round(255 * (1 - 0.15 * smoothstep(4, 18, v))) for v in range(256)
    ])
    return ImageChops.multiply(tone, protection)


def shadow_gray(base: Image.Image, *, pixel_scale: int = 1) -> Image.Image:
    screened = quantized(base, dual=False, palette=SHADOW_PALETTE,
                         pixel_scale=pixel_scale)
    return Image.composite(screened, base, shadow_weight(base))


def sheet(name: str, images: dict[str, Image.Image]) -> Image.Image:
    canvas = Image.new("RGB", (1536, 1020), "#080808")
    draw = ImageDraw.Draw(canvas)
    text(draw, (24, 20), f"ROSA-RETICLE / 03 / {name}", 28)
    text(draw, (24, 63), "EXPERIMENTAL / mesma base tonal de 02; mais contraste na trama das sombras", 18)
    w, h = next(iter(images.values())).size
    cx, cy = CENTERS[name]
    left, top = max(0, min(w - 180, round(cx * w) - 90)), max(0, min(h - 160, round(cy * h) - 80))
    bounds = (left, top, left + 180, top + 160)
    for i, (key, image) in enumerate(images.items()):
        x = 24 + i * 376
        text(draw, (x, 110), LABELS[key], 21)
        text(draw, (x, 143), "FOTO INTEIRA / 360 px", 15, "#aaaaaa")
        canvas.paste(image.resize((360, round(h * 360 / w)), Image.Resampling.LANCZOS), (x, 170))
        text(draw, (x, 448), "MESMO RECORTE / 2x SEM SUAVIZAR", 15, "#aaaaaa")
        canvas.paste(image.crop(bounds).resize((360, 320), Image.Resampling.NEAREST), (x, 479))
        text(draw, (x, 827), "FOTO INTEIRA / 15%", 15, "#aaaaaa")
        small = image.resize((round(w * .15), round(h * .15)), Image.Resampling.LANCZOS)
        canvas.paste(small, (x + (360 - small.width) // 2, 854))
    text(draw, (24, 994), "1 e 2 px mudam somente a escala da matriz. Sem ruido aleatorio ou caracteres.", 16, "#aaaaaa")
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("assets/treated/rosa-reticle-study-03"))
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Choose a new output directory; existing studies are preserved")
    paths = {name: Path("assets") / f"{name}.jpeg" for name in CENTERS}
    for path in paths.values():
        if not path.is_file():
            parser.error(f"Missing source: {path}")
    args.output_dir.mkdir(parents=True)
    manifest = {"experiment": "rosa-reticle", "investigation": "03", "status": "experimental",
                "width": 1200, "shadow_palette": SHADOW_PALETTE,
                "tonal_gate": {"fade_in": [.025, .10], "fade_out": [.32, .58]},
                "detail_attenuation": .15, "matrix": "Bayer 4x4", "pixel_scales": [1, 2],
                "sources": {}}
    for name, path in paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as source:
            previous = photo_variants(source)
        base = ImageEnhance.Contrast(ImageOps.grayscale(previous["original"])).enhance(1.1).point(curve_lut())
        images = {key: previous[key] for key in ("bayer-current", "selective")}
        root = args.output_dir / name
        root.mkdir()
        for scale, key in ((1, "shadow-fine"), (2, "shadow-medium")):
            images[key] = duotone(shadow_gray(base, pixel_scale=scale))
            images[key].save(root / f"{key}.png")
        duotone(base).save(root / "tonal-base.png")
        shadow_weight(base).save(root / "texture-mask.png")
        sheet(name, images).save(root / "comparison.png")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        manifest["sources"][name] = {"path": str(path), "sha256": digest, "size": base.size,
                                     "crop_center": CENTERS[name]}
        print(root / "comparison.png", flush=True)
    ramp = Image.frombytes("L", (256, 96), bytes(range(256)) * 96).resize((1024, 96), Image.Resampling.NEAREST)
    diagnostic = Image.new("RGB", (1024, 384))
    for i, image in enumerate((duotone(ramp), duotone(shadow_gray(ramp)),
                                duotone(shadow_gray(ramp, pixel_scale=2)), shadow_weight(ramp).convert("RGB"))):
        diagnostic.paste(image, (0, i * 96))
    diagnostic.save(args.output_dir / "tonal-diagnostic.png")
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
