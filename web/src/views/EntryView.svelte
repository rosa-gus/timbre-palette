<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import { fadeTransition } from "../transitions/dialog";
  import FamilyPalette from "../components/FamilyPalette.svelte";
  import instrumentPreview from "../analysis/instrument-preview.generated.json";
  import type { FamilyPresence, ProfileAnalysisV3 } from "../api/types";
  import pronunciationUrl from "../assets/audio/timbrepalette.mp3";
  import { formatWaitDuration } from "../i18n/formatters";
  import Message from "../i18n/Message.svelte";
  import { translation as t, localeStore, type Locale } from "../i18n/runtime";
  import HistoryResumeNotice from "../components/HistoryResume.svelte";
  import type { HistoryResume } from "../analysis/history";
  import LoadingView from "./LoadingView.svelte";
  import Button from "../components/Button.svelte";
  import Arrow from "../components/Arrow.svelte";
  import AnalysisLimits from "../components/AnalysisLimits.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import type { ListeningPeriod } from "../api/types";

  export let username = "";
  export let catalogSize: number | null = null;
  export let period: ListeningPeriod = "1month";
  export let periods: { value: ListeningPeriod; label: string }[] = [];
  export let formError = "";
  export let resumeProgress: HistoryResume | null = null;
  export let waitSeconds = 0;
  export let onResume: () => void = () => undefined;
  export let loading = false;
  export let loadingTitle = $t("loading.historyTitle");
  export let loadingDetail = $t("loading.historyDetail");
  export let onUsernameChange: (value: string) => void = () => undefined;
  export let onPeriodChange: (value: ListeningPeriod) => void = () => undefined;
  export let onSubmit: () => void = () => undefined;
  export let onExample: () => void = () => undefined;

  let pronunciationAudio: HTMLAudioElement;
  let pronunciationPlaying = false;
  let pronunciationError = false;
  let previewOpen: "palette" | "instrument" | "share" | null = null;
  $: previewInstrument = instrumentPreview[$localeStore];
  let previewLoading = false;
  let previewError = false;
  let previewFamilies: FamilyPresence[] = [];
  let previewHeading: HTMLParagraphElement;
  let usernameInput: HTMLInputElement;
  const previewController = new AbortController();
  let examplePromise: Promise<ProfileAnalysisV3> | null = null;
  let sharePreviewUrl = "";
  let sharePreviewLoading = false;
  let sharePreviewError = false;
  let shareRequest = 0;
  let sharePendingLocale: Locale | null = null;
  const shareImages = new Map<Locale, string>();

  function loadPreviewExample(): Promise<ProfileAnalysisV3> {
    if (!examplePromise) {
      examplePromise = import("../analysis/browser")
        .then(({ getBrowserExampleAnalysis }) =>
          getBrowserExampleAnalysis(
            "1month",
            previewController.signal,
            "entry-palette-preview",
          ),
        )
        .catch((error) => {
          examplePromise = null;
          throw error;
        });
    }
    return examplePromise;
  }

  $: if (previewOpen === "share") void prepareSharePreview($localeStore);

  async function prepareSharePreview(language: Locale): Promise<void> {
    const cached = shareImages.get(language);
    if (cached) {
      ++shareRequest;
      sharePreviewUrl = cached;
      sharePreviewLoading = false;
      sharePreviewError = false;
      sharePendingLocale = null;
      return;
    }
    if (sharePendingLocale === language) return;
    const request = ++shareRequest;
    sharePendingLocale = language;
    sharePreviewLoading = true;
    sharePreviewError = false;
    sharePreviewUrl = "";
    try {
      await tick();
      // Let the existing loading indicator paint before rendering the canvas.
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      );
      const [example, { createShareImage }] = await Promise.all([
        loadPreviewExample(),
        import("../sharing/share"),
      ]);
      if (previewController.signal.aborted || request !== shareRequest) return;
      const blob = await createShareImage(example.track_palette, undefined, {
        isExample: true,
        displayName: example.profile.realname || $t("example.displayName"),
      });
      if (
        previewController.signal.aborted ||
        request !== shareRequest ||
        $localeStore !== language
      )
        return;
      const url = URL.createObjectURL(blob);
      shareImages.set(language, url);
      sharePreviewUrl = url;
    } catch {
      if (!previewController.signal.aborted && request === shareRequest)
        sharePreviewError = true;
    } finally {
      if (request === shareRequest) {
        sharePreviewLoading = false;
        sharePendingLocale = null;
      }
    }
  }

  async function showPreview(
    kind: "palette" | "instrument" | "share",
  ): Promise<void> {
    if (loading) return;
    if (previewOpen === kind) {
      previewOpen = null;
      return;
    }
    previewOpen = kind;
    await tick();
    previewHeading?.focus();
    if (kind !== "palette") return;
    if (previewFamilies.length || previewLoading) return;
    previewLoading = true;
    previewError = false;
    try {
      const example = await loadPreviewExample();
      if (!previewController.signal.aborted)
        previewFamilies = example.track_palette.families.slice(0, 3);
    } catch {
      if (!previewController.signal.aborted) previewError = true;
    } finally {
      previewLoading = false;
    }
  }

  async function returnToForm(): Promise<void> {
    previewOpen = null;
    await tick();
    usernameInput?.focus();
  }

  async function togglePronunciation(): Promise<void> {
    if (!pronunciationAudio) return;
    pronunciationError = false;
    if (!pronunciationAudio.paused) {
      pronunciationAudio.pause();
      pronunciationAudio.currentTime = 0;
      return;
    }
    if (!pronunciationAudio.getAttribute("src"))
      pronunciationAudio.src = pronunciationUrl;
    else if (pronunciationAudio.error) pronunciationAudio.load();
    try {
      await pronunciationAudio.play();
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      pronunciationPlaying = false;
      pronunciationError = true;
    }
  }

  onDestroy(() => pronunciationAudio?.pause());
  onDestroy(() => previewController.abort());
  onDestroy(() => {
    for (const url of shareImages.values()) URL.revokeObjectURL(url);
  });

  function submitProfile(): void {
    if (loading || waitSeconds > 0) return;
    if (resumeProgress?.pages) onResume();
    else onSubmit();
  }
</script>

{#snippet titleEmphasis(text: string)}<span>{text}</span>{/snippet}
{#snippet catalogCount(text: string)}<code>{text}</code>{/snippet}

<section
  class:loading
  class="entry-view"
  aria-labelledby={loading ? "loading-title" : "entry-title"}
>
  {#if loading}
    <LoadingView
      title={loadingTitle}
      context={$t("loading.profileContext", {
        username: username ? `@${username}` : $t("example.displayName"),
        period:
          periods.find((option) => option.value === period)?.label ?? period,
      })}
      detail={loadingDetail}
    />
  {:else}
    <div class="entry-intro">
      <h1 id="entry-title" class="entry-tagline">
        <Message message="entry.title" wrappers={{ emphasis: titleEmphasis }} />
      </h1>
      <p class="entry-subtitle">{$t("entry.subtitle")}</p>
      <div class="entry-pronunciation">
        <button
          class="pronunciation-button"
          type="button"
          aria-label={pronunciationPlaying
            ? $t("entry.pronunciationStop")
            : $t("entry.pronunciationPlay")}
          aria-pressed={pronunciationPlaying}
          on:click={togglePronunciation}
        >
          <span lang="en-GB" aria-hidden="true">/ˈtæm.bə ˈpæl.ət/</span>
          <span
            class="pronunciation-symbol"
            class:playing={pronunciationPlaying}
            aria-hidden="true"
          ></span>
        </button>
        <audio
          bind:this={pronunciationAudio}
          preload="none"
          hidden
          on:play={() => (pronunciationPlaying = true)}
          on:pause={() => (pronunciationPlaying = false)}
          on:ended={() => (pronunciationPlaying = false)}
          on:error={() => {
            pronunciationPlaying = false;
            pronunciationError = true;
          }}
        ></audio>
        {#if pronunciationError}<p class="pronunciation-error" role="status">
            {$t("entry.pronunciationError")}
          </p>{/if}
      </div>
      <ul class="entry-description" role="list">
        <li>
          <span class="entry-list-marker" aria-hidden="true"></span><button
            class="entry-preview-trigger"
            type="button"
            aria-expanded={previewOpen === "palette" && !loading}
            aria-controls="entry-preview"
            disabled={loading}
            on:click={() => showPreview("palette")}
            >{$t("entry.discover")}</button
          >
        </li>
        <li>
          <span class="entry-list-marker" aria-hidden="true"></span><button
            class="entry-preview-trigger"
            type="button"
            aria-expanded={previewOpen === "instrument" && !loading}
            aria-controls="entry-preview"
            disabled={loading}
            on:click={() => showPreview("instrument")}
            >{$t("entry.explore")}</button
          >
        </li>
        <li>
          <span class="entry-list-marker" aria-hidden="true"></span><button
            class="entry-preview-trigger"
            type="button"
            aria-expanded={previewOpen === "share" && !loading}
            aria-controls="entry-preview"
            disabled={loading}
            on:click={() => showPreview("share")}>{$t("entry.share")}</button
          >
        </li>
      </ul>
      <p class="entry-preview-hint">{$t("entry.previewHint")}</p>
      <p class="entry-source-note">{$t("entry.sourceNote")}</p>
      {#if catalogSize !== null}
        <p class="entry-catalog-size">
          <Message
            message="entry.catalogSize"
            values={{ count: catalogSize }}
            wrappers={{ value: catalogCount }}
          />
        </p>
      {/if}
    </div>

    <div class="entry-action-area">
      {#if !loading}
        {#each previewOpen ? [previewOpen] : [] as previewKind (previewKind)}
          <div
            id="entry-preview"
            class="entry-preview"
            class:instrument-preview-shell={previewKind === "instrument"}
            in:fadeTransition|global
            out:fadeTransition|global
            aria-busy={(previewKind === "palette" && previewLoading) ||
              (previewKind === "share" && sharePreviewLoading)}
          >
            {#if previewKind !== "instrument"}
              <div class="preview-heading">
                <p class="eyebrow" tabindex="-1" bind:this={previewHeading}>
                  {previewKind === "palette"
                    ? $t("entry.previewHeading")
                    : $t("sharing.exampleHeading")}
                </p>
                <button
                  type="button"
                  class="preview-close"
                  aria-label={$t("entry.previewClose")}
                  on:click={returnToForm}>[×]</button
                >
              </div>
            {/if}
            {#if previewKind === "share"}
              {#if sharePreviewLoading}
                <p class="share-preview-status" role="status">
                  <span class="loading-indicator" aria-hidden="true"></span>
                  <span>{$t("entry.sharePreviewLoading")}</span>
                </p>
              {:else if sharePreviewError}
                <p class="entry-source-note" role="status">
                  {$t("sharing.failed")}
                </p>
              {:else if sharePreviewUrl}
                <img
                  class="share-preview-image"
                  src={sharePreviewUrl}
                  width="1200"
                  height="1500"
                  alt={$t("sharing.previewAlt", {
                    listener: $t("example.displayName"),
                  })}
                />
              {/if}
            {:else if previewKind === "instrument"}
              <div class="instrument-preview-stack">
                <figure
                  class="instrument-preview-card instrument-preview-panel"
                  style={`--family-tone:${previewInstrument.image?.tone.highlight ?? "#9EBBD1"}`}
                >
                  <figcaption>
                    <div class="instrument-preview-card-heading">
                      <p
                        class="eyebrow"
                        tabindex="-1"
                        bind:this={previewHeading}
                      >
                        {$t("entry.instrumentPreviewHeading")} ({previewInstrument.name})
                      </p>
                      <button
                        type="button"
                        class="preview-close"
                        aria-label={$t("entry.previewClose")}
                        on:click={returnToForm}>[×]</button
                      >
                    </div>
                  </figcaption>
                  {#if previewInstrument.image}
                    <div class="instrument-preview-card-image">
                      <img
                        src={`${import.meta.env.BASE_URL}${previewInstrument.image.url}`}
                        alt={previewInstrument.image.alt}
                        width={previewInstrument.image.width}
                        height={previewInstrument.image.height}
                      />
                    </div>
                    <p class="instrument-preview-card-caption">
                      {$t("images.photoCaption", {
                        caption: previewInstrument.image.caption,
                      })}
                      {#if previewInstrument.image.credit.photographer_url}
                        <a
                          href={previewInstrument.image.credit.photographer_url}
                          target="_blank"
                          rel="noreferrer"
                          >{previewInstrument.image.credit.photographer}<Arrow
                            direction="up-right"
                          /></a
                        >
                      {/if}
                    </p>
                  {:else}
                    <div class="instrument-preview-image-empty">
                      {previewInstrument.name}
                    </div>
                  {/if}
                </figure>
                <div
                  class="instrument-preview-connector"
                  aria-hidden="true"
                ></div>
                <div
                  class="instrument-preview instrument-preview-panel"
                  lang={$localeStore}
                >
                  <p class="instrument-preview-family">
                    {previewInstrument.family}
                  </p>
                  <section
                    class="instrument-block"
                    aria-labelledby="preview-sound-production"
                  >
                    <h3 id="preview-sound-production" class="eyebrow">
                      <Message message="instrument.soundProductionHeading" />
                    </h3>
                    <p>{previewInstrument.soundProduction}</p>
                  </section>
                  <section
                    class="instrument-block"
                    aria-labelledby="preview-curiosity"
                  >
                    <h3 id="preview-curiosity" class="eyebrow">
                      <Message message="instrument.curiosityHeading" />
                    </h3>
                    <p>{previewInstrument.curiosity}</p>
                  </section>
                  <div class="instrument-preview-sources">
                    <p class="eyebrow">
                      <Message message="instrument.sourcesHeading" />
                    </p>
                    {#each previewInstrument.sources as source}
                      <a
                        href={source.url}
                        title={source.title}
                        target="_blank"
                        rel="noreferrer"
                        >{source.publisher}<Arrow direction="up-right" /></a
                      >
                    {/each}
                  </div>
                </div>
              </div>
            {:else if previewLoading}
              <p class="entry-source-note" role="status">
                {$t("loading.catalog")}
              </p>
            {:else if previewError}
              <p class="entry-source-note" role="status">
                {$t("entry.previewUnavailable")}
              </p>
            {:else}
              <p class="palette-preview-intro">{$t("entry.previewIntro")}</p>
              <FamilyPalette families={previewFamilies} compact />
              <p class="entry-source-note">{$t("entry.previewScope")}</p>
            {/if}
          </div>
          <div class="preview-actions">
            <Button variant="primary" on:click={returnToForm}
              ><span>{$t("entry.previewConsult")}</span><Arrow
                direction="right"
              /></Button
            >
            <button class="example-button" type="button" on:click={onExample}
              >{$t("entry.previewFull")}<Arrow direction="right" /></button
            >
          </div>
        {/each}
      {/if}
      <form
        class="profile-form"
        hidden={previewOpen !== null && !loading}
        inert={loading}
        aria-hidden={loading}
        on:submit|preventDefault={submitProfile}
      >
        <div class="field-block">
          <div class="field-heading">
            <label for="username">{$t("entry.profileLabel")}</label>
          </div>
          <div class="username-field">
            <span id="username-prefix" class="username-prefix"
              >last.fm/user/</span
            >
            <input
              bind:this={usernameInput}
              id="username"
              aria-describedby="username-prefix"
              value={username}
              on:input={(event) => onUsernameChange(event.currentTarget.value)}
              autocomplete="username"
              spellcheck="false"
              placeholder={$t("entry.usernamePlaceholder")}
              aria-invalid={formError ? "true" : undefined}
              aria-errormessage={formError ? "profile-error" : undefined}
              required
              maxlength="64"
            />
          </div>
        </div>
        <div class="form-row">
          <div class="field-block period-field">
            <span class="field-label">{$t("periods.label")}</span>
            <SegmentedControl
              label={$t("periods.listeningLabel")}
              options={periods}
              value={period}
              onChange={(value) => onPeriodChange(value as ListeningPeriod)}
            />
          </div>
          <Button variant="primary" type="submit" disabled={waitSeconds > 0}>
            <span
              >{resumeProgress?.pages
                ? $t("actions.resume")
                : $t("actions.search")}</span
            >
            <span class="submit-arrow" aria-hidden="true"
              ><Arrow direction="right" /></span
            >
          </Button>
        </div>
        {#if formError}<p id="profile-error" class="form-error" role="alert">
            {formError}
          </p>{/if}
        {#if !loading && resumeProgress}
          <HistoryResumeNotice
            progress={resumeProgress}
            {waitSeconds}
            showResume={false}
          />
        {:else if !loading && waitSeconds > 0}
          <p class="form-error">
            {$t("history.wait", { duration: formatWaitDuration(waitSeconds) })}
          </p>
        {/if}
        <div class="entry-secondary">
          <button
            class="example-button"
            type="button"
            disabled={loading}
            on:click={onExample}
            >{$t("entry.example")}<Arrow direction="right" />
          </button>
          {#if !loading}<div class="entry-limits"><AnalysisLimits /></div>{/if}
        </div>
      </form>
    </div>
  {/if}
</section>

<style>
  .entry-view {
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
    align-content: center;
    align-items: start;
    gap: clamp(40px, 7vw, 120px);
    width: min(100%, 1320px);
    margin-inline: auto;
    padding: clamp(48px, 8svh, 100px) 0 56px;
    color: var(--ink);
  }
  .entry-view.loading {
    grid-template-columns: minmax(0, 1fr);
    align-content: center;
    justify-items: center;
    gap: 0;
  }
  .entry-intro {
    min-width: 0;
  }
  .entry-tagline {
    max-width: none;
    margin: 0;
    color: var(--ink);
    font-size: clamp(2rem, 3vw, 3rem);
    font-weight: 500;
    letter-spacing: -0.055em;
    line-height: 1.08;
    text-wrap: wrap;
  }
  .entry-tagline span {
    display: block;
  }
  .entry-subtitle {
    max-width: 44ch;
    margin: 16px 0 0;
    color: var(--muted);
    font-size: 1rem;
    line-height: 1.6;
    text-wrap: pretty;
  }
  .entry-pronunciation {
    margin-top: 12px;
  }
  .pronunciation-button {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    min-height: 36px;
    padding: 4px 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
    cursor: pointer;
  }
  .pronunciation-button:is(:hover, :focus-visible),
  .pronunciation-button[aria-pressed="true"] {
    color: var(--accent-soft);
  }
  .pronunciation-symbol {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 10px;
    height: 12px;
  }
  .pronunciation-symbol::before {
    width: 0;
    height: 0;
    border-top: 4px solid transparent;
    border-bottom: 4px solid transparent;
    border-left: 6px solid currentColor;
    content: "";
  }
  .pronunciation-symbol.playing::before {
    width: 6px;
    height: 8px;
    border: 0;
    background: currentColor;
  }
  .pronunciation-error {
    max-width: 36ch;
    margin: 4px 0 8px;
    color: var(--accent-soft);
    font: 12px/1.5 var(--meta);
  }
  .entry-description {
    display: grid;
    gap: 8px;
    max-width: 44ch;
    margin: 8px 0 0;
    padding: 0;
    list-style: none;
    color: var(--muted);
    font-size: 1rem;
    line-height: 1.5;
    text-wrap: pretty;
  }
  .entry-description li {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 12px;
  }
  .entry-list-marker {
    width: 7px;
    height: 7px;
    background: var(--accent);
  }
  .entry-preview-trigger {
    display: inline;
    justify-self: start;
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    text-decoration: underline;
    text-decoration-color: var(--line-strong);
    text-decoration-thickness: 1px;
    text-underline-offset: 4px;
    cursor: pointer;
  }
  .entry-preview-trigger:is(:hover, :focus-visible, [aria-expanded="true"]) {
    color: var(--ink);
    text-decoration-color: currentColor;
  }
  .entry-preview-trigger[aria-expanded="true"] {
    color: var(--accent-soft);
  }
  .entry-preview {
    grid-area: 1 / 1;
    align-self: start;
    padding: 24px;
    border: 1px solid var(--line-strong);
    background: var(--paper);
  }
  .palette-preview-intro {
    margin: 0 0 20px;
    color: var(--muted);
    line-height: 1.6;
    text-wrap: pretty;
  }
  .entry-preview-hint {
    margin: 8px 0 0;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
  }
  .preview-heading {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 24px;
    color: var(--muted);
  }
  .preview-heading p {
    margin: 0;
  }
  .preview-close {
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
    cursor: pointer;
  }
  .preview-close:hover {
    color: var(--ink);
  }
  .share-preview-status {
    display: flex;
    align-items: baseline;
    gap: 12px;
    min-height: 180px;
    margin: 0;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
  }
  .share-preview-image {
    display: block;
    width: 100%;
    height: auto;
  }
  .instrument-preview-stack {
    display: grid;
  }
  .instrument-preview-shell {
    padding: 0;
    border: 0;
    background: transparent;
  }
  .instrument-preview-panel {
    min-width: 0;
    margin: 0;
    padding: 24px;
    border: 1px solid var(--line-strong);
    background: var(--paper);
  }
  .instrument-preview-card figcaption {
    padding: 0 0 16px;
  }
  .instrument-preview-card-heading {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
  }
  .instrument-preview-card-heading .eyebrow {
    margin: 0;
    color: var(--muted);
  }
  .instrument-preview-card-image img,
  .instrument-preview-image-empty {
    display: block;
    width: 100%;
    height: 136px;
    object-fit: cover;
    background: var(--panel);
  }
  .instrument-preview-image-empty {
    display: grid;
    place-items: center;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
  }
  .instrument-preview-card-caption {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin: 0;
    padding: 12px 0 0;
    color: var(--muted);
    font: 11px/1.5 var(--meta);
  }
  .instrument-preview-card-caption a {
    color: var(--ink);
    text-underline-offset: 3px;
  }
  .instrument-preview-card-caption a:hover,
  .instrument-preview-card-caption a:focus-visible {
    color: var(--accent-soft);
  }
  .instrument-preview-connector {
    justify-self: center;
    height: 24px;
    border-left: 1px dotted var(--line-strong);
  }
  .instrument-preview-stack > .instrument-preview .instrument-preview-family {
    margin-top: 0;
  }
  .instrument-preview-image-empty {
    height: 136px;
  }
  .instrument-preview-family {
    margin: 8px 0 24px;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
  }
  .instrument-block {
    margin: 0 0 24px;
  }
  .instrument-block .eyebrow,
  .instrument-preview-sources .eyebrow {
    margin: 0 0 12px;
    color: var(--muted);
    letter-spacing: 0.065em;
  }
  .instrument-block > p {
    margin: 0;
    color: var(--muted);
    font-size: 14px;
    line-height: 1.7;
  }
  .instrument-preview-sources a {
    color: var(--muted);
    font: 12px/1.5 var(--meta);
    text-underline-offset: 4px;
  }
  .instrument-preview-sources a:is(:hover, :focus-visible) {
    color: var(--ink);
  }
  .preview-actions {
    grid-area: 2 / 1;
    display: grid;
    gap: 8px;
    margin-top: 24px;
  }
  .preview-actions :global(.ui-button) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    min-height: 48px;
  }
  .entry-source-note {
    max-width: 64ch;
    margin: 16px 0 0;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
    text-wrap: pretty;
  }
  .entry-catalog-size {
    margin: 8px 0 0;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
  }
  .entry-catalog-size code {
    color: var(--accent-soft);
    font: inherit;
  }
  .entry-action-area {
    display: grid;
    position: relative;
    width: 100%;
    max-width: 440px;
    min-width: 0;
    margin-top: clamp(80px, 15svh, 160px);
    justify-self: end;
  }
  .profile-form {
    grid-area: 1 / 1;
    width: 100%;
  }
  .field-block {
    display: grid;
    gap: 10px;
  }
  .field-heading {
    display: flex;
  }
  .field-block label,
  .field-label {
    color: var(--muted);
    font-family: var(--meta);
    font-size: 12px;
    letter-spacing: 0.065em;
    text-transform: uppercase;
  }
  .example-button {
    display: inline-flex;
    align-items: center;
    min-height: 44px;
    margin: 0;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--meta);
    font-size: 12px;
  }
  .example-button:hover:not(:disabled),
  .example-button:focus-visible {
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 4px;
  }
  .example-button:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }
  .username-field {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    min-height: 52px;
    border: 1px solid var(--line-strong);
    background: var(--paper);
  }
  .username-field:focus-within {
    border-color: var(--accent-soft);
    outline: 2px solid var(--accent-soft);
    outline-offset: 3px;
  }
  .username-prefix {
    padding: 12px 14px;
    border-right: 1px solid var(--line);
    color: var(--muted);
    font-family: var(--meta);
    font-size: 12px;
    white-space: nowrap;
  }
  input {
    min-width: 0;
    width: 100%;
    padding: 12px 14px;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: var(--ink);
    font-size: 1rem;
  }
  input::placeholder {
    color: var(--quiet);
    opacity: 1;
  }
  input:focus {
    outline: 0;
  }
  .form-row {
    display: grid;
    gap: 24px;
    margin-top: 24px;
  }
  .period-field :global(.segmented-control) {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }
  .period-field :global(.segment-button) {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 44px;
    background: var(--paper);
  }
  .period-field :global(.segment-button[data-state="checked"]) {
    background: var(--accent-soft);
  }
  .form-row :global(.ui-button) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    min-height: 48px;
  }
  .submit-arrow {
    display: inline-flex;
    flex-shrink: 0;
  }
  .submit-arrow :global(.icon-arrow) {
    margin: 0;
  }
  .form-error {
    margin: 16px 0 0;
    color: var(--accent-soft);
    font-family: var(--meta);
    font-size: 13px;
    line-height: 1.5;
  }
  .entry-secondary {
    display: flex;
    flex-direction: column;
    align-items: start;
    gap: 8px;
    margin-top: 12px;
    min-width: 0;
  }
  .entry-limits {
    width: 100%;
    min-width: 0;
  }
  @media (max-width: 1000px) and (min-width: 801px) {
    .entry-view {
      gap: 40px;
    }
    .entry-tagline {
      font-size: clamp(2rem, 3vw, 2.5rem);
    }
  }
  @media (max-width: 800px) {
    .entry-view {
      grid-template-columns: minmax(0, 1fr);
      align-content: start;
      gap: 36px;
      padding: 56px 0 28px;
      max-width: 520px;
    }
    .entry-tagline {
      font-size: clamp(1.5rem, 6vw, 2rem);
      letter-spacing: -0.045em;
      line-height: 1.1;
    }
    .entry-description {
      font-size: 14px;
    }
    .entry-preview {
      padding: 16px;
    }
    .entry-action-area {
      max-width: none;
      margin-top: 0;
    }
  }
  @media (max-width: 380px) {
    .username-prefix {
      padding-inline: 10px;
      font-size: 11px;
    }
    input {
      padding-inline: 10px;
    }
    .period-field :global(.segment-button) {
      padding-inline: 4px;
      font-size: 11px;
    }
  }
</style>
