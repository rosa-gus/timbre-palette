# MusicBrainz ETL (Rust)

This is the first stage of the next offline MusicBrainz pipeline. It reads an
extracted dump directory or a `tar`/`tar.bz2` archive and materializes the
selected PostgreSQL `COPY` tables once into compact JSONL projections.

It is intentionally separate from the Python Worker and does not publish to
R2 yet. The next stage will join these projections into direct-evidence and
Artist Vocabulary partitions.

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
