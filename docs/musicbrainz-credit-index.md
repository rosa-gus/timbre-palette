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

The API records missing snapshot targets in `snapshot_hydration_jobs`. The TypeScript snapshot hydrator runs on a two-minute Cron, claims one target at a time, reads one calculated R2 shard, validates the v2 envelope, resolves the controlled taxonomy, and materializes D1 projections idempotently. It does not parse the large manifest at runtime; publication stores the complete immutable R2 prefix in the active D1 snapshot row.

Recording projections preserve both instrument-level and family-level claims. Artist Vocabulary only accepts mappings to specific instruments. Missing targets become `complete_empty`; malformed or missing shards are terminal failures for that snapshot, while transient R2/D1 errors use bounded retries.

An object miss is terminal for the targeted snapshot version. The hydrator does not fall back to a network API. A later MusicBrainz dump can supply new evidence through a new immutable snapshot.

The HTTP Worker has no R2 binding. The hydrator owns the R2 binding and D1 write access; the API owns only D1 reads and hydration-job scheduling. The hydrator binding uses the existing Standard R2 bucket in the `eu` jurisdiction and keeps a daily D1-write guard plus the monthly R2-read guard.

### Publishing a serving snapshot

R2 upload and D1 publication are separate steps. After validating the serving
directory, render the idempotent D1 publication SQL from its manifest:

```sh
yarn musicbrainz:publish \
  /data/musicbrainz/serving/20260912-002318/manifest.json \
  > /tmp/publish-20260912-002318.sql
```

Review the generated SQL, then apply it to the intended D1 database with
Wrangler. The publication marks the previous active snapshot as superseded
and activates the manifest's immutable prefix, schema, counts, and hash.

## License and refresh policy

The [MusicBrainz download documentation](https://musicbrainz.org/doc/MusicBrainz_Database/Download) identifies the core dump as CC0 and supplementary dumps as CC BY-NC-SA 3.0. The [data license](https://musicbrainz.org/doc/About/Data_License) requires attribution and preservation of applicable conditions for derivative works.

The ETL requires an explicit snapshot version and carries license and attribution into intermediate and serving artifacts. The R2 manifest and D1 snapshot metadata preserve the source URL, schema version, manifest hash, license, attribution, publication state, and publication time.
