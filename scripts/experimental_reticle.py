"""Experimental v1: a ranked, clustered screen derived from crossing strokes.

Not an ASCII overlay. Each pixel's rank controls when ink grows from a compact
square into axial strokes, bridges, and finally small negative spaces. Ranking
every pixel exactly once gives predictable coverage on uniform tonal patches.
The staggered lattice is fixed in image coordinates, without frame randomness.
"""

import math
from functools import lru_cache

from PIL import Image


@lru_cache(maxsize=8)
def rank_cell(cell: int, diagonal: bool = False) -> tuple[tuple[int, ...], ...]:
    if not isinstance(cell, int) or not 8 <= cell <= 64 or cell % 2:
        raise ValueError("reticle_cell must be an even integer between 8 and 64")
    points = []
    for y in range(cell):
        for x in range(cell):
            u, v = 2 * x - cell + 1, 2 * y - cell + 1
            dx, dy = (abs(u + v), abs(u - v)) if diagonal else (abs(u), abs(v))
            # An axial spot function, rather than a rasterized character. The
            # product gently rounds the spaces between the growing strokes.
            score = min(dx, dy) * 100 + max(dx, dy) * 28 + dx * dy * 16 // cell
            # Resolve geometric ties by alternating parity, then coordinates.
            # This affects only symmetric ties, not the designed spot shape.
            points.append((score, (x % 2) * 2 + y % 2, y, x))
    ranks = [[0] * cell for _ in range(cell)]
    for rank, (_, _, y, x) in enumerate(sorted(points)):
        ranks[y][x] = rank
    return tuple(tuple(row) for row in ranks)


def reticle_indices(
    gray: Image.Image, gamma_lut: list[float], levels: int,
    strength: float, cell: int,
) -> Image.Image:
    """Quantize individual pixels into adjacent palette entries using the screen.

    At strength 1, a uniform complete cell covers the requested fractional
    palette step to within half a pixel. Zero gives plain posterization.
    Source pixels are never replaced by cell averages or empty black fields.
    """
    ranks = (rank_cell(cell), rank_cell(cell, diagonal=True))
    count = cell * cell
    tables = [
        bytes(max(0, min(levels - 1, math.floor(
            value * (levels - 1) + 0.5
            + (0.5 - (rank + 0.5) / count) * strength
        ))) for value in gamma_lut)
        for rank in range(count)
    ]
    luminance = gray.tobytes()
    indices = bytearray(len(luminance))
    period = cell * 2
    for y in range(gray.height):
        start, end = y * gray.width, (y + 1) * gray.width
        # Offset alternate rows of spots to avoid a rectangular stamp lattice.
        phase = cell // 2 if (y // cell) % 2 else 0
        for x in range(period):
            shifted = (x + phase) % period
            orientation = (shifted // cell + y // cell) % 2
            rank = ranks[orientation][y % cell][shifted % cell]
            table = tables[rank]
            indices[start + x:end:period] = luminance[start + x:end:period].translate(table)
    return Image.frombytes("L", gray.size, bytes(indices))
