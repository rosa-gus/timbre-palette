#!/usr/bin/env python3
"""Experimental encoding comparison from identical study-04 treated PNG frames.

Input: numbered PNGs starting at 000001.png, 24000/1001 fps. No image treatment
is altered. Decode three frames per candidate for shadow-detail diagnostics.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time

from PIL import Image, ImageFilter, ImageDraw, ImageFont

if __package__:
    from .rosa_tonal import duotone
else:
    from rosa_tonal import duotone


PRESETS = {
    "vp9-current": ["-c:v", "libvpx-vp9", "-crf", "14", "-b:v", "0", "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1", "-pix_fmt", "yuv420p"],
    "vp9-efficient": ["-c:v", "libvpx-vp9", "-crf", "18", "-b:v", "0", "-deadline", "good", "-cpu-used", "4", "-row-mt", "1", "-pix_fmt", "yuv420p"],
    "vp9-quality": ["-c:v", "libvpx-vp9", "-crf", "8", "-b:v", "0", "-deadline", "good", "-cpu-used", "4", "-row-mt", "1", "-pix_fmt", "yuv420p"],
    "vp9-chroma": ["-c:v", "libvpx-vp9", "-crf", "14", "-b:v", "0", "-deadline", "good", "-cpu-used", "4", "-row-mt", "1", "-pix_fmt", "yuv444p"],
    "av1-quality": ["-c:v", "libsvtav1", "-crf", "20", "-preset", "6", "-svtav1-params", "lp=2", "-pix_fmt", "yuv420p"],
    "vp9-gray": ["-c:v", "libvpx-vp9", "-crf", "18", "-b:v", "0", "-deadline", "good", "-cpu-used", "4", "-row-mt", "1", "-pix_fmt", "yuv420p"],
    "av1-gray": ["-c:v", "libsvtav1", "-crf", "20", "-preset", "6", "-svtav1-params", "lp=2", "-pix_fmt", "yuv420p"],
    "vp9-gray-light": ["-c:v", "libvpx-vp9", "-crf", "26", "-b:v", "0", "-deadline", "good", "-cpu-used", "4", "-row-mt", "1", "-pix_fmt", "yuv420p"],
    "av1-gray-light": ["-c:v", "libsvtav1", "-crf", "24", "-preset", "6", "-svtav1-params", "lp=2", "-pix_fmt", "yuv420p"],
}


def encode(name: str, frames: Path, output: Path) -> None:
    start = time.monotonic()
    if "-gray" in name:
        frames = frames.parent / "gray-transport"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                    "-framerate", "24000/1001", "-i", str(frames / "%06d.png"),
                    "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=black", "-an",
                    *PRESETS[name], "-threads", "2", str(output / f"{name}.webm")], check=True)
    print(f"Encoded {name}: {time.monotonic()-start:.1f}s", flush=True)


def shadow_metrics(reference: Image.Image, decoded: Image.Image) -> dict:
    # Red carries the full-range pink amplitude. Evaluate only source shadow
    # tones, avoiding the large black areas that inflate whole-image PSNR.
    a, b = reference.getchannel("R"), decoded.getchannel("R")
    ab, bb = a.filter(ImageFilter.GaussianBlur(1)), b.filter(ImageFilter.GaussianBlur(1))
    count, squared, signal, projection, reconstructed = 0, 0, 0, 0, 0
    for expected, actual, low_a, low_b in zip(a.tobytes(), b.tobytes(), ab.tobytes(), bb.tobytes()):
        if 12 <= expected <= 120:
            count += 1
            squared += (expected - actual) ** 2
            high_a, high_b = expected-low_a, actual-low_b
            signal += high_a ** 2
            projection += high_a * high_b
            reconstructed += high_b ** 2
    return {"shadow_red_rmse": math.sqrt(squared/count),
            "shadow_highpass_gain": projection/signal,
            "shadow_highpass_correlation": projection/math.sqrt(signal*reconstructed)}


def analyze(frames: Path, output: Path) -> None:
    count = len(list(frames.glob("*.png")))
    indices = (0, count//2, count-1)
    report = {"status": "experimental", "frames": count, "fps": "24000/1001",
              "duration": count*1001/24000, "sampled_indices": indices,
              "note": "Shadow metrics use red 12..120 of the reference; highpass is R minus Gaussian sigma=1. Gain/correlation are diagnostics, not aesthetic scores. Sample sizes do not predict complete-clip sizes exactly.",
              "presets": {}}
    first_frames = {}
    for name, settings in PRESETS.items():
        path = output / f"{name}.webm"
        with tempfile.TemporaryDirectory(prefix="rosa-quality-decode-") as directory:
            selection = "+".join(f"eq(n\\,{i})" for i in indices)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                            "-i", str(path), "-vf", f"select={selection}", "-fps_mode", "vfr",
                            str(Path(directory)/"%03d.png")], check=True)
            metrics = []
            for j, index in enumerate(indices):
                with Image.open(frames/f"{index+1:06d}.png") as ref, Image.open(Path(directory)/f"{j+1:03d}.png") as raw:
                    decoded = raw.convert("RGB").crop((0, 0, ref.width, ref.height))
                    if "-gray" in name:
                        decoded = duotone(decoded.getchannel("R"))
                    metrics.append(shadow_metrics(ref, decoded))
                    if j == 0:
                        first_frames[name] = decoded.copy()
        report["presets"][name] = {"bytes": path.stat().st_size, "settings": settings,
            **{key: sum(m[key] for m in metrics)/len(metrics) for key in metrics[0]}}
        print(name, report["presets"][name], flush=True)
    with Image.open(frames/"000001.png") as reference:
        first_frames = {"uncompressed": reference.copy(), **first_frames}
    board = Image.new("RGB", (len(first_frames)*256, 628), "#080808")
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default(size=16)
    for i, (name, image) in enumerate(first_frames.items()):
        x = i*256
        draw.text((x+8, 12), name, font=font, fill="#eeeeee")
        for row, bounds in enumerate(((770, 385, 890, 505), (630, 460, 750, 580))):
            board.paste(image.crop(bounds).resize((240, 240), Image.Resampling.NEAREST), (x+8, 50+row*280))
    board.save(output/"crops.png")
    (output/"report.json").write_text(json.dumps(report, indent=2)+"\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--append", action="store_true", help="Keep encoded candidates and generate missing ones")
    args = parser.parse_args()
    if not args.analyze_only:
        if args.output.exists() and not args.append:
            parser.error("Choose a new output directory")
        args.output.mkdir(parents=True, exist_ok=True)
        gray_dir = args.frames.parent / "gray-transport"
        gray_dir.mkdir(exist_ok=True)
        for path in sorted(args.frames.glob("*.png")):
            target = gray_dir/path.name
            if not target.exists():
                with Image.open(path) as frame:
                    gray = frame.getchannel("R").point([min(255, round(v*255/242)) for v in range(256)])
                    gray.convert("RGB").save(target, compress_level=1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(encode, name, args.frames, args.output) for name in PRESETS
                       if not (args.output/f"{name}.webm").exists()]
            for future in futures:
                future.result()
    analyze(args.frames, args.output)


if __name__ == "__main__":
    main()
