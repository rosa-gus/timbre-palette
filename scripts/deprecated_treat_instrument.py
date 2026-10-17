#!/usr/bin/env python3
"""Deprecated image/video treatment retained for existing Bayer manifests.

Requires Pillow: python3 -m pip install 'Pillow>=10.1,<13'
Videos also require FFmpeg with the libvpx-vp9 encoder.
Run offline, before publishing assets; no image processing in HTTP requests.
"""

import argparse
import math
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Callable

from PIL import Image, ImageColor, ImageEnhance, ImageOps

if __package__:
    from .experimental_reticle import rank_cell, reticle_indices
    from .deprecated_rosa_reticle import DEFAULT_SEED, FAMILIES, rosa_indices
else:
    from experimental_reticle import rank_cell, reticle_indices
    from deprecated_rosa_reticle import DEFAULT_SEED, FAMILIES, rosa_indices


BAYER_4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


# Explicit 5×7 glyphs keep thin strokes intact at native resolution. Their
# increasing ink coverage is the tonal ramp, rather than a repeating wallpaper.
ASCII_GLYPHS = (
    ("00000", "00100", "00100", "00000", "00100", "00100", "00000"),  # :
    ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),  # +
    ("00000", "10101", "01110", "11111", "01110", "10101", "00000"),  # *
    ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),  # #
)


@lru_cache(maxsize=16)
def ascii_masks(cell: int) -> tuple[Image.Image, ...]:
    """Complete, pixel-aligned glyphs; never threshold an anti-aliased font."""
    scale = max(1, cell // 8)
    x0, y0 = (cell - 5 * scale) // 2, (cell - 7 * scale) // 2
    masks = []
    for glyph in ASCII_GLYPHS:
        mask = Image.new("L", (cell, cell))
        for y, row in enumerate(glyph):
            for x, pixel in enumerate(row):
                if pixel == "1":
                    mask.paste(255, (x0 + x * scale, y0 + y * scale,
                                     x0 + (x + 1) * scale, y0 + (y + 1) * scale))
        masks.append(mask)
    return tuple(masks)


@lru_cache(maxsize=16)
def ascii_tones(levels: int, strength: float) -> tuple[tuple[list[int], int], ...]:
    """Dark cells are made of ink on black; highlights recover the photograph."""
    tones = []
    for tone in range(256):
        value = tone / 255
        transition = max(0.0, min(1.0, (value - 0.25) / 0.35))
        transition = transition * transition * (3 - 2 * transition)
        amount = strength * (1 - transition)
        photo = 1 - amount
        glyph = value * photo + min(1.0, 0.12 + value * 2) * amount
        quantize = lambda v: max(0, min(levels - 1, math.floor(v * (levels - 1) + 0.5)))
        tones.append(([quantize(pixel / 255 * photo) for pixel in range(256)], quantize(glyph)))
    return tuple(tones)


def ascii_indices(
    gray: Image.Image, gamma_lut: list[float], levels: int,
    strength: float, cell: int,
) -> Image.Image:
    """Reconstruct shadows with whole glyphs selected by local luminance.

    Source pixels fade into black between strokes instead of showing through
    a repeating texture. Each glyph has one constant ink color; its density
    and brightness follow its cell's tone. Clear regions retain photo detail.
    """
    luminance = gray.point([round(value * 255) for value in gamma_lut])
    plain = gray.point([max(0, min(levels - 1, math.floor(
        value * (levels - 1) + 0.5
    ))) for value in gamma_lut])
    if not strength:
        return plain
    columns, rows = math.ceil(gray.width / cell), math.ceil(gray.height / cell)
    padded = Image.new("L", (columns * cell, rows * cell))
    padded.paste(luminance)
    if padded.width > gray.width:
        padded.paste(luminance.crop((gray.width - 1, 0, gray.width, gray.height)).resize(
            (padded.width - gray.width, gray.height)), (gray.width, 0))
    if padded.height > gray.height:
        padded.paste(padded.crop((0, gray.height - 1, padded.width, gray.height)).resize(
            (padded.width, padded.height - gray.height)), (0, gray.height))
    local_tones = padded.resize((columns, rows), Image.Resampling.BOX)
    masks, tones = ascii_masks(cell), ascii_tones(levels, strength)
    output = plain.copy()
    for row in range(rows):
        for column in range(columns):
            tone = local_tones.getpixel((column, row))
            if tone >= 153:
                continue
            x, y = column * cell, row * cell
            bounds = (x, y, min(x + cell, gray.width), min(y + cell, gray.height))
            background, foreground = tones[tone]
            patch = luminance.crop(bounds).point(background)
            if tone >= 8:
                mask = masks[min(3, int(tone / 255 / 0.35 * 4))]
                if mask.size != patch.size:
                    mask = mask.crop((0, 0, patch.width, patch.height))
                patch.paste(foreground, (0, 0, patch.width, patch.height), mask)
            output.paste(patch, (x, y))
    return output


def treat_image(
    image: Image.Image,
    *,
    shadow: str = "#000000",
    highlight: str = "#f29191",
    levels: int = 8,
    strength: float = 0.35,
    width: int = 1200,
    contrast: float = 1.1,
    gamma: float = 1.0,
    pattern: str = "bayer",
    ascii_cell: int = 24,
    reticle_cell: int = 16,
    rosa_family: str = "islands",
    rosa_scale: int = 16,
    rosa_seed: int = DEFAULT_SEED,
) -> Image.Image:
    """Resize first, then quantize luminance and map it onto an sRGB palette.

    Bayer strength scales the threshold by one quantization step. ASCII
    strength controls reconstruction of shadows from complete tonal glyphs.
    Experimental reticle uses ranked crossing strokes; strength 1 gives full
    tonal coverage. Zero gives plain posterization in every mode.
    Output has at most `levels` opaque colors. Transparent input is composited
    onto the shadow color. No crop or automatic per-image normalization.
    """
    if not 2 <= levels <= 256:
        raise ValueError("levels must be between 2 and 256")
    if not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("strength must be between 0 and 1")
    if width < 1:
        raise ValueError("width must be positive")
    if any(not math.isfinite(value) or value <= 0 for value in (contrast, gamma)):
        raise ValueError("contrast and gamma must be finite and positive")
    if pattern not in ("bayer", "ascii", "reticle", "rosa-reticle"):
        raise ValueError("pattern must be bayer, ascii, reticle, or rosa-reticle")
    if pattern == "reticle":
        rank_cell(reticle_cell)
    if not 8 <= ascii_cell <= 64:
        raise ValueError("ascii_cell must be between 8 and 64 pixels")

    dark = ImageColor.getrgb(shadow)
    light = ImageColor.getrgb(highlight)
    if len(dark) != 3 or len(light) != 3:
        raise ValueError("shadow and highlight must be opaque RGB colors")
    oriented = ImageOps.exif_transpose(image).convert("RGBA")
    background = Image.new("RGBA", oriented.size, (*dark, 255))
    rgb = Image.alpha_composite(background, oriented).convert("RGB")
    if rgb.width > width:
        height = max(1, round(rgb.height * width / rgb.width))
        rgb = rgb.resize((width, height), Image.Resampling.LANCZOS)

    gray = ImageEnhance.Contrast(ImageOps.grayscale(rgb)).enhance(contrast)
    gamma_lut = [(value / 255) ** (1 / gamma) for value in range(256)]
    palette = [
        tuple(round(a + (b - a) * index / (levels - 1)) for a, b in zip(dark, light))
        for index in range(levels)
    ]
    if pattern in ("ascii", "reticle", "rosa-reticle"):
        if pattern == "rosa-reticle":
            indices_image = rosa_indices(gray, gamma_lut, levels, strength,
                                         family=rosa_family, scale=rosa_scale, seed=rosa_seed)
        elif pattern == "reticle":
            indices_image = reticle_indices(gray, gamma_lut, levels, strength, reticle_cell)
        else:
            indices_image = ascii_indices(gray, gamma_lut, levels, strength, ascii_cell)
        output = Image.frombytes("P", gray.size, indices_image.tobytes())
        output.putpalette([channel for color in palette for channel in color])
        return output.convert("RGB")
    # Translate whole row slices instead of doing Python work per video pixel.
    tables = []
    for row in BAYER_4:
        tables.append([
            bytes(max(0, min(levels - 1, math.floor(
                value * (levels - 1) + ((threshold + 0.5) / 16 - 0.5) * strength + 0.5
            ))) for value in gamma_lut)
            for threshold in row
        ])
    luminance = gray.tobytes()
    indices = bytearray(len(luminance))
    for y in range(gray.height):
        start, end = y * gray.width, (y + 1) * gray.width
        for x in range(4):
            indices[start + x:end:4] = luminance[start + x:end:4].translate(tables[y % 4][x])
    output = Image.frombytes("P", gray.size, bytes(indices))
    output.putpalette([channel for color in palette for channel in color])
    return output.convert("RGB")


def treat_video(
    source: Path,
    destination: Path,
    *,
    fps: float = 24,
    duration: float | None = None,
    crf: int = 18,
    cpu_used: int = 4,
    deadline: str = "good",
    poster: Path | None = None,
    frame_processor: Callable[[Image.Image], Image.Image] | None = None,
    **treatment,
) -> int:
    """Treat frames offline with Pillow, then encode silent VP9 WebM.

    Temporary frames are cleaned up even on failure. The complete video is
    retained unless duration is specified. FFmpeg applies video orientation.
    """
    if destination.suffix.lower() != ".webm":
        raise ValueError("Video output must use .webm (FFmpeg with libvpx-vp9 required)")
    if destination.exists() or source.resolve() == destination.resolve():
        raise ValueError("Video output already exists or matches the input")
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("fps must be finite and positive")
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise ValueError("duration must be finite and positive")
    if not 0 <= crf <= 63:
        raise ValueError("crf must be between 0 and 63")
    if not 0 <= cpu_used <= 8:
        raise ValueError("cpu_used must be between 0 and 8")
    if deadline not in ("good", "realtime"):
        raise ValueError("deadline must be good or realtime")
    if poster and (poster.suffix.lower() != ".png" or poster.exists()
                   or poster.resolve() in (source.resolve(), destination.resolve())):
        raise ValueError("Poster must be a new .png file distinct from input and output")
    # A separate experimental pipeline may supply its complete frame treatment.
    # The default path and its parameter validation remain unchanged.
    if frame_processor is None:
        treat_image(Image.new("RGB", (4, 4)), **treatment)
    with tempfile.TemporaryDirectory(prefix="palette-video-") as directory:
        root = Path(directory)
        original, treated = root / "original", root / "treated"
        original.mkdir()
        treated.mkdir()
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                   "-i", str(source.resolve()), "-map", "0:v:0", "-an"]
        if duration is not None:
            command += ["-t", str(duration)]
        width = treatment.get("width", 1200)
        command += ["-vf", f"fps={fps},scale=w='min(iw,{width})':h=-1:flags=lanczos",
                    "-compression_level", "1", str(original / "%06d.png")]
        subprocess.run(command, check=True)
        frames = sorted(original.glob("*.png"))
        if not frames:
            raise ValueError("Input contains no decodable video frames")
        for index, frame in enumerate(frames):
            with Image.open(frame) as image:
                result = (frame_processor(image) if frame_processor is not None
                          else treat_image(image, **treatment))
            result.save(treated / frame.name, compress_level=1)
            if index == 0 and poster:
                result.save(root / "poster.png", optimize=True)
        encoded = root / "video.webm"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-framerate", str(fps), "-i", str(treated / "%06d.png"),
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=" + treatment.get("shadow", "#000000"),
            "-an", "-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0",
            "-pix_fmt", "yuv420p", "-deadline", deadline, "-cpu-used", str(cpu_used),
            "-threads", "2", "-row-mt", "1",
            str(encoded),
        ], check=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation protects existing files, including concurrent runs.
        with destination.open("xb") as output, encoded.open("rb") as video:
            shutil.copyfileobj(video, output)
        if poster:
            poster.parent.mkdir(parents=True, exist_ok=True)
            with poster.open("xb") as output, (root / "poster.png").open("rb") as image:
                shutil.copyfileobj(image, output)
        return len(frames)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, help="Output .png image or .webm video")
    parser.add_argument("--shadow", default="#000000")
    parser.add_argument("--highlight", default="#f29191")
    parser.add_argument("--levels", type=int, default=8)
    parser.add_argument("--strength", type=float, default=0.35)
    parser.add_argument("--width", type=int, default=1200, help="Maximum width; never upscales")
    parser.add_argument("--contrast", type=float, default=1.1)
    parser.add_argument("--gamma", type=float, default=1.0, help="Above 1 brightens midtones")
    parser.add_argument("--pattern", choices=("bayer", "ascii", "reticle", "rosa-reticle"), default="bayer",
                        help="rosa-reticle and reticle are experimental; Bayer remains the production default")
    parser.add_argument("--ascii-cell", type=int, default=24,
                        help="ASCII grid cell size in output pixels (8–64)")
    parser.add_argument("--reticle-cell", type=int, default=16,
                        help="Experimental screen size: an even number from 8 to 64")
    parser.add_argument("--rosa-family", choices=FAMILIES, default="islands")
    parser.add_argument("--rosa-scale", type=int, default=16, help="Nominal rosa-reticle scale, 8–64 px")
    parser.add_argument("--rosa-seed", type=int, default=DEFAULT_SEED, help="Fixed 32-bit layout seed")
    parser.add_argument("--fps", type=float, default=24, help="Video output frame rate")
    parser.add_argument("--duration", type=float, help="Optional maximum video duration in seconds")
    parser.add_argument("--crf", type=int, default=18, help="VP9 quality, 0–63; lower is higher quality")
    parser.add_argument("--cpu-used", type=int, default=4,
                        help="VP9 speed, 0–8; higher encodes faster at lower compression efficiency")
    parser.add_argument("--deadline", choices=("good", "realtime"), default="good",
                        help="VP9 encoding profile; realtime supports faster previews")
    parser.add_argument("--poster", type=Path, help="Save first treated video frame as PNG")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Input and output must be different files")
    if args.output.suffix.lower() not in (".png", ".webm"):
        parser.error("Output must use .png for images or .webm for videos")
    if args.output.exists():
        parser.error("Output already exists; choose a new path")
    try:
        if args.output.suffix.lower() == ".webm":
            frames = treat_video(
                args.input, args.output, fps=args.fps, duration=args.duration,
                crf=args.crf, cpu_used=args.cpu_used, deadline=args.deadline,
                poster=args.poster, shadow=args.shadow,
                highlight=args.highlight, levels=args.levels, strength=args.strength,
                width=args.width, contrast=args.contrast, gamma=args.gamma,
                pattern=args.pattern, ascii_cell=args.ascii_cell, reticle_cell=args.reticle_cell,
                rosa_family=args.rosa_family, rosa_scale=args.rosa_scale, rosa_seed=args.rosa_seed,
            )
            print(f"Generated {args.output} ({frames} frames at {args.fps:g} fps)")
            return
        if args.poster or args.duration is not None:
            parser.error("--poster and --duration apply only to video output")
        with Image.open(args.input) as image:
            result = treat_image(
                image, shadow=args.shadow, highlight=args.highlight,
                levels=args.levels, strength=args.strength, width=args.width,
                contrast=args.contrast, gamma=args.gamma,
                pattern=args.pattern, ascii_cell=args.ascii_cell, reticle_cell=args.reticle_cell,
                rosa_family=args.rosa_family, rosa_scale=args.rosa_scale, rosa_seed=args.rosa_seed,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.save(args.output, format="PNG", optimize=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(f"Generated {args.output} ({result.width}×{result.height}, {args.levels} levels)")


if __name__ == "__main__":
    main()
