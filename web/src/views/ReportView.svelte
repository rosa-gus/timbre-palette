<script lang="ts">
  import { formatPercent } from "../i18n/formatters";
  import Message from "../i18n/Message.svelte";
  import { translation as t, localeStore } from "../i18n/runtime";
  import Arrow from "../components/Arrow.svelte";
  import Badge from "../components/Badge.svelte";
  import Button from "../components/Button.svelte";
  import ColorSwatch from "../components/ColorSwatch.svelte";
  import Dropdown from "../components/Dropdown.svelte";
  import Tooltip from "../components/Tooltip.svelte";
  import {
    getPortraitCopy,
    getAnalysisNotice,
    getDiscoveryCopy,
    getImageCopy,
  } from "../analysis/presentation";
  import { createAsciiArtwork } from "../sharing/ascii";
  import FamilyPalette from "../components/FamilyPalette.svelte";
  import {
    fallbackTone,
    parseHex,
    mix,
    hex,
    toneText,
    type Rgb,
  } from "../sharing/palette-tones";
  import type {
    Confidence,
    PaletteReport,
    SectionAvailability,
  } from "../api/types";
  import type { FamilyPresence } from "../api/types";

  type SectionId = "portrait" | "palette" | "discovery" | "share";
  export let report: PaletteReport;
  export let isExample = false;
  export let hydrationPending = false;
  $: portrait = getPortraitCopy(report, $localeStore);
  $: discoveryCopy = report.discovery
    ? getDiscoveryCopy(report.discovery, $localeStore)
    : null;
  $: asciiArtwork = createAsciiArtwork(report.families);
  $: discoveryAvailable =
    !!report.discovery && getAvailability("discovery") === "available";
  export let periodLabels: Record<string, string>;
  export let confidenceLabels: Record<Confidence, string>;
  export let shareFeedback = "";
  export let onOpenInstrument: () => void = () => undefined;
  export let onOpenInstrumentSlug: (slug: string) => void = () => undefined;
  export let onGenerateShare: () => void = () => undefined;
  export let getAvailability: (
    section: SectionId,
  ) => SectionAvailability = () => "insufficient_coverage";

  $: percent = (value: number): string => formatPercent(value, 0, $localeStore);

  function toneSwatches(family: FamilyPresence): string[] {
    const base =
      parseHex(family.tone?.highlight ?? fallbackTone) ??
      parseHex(fallbackTone)!;
    const black: Rgb = [0, 0, 0];
    const white: Rgb = [255, 255, 255];
    return [
      hex(mix(base, black, 0.15)),
      hex(base),
      hex(mix(base, white, 0.1)),
      hex(mix(base, white, 0.2)),
    ];
  }

  export let sharePreviewUrl = "";
  export let shareBusy = false;
  export let canShareImage = false;
  export let onDownloadShare: () => void = () => undefined;
  export let onShareImage: () => void = () => undefined;
  const natureLabels: Record<string, string> = {
    acoustic: $t("nature.acoustic"),
    electric: $t("nature.electric"),
    electronic: $t("nature.electronic"),
    sampled: $t("nature.sampled"),
    hybrid: $t("nature.hybrid"),
    unknown: $t("nature.unknown"),
  };
</script>

{#snippet sourceValue(text: string)}<span class="source-value">{text}</span
  >{/snippet}
{#snippet nextLine(text: string)}<br />{text}{/snippet}

<section
  class="report-view"
  aria-labelledby="report-title"
  style={`--report-tone:${report.families[0]?.tone?.highlight ?? fallbackTone};--report-tone-text:${toneText(report.families[0]?.tone?.highlight ?? fallbackTone)}`}
>
  <section id="portrait" class="portrait" aria-labelledby="report-title">
    <div class="portrait-copy">
      <p class="eyebrow">{$t("report.portraitHeading")}</p>
      <h2 class="portrait-title" id="report-title">{portrait.title}</h2>
      <p class="large-copy">
        {portrait.summary}
      </p>
      <p class="portrait-scope">{$t("report.portraitScope")}</p>
      <div class="portrait-caption">
        <span
          >{$t("report.trackCount", {
            tracks_analyzed: report.profile.tracks_analyzed,
          })}</span
        ><span
          >{$t("report.playCount", {
            total_plays: report.profile.total_plays,
          })}</span
        ><span
          >{$t("report.trackCoverage", {
            coverage: percent(report.analysis.coverage_tracks),
          })}
          <Tooltip ariaLabel={$t("report.coverageTitle")} triggerLabel="[i]">
            <p>{$t("report.coverageDescription")}</p>
            <p>{$t("report.excludedTracks")}</p>
            {#if hydrationPending}<p class="tooltip-note">
                <span class="loading-indicator" aria-hidden="true"></span>
                <span>{$t("report.hydrationNotice")}</span>
              </p>{/if}
          </Tooltip>
        </span>
      </div>
      {#if portrait.disclaimer}<p class="disclaimer">
          {portrait.disclaimer}
        </p>{/if}
    </div>
    <div class="composition" aria-label={$t("report.compositionLabel")}>
      {#each report.families as family}<ColorSwatch
          color={family.tone?.highlight ?? fallbackTone}
          label={`${family.name} (${percent(family.share)})`}
          presenceName={family.name}
          className="composition-swatch"
          style={`flex-grow:${family.share};`}
        />{/each}
    </div>
    <p class="color-hint">{$t("report.copyHint")}</p>
    <div class="instrument-grid">
      {#each report.families.slice(0, 3) as family, index}
        <figure
          class="instrument-card"
          style={`--family-tone:${family.tone?.highlight ?? fallbackTone};--family-tone-text:${toneText(family.tone?.highlight ?? fallbackTone)}`}
        >
          <figcaption>
            <div class="instrument-heading">
              <span class="eyebrow"
                >{$t("report.dominantPresence", {
                  index: String(index + 1).padStart(2, "0"),
                })}</span
              >
              <button
                type="button"
                class="family-card-link"
                aria-label={$t("actions.openInstrument", { name: family.name })}
                on:click={() => onOpenInstrumentSlug(family.slug)}
                >{$t("actions.open")}</button
              >
            </div>
            <div class="instrument-name">
              <h2 lang={family.locale}>{family.name}</h2>
              <strong>{percent(family.share)}</strong>
            </div>
          </figcaption>
          {#if family.image?.variants.length}<div class="credited-image">
              <img
                src={family.image.variants[0].url}
                lang={family.image.alt ? family.image.locale : $localeStore}
                alt={getImageCopy(family.image, $localeStore).alt}
                width={family.image.variants[0].width}
                height={family.image.variants[0].height}
              />
            </div>{:else}<div class="image-placeholder">{family.name}</div>{/if}
          <div
            class="tone-strip"
            aria-label={$t("colors.variations", { name: family.name })}
          >
            {#each toneSwatches(family) as swatch}<ColorSwatch
                color={swatch}
                label={$t("colors.variation", { name: family.name })}
              />{/each}
          </div>
          {#if family.image?.variants.length}<p class="photo-caption">
              <span class="photo-caption-text"
                >{$t("images.photoLabel")} <span
                  class="inline-divider"
                  aria-hidden="true"
                ></span> {getImageCopy(family.image, $localeStore).label}</span
              >{#if family.image.credit.photographer_url}<a
                  href={family.image.credit.photographer_url}
                  target="_blank"
                  rel="noreferrer"
                  >{family.image.credit.photographer ??
                    $t("images.viewCredit")}<Arrow direction="up-right" /></a
                >{:else if family.image.credit.photographer}<span
                  >{family.image.credit.photographer}</span
                >{/if}
            </p>{/if}
        </figure>
      {/each}
    </div>
  </section>
  <section id="palette" class="archive-section" aria-labelledby="palette-title">
    <div class="section-heading">
      <p class="eyebrow">{$t("report.paletteHeading")}</p>
      <h2 id="palette-title">{$t("report.paletteTitle")}</h2>
      <p class="palette-scope">{$t("report.identifiedSources")}</p>
    </div>
    <div class="palette-layout">
      <FamilyPalette
        families={report.families}
        {confidenceLabels}
        {onOpenInstrumentSlug}
      />
      <aside>
        <p class="eyebrow">{$t("report.natureHeading")}</p>
        {#if report.sound_balance}<ul class="compact-list">
            {#each Object.entries(report.sound_balance)
              .filter(([, value]) => Math.round(value * 100) > 0)
              .sort(([, a], [, b]) => b - a) as [nature, value]}<li>
                <span>{natureLabels[nature] ?? nature}</span><strong
                  >{percent(value)}</strong
                >
              </li>{/each}
          </ul>{:else}<p>{$t("report.naturePending")}</p>{/if}
      </aside>
    </div>
    <div class="analysis-details">
      <Dropdown title={$t("report.dataTitle")}>
        <p>{getAnalysisNotice(report.analysis, $localeStore)}</p>
        <p>
          <Message
            message="report.coverage"
            values={{
              tracks: percent(report.analysis.coverage_tracks),
              plays: percent(report.analysis.coverage_plays),
            }}
            wrappers={{ value: sourceValue }}
          />
        </p>
        <p>
          <Message
            message="report.vocals"
            values={{
              tracks: report.analysis.vocal_presence.documented_tracks,
              artists: report.analysis.vocal_presence.documented_artists,
              plays: report.analysis.vocal_presence.documented_plays,
              ratio: percent(report.analysis.vocal_presence.play_ratio),
            }}
            wrappers={{ value: sourceValue }}
          />
        </p>
        <p>
          {$t("report.catalogLabel")}
          {#if report.analysis.catalog_version}<code class="source-value"
              >{report.analysis.catalog_version}</code
            >{:else}{$t("report.unpublished")}{/if}
          <span class="inline-divider" aria-hidden="true"></span>{$t(
            "report.methodLabel",
          )}
          <code class="source-value">{report.analysis.methodology_version}</code
          >
        </p>
      </Dropdown>
    </div>
  </section>
  <section
    id="discovery"
    class="archive-section"
    class:unavailable-section={!discoveryAvailable}
    aria-labelledby="discovery-title"
  >
    {#if discoveryAvailable && report.discovery}
      <div class="section-heading">
        <p class="eyebrow">{$t("report.discoveryHeading")}</p>
        <h2 id="discovery-title">{$t("report.discoveryTitle")}</h2>
      </div>
      <div class="discovery-layout">
        {#if report.discovery.image?.variants.length}<figure
            class="credited-image"
          >
            <img
              src={report.discovery.image.variants[0].url}
              lang={report.discovery.image.alt
                ? report.discovery.image.locale
                : $localeStore}
              alt={getImageCopy(report.discovery.image, $localeStore).alt}
              width={report.discovery.image.variants[0].width}
              height={report.discovery.image.variants[0].height}
              loading="lazy"
            />
            <figcaption class="photo-caption">
              <span class="photo-caption-text"
                >{$t("images.photoLabel")} <span
                  class="inline-divider"
                  aria-hidden="true"
                ></span> {getImageCopy(report.discovery.image, $localeStore)
                  .label}</span
              >{#if report.discovery.image.credit.photographer_url}
                <a
                  href={report.discovery.image.credit.photographer_url}
                  target="_blank"
                  rel="noreferrer"
                  >{report.discovery.image.credit.photographer ??
                    $t("images.viewCredit")}<Arrow direction="up-right" /></a
                >{:else if report.discovery.image.credit.photographer}<span
                  >{report.discovery.image.credit.photographer}</span
                >{/if}
            </figcaption>
          </figure>{/if}
        <div>
          <h3>{discoveryCopy?.title}</h3>
          <p class="large-copy">{discoveryCopy?.summary}</p>
          <Button variant="secondary" on:click={onOpenInstrument}
            >{$t("actions.exploreInstrument")}
            <Arrow direction="right" /></Button
          >
        </div>
      </div>
    {:else}
      <p class="eyebrow">{$t("report.discoveryHeading")}</p>
      <p id="discovery-title">{$t("report.noDiscovery")}</p>
    {/if}
  </section>
  <section
    id="share"
    class="archive-section share-section"
    aria-labelledby="share-title"
  >
    <div class="share-copy">
      <p class="eyebrow">
        04 / {isExample
          ? $t("sharing.exampleHeading")
          : $t("sharing.ownHeading")}
      </p>
      <h2 id="share-title">
        <Message
          message={isExample ? "sharing.exampleLead" : "sharing.ownLead"}
          wrappers={{ line: nextLine }}
        />
      </h2>
      <p class="large-copy">
        {isExample ? $t("sharing.exampleIntro") : $t("sharing.ownIntro")}
      </p>
      <Button variant="primary" disabled={shareBusy} on:click={onGenerateShare}
        >{sharePreviewUrl
          ? $t("sharing.update")
          : isExample
            ? $t("sharing.prepareExample")
            : $t("sharing.prepareOwn")}
        <Arrow direction="right" /></Button
      >{#if sharePreviewUrl}{#if canShareImage}<Button
            variant="secondary"
            on:click={onShareImage}>{$t("actions.share")}</Button
          >{/if}<Button variant="secondary" on:click={onDownloadShare}
          >{$t("sharing.download")}</Button
        >{/if}
      <p class="share-feedback" aria-live="polite">{shareFeedback}</p>
    </div>
    <div class="share-preview">
      {#if sharePreviewUrl}<img
          src={sharePreviewUrl}
          alt={$t("sharing.previewAlt", {
            listener: isExample
              ? report.profile.realname || $t("example.displayName")
              : report.profile.username,
          })}
        />{:else}<div class="share-card-preview">
          <span class="eyebrow"
            >{$t("sharing.previewIdentity", {
              listener: isExample
                ? report.profile.realname || $t("example.displayName")
                : `@${report.profile.username}`,
            })} <span class="inline-divider" aria-hidden="true"></span>
            {#if isExample}{$t("example.badge")}
              <span class="inline-divider" aria-hidden="true"></span>
            {/if}
            {periodLabels[report.profile.period]}</span
          ><strong>{portrait.title}</strong>
          <p class="preview-summary">{portrait.summary}</p>
          <div
            class="preview-specimens"
            style={`--specimen-count:${Math.max(1, asciiArtwork.length)}`}
          >
            {#each asciiArtwork as item, index}<div
                class="preview-specimen"
                style={`--specimen-tone:${item.color}`}
              >
                <div class="preview-ascii-drawing" aria-hidden="true">
                  <pre
                    style={`font-size:${Math.min(9, 100 / (item.columns * 0.6), 88 / (item.lines.length * 0.95))}cqw`}>{item.lines.join(
                      "\n",
                    )}</pre>
                </div>
                <span class="preview-index"
                  >{String(index + 1).padStart(2, "0")}</span
                >
                <span class="preview-family">{item.family.name}</span>
                <span class="preview-share">{percent(item.family.share)}</span>
              </div>{/each}
          </div>
          <span class="preview-note"
            >{$t("sharing.interpretation")}
            <span class="inline-divider" aria-hidden="true"></span> TIMBRE
            PALETTE</span
          >
        </div>{/if}
    </div>
  </section>
</section>

<style>
  .report-view {
    width: 100%;
    max-width: 1320px;
    margin: 0 auto;
    padding: 0 0 32px;
  }
  .portrait {
    padding-top: 40px;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 24px;
  }
  .portrait-title {
    max-width: 950px;
    margin: 12px 0 24px;
    font-size: clamp(2.5rem, 4vw, 4rem);
    line-height: 1.05;
  }
  h2 {
    font-size: clamp(1.6rem, 2.6vw, 2.5rem);
    line-height: 1.15;
    margin: 0;
  }
  h3 {
    font-size: 1.8rem;
    line-height: 1.2;
  }
  .large-copy {
    max-width: 760px;
    color: var(--muted);
    font-size: clamp(1rem, 1.4vw, 1.2rem);
    line-height: 1.65;
    margin: 0 0 24px;
  }
  .disclaimer {
    max-width: 760px;
    font-size: 13px;
    color: var(--muted);
    margin: 0;
  }
  .portrait-scope {
    margin: 0 0 8px;
    color: var(--muted);
    font-size: 14px;
  }
  .portrait-caption {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px 20px;
    margin-bottom: 16px;
    color: var(--muted);
    font-family: var(--meta);
    font-size: 13px;
  }
  .composition {
    grid-column: 1/-1;
    display: flex;
    height: 42px;
    gap: 4px;
    margin-top: 8px;
  }
  .color-hint {
    grid-column: 1/-1;
    margin: -2px 0 16px;
    color: var(--muted);
    font: 12px var(--meta);
  }
  .instrument-grid {
    grid-column: 1/-1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 24px;
  }
  figure {
    margin: 0;
    min-width: 0;
  }
  .instrument-card figcaption {
    padding: 4px 0 18px;
  }
  .instrument-heading {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
  }
  .instrument-name {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin-top: 12px;
  }
  .instrument-name h2 {
    font-size: clamp(1.2rem, 1.8vw, 1.75rem);
  }
  .family-card-link {
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    text-align: left;
    text-decoration: underline;
    text-decoration-color: var(--line-strong);
    text-decoration-thickness: 1px;
    text-underline-offset: 5px;
    transition:
      color 150ms ease,
      text-decoration-color 150ms ease;
  }
  .family-card-link:hover,
  .family-card-link:focus-visible {
    color: var(--family-tone-text);
    text-decoration-color: currentColor;
  }
  .family-card-link {
    color: var(--muted);
    font: 12px/1.5 var(--meta);
    text-decoration: none;
    white-space: nowrap;
  }
  :global(:root[data-theme="dark"])
    .family-card-link:is(:hover, :focus-visible) {
    color: var(--family-tone);
  }
  .instrument-name strong {
    font-family: var(--meta);
    font-size: 18px;
    font-weight: 400;
    color: var(--family-tone-text);
  }
  .instrument-card .credited-image > img,
  .image-placeholder {
    width: 100%;
    height: 230px;
    object-fit: cover;
    display: block;
    background: var(--panel);
  }
  .image-placeholder {
    display: grid;
    place-items: center;
    color: var(--family-tone-text);
  }
  .tone-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 3px;
    height: 24px;
    margin-top: 4px;
  }
  .credited-image {
    min-width: 0;
  }
  .photo-caption {
    display: grid;
    gap: 2px;
    padding: 8px 0 0;
    margin: 0;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
    letter-spacing: 0.035em;
  }
  .photo-caption-text {
    display: inline-flex;
    align-items: center;
    color: var(--quiet);
    text-transform: uppercase;
  }
  .photo-caption a {
    justify-self: start;
    color: var(--ink);
    text-underline-offset: 3px;
  }
  .photo-caption a:hover,
  .photo-caption a:focus-visible {
    color: var(--accent-soft);
  }
  .archive-section {
    margin-top: 64px;
    padding-top: 32px;
    scroll-margin-top: 24px;
  }
  .section-heading {
    margin-bottom: 36px;
  }
  .section-heading .eyebrow {
    margin: 0 0 12px;
  }
  .palette-scope {
    margin: 14px 0 0;
    color: var(--muted);
    font: 12px var(--meta);
  }
  .palette-layout,
  .discovery-layout {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr);
    gap: 64px;
  }
  .compact-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .compact-list li {
    display: flex;
    justify-content: space-between;
    border-bottom: 1px solid var(--line);
    padding: 12px 0;
    font-size: 15px;
    color: var(--muted);
  }
  .compact-list strong {
    font-weight: 400;
    color: var(--ink);
  }
  .compact-list li:last-child {
    border-bottom: 0;
  }
  .analysis-details {
    margin-top: 36px;
  }
  .discovery-layout {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    align-items: center;
  }
  .discovery-layout img {
    display: block;
    width: 100%;
    height: 300px;
    object-fit: cover;
  }
  .share-section {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 64px;
    align-items: center;
  }
  .share-copy h2 {
    font-size: clamp(2rem, 3.4vw, 3.5rem);
    margin: 16px 0 24px;
  }
  .share-copy :global(.ui-button) {
    margin: 0 10px 10px 0;
  }
  .share-feedback {
    color: var(--muted);
    min-height: 24px;
    font-size: 14px;
  }
  .share-preview > img {
    display: block;
    width: 100%;
    height: auto;
    border: 1px solid var(--line-strong);
  }
  .share-card-preview {
    padding: 28px;
    background: #000;
    color: var(--on-dark);
    border-top: 8px solid var(--report-tone);
    display: grid;
    gap: 28px;
  }
  .share-card-preview > strong {
    font-size: clamp(1.8rem, 2.8vw, 2.8rem);
    line-height: 1.1;
    font-weight: 500;
    letter-spacing: -0.035em;
  }
  .preview-summary {
    margin: 0;
    color: #b5adaa;
    font-size: 14px;
    line-height: 1.5;
  }
  .preview-specimens {
    display: grid;
    grid-template-columns: repeat(var(--specimen-count), minmax(0, 1fr));
    gap: 16px;
  }
  .preview-specimen {
    display: grid;
    grid-template-rows: auto auto 1fr auto;
    min-width: 0;
    gap: 10px;
  }
  .preview-ascii-drawing {
    display: grid;
    place-items: center;
    container-type: inline-size;
    aspect-ratio: 1;
    overflow: hidden;
    border-bottom: 2px solid var(--specimen-tone);
  }
  .preview-ascii-drawing pre {
    margin: 0;
    color: var(--specimen-tone);
    font-family: var(--meta);
    line-height: 0.95;
    font-weight: 500;
  }
  .preview-index,
  .preview-share {
    color: var(--specimen-tone);
    font-family: var(--meta);
  }
  .preview-index {
    font-size: 10px;
  }
  .preview-family {
    font-size: 14px;
    line-height: 1.25;
  }
  .preview-share {
    font-size: 22px;
  }
  .share-card-preview .eyebrow,
  .share-card-preview .preview-note {
    color: #b5adaa;
  }
  .preview-note {
    color: var(--muted);
    font-size: 12px;
  }
  .archive-section.unavailable-section {
    display: flex;
    align-items: baseline;
    gap: 24px;
    margin-top: 28px;
    padding: 12px 0;
    border-block: 1px solid var(--line);
  }
  .archive-section.unavailable-section > p {
    margin: 0;
  }
  .archive-section.unavailable-section > p:last-child {
    color: var(--muted);
    font-size: 14px;
  }
  @media (max-width: 800px) {
    .portrait {
      grid-template-columns: 1fr;
      padding-top: 24px;
      gap: 24px;
    }
    .portrait-caption {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }
    .instrument-grid {
      grid-template-columns: 1fr;
      gap: 32px;
    }
    .instrument-card .credited-image > img {
      height: 260px;
    }
    .palette-layout,
    .discovery-layout,
    .share-section {
      grid-template-columns: 1fr;
      gap: 32px;
    }
    .archive-section {
      margin-top: 44px;
    }
    .share-card-preview {
      padding: 20px;
    }
    .archive-section.unavailable-section {
      flex-wrap: wrap;
      gap: 4px 12px;
    }
    .share-preview {
      width: calc(100% + 40px);
      margin-inline: -20px;
    }
    .share-preview > img {
      border: 0;
    }
  }
</style>
