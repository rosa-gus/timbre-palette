# Public API Contract

FastAPI generates the canonical OpenAPI document at `GET /openapi.json`. This document records semantic guarantees that clients must not infer from free-form messages.

## Catalog statistics

`GET /v1/catalog/stats` returns `recordings_with_evidence`: the number of unique recordings with an accepted claim, a valid family, and recording- or track-level evidence. Release credits, unresolved candidates, and pending jobs are excluded.

The response is publicly cacheable for five minutes. Without a D1 binding it returns `0` with `Cache-Control: no-store`; it never fabricates statistics.

## Palette report

`GET /v1/profiles/{username}/palette` always returns the `PaletteReport` envelope. The public analysis states are all returned with HTTP `200`:

| `analysis.status` | Meaning                                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `insufficient`    | No published instrumental evidence is available to build a palette. Enrichment may continue asynchronously.                                |
| `partial`         | A usable result exists, but a coverage gate, interpretation gate, or pending/transient enrichment prevents a final result.                 |
| `ready`           | The interpretation gate is satisfied and no pending/transient enrichment can change the report. This does not require 100% track coverage. |

In `insufficient`, `families` is empty and `sound_balance`, `discovery`, and `temperament` are `null`.

### Coverage and recording state

`analysis.coverage_tracks` is the fraction of history tracks with at least one accepted instrumental layer. `analysis.coverage_plays` is the fraction of total plays represented by those tracks. There is no third generic `coverage` field.

`analysis.recording_status_counts` always contains these six fields, including zero values:

- `resolved`: accepted identity and instrumental evidence are available;
- `pending_enrichment`: enrichment is queued or not yet completed;
- `ambiguous`: multiple plausible identities require review;
- `resolved_without_evidence`: identity is resolved but no accepted instrumental claim exists;
- `transient_failure`: a retryable enrichment failure occurred;
- `terminal_failure`: no automatic retry is scheduled.

Each item in `recordings` repeats its authoritative `status` with title, artist, play count, MBID, and Last.fm URL. `status_detail` is explanatory only.

`analysis.vocal_presence` is derived from documented `voice` claims and counts each recording once, even when it has multiple vocal roles. It exposes documented tracks, distinct artists, plays, and the corresponding track and play ratios. Programming, samples, and release context are excluded.

`analysis.section_availability` reports availability for `families`, `sound_balance`, `discovery`, and `temperament` using `available`, `insufficient_coverage`, `insufficient_diversity`, `insufficient_nature_evidence`, or `no_candidate`.

## Catalog and methodology semantics

Family-level claims can contribute to a family but do not create an instrument layer or infer a sound nature. Release-level evidence is retained for provenance and review but does not count as accepted coverage.

`analysis.catalog_version` identifies the active `catalog_publications` revision, or the fallback `catalog_versions` revision before the prepared catalog is published. `analysis.methodology_version` identifies the calculation rules; see [Analysis Methodology](methodology.md).

## Instrument resources and editorial content

`GET /v1/instruments/{slug}` returns an instrument or sound-family resource with `catalog_version`. It includes a brief description, sound production, optional curiosity sections, sources, citations, images, and optional further-reading links.

The current public editorial scope does not include historical-origin sections. `sections` and `sources` may be empty. Empty text, `draft`, and `deprecated` blocks are not returned. Blocks with `sourced`, `reviewed`, or `published` status are projected only when `claim_support_verified` is true and every cited source has `metadata_verified` set to true. A `sourced` block may therefore be public while awaiting formal editorial review; its review state remains visible in the response.

`further_reading` is optional and contains HTTP(S) links with a title and optional publisher. Only `reviewed` or `published` links are exposed. Further reading never replaces citations attached to editorial text.

Citations are optional for the base `description` and `sound_production` fields. Curiosity sections require citations before leaving `draft` status.

The editorial panel stores working revisions in the browser and exports JSON. The committed snapshot is validated and published to D1 by GitHub Actions; the panel itself never receives database credentials or writes to the API.

## Images and cache identity

Reports and instrument resources may include `InstrumentImage` objects for families, instrument layers, discoveries, and editorial resources. Images are editorial assets, not instrumental evidence. `resolution` identifies `exact`, `related`, or `family`; `caption` must clarify when the depicted subject differs from the requested instrument.

Image URLs are absolute. The default local base is `http://127.0.0.1:5173/`; `IMAGE_ASSET_BASE_URL` selects another base. Run `yarn prepare:images` to prepare public assets and regenerate the image catalog. `analysis.image_catalog_version` and the resource-level `image_catalog_version` must participate in cache keys.

Family tones are stable catalog data exposed as `shadow` and `highlight`. They are independent of the profile and are not evidence.

## Errors

An empty listening history is not an analysis state: it returns `ApiError` with HTTP `422` and code `empty_listening_history`. A nonexistent Last.fm profile returns HTTP `404` with code `lastfm_profile_not_found`. Other integration failures are returned as structured `ApiError` responses without exposing credentials or upstream response bodies.
