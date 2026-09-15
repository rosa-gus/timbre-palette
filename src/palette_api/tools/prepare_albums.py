"""Validate and optionally render SQL for the curated album manifest."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def load_manifest(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("albums"), list):
        raise ValueError("The manifest must contain schema_version 1 and albums.")
    albums: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(payload["albums"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Album {index} must be an object.")
        release_mbid = item.get("release_mbid")
        artist = item.get("artist")
        title = item.get("title")
        if (
            not isinstance(release_mbid, str)
            or not MBID.fullmatch(release_mbid)
            or release_mbid in seen
        ):
            raise ValueError(f"release_mbid is invalid or duplicated in album {index}.")
        if not isinstance(artist, str) or not artist.strip():
            raise ValueError(f"artist is missing from album {index}.")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"title is missing from album {index}.")
        priority = item.get("priority", 0)
        if not isinstance(priority, int):
            raise ValueError(f"priority must be an integer in album {index}.")
        seen.add(release_mbid)
        albums.append(
            {
                "release_mbid": release_mbid,
                "artist": artist.strip(),
                "title": title.strip(),
                "genre": str(item.get("genre", "")).strip() or None,
                "priority": priority,
            }
        )
    return albums


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def emit_sql(albums: list[dict[str, object]]) -> str:
    statements = ["BEGIN;"]
    for album in albums:
        statements.append(
            "INSERT INTO prepared_album_targets "
            "(release_mbid, artist, title, genre, priority) VALUES "
            f"({sql_literal(album['release_mbid'])}, {sql_literal(album['artist'])}, "
            f"{sql_literal(album['title'])}, {sql_literal(album['genre'])}, "
            f"{sql_literal(album['priority'])}) "
            "ON CONFLICT(release_mbid) DO UPDATE SET artist=excluded.artist, "
            "title=excluded.title, genre=excluded.genre, priority=excluded.priority, "
            "status='pending', updated_at=datetime('now');"
        )
    statements.append("COMMIT;")
    return "\n".join(statements)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--sql", action="store_true", help="imprime SQL para D1")
    args = parser.parse_args()
    albums = load_manifest(args.manifest)
    if args.sql:
        print(emit_sql(albums))
    else:
        print(f"Manifesto válido: {len(albums)} álbuns.")


if __name__ == "__main__":
    main()
