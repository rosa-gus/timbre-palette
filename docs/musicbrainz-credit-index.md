# MusicBrainz credit index

The enrichment runtime reads published R2 credit objects. New snapshots are
built through the Rust pipeline.

```text
MusicBrainz dump/replication snapshot
        ↓ Rust offline ETL
staging projections → direct evidence + Artist Vocabulary aggregation
        ↓ Rust serving snapshot
compressed R2 shards → Python Worker runtime → D1 evidence cache
```

## Rust ETL status

The active command accepts an extracted `mbdump` directory or a `tar`/`tar.bz2`
archive and scans it once:

```sh
cargo run --release --manifest-path etl/musicbrainz-etl/Cargo.toml -- \
  /data/musicbrainz/mbdump.tar.bz2 \
  /data/musicbrainz/staging/20260912-002318 \
  --snapshot-version 20260912-002318
```

It writes projected JSONL tables, a schema-versioned `manifest.json`, and a
`LICENSE-MUSICBRAINZ.txt` notice. The staging directory is an intermediate
local artifact. It is not an R2 serving snapshot and must not be uploaded
directly. The `aggregate` command joins the projections into recording-level
evidence and Artist Vocabulary partitions; `serve` then emits the local R2
artifact described below.

The staging schema preserves recording-scoped and release-scoped relationships
separately. The serving stage keeps release context only as a fallback when a
recording has no direct evidence; it never lets release context replace direct
evidence for a recording that already has one. The aggregate directory is an
intermediate local input to the serving command below and is not uploaded
directly.

## Serving snapshot

Build the R2-ready local artifact from an aggregate directory:

```sh
cargo run --release --manifest-path etl/musicbrainz-etl/Cargo.toml -- \
  serve \
  /data/musicbrainz/aggregate/20260912-002318 \
  /data/musicbrainz/serving/20260912-002318 \
  --snapshot-version 20260912-002318
```

The output uses the `musicbrainz-instrument-credits-serving-v1` schema. It
contains deterministic bzip2 shards under `recordings/`, `tracks/`, and
`artists/`, with two hexadecimal characters selecting a shard. The Worker reads
this sharded layout directly.

## Runtime guard

The Python Worker starts with the R2 index disabled:

```jsonc
"MUSICBRAINZ_CREDIT_INDEX_ENABLED": "false"
```

When a Rust-generated serving snapshot is available and validated, enable the
index and, when required, offline-only mode:

```jsonc
"MUSICBRAINZ_CREDIT_INDEX_ENABLED": "true",
"MUSICBRAINZ_CREDIT_INDEX_OFFLINE_ONLY": "true"
```

Offline-only mode routes release-bearing tracks through concrete recording
jobs and treats index misses as terminal. With the flag disabled, the normal
MusicBrainz API fallback remains available.

Each permitted R2 lookup is reserved in `musicbrainz_credit_index_usage`
before the object is read. The configured read budget fails closed when
exhausted. Budget alerts remain useful as a second line of defense, but they
are not hard Cloudflare usage caps.

## License and refresh policy

The [MusicBrainz download documentation](https://musicbrainz.org/doc/MusicBrainz_Database/Download)
identifies the core dump as CC0 and supplementary dumps as CC BY-NC-SA 3.0.
The [data license](https://musicbrainz.org/doc/About/Data_License) requires
attribution and preservation of applicable conditions for derivative works.
The Rust staging command therefore requires an explicit snapshot version and
carries license and attribution into the intermediate artifact. The serving
manifest and license notice preserve that provenance for the eventual R2
publication and D1 metadata.

The R2 binding is configured on the private Python enrichment Worker as
`MUSICBRAINZ_CREDIT_INDEX`. The recent D1 cache defaults to 30 days and the
runtime guard uses `MUSICBRAINZ_CREDIT_INDEX_MAX_READS` and
`MUSICBRAINZ_CREDIT_INDEX_USAGE_PERIOD`.

## Release-first runtime behavior

When API fallback is enabled and Last.fm supplies an album/release MBID, the
scheduler creates one release job instead of one recording job. In offline-only
mode, the release MBID is only an expansion target: concrete tracks are
resolved through their recording identity and serving index objects.

The API include behavior follows the official
[MusicBrainz API relationship documentation](https://musicbrainz.org/doc/MusicBrainz_API):
`recording-level-rels` is the switch for relationships on recordings linked to
a release, and the linked-entity limit makes concrete release lookup the
appropriate unit for that workflow.
