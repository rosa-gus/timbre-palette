"""Resolve catalog images without coupling images to listening analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit


@dataclass(frozen=True, slots=True)
class ResolvedImage:
    asset_id: str
    resolution: str
    depicted_instrument_slug: str
    alt: str
    caption: str
    url: str
    width: int
    height: int
    shadow: str
    highlight: str
    credit: dict[str, str | None]


class InstrumentImageCatalog:
    """Small, immutable view of the versioned image manifest.

    Missing manifests and unpublished assets resolve to ``None`` so image
    curation cannot make the palette endpoint unavailable.
    """

    def __init__(self, manifest: dict[str, Any] | None = None, *, base_url: str | None = None) -> None:
        if manifest is None:
            manifest = self._read_manifest()
        self._manifest = manifest
        local_base = manifest.get("asset_base_urls", {}).get("local", "http://127.0.0.1:5173/")
        self._base_url = (base_url or local_base).rstrip("/") + "/"
        parsed = urlsplit(self._base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or "<" in self._base_url or ">" in self._base_url:
            raise ValueError("asset base URL must be an absolute HTTP(S) URL without placeholders")
        self.version = str(manifest.get("catalog_version", "images-0.1.0"))
        defaults = manifest.get("defaults", {})
        self._defaults = defaults if isinstance(defaults, dict) else {}
        tones = manifest.get("family_tones", {})
        self._family_tones = tones if isinstance(tones, dict) else {}
        names = manifest.get("family_names", {})
        self._family_names = names if isinstance(names, dict) else {}
        raw_images = manifest.get("images", [])
        self._images = {
            str(item.get("slug")): item
            for item in raw_images
            if isinstance(item, dict) and item.get("slug")
        }
        self._instrument_images = self._mapping(manifest.get("instrument_images"))
        self._family_images = manifest.get("family_images", {})
        self._fallbacks = self._mapping(manifest.get("instrument_fallbacks"))

    @staticmethod
    def _mapping(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            str(key): str(asset)
            for key, asset in value.items()
            if isinstance(asset, str)
        }

    @staticmethod
    def _read_manifest() -> dict[str, Any]:
        path = Path(__file__).with_name("_generated_image_catalog.json")
        if not path.is_file():
            path = Path(__file__).resolve().parents[2] / "catalog" / "instrument-images.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def with_base_url(self, base_url: str) -> InstrumentImageCatalog:
        return InstrumentImageCatalog(self._manifest, base_url=base_url)

    def resolve(self, slug: str, family_slug: str | None = None) -> ResolvedImage | None:
        candidates: list[tuple[str, str]] = []
        if slug in self._instrument_images:
            candidates.append((self._instrument_images[slug], "exact"))
        if slug in self._fallbacks:
            candidates.append((self._fallbacks[slug], "related"))
        family = family_slug or self._family_for(slug)
        family_entry = self._family_images.get(family)
        if isinstance(family_entry, dict) and isinstance(family_entry.get("asset_id"), str):
            candidates.append((family_entry["asset_id"], "family"))
        for asset_id, resolution in candidates:
            item = self._images.get(asset_id)
            if item is None or self._status(item) not in {"approved", "published"}:
                continue
            if any("<hash>" in str(v.get("url", "")) for v in item.get("variants", [])):
                continue
            return self._to_resolved(asset_id, resolution, item, family)
        return None

    def family_tone(self, family_slug: str) -> dict[str, str] | None:
        tone = self._family_tones.get(family_slug)
        if not isinstance(tone, dict):
            return None
        return {key: str(tone[key]) for key in ("shadow", "highlight")}

    def _family_for(self, slug: str) -> str | None:
        item = self._images.get(slug)
        family = item.get("family_slug") if item else None
        return str(family) if family else None

    @staticmethod
    def _status(item: dict[str, Any]) -> str:
        publication = item.get("publication")
        return str(publication.get("status", "draft")) if isinstance(publication, dict) else "draft"

    def _to_resolved(
        self,
        asset_id: str,
        resolution: str,
        item: dict[str, Any],
        family_slug: str | None,
    ) -> ResolvedImage:
        treatment = dict(self._defaults)
        treatment.update(self.family_tone(str(item.get("family_slug"))) or {})
        treatment.update(item.get("treatment") if isinstance(item.get("treatment"), dict) else {})
        variants = item.get("variants") if isinstance(item.get("variants"), list) else []
        variant = next((v for v in variants if isinstance(v, dict) and v.get("name") == "detail"), None)
        if variant is None:
            variant = next((v for v in variants if isinstance(v, dict)), None)
        variant = variant or {}
        publication = item.get("publication")
        published_url = publication.get("url") if isinstance(publication, dict) else None
        url = variant.get("url") or published_url or item.get("output")
        if not isinstance(url, str):
            url = ""
        url = urljoin(self._base_url, url)
        width = int(variant.get("width", 0) or 0)
        height = int(variant.get("height", 0) or 0)
        depicted = str(item.get("instrument_slug") or item.get("slug"))
        label = item.get("depicted_name") or depicted
        caption = f"Imagem do instrumento {label}."
        family_name = self._family_names.get(family_slug, family_slug or "instrumental")
        if resolution == "family":
            caption = f"Imagem ilustrativa da família {family_name}: {label}."
        elif resolution == "related":
            caption = f"Imagem relacionada ao instrumento {label}."
        credit = item.get("credit") if isinstance(item.get("credit"), dict) else {}
        return ResolvedImage(
            asset_id=asset_id,
            resolution=resolution,
            depicted_instrument_slug=depicted,
            alt=str(item.get("alt", f"Imagem de {label}.")),
            caption=caption,
            url=url,
            width=width,
            height=height,
            shadow=str(treatment.get("shadow", "#000000")),
            highlight=str(treatment.get("highlight", "#f29191")),
            credit={key: value if isinstance(value, str) else None for key, value in credit.items()},
        )


DEFAULT_IMAGE_CATALOG = InstrumentImageCatalog()
