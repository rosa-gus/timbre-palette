# Analysis methodology — API v2

The API v2 keeps two products independent and versioned:

- `track_palette` uses direct recording/track evidence and owns coverage,
  sound balance, discovery, and temperament;
- `artist_vocabulary` describes recurring documented instruments among artists
  represented in the listening history.

## Direct track palette

Only mapped instrument or family facts with `recording` or `track` scope count
as direct evidence. Release context, unresolved relationships, programming,
samples, and pending hydration do not increase direct coverage.

```text
track coverage = covered tracks / total tracks
play coverage  = plays in covered tracks / total plays
```

`coverage_tracks` and `coverage_plays` remain exclusive to
`track_palette`. The existing direct palette gates and interpretation sections
are preserved under their own methodology version.

## Artist vocabulary candidate

The candidate policy is deliberately configurable and is not frozen by the
small research sample. An instrument qualifies for an artist when it appears in
at least three distinct documented recordings. The artist vocabulary gate then
requires:

- track reach of at least 40%;
- play reach of at least 40%;
- at least four qualified artists when the history contains four or more;
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
becomes inferred evidence.

## Availability and versioning

Both products expose `available`, `pending`, or `insufficient` states. The
default view is the direct palette when it is sufficient, the artist vocabulary
when only it is sufficient, and null when neither is sufficient.

Every response identifies the active snapshot and methodology version. Any
change to recurrence, reach, weighting, concentration, evidence eligibility, or
section gates requires a methodology version increment and updated regression
fixtures.
