#!/usr/bin/env python3
"""Generate procedural calibration images for the EXPERIMENTAL reticle v1.

Only still images. No source photography, home-page changes, or video encoding.
"""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

if __package__:
    from .deprecated_treat_instrument import treat_image
else:
    from deprecated_treat_instrument import treat_image


def gradient_source(width: int = 512, height: int = 128) -> Image.Image:
    row = bytes(round(255 * x / (width - 1)) for x in range(width))
    return Image.frombytes("L", (width, height), row * height)


def sphere_source(size: int = 512) -> Image.Image:
    """Analytic diffuse sphere with a small broad specular highlight."""
    work = size * 2
    light = (-0.48, -0.50, 0.72)
    norm = math.sqrt(sum(value * value for value in light))
    light = tuple(value / norm for value in light)
    half = (light[0], light[1], light[2] + 1)
    norm = math.sqrt(sum(value * value for value in half))
    half = tuple(value / norm for value in half)
    pixels = bytearray(work * work)
    for y in range(work):
        ny = (y / work - 0.49) / 0.39
        for x in range(work):
            nx = (x / work - 0.5) / 0.39
            radius = nx * nx + ny * ny
            value = 0.0
            if radius <= 1:
                normal = (nx, ny, math.sqrt(1 - radius))
                diffuse = max(0.0, sum(a * b for a, b in zip(normal, light)))
                specular = max(0.0, sum(a * b for a, b in zip(normal, half))) ** 48
                value = 0.10 + 0.78 * diffuse + 0.07 * specular
            pixels[y * work + x] = round(255 * value)
    return Image.frombytes("L", (work, work), bytes(pixels)).resize(
        (size, size), Image.Resampling.LANCZOS,
    )


def render(source: Image.Image, pattern: str, *, cell: int = 16,
           highlight: str = "#f29191", levels: int = 8) -> Image.Image:
    reference = pattern == "plain"
    return treat_image(
        source, pattern="bayer" if reference else pattern, reticle_cell=cell,
        levels=256 if reference else levels, strength=0 if reference else 1,
        contrast=1, gamma=1, width=source.width, highlight=highlight,
    )


def calibration(gradient: Image.Image, sphere: Image.Image) -> Image.Image:
    panel, gutter, margin = 352, 24, 32
    width = panel * 4 + gutter * 3 + margin * 2
    sheet = Image.new("RGB", (width, 1124), "#080808")
    draw = ImageDraw.Draw(sheet)
    title = ImageFont.load_default(size=30)
    label = ImageFont.load_default(size=21)
    small = ImageFont.load_default(size=16)
    draw.text((margin, 22), "TIMBRE / RETICULA EXPERIMENTAL V1", font=title, fill="#eeeeee")
    draw.text((margin, 64), "Mesmo sinal de entrada. Sem alteracao de contraste ou gama.",
              font=small, fill="#aaaaaa")
    variants = (("REFERENCIA CONTINUA", "plain", 12, 256),
                ("BAYER 4x4", "bayer", 12, 8),
                ("RETICULA / 12 px", "reticle", 12, 8),
                ("RETICULA / 12 px", "reticle", 12, 16))
    ramp = gradient.resize((panel, 88), Image.Resampling.LANCZOS)
    ball = sphere.resize((panel, panel), Image.Resampling.LANCZOS)
    for index, (name, pattern, cell, levels) in enumerate(variants):
        x = margin + index * (panel + gutter)
        draw.text((x, 110), name, font=label, fill="#eeeeee")
        draw.text((x, 141), "256 tons" if pattern == "plain" else f"{levels} tons / intensidade 1",
                  font=small, fill="#aaaaaa")
        sheet.paste(render(ramp, pattern, cell=cell, levels=levels, highlight="#ffffff"), (x, 176))
        draw.text((x, 288), "VOLUME / NEUTRO", font=small, fill="#aaaaaa")
        sheet.paste(render(ball, pattern, cell=cell, levels=levels, highlight="#ffffff"), (x, 320))
        draw.text((x, 696), "VOLUME / DUOTONE", font=small, fill="#aaaaaa")
        sheet.paste(render(ball, pattern, cell=cell, levels=levels), (x, 728))
    draw.text((margin, 1094), "Estudo de calibracao. Nao e um tratamento final aprovado.",
              font=small, fill="#aaaaaa")
    return sheet


def structure_sheet() -> Image.Image:
    sheet = Image.new("RGB", (1376, 356), "#080808")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=21)
    draw.text((24, 16), "ESTRUTURA / 2 CORES / CELULA 16 px / AMPLIACAO 4x", font=font, fill="#eeeeee")
    for index, coverage in enumerate((0.10, 0.25, 0.50, 0.75, 0.90)):
        source = Image.new("L", (64, 64), round(255 * coverage))
        treated = render(source, "reticle", cell=16, levels=2)
        x = 24 + index * 268
        draw.text((x, 57), f"{coverage:.0%} de cobertura", font=font, fill="#aaaaaa")
        sheet.paste(treated.resize((256, 256), Image.Resampling.NEAREST), (x, 90))
    return sheet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("assets/treated/reticle-experimental-v1"))
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Choose a new output directory; existing studies are preserved")
    gradient, sphere = gradient_source(), sphere_source()
    images = {
        "gradient-source.png": gradient,
        "sphere-source.png": sphere,
        "calibration.png": calibration(gradient, sphere),
        "structure.png": structure_sheet(),
        "sphere-duotone.png": render(sphere, "reticle", cell=12, levels=16),
    }
    args.output_dir.mkdir(parents=True)
    for name, image in images.items():
        image.save(args.output_dir / name, optimize=True)
        print(args.output_dir / name)


if __name__ == "__main__":
    main()
