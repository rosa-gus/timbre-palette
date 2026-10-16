# Translation policy

## Translation coverage

<!-- translation-coverage:start -->

| Locale | Web UI | Editorial UI | Reviewed editorial content |
| --- | ---: | ---: | ---: |
| en-US | 100% (406/406) | 100% (109/109) | 100% (23/23) |
| pt-BR | 100% (406/406) | 100% (109/109) | 100% (23/23) |

<!-- translation-coverage:end -->

UI coverage counts each locale's own messages against its application's English catalog; fallback text does not count. Editorial coverage counts current, independently approved resources against publishable Portuguese sources, excluding withdrawn sources. Counts describe the committed snapshot, not a deployed publication; coverage does not certify linguistic quality or replace review. A dash means the locale is unavailable in that area or no source is publishable.

Run `yarn locales:generate` to update this table after UI or editorial changes. `yarn locales:check` rejects stale coverage in CI. Do not edit the generated table manually. These commands require Node.js and Python 3 (standard library only).

## Ownership

Each frontend owns its UI catalogs and locale preference. The API and hydrator must not import frontend dictionaries or runtimes. Editorial translations are published resource data, separate from UI copy. The editorial UI language does not select the language being edited.

Keep identifiers, error codes, evidence, analytical values, and history caches independent of language. Translate known error codes locally; use a generic local message for unknown codes. Never derive UI copy by parsing API diagnostics.

## UI language and fallback

Support canonical `pt-BR` and `en-US`. Resolve the UI language from the supported `lang` query parameter, saved application preference, browser preferences, then `en-US`. Map `pt` to `pt-BR` and `en` to `en-US`; do not infer other regional mappings.

English is the complete, startup-available fallback catalog and defines message keys and parameters. Other catalogs may omit messages. Resolve each complete message in the selected language, then in English; never discard available translations because another key is missing. Runtime lookup treats blank messages as missing, but committed blank messages are invalid: omit untranslated keys instead. A missing English message is an error.

Fallback does not change the selected locale, preference, or number/date formatting. Preserve parameters and component-owned wrappers across translations. Do not construct sentences by concatenating translated fragments.

For quantities, use cardinal plural messages, for example `{count, plural, =0 {# tracks} one {# track} other {# tracks}}`. Pass raw finite numbers; `#` uses the selected UI's number formatting. Categories follow `Intl.PluralRules` for the message's own language, including English fallback. Always provide `other`; exact counts and nested plurals are supported. Keep component-owned wrappers consistent across all forms. These rules support cardinal plurals and named parameters, not arbitrary ICU formatters.

Use nested JSON objects, one owner file per top-level namespace, semantic keys, and named parameters. Keep markup flat and balanced: `<upper>`, `<emphasis>`, `<line>`, `<value>`, and `<version>`. `<upper>` applies locale-aware casing; keep names outside it when their casing must be preserved. Parameter values are text and must never be interpreted as markup or HTML.

Run `yarn locales:format`, `yarn locales:generate`, and `yarn locales:check` after catalog changes. Commit generated imports and parameter types. Validation rejects unknown keys, empty messages, invalid markup, and incompatible parameters or wrappers. Missing non-English keys use the English fallback.

## Editorial content and review

`pt-BR` is the editorial source language. Translate by stable resource and block IDs. Preserve claims, qualifications, citations, provenance, original bibliographic titles, and image rights. Do not introduce factual claims through translation.

Every translation requires its own review under the [editorial policy](editorial-policy.md). Original approval does not approve a translation. Record the reviewer, review date, and source revision; only reviewed or published content with valid approval is eligible. Draft, stale, and deprecated translations are unavailable to public readers. Source content changes require renewed translation review. Source revisions cover text, citations, bibliographic content, image identity and authored image text, classification, and publication eligibility. Catalog versions, colors, image URLs and attribution, reviewer names/dates/notes, and source access/verification dates do not invalidate a translation. Changes to approval flags or block status still affect eligibility and revision.

Revision schema 2 excludes that operational metadata. Existing legacy digests may be upgraded only when they match the exact current source under the old algorithm; never replace an unmatched digest or approve stale content automatically.

Preserve withdrawal status through editing, saving, export, and publication. An old approval must never turn deprecated source content into published content. A missing or unapproved source makes its translations unavailable, even when they retain approval. Deleted blocks and withdrawn claims must not return through a translation or fallback.

The API serves a complete eligible resource in the requested language, otherwise the complete eligible Portuguese source. Resource-level fallback preserves a coherent reviewed text; UI message fallback does not authorize mixing editorial fields. If the source is unavailable, return `404` without exposing compatibility text. Omitted locale remains `pt-BR`; malformed or repeated locale parameters return `422`.

Declare the effective resource language in `locale` and `Content-Language`, preserve `requested_locale`, and expose source, content, and publication revisions. Distinguish requested languages in cache identity. Follow the [publication workflow](editorial-publishing.md).

## Partial reports and exports

Changing UI language must not recollect listening history, recalculate analysis, or mutate the neutral report. Localize presentation fields separately, including discovery image subjects. Preserve each resource's effective language and mark standalone translated labels accordingly.

Resolve report resources with at most four concurrent requests and one total five-second deadline. Keep completed translations and declared editorial fallbacks. On failure or timeout, retain the original report labels, disclose partial localization, and cancel pending requests. Late responses must not change the consolidated presentation.

Allow translation retries without rerunning analysis; bypass cached fallbacks on an explicit retry. Cancel superseded presentation requests when the report or locale changes. Enable sharing after presentation settles and export that same consolidated report. Clear obsolete previews when the language changes or translations are retried.

Formatting and narrative helpers honor an explicit locale without changing UI selection. Their small catalogs are available synchronously in both languages; the remaining Portuguese UI copy loads on demand.

Update document language, metadata, accessibility copy, formatting, and share images with the selected UI locale. Review UI wording and editorial translations before merging; automated validation checks structure and contracts, not linguistic accuracy.
