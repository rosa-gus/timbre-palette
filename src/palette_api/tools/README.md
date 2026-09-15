# Backend Tooling

Offline utilities for editorial image processing, static asset publication, and
album-manifest preparation. No tool runs during an API request.

## Image processing

Install the image-processing dependency:

```sh
python3 -m pip install 'Pillow>=10,<13'
```

### Batch preparation

```sh
python3 src/palette_api/tools/prepare_images.py
python3 src/palette_api/tools/prepare_images.py --force
python3 src/palette_api/tools/prepare_images.py --manifest catalog/instrument-images.json
```

`prepare_images.py` validates manifest schema v1 and generates treated PNGs from
the manifest defaults, family tones, and per-image overrides. Existing outputs
are preserved unless `--force` is supplied. Manifest paths are resolved from
the repository root.

### Single-file treatment

```sh
python3 src/palette_api/tools/treat_instrument.py \
  assets/piano.jpeg assets/treated/piano.png
```

Image options:

- `--shadow`, `--highlight`: opaque RGB colors;
- `--levels`: quantization levels, from 2 to 256;
- `--strength`: ordered-dithering intensity, from 0 to 1;
- `--width`: maximum output width; images are never upscaled;
- `--contrast`, `--gamma`: positive tonal adjustments.

The pipeline applies EXIF orientation, composites transparency over the shadow
color, resizes before dithering, and writes metadata-free PNGs. It does not
crop, normalize histograms, overwrite existing outputs, or process images in
HTTP requests. The same input, parameters, and Pillow version produce a
deterministic result.

### Video treatment

Video output requires FFmpeg with the `libvpx-vp9` encoder:

```sh
python3 src/palette_api/tools/treat_instrument.py \
  assets/flower-intro.mp4 assets/treated/flower-intro.webm \
  --poster assets/treated/flower-intro.png
```

Video-specific options are `--fps`, `--duration`, `--crf`, and `--poster`.
Output is silent VP9 WebM; the default is 24 fps, a maximum width of 1200 px,
and CRF 18. Temporary frames are removed automatically. Videos are not part
of the instrumental image manifest or the static image publication pipeline.

## Static image publication

```sh
yarn prepare:images
```

`publish_images.py` copies approved or published treated assets to:

```text
public/instruments/<asset-id>/<sha256-prefix>/detail.png
```

It also generates `src/palette_api/_generated_image_catalog.json`, which is a
build artifact and is ignored by Git. The content hash changes the public path
when the treated PNG changes. The command does not alter source images or the
editorial manifest.

`yarn dev:web` and `yarn build:web` run this publication step automatically.
Run `prepare_images.py` first when a source photograph, treatment parameter, or
manifest output changes.

The API returns absolute image URLs. Set the non-secret
`IMAGE_ASSET_BASE_URL` variable to select the hosting base; local development
uses `http://127.0.0.1:5173/` and production uses the configured GitHub Pages
base.

## Album manifest

`prepare_albums.py` validates `catalog/prepared-albums.json` and can emit SQL
for D1:

```sh
yarn catalog:validate
yarn catalog:sql > /tmp/timbre-palette-albums.sql
```

Each entry must contain a unique release MBID, artist, title, and integer
priority. Optional genre values are normalized during validation. SQL output
uses an idempotent upsert for `prepared_album_targets`.

## Editorial publication

Validate the canonical editorial snapshot:

```sh
yarn editorial:validate
```

Render a repeatable D1 publication file:

```sh
yarn editorial:sql > /tmp/timbre-palette-editorial.sql
```

`publish_editorial.py` accepts both the editor seed array and exported
schema-v1 snapshots. It synchronizes resource text, source metadata, citations,
curiosity blocks, further reading, and review metadata. It records a manifest
hash and publication revision in `editorial_publications`; it does not perform
network requests or run during an API request.

## Media credits

Home-page media credits are maintained in
[assets/CREDITS.md](../../../assets/CREDITS.md).
