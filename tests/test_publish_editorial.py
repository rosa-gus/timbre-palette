import json
import sqlite3
from pathlib import Path

from palette_api.tools.publish_editorial import (
    emit_sql,
    load_manifest,
    manifest_digest,
)


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "editorial/src/instruments.json"


def test_editorial_manifest_validates_and_has_stable_digest() -> None:
    resources = load_manifest(MANIFEST)
    assert len(resources) == 23
    payload = json.loads(MANIFEST.read_text())
    source_resources = payload["instruments"] if isinstance(payload, dict) else payload
    assert manifest_digest(resources) == manifest_digest(source_resources)


def test_editorial_sql_is_repeatable_and_persists_verified_review() -> None:
    resources = load_manifest(MANIFEST)
    sql = emit_sql(
        resources,
        revision="editorial-test",
        commit_sha="abc123",
        published_by="pytest",
    )
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    for migration in sorted((ROOT / "migrations").glob("*.sql")):
        conn.executescript(migration.read_text(encoding="utf-8"))
    conn.executescript(sql)
    conn.executescript(sql)

    publication = conn.execute(
        "SELECT revision, manifest_hash, status FROM editorial_publications"
    ).fetchall()
    assert publication == [("editorial-test", manifest_digest(resources), "active")]
    reviewed_sheet = next(
        sheet
        for sheet in resources
        if any(section["review"].get("claim_support_verified") for section in sheet["resource"]["sections"])
    )
    reviewed_section = next(
        section
        for section in reviewed_sheet["resource"]["sections"]
        if section["review"].get("claim_support_verified")
    )
    review = conn.execute(
        """
        SELECT claim_support_verified, reviewed_at, reviewer
        FROM editorial_content_blocks
        WHERE id = ?
        """,
        (reviewed_section["id"],),
    ).fetchone()
    assert review == (
        1,
        reviewed_section["review"]["reviewed_at"],
        reviewed_section["review"]["reviewer"],
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM editorial_content_blocks WHERE status = 'deprecated'"
    ).fetchone()[0] == 0


def test_editorial_manifest_accepts_verified_text_without_citations(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["instruments"][0]["review"]["claim_support_verified"] = True
    payload["instruments"][0]["review"]["reviewer"] = "Editor"
    payload["instruments"][0]["review"]["reviewed_at"] = "2026-09-15"
    manifest = tmp_path / "verified.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    assert load_manifest(manifest)[0]["review"]["claim_support_verified"] is True
