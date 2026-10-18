<script lang="ts">
  import type { Confidence, FamilyPresence } from "../api/types";
  import { formatPercent } from "../i18n/formatters";
  import { translation as t, localeStore } from "../i18n/runtime";
  import { getFamilyTexture } from "../sharing/ascii";
  import { fitFamilyTexture } from "../sharing/texture";
  import { fallbackTone, toneText } from "../sharing/palette-tones";
  import Badge from "./Badge.svelte";
  import ColorSwatch from "./ColorSwatch.svelte";

  export let families: FamilyPresence[];
  export let compact = false;
  export let confidenceLabels: Partial<Record<Confidence, string>> = {};
  export let onOpenInstrumentSlug: (slug: string) => void = () => undefined;
  $: percent = (value: number): string => formatPercent(value, 0, $localeStore);
</script>

<div class="family-list" class:compact aria-label={$t("report.familiesLabel")}>
  {#each families as family}<div
      class="family-row"
      style={`--family-tone:${family.tone?.highlight ?? fallbackTone};--family-tone-text:${toneText(family.tone?.highlight ?? fallbackTone)}`}
    >
      <div class="family-label">
        {#if compact}
          <span lang={family.locale}>{family.name}</span>
        {:else}
        <button
          type="button"
          class="family-link"
          aria-label={$t("actions.openInstrument", { name: family.name })}
          on:click={() => onOpenInstrumentSlug(family.slug)}
          lang={family.locale}
          >{family.name}</button
        ><Badge tone="neutral"
          >{confidenceLabels[family.confidence]}</Badge
        >
        {/if}
      </div>
      <div
        class="share-bar"
        aria-label={`${family.name}: ${percent(family.share)}`}
        style={`--family-texture-tone:${toneText(family.tone?.highlight ?? fallbackTone)};--family-tone:${family.tone?.highlight ?? fallbackTone}`}
      >
        <span
          class="family-texture"
          style={`width:${family.share * 100}%;`}
          aria-hidden="true"
          use:fitFamilyTexture={getFamilyTexture(family.slug)}
        ></span>
        <ColorSwatch
          color={family.tone?.highlight ?? fallbackTone}
          label={`${family.name} (${percent(family.share)})`}
          className="share-swatch"
          style={`width:${family.share * 100}%;`}
        />
      </div>
      <strong>{percent(family.share)}</strong>
    </div>{/each}
</div>

<style>
  .family-list {
    display: grid;
    gap: 24px;
  }
  .family-row {
    display: grid;
    grid-template-columns: minmax(170px, 1fr) minmax(80px, 1.5fr) 48px;
    gap: 20px;
    align-items: center;
  }
  .family-label {
    display: grid;
    justify-items: start;
    gap: 6px;
  }
  .family-label .family-link {
    font-size: 17px;
  }
  .share-bar {
    position: relative;
    min-width: 0;
    height: 28px;
    border-bottom: 1px solid var(--line);
  }
  .family-texture {
    display: block;
    color: var(--family-texture-tone);
    font: 14px/22px var(--meta);
    letter-spacing: 0;
    white-space: nowrap;
    pointer-events: none;
  }
  :global(:root[data-theme="dark"]) .family-texture {
    color: var(--family-tone);
  }
  .share-bar :global(.share-swatch) {
    position: absolute;
    inset: 0 auto 0 0;
    height: 100%;
    background: transparent;
    border-bottom: 3px solid var(--swatch-color);
  }
  .share-bar :global(.share-swatch:hover),
  .share-bar :global(.share-swatch:focus-visible),
  .share-bar :global(.share-swatch[data-state="open"]) {
    outline-offset: 2px;
  }
  .family-row > strong {
    font-family: var(--meta);
    font-size: 14px;
    font-weight: 400;
    text-align: right;
  }
  .family-link {
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
    transition: color 150ms ease, text-decoration-color 150ms ease;
  }
  .family-link:is(:hover, :focus-visible) {
    color: var(--family-tone-text);
    text-decoration-color: currentColor;
  }
  :global(:root[data-theme="dark"]) .family-link:is(:hover, :focus-visible) {
    color: var(--family-tone);
  }
  .compact { gap: 20px; }
  .compact .family-row {
    grid-template-columns: minmax(0, 1fr) 48px;
    gap: 8px;
  }
  .compact .family-row > strong { grid-column: 2; grid-row: 1; }
  .compact .share-bar { grid-column: 1 / -1; }
  @media (max-width: 800px) {
    .family-row {
      grid-template-columns: 1fr 48px;
      gap: 10px;
    }
    .family-row > strong {
      grid-column: 2;
      grid-row: 1;
    }
    .share-bar {
      grid-column: 1/-1;
    }
  }
</style>
