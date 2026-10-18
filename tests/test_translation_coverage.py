import copy
from pathlib import Path

import pytest

from scripts.editorial_content import expand_snapshot, read_snapshot
from scripts.translation_coverage import editorial_coverage

MANIFEST = Path(__file__).resolve().parent.parent / "editorial/content/catalog.json"


def fixture():
    return copy.deepcopy(read_snapshot(MANIFEST))


def test_counts_current_approved_resources_in_the_committed_snapshot():
    payload = fixture()
    coverage = editorial_coverage(expand_snapshot(payload), list(payload["locales"]))
    assert coverage == {locale: {"translated": 23, "total": 23} for locale in ("pt-BR", "en-US")}


@pytest.mark.parametrize("change", ["draft", "stale", "deprecated", "missing", "reviewer", "date", "approval"])
def test_excludes_unavailable_translations_without_counting_portuguese_fallback(change):
    payload = fixture()
    text = payload["locales"]["en-US"][0]
    if change in {"draft", "deprecated"}:
        text["status"] = change
    elif change == "stale":
        text["source_revision"] = "0" * 64
    elif change == "missing":
        payload["locales"]["en-US"].pop(0)
    sheets = expand_snapshot(payload)
    if change in {"reviewer", "date", "approval"}:
        review = sheets[0]["translations"][0]["review"]
        review[{"reviewer": "reviewer", "date": "reviewed_at", "approval": "claim_support_verified"}[change]] = None
    coverage = editorial_coverage(sheets, list(payload["locales"]))
    assert coverage["en-US"] == {"translated": 22, "total": 23}
    assert coverage["pt-BR"] == {"translated": 23, "total": 23}


@pytest.mark.parametrize("status", ["deprecated", "draft", "stale"])
def test_excludes_unpublishable_sources_from_every_denominator(status):
    payload = fixture()
    payload["locales"]["pt-BR"][0]["status"] = status
    coverage = editorial_coverage(expand_snapshot(payload), list(payload["locales"]))
    assert coverage == {locale: {"translated": 22, "total": 22} for locale in ("pt-BR", "en-US")}


def test_reports_zero_when_no_source_is_publishable_and_includes_empty_locales():
    payload = fixture()
    for text in payload["locales"]["pt-BR"]:
        text["status"] = "deprecated"
    payload["locales"]["fr"] = []
    assert editorial_coverage(expand_snapshot(payload), list(payload["locales"])) == {
        locale: {"translated": 0, "total": 0} for locale in payload["locales"]
    }
