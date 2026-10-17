<script lang="ts">
  import { onDestroy } from "svelte";
  import pronunciationUrl from "../assets/audio/timbrepalette.mp3";
  import { formatWaitDuration } from "../i18n/formatters";
  import Message from "../i18n/Message.svelte";
  import { translation as t } from "../i18n/runtime";
  import HistoryResumeNotice from "../components/HistoryResume.svelte";
  import type { HistoryResume } from "../analysis/history";
  import LoadingView from "./LoadingView.svelte";
  import Button from "../components/Button.svelte";
  import Arrow from "../components/Arrow.svelte";
  import AnalysisLimits from "../components/AnalysisLimits.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import type { ListeningPeriod } from "../api/types";

  export let username = "";
  export let period: ListeningPeriod = "1month";
  export let periods: { value: ListeningPeriod; label: string }[] = [];
  export let formError = "";
  export let resumeProgress: HistoryResume | null = null;
  export let waitSeconds = 0;
  export let onResume: () => void = () => undefined;
  export let loading = false;
  export let loadingTitle = $t("loading.historyTitle");
  export let loadingDescription = $t("loading.historyDescription");
  export let loadingDetail = $t("loading.historyDetail");
  export let onUsernameChange: (value: string) => void = () => undefined;
  export let onPeriodChange: (value: ListeningPeriod) => void = () => undefined;
  export let onSubmit: () => void = () => undefined;
  export let onExample: () => void = () => undefined;

  let pronunciationAudio: HTMLAudioElement;
  let pronunciationPlaying = false;
  let pronunciationError = false;

  async function togglePronunciation(): Promise<void> {
    if (!pronunciationAudio) return;
    pronunciationError = false;
    if (!pronunciationAudio.paused) {
      pronunciationAudio.pause();
      pronunciationAudio.currentTime = 0;
      return;
    }
    if (!pronunciationAudio.getAttribute("src")) pronunciationAudio.src = pronunciationUrl;
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

  function submitProfile(): void {
    if (loading || waitSeconds > 0) return;
    if (resumeProgress?.pages) onResume();
    else onSubmit();
  }
</script>

{#snippet titleEmphasis(text: string)}<span>{text}</span>{/snippet}

<section
  class:loading
  class="entry-view"
  aria-labelledby="entry-title"
  aria-busy={loading}
>
  <div class="entry-intro">
    <h1 id="entry-title" class="entry-tagline"><Message message="entry.title" wrappers={{ emphasis: titleEmphasis }} />
    </h1>
    <div class="entry-pronunciation">
      <button
        class="pronunciation-button"
        type="button"
        aria-label={pronunciationPlaying ? $t("entry.pronunciationStop") : $t("entry.pronunciationPlay")}
        aria-pressed={pronunciationPlaying}
        on:click={togglePronunciation}
      >
        <span lang="en-GB" aria-hidden="true">/ˈtæm.bə ˈpæl.ət/</span>
        <span class="pronunciation-symbol" class:playing={pronunciationPlaying} aria-hidden="true"></span>
      </button>
      <audio
        bind:this={pronunciationAudio}
        preload="none"
        hidden
        on:play={() => pronunciationPlaying = true}
        on:pause={() => pronunciationPlaying = false}
        on:ended={() => pronunciationPlaying = false}
        on:error={() => { pronunciationPlaying = false; pronunciationError = true; }}
      ></audio>
      {#if pronunciationError}<p class="pronunciation-error" role="status">{$t("entry.pronunciationError")}</p>{/if}
    </div>
    <p class="entry-description">{$t("entry.description")} </p>
  </div>

  <div class="entry-action-area">
    <form
      class="profile-form"
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
          <span>{resumeProgress?.pages ? $t("actions.resume") : $t("actions.search")}</span>
          <span class="submit-arrow" aria-hidden="true"><Arrow direction="right" /></span>
        </Button>
      </div>
      {#if formError}<p id="profile-error" class="form-error" role="alert">{formError}</p>{/if}
      {#if !loading && resumeProgress}
        <HistoryResumeNotice progress={resumeProgress} {waitSeconds} showResume={false} />
      {:else if !loading && waitSeconds > 0}
        <p class="form-error">{$t("history.wait", { duration: formatWaitDuration(waitSeconds) })}</p>
      {/if}
      <div class="entry-secondary">
        <button
          class="example-button"
          type="button"
          disabled={loading}
          aria-label={$t("entry.exampleLabel")}
          on:click={onExample}
        >{$t("entry.example")}<Arrow direction="right" />
        </button>
        {#if !loading}<div class="entry-limits"><AnalysisLimits /></div>{/if}
      </div>
    </form>
    {#if loading}
      <LoadingView
        title={loadingTitle}
        description={loadingDescription}
        detail={loadingDetail}
      />
    {/if}
  </div>
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
  .entry-intro { min-width: 0; }
  .entry-tagline {
    max-width: none;
    margin: 0;
    color: var(--ink);
    font-size: clamp(2.5rem, 4vw, 4rem);
    font-weight: 500;
    letter-spacing: -0.055em;
    line-height: 1.08;
    text-wrap: wrap;
  }
  .entry-tagline span { display: block; }
  .entry-pronunciation { margin-top: 12px; }
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
  .pronunciation-button[aria-pressed="true"] { color: var(--accent-soft); }
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
    max-width: 32ch;
    margin: 8px 0 0;
    color: var(--muted);
    font-size: 1rem;
    line-height: 1.5;
    text-wrap: pretty;
  }
  .entry-action-area {
    position: relative;
    width: 100%;
    max-width: 440px;
    min-width: 0;
    margin-top: clamp(80px, 15svh, 160px);
    justify-self: end;
  }
  .profile-form { width: 100%; }
  .loading .profile-form { visibility: hidden; }
  .field-block { display: grid; gap: 10px; }
  .field-heading { display: flex; }
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
  .example-button:disabled { cursor: not-allowed; opacity: 0.6; }
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
  input::placeholder { color: var(--quiet); opacity: 1; }
  input:focus { outline: 0; }
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
  .submit-arrow { display: inline-flex; flex-shrink: 0; }
  .submit-arrow :global(.icon-arrow) { margin: 0; }
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
  .entry-limits { width: 100%; min-width: 0; }
  @media (max-width: 1000px) and (min-width: 801px) {
    .entry-view { gap: 40px; }
    .entry-tagline { font-size: clamp(2.5rem, 4vw, 3rem); }
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
      font-size: clamp(1.75rem, 7.5vw, 2.5rem);
      letter-spacing: -0.045em;
      line-height: 1.1;
    }
    .entry-description { font-size: 14px; }
    .entry-action-area { max-width: none; margin-top: 0; }
  }
  @media (max-width: 380px) {
    .username-prefix { padding-inline: 10px; font-size: 11px; }
    input { padding-inline: 10px; }
    .period-field :global(.segment-button) { padding-inline: 4px; font-size: 11px; }
  }
</style>
