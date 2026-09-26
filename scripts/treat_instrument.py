#!/usr/bin/env python3
"""Generate editorial duotone PNGs or WebM videos with ordered Bayer 4×4.

Requires Pillow: python3 -m pip install 'Pillow>=10,<13'
Videos also require FFmpeg with the libvpx-vp9 encoder.
Run offline, before publishing assets; no image processing in HTTP requests.
"""

import argparse
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageColor, ImageEnhance, ImageOps


BAYER_4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


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
) -> Image.Image:
    """Resize first, then quantize luminance and map it onto an sRGB palette.

    Strength scales a centered Bayer threshold by one quantization step.
    Zero gives plain posterization; one gives full ordered dithering.
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
    poster: Path | None = None,
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
    if poster and (poster.suffix.lower() != ".png" or poster.exists()
                   or poster.resolve() in (source.resolve(), destination.resolve())):
        raise ValueError("Poster must be a new .png file distinct from input and output")
    # Validate treatment parameters before decoding any frames.
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
                result = treat_image(image, **treatment)
            result.save(treated / frame.name, compress_level=1)
            if index == 0 and poster:
                result.save(root / "poster.png", optimize=True)
        encoded = root / "video.webm"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-framerate", str(fps), "-i", str(treated / "%06d.png"),
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=" + treatment.get("shadow", "#000000"),
            "-an", "-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0",
            "-pix_fmt", "yuv420p", "-deadline", "good", "-cpu-used", "4",
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
    parser.add_argument("--fps", type=float, default=24, help="Video output frame rate")
    parser.add_argument("--duration", type=float, help="Optional maximum video duration in seconds")
    parser.add_argument("--crf", type=int, default=18, help="VP9 quality, 0–63; lower is higher quality")
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
                crf=args.crf, poster=args.poster, shadow=args.shadow,
                highlight=args.highlight, levels=args.levels, strength=args.strength,
                width=args.width, contrast=args.contrast, gamma=args.gamma,
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
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.save(args.output, format="PNG", optimize=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(f"Generated {args.output} ({result.width}×{result.height}, {args.levels} levels)")


if __name__ == "__main__":
    main()
