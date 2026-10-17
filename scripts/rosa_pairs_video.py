#!/usr/bin/env python3
"""Apply experimental rosa-reticle study 04 to a complete video, offline."""

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageEnhance, ImageOps

if __package__:
    from .rosa_pairs import pair_screen, pairs_gray
    from .rosa_shadow_study import SHADOW_PALETTE
    from .rosa_tonal import CURVE, curve_lut, duotone, prepare_source
    from .deprecated_treat_instrument import treat_video
else:
    from rosa_pairs import pair_screen, pairs_gray
    from rosa_shadow_study import SHADOW_PALETTE
    from rosa_tonal import CURVE, curve_lut, duotone, prepare_source
    from deprecated_treat_instrument import treat_video


def process_frame(image: Image.Image, width: int = 1200) -> Image.Image:
    rgb = prepare_source(image, width)
    base = ImageEnhance.Contrast(ImageOps.grayscale(rgb)).enhance(1.1).point(curve_lut())
    return duotone(pairs_gray(base))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--crf", type=int, default=14)
    parser.add_argument("--cpu-used", type=int, default=8)
    parser.add_argument("--deadline", choices=("good", "realtime"), default="realtime")
    args = parser.parse_args()
    if args.width < 1:
        parser.error("width must be positive")
    poster, manifest = args.output.with_suffix(".png"), args.output.with_suffix(".json")
    if any(path.exists() for path in (args.output, poster, manifest)):
        parser.error("Choose a new output; existing video, poster and manifest are preserved")
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=avg_frame_rate,r_frame_rate,width,height", "-of", "json", str(args.source),
    ]))
    stream = probe["streams"][0]
    fps = Fraction(stream["avg_frame_rate"])
    if fps <= 0:
        fps = Fraction(stream["r_frame_rate"])
    print(f"Experimental study 04 / full video / {fps} fps / width {args.width} / CRF {args.crf}", flush=True)
    frames = treat_video(
        args.source, args.output, fps=fps, crf=args.crf, cpu_used=args.cpu_used, deadline=args.deadline,
        poster=poster, width=args.width,
        frame_processor=lambda image: process_frame(image, args.width),
    )
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == source_hash
    metadata = {
        "experiment": "rosa-reticle", "study": "04", "status": "experimental",
        "source": str(args.source), "source_sha256": source_hash,
        "video": str(args.output), "poster": str(poster), "frames": frames,
        "fps": str(fps), "width": args.width, "contrast": 1.1,
        "curve": CURVE, "palette": SHADOW_PALETTE, "ranks": pair_screen(),
        "signature_gate": {"fade_in": [.035, .08], "fade_out": [.14, .24], "peak": .85},
        "encoding": {"codec": "VP9", "crf": args.crf, "cpu_used": args.cpu_used, "deadline": args.deadline,
                     "pixel_format": "yuv420p", "audio": False, "padding": "black to even dimensions"},
        "poster_note": "First treated frame before lossy encoding and even-dimension padding",
    }
    with manifest.open("x") as output:
        json.dump(metadata, output, indent=2)
        output.write("\n")
    print(f"Saved {frames} frames: {args.output}; poster: {poster}", flush=True)


if __name__ == "__main__":
    main()
