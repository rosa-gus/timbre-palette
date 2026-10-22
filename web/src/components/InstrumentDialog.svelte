<script lang="ts">
  import { formatDate, formatLanguage } from "../i18n/formatters";
  import { translation as t, localeStore } from "../i18n/runtime";
  import { onDestroy } from "svelte";
  import { Dialog } from "bits-ui";
  import { localizedInstrument as getInstrument } from "../i18n/resources";
  import type { InstrumentResource } from "../api/types";
  import ScrollArea from "./ScrollArea.svelte";
  import Arrow from "./Arrow.svelte";
  import Badge from "./Badge.svelte";
  import ColorSwatch from "./ColorSwatch.svelte";
  import Dropdown from "./Dropdown.svelte";

  export let resource: InstrumentResource | null = null;
  export let open = false;
  export let loading = false;
  export let error = "";
  export let onClose: () => void = () => undefined;
  export let onOpenRelated: (slug: string) => void = () => undefined;

  let familyName = "";
  let related: InstrumentResource[] = [];
  let relationsLoading = false;
  let relationsError = "";
  let contextResource: InstrumentResource | null = null;
  let relationsController: AbortController | null = null;
  function imageCaption(value: string): string {
    return value
      .replace(/^Imagem ilustrativa da família [^:]+:\s*/i, "")
      .replace(/^Imagem do instrumento\s*/i, "")
      .trim();
  }
  let statusLabels: Record<string, string>;
  $: statusLabels = {
    sourced: $t("editorialStatus.sourced"),
    reviewed: $t("editorialStatus.reviewed"),
    published: $t("editorialStatus.published"),
  };
  let sourceTypeLabels: Record<string, string>;
  $: sourceTypeLabels = {
    book: $t("sourceTypes.book"),
    article: $t("sourceTypes.article"),
    website: $t("sourceTypes.website"),
    web: $t("sourceTypes.website"),
    journal: $t("sourceTypes.journal"),
    encyclopedia: $t("sourceTypes.encyclopedia"),
    institution: $t("sourceTypes.institution"),
  };

  $: sections =
    resource?.sections.filter(
      (section) =>
        section.status !== "draft" && section.status !== "deprecated",
    ) ?? [];
  $: if (open && !loading && resource && resource !== contextResource)
    void loadRelations(resource);
  $: if (!open) {
    relationsController?.abort();
    contextResource = null;
  }

  $: date = (value: string | null): string => {
    if (!value) return "";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
      ? value
      : formatDate(parsed, $localeStore);
  };
  $: language = (value: string) => formatLanguage(value, $localeStore);
  function sourceId(id: string): string {
    return `instrument-source-${encodeURIComponent(resource?.slug ?? "")}-${encodeURIComponent(id)}`;
  }
  function sourceNumber(id: string): number {
    return (
      (resource?.sources.findIndex((source) => source.id === id) ?? -1) + 1
    );
  }
  function sourceMetaParts(
    source: InstrumentResource["sources"][number],
  ): string[] {
    return [
      source.contributors.join(", "),
      source.publisher,
      source.publication_date,
    ].filter((part): part is string => Boolean(part));
  }
  type Rgb = [number, number, number];
  function parseHex(value: string): Rgb {
    const normalized = value.replace(/^#/, "");
    return [
      Number.parseInt(normalized.slice(0, 2), 16),
      Number.parseInt(normalized.slice(2, 4), 16),
      Number.parseInt(normalized.slice(4, 6), 16),
    ];
  }
  function mix(first: Rgb, second: Rgb, amount: number): Rgb {
    return first.map((value, index) =>
      Math.round(value + (second[index] - value) * amount),
    ) as Rgb;
  }
  function hex(rgb: Rgb): string {
    return `#${rgb
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase()}`;
  }
  function toneSwatches(value: string): string[] {
    const base = parseHex(value);
    return [
      hex(mix(base, [0, 0, 0], 0.15)),
      hex(base),
      hex(mix(base, [255, 255, 255], 0.1)),
      hex(mix(base, [255, 255, 255], 0.2)),
    ];
  }
  function toneText(value: string): string {
    return hex(mix(parseHex(value), [0, 0, 0], 0.6));
  }
  async function loadRelations(current: InstrumentResource): Promise<void> {
    relationsController?.abort();
    const controller = new AbortController();
    relationsController = controller;
    contextResource = current;
    familyName = "";
    related = [];
    relationsError = "";
    const language = $localeStore;
    const slugs = [
      ...new Set(
        [current.family_slug, ...current.related_slugs].filter(
          (slug): slug is string => !!slug && slug !== current.slug,
        ),
      ),
    ];
    relationsLoading = slugs.length > 0;
    const results = await Promise.allSettled(
      slugs.map(async (slug) => {
        return getInstrument(slug, controller.signal, language);
      }),
    );
    if (controller.signal.aborted) return;
    const items = results.flatMap((result) =>
      result.status === "fulfilled" ? [result.value] : [],
    );
    familyName =
      items.find((item) => item.slug === current.family_slug)?.name ?? "";
    related = items.filter((item) => current.related_slugs.includes(item.slug));
    relationsError = results.some(
      (result, index) =>
        result.status === "rejected" &&
        current.related_slugs.includes(slugs[index]),
    )
      ? $t("instrument.relatedUnavailable")
      : "";
    relationsLoading = false;
  }
  onDestroy(() => relationsController?.abort());
</script>

<Dialog.Root
  {open}
  onOpenChange={(value) => {
    open = value;
    if (!value) onClose();
  }}
>
  <Dialog.Portal>
    <Dialog.Overlay
      class="ui-dialog-overlay"
      style={`--instrument-tone:${resource?.tone?.highlight ?? "var(--accent)"}`}
    />
    <Dialog.Content lang={$localeStore}
      class="ui-dialog-content"
      style={`--instrument-tone:${resource?.tone?.highlight ?? "#F29191"};--instrument-tone-text:${toneText(resource?.tone?.highlight ?? "#F29191")};--instrument-shadow:${resource?.tone?.shadow ?? "#100e0e"}`}
    >
      <div class="ui-dialog-header">
        <div>
          <div class="ui-dialog-kind">
            <Badge>
              {!loading && resource?.kind === "family"
                ? $t("instrument.familyBadge")
                : $t("instrument.instrumentBadge")}
            </Badge>
          </div>
          <Dialog.Title lang={!loading && !error ? resource?.locale : $localeStore} class="ui-dialog-title"
            >{loading || error
              ? $t("instrument.title")
              : (resource?.name ?? $t("instrument.title"))}</Dialog.Title
          >
          {#if !loading && !error && familyName}<p class="instrument-family">
              {familyName}
            </p>{/if}
        </div>
        <Dialog.Close class="ui-dialog-close" aria-label={$t("instrument.close")}
          >×</Dialog.Close
        >
      </div>
      <Dialog.Description class="visually-hidden"
        >{$t("instrument.description")}</Dialog.Description
      >
      {#key resource?.slug}
        <ScrollArea>
          {#if loading}
            <p class="instrument-message instrument-loading" role="status">
              <span class="loading-indicator" aria-hidden="true"></span>
              <span>{$t("instrument.loading")}</span>
            </p>
          {:else if error}
            <p class="instrument-message" role="alert">{error}</p>
          {:else if resource}
            <div class="instrument-sheet" data-instrument={resource.slug}>
              <aside
                class="instrument-visual"
                aria-label={$t("instrument.imageCatalogLabel")}
              >
                <figure class="instrument-photo">
                  {#if resource.image?.variants.length}
                    <img
                      src={resource.image.variants[0].url}
                      lang={resource.locale}
                      alt={resource.image.alt}
                      width={resource.image.variants[0].width}
                      height={resource.image.variants[0].height}
                    />
                  {:else}<div class="instrument-image-empty">
                      <span>{resource.name}</span><small
                        >{$t("instrument.imageUnavailable")}</small
                      >
                    </div>{/if}
                  <div
                    class="instrument-tones"
                    aria-label={$t("colors.variations", { name: resource.name })}
                  >
                    {#each toneSwatches(resource.tone?.highlight ?? "#F29191") as swatch}<ColorSwatch
                        color={swatch}
                        label={$t("colors.variation", { name: resource.name })}
                      />{/each}
                  </div>
                  {#if resource.image?.variants.length}
                    <figcaption class="instrument-photo-credit">
                      {#if resource.image.resolution === "exact"}<span
                          >{$t("images.photoCaption", { caption: imageCaption(resource.image.caption) })}</span
                        >{/if}
                      {#if resource.image.credit.photographer_url}<a
                          href={resource.image.credit.photographer_url}
                          target="_blank"
                          rel="noreferrer"
                          >{resource.image.credit.photographer ??
                            $t("images.viewCredit")}<Arrow
                            direction="up-right"
                          /></a
                        >{:else if resource.image.credit.photographer}<span
                          >{resource.image.credit.photographer}</span
                        >{/if}
                    </figcaption>
                  {/if}
                </figure>
                {#if resource.image && resource.image.resolution !== "exact"}<p
                    class="instrument-image-note"
                  >
                    {resource.image.caption}
                  </p>{/if}
              </aside>
              <div class="instrument-reading">
                <p lang={resource.locale} class="instrument-description">{resource.description}</p>
                <section class="instrument-block" aria-label={$t("instrument.soundProductionLabel")}>
                  <h3 class="eyebrow">{$t("instrument.soundProductionHeading")}</h3>
                  <p lang={resource.locale}>{resource.sound_production}</p>
                </section>
                {#if resource.common_roles.length}<section
                    class="instrument-block"
                    aria-label={$t("instrument.rolesLabel")}
                  >
                    <h3 class="eyebrow">{$t("instrument.rolesHeading")}</h3>
                    <ul class="instrument-roles">
                      {#each resource.common_roles as role}<li lang={resource.locale}>
                          {role}
                        </li>{/each}
                    </ul>
                  </section>{/if}
                {#each sections as section}
                  <section
                    class="instrument-block"
                    aria-label={$t("instrument.curiosityLabel")}
                  >
                    <h3 class="eyebrow">{$t("instrument.curiosityHeading")}</h3>
                    <p lang={resource.locale}>
                      {section.text}
                      {#each section.citations as citation}{#if sourceNumber(citation.source_id)}<a
                            class="instrument-citation"
                            href={`#${sourceId(citation.source_id)}`}
                            aria-label={$t("instrument.referenceLabel", { number: sourceNumber(citation.source_id) })}
                            >[{sourceNumber(citation.source_id)}]</a
                          >{:else}<span class="instrument-review-note"
                            >{$t("instrument.referenceUnavailable")}</span
                          >{/if}{/each}
                    </p>
                    {#if !section.review.claim_support_verified}<p
                        class="instrument-review-note"
                      >{$t("instrument.claimReviewPending")} </p>{/if}
                    <Dropdown title={$t("instrument.sectionDetails")}>
                      <div class="instrument-details">
                        <dl>
                          <div>
                            <dt>{$t("instrument.contentLabel")}</dt>
                            <dd>
                              {section.content_type === "fact"
                                ? $t("instrument.fact")
                                : $t("instrument.summary")}
                            </dd>
                          </div>
                          <div>
                            <dt>{$t("instrument.statusLabel")}</dt>
                            <dd>
                              {statusLabels[section.status] ?? section.status}
                            </dd>
                          </div>
                          <div>
                            <dt>{$t("instrument.bibliographyLabel")}</dt>
                            <dd>
                              {section.review.source_metadata_verified
                                ? $t("instrument.verified")
                                : $t("instrument.verificationPending")}
                            </dd>
                          </div>
                          <div>
                            <dt>{$t("instrument.claimSupportLabel")}</dt>
                            <dd>
                              {section.review.claim_support_verified
                                ? $t("editorialStatus.reviewed")
                                : $t("instrument.reviewPending")}
                            </dd>
                          </div>
                          {#if section.review.reviewed_at}<div>
                              <dt>{$t("instrument.reviewLabel")}</dt>
                              <dd>
                                {date(
                                  section.review.reviewed_at,
                                )}{#if section.review.reviewer}<span
                                    class="inline-divider"
                                    aria-hidden="true"></span
                                  >{section.review.reviewer}{/if}
                              </dd>
                            </div>{/if}
                        </dl>
                        {#if section.review.editorial_note}<p>
                            {section.review.editorial_note}
                          </p>{/if}{#each section.citations as citation}{#if citation.locator || citation.note}<p
                            >
                              <strong
                                >{$t("instrument.referencePrefix", { number: sourceNumber(citation.source_id) ||
                                  $t("instrument.referenceMissing") })}</strong
                              >
                              {citation.locator ?? ""}{#if citation.note && $localeStore === "pt-BR"}<span
                                  class="inline-divider"
                                  aria-hidden="true"></span
                                >{citation.note}{/if}
                            </p>{/if}{/each}
                      </div>
                    </Dropdown>
                  </section>
                {/each}
                {#if resource.related_slugs.length}<section
                    class="instrument-block"
                    aria-label={$t("instrument.relatedLabel")}
                  >
                    <h3 class="eyebrow">{$t("instrument.relatedHeading")}</h3>
                    <div class="instrument-related">
                      {#each related as item}<button
                          type="button"
                          on:click={() => onOpenRelated(item.slug)}
                          >{item.name}</button
                        >{/each}
                    </div>
                    {#if relationsLoading}<p
                        class="instrument-review-note instrument-loading-note"
                        role="status"
                      >
                        <span class="loading-indicator" aria-hidden="true"
                        ></span>
                        <span>{$t("instrument.loadingRelated")}</span>
                      </p>{/if}{#if relationsError}<p
                        class="instrument-review-note"
                        role="status"
                      >
                        {relationsError}
                      </p>{/if}
                  </section>{/if}
                {#if resource.further_reading?.length}
                  <section class="instrument-block" aria-label={$t("instrument.readingLabel")}>
                    <h3 class="eyebrow">{$t("instrument.readingHeading")}</h3>
                    <ul>
                      {#each resource.further_reading as article}
                        <li>
                          <a
                            href={article.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            >{article.title} <Arrow direction="up-right" /></a
                          >{#if article.publisher}<p>
                              {article.publisher}
                            </p>{/if}
                        </li>
                      {/each}
                    </ul>
                  </section>
                {/if}
                {#if resource.sources.length}<section
                    class="instrument-block"
                    aria-label={$t("instrument.sourcesLabel")}
                  >
                    <h3 class="eyebrow">{$t("instrument.sourcesHeading")}</h3>
                    <ol class="instrument-sources">
                      {#each resource.sources as source, index}<li
                          id={sourceId(source.id)}
                        >
                          <span class="instrument-source-number"
                            >[{index + 1}]</span
                          >
                          <div>
                            {#if source.url}<a
                                class="instrument-source-title"
                                href={source.url}
                                target="_blank"
                                rel="noreferrer"
                                >{source.title}
                                <Arrow direction="up-right" /></a
                              >{:else}<span class="instrument-source-title"
                                >{source.title}</span
                              >{/if}
                            <p class="instrument-source-meta">
                              {#each sourceMetaParts(source) as part, index}{#if index > 0}<span
                                    class="inline-divider"
                                    aria-hidden="true"></span
                                  >{/if}{part}{/each}
                            </p>
                            <Dropdown title={$t("instrument.sourceDetails")}>
                              <div class="instrument-details">
                                <dl>
                                  <div>
                                    <dt>{$t("instrument.sourceTypeLabel")}</dt>
                                    <dd>
                                      {sourceTypeLabels[source.source_type] ??
                                        source.source_type}
                                    </dd>
                                  </div>
                                  <div>
                                    <dt>{$t("instrument.languageLabel")}</dt>
                                    <dd>{language(source.language)}</dd>
                                  </div>
                                  <div>
                                    <dt>{$t("instrument.metadataLabel")}</dt>
                                    <dd>
                                      {source.metadata_verified
                                        ? $t("instrument.verified")
                                        : $t("instrument.verificationPending")}
                                    </dd>
                                  </div>
                                  {#if source.locator}<div>
                                      <dt>{$t("instrument.locatorLabel")}</dt>
                                      <dd>{source.locator}</dd>
                                    </div>{/if}{#if source.license}<div>
                                      <dt>{$t("instrument.licenseLabel")}</dt>
                                      <dd>{source.license}</dd>
                                    </div>{/if}{#if source.accessed_at}<div>
                                      <dt>{$t("instrument.accessedLabel")}</dt>
                                      <dd>{date(source.accessed_at)}</dd>
                                    </div>{/if}{#if source.verified_at}<div>
                                      <dt>{$t("instrument.verifiedLabel")}</dt>
                                      <dd>{date(source.verified_at)}</dd>
                                    </div>{/if}
                                </dl>
                                {#if source.note}<p>{source.note}</p>{/if}
                              </div>
                            </Dropdown>
                          </div>
                        </li>{/each}
                    </ol>
                  </section>{/if}
                <Dropdown title={$t("instrument.resourceDetails")}>
                  <div class="instrument-details instrument-about">
                    <dl>
                      <div>
                        <dt>{$t("instrument.provenanceLabel")}</dt>
                        <dd>
                          {resource.data_source === "mock"
                            ? $t("instrument.demoData")
                            : $t("instrument.catalogData")}
                        </dd>
                      </div>
                      <div>
                        <dt>{$t("instrument.catalogLabel")}</dt>
                        <dd><code class="source-value">{resource.catalog_version}</code></dd>
                      </div>
                      <div>
                        <dt>{$t("instrument.imageCatalogLabel")}</dt>
                        <dd><code class="source-value">{resource.image_catalog_version}</code></dd>
                      </div>
                    </dl>
                  </div>
                </Dropdown>
              </div>
            </div>
          {/if}
        </ScrollArea>
      {/key}
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
