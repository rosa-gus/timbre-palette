# MusicBrainz credit index

The enrichment path uses three layers:

```text
MusicBrainz dump/replication snapshot
        ↓ offline ETL
R2: one compact object per recording MBID
        ↓ only demanded recordings
D1: normalized candidates, claims and evidence
        ↓ cache miss or expired D1 evidence
MusicBrainz API
```

This deliberately removes the full MusicBrainz database from the request and
Queue paths. A recording that is present in the snapshot is normalized from
R2 without consuming a MusicBrainz API request. The API remains available for
recordings not present in the snapshot; stale D1 evidence falls through to R2
before the API is considered.

## Build the index

The builder accepts either an extracted `mbdump` directory or the original
`mbdump.tar.bz2` archive. It stages only the required tables in a local SQLite
database and writes a new, empty output directory:

```sh
.venv/bin/uv run python -m palette_api.tools.build_musicbrainz_index \
  /data/musicbrainz/mbdump.tar.bz2 \
  /data/index/musicbrainz-2026-09-12 \
  --snapshot-version schema-30-2026-09-12 \
  --source-url https://musicbrainz.org/doc/MusicBrainz_Database/Download \
  --license CC\ BY-NC-SA-3.0 \
  --attribution 'MusicBrainz; derived instrumental-credit index.'
```

The ETL reads `artist`, `recording`, `instrument`, relationship/link tables,
and—when present—`release`, `medium`, `track`, and `l_artist_release`. It
preserves recording-scoped and release-scoped rows separately. Release scope
is not promoted to a documented recording claim by the application.

The output contains:

- `manifest.json`, including snapshot version, hash, source URL, license,
  attribution, counts, and the object key template;
- `LICENSE-MUSICBRAINZ.txt`, which travels with the derivative dataset;
- `musicbrainz/instrument-credits/v1/recordings/<recording-mbid>.json`, with
  the recording MBID, artist MBID, instrument MBID/name, relation attributes,
  scope, source URL, and snapshot version.

The object layout is intentionally direct-addressed: a Worker can perform one
R2 `get` for a recording rather than downloading a large shard. Upload the
generated directory with the project's R2 publication job or S3-compatible R2
sync process, preserving `manifest.json` and the license notice.

## Publish snapshot metadata to D1

After the R2 objects are available, generate the D1 publication SQL and apply
it through the normal migration/SQL review flow:

```sh
.venv/bin/uv run python -m palette_api.tools.publish_musicbrainz_index \
  /data/index/musicbrainz-2026-09-12/manifest.json \
  > /tmp/timbre-palette-musicbrainz-index.sql
```

The SQL records the active manifest only; it does not copy the entire index to
D1. Runtime hits add only the normalized candidate/evidence needed for the
recording that the product encountered.

## License and refresh policy

The [MusicBrainz download documentation](https://musicbrainz.org/doc/MusicBrainz_Database/Download)
identifies the core dump as CC0 and the supplementary dumps as CC BY-NC-SA 3.0.
The [data license](https://musicbrainz.org/doc/About/Data_License) also states
that replication packets are CC BY-NC-SA 3.0 and that derivative works using
that data must preserve attribution and the applicable conditions. The build
command therefore requires an explicit snapshot version and carries the
license/attribution into both R2 and D1 metadata; choose the license that
matches the artifact actually processed.

The R2 binding is configured on the private Python enrichment Worker as
`MUSICBRAINZ_CREDIT_INDEX`. Create the bucket named in
`wrangler.enricher-python.jsonc` before deployment. The recent D1 cache defaults
to 30 days and can be changed with
`MUSICBRAINZ_CREDIT_INDEX_MAX_AGE_DAYS`.

## Release-first enrichment

When Last.fm supplies an album/release MBID, the scheduler creates one release
job instead of one recording job. The existing release collector requests
`recordings+recording-level-rels` in one MusicBrainz lookup and persists the
recordings and their raw observations together. Tracks without a usable release
MBID still use the R2/D1 lookup path before falling back to individual API
resolution.

The API include behavior follows the official
[MusicBrainz API relationship documentation](https://musicbrainz.org/doc/MusicBrainz_API):
`recording-level-rels` is the switch for relationships on recordings linked to
a release, and the linked-entity limit still makes the concrete release lookup
the appropriate unit for this workflow.
