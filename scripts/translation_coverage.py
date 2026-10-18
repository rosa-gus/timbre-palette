"""Count current, approved editorial resources without counting fallback text."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.editorial_content import DEFAULT_LOCALE, read_snapshot, source_revision
from scripts.publish_editorial import load_manifest


def editorial_coverage(sheets: list[dict], locales: list[str]) -> dict[str, dict[str, int]]:
    def approved(sheet: dict) -> bool:
        review = sheet["review"]
        return (sheet.get("status") in {"reviewed", "published"}
                and bool(review.get("claim_support_verified"))
                and bool(review.get("reviewer")) and bool(review.get("reviewed_at")))

    sources = [sheet for sheet in sheets if approved(sheet)]
    coverage = {locale: {"translated": 0, "total": len(sources)} for locale in locales}
    for sheet in sources:
        coverage[DEFAULT_LOCALE]["translated"] += 1
        revision = source_revision(sheet)
        for translation in sheet.get("translations", []):
            if approved(translation) and translation["source_revision"] == revision:
                coverage[translation["locale"]]["translated"] += 1
    return coverage


if __name__ == "__main__":
    manifest = Path(__file__).resolve().parent.parent / "editorial/content/catalog.json"
    payload = read_snapshot(manifest)
    print(json.dumps(editorial_coverage(load_manifest(manifest), list(payload["locales"])), sort_keys=True))
