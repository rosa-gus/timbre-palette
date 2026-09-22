<script lang="ts">
  export let title = "Lendo seu histórico.";
  export let description = "As primeiras relações estão sendo reunidas.";
  export let detail = "Consultando o Last.fm";
</script>

<section class="loading-view" role="status" aria-live="polite">
  <h1>{title}</h1>
  <p class="loading-description">{description}</p>
  <div class="loading-characters" aria-hidden="true">
    <span class="loading-sequence"></span>
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
  .loading-sequence::after {
    color: var(--accent);
    content: "* . . .";
    display: inline-block;
    animation: loading-sequence 1.2s step-end infinite;
  }
  .loading-detail {
    margin: 0;
    color: var(--muted);
    font-family: var(--meta);
    font-size: 11px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  @keyframes loading-sequence {
    0%, 24.99% { content: "* . . ."; }
    25%, 49.99% { content: ". * . ."; }
    50%, 74.99% { content: ". . * ."; }
    75%, 100% { content: ". . . *"; }
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
    .loading-sequence::after {
      animation: none;
      content: "* . . .";
    }
  }
</style>
