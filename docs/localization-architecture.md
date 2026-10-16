# Localization architecture

Status: accepted; phase 2 implemented. API and editorial publication behavior remain unchanged.

## Ownership and dependency boundaries

| Owner | Localized content | Planned location |
| --- | --- | --- |
| Public web app | UI, accessibility, validation, report narratives, share images | `web/src/i18n/` |
| Editorial app | Editor UI and validation messages | `editorial/src/i18n/` |
| API | Technical diagnostics; English initially | `workers/api/src/errors/` |
| Editorial publication | Instrument and family names, descriptions, roles, blocks, image captions and alt text | `editorial/content/` with locale-specific data |

Each application owns its locale registry, fallback policy, and release schedule. There is no root locale bundle. The API and hydrator must not import either application's UI dictionaries or localization runtime. Shared contracts may contain neutral identifiers and schemas, never UI translations. API consumers need no web dependencies or translation downloads.

Editorial content is API resource data, not a web dictionary. The editorial app's UI language is independent of the language being edited. Moving the current `editorial/src/instruments.json` source requires a later publication migration.

## Stable contracts

- Keep error codes, slugs, enums, identifiers, numeric values, and evidence provenance independent of language. Changing a translation must not change analysis results or entity matching.
- Preserve the existing error shape `{ code, message }`. `message` is a diagnostic, not a client localization key. Clients translate known codes and use a local generic message for unknown codes; they must not parse or display arbitrary upstream messages as UI copy.
- Expose variable error details through documented structured fields or existing headers such as `Retry-After`. Any new fields must be additive.
- Assemble analysis as structured facts, reason codes, and narrative identifiers with parameters. Render prose in the presentation layer, including portraits and share images. Translation keys remain private to each client.
- Keep history checkpoints and analysis caches language-neutral. Cache localized resources separately by effective locale and publication revision.

The current browser report and Python reference still contain rendered strings. Migrating them requires explicit schema/cache compatibility handling; existing fields must not silently change meaning.

## Locale resolution

Use canonical BCP 47 tags and an explicit supported-locale registry per application. Resolve the public web locale in this order: supported `lang` URL parameter, saved preference, browser preferences, then `pt-BR`. Match exact tags first, then an explicitly configured language fallback; do not infer a region arbitrarily.

Load UI dictionaries on demand, with the default available at startup. Use complete messages with named parameters and locale-aware plural rules. Centralize number, percentage, date, and language-name formatting through `Intl`. Update document language, text direction, accessibility copy, and exported images when the locale changes.

Changing UI language must not recollect listening history or recalculate analysis. A localized catalog resource may be fetched again.

## Editorial resources and fallback

The planned catalog extension is `GET /v2/instruments/{slug}?locale=en`; it is not available yet. Omitted locale preserves the current Portuguese response. Explicit unsupported locales fall back to `pt-BR`; malformed tags use the API's validation error contract. Document the extension in OpenAPI when implemented.

Separate neutral entities from translations keyed by entity/block ID and locale. Serve one publishable language version per resource. If the requested translation is unavailable, return the publishable `pt-BR` version and expose the effective locale in response metadata and `Content-Language`. If neither version is publishable, preserve existing resource availability rules. Do not silently mix translated fields from different languages.

Include the resolved locale in localized response cache identity. Any cache serving an explicit locale must distinguish it from the default response. Evidence and hydration endpoints remain language-neutral and do not require locale negotiation.

Translations retain citations, source IDs, provenance, and original bibliographic metadata. Source language is distinct from translation language. Review each translation independently under the existing [editorial policy](editorial-policy.md); approval of the original does not approve its translation. Record the source revision used by each translation. A changed source marks affected translations stale and excludes them from publication until reviewed again. Content publication remains governed by the [editorial workflow](editorial-publishing.md).

## Delivery and acceptance

1. Record ownership and contracts (complete).
2. Extract current Portuguese UI copy without changing behavior (complete).
3. Separate analysis data from rendered narratives, including cache and reference compatibility.
4. Add editorial translation storage, review, publication, and API support.
5. Add another language and validate UI, accessibility, and exported images.

Later implementation must verify:

- The API builds without importing either application's UI locales.
- API clients can operate without web assets or localization packages.
- Locale changes preserve analytical values and do not repeat evidence collection.
- Unknown error codes use translated generic UI copy.
- Missing or stale editorial translations produce a declared, coherent fallback.
- Locale keys and parameters validate; only publishable translations are served.
- Existing endpoint defaults and consumers remain compatible.

## Current implementation

Public and editorial UI messages live in separate `src/i18n/locales/pt-BR.ts` catalogs. Their runtimes support only `pt-BR`; language selection and additional dictionaries are deferred. Public HTML metadata is resolved from its catalog during Vite development and builds.

Use semantic keys and named parameters with `t`. Public `Message.svelte` supports named wrappers for component-owned markup without rendering HTML. Date, number, percentage, and wait-duration formatting is centralized in `web/src/i18n/formatters.ts`.

Rendered analysis narratives, the Python reference, and report/cache compatibility remain phase 3 work. Editorial resource translations remain phase 4 work. The development-only ASCII workspace is outside this UI extraction. Existing unknown-error fallback behavior is preserved until the error-contract migration.
