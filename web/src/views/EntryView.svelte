<script lang="ts">
  import chladniHeroImage from "../../../assets/treated/chladni-hero.png";
  import chladniHeroVideo from "../../../assets/treated/chladni-hero.webm";
  import LoadingView from "./LoadingView.svelte";
  import Button from "../components/Button.svelte";
  import Arrow from "../components/Arrow.svelte";
  import ColorSwatch from "../components/ColorSwatch.svelte";
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
    <p id="entry-title" class="entry-tagline">
      Descubra do que sua escuta é feita.
    </p>
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
          Reproduzindo <span aria-hidden="true">Ⅱ</span>
        {:else}
          Reproduzir <span aria-hidden="true">▷</span>
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
            Ver exemplo<Arrow direction="up-right" />
          </button>
        </div>
        <div class="username-field">
          <span id="username-prefix" class="username-prefix"
            >www.last.fm/user/</span
          >
          <input
            id="username"
            aria-describedby="username-prefix"
            value={username}
            on:input={(event) => onUsernameChange(event.currentTarget.value)}
            autocomplete="username"
            spellcheck="false"
            placeholder="nome de usuário"
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
      {#if formError}<p class="form-error" role="alert">{formError}</p>{/if}
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
    align-content: center;
    justify-items: center;
    gap: clamp(12px, 2.4svh, 24px);
    min-height: 0;
    padding: 32px 4px 12px;
    overflow: visible;
  }
  .entry-intro {
    display: grid;
    gap: 4px;
    width: min(100%, 680px);
    text-align: center;
  }
  .entry-description {
    margin: 0;
    color: var(--muted);
    font-size: clamp(13px, 1.2vw, 15px);
    line-height: 1.45;
  }
  .entry-stage {
    position: relative;
    display: grid;
    justify-items: center;
    width: min(100%, 680px);
  }
  .hero-frame {
    position: relative;
    width: 100%;
    aspect-ratio: 16/9;
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
  .hero-frame video.visible {
    opacity: 1;
  }
  .hero-controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    margin-top: 8px;
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
    justify-self: end;
    padding: 2px 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--meta);
    font-size: 12px;
    letter-spacing: 0.065em;
    text-transform: uppercase;
  }
  .hero-play span {
    margin-left: 5px;
    color: var(--accent-soft);
  }
  .hero-play:hover:not(:disabled),
  .hero-play:focus-visible {
    color: var(--accent-soft);
  }
  .hero-play.playing {
    color: var(--accent-soft);
  }
  .hero-play:disabled {
    color: var(--quiet);
    cursor: default;
    opacity: 0.75;
  }
  .entry-tagline {
    margin: 0;
    color: var(--ink);
    font-size: 1rem;
    line-height: 1.5;
  }
  .entry-action-area {
    position: relative;
    width: min(100%, 680px);
  }
  .profile-form {
    width: 100%;
  }
  .loading .profile-form {
    visibility: hidden;
  }
  .field-block {
    display: grid;
    gap: 8px;
  }
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
    font-size: 13px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .example-button {
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--meta);
    font-size: 12px;
    letter-spacing: 0.04em;
    white-space: nowrap;
  }
  .example-button:hover:not(:disabled),
  .example-button:focus-visible {
    color: var(--accent-soft);
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .example-button:disabled {
    cursor: not-allowed;
    opacity: 0.62;
  }
  .username-field {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    border: 1px solid var(--line-strong);
  }
  .username-field:focus-within {
    border-color: var(--accent-soft);
  }
  .username-prefix {
    padding: 12px 14px 13px;
    border-right: 1px solid var(--line);
    color: var(--muted);
    font-family: var(--meta);
    font-size: 13px;
    white-space: nowrap;
  }
  input {
    width: 100%;
    padding: 12px 14px 13px;
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
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 24px;
    align-items: end;
    margin-top: 25px;
  }
  .form-error {
    margin: 16px 0 0;
    color: var(--accent-soft);
    font-family: var(--meta);
    font-size: 13px;
    line-height: 1.5;
  }
  @media (min-width: 801px) {
    .entry-stage,
    .entry-action-area {
      width: min(100%, 680px, max(320px, calc((100svh - 640px) * 16 / 9)));
    }
  }
  @media (max-width: 800px) {
    .entry-view {
      gap: clamp(12px, 2svh, 18px);
      padding: 28px 0 20px;
    }
    .entry-stage,
    .profile-form {
      width: 100%;
    }
    .entry-description {
      max-width: 40ch;
      margin-inline: auto;
      font-size: 13px;
    }
    .username-field {
      grid-template-columns: 1fr;
      border: 0;
      border-bottom: 1px solid var(--line-strong);
    }
    .username-prefix {
      padding: 0 0 2px;
      border: 0;
    }
    .username-field input {
      padding: 4px 0 13px;
    }
    .form-row {
      grid-template-columns: 1fr;
      gap: 20px;
    }
    .form-row :global(.ui-button) {
      width: 100%;
    }
  }
  @media (max-height: 700px) {
    .entry-view {
      gap: 8px;
      padding: 18px 0 6px;
    }
    .entry-intro {
      gap: 2px;
    }
    .entry-tagline {
      font-size: 14px;
      line-height: 1.3;
    }
    .entry-description {
      font-size: 12px;
      line-height: 1.3;
    }
    .entry-stage,
    .entry-action-area {
      width: min(100%, 680px);
    }
    .hero-controls {
      margin-top: 4px;
    }
    .field-block {
      gap: 4px;
    }
    .form-row {
      margin-top: 12px;
    }
  }
  @media (max-width: 800px) and (max-height: 700px) {
    .entry-view {
      padding-top: 14px;
      padding-bottom: 4px;
    }
    .username-field {
      grid-template-columns: auto minmax(0, 1fr);
      border: 1px solid var(--line-strong);
    }
    .username-prefix {
      padding: 8px 9px;
      border-right: 1px solid var(--line);
      white-space: nowrap;
    }
    .username-field input {
      min-width: 0;
      padding: 8px 9px;
    }
    .form-row {
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: end;
    }
    .form-row :global(.ui-button) {
      width: auto;
    }
    .period-field {
      min-width: 0;
    }
    .period-field :global(.segmented-control) {
      gap: 4px;
    }
    .period-field :global(.segment-button) {
      min-height: 28px;
      padding-inline: 6px;
      font-size: 11px;
    }
  }
  @media (min-width: 801px) and (max-height: 700px) {
    .hero-frame {
      height: clamp(72px, 15svh, 108px);
      aspect-ratio: auto;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .hero-frame video {
      transition: none;
    }
  }
</style>
