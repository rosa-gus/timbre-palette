"""rosa-reticle / experimental photographic treatment, investigation 02.

Bayer-derived quantization error in selected tonal ranges, with a continuous
duotone base. No large cells, Voronoi domains, characters, or random fields.
"""

from bisect import bisect_right

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

if __package__:
    from .deprecated_treat_instrument import BAYER_4, treat_image
else:
    from deprecated_treat_instrument import BAYER_4, treat_image


CURVE = ((0, 0), (0.015, 0.008), (0.04, 0.028), (0.10, 0.095),
         (0.22, 0.235), (0.40, 0.445), (0.60, 0.665), (0.80, 0.855), (1, 1))
PALETTE = (0, 0.012, 0.025, 0.045, 0.070, 0.10, 0.14, 0.19, 0.25,
           0.32, 0.40, 0.49, 0.53, 0.57, 0.61, 0.65, 0.69, 0.73,
           0.77, 0.81, 0.85, 0.89, 0.92, 0.945, 0.965, 0.98, 1)


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


def screen(dual: bool) -> tuple[tuple[int, ...], ...]:
    if not dual:
        return BAYER_4
    # An 8×8 ranked screen: mostly one-pixel Bayer, with a weaker two-pixel
    # component. This changes the error structure, not source image resolution.
    scores = []
    for y in range(8):
        for x in range(8):
            fine = (BAYER_4[y % 4][x % 4] + 0.5) / 16
            medium = (BAYER_4[(y // 2 + 1) % 4][(x // 2 + 2) % 4] + 0.5) / 16
            scores.append((0.72 * fine + 0.28 * medium, BAYER_4[y % 4][x % 4], y, x))
    ranks = [[0] * 8 for _ in range(8)]
    for rank, (_, _, y, x) in enumerate(sorted(scores)):
        ranks[y][x] = rank
    return tuple(tuple(row) for row in ranks)


def quantized(gray: Image.Image, *, dual: bool, palette: tuple[float, ...] = PALETTE,
              pixel_scale: int = 1) -> Image.Image:
    if pixel_scale not in (1, 2):
        raise ValueError("pixel_scale must be 1 or 2")
    ranks = screen(dual)
    ranks = tuple(tuple(row[x // pixel_scale] for x in range(len(row) * pixel_scale))
                  for row in ranks for _ in range(pixel_scale))
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


def texture_weight(gray: Image.Image) -> Image.Image:
    tone = gray.point([
        round(255 * 0.80 * smoothstep(0.02, 0.08, value / 255)
              * (1 - smoothstep(0.30, 0.68, value / 255)))
        for value in range(256)
    ])
    # Fine image detail lowers the quantization residual, preserving the
    # continuous source at eyes, hair, labels, instrument edges, and leaves.
    detail = ImageChops.difference(gray, gray.filter(ImageFilter.GaussianBlur(1.0)))
    protection = detail.point([
        round(255 * (1 - 0.70 * smoothstep(4, 18, value))) for value in range(256)
    ])
    return ImageChops.multiply(tone, protection)


def duotone(gray: Image.Image) -> Image.Image:
    return Image.merge("RGB", tuple(gray.point([
        round(channel * value / 255) for value in range(256)
    ]) for channel in (242, 145, 145)))


def prepare_source(image: Image.Image, width: int = 1200) -> Image.Image:
    if width < 1:
        raise ValueError("width must be positive")
    oriented = ImageOps.exif_transpose(image).convert("RGBA")
    rgb = Image.alpha_composite(Image.new("RGBA", oriented.size, (0, 0, 0, 255)), oriented).convert("RGB")
    if rgb.width > width:
        rgb = rgb.resize((width, max(1, round(rgb.height * width / rgb.width))), Image.Resampling.LANCZOS)
    return rgb


def photo_variants(image: Image.Image, width: int = 1200) -> dict[str, Image.Image]:
    rgb = prepare_source(image, width)
    gray = ImageEnhance.Contrast(ImageOps.grayscale(rgb)).enhance(1.1)
    base = gray.point(curve_lut())
    weight = texture_weight(base)
    return {
        "original": rgb,
        "bayer-current": treat_image(rgb, width=width),
        "tonal-base": duotone(base),
        "selective": duotone(Image.composite(quantized(base, dual=False), base, weight)),
        "dual": duotone(Image.composite(quantized(base, dual=True), base, weight)),
    }
