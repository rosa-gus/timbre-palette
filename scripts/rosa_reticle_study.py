#!/usr/bin/env python3
"""rosa-reticle / investigation 01 — EXPERIMENTAL still-only comparison.

Three irregular, fixed screens, controlled palette/scale/seed, and native,
magnified, 50%, and 25% views. Creates no video and does not change the home.
"""

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

if __package__:
    from .reticle_study import gradient_source, sphere_source
    from .deprecated_rosa_reticle import DEFAULT_SEED, FAMILIES
    from .deprecated_treat_instrument import treat_image
else:
    from reticle_study import gradient_source, sphere_source
    from deprecated_rosa_reticle import DEFAULT_SEED, FAMILIES
    from deprecated_treat_instrument import treat_image


SCALE, LEVELS = 16, 16
PANEL, GAP, MARGIN = 352, 24, 32
WIDTH = PANEL * 4 + GAP * 3 + MARGIN * 2
LABELS = {"plain": "CONTINUO", "bayer": "BAYER FINO / CONTROLE",
          "islands": "ILHAS", "fibers": "FIBRAS", "mineral": "FACETAS"}


def render(source: Image.Image, family: str, levels: int = LEVELS) -> Image.Image:
    plain = family == "plain"
    control = family in ("plain", "bayer")
    return treat_image(
        source, pattern="bayer" if control else "rosa-reticle",
        levels=256 if plain else levels, strength=0 if plain else 1,
        rosa_family="islands" if control else family, rosa_scale=SCALE,
        rosa_seed=DEFAULT_SEED, contrast=1, gamma=1, width=source.width,
    )


def canvas(height: int, heading: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, height), "#080808")
    draw = ImageDraw.Draw(image)
    draw.text((MARGIN, 22), heading, font=ImageFont.load_default(size=30), fill="#eeeeee")
    draw.text((MARGIN, 65), subtitle, font=ImageFont.load_default(size=17), fill="#aaaaaa")
    return image, draw


def column_label(draw: ImageDraw.ImageDraw, x: int, family: str) -> None:
    draw.text((x, 111), LABELS[family], font=ImageFont.load_default(size=23), fill="#eeeeee")
    subtitle = "256 tons / referencia" if family == "plain" else f"{LEVELS} tons / escala nominal {SCALE} px"
    if family == "bayer":
        subtitle = f"{LEVELS} tons / matriz 4x4 / intensidade 1"
    draw.text((x, 144), subtitle, font=ImageFont.load_default(size=16), fill="#aaaaaa")


def families_sheet(source: Image.Image) -> Image.Image:
    sheet, draw = canvas(824, "ROSA-RETICLE / INVESTIGACAO 01",
                         f"Experimental | mesma paleta, escala e seed {DEFAULT_SEED} | sem ajustes tonais")
    small = ImageFont.load_default(size=16)
    ramp = gradient_source(PANEL, 72)
    field = Image.new("L", (PANEL, 72), round(255 * 0.35))
    for index, family in enumerate(("plain", *FAMILIES)):
        x = MARGIN + index * (PANEL + GAP)
        column_label(draw, x, family)
        sheet.paste(render(ramp, family), (x, 176))
        sheet.paste(render(source, family), (x, 280))
        draw.text((x, 656), "CAMPO UNIFORME / TOM 35%", font=small, fill="#aaaaaa")
        sheet.paste(render(field, family), (x, 684))
    draw.text((MARGIN, 788), "Estruturas fixas e irregulares. Nenhum caractere ou mascara sobre a fotografia.",
              font=small, fill="#aaaaaa")
    return sheet


def near_far_sheet(source: Image.Image) -> Image.Image:
    sheet, draw = canvas(850, "ROSA-RETICLE / PERTO E LONGE",
                         "Controle Bayer com a mesma paleta. Acima: detalhe 4x. Abaixo: reducoes para 50% e 25%.")
    small = ImageFont.load_default(size=17)
    for index, family in enumerate(("bayer", *FAMILIES)):
        x = MARGIN + index * (PANEL + GAP)
        column_label(draw, x, family)
        image = render(source, family)
        detail = image.crop((116, 80, 204, 168)).resize((PANEL, PANEL), Image.Resampling.NEAREST)
        sheet.paste(detail, (x, 176))
        draw.text((x, 570), "50%", font=small, fill="#aaaaaa")
        draw.text((x + 224, 570), "25%", font=small, fill="#aaaaaa")
        sheet.paste(image.resize((176, 176), Image.Resampling.LANCZOS), (x, 604))
        sheet.paste(image.resize((88, 88), Image.Resampling.LANCZOS), (x + 224, 604))
    draw.text((MARGIN, 815), "As reducoes usam Lanczos. Observe os arquivos no tamanho nativo para comparar as escalas.",
              font=small, fill="#aaaaaa")
    return sheet


def tonal_sheet() -> Image.Image:
    sheet = Image.new("RGB", (960, 756), "#080808")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=20)
    small = ImageFont.load_default(size=15)
    draw.text((24, 20), "ROSA-RETICLE / COMPORTAMENTO TONAL", font=font, fill="#eeeeee")
    draw.text((24, 55), "Diagnostico em 2 cores / recortes nativos 144 px / mesmo seed e escala",
              font=small, fill="#aaaaaa")
    for row, family in enumerate(FAMILIES):
        y = 116 + row * 198
        draw.text((24, y + 56), LABELS[family], font=font, fill="#eeeeee")
        for column, tone in enumerate((0.10, 0.25, 0.50, 0.75, 0.90)):
            x = 152 + column * 160
            source = Image.new("L", (144, 144), round(255 * tone))
            image = render(source, family, levels=2)
            sheet.paste(image, (x, y))
            ink = sum(count for count, color in image.getcolors() if color != (0, 0, 0)) / (144 * 144)
            draw.text((x, y + 153), f"tom {tone:.0%}", font=small, fill="#eeeeee")
            draw.text((x, y + 174), f"area local {ink:.1%}", font=small, fill="#aaaaaa")
    draw.text((24, 727), "Area local pode variar. A cobertura global do atlas e igual nas tres familias.",
              font=small, fill="#aaaaaa")
    return sheet


def metrics(source: Image.Image) -> dict:
    references = {"continuous": render(source, "plain"), "bayer_same_palette": render(source, "bayer")}
    mask = source.point(lambda value: 255 if value else 0)
    results = {}
    for family in FAMILIES:
        candidate = render(source, family)
        results[family] = {}
        for reference_name, reference in references.items():
            errors = {}
            for name, factor in (("native", 1), ("50_percent", 0.5), ("25_percent", 0.25)):
                size = (round(source.width * factor), round(source.height * factor))
                actual = candidate.resize(size, Image.Resampling.LANCZOS)
                expected = reference.resize(size, Image.Resampling.LANCZOS)
                region = mask.resize(size, Image.Resampling.NEAREST)
                stat = ImageStat.Stat(ImageChops.difference(actual, expected), mask=region)
                errors[name] = round(math.sqrt(sum(value**2 for value in stat.rms) / 3), 4)
            results[family][f"rms_rgb_0_255_vs_{reference_name}"] = errors
    return {
        "experiment": "rosa-reticle", "study": "01", "status": "experimental",
        "levels": LEVELS, "nominal_scale_px": SCALE, "seed": DEFAULT_SEED,
        "sample_size": list(source.size), "resampling": "Lanczos",
        "measurement": "RGB RMS inside the sphere; difference is not a perceptual quality score",
        "atlas_period_px": 512, "families": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("assets/treated/rosa-reticle-study-01"))
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Choose a new directory; existing studies are preserved")
    source = sphere_source()
    panel = source.resize((PANEL, PANEL), Image.Resampling.LANCZOS)
    images = {
        "gradient-source.png": gradient_source(), "sphere-source.png": source,
        "families.png": families_sheet(panel), "near-far.png": near_far_sheet(panel),
        "tonal-behavior.png": tonal_sheet(), "sphere-continuous.png": render(source, "plain"),
        **{f"sphere-{family}.png": render(source, family) for family in FAMILIES},
    }
    report = metrics(panel)
    args.output_dir.mkdir(parents=True)
    for name, image in images.items():
        image.save(args.output_dir / name, optimize=True)
        print(args.output_dir / name)
    (args.output_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
