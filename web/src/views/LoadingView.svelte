<script lang="ts">
  import { translation as t } from "../i18n/runtime";
  export let title = "";
  export let context = "";
  export let detail = "";
</script>

<section class="loading-view" role="status" aria-live="polite">
  <p class="loading-context">{context}</p>
  <div class="loading-characters" aria-hidden="true">
    <span class="loading-indicator"></span>
  </div>
  <h1 id="loading-title">{title || $t("loading.historyTitle")}</h1>
  <p class="loading-detail">{detail || $t("loading.historyDetail")}</p>
</section>

<style>
  .loading-view {
    width: 100%;
    max-width: 560px;
    min-width: 0;
    text-align: center;
    overflow-wrap: anywhere;
    animation: appear 240ms ease;
  }
  h1 {
    margin: 0 0 10px;
    font-size: clamp(1.35rem, 2vw, 1.8rem);
    line-height: 1.2;
  }
  .loading-context {
    margin: 0;
    color: var(--muted);
    font: 12px/1.6 var(--meta);
    letter-spacing: 0.06em;
  }
  .loading-characters {
    margin: 32px 0;
    color: var(--accent-soft);
    font-family: var(--meta);
    font-size: 22px;
    line-height: 1.5;
    white-space: pre;
  }
  .loading-detail {
    margin: 0;
    color: var(--muted);
    font-family: var(--meta);
    font-size: 12px;
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
  @media (prefers-reduced-motion: reduce) {
    .loading-view {
      animation: none;
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
</style>
