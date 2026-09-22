<script lang="ts">
  import flowerIntroImage from "../../../assets/treated/flower-intro.png";
  import flowerIntroVideo from "../../../assets/treated/flower-intro.webm";
  import flowerLoadingVideo from "../../../assets/treated/flower-loading.webm";
  import LoadingView from "./LoadingView.svelte";
  import Button from "../components/Button.svelte";
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

  const accentSwatches = [
    { color: "#D76F78", label: "Accent forte" },
    { color: "#F29191", label: "Accent principal" },
    { color: "#FFB8B8", label: "Accent suave" },
  ];

  let video: HTMLVideoElement;
  let videoPlaying = false;
  let videoStarted = false;
  let videoFailed = false;
  let loadingVideo: HTMLVideoElement | undefined;
  let loadingVideoPlaying = false;
  let loadingVideoStarted = false;

  $: if (video) {
    if (loading) {
      video.pause();
      videoPlaying = false;
    } else if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches)
      playIntro();
  }

  function startLoadingVideo(node: HTMLVideoElement) {
    loadingVideo = node;
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      void node.play().catch(() => {
        loadingVideoPlaying = false;
      });
    }
    return {
      destroy() {
        node.pause();
        loadingVideo = undefined;
        loadingVideoPlaying = false;
        loadingVideoStarted = false;
      },
    };
  }

  function submitProfile(): void {
    if (loading) return;
    onSubmit();
  }

  function playIntro(): void {
    if (!video || videoFailed) return;
    void video
      .play()
      .then(() => {
        videoStarted = true;
      })
      .catch(() => {
        videoPlaying = false;
      });
  }
  function toggleIntro(): void {
    if (loading) {
      if (!loadingVideo) return;
      if (loadingVideoPlaying) loadingVideo.pause();
      else
        void loadingVideo.play().catch(() => {
          loadingVideoPlaying = false;
        });
      return;
    }
    if (!video || videoFailed) return;
    if (videoPlaying) {
      video.pause();
      videoPlaying = false;
      return;
    }
    playIntro();
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
  <p id="entry-title" class="entry-tagline">
    Duas leituras instrumentais da sua escuta.
  </p>

  <div class="entry-stage">
    <div class="intro-frame">
      <img
        src={flowerIntroImage}
        alt="Flores tratadas em duotone rosa e preto"
      />
      <video
        bind:this={video}
        class:visible={videoStarted}
        muted
        loop
        playsinline
        preload="metadata"
        poster={flowerIntroImage}
        aria-hidden="true"
        on:playing={handlePlaying}
        on:error={handleVideoError}
      >
        <source src={flowerIntroVideo} type="video/webm" />
      </video>
      {#if loading}
        <video
          use:startLoadingVideo
          class="loading-video"
          class:visible={loadingVideoStarted}
          muted
          loop
          playsinline
          preload="auto"
          aria-hidden="true"
          on:playing={() => {
            loadingVideoPlaying = true;
            loadingVideoStarted = true;
          }}
          on:pause={() => (loadingVideoPlaying = false)}
          on:error={() => {
            loadingVideoPlaying = false;
            loadingVideoStarted = false;
          }}
        >
          <source src={flowerLoadingVideo} type="video/webm" />
        </video>
      {/if}
    </div>
    <div class="intro-controls">
      <div
        class="intro-palette"
        role="group"
        aria-label="Variações do accent do projeto"
      >
        {#each accentSwatches as swatch}<ColorSwatch
            color={swatch.color}
            label={swatch.label}
            className="intro-swatch"
          />{/each}
      </div>
      <button
        class:playing={loading ? loadingVideoPlaying : videoPlaying}
        class="intro-play"
        type="button"
        disabled={loading ? !loadingVideo : videoFailed}
        aria-label={(loading ? loadingVideoPlaying : videoPlaying)
          ? "Pausar vídeo"
          : "Reproduzir vídeo"}
        on:click={toggleIntro}
      >
        {(loading ? loadingVideoPlaying : videoPlaying)
          ? "Reproduzindo"
          : "Reproduzir"}{#if loading ? loadingVideoPlaying : videoPlaying}<span
            aria-hidden="true">Ⅱ</span
          >{:else}<span aria-hidden="true">▷</span>{/if}
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
        <label for="username">Seu perfil do Last.fm</label>
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
    gap: 26px;
    min-height: 0;
    padding: 18px 4px;
    overflow: visible;
  }
  .entry-stage {
    position: relative;
    display: grid;
    justify-items: center;
    width: min(100%, 680px);
  }
  .intro-frame {
    position: relative;
    width: 100%;
    aspect-ratio: 16/9;
    overflow: hidden;
    border: 1px solid var(--line-strong);
    background: var(--paper);
  }
  .intro-frame img,
  .intro-frame video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .intro-frame video {
    opacity: 0;
    transition: opacity 260ms ease;
  }
  .intro-frame video.visible {
    opacity: 1;
  }
  .intro-controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    margin-top: 8px;
  }
  .intro-palette {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .intro-palette :global(.intro-swatch) {
    width: 12px;
    height: 12px;
    min-height: 12px;
    border: 1px solid var(--line-strong);
  }
  .intro-palette :global(.intro-swatch:hover),
  .intro-palette :global(.intro-swatch:focus-visible) {
    outline-offset: 2px;
  }
  .intro-play {
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
  .intro-play span {
    margin-left: 5px;
    color: var(--accent);
  }
  .intro-play:hover:not(:disabled),
  .intro-play:focus-visible {
    color: var(--accent-soft);
  }
  .intro-play.playing {
    color: var(--accent);
  }
  .intro-play:disabled {
    color: var(--quiet);
    cursor: default;
    opacity: 0.75;
  }
  .entry-tagline {
    margin: 0;
    color: var(--muted);
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
  .loading .intro-frame > video:not(.loading-video) {
    opacity: 0;
  }
  .field-block {
    display: grid;
    gap: 8px;
  }
  .field-block label,
  .field-label {
    color: var(--muted);
    font-family: var(--meta);
    font-size: 13px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
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
    grid-template-columns: minmax(112px, 0.75fr) 1fr;
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
    .entry-stage {
      width: min(100%, 680px, max(320px, calc((100svh - 530px) * 16 / 9)));
    }
  }
  @media (max-width: 800px) {
    .entry-view {
      padding: 24px 0 30px;
    }
    .entry-stage,
    .profile-form {
      width: 100%;
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
  @media (prefers-reduced-motion: reduce) {
    .intro-frame video {
      transition: none;
    }
  }
</style>
