<h1 align="center">
  <img src="./public/timbre-mark.png" width="300" alt="Timbre Palette">
</h1>

Timbre Palette is an experimental web application that transforms a public Last.fm listening history into an instrumental profile. It combines listening data with accepted instrument evidence to describe recurring sound families, acoustic and electronic characteristics, coverage, and an editorial interpretation called the listening temperament.

The project is currently in a pilot phase. Its results are designed to be transparent, reproducible, and explicit about incomplete evidence.

## Features

- Generates an instrumental palette from a public Last.fm profile and a selected listening period.
- Ranks recurring instrument families while preserving evidence and confidence information.
- Describes the balance between acoustic, electric, electronic, sampled, hybrid, and unidentified sound sources.
- Reports track and play coverage instead of presenting incomplete metadata as complete analysis.
- Distinguishes `ready`, `partial`, and `insufficient` analyses through a stable API response contract.
- Produces deterministic editorial observations and an instrument discovery when the available evidence supports them.
- Exposes sourced instrument and sound-family profiles with citations, image credits, and review metadata.
- Generates a downloadable, shareable portrait in the browser.
- Records missing snapshot targets so they can be hydrated asynchronously from the published offline index.

## Services

### Last.fm

Last.fm provides the public listening history used as the input for an analysis. The browser requests up to four pages of 50 ranked tracks for the selected period, then checks the local snapshot in batches so documented tracks below the first 50 ranks can contribute. Visitors do not authenticate with their Last.fm accounts. A project API key is required when running the real integration.

Last.fm is a listening-history source, not an authoritative source of instrumentation.

### MusicBrainz

MusicBrainz data is consumed exclusively through versioned offline snapshots built by the Rust ETL and published to R2. The application does not call the MusicBrainz API at runtime. Only credits with a resolved identity, supported scope, and explicit instrument mapping enter the serving snapshot.

## API

The public API is the TypeScript Cloudflare Worker in `workers/api/`. It provides bounded Last.fm history pages and profile metadata, read-only snapshot evidence, and a queue for asynchronous hydration. The browser combines those responses into the Profile Analysis v2 report; the API does not assemble the report on the production request path.

The API exposes these resources:

- `GET /v3/profiles/{username}/tracks` — returns one validated Last.fm page of up to 50 tracks. Pages 1–4 are available.
- `GET /v3/profiles/{username}/metadata` — returns public Last.fm profile metadata.
- `POST /v3/evidence` — reads evidence for up to 50 track MBIDs and 50 artist MBIDs from one pinned snapshot.
- `POST /v3/hydration` — queues up to 50 recording or track targets and 200 artist targets for background processing.
- `GET /v2/instruments/{slug}` and `GET /v2/catalog/stats` — serve reviewed catalog resources and a summary count.

The canonical OpenAPI document is available at `GET /openapi.json`. It describes the active TypeScript Worker contract; no interactive `/docs` page is served. The former FastAPI report assembler remains in the repository as a local reference implementation and is not the production API.

Detailed catalog behavior, persistence, and business rules are maintained in the API documentation:

- [Public API contract](docs/api-contract.md)
- [Backend protection and budgets](docs/backend-protection.md)
- [Catalog architecture](docs/catalog-architecture.md)
- [Editorial publication](docs/editorial-publishing.md)
- [Versioned analysis methodology](docs/methodology.md)

### Architecture

```mermaid
flowchart LR
    Browser[Public Svelte application] -->|history pages and metadata| API[TypeScript API Worker]
    API -->|public listening history| LastFM[Last.fm API]
    Browser -->|batched evidence requests| API
    API -->|read snapshot projections| D1[(Cloudflare D1)]
    Browser -->|queue missing targets| API
    API -->|record hydration jobs| D1
    Browser -->|assemble Profile Analysis v2| Report[Profile report]
    Hydrator[Snapshot hydrator] -->|claim jobs| D1
    Hydrator -->|read versioned shards| R2[(R2 credit index)]
    Hydrator -->|materialize projections| D1
```

The browser requests history in pages of 50, pins evidence reads to one snapshot, assembles the report, and submits missing targets in a separate bounded request. Hydration never blocks report assembly. Curated examples use a static fixture and do not call Last.fm or queue hydration. The former Python server assembler lives in `reference/server-assembly/` and remains available only for local comparison through `yarn dev:api:reference`. The ETL, object layout, publication, and license handling are documented in [MusicBrainz credit index](docs/musicbrainz-credit-index.md).

## Front-end

Both interfaces use Svelte, strict TypeScript, Vite, semantic HTML, and project-owned CSS. The public application is a static build with no server credentials. Its versioned browser code assembles the Profile Analysis v2 report.

### Central Panel

The central panel is the public analysis experience in `web/`. A visitor enters a Last.fm username, selects a listening period, and receives the currently available report. The report is organized into an instrumental portrait, family palette, sound-source balance, discovery, evidence coverage, technical notes, and a shareable image generated locally in the browser.

The interface handles incomplete datasets as first-class states. Sections remain unavailable when coverage or diversity thresholds are not met, and the report identifies whether its data is ready, partial, or insufficient. Instrument details are loaded on demand from the API.

A development-only ASCII portrait workspace is available at `/portrait-preview.html`. Its 20 × 17 editor supports:

- per-family drawings and arbitrary printable ASCII characters;
- click, drag, keyboard-accessible cells, erasing, and horizontal mirroring;
- undo, reset, and live portrait previews;
- browser-local persistence;
- copying either rendered ASCII or source-ready line arrays.

The preview uses the production portrait generator but is excluded from the production build.

### Editorial Panel

> The editorial panel is in an early stage of development.

The separate application in `editorial/` manages instrument and sound-family records. Editors can review descriptions, sound-production notes, optional curiosities, citations, source metadata, further-reading links, images, rights information, and review status.

Changes are stored in the editor's browser and can be exported as a validated JSON review. The exported snapshot is committed to `editorial/src/instruments.json`; the editorial publication workflow validates it, generates idempotent SQL, and synchronizes Cloudflare D1. See [Editorial publication](docs/editorial-publishing.md).

## Local Installation

### Prerequisites

- Git
- Python 3.13 or later
- Node.js 24 or later
- Yarn Classic 1.22

### 1. Clone the repository

```sh
git clone https://github.com/rosa-gus/timbre-palette.git
cd timbre-palette
```

### 2. Install the JavaScript dependencies

```sh
yarn install --frozen-lockfile
```

### 3. Create the Python environment

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

### 4. Configure local secrets

Copy the development template:

```sh
cp .dev.vars.example .dev.vars
```

Set `LASTFM_API_KEY` in `.dev.vars` to a valid Last.fm application key. The key is optional when using the local reference mock. `IMAGE_ASSET_BASE_URL` may remain set to the local Vite origin. Never commit `.dev.vars` or place credentials in frontend environment variables.

### 5. Start the API

To run the API with local D1 migrations:

```sh
yarn dev:api
```

The public Worker API is available at `http://localhost:8787`; its OpenAPI document is at `http://localhost:8787/openapi.json`.

For deterministic profile data without a Last.fm key or external requests, run the local server-assembly reference in mock mode:

```sh
yarn dev:api:mock
```

The mock reference listens on port `8788`. Enable server mode and set its URL as described below to use it for profile requests; catalog resources continue to use the active TypeScript API on port `8787`.

### 6. Start the public front-end

In a second terminal:

```sh
VITE_API_BASE_URL=http://localhost:8787 yarn dev:web
```

Open `http://127.0.0.1:5173/`. The ASCII portrait workspace is available at `http://127.0.0.1:5173/portrait-preview.html`.

Browser assembly is the default in development and production. To compare it with the retained Python server assembler, start the local reference service:

```sh
yarn dev:api:reference
```

Then set these values in the ignored `.env.local` file before starting Vite:

```dotenv
VITE_PROFILE_ANALYSIS_MODE=server
VITE_PROFILE_SERVER_API_BASE_URL=http://127.0.0.1:8788
```

The reference Worker is for local comparison only and has no production deployment role. Remove those values to return to browser assembly. `VITE_API_BASE_URL` selects the active TypeScript API URL; the local default is `http://localhost:8787`. Runtime mode can also be selected through `public/profile-analysis-config.json` without rebuilding the front-end.

### 7. Start the editorial panel

In another terminal:

```sh
yarn dev:editorial
```

Open `http://127.0.0.1:5174/`.

### Validation commands

```sh
.venv/bin/pytest
yarn editorial:validate
yarn typecheck:web
yarn typecheck:editorial
yarn typecheck:api
yarn typecheck:hydrator
yarn build:web
yarn build:editorial
```

Regenerate the active API Worker bindings after changing `wrangler.jsonc` with `yarn types:api`.

## Guidelines

Timbre Palette follows an honesty-first editorial and technical policy:

- It is not a personality test and makes no scientific, psychological, diagnostic, or behavioral claims.
- The listening temperament is a deterministic editorial interpretation of recurring musical characteristics, not a statement about the listener's identity or personality.
- Published information about an instrument must be supported by legitimate, traceable sources. Citations and review state must remain attached to the claims they support.
- Direct evidence is preferred to inference. When evidence does not support a specific instrument, the system should use a defensible sound family or report the information as unknown.
- Missing or low-confidence evidence must remain visible through coverage, confidence, provenance, and availability states.
- The application does not score musical taste, rank listeners, or imply that one palette is superior to another.

The full editorial policy is documented in [docs/editorial-policy.md](docs/editorial-policy.md).

## Technical Limitations

- Timbre Palette analyzes metadata and reviewed credits; it does not analyze audio, isolate stems, or estimate an instrument's loudness or prominence from a recording.
- Instrument credits are incomplete and unevenly distributed across artists, genres, regions, and release formats. A missing instrument in a report does not imply that it is absent from the music.
- Contemporary music can be especially difficult to document because detailed personnel and instrument credits are often sparse, fragmented across platforms, or omitted from public structured metadata.
- A recording present in MusicBrainz may have no usable instrument relationships, and a release-level credit cannot automatically be treated as evidence for every track.
- Catalog coverage is still limited. Snapshot hydration may improve a later report, but it cannot guarantee complete attribution.
- The offline MusicBrainz index is a versioned derivative snapshot. It can lag behind live edits; its snapshot version, source URL, attribution, and license remain attached to normalized evidence.
- Results depend on the public top-track history returned by Last.fm and therefore do not represent a complete listening archive.

## License

The original source code in this repository is licensed under the [GNU General Public License, version 3](LICENSE.txt);

Third-party software remains subject to the licenses and copyrights of its respective authors. Photographs, videos, fonts, and other third-party media are not relicensed under the GPL; their respective authors and rights holders retain all applicable rights. Asset-specific attribution and licensing information is available in [assets/CREDITS.md](assets/CREDITS.md).
