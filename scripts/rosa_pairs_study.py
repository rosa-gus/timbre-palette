#!/usr/bin/env python3
"""rosa-reticle 04: tonal pair cadence. EXPERIMENTAL stills, no publication."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageOps, ImageStat

if __package__:
    from .rosa_pairs import pair_screen, pairs_gray, signature_weight
    from .rosa_shadow_study import CENTERS, SHADOW_PALETTE, shadow_gray
    from .rosa_tonal import CURVE, curve_lut, duotone, prepare_source
    from .rosa_photo_study import text
    from .deprecated_treat_instrument import BAYER_4
else:
    from rosa_pairs import pair_screen, pairs_gray, signature_weight
    from rosa_shadow_study import CENTERS, SHADOW_PALETTE, shadow_gray
    from rosa_tonal import CURVE, curve_lut, duotone, prepare_source
    from rosa_photo_study import text
    from deprecated_treat_instrument import BAYER_4


def comparison(name: str, reference: Image.Image, candidate: Image.Image) -> Image.Image:
    board = Image.new("RGB", (1048, 1232), "#080808")
    draw = ImageDraw.Draw(board)
    text(draw, (24, 20), f"ROSA-RETICLE / 04 / {name}", 26)
    text(draw, (24, 60), "EXPERIMENTAL / mesma curva, paleta e contraste / muda a cadencia nas sombras", 16)
    w, h = reference.size
    cx, cy = CENTERS[name]
    left = max(0, min(w - 240, round(w * cx) - 120))
    top = max(0, min(h - 200, round(h * cy) - 100))
    bounds = (left, top, left + 240, top + 200)
    for i, (label, image) in enumerate((("REFERENCIA / SOMBRA 1 px", reference), ("ESTUDO 04 / PARES", candidate))):
        x = 24 + 520 * i
        text(draw, (x, 110), label, 22)
        board.paste(image.resize((480, round(h * 480 / w)), Image.Resampling.LANCZOS), (x, 150))
        text(draw, (x, 495), "MESMO RECORTE / 2x SEM SUAVIZAR", 16, "#aaaaaa")
        crop = image.crop(bounds)
        board.paste(crop.resize((480, 400), Image.Resampling.NEAREST), (x, 525))
        text(draw, (x, 955), "RECORTE / 1:1", 16, "#aaaaaa")
        board.paste(crop, (x, 985))
        text(draw, (x + 270, 955), "FOTO / 15%", 16, "#aaaaaa")
        board.paste(image.resize((round(w * .15), round(h * .15)), Image.Resampling.LANCZOS), (x + 270, 985))
    text(draw, (24, 1204), "Pares de 1 pixel; faixa tonal localizada; posicoes fixas. A reducao pode ocultar a diferenca.", 16, "#aaaaaa")
    return board


def geometry_diagnostic() -> Image.Image:
    board = Image.new("RGB", (1048, 430), "#080808")
    draw = ImageDraw.Draw(board)
    text(draw, (24, 18), "ROSA-RETICLE / 04 / GEOMETRIA ISOLADA", 25)
    text(draw, (24, 57), "Bicolor, ampliacao 6x. Diagnostico da matriz; nao representa o contraste fotografico.", 16)
    for row, (label, ranks) in enumerate((("BAYER", BAYER_4), ("PARES", pair_screen()))):
        text(draw, (24, 122 + row * 148), label, 18)
        n = len(ranks)
        for col, coverage in enumerate((.125, .25, .375, .5, .625, .75)):
            patch = Image.new("L", (24, 16))
            patch.putdata([255 if (ranks[y % n][x % n] + .5) / (n * n) < coverage else 0
                           for y in range(16) for x in range(24)])
            x, y = 128 + col * 148, 128 + row * 148
            text(draw, (x, y - 25), f"{coverage:.1%}", 15)
            board.paste(duotone(patch).resize((144, 96), Image.Resampling.NEAREST), (x, y))
    return board


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, default=Path("assets"))
    parser.add_argument("--output-dir", type=Path, default=Path("assets/treated/rosa-reticle-study-04"))
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Choose a new output directory; previous studies are preserved")
    paths = {name: args.assets_dir / f"{name}.jpeg" for name in CENTERS}
    for path in paths.values():
        if not path.is_file():
            parser.error(f"Missing source: {path}")
    args.output_dir.mkdir(parents=True)
    manifest = {"experiment": "rosa-reticle", "investigation": "04", "status": "experimental",
                "width": 1200, "contrast": 1.1, "curve": CURVE, "palette": SHADOW_PALETTE,
                "signature_gate": {"fade_in": [.035, .08], "fade_out": [.14, .24], "peak": .85},
                "ranks": pair_screen(), "reference": "03 shadow-fine", "sources": {}}
    for name, path in paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as image:
            rgb = prepare_source(image)
        base = ImageEnhance.Contrast(ImageOps.grayscale(rgb)).enhance(1.1).point(curve_lut())
        reference, candidate = duotone(shadow_gray(base)), duotone(pairs_gray(base))
        root = args.output_dir / name
        root.mkdir()
        reference.save(root / "shadow-fine-reference.png")
        candidate.save(root / "pairs.png")
        signature_weight(base).save(root / "signature-mask.png")
        comparison(name, reference, candidate).save(root / "comparison.png")
        # Mean error is recorded as a diagnostic, never as an aesthetic score.
        manifest["sources"][name] = {"path": str(path), "sha256": digest,
            "size": base.size, "crop_center": CENTERS[name],
            "mean_red_difference": ImageStat.Stat(candidate).mean[0] - ImageStat.Stat(reference).mean[0]}
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        print(root / "comparison.png", flush=True)
    geometry_diagnostic().save(args.output_dir / "geometry.png")
    ramp = Image.frombytes("L", (256, 80), bytes(range(256)) * 80).resize((1024, 80), Image.Resampling.NEAREST)
    diagnostic = Image.new("RGB", (1024, 240))
    for i, image in enumerate((duotone(shadow_gray(ramp)), duotone(pairs_gray(ramp)), signature_weight(ramp).convert("RGB"))):
        diagnostic.paste(image, (0, i * 80))
    diagnostic.save(args.output_dir / "tonal-diagnostic.png")
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
