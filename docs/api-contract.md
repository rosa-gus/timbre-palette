# Public API and profile assembly contract

The active public API is the TypeScript Cloudflare Worker configured by the root `wrangler.jsonc`. Its OpenAPI 3.1 document is served at `GET /openapi.json`. The Worker provides profile inputs, snapshot evidence, catalog resources, and asynchronous hydration scheduling. The browser assembles the Profile Analysis v2 report.

The active API runtime version is `3.0.0`, reflecting the split v3 profile-input and evidence contract. The report schema remains v2. The local FastAPI server-assembly reference retains version `2.1.1`.

The former FastAPI implementation remains in `reference/server-assembly/` for local comparison. It is not deployed as the public API or used by the default front-end runtime.

## Profile request flow

For a real profile, the browser performs these operations:

1. Request the first 50-track Last.fm page for the selected period.
2. Read public profile metadata while fetching any remaining pages.
3. Submit each page's track and artist MBIDs to the evidence endpoint. The first response selects the active snapshot; later batches send its version to remain pinned to the same snapshot.
4. Assemble the report from all returned history and evidence in the browser.
5. Submit pending recording, track, and artist identities to the hydration endpoint. The browser waits for the queue's `202` acknowledgement, not for the hydrator to finish processing those targets.

The browser reads no more than four Last.fm pages, for a maximum of 200 ranked tracks. Each history request contains exactly 50 tracks. The API key stays in the Worker secret and is never included in the response.

## Profile input endpoints

### `GET /v3/profiles/{username}/tracks`

Returns the upstream Last.fm `user.gettoptracks` JSON for one page. Supported query parameters:

| Parameter | Values | Default |
| --- | --- | --- |
| `period` | `7day`, `1month`, `3month`, `6month`, `12month`, `overall` | `7day` |
| `page` | Integer from 1 to 4 | `1` |
| `limit` | Exactly `50` | `50` |

The response is streamed from Last.fm. Last.fm error objects may therefore appear in an HTTP `200` response; the browser recognizes and translates those provider errors for the interface.

### `GET /v3/profiles/{username}/metadata`

Returns `{ username, profile, wall_ms }`. `profile` is the public Last.fm `user.getinfo` object. Profile metadata is optional to report assembly: the browser continues with null metadata fields if this request fails, except when the request was cancelled.

## Snapshot evidence endpoint

### `POST /v3/evidence`

Request body:

```json
{
  "track_mbids": ["00000000-0000-4000-8000-000000000000"],
  "artist_mbids": ["00000000-0000-4000-8000-000000000001"],
  "snapshot_version": "20260912-002318"
}
```

Both MBID arrays are required and may be empty. Each array accepts at most 50 valid MusicBrainz UUIDs. `snapshot_version` is optional on the first batch and pins subsequent batches to the same snapshot.

The response includes:

- `snapshot`: snapshot version, index schema, manifest hash, object prefix, and methodology version;
- `aliases`: track-to-recording identity mappings;
- `recording_statuses` and `recording_claims`: direct track or recording evidence;
- `artist_statuses` and `artist_vocabulary`: artist-level recurring instrumentation evidence;
- `counts` and `wall_ms`: batch sizes and elapsed Worker time.

The endpoint performs read-only D1 queries. It does not add hydration jobs. Direct track evidence and artist vocabulary remain separate products: vocabulary does not increase track or play coverage and cannot unlock discovery, sound balance, or temperament.

## Hydration endpoint

### `POST /v3/hydration`

Request body:

```json
{
  "snapshot_version": "20260912-002318",
  "recording_targets": [
    { "kind": "track", "mbid": "00000000-0000-4000-8000-000000000000" }
  ],
  "artist_mbids": ["00000000-0000-4000-8000-000000000001"]
}
```

The request accepts at most 50 recording or track targets and 200 artist MBIDs. Targets are deduplicated before `INSERT OR IGNORE` writes to the snapshot hydration queue. A successful request returns HTTP `202` with the accepted target count and snapshot version. The snapshot hydrator claims those jobs, reads the corresponding R2 shard, and materializes D1 projections in the background.

The browser preserves pending state in the current report. A later profile request can use the newly materialized evidence.

## Browser report model

The browser builds the `ProfileAnalysisV2` object from the paginated history and evidence responses. Track coverage uses every valid track returned for the selected period as its denominator. Missing recording or track identities are queued up to the 50-target per-report limit; the browser separately deduplicates up to 200 artist identities.

The report keeps `track_palette` and `artist_vocabulary` independent. The direct palette owns track and play coverage, sound balance, discovery, and temperament. Vocabulary reach belongs only to the artist vocabulary. Pending hydration does not turn missing catalog rows into evidence or change the direct palette's availability state.

## Curated example

The example profile is assembled in the browser from `public/profile-analysis-example.json`, generated from `reference/server-assembly/src/palette_api/_curated_example_history.json` by `yarn prepare:images`. It does not call Last.fm, D1, or the hydration endpoint. The sample ID and selected period seed deterministic recording selection and play counts for the current fixture version. Synthetic play counts are illustrative and are not Last.fm observations.

The sample includes direct track evidence and a small artist-vocabulary fixture. Its `history_source` is `mock`, its instrumentation source is `catalog`, and its report sets `is_example` to `true` with the effective ID in `example_id`.

## Catalog endpoints

- `GET /v2/instruments/{slug}` returns a reviewed instrument or sound-family resource, including eligible editorial sections, citations, image metadata, and further reading.
- `GET /v2/catalog/stats` returns `recordings_with_evidence` from the active snapshot projection.
- `GET /health` returns the Worker service name and API version.

Catalog resources retain the v2 route prefix while profile input and evidence use v3 routes. The v2 prefix for catalog resources does not mean that the former v2 server-assembled profile endpoint remains available on the public Worker.

## Errors and logs

API-generated failures use an English message and a stable machine-readable error code:

```json
{
  "error": "snapshot_unavailable",
  "message": "The requested evidence snapshot is unavailable."
}
```

Worker logs use structured English event names and field names. They include elapsed time and request counts where useful and omit raw exception text. Last.fm responses streamed by the tracks endpoint remain provider responses, not API-generated error envelopes.

## Runtime assembly mode

`public/profile-analysis-config.json` selects the default assembly mode at runtime. It defaults to `browser`. `VITE_PROFILE_ANALYSIS_MODE=server` can override it during local development, and `VITE_PROFILE_SERVER_API_BASE_URL` selects the server-reference endpoint. The server mode exists only to compare local results against the retained FastAPI implementation. The reference service is started with `yarn dev:api:reference` on port `8788`; do not deploy it as the production API.

`VITE_API_BASE_URL` selects the active TypeScript Worker URL. The Last.fm key belongs in the Worker secret or local `.dev.vars`; it must never be placed in a `VITE_*` variable or static runtime configuration.
