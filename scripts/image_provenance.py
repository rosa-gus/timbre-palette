"""Generation records shared by the instrument CLI and batch preparer."""

from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import tempfile

from PIL import Image, __version__ as pillow_version


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else digest(source.read())


def recipe(renderer, version: str, options: dict) -> dict:
    """Resolve actual function defaults and fingerprint its implementation."""
    try:
        bound = inspect.signature(renderer).bind(None, **options)
    except TypeError as error:
        raise ValueError(f"Invalid image treatment options: {error}") from error
    bound.apply_defaults()
    resolved = {key: value for key, value in bound.arguments.items() if key != "image"}
    directory = Path(__file__).resolve().parent
    files = [Path(inspect.getfile(renderer))]
    if version == "rosa-reticle-0.1.0":
        files.append(directory / "rosa_reticle.py")
    else:
        files.extend(directory / name for name in ("deprecated_rosa_reticle.py", "experimental_reticle.py"))
    result = {
        "treatment_version": version, "parameters": resolved,
        "implementation": {f"scripts/{path.name}": file_digest(path) for path in files},
        "runtime": {"python": platform.python_version(), "pillow": pillow_version},
        "encoding": {"format": "PNG", "mode": "RGB", "optimize": True, "source_metadata": False},
    }
    if version == "rosa-reticle-0.1.0":
        if __package__:
            from .rosa_reticle import CURVE, SHADOW_PALETTE, pair_screen
        else:
            from rosa_reticle import CURVE, SHADOW_PALETTE, pair_screen
        result["tonal_curve"] = CURVE
        result["tonal_palette"] = SHADOW_PALETTE
        result["screen_ranks"] = pair_screen()
    return json.loads(json.dumps(result))


def output_info(path: Path) -> dict:
    with Image.open(path) as image:
        return {"sha256": file_digest(path), "bytes": path.stat().st_size,
                "dimensions": list(image.size), "mode": image.mode, "format": image.format}


def generation_record(*, slug: str | None, family: str | None, family_tone: dict,
                      source_path: str, source_bytes: bytes, source_image: Image.Image,
                      destination: Path, output_path: str, treatment: dict) -> dict:
    return {
        "provenance": "recorded", "generated_at": now(), "slug": slug,
        "family_slug": family, "family_tone": family_tone,
        "source": {"path": source_path, "sha256": digest(source_bytes),
                   "bytes": len(source_bytes), "dimensions": list(source_image.size),
                   "mode": source_image.mode, "format": source_image.format},
        "output": {"path": output_path, **output_info(destination)},
        "treatment": treatment,
    }


def write_json(path: Path, document: dict) -> None:
    """Replace a generation log atomically, even if a batch is interrupted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(document, output, indent=2, ensure_ascii=False)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
