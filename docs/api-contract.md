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

The Last.fm history read requests up to 200 ranked candidates for the selected
period. The direct palette's denominators include every valid candidate
returned by that read, including candidates that are not yet documented. The
snapshot provider checks those identities in batched local D1 projections, so a
documented recording can contribute even when it is below the first 50 ranks.
Missing recording/track identities are capped at 50 new hydration targets per
request and are kept in Last.fm rank order. Artist targets remain deduplicated
separately because one artist hydration can serve many candidate tracks.

The vocabulary is available only when its configured recurrence, track reach,
play reach, artist diversity, and concentration gates are satisfied. If pending
artists could still change an insufficient result, its status is `pending`; if
the materialized rows already pass, it can be `available` with pending counts.
A pending snapshot hydration is represented explicitly and is not treated as an
empty catalog. Instrument and family rows are accepted only when they resolve
to the editorial D1 taxonomy.

`artist_vocabulary.reach.unresolved_artists` and `unresolved_tracks` count
history entries without an artist MBID. They are identity gaps, not pending
hydration work.

The direct palette uses `ready`, `partial`, and `insufficient` to describe the
amount of accepted recording evidence. `ready` is the useful five-track,
5%-play, two-artist sample gate. `partial` means direct evidence exists below
that gate. Hydration progress does not change these states. A track without a
MusicBrainz identity is reported as `unresolved_identity`; it does not create a
hydration job.

`discovery`, `sound_balance`, and `temperament` belong exclusively to the direct
track palette and retain their own evidence gates. Discovery uses recurring
instrument evidence from the period, while temperament uses recurring family
contrast. They are never unlocked by artist vocabulary.

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
