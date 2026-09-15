<script lang="ts">
  export let title = "Lendo seu histórico.";
  export let description = "As primeiras relações estão sendo reunidas.";
  export let detail = "Consultando o Last.fm";
</script>

<section class="loading-view" role="status" aria-live="polite">
  <h1>{title}</h1>
  <p class="loading-description">{description}</p>
  <div class="loading-characters" aria-hidden="true">
    [ <span>&amp;</span> <span>*</span> <span>$</span> <span>%</span> ]
  </div>
  <p class="loading-detail">{detail}</p>
</section>

<style>
  .loading-view {
    position: absolute;
    inset: 0;
    overflow: auto;
    animation: appear 240ms ease;
  }
  h1 {
    margin: 0 0 10px;
    font-size: clamp(1.35rem, 2vw, 1.8rem);
    line-height: 1.2;
  }
  .loading-description {
    margin: 0;
    color: var(--muted);
    font-size: 14px;
    line-height: 1.5;
  }
  .loading-characters {
    margin: 18px 0 12px;
    color: var(--muted);
    font-family: var(--meta);
    font-size: 13px;
    line-height: 1.5;
    white-space: pre;
  }
  .loading-characters span {
    color: var(--accent);
    animation: erase-first 2s step-end infinite;
  }
  .loading-characters span:nth-child(2) {
    animation-name: erase-second;
  }
  .loading-characters span:nth-child(3) {
    animation-name: erase-third;
  }
  .loading-characters span:nth-child(4) {
    animation-name: erase-fourth;
  }
  .loading-detail {
    margin: 0;
    color: var(--muted);
    font-family: var(--meta);
    font-size: 11px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  @keyframes erase-first {
    0% {
      opacity: 1;
    }
    20%,
    100% {
      opacity: 0;
    }
  }
  @keyframes erase-second {
    0% {
      opacity: 1;
    }
    40%,
    100% {
      opacity: 0;
    }
  }
  @keyframes erase-third {
    0% {
      opacity: 1;
    }
    60%,
    100% {
      opacity: 0;
    }
  }
  @keyframes erase-fourth {
    0% {
      opacity: 1;
    }
    80%,
    100% {
      opacity: 0;
    }
  }
  @keyframes appear {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .loading-view,
    .loading-characters span {
      animation: none;
    }
  }
</style>
