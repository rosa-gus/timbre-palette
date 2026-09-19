# Public API contract

FastAPI publishes the active contract at `GET /openapi.json`.

## API v2

`GET /v2/profiles/{username}/analysis?period=...` returns one envelope with
two independent products:

- `track_palette`: direct instrumental evidence attached to the listener's
  tracks;
- `artist_vocabulary`: recurring instruments documented in recordings
  associated with artists in the history.

The response also contains `snapshot`, `hydration`, `available_views`, and
`default_view`. The two products never share coverage metrics: track and play
coverage belong only to `track_palette`; vocabulary reach belongs only to
`artist_vocabulary`.

The vocabulary is available only when its configured recurrence, track reach,
play reach, artist diversity, and concentration gates are satisfied. A pending
snapshot hydration is represented explicitly and is not treated as an empty
catalog. Instrument and family rows are accepted only when they resolve to the
editorial D1 taxonomy.

`discovery`, `sound_balance`, and `temperament` belong exclusively to the direct
track palette. They are never unlocked by artist vocabulary.

The endpoint returns HTTP `200` for a valid history, including insufficient or
pending analysis states. A missing Last.fm profile, invalid period, empty
history, unavailable active snapshot, or upstream failure uses the structured
`ApiError` response.

`GET /v2/instruments/{slug}` returns the reviewed editorial resource. `GET
/v2/catalog/stats` returns counts from the active snapshot projection.

## API v1 — deprecated

The former `/v1/profiles/{username}/palette` contract produced only a direct
track palette and is retained here solely as historical context. Its endpoints
are no longer registered or available in the runtime and are not included in
the OpenAPI document.
