# Analysis methodology — API v2

Current direct-palette methodology version: `0.5.0`.

The API v2 keeps two products independent and versioned:

- `track_palette` uses direct recording/track evidence and owns coverage,
  sound balance, discovery, and temperament;
- `artist_vocabulary` describes recurring documented instruments among artists
  represented in the listening history.

## Direct track palette

Only mapped instrument or family facts with `recording` or `track` scope count
as direct evidence. Release context, unresolved relationships, programming,
samples, and pending hydration do not increase direct coverage.

The Last.fm adapter reads up to 200 ranked candidates in one page. The catalog
projection is queried in batches for the whole candidate page; the analysis
does not discard undocumented candidates before calculating its denominator.
This allows already-materialized evidence below rank 50 to be used without
turning catalog discovery into an evidence-biased sample. Hydration remains a
separate budget: at most 50 missing recording/track identities from a request
are enqueued, preserving Last.fm rank order.

```text
track coverage = covered tracks / total tracks
play coverage  = plays in covered tracks / total plays
```

`coverage_tracks` and `coverage_plays` remain exclusive to
`track_palette`. The direct palette has two levels:

- a useful documented sample requires at least five covered tracks, 5% play
  reach, and two covered artists when the history contains two or more;
- discovery and temperament use the same useful sample gate, then apply their
  own recurrence and contrast checks. They do not change the palette's
  top-level status.

For `discovery`, an instrument-level claim must recur in at least three
documented tracks from two artists and account for no more than 35% of the
documented plays. The selection is based on the period's evidence; it does not
depend on a manually assigned `unexpected` flag.

For `temperament`, at least two families need three documented tracks each and
the second family must reach 10% of the documented play share. The resulting
text remains a deterministic editorial interpretation, not a claim about the
listener's personality.

`ready` means the first gate passed. `partial` means that some direct evidence
can be shown but the sample is below that gate. `insufficient` means that no
track has accepted direct evidence. Asynchronous hydration is reported in the
separate `hydration` object and does not downgrade a ready sample.

## Artist vocabulary candidate

The candidate policy is deliberately configurable and is not frozen by the
the initial research sample. An instrument qualifies for an artist when it
appears in at least three distinct documented recordings. The initial vocabulary
gate then requires:

- track reach of at least 10%;
- play reach of at least 10%;
- at least three qualified artists when the history contains three or more;
- artist contribution below the configured concentration limit.

```text
artist contribution = capped play weight
                      × family prevalence
                      × evidence quality

family score = sum of artist contributions
```

When multiple qualifying instruments map to the same family for one artist,
the implementation uses the highest prevalence conservatively. The current
snapshot contains direct relationships, so its initial evidence quality is
`1.0`; future snapshot schemas may provide a more granular quality model.

Vocabulary reach is not direct coverage. A missing artist MBID, an unmapped
instrument, or pending hydration remains visible in availability and never
becomes inferred evidence. If the materialized rows already pass the gate, the
vocabulary can be `available` while additional artist rows are still pending.
Pending is reserved for work that could still change an insufficient result;
work that cannot meet the thresholds is reported as `insufficient`.

## Availability and versioning

The vocabulary exposes `available`, `pending`, or `insufficient`. The direct
palette uses `ready`, `partial`, or `insufficient`. The default view is the
direct palette when it is ready, the artist vocabulary when it is available and
the direct palette is not ready, and null when neither product has a primary
result. A partial direct palette remains in the response as a limited view.

Every response identifies the active snapshot and methodology versions. Any
change to recurrence, reach, weighting, concentration, evidence eligibility, or
section gates requires a methodology version increment and updated regression
fixtures.
