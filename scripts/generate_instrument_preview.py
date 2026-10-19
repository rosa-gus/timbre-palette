"""Extract a small, sourced instrument preview from the editorial catalog."""

import json
from pathlib import Path


def generate(root: Path) -> None:
    content = root / "editorial/content"
    entities = json.loads((content / "entities.json").read_text())
    sources = {row["id"]: row for row in json.loads((content / "sources.json").read_text())}
    image_catalog = json.loads(
        (root / "reference/server-assembly/src/palette_api/_generated_image_catalog.json").read_text()
    )
    entity = next(row for row in entities if row["slug"] == "sampler")
    family_tone = image_catalog["family_tones"][entity["family_slug"]]
    image = next(
        row for row in image_catalog["images"] if row["slug"] == "sampler-ricardo-abreu-01"
    )
    image_variant = image["variants"][0]
    result = {}
    for locale in ("pt-BR", "en-US"):
        rows = json.loads((content / "locales" / f"{locale}.json").read_text())
        instrument = next(row for row in rows if row["slug"] == entity["slug"])
        if instrument["status"] not in {"published", "reviewed"}:
            raise ValueError(f"Unreviewed preview translation: {locale}")
        section = next(row for row in entity["sections"] if row["kind"] == "curiosity")
        curiosity = next(row for row in instrument["sections"] if row["id"] == section["id"])
        source_ids = dict.fromkeys([
            *entity["text_citations"]["sound_production"],
            *(citation["source_id"] for citation in section["citations"]),
        ])
        result[locale] = {
            "slug": entity["slug"],
            "name": instrument["name"],
            "family": next(row["name"] for row in rows if row["slug"] == entity["family_slug"]),
            "image": {
                "url": image["publication"]["url"],
                "alt": instrument["image"]["alt"],
                "caption": image["depicted_name"],
                "credit": image["credit"],
                "width": image_variant["width"],
                "height": image_variant["height"],
                "tone": family_tone,
            },
            "soundProduction": instrument["sound_production"],
            "curiosity": curiosity["text"],
            "sources": [
                {key: sources[source_id][key] for key in ("title", "publisher", "url")}
                for source_id in source_ids
            ],
        }
    destination = root / "web/src/analysis/instrument-preview.generated.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1])
