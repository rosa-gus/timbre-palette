"""Deprecated irregular screens retained for legacy export options.

Families share a nominal scale, seed, globally uniform threshold histogram,
and quantizer. No image-dependent normalization or per-frame randomness.
The 512 px atlas is periodic at its outer boundary, not aperiodic or blue noise.
"""

import math
import random
from functools import lru_cache

from PIL import Image


ATLAS_SIZE = 512
FAMILIES = ("islands", "fibers", "mineral")
DEFAULT_SEED = 20261016


@lru_cache(maxsize=6)
def _layout(scale: int, seed: int) -> tuple[list[list[int]], list[tuple[float, ...]]]:
    """Shared jittered Voronoi regions on a torus, independent of family/input."""
    size = ATLAS_SIZE
    n = max(2, round(size / scale))
    spacing = size / n
    rng = random.Random(seed)
    centers = []
    for y in range(n):
        for x in range(n):
            centers.append(((x + 0.5 + rng.uniform(-0.34, 0.34)) * spacing,
                            (y + 0.5 + rng.uniform(-0.34, 0.34)) * spacing,
                            rng.random() * math.tau, rng.uniform(0.85, 1.15)))
    members = [[] for _ in centers]
    for y in range(size):
        row = int(y / spacing)
        for x in range(size):
            column = int(x / spacing)
            closest, distance = 0, float("inf")
            for oy in (-2, -1, 0, 1, 2):
                for ox in (-2, -1, 0, 1, 2):
                    index = ((row + oy) % n) * n + (column + ox) % n
                    cx, cy, _, _ = centers[index]
                    dx = (x + 0.5 - cx + size / 2) % size - size / 2
                    dy = (y + 0.5 - cy + size / 2) % size - size / 2
                    candidate = dx * dx + dy * dy
                    if candidate < distance:
                        closest, distance = index, candidate
            members[closest].append(y * size + x)
    return members, centers


@lru_cache(maxsize=12)
def threshold_atlas(family: str = "islands", scale: int = 16,
                    seed: int = DEFAULT_SEED) -> bytes:
    """Locally balanced ranks; each global threshold occurs 1024 times.

    Domains and rank calibration belong to the fixed atlas, never the source
    image. Equal local rank coverage prevents broad noise from turning tonal
    gradients into posterized patches. A final global ranking matches the
    histogram exactly across families.
    """
    if family not in FAMILIES:
        raise ValueError(f"rosa family must be one of {FAMILIES}")
    if not isinstance(scale, int) or not 8 <= scale <= 64:
        raise ValueError("rosa scale must be an integer between 8 and 64")
    if not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("rosa seed must be a 32-bit unsigned integer")
    size = ATLAS_SIZE
    members, centers = _layout(scale, seed)
    fractions = [0.0] * (size * size)
    for pixels, (cx, cy, phase, aspect) in zip(members, centers):
        if not pixels:
            continue
        angle = 1.0 + 0.55 * math.sin(cx * math.tau / size) + 0.35 * math.cos(cy * math.tau / size)
        angle += 0.12 * math.sin(phase)
        if family == "mineral":
            angle = phase
        ca, sa = math.cos(angle), math.sin(angle)
        scored = []
        for index in pixels:
            dx = ((index % size + 0.5 - cx + size / 2) % size - size / 2) / scale
            dy = ((index // size + 0.5 - cy + size / 2) % size - size / 2) / scale
            u, v = dx * ca + dy * sa, -dx * sa + dy * ca
            if family == "islands":
                theta = math.atan2(v, u)
                score = math.hypot(u * aspect, v / aspect) * (
                    1 + 0.10 * math.sin(theta * 3 + phase) + 0.05 * math.sin(theta * 5 - phase)
                )
            elif family == "fibers":
                score = (u / 1.8) ** 2 + (v * 1.8) ** 2
            else:
                a, b = abs(u * aspect), abs(v / aspect)
                score = max(a, b) * 0.85 + min(a, b) * 0.15
                score += 0.025 * math.sin(u * 4 + phase) * math.sin(v * 3)
            scored.append((score, index))
        for rank, (_, index) in enumerate(sorted(scored)):
            fractions[index] = (rank + 0.5) / len(pixels)
    order = sorted(range(len(fractions)), key=lambda index: (fractions[index], index))
    thresholds = bytearray(len(fractions))
    per_bin = len(fractions) // 256
    for rank, index in enumerate(order):
        thresholds[index] = rank // per_bin
    return bytes(thresholds)


def threshold_image(size: tuple[int, int], family: str, scale: int, seed: int,
                    origin: tuple[int, int] = (0, 0)) -> Image.Image:
    atlas = threshold_atlas(family, scale, seed)
    width, height = size
    ox, oy = origin
    pixels = bytearray(width * height)
    for y in range(height):
        row_start = ((y + oy) % ATLAS_SIZE) * ATLAS_SIZE
        row = atlas[row_start:row_start + ATLAS_SIZE]
        offset = ox % ATLAS_SIZE
        expanded = row * (math.ceil((width + offset) / ATLAS_SIZE))
        pixels[y * width:(y + 1) * width] = expanded[offset:offset + width]
    return Image.frombytes("L", size, bytes(pixels))


def rosa_indices(gray: Image.Image, gamma_lut: list[float], levels: int,
                 strength: float, *, family: str = "islands", scale: int = 16,
                 seed: int = DEFAULT_SEED, origin: tuple[int, int] = (0, 0)) -> Image.Image:
    """Per-pixel adjacent-palette quantization, driven by a fixed ranked field."""
    thresholds = threshold_image(gray.size, family, scale, seed, origin).tobytes()
    tables = [bytes(max(0, min(levels - 1, math.floor(
        value * (levels - 1) + 0.5 + (0.5 - (threshold + 0.5) / 256) * strength
    ))) for value in gamma_lut) for threshold in range(256)]
    result = bytes(tables[threshold][value]
                   for value, threshold in zip(gray.tobytes(), thresholds))
    return Image.frombytes("L", gray.size, result)
