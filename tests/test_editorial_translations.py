import copy
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.editorial_content import expand_snapshot, read_snapshot, source_revision, split_snapshot
from scripts.publish_editorial import emit_sql, load_manifest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "editorial/content/catalog.json"


def snapshot_with_translation():
    payload = read_snapshot(MANIFEST)
    text = copy.deepcopy(payload["locales"]["pt-BR"][0])
    text["source_revision"] = source_revision(expand_snapshot(payload)[0])
    text["name"] = "Acoustic keys"
    text["description"] = "Acoustic instruments played using keys."
    text["sound_production"] = "Keys activate a resonating mechanism."
    payload["locales"]["en"] = [text]
    return payload


def load_snapshot(tmp_path, payload):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_manifest(path)


def database():
    conn = sqlite3.connect(":memory:")
    for migration in sorted((ROOT / "migrations").glob("*.sql")):
        conn.executescript(migration.read_text())
    return conn


def publish(conn, sheets, revision):
    conn.executescript(emit_sql(sheets, revision=revision, commit_sha=revision, published_by="test"))


def test_split_content_preserves_legacy_snapshot():
    sheets = load_manifest(MANIFEST)
    assert len(sheets) == 23
    assert expand_snapshot(split_snapshot(sheets)) == sheets


def test_publishes_translation_with_independent_review_and_original_sources(tmp_path):
    payload = snapshot_with_translation()
    sheets = load_snapshot(tmp_path, payload)
    conn = database()
    publish(conn, sheets, "first")
    publish(conn, sheets, "first")
    status, raw = conn.execute("SELECT status, content_json FROM editorial_resource_translations WHERE locale='en'").fetchone()
    content = json.loads(raw)
    assert status == "published"
    assert content["name"] == "Acoustic keys"
    assert content["sources"] == sheets[0]["resource"]["sources"]
    assert content["sections"][0]["id"] == sheets[0]["resource"]["sections"][0]["id"]
    assert conn.execute("SELECT COUNT(*) FROM editorial_block_translations WHERE locale='en'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM editorial_translation_history WHERE locale='en'").fetchone()[0] == 1


def test_changed_source_marks_translation_stale_and_preserves_history(tmp_path):
    payload = snapshot_with_translation()
    conn = database()
    publish(conn, load_snapshot(tmp_path, payload), "first")
    payload["locales"]["pt-BR"][0]["description"] += " Updated."
    sheets = load_snapshot(tmp_path, payload)
    assert sheets[0]["translations"][0]["status"] == "stale"
    publish(conn, sheets, "second")
    assert conn.execute("SELECT status FROM editorial_resource_translations WHERE locale='en' AND publication_revision='second'").fetchone()[0] == "stale"
    assert conn.execute("SELECT COUNT(*) FROM editorial_translation_history WHERE locale='en'").fetchone()[0] == 2
    del payload["locales"]["en"]
    publish(conn, load_snapshot(tmp_path, payload), "third")
    assert conn.execute("SELECT status FROM editorial_resource_translations WHERE locale='en' AND publication_revision='third'").fetchone()[0] == "deprecated"


def test_stale_translation_survives_removed_block_for_review(tmp_path):
    payload = snapshot_with_translation()
    payload["entities"][0]["sections"] = []
    payload["locales"]["pt-BR"][0]["sections"] = []
    sheets = load_snapshot(tmp_path, payload)
    assert sheets[0]["translations"][0]["status"] == "stale"
    publish(database(), sheets, "changed-blocks")


def test_export_import_and_unfinished_translation(tmp_path):
    from scripts.editorial_content import write_snapshot
    payload = snapshot_with_translation()
    text = payload["locales"]["en"][0]
    text["status"] = "draft"
    text["name"] = ""
    text["review"]["claim_support_verified"] = False
    destination = tmp_path / "content"
    write_snapshot(payload, destination)
    assert load_manifest(destination / "catalog.json")[0]["translations"][0]["status"] == "draft"


def test_publication_revision_is_immutable(tmp_path):
    payload = snapshot_with_translation()
    conn = database()
    publish(conn, load_snapshot(tmp_path, payload), "immutable")
    payload["locales"]["en"][0]["description"] += " Correction."
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        publish(conn, load_snapshot(tmp_path, payload), "immutable")


def test_staging_release_preserves_previous_active_content(tmp_path):
    payload = snapshot_with_translation()
    conn = database()
    publish(conn, load_snapshot(tmp_path, payload), "active")
    payload["locales"]["en"][0]["description"] += " Correction."
    sql = emit_sql(load_snapshot(tmp_path, payload), revision="staging", commit_sha="test", published_by="test")
    before_activation = sql.split("UPDATE editorial_publications SET status='superseded'")[0]
    conn.executescript(before_activation)
    active = conn.execute("SELECT t.content_json FROM editorial_resource_translations t JOIN editorial_publications p ON p.revision=t.publication_revision WHERE p.status='active' AND t.locale='en'").fetchone()[0]
    assert json.loads(active)["description"] == "Acoustic instruments played using keys."


@pytest.mark.parametrize("change", ["review", "missing-block", "missing-image", "locale"])
def test_rejects_invalid_translation(tmp_path, change):
    payload = snapshot_with_translation()
    text = payload["locales"]["en"][0]
    if change == "review": text["review"]["reviewer"] = None
    if change == "missing-block": text["sections"] = []
    if change == "missing-image": text["image"] = None
    if change == "locale": payload["locales"]["en_us"] = payload["locales"].pop("en")
    with pytest.raises(ValueError):
        load_snapshot(tmp_path, payload)


def test_english_catalog_is_complete_current_and_preserves_neutral_identifiers():
    sheets = load_manifest(MANIFEST)
    assert len(sheets) == 23
    for sheet in sheets:
        english = next(item for item in sheet["translations"] if item["locale"] == "en-US")
        assert english["status"] == "reviewed"
        assert english["source_revision"] == source_revision(sheet)
        assert english["review"]["reviewer"] == "Codex (translation review)"
        for key in ("slug", "kind", "family_slug", "related_slugs", "sources"):
            assert english["resource"][key] == sheet["resource"][key]
        assert {block["id"] for block in english["resource"]["sections"]} == {block["id"] for block in sheet["resource"]["sections"]}
    conn = database()
    publish(conn, sheets, "english")
    assert conn.execute("SELECT COUNT(*) FROM editorial_resource_translations WHERE locale='en-US' AND status='reviewed'").fetchone()[0] == 23


def test_source_withdrawal_survives_split_export_and_publication(tmp_path):
    payload = snapshot_with_translation()
    payload["locales"]["pt-BR"][0]["status"] = "deprecated"
    sheets = load_snapshot(tmp_path, payload)
    exported = split_snapshot(sheets)
    assert exported["locales"]["pt-BR"][0]["status"] == "deprecated"
    conn = database()
    publish(conn, load_snapshot(tmp_path, exported), "withdrawn")
    assert conn.execute("SELECT status FROM editorial_resource_translations WHERE locale='pt-BR' AND resource_slug=?", (sheets[0]["resource"]["slug"],)).fetchone()[0] == "deprecated"


def test_withdrawn_translation_remains_withdrawn_when_source_changes(tmp_path):
    payload = snapshot_with_translation()
    payload["locales"]["en"][0]["status"] = "deprecated"
    payload["locales"]["pt-BR"][0]["description"] += " Updated."
    sheets = load_snapshot(tmp_path, payload)
    translated = next(item for item in sheets[0]["translations"] if item["locale"] == "en")
    assert translated["status"] == "deprecated"
    conn = database()
    publish(conn, sheets, "withdrawn-translation")
    assert conn.execute("SELECT status FROM editorial_resource_translations WHERE locale='en'").fetchone()[0] == "deprecated"


@pytest.mark.parametrize("field", ["catalog_version", "image_catalog_version", "tone", "image-url", "image-credit", "review-note", "review-date", "source-access-date"])
def test_operational_metadata_does_not_invalidate_translations(tmp_path, field):
    payload = snapshot_with_translation()
    entity = payload["entities"][0]
    text = payload["locales"]["pt-BR"][0]
    if field in {"catalog_version", "image_catalog_version"}: entity[field] = "new-version"
    if field == "tone": entity["tone"]["highlight"] = "#ffffff"
    if field == "image-url": entity["image"]["variants"][0]["url"] += "?updated=1"
    if field == "image-credit": entity["image"]["credit"]["photographer"] = "Updated attribution"
    if field == "review-note": text["review"]["editorial_note"] = "Operational note"
    if field == "review-date": text["review"]["reviewed_at"] = "2026-10-17"
    if field == "source-access-date": payload["sources"][0]["accessed_at"] = "2026-10-17"
    sheets = load_snapshot(tmp_path, payload)
    translation = next(item for item in sheets[0]["translations"] if item["locale"] == "en")
    assert translation["status"] == "published"
    assert translation["source_revision"] == source_revision(sheets[0])


@pytest.mark.parametrize("field", ["description", "block-text", "citation", "source-url", "asset", "alt", "block-withdrawal", "source-verification"])
def test_content_and_publication_changes_still_invalidate_translations(field):
    payload = snapshot_with_translation()
    text = payload["locales"]["pt-BR"][0]
    entity = payload["entities"][0]
    if field == "description": text["description"] += " Updated."
    if field == "block-text": text["sections"][0]["text"] += " Updated."
    if field == "citation": entity["sections"][0]["citations"][0]["note"] = "Changed evidence"
    if field == "source-url": payload["sources"][0]["url"] += "?updated=1"
    if field == "asset":
        entity["image"]["asset_id"] = "new-image"
        text["image"]["asset_id"] = "new-image"
    if field == "alt": text["image"]["alt"] += " Updated."
    if field == "block-withdrawal": text["sections"][0]["status"] = "deprecated"
    if field == "source-verification": payload["sources"][0]["metadata_verified"] = False
    assert next(item for item in expand_snapshot(payload)[0]["translations"] if item["locale"] == "en")["status"] == "stale"


def test_upgrades_legacy_revisions_only_when_the_exact_source_matches():
    from scripts.editorial_content import legacy_source_revision
    payload = snapshot_with_translation()
    source = expand_snapshot(payload)[0]
    text = payload["locales"]["en"][0]
    text["source_revision"] = legacy_source_revision(source)
    upgraded = next(item for item in expand_snapshot(payload)[0]["translations"] if item["locale"] == "en")
    assert upgraded["status"] == "published"
    assert upgraded["source_revision"] == source_revision(source)
    payload["locales"]["pt-BR"][0]["description"] += " Changed after review."
    changed = next(item for item in expand_snapshot(payload)[0]["translations"] if item["locale"] == "en")
    assert changed["status"] == "stale"
    assert changed["source_revision"] == text["source_revision"]
