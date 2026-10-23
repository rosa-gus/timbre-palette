"""Generate the static instrument and palette previews used on the entry page."""

import json
import math
from pathlib import Path


CONFIDENCE_WEIGHT = {
    "documented": 1,
    "strongly_associated": 0.75,
    "estimated": 0.45,
}
PERIOD = "1month"
SAMPLE_ID = "entry-palette-preview"


def seeded_random(seed: str):
    state = 2_166_136_261
    for character in seed:
        state = ((state ^ ord(character)) * 16_777_619) & 0xFFFFFFFF
    if state == 0:
        state = 0x6D2B79F5

    def random():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        value = state
        value = ((value ^ (value >> 15)) * (value | 1)) & 0xFFFFFFFF
        value ^= (value + (((value ^ (value >> 7)) * (value | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((value ^ (value >> 14)) & 0xFFFFFFFF) / 4_294_967_296

    return random


def round4(value: float) -> float:
    return math.floor((value + 1e-12) * 10_000 + 0.5) / 10_000


def generate_palette_preview(root: Path, content: Path, image_catalog: dict) -> None:
    fixture = json.loads(
        (root / "reference/server-assembly/src/palette_api/_curated_example_history.json").read_text()
    )
    locales = {
        locale: {
            row["slug"]: row["name"]
            for row in json.loads((content / "locales" / f"{locale}.json").read_text())
        }
        for locale in ("pt-BR", "en-US")
    }
    family_tones = image_catalog.get("family_tones", {})
    recordings = [
        row for row in fixture["recordings"]
        if isinstance(row.get("layers"), list) and row["layers"]
    ]
    qualified_artists = {
        row["artist_mbid"].lower()
        for row in fixture["artist_vocabulary"]
        if row["distinct_recordings"] >= 3
    }
    random = seeded_random(f"{SAMPLE_ID}:{PERIOD}")
    direct = recordings[:]
    other = [
        row for row in fixture["recordings"]
        if not isinstance(row.get("layers"), list) or not row["layers"]
    ]
    # This mirrors the deterministic fixture selection in browser.ts.
    def shuffle(items):
        items = items[:]
        for index in range(len(items) - 1, 0, -1):
            other_index = int(random() * (index + 1))
            items[index], items[other_index] = items[other_index], items[index]
        return items

    direct, other = shuffle(direct), shuffle(other)
    selected = []
    selected_mbids = set()
    artist_counts = {}

    def add(recording):
        mbid = recording.get("mbid")
        if not mbid or mbid in selected_mbids:
            return
        selected.append(recording)
        selected_mbids.add(mbid)
        artist = recording.get("artist_mbid", "").lower()
        artist_counts[artist] = artist_counts.get(artist, 0) + 1

    def add_candidates(candidates, quota):
        initial_count = len(selected)
        for require_new_artist in (True, False):
            for recording in candidates:
                if len(selected) - initial_count >= quota:
                    return
                mbid = recording.get("mbid")
                if not mbid or mbid in selected_mbids:
                    continue
                artist = recording.get("artist_mbid", "").lower()
                count = artist_counts.get(artist, 0)
                if require_new_artist and count:
                    continue
                if count >= fixture["max_recordings_per_artist"]:
                    continue
                add(recording)

    target = max(5, fixture["target_recordings"])
    other_quota = min(len(other), target // 3)
    priority_artists = {
        row["artist_mbid"].lower()
        for row in fixture["artist_vocabulary"]
        if row["distinct_recordings"] >= 3
    }
    for recording in direct + other:
        artist = recording.get("artist_mbid", "").lower()
        if artist in priority_artists and not artist_counts.get(artist):
            add(recording)
    add_candidates(direct, target - other_quota)
    add_candidates(other, target - len(selected))
    add_candidates(direct + other, target - len(selected))

    scores = {}
    confidence_scores = {}
    evidence = {}
    names = {}
    for recording in selected:
        artist_mbid = recording.get("artist_mbid", "").lower()
        plays = 12 if artist_mbid in qualified_artists else int(random() * 11) + 2
        plays *= fixture["period_multipliers"][PERIOD]
        by_family = {}
        for layer in recording["layers"]:
            by_family.setdefault(layer["family_slug"], []).append(layer)
            names.setdefault(layer["family_slug"], layer["family_name"])
        strongest = {}
        for family, layers in by_family.items():
            strongest[family] = sorted(
                layers,
                key=lambda layer: (
                    -(layer["prominence"] * CONFIDENCE_WEIGHT.get(layer["confidence"], 1)),
                    0 if layer.get("claim_level") == "instrument" else 1,
                    layer["slug"],
                ),
            )[0]
        total_weight = sum(
            layer["prominence"] * CONFIDENCE_WEIGHT.get(layer["confidence"], 1)
            for layer in strongest.values()
        )
        if total_weight <= 0:
            continue
        key = recording["mbid"]
        for family, layer in strongest.items():
            score = plays * layer["prominence"] * CONFIDENCE_WEIGHT.get(layer["confidence"], 1) / total_weight
            scores[family] = scores.get(family, 0) + score
            confidence_scores[family] = confidence_scores.get(family, 0) + score * CONFIDENCE_WEIGHT.get(layer["confidence"], 1)
            evidence.setdefault(family, set()).add(key)

    total_score = sum(scores.values())
    ordered = sorted(scores, key=lambda family: (-scores[family], family))
    result = {}
    for locale in ("pt-BR", "en-US"):
        families = []
        for family in ordered[:3]:
            confidence_ratio = confidence_scores[family] / scores[family]
            confidence = (
                "documented" if confidence_ratio >= 0.9
                else "strongly_associated" if confidence_ratio >= 0.65
                else "estimated"
            )
            tone = family_tones.get(family)
            families.append({
                "locale": locale,
                "slug": family,
                "name": locales[locale].get(family, names[family]),
                "share": round4(scores[family] / total_score),
                "evidence_count": len(evidence[family]),
                "confidence": confidence,
                "image": None,
                "tone": tone,
            })
        result[locale] = families
    destination = root / "web/src/analysis/palette-preview.generated.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


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
                "caption": instrument["image"]["caption"],
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
    generate_palette_preview(root, content, image_catalog)


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1])
