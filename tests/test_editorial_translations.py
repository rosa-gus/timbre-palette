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
