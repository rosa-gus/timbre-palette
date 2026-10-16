# Editorial Publication

Editorial content is maintained as a versioned JSON snapshot and published as data. Database migrations are reserved for schema changes.

## Source of truth

The canonical schema-v2 snapshot is `editorial/content/catalog.json`. It references neutral `entities.json`, bibliographic `sources.json`, and `locales/{locale}.json`. The panel edits Portuguese source content and separate translations, saves working changes in browser storage, and exports a combined schema-v2 snapshot. Existing schema-v1 browser drafts remain readable.

The publisher updates instrument and family text, source metadata, curiosity blocks, citations, further-reading state, and resource-level review metadata. Removed curiosity blocks are retained as `deprecated` records. Source records are retained for provenance.

## Review flow

1. Edit a resource in the editorial panel.
2. Export the JSON snapshot.
3. Split the export with the command below and commit the content directory in a pull request.
4. CI runs `yarn editorial:validate` and rejects invalid citations, source metadata, review identity, status requirements, or unsupported publication flags. Citations are optional for base description and sound-production fields, but required for every non-draft curiosity.
5. After merge to `main`, GitHub Actions renders a deterministic SQL publication with the manifest hash, commit SHA, and publishing actor.
6. Wrangler applies the SQL to the remote D1 database and verifies the active publication.
7. The API exposes only content whose status, claim support, citations, and source metadata satisfy the public projection rules.

Content with `sourced` status may be public while formal review is pending when `claim_support_verified` is true, it has a citation, and every cited source has `metadata_verified` set to true. `reviewed` and `published` content also require a reviewer and review date. Base description and sound-production fields may be reviewed and published without linked citations.

## Local commands

```sh
yarn editorial:validate
yarn editorial:sql > /tmp/timbre-palette-editorial.sql
yarn wrangler d1 execute DB --local --file=/tmp/timbre-palette-editorial.sql --yes -c wrangler.jsonc
```

The SQL is repeatable: sources, blocks, citations, resources, and reviews use deterministic upserts. A publication revision is recorded in `editorial_publications`; only the latest successful revision is active. The generated SQL is temporary and must not be committed.

## GitHub Actions secrets

Configure these repository secrets under **Settings → Secrets and variables → Actions**:

- `CLOUDFLARE_ACCOUNT_ID`: the Cloudflare account identifier that owns the Worker and D1 database.
- `CLOUDFLARE_API_TOKEN`: a scoped Cloudflare API token with the `D1 Edit` permission for the target account. Do not use a global API key or expose the token to the editorial front-end.

The D1 binding in `wrangler.jsonc` must also contain the real remote `database_id`; `local` is only a development placeholder. The workflow applies pending migrations, then uses the `DB` binding with `wrangler d1 execute DB --remote --file=...`.

## Operational notes

The publication workflow is serialized to prevent concurrent revisions. Manifest validation happens before editorial data writes. The SQL applies data updates before marking the revision active, and the final verification confirms the expected revision and manifest hash. Cloudflare D1 file execution must not include an explicit `BEGIN`/`COMMIT` wrapper; this keeps the generated file compatible with Wrangler imports.

Instrument responses use a five-minute edge-cache TTL, so a publication may remain stale for at most that period without a cache purge. D1 updates alone do not invalidate an already cached HTTP response.

## Translations

Start a translation in the panel, edit all text and image descriptions, and record its own reviewer, date, and approval. Source citations, identifiers, image rights, and original bibliographic titles are shared. UI language is independent of content language.

A translation records the SHA-256 revision of its source resource, including provenance and asset identity. Source changes make it stale; use the panel to compare, update the source revision, and review again. Updating the revision resets approval. Stale and withdrawn translations remain stored but cannot be public. Publication keeps resource/block translations and immutable snapshot history per release.

Locale rows belong to a publication revision. The API reads only the active release; staged or failed releases cannot replace its translations. Reusing a revision with different content is rejected.

```sh
python3 scripts/publish_editorial.py /path/to/export.json --write-content editorial/content
```

Apply migration `0021_editorial_translations.sql` before deploying the locale-aware Worker. The existing publication workflow applies pending migrations before publishing. `GET /v2/instruments/{slug}?locale=en` returns one complete eligible locale, falling back to `pt-BR`. The response declares `locale`, `requested_locale`, source/content/publication revisions, and `Content-Language`. Cache keys must retain the query string; the ETag also identifies the requested locale, publication, and image catalog. No additional language is published in this phase.
