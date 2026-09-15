# Analysis Methodology — v0.3.0

This document specifies the deterministic rules that transform accepted instrumental evidence into a palette report. The same listening history, catalog revision, and methodology version must produce the same result.

## Eligible evidence

Only claims with published evidence levels `documented` or `editorially_verified` and recording- or track-level scope contribute to the palette. The following do not contribute:

- `release_context`, `tentative`, `estimated`, and `unknown` evidence;
- unmapped external relationships;
- generic or `additional` relationships;
- programming, samples, and release-level context.

Family-level claims count toward their family but do not create a specific instrument or infer a sound nature that the source did not provide. Vocal or `vocals` relationships with recording- or track-level scope contribute to documented `voice` presence when the family claim is accepted.

## Coverage

Coverage is measured independently by tracks and plays, then evaluated conjunctively:

```text
track coverage = covered tracks / total tracks
play coverage  = plays in covered tracks / total plays
```

A covered track has at least one accepted instrumental layer. The minimum covered-track count is:

```text
min(total tracks, max(absolute floor, ceil(ratio × total tracks)))
```

### Palette gate

The palette gate requires all of the following:

- track coverage ≥ 20%;
- play coverage ≥ 20%;
- at least `min(total tracks, max(5, ceil(0.20 × total tracks)))` covered tracks;
- at least three covered artists when the history contains three or more artists.

### Interpretation gate

The interpretation gate requires all of the following:

- track coverage ≥ 40%;
- play coverage ≥ 40%;
- at least `min(total tracks, max(8, ceil(0.40 × total tracks)))` covered tracks;
- at least four covered artists when the history contains four or more artists.

Track and play thresholds are never interchangeable. Meeting one dimension does not compensate for failing the other.

## Public analysis states

- `insufficient`: no eligible track is available to build a palette. Background enrichment may continue, but the request returns immediately.
- `partial`: eligible evidence exists, but the palette or interpretation gate is not satisfied, or pending/transient enrichment could change the result.
- `ready`: both gates are satisfied and no pending or transient enrichment remains that could change the report.

Terminal recording states such as `ambiguous`, `resolved_without_evidence`, and `terminal_failure` remain visible in `recording_status_counts`; they do not by themselves determine the analysis state.

## Palette calculation

For each covered recording:

1. Group layers by family.
2. Select the strongest layer per family using `prominence × confidence weight`.
3. Normalize the selected family weights within the recording.
4. Multiply the normalized weights by the recording's play count.
5. Aggregate the scores across recordings and normalize them into family shares.

Confidence weights are:

| Confidence            | Weight |
| --------------------- | -----: |
| `documented`          |   1.00 |
| `strongly_associated` |   0.75 |
| `estimated`           |   0.45 |

Each recording contributes at most its own play count. Multiple claims in the same family are consolidated, so detailed metadata cannot give a recording disproportionate influence. Family participation and aggregated confidence are calculated separately; confidence is not a measure of loudness or sonic prominence.

Family results are sorted by descending share, with the family slug as the deterministic tie-breaker.

## Sound nature and vocal presence

Sound nature is calculated from accepted layers with an explicit nature: `acoustic`, `electric`, `electronic`, `sampled`, or `hybrid`. `sound_balance` is returned only when at least 80% of the palette score has known nature. The `unknown` value preserves the remaining share.

Family-level claims do not invent a nature. Vocal presence and production nature are separate signals; the `voice` family may contribute to the palette without contributing to `sound_balance`.

`analysis.vocal_presence` counts only documented recording-level or track-level `voice` claims:

- `documented_tracks`: recordings with at least one accepted vocal claim;
- `documented_artists`: distinct artists represented by those recordings;
- `documented_plays`: plays from those recordings;
- `track_ratio` and `play_ratio`: the corresponding counts divided by the history totals.

A recording with lead, backing, and choral vocals counts once for each measure.

## Conditional sections

The report exposes section availability through `analysis.section_availability`.

- `families` is available when at least one covered recording exists; with no covered recording it is unavailable.
- `sound_balance` requires the known-nature threshold above.
- `discovery` requires the interpretation gate and an unexpected instrument-level claim present in at least three recordings and two artists.
- `temperament` requires the interpretation gate, an available sound balance, and at least two families with three or more recordings each. The second-ranked supported family must have a share of at least 15%.

Unavailable sections are not replaced with invented defaults. Their structured reasons may be `insufficient_coverage`, `insufficient_diversity`, `insufficient_nature_evidence`, or `no_candidate`.

## Temperament rules

The temperament is an editorial interpretation of observable palette relationships. It is deterministic, non-scientific, and never a personality or psychological assessment.

When the temperament prerequisites are met, identities are evaluated in this order:

1. **Movement with atmosphere**: `percussion` and `synthesizers` each represent at least 15% of the palette, co-occur in at least three covered recordings, and their co-occurrence represents at least 15% of covered plays.
2. **Electric body**: `plucked-strings` and the `electric` nature each represent at least 25% of their respective signals.
3. **Memory in cuts**: the `sampled` nature represents at least 15%.
4. **Electronic texture**: the `electronic` nature represents at least 25%.
5. **Nature fallback**: select the identity corresponding to the predominant nature (`acoustic`, `electric`, `electronic`, `sampled`, or `hybrid`).

The first matching identity wins. Its text must describe relationships in the data, not traits of the listener.

## Versioning and regression

`methodology_version` is included in every report. Any change to thresholds, eligible evidence, weighting, normalization, section gates, or temperament rules requires an explicit version increment and updated regression fixtures.

Regression tests must cover both coverage dimensions, artist diversity, family claims, rejected release-level evidence, unknown or unmapped candidates, discovery recurrence, temperament precedence, and invariance to track ordering.
