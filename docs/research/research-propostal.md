# Production context for sparsely documented music

Underground scenes and music made primarily with production software often have
little or no documented instrument credit. A recording may be made by one person
or a small group using programmed sounds, synthesis, and samples rather than a
conventional ensemble. Missing MusicBrainz instrument relationships are therefore
especially common for the music this project should still be able to describe.
Neither successful identity resolution nor Artist Vocabulary guarantees a useful
result for these recordings.

Investigate a third, separately labeled layer of **possible production context**.
First, evaluate recording-scoped relationships that directly document techniques
such as programming or sampling. Report those as technique evidence, without
converting them into a claim about a specific instrument or software product.
For recordings without such evidence, test a versioned offline calculation using
track-level scene or subgenre tags, artist tags with lower weight, and reliable
release-period information. Derive candidate sound families or techniques from
documented examples across multiple independent artists, rather than maintaining
an expanding editorial list of genre-to-instrument rules.

The calculation must require enough independent examples, limit the influence
of any one artist, and abstain when tags, dates, or examples are too sparse or
ambiguous. The documented subset may be biased toward better-cataloged artists;
its frequency is not automatically a probability for an undocumented track.
Prefer broad descriptions such as programming, synthesis, or sampled sounds to
unsupported instrument-level claims. A scene tag alone never proves what is in
a particular recording, and a digital production context never identifies the
DAW used.

This layer would have its own reach, provenance, eligibility rules, and
methodology version. It must not increase `track_palette.coverage_tracks` or
`coverage_plays`, change direct-evidence confidence, or unlock the direct
palette's discovery, sound balance, or temperament. Before implementation,
pilot it on contemporary profiles with insufficient evidence and review a sample
of its claims for usefulness and overstatement. Adopt it only if it adds useful
context while reliably withholding claims the data cannot support.
