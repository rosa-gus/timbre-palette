"""Locale-specific editorial snapshots and source revision tracking."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_LOCALE = "pt-BR"
NEUTRAL_FIELDS = ("data_source", "catalog_version", "image_catalog_version", "slug", "kind", "family_slug", "related_slugs", "tone")


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def source_revision(sheet: dict[str, Any]) -> str:
    source = copy.deepcopy({k: sheet[k] for k in ("resource", "review", "text_citations")})
    source["review"].pop("source_metadata_verified", None)
    for block in source["resource"]["sections"]:
        block["review"].pop("source_metadata_verified", None)
    return hashlib.sha256(canonical(source).encode()).hexdigest()


def split_snapshot(sheets: list[dict[str, Any]]) -> dict[str, Any]:
    entities, texts, sources = [], [], {}
    for sheet in sheets:
        resource = sheet["resource"]
        entity = {key: resource[key] for key in NEUTRAL_FIELDS}
        entity.update(source_ids=[source["id"] for source in resource["sources"]],
                      text_citations=sheet["text_citations"], further_reading=resource["further_reading"],
                      sections=[{key: block[key] for key in ("id", "kind", "content_type", "citations")} for block in resource["sections"]])
        image = copy.deepcopy(resource["image"])
        image_text = None
        if image:
            image_text = {key: image.pop(key) for key in ("alt", "caption")}
            image_text["asset_id"] = image["asset_id"]
        entity["image"] = image
        entities.append(entity)
        sources.update({source["id"]: source for source in resource["sources"]})
        texts.append(dict(slug=resource["slug"], name=resource["name"], description=resource["description"],
                          sound_production=resource["sound_production"], common_roles=resource["common_roles"],
                          sections=[{key: block[key] for key in ("id", "text", "status", "review")} for block in resource["sections"]],
                          image=image_text, review=sheet["review"], status="published"))
    return dict(schema_version=2, source_locale=DEFAULT_LOCALE, entities=entities,
                sources=list(sources.values()), locales={DEFAULT_LOCALE: texts})


def read_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("schema_version") == 2 and isinstance(payload.get("entities"), str):
        root = path.parent
        payload["entities"] = json.loads((root / payload["entities"]).read_text())
        payload["sources"] = json.loads((root / payload["sources"]).read_text())
        payload["locales"] = {locale: json.loads((root / filename).read_text()) for locale, filename in payload["locales"].items()}
    return payload


def write_snapshot(payload: dict[str, Any], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "locales").mkdir(exist_ok=True)
    def write(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name in ("entities", "sources"):
        write(directory / f"{name}.json", payload[name])
    locales = {}
    for locale, texts in sorted(payload["locales"].items()):
        locales[locale] = f"locales/{locale}.json"
        write(directory / locales[locale], texts)
    write(directory / "catalog.json", dict(schema_version=2, source_locale=DEFAULT_LOCALE,
          entities="entities.json", sources="sources.json", locales=locales))


def expand_snapshot(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("source_locale") != DEFAULT_LOCALE:
        raise ValueError("The source locale must be pt-BR.")
    entities = payload["entities"]
    sources = payload["sources"]
    locales = payload["locales"]
    if not isinstance(entities, list) or not isinstance(sources, list) or not isinstance(locales, dict):
        raise ValueError("Invalid editorial content groups.")
    source_by_id = {source["id"]: source for source in sources}
    if len(source_by_id) != len(sources):
        raise ValueError("Duplicate source id.")
    entity_by_slug = {entity["slug"]: entity for entity in entities}
    if len(entity_by_slug) != len(entities):
        raise ValueError("Duplicate entity slug.")
    for locale, texts in locales.items():
        # Canonical tags only; runtime negotiation uses Intl.getCanonicalLocales.
        if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?", locale):
            raise ValueError(f"Invalid or noncanonical content locale: {locale}.")
        if not isinstance(texts, list) or len({text["slug"] for text in texts}) != len(texts):
            raise ValueError(f"{locale}: duplicate resource translation.")
        for text in texts:
            if text["slug"] not in entity_by_slug:
                raise ValueError(f"{locale}: unknown resource {text['slug']}.")
    base_texts = {text["slug"]: text for text in locales[DEFAULT_LOCALE]}
    if base_texts.keys() != entity_by_slug.keys():
        raise ValueError("Every entity requires a source-locale resource.")

    def expand(entity: dict, text: dict, locale: str, stale: bool = False) -> dict:
        allowed = {"slug", "name", "description", "sound_production", "common_roles", "sections", "image", "review", "status", "source_revision"}
        if set(text) - allowed:
            raise ValueError(f"{locale}/{entity['slug']}: localized text cannot override neutral fields.")
        if any(not isinstance(text.get(field), str) for field in ("name", "description", "sound_production")) or not isinstance(text.get("common_roles"), list) or any(not isinstance(role, str) for role in text["common_roles"]):
            raise ValueError(f"{locale}/{entity['slug']}: invalid translated text.")
        for block in text["sections"]:
            if set(block) - {"id", "text", "status", "review"} or not isinstance(block.get("text"), str):
                raise ValueError(f"{locale}/{entity['slug']}: invalid block translation.")
        base_ids = {block["id"] for block in entity["sections"]}
        translated = {block["id"]: block for block in text["sections"]}
        if len(translated) != len(text["sections"]) or (not stale and translated.keys() != base_ids):
            raise ValueError(f"{locale}/{entity['slug']}: translate every block exactly once.")
        resource = {key: entity[key] for key in NEUTRAL_FIELDS}
        resource.update({key: text[key] for key in ("name", "description", "sound_production", "common_roles")})
        blocks = {block["id"]: block for block in entity["sections"]}
        resource.update(sections=[{**blocks.get(block_id, dict(kind="curiosity", content_type="editorial_summary", citations=[])), **block} for block_id, block in translated.items()],
                        sources=[source_by_id[source_id] for source_id in entity["source_ids"]],
                        further_reading=entity["further_reading"], image=None)
        if entity["image"]:
            if not stale and (not text.get("image") or text["image"]["asset_id"] != entity["image"]["asset_id"]):
                raise ValueError(f"{locale}/{entity['slug']}: image translation must match its asset.")
            resource["image"] = {**entity["image"], **text["image"]} if text.get("image") else None
        elif text.get("image") and not stale:
            raise ValueError(f"{locale}/{entity['slug']}: unexpected image translation.")
        status = text.get("status")
        if status not in {"draft", "reviewed", "published", "deprecated", "stale"}:
            raise ValueError(f"{locale}/{entity['slug']}: invalid translation status.")
        if locale != DEFAULT_LOCALE and not re.fullmatch(r"[a-f0-9]{64}", text.get("source_revision", "")):
            raise ValueError(f"{locale}/{entity['slug']}: source_revision must be a SHA-256 digest.")
        if not stale and status in {"reviewed", "published"} and not (text["review"].get("claim_support_verified") and text["review"].get("reviewer") and text["review"].get("reviewed_at")):
            raise ValueError(f"{locale}/{entity['slug']}: independent translation review is required.")
        if not stale and status in {"reviewed", "published"} and resource["image"] and any(not isinstance(resource["image"].get(field), str) or not resource["image"][field].strip() for field in ("alt", "caption")):
            raise ValueError(f"{locale}/{entity['slug']}: reviewed image text is required.")
        return dict(resource=resource, review=text["review"], text_citations=entity["text_citations"],
                    locale=locale, status=status, source_revision=text.get("source_revision"))

    sheets = [expand(entity, base_texts[entity["slug"]], DEFAULT_LOCALE) for entity in entities]
    for sheet in sheets:
        sheet["source_revision"] = source_revision(sheet)
        sheet["translations"] = []
    by_slug = {sheet["resource"]["slug"]: sheet for sheet in sheets}
    for locale, texts in locales.items():
        if locale == DEFAULT_LOCALE:
            continue
        for text in texts:
            base = by_slug[text["slug"]]
            stale = text.get("source_revision") != base["source_revision"]
            translation = expand(entity_by_slug[text["slug"]], text, locale, stale)
            if stale:
                translation["status"] = "stale"
            base["translations"].append(translation)
    return sheets


def public_content(sheet: dict[str, Any]) -> dict[str, Any]:
    resource = copy.deepcopy(sheet["resource"])
    sources = {source["id"]: source for source in resource["sources"]}
    resource["sections"] = [block for block in resource["sections"] if
        block["status"] in {"sourced", "reviewed", "published"} and block["review"].get("claim_support_verified") and
        block["citations"] and all(sources[citation["source_id"]].get("metadata_verified") for citation in block["citations"])]
    resource["further_reading"] = [{key: reading.get(key) for key in ("title", "url", "publisher")} for reading in resource["further_reading"] if reading.get("status") in {"reviewed", "published"}]
    # Asset URLs and attribution are resolved from the independent image catalog.
    if resource["image"]:
        resource["image"] = {key: resource["image"][key] for key in ("asset_id", "alt", "caption")}
    return resource
