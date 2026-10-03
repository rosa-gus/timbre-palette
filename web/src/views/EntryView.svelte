<script lang="ts">
  import chladniHeroImage from "../../../assets/treated/chladni-hero.png";
  import chladniHeroVideo from "../../../assets/treated/chladni-hero.webm";
  import LoadingView from "./LoadingView.svelte";
  import Button from "../components/Button.svelte";
  import Arrow from "../components/Arrow.svelte";
  import ColorSwatch from "../components/ColorSwatch.svelte";
  import AnalysisLimits from "../components/AnalysisLimits.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import type { ListeningPeriod } from "../api/types";

  export let username = "";
  export let period: ListeningPeriod = "1month";
  export let periods: { value: ListeningPeriod; label: string }[] = [];
  export let formError = "";
  export let loading = false;
  export let loadingTitle = "Lendo seu histórico.";
  export let loadingDescription = "As primeiras relações estão sendo reunidas.";
  export let loadingDetail = "Consultando o Last.fm";
  export let onUsernameChange: (value: string) => void = () => undefined;
  export let onPeriodChange: (value: ListeningPeriod) => void = () => undefined;
  export let onSubmit: () => void = () => undefined;
  export let onExample: () => void = () => undefined;

  const accentSwatches = [
    { color: "#D76F78", label: "Accent forte" },
    { color: "#F29191", label: "Accent principal" },
    { color: "#FFB8B8", label: "Accent suave" },
  ];

  let heroVideo: HTMLVideoElement;
  let videoPlaying = false;
  let videoStarted = false;
  let videoFailed = false;

  $: if (
    heroVideo &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches
  )
    playHero();

  function submitProfile(): void {
    if (loading) return;
    onSubmit();
  }

  function playHero(): void {
    if (!heroVideo || videoFailed) return;
    void heroVideo
      .play()
      .then(() => {
        videoStarted = true;
      })
      .catch(() => {
        videoPlaying = false;
      });
  }
  function toggleHero(): void {
    if (!heroVideo || videoFailed) return;
    if (videoPlaying) {
      heroVideo.pause();
      videoPlaying = false;
      return;
    }
    playHero();
  }
  function handlePlaying(): void {
    videoStarted = true;
    videoPlaying = true;
  }
  function handleVideoError(): void {
    videoFailed = true;
    videoPlaying = false;
    videoStarted = false;
  }
</script>

<section
  class:loading
  class="entry-view"
  aria-labelledby="entry-title"
  aria-busy={loading}
>
  <div class="entry-intro">
    <h1 id="entry-title" class="entry-tagline">
      Descubra do que <span>sua escuta é feita.</span>
    </h1>
    <p class="entry-description">
      Uma paleta de cores para os instrumentos documentados nas músicas que você
      ouviu.
    </p>
  </div>

  <div class="entry-stage">
    <div class="hero-frame">
      <img
        src={chladniHeroImage}
        alt="Experimento histórico de Chladni tratado em duotone rosa e preto"
      />
      <video
        bind:this={heroVideo}
        class:visible={videoStarted}
        muted
        loop
        playsinline
        preload="metadata"
        poster={chladniHeroImage}
        aria-hidden="true"
        on:playing={handlePlaying}
        on:error={handleVideoError}
      >
        <source src={chladniHeroVideo} type="video/webm" />
      </video>
    </div>
    <div class="hero-controls">
      <div
        class="hero-palette"
        role="group"
        aria-label="Variações do accent do projeto"
      >
        {#each accentSwatches as swatch}
          <ColorSwatch
            color={swatch.color}
            label={swatch.label}
            className="hero-swatch"
          />
        {/each}
      </div>
      <button
        class:playing={videoPlaying}
        class="hero-play"
        type="button"
        disabled={videoFailed}
        aria-label={videoPlaying ? "Pausar vídeo" : "Reproduzir vídeo"}
        on:click={toggleHero}
      >
        {#if videoPlaying}
          Reproduzindo <span aria-hidden="true">||</span>
        {:else}
          Reproduzir <span aria-hidden="true">&gt;</span>
        {/if}
      </button>
    </div>
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
          <label for="username">Seu perfil do Last.fm</label>
          <button
            class="example-button"
            type="button"
            disabled={loading}
            aria-label="Ver uma escuta de exemplo"
            on:click={onExample}
          >
            Ver exemplo<Arrow direction="right" />
          </button>
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
            placeholder="nome de usuário"
            aria-invalid={formError ? "true" : undefined}
            aria-errormessage={formError ? "profile-error" : undefined}
            required
            maxlength="64"
          />
        </div>
      </div>
      <div class="form-row">
        <div class="field-block period-field">
          <span class="field-label">Período</span>
          <SegmentedControl
            label="Período de escuta"
            options={periods}
            value={period}
            onChange={(value) => onPeriodChange(value as ListeningPeriod)}
          />
        </div>
        <Button variant="primary" type="submit" terminalHover>Buscar</Button>
      </div>
      {#if formError}<p id="profile-error" class="form-error" role="alert">{formError}</p>{/if}
    </form>
    {#if loading}
      <LoadingView
        title={loadingTitle}
        description={loadingDescription}
        detail={loadingDetail}
      />
    {/if}
  </div>

  <div class="entry-limits"><AnalysisLimits /></div>
</section>

<style>
  .entry-view {
    --entry-width: 520px;
    display: grid;
    align-content: center;
    justify-items: center;
    gap: 20px;
    min-height: 0;
    padding: 28px 0 16px;
  }
  .entry-intro,
  .entry-stage,
  .entry-action-area,
  .entry-limits {
    width: min(100%, var(--entry-width));
  }
  .entry-intro {
    display: grid;
    justify-items: center;
    gap: 12px;
    text-align: center;
  }
  .entry-tagline {
    margin: 0;
    color: var(--ink);
    font-size: clamp(1.75rem, 2.4vw, 2rem);
    font-weight: 500;
    letter-spacing: -0.035em;
    line-height: 1.12;
  }
  .entry-tagline span { display: block; }
  .entry-description {
    max-width: 46ch;
    margin: 0;
    color: var(--muted);
    font-size: 15px;
    line-height: 1.5;
    text-wrap: pretty;
  }
  .entry-stage,
  .entry-action-area { position: relative; }
  .hero-frame {
    position: relative;
    width: 100%;
    aspect-ratio: 16 / 9;
    overflow: hidden;
    border: 1px solid var(--line-strong);
    background: var(--paper);
  }
  .hero-frame img,
  .hero-frame video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .hero-frame video {
    opacity: 0;
    transition: opacity 260ms ease;
  }
  .hero-frame video.visible { opacity: 1; }
  .hero-controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 8px;
    min-height: 24px;
  }
  .hero-palette {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .hero-palette :global(.hero-swatch) {
    width: 12px;
    height: 12px;
    min-height: 12px;
    border: 1px solid var(--line-strong);
  }
  .hero-palette :global(.hero-swatch:hover),
  .hero-palette :global(.hero-swatch:focus-visible) {
    outline-offset: 2px;
  }
  .hero-play {
    font-family: var(--meta);
    font-size: 11px;
    letter-spacing: 0.04em;
  }
  .hero-play {
    padding: 4px 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    text-transform: uppercase;
  }
  .hero-play span { margin-left: 6px; }
  .hero-play:hover:not(:disabled),
  .hero-play:focus-visible { color: var(--ink); }
  .hero-play:disabled { cursor: default; opacity: 0.6; }
  .profile-form { width: 100%; }
  .loading .profile-form { visibility: hidden; }
  .field-block { display: grid; gap: 8px; }
  .field-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
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
    min-height: 24px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--meta);
    font-size: 12px;
    white-space: nowrap;
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
  }
  .username-field:focus-within {
    border-color: var(--accent-soft);
    outline: 1px solid var(--accent-soft);
    outline-offset: 2px;
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
    gap: 20px;
    margin-top: 20px;
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
    gap: 6px;
    min-height: 36px;
    border-color: var(--line-strong);
  }
  .period-field :global(.segment-button[data-state="checked"]) {
    border-color: var(--accent-soft);
    background: var(--accent-soft);
    color: var(--on-accent-soft);
  }
  .period-field :global(.segment-button:hover:not([data-state="checked"])) {
    border-color: var(--accent-soft);
    color: var(--ink);
    background: var(--panel);
  }
  .form-row :global(.ui-button) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    min-height: 44px;
  }
  .form-error {
    margin: 16px 0 0;
    color: var(--accent-soft);
    font-family: var(--meta);
    font-size: 13px;
    line-height: 1.5;
  }
  .entry-limits { margin-top: -8px; }
  @media (max-width: 800px) {
    .entry-view { gap: 24px; padding: 32px 0 16px; }
    .entry-description { font-size: 14px; }
  }
  @media (max-width: 380px) {
    .field-heading { align-items: flex-start; gap: 8px; }
    .field-block label { max-width: 17ch; }
    .username-prefix { padding-inline: 10px; font-size: 11px; }
    input { padding-inline: 10px; font-size: 14px; }
    .period-field :global(.segment-button) { padding-inline: 4px; font-size: 11px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .hero-frame video { transition: none; }
  }
</style>
