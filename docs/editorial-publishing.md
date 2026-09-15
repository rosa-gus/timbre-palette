# Editorial Publication

Editorial content is maintained as a versioned JSON snapshot and published as data. Database migrations are reserved for schema changes.

## Source of truth

The canonical snapshot is `editorial/src/instruments.json`. The editorial panel starts from this file, stores working changes in browser storage, and exports a schema-v1 snapshot. The exported JSON object can replace the canonical file after review; the panel accepts both the original seed array and the exported object.

The publisher updates instrument and family text, source metadata, curiosity blocks, citations, further-reading state, and resource-level review metadata. Removed curiosity blocks are retained as `deprecated` records. Source records are retained for provenance.

## Review flow

1. Edit a resource in the editorial panel.
2. Export the JSON snapshot.
3. Commit the snapshot in a pull request.
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
