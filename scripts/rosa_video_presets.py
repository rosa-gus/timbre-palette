"""Delivery presets for rosa-reticle 0.1.0 grayscale video."""

PRESETS = {
    "av1": ["-c:v", "libsvtav1", "-crf", "24", "-preset", "6",
            "-svtav1-params", "lp=2", "-pix_fmt", "yuv420p"],
    "vp9": ["-c:v", "libvpx-vp9", "-crf", "26", "-b:v", "0",
            "-deadline", "good", "-cpu-used", "4", "-row-mt", "1",
            "-pix_fmt", "yuv420p"],
}
