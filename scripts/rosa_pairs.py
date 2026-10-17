"""Experimental rosa-reticle 04: one-pixel tonal pairs in emerging shadows."""

from bisect import bisect_right
from functools import lru_cache

from PIL import Image, ImageChops

if __package__:
    from .rosa_shadow_study import SHADOW_PALETTE, shadow_gray, shadow_weight
    from .rosa_tonal import smoothstep
    from .deprecated_treat_instrument import BAYER_4
else:
    from rosa_shadow_study import SHADOW_PALETTE, shadow_gray, shadow_weight
    from rosa_tonal import smoothstep
    from deprecated_treat_instrument import BAYER_4


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
    # shadow mask and fine-detail protection from study 03 still apply.
    return base.point([
        round(255 * .85 * smoothstep(.035, .08, v / 255)
              * (1 - smoothstep(.14, .24, v / 255)))
        for v in range(256)
    ])


def pairs_gray(base: Image.Image) -> Image.Image:
    reference = shadow_gray(base)
    paired = Image.composite(pair_quantized(base), base, shadow_weight(base))
    return Image.composite(paired, reference, signature_weight(base))
