# MusicBrainz credit index

MusicBrainz data reaches the application through a versioned offline pipeline. Runtime services do not call the MusicBrainz API.

```text
MusicBrainz dump/replication snapshot
        ↓ Rust ETL
staging projections
        ↓ aggregate
direct evidence + Artist Vocabulary partitions
        ↓ serve
compressed R2 shards
        ↓ snapshot hydrator
versioned D1 projections
```

## Staging

The ETL accepts an extracted `mbdump` directory or a `tar`/`tar.bz2` archive and scans it once:

```sh
cargo run --release --manifest-path etl/musicbrainz-etl/Cargo.toml -- \
  /data/musicbrainz/mbdump.tar.bz2 \
  /data/musicbrainz/staging/20260912-002318 \
  --snapshot-version 20260912-002318
```

It writes projected JSONL tables, a schema-versioned `manifest.json`, and `LICENSE-MUSICBRAINZ.txt`. Staging is a local intermediate artifact and must not be uploaded to R2.

Recording-scoped and release-scoped relationships remain separate. Release context can be used only when a recording has no direct evidence; it never replaces direct evidence already attached to that recording.

## Aggregation and serving

The `aggregate` command joins staging projections into recording evidence, track aliases, and Artist Vocabulary partitions. The `serve` command then creates the R2-ready artifact:

```sh
cargo run --release --manifest-path etl/musicbrainz-etl/Cargo.toml -- \
  serve \
  /data/musicbrainz/aggregate/20260912-002318 \
  /data/musicbrainz/serving/20260912-002318 \
  --snapshot-version 20260912-002318
```

The output uses the `musicbrainz-instrument-credits-serving-v2` schema and deterministic gzip shards under `recordings/`, `tracks/`, and `artists/`. Recording claims are pre-aggregated by instrument identity, scope, relation, production method, and attributes; performer and source counts remain attached to each claim. Gzip is emitted at maximum compression by default so the serving Worker can use the Workers runtime's native decompressor. Recordings and track aliases use four hexadecimal partition characters; artist vocabulary uses three. Release duplicates retain distinct source URLs, and placeholder artist identities are excluded from vocabulary.

Credits that cannot be resolved to an instrument or family in the project taxonomy are discarded before serving publication.

## Hydration contract

The API records missing snapshot targets in `snapshot_hydration_jobs`. The snapshot hydrator claims those jobs in batches, groups keys that share an R2 object, validates the manifest and object metadata, and materializes D1 projections idempotently.

An object miss is terminal for the targeted snapshot version. The hydrator does not fall back to a network API. A later MusicBrainz dump can supply new evidence through a new immutable snapshot.

The HTTP API has no R2 binding. The hydrator owns the R2 binding and D1 write access; the API owns only D1 reads and hydration-job scheduling.

## License and refresh policy

The [MusicBrainz download documentation](https://musicbrainz.org/doc/MusicBrainz_Database/Download) identifies the core dump as CC0 and supplementary dumps as CC BY-NC-SA 3.0. The [data license](https://musicbrainz.org/doc/About/Data_License) requires attribution and preservation of applicable conditions for derivative works.

The ETL requires an explicit snapshot version and carries license and attribution into intermediate and serving artifacts. The R2 manifest and D1 snapshot metadata preserve the source URL, schema version, manifest hash, license, attribution, publication state, and publication time.
