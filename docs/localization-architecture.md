# Localization architecture

Status: phase 5 implemented; browser validation pending.

## Ownership and dependency boundaries

| Owner                 | Localized content                                                                     | Planned location                               |
| --------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Public web app        | UI, accessibility, validation, report narratives, share images                        | `web/src/i18n/`                                |
| Editorial app         | Editor UI and validation messages                                                     | `editorial/src/i18n/`                          |
| API                   | Technical diagnostics; English initially                                              | `workers/api/src/errors/`                      |
| Editorial publication | Instrument and family names, descriptions, roles, blocks, image captions and alt text | `editorial/content/` with locale-specific data |

Each application owns its locale registry, fallback policy, and release schedule. There is no root locale bundle. The API and hydrator must not import either application's UI dictionaries or localization runtime. Shared contracts may contain neutral identifiers and schemas, never UI translations. API consumers need no web dependencies or translation downloads.

Editorial content is API resource data, not a web dictionary. The editorial app's UI language is independent of the language being edited. Canonical resources live in `editorial/content/`, separate from both UI dictionaries.

## Stable contracts

- Keep error codes, slugs, enums, identifiers, numeric values, and evidence provenance independent of language. Changing a translation must not change analysis results or entity matching.
- Preserve the existing error shape `{ code, message }`. `message` is a diagnostic, not a client localization key. Clients translate known codes and use a local generic message for unknown codes; they must not parse or display arbitrary upstream messages as UI copy.
- Expose variable error details through documented structured fields or existing headers such as `Retry-After`. Any new fields must be additive.
- Assemble analysis as structured facts, reason codes, and narrative identifiers with parameters. Render prose in the presentation layer, including portraits and share images. Translation keys remain private to each client.
- Keep history checkpoints and analysis caches language-neutral. Cache localized resources separately by effective locale and publication revision.

Structured reports use `profile-analysis-v3`. The reference retains its v2 response contract through a separate legacy serializer; existing fields keep their meanings.

## Locale resolution

Use canonical BCP 47 tags and an explicit supported-locale registry per application. Resolve the public web locale in this order: supported `lang` URL parameter, saved preference, browser preferences, then `pt-BR`. Match exact tags first, then an explicitly configured language fallback; do not infer a region arbitrarily.

Load UI dictionaries on demand, with the default available at startup. Use complete messages with named parameters and locale-aware plural rules. Centralize number, percentage, date, and language-name formatting through `Intl`. Update document language, text direction, accessibility copy, and exported images when the locale changes.

Changing UI language must not recollect listening history or recalculate analysis. A localized catalog resource may be fetched again.

## Editorial resources and fallback

The catalog supports `GET /v2/instruments/{slug}?locale=en-US`. Omitted locale preserves the current Portuguese response. Explicit unsupported locales fall back to `pt-BR`; malformed tags use the API's validation error contract. OpenAPI documents the parameter and locale metadata.

Separate neutral entities from translations keyed by entity/block ID and locale. Serve one publishable language version per resource. If the requested translation is unavailable, return the publishable `pt-BR` version and expose the effective locale in response metadata and `Content-Language`. If neither version is publishable, preserve existing resource availability rules. Do not silently mix translated fields from different languages.

Include the resolved locale in localized response cache identity. Any cache serving an explicit locale must distinguish it from the default response. Evidence and hydration endpoints remain language-neutral and do not require locale negotiation.

Translations retain citations, source IDs, provenance, and original bibliographic metadata. Source language is distinct from translation language. Review each translation independently under the existing [editorial policy](editorial-policy.md); approval of the original does not approve its translation. Record the source revision used by each translation. A changed source marks affected translations stale and excludes them from publication until reviewed again. Content publication remains governed by the [editorial workflow](editorial-publishing.md).

## Delivery and acceptance

1. Record ownership and contracts (complete).
2. Extract current Portuguese UI copy without changing behavior (complete).
3. Separate analysis data from rendered narratives, including cache and reference compatibility (complete).
4. Add editorial translation storage, review, publication, and API support (complete).
5. Add `en-US`, locale selection, accessible copy, and localized exports (implemented; browser validation pending).

Later implementation must verify:

- The API builds without importing either application's UI locales.
- API clients can operate without web assets or localization packages.
- Locale changes preserve analytical values and do not repeat evidence collection.
- Unknown error codes use translated generic UI copy.
- Missing or stale editorial translations produce a declared, coherent fallback.
- Locale keys and parameters validate; only publishable translations are served.
- Existing endpoint defaults and consumers remain compatible.

## Current implementation

Public and editorial UI dictionaries independently support `pt-BR` and `en-US`, split by responsibility under `src/i18n/locales/{locale}/`. Portuguese is available at startup; English loads on demand. Resolve locale from `?lang=`, the application-specific saved preference, browser languages, then `pt-BR`. Explicit language fallbacks map `en` to `en-US` and `pt` to `pt-BR`. Both headers expose a language selector.

Each JSON file owns distinct top-level namespaces and uses nested objects. Nesting preserves existing full keys: `entry.profileLabel` resolves to `entry` → `profileLabel`. Web domains are common, entry, analysis, narratives, instruments, sharing, errors, and metadata. Editorial domains are common, catalog, sheet, sources, review, images, and translations. Key renaming and copy cleanup are deferred.

Run `yarn locales:format` to apply natural key ordering and two-space indentation. After adding files or changing keys or `{parameters}`, run `yarn locales:generate`. Commit the generated import catalogs and parameter `.d.ts` files; neither duplicates message text. `yarn locales:check` rejects duplicate keys, namespace conflicts, malformed placeholders, unordered JSON, stale artifacts, and differences in locale keys, parameters, or component-owned wrappers. CI and application type checks enforce these rules. Development commands generate artifacts at startup.

Use semantic keys and named parameters with `t`. Public `Message.svelte` supports named wrappers for component-owned markup without rendering HTML. Date, number, percentage, and wait-duration formatting is centralized in `web/src/i18n/formatters.ts`.

Use `<upper>Sentence case</upper>` for uppercase presentation. Both runtimes apply locale-aware casing in `t`; public `Message.svelte` also handles it without a snippet. Only text inside the tag changes case; keep names and dates outside when their casing must be preserved. Tags must be balanced and cannot nest. Parameter values are never parsed as tags.

Report calculation and history collection do not import UI locales. `web/src/analysis/presentation.ts` renders structured narratives for screens and share images. Unknown API errors use local generic copy. The Python reference calculates the same neutral contract and isolates frozen v2 prose in `legacy_presentation.py`. See [report compatibility](api-contract.md#structured-reports-and-compatibility).

Editorial resources use schema-v2 snapshots: neutral entities and bibliographic sources are separate from locale files. Each translation has independent review metadata and a source-content SHA-256 revision; changed source content makes it stale. Publication persists resource and block translations plus revision history. The Worker serves a complete eligible translation or the complete Portuguese fallback, with locale and publication metadata. Legacy taxonomy text columns remain compatibility projections for evidence consumers and the Python reference. The development-only ASCII workspace remains outside UI extraction, but its report fixtures use the structured contract.

Language changes update subscribed UI text, document language, public metadata, formatters, and report presentation in place. They do not repeat listening-history collection or analysis. Public HTML retains Portuguese build-time metadata for clients that do not execute JavaScript. A failed initial English bundle load falls back to Portuguese; a failed manual change keeps the current locale.

Instrument requests include the selected content locale. Resource caches include locale and expire after five minutes. Report display names are resolved from localized catalog resources, with bounded concurrency and cancellation; neutral report and evidence caches remain unchanged. Changing language clears an existing share preview, so exported images use the current language. The ASCII development workspace remains Portuguese.

The 23 English editorial resources are reviewed as translations by `Codex (translation review)`, with their source revisions recorded. Original bibliographic metadata, citations, and image rights remain unchanged. Publish the editorial snapshot to make these resources available through the API; before publication, the existing Portuguese fallback still applies. Browser validation is performed separately by the maintainer.
