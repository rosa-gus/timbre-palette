# Editorial Policy

This policy governs how Timbre Palette researches, writes, cites, reviews, and publishes public information about instruments and sound families.

Its goal is to keep the product concise and accessible without presenting unsupported claims as facts. This document covers editorial content only. The API contract, catalog schema, persistence model, and analysis business rules are documented separately in the [Public API contract](api-contract.md), [Catalog architecture](catalog-architecture.md), and [analysis methodology](methodology.md).

## Scope

The policy applies to public content about:

- instrument and sound-family classification;
- sound production, construction, materials, mechanisms, and musical roles;
- names, relationships, and documented historical or cultural context;
- curiosities and other factual summaries;
- people, communities, traditions, places, and periods associated with an instrument;
- images, captions, credits, and further-reading links included with an editorial profile.

It applies wherever this content is published, including the API, public front-end, shareable images, and editorial tools.

## Core principles

### Evidence before effect

Published factual claims should be supported by a traceable source. In the current catalog contract, citations are optional for the concise `description` and `sound_production` fields; those fields must remain conservative when no source is attached. Specific, surprising, or controversial claims require stronger evidence than broad descriptive statements. When evidence is insufficient or contradictory, the text must be narrowed, qualified, or withheld.

### Claim-level citation

The unit of publication is an editorial block: a sentence or short paragraph expressing a verifiable idea. Citations must be attached to the block they support, rather than added only to the instrument profile as a whole.

### Fact, synthesis, and interpretation remain distinct

Editorial content must distinguish between:

- a fact supported by a source;
- an `editorial_summary` written from one or more identified sources;
- recording evidence that supports the presence of an instrument in a specific recording;
- the listening temperament, which is a deterministic and non-scientific interpretation of an analysis.

A source about an instrument's history does not prove that the instrument appears in a recording. A recording credit does not automatically support a historical or technical statement about the instrument.

The listening temperament is not a personality test and must not be framed as a scientific, psychological, diagnostic, or behavioral assessment.

### Context and respect

Historical and cultural material must preserve relevant distinctions between communities, regions, traditions, religious practices, migration, colonial histories, and authorship. Avoid exoticizing language, generalized ownership claims, and certainty that the sources do not support.

### Transparency

Coverage, uncertainty, source scope, review state, and editorial limitations must remain visible wherever they affect interpretation. The number of sources must not be presented as a substitute for source quality.

## Content that requires a source

The following require at least one specific citation:

- curiosity blocks once they leave `draft` status;
- dates, origins, invention, authorship, diffusion, decline, or revival;
- regional, cultural, social, or religious associations;
- alternative names, etymologies, relationships, and representative examples;
- claims attributed to makers, performers, composers, movements, or institutions;
- curiosities presented as factual information.

The base `description` and `sound_production` fields are exceptions in the current product contract: their source links are optional. This does not authorize unsupported historical or culturally sensitive claims in those fields.

Interface labels, slugs, and project-defined taxonomy do not require citations by themselves. Any factual premise behind a project-defined category remains subject to this policy.

The listening temperament does not require historical citations because it is a product interpretation. It must be labelled as non-scientific and remain reproducible from the versioned methodology.

## Source selection

Preferred sources include:

- museums, universities, libraries, archives, and preservation institutions;
- identified books, scholarly articles, and reference works;
- research or technical documentation from accountable organizations;
- manufacturer documentation for characteristics of the manufacturer's own instruments;
- primary sources such as patents, historical catalogs, interviews, treaties, and archival records, interpreted within their context.

Collaborative databases, specialist journalism, and official artist or organization pages may provide useful supporting material when authorship, provenance, and scope are visible.

The following must not be the sole basis for a published factual block:

- anonymous or editorially unaccountable pages;
- stores, advertisements, and promotional copy used for broad historical claims;
- unsourced social posts, forums, and blogs;
- search-result snippets, automated summaries, and AI-generated text.

These materials may suggest research leads, but they are not sufficient evidence on their own.

## Source records and writing standards

A source record should contain enough metadata for another person to find and evaluate it: title, author or responsible organization, publication or publisher, date when available, stable URL or bibliographic identifier, locator when applicable, access date, source type, language, and relevant scope or licensing notes.

A URL alone is not a complete citation. Page, section, chapter, entry, timestamp, or another locator should be recorded whenever it is necessary to verify the claim. Broken links require review, but link availability does not replace evaluation of the source itself.

Editorial text must be an original, faithful paraphrase. It must not copy extended passages or silently expand a source's scope. Direct quotations should be brief, necessary, and clearly marked. Relevant qualifications and disagreements must be preserved.

Historical claims require additional care:

1. Distinguish invention, first documentation, manufacture, and popularization.
2. Use approximate language when dates or origins are uncertain.
3. Attribute conflicting accounts instead of selecting one without explanation.
4. Do not treat missing records as proof that an event or practice did not exist.
5. Use sources close to the subject and include perspectives from affected communities when relevant.

## Review and publication states

Each editorial block uses one of the following states:

- `draft` — in progress and not eligible for public publication;
- `sourced` — citations are registered; the block may be publicly projected when claim support and all cited source metadata are verified, but the formal editorial review is still pending;
- `reviewed` — content, source metadata, and claim-to-source correspondence have been checked;
- `published` — approved for the active public catalog;
- `deprecated` — withdrawn from public use while its history is retained.

The minimum workflow is:

1. Register and assess the sources when available.
2. Write the block and attach claim-level citations to every non-draft curiosity.
3. Verify that each citation supports the exact scope of the claim.
4. Review clarity, context, limitations, and disagreements.
5. Record the reviewer and review date, then publish a new catalog version.

`sourced` content must not be presented as fully reviewed. The public API may return a `sourced` block only when `claim_support_verified` is true and every cited source has verified metadata. `draft` and `deprecated` content must not be returned by the public API. Further-reading links are optional and do not replace citations for the text they accompany.

Content involving contested history, living people, vulnerable communities, or culturally sensitive practices should receive a second review whenever possible.

## Publication checks

Before publication, validation and review must confirm that:

- every non-draft curiosity block has at least one citation;
- every citation resolves to a source in the same response or to a stable, documented public resource;
- every digital source has a title and an identifiable responsible author or organization;
- a locator is present where it is necessary to verify the claim;
- every publicly projected block has explicit support verification and every cited source has verified metadata;
- `reviewed` and `published` blocks have explicit support verification, reviewer, and review date;
- disputed claims are qualified or supported by appropriate independent evidence;
- recording evidence is not presented as general editorial evidence, and editorial sources are not presented as recording credits.

The API should return structured text, citations, sources, and review metadata rather than pre-rendered HTML. The front-end should expose citations next to the relevant block and make the source list accessible without overwhelming the primary reading experience.

Images are editorial assets, not evidence of instrument presence. Their caption must disclose when an image represents a related instrument or an entire family, and their photographer, provider, license, and source URL must be retained where available.

## Corrections, versioning, and rights

Every public publication must identify the catalog version. Corrections must preserve the previous content, reason for change, affected sources, date, and responsible reviewer. A new source that narrows or contradicts a claim should return the block to review rather than silently overwrite the decision.

Re-evaluate sources after a material correction, a relevant broken link, substantial new research, or a significant change to the source page. An access date records when a source was checked; it is not a permanent guarantee of currency.

Referencing a source does not authorize copying it. Text should be original and limited to the material required for explanation and verification. Quotes, images, illustrations, diagrams, audio, and other third-party material require compatible permission or licensing, with attribution and usage conditions preserved.

See the [instrument catalog](instrument-catalog.md) for current editorial records and [asset credits](../assets/CREDITS.md) for media attribution and licensing information.
