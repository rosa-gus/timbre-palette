# Offline tools

Offline utilities for editorial image processing and static asset publication.
No tool runs during an API request.

## Image processing

The current treatment is **rosa-reticle 0.1.0**, a tonal screen inspired by
Bayer ordered dithering. It applies a fine texture selectively to shadows,
preserves continuous highlights, and maps the result to a duotone palette.

Install Pillow and ensure FFmpeg is available for video work:

```sh
python3 -m pip install 'Pillow>=10.1,<13'
```

### Instrument photograph

```sh
python3 scripts/treat_instrument.py assets/piano.jpeg /tmp/piano-rosa.png
python3 scripts/treat_instrument.py assets/piano.jpeg /tmp/piano-blue.png \
  --highlight '#9EBBD1' --width 1200
```

`treat_instrument.py` calls the engine in `rosa_reticle.py`. Options are
`--width`, `--shadow` and `--highlight`. Output is an RGB PNG without embedded
source metadata, accompanied by a `.json` generation record. Existing outputs
and sidecars are preserved. The same command is available through
`python3 scripts/rosa_reticle.py image ...`.

### Video

```sh
python3 scripts/rosa_reticle.py video assets/vinil.mp4 /tmp/vinil-rosa-av1.webm \
  --work-dir /tmp/vinil-rosa-frames --prepare-only
python3 scripts/rosa_reticle.py video assets/vinil.mp4 /tmp/vinil-rosa-av1.webm \
  --work-dir /tmp/vinil-rosa-frames --encode-only --preset av1
```

Videos carry treated grayscale; apply the duotone during display using the
sRGB SVG color matrix documented in [rosa-reticle](../docs/rosa-reticle.md).
The guide covers video presets, resuming jobs, poster handling, the Python API,
and contribution checks.

### Documentation showcase

The documentation showcase can be regenerated independently:

```sh
python3 scripts/rosa_reticle_showcase.py --force
```

It writes the comparison PNG and reproducibility sidecar under `docs/images/`.
See [the visual showcase](../docs/rosa-reticle.md#visual-showcase) for the Bayer
reference parameters and the controlled comparison.

### Batch preparation

```sh
python3 scripts/prepare_images.py
python3 scripts/prepare_images.py --force
python3 scripts/prepare_images.py --manifest catalog/instrument-images.json
```

`prepare_images.py` validates manifest schema v1. A manifest with
`"treatment_version": "rosa-reticle-0.1.0"` uses the current engine; its
`defaults` and per-image `treatment` options accept `width`, `shadow` and
`highlight`. Family tones continue to select each instrument's colors.

The repository catalog uses `rosa-reticle-0.1.0`. `--force` regenerates existing
outputs; without it, existing files are skipped. Paths are resolved from the
repository root.

Every batch writes `assets/treated/manifest.json`, recording actual source and
output hashes, family colors, resolved options, image dimensions, generation
times, implementation fingerprints, and Python/Pillow versions. The log tracks
generated and skipped files and whether retained outputs match the current
request. Unknown provenance is marked explicitly. Use
`--generation-manifest <path.json>` to select another log path.

## Static image publication

```sh
yarn prepare:images
```

`publish_images.py` copies approved or published treated assets to:

```text
public/instruments/<asset-id>/<sha256-prefix>/detail.png
```

It generates `reference/server-assembly/src/palette_api/_generated_image_catalog.json` and publishes
`public/profile-analysis-catalog.json` plus
`public/profile-analysis-example.json`. The generated catalog and example
fixture are build artifacts and are ignored by Git. The content hash changes
the public path when a treated PNG changes. The example file is copied from
`reference/server-assembly/src/palette_api/_curated_example_history.json` for browser-side example
assembly. The command does not alter source images or the editorial manifest.

The active API Worker also imports this generated catalog. Wrangler runs the
publication step before local development and deployment, so instrument
images use the same resolved URLs in the API and browser.

`yarn dev:web` and `yarn build:web` run this publication step automatically.
Run `prepare_images.py` first when a source photograph, treatment parameter, or
manifest output changes.

The API returns absolute image URLs. Set the non-secret
`IMAGE_ASSET_BASE_URL` variable to select the hosting base; local development
uses `http://127.0.0.1:5173/` and production uses the configured GitHub Pages
base.

## MusicBrainz offline credit index

The offline ETL is a standalone Rust materializer. It scans the dump once,
aggregates evidence and Artist Vocabulary, and emits serving shards for R2:

```sh
cargo run --release --manifest-path etl/musicbrainz-etl/Cargo.toml -- \
  /data/musicbrainz/mbdump.tar.bz2 \
  /data/musicbrainz/staging/20260912-002318 \
  --snapshot-version 20260912-002318
```

The staging materializer writes projected JSONL tables, a schema-versioned
manifest, and a `LICENSE-MUSICBRAINZ.txt` notice. Use its `aggregate` and
`serve` subcommands to produce the uploadable artifact.

See [MusicBrainz credit index](../docs/musicbrainz-credit-index.md) for
the hydration contract and provenance.

## Editorial publication

Validate the canonical editorial snapshot:

```sh
yarn editorial:validate
```

Render a repeatable D1 publication file:

```sh
yarn editorial:sql > /tmp/timbre-palette-editorial.sql
```

`publish_editorial.py` accepts split schema-v2 content and editor exports, with
legacy snapshot support. It synchronizes translations, source metadata, citations,
curiosity blocks, further reading, and review metadata. It records a manifest
hash and publication revision in `editorial_publications`; it does not perform
network requests or run during an API request.

## Media credits

Home-page media credits are maintained in
[assets/CREDITS.md](../../../assets/CREDITS.md).
