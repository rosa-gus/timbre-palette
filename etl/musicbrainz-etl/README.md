# MusicBrainz ETL (Rust)

This CLI implements the offline MusicBrainz pipeline. The default invocation
reads an extracted dump directory or a `tar`/`tar.bz2` archive and materializes
the selected PostgreSQL `COPY` tables once into compact JSONL projections.

The `aggregate` subcommand joins a staging snapshot into direct recording
evidence, release-scoped context, track aliases, and Artist Vocabulary
statistics. It writes local JSONL artifacts and does not publish to R2 yet.

## Build

```sh
cargo build --release --manifest-path etl/musicbrainz-etl/Cargo.toml
```

## Run

```sh
etl/musicbrainz-etl/target/release/musicbrainz-etl \
  /data/musicbrainz/mbdump.tar.bz2 \
  /data/musicbrainz/staging/20260912-002318 \
  --snapshot-version 20260912-002318
```

The output directory contains one projected `*.jsonl` file per available
table, `manifest.json`, and `LICENSE-MUSICBRAINZ.txt`. The command fails when a
required table is absent or when the output directory is not empty.

The projection is deliberately schema-versioned. In particular, `medium` is
projected as `[id, release]`; the dump's third column is `position`, not a
release identifier.

Progress is written to stderr. Use `--no-progress` for automation or
`--progress-interval 10` for less frequent updates.

## Aggregate a staging snapshot

```sh
etl/musicbrainz-etl/target/release/musicbrainz-etl aggregate \
  /data/musicbrainz/staging/20260912-002318 \
  /data/musicbrainz/aggregate/20260912-002318 \
  --snapshot-version 20260912-002318 \
  --min-recordings 3
```

The aggregate output contains `direct-evidence.jsonl`,
`release-context.jsonl`, `track-aliases.jsonl`, `artist-vocabulary.jsonl`, a
schema-versioned `manifest.json`, and the MusicBrainz license notice. The
vocabulary file reports distinct recordings, documented recordings,
prevalence, and whether the configured minimum was reached. The command
requires an empty output directory and validates the staging manifest before
reading tables.

## Build a serving snapshot

```sh
etl/musicbrainz-etl/target/release/musicbrainz-etl serve \
  /data/musicbrainz/aggregate/20260912-002318 \
  /data/musicbrainz/serving/20260912-002318 \
  --snapshot-version 20260912-002318 \
  --recording-shards 4096 \
  --auxiliary-shards 256 \
  --compression-level 6
```

The serving stage validates the aggregate manifest, discards unresolved
`instrument` relations without an `instrument_mbid`, and keeps release-scoped
credits only as a fallback when a recording has no direct evidence. It writes
deterministic bzip2-compressed shards under `recordings/`, `tracks/`, and
`artists/`, plus a serving manifest and license notice. The default 256
hexadecimal-prefix shards cover aliases and artists; recordings use 4096
three-character-prefix shards so a Worker can decode an object within its
memory budget. Release fallback credits are deduplicated semantically while
retaining their source URLs in the serving record. Placeholder artist
identities such as `[unknown]` and `Various Artists` are excluded from the
artist vocabulary; the serving manifest reports how many rows were filtered.
