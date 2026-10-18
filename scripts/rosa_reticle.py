"""rosa-reticle 0.1.0: Bayer-inspired tonal screening and grayscale transport.

Public image API: treat_gray(image, width=1200), then duotone(gray) for a
black/pink PNG. Videos transport the treated gray values and apply the same
sRGB color mapping at display time.
"""

from bisect import bisect_right
from functools import lru_cache
from PIL import Image, ImageChops, ImageColor, ImageEnhance, ImageFilter, ImageOps

__version__ = "0.1.0"
__all__ = ["__version__", "treat_gray", "duotone"]

BAYER_4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


CURVE = ((0, 0), (0.015, 0.008), (0.04, 0.028), (0.10, 0.095),
         (0.22, 0.235), (0.40, 0.445), (0.60, 0.665), (0.80, 0.855), (1, 1))


SHADOW_PALETTE = (0, 0.02, 0.065, 0.16, 0.31, 0.49, 0.68, 0.82, 1)


def smoothstep(start: float, end: float, value: float) -> float:
    value = max(0.0, min(1.0, (value - start) / (end - start)))
    return value * value * (3 - 2 * value)


def curve_lut() -> list[int]:
    output = []
    for value in range(256):
        t = value / 255
        index = min(len(CURVE) - 2, max(0, bisect_right([x for x, _ in CURVE], t) - 1))
        (x0, y0), (x1, y1) = CURVE[index:index + 2]
        output.append(round(255 * (y0 + (y1 - y0) * (t - x0) / (x1 - x0))))
    return output


def duotone(gray: Image.Image, *, shadow: str = "#000000",
            highlight: str = "#f29191") -> Image.Image:
    """Map treated grayscale to two opaque sRGB endpoint colors."""
    dark, light = ImageColor.getrgb(shadow), ImageColor.getrgb(highlight)
    if len(dark) != 3 or len(light) != 3:
        raise ValueError("shadow and highlight must be opaque RGB colors")
    return Image.merge("RGB", tuple(gray.point([
        round(a + (b - a) * value / 255) for value in range(256)
    ]) for a, b in zip(dark, light)))


def prepare_source(image: Image.Image, width: int = 1200) -> Image.Image:
    if width < 1:
        raise ValueError("width must be positive")
    oriented = ImageOps.exif_transpose(image).convert("RGBA")
    rgb = Image.alpha_composite(Image.new("RGBA", oriented.size, (0, 0, 0, 255)), oriented).convert("RGB")
    if rgb.width > width:
        rgb = rgb.resize((width, max(1, round(rgb.height * width / rgb.width))), Image.Resampling.LANCZOS)
    return rgb


def quantized(gray: Image.Image, *, palette: tuple[float, ...] = SHADOW_PALETTE) -> Image.Image:
    ranks = BAYER_4
    period = len(ranks)
    count = max(max(row) for row in ranks) + 1
    tables = []
    for rank in range(count):
        threshold = (rank + 0.5) / count
        table = []
        for encoded in range(256):
            value = encoded / 255
            lower = min(len(palette) - 2, max(0, bisect_right(palette, value) - 1))
            low, high = palette[lower:lower + 2]
            fraction = (value - low) / (high - low)
            table.append(round(255 * (high if fraction > threshold else low)))
        tables.append(bytes(table))
    source = gray.tobytes()
    result = bytearray(len(source))
    for y in range(gray.height):
        start, end = y * gray.width, (y + 1) * gray.width
        for x in range(period):
            result[start + x:end:period] = source[start + x:end:period].translate(tables[ranks[y % period][x]])
    return Image.frombytes("L", gray.size, bytes(result))


def shadow_weight(base: Image.Image) -> Image.Image:
    tone = base.point([
        round(255 * smoothstep(0.025, 0.10, v / 255)
              * (1 - smoothstep(0.32, 0.58, v / 255)))
        for v in range(256)
    ])
    detail = ImageChops.difference(base, base.filter(ImageFilter.GaussianBlur(1)))
    # Retain at least 85% of the applicable screen at detailed edges.
    protection = detail.point([
        round(255 * (1 - 0.15 * smoothstep(4, 18, v))) for v in range(256)
    ])
    return ImageChops.multiply(tone, protection)


def shadow_gray(base: Image.Image) -> Image.Image:
    screened = quantized(base)
    return Image.composite(screened, base, shadow_weight(base))


def pair_screen() -> tuple[tuple[int, ...], ...]:
    """16x16 permutation with sparse local exchanges in a Bayer scaffold.

    Only four of sixteen 4x4 cells exchange two threshold positions. An early
    mark moves next to a seed, horizontally or vertically. The other twelve
    cells retain Bayer geometry. Ties within each Bayer rank activate in a
    dispersed order, avoiding wholesale synchronized changes of density.
    """
    cells = [[list(row) for row in BAYER_4] for _ in range(16)]
    for cy in range(4):
        for cx in range(4):
            if BAYER_4[cy][cx] < 4:
                # Four separated interventions, two horizontal and two vertical.
                dx, dy = ((1, 0), (0, 1), (3, 0), (0, 3))[BAYER_4[cy][cx]]
                cell = cells[cy * 4 + cx]
                cell[2][2], cell[dy][dx] = cell[dy][dx], cell[2][2]
    ranks = [[0] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            cx, cy = x // 4, y // 4
            ranks[y][x] = cells[cy * 4 + cx][y % 4][x % 4] * 16 + BAYER_4[cy][cx]
    return tuple(tuple(row) for row in ranks)


@lru_cache(maxsize=1)
def pair_tables() -> tuple[bytes, ...]:
    tables = []
    for rank in range(256):
        threshold = (rank + .5) / 256
        values = []
        for v in range(256):
            value = v / 255
            index = min(len(SHADOW_PALETTE) - 2,
                        max(0, bisect_right(SHADOW_PALETTE, value) - 1))
            low, high = SHADOW_PALETTE[index:index + 2]
            values.append(round(255 * (high if (value - low) / (high - low) > threshold else low)))
        tables.append(bytes(values))
    return tuple(tables)


def pair_quantized(base: Image.Image, origin: tuple[int, int] = (0, 0)) -> Image.Image:
    if base.mode != "L":
        raise ValueError("Expected an L image")
    ranks, tables = pair_screen(), pair_tables()
    source = base.tobytes()
    result = bytearray(len(source))
    ox, oy = origin
    for y in range(base.height):
        start, end = y * base.width, (y + 1) * base.width
        for x in range(min(16, base.width)):
            rank = ranks[(y + oy) % 16][(x + ox) % 16]
            result[start + x:end:16] = source[start + x:end:16].translate(tables[rank])
    return Image.frombytes("L", base.size, bytes(result))


def signature_weight(base: Image.Image) -> Image.Image:
    # This narrower gate controls only the change of geometry. The broader
    # shadow mask and fine-detail protection still apply.
    return base.point([
        round(255 * .85 * smoothstep(.035, .08, v / 255)
              * (1 - smoothstep(.14, .24, v / 255)))
        for v in range(256)
    ])


def pairs_gray(base: Image.Image) -> Image.Image:
    reference = shadow_gray(base)
    paired = Image.composite(pair_quantized(base), base, shadow_weight(base))
    return Image.composite(paired, reference, signature_weight(base))


def treat_gray(image: Image.Image, width: int = 1200) -> Image.Image:
    """Orient, resize without upscaling, and apply the versioned tonal screen.

    Returns an L image. Composite transparency over black. Process a complete
    frame before cropping so the detail mask keeps its neighborhood context.
    """
    rgb = prepare_source(image, width)
    base = ImageEnhance.Contrast(ImageOps.grayscale(rgb)).enhance(1.1).point(curve_lut())
    return pairs_gray(base)


def main() -> None:
    """CLI entry point for the versioned image and grayscale-video exporters."""
    import argparse
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "image":
        if __package__:
            from .treat_instrument import main as command
        else:
            from treat_instrument import main as command
        command(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "video":
        if __package__:
            from .rosa_gray_video import main as command
        else:
            from rosa_gray_video import main as command
        command(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"rosa-reticle {__version__}")
    parser.add_argument("command", choices=("image", "video"))
    parser.parse_args()


if __name__ == "__main__":
    main()
