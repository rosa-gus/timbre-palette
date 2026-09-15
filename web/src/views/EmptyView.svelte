<script lang="ts">
  import Arrow from "../components/Arrow.svelte";
  import { normalizePathname } from "../navigation";

  const homePath = normalizePathname();
  export let notice = "";
</script>

<section class="empty-view" aria-live="polite">
  <h1>Foi mal, o sistema ainda está meio burro.</h1>
  <p>{notice}</p>
  <a class="retry-link" href={homePath}
    >Tentar outro período <Arrow direction="right" /></a
  >
</section>

<style>
  .retry-link {
    display: inline-flex;
    align-items: center;
    min-height: 40px;
    padding: 0 14px;
    border: 1px solid var(--line-strong);
    color: var(--muted);
    font-family: var(--meta);
    font-size: 13px;
    letter-spacing: .04em;
    text-transform: uppercase;
    text-decoration: none;
  }
  .retry-link:hover,
  .retry-link:focus-visible {
    border-color: var(--accent-soft);
    color: var(--accent-pale);
  }
  .empty-view {
    max-width: 760px;
    margin: auto;
    padding: 10vh 4px;
  }
  h1 {
    margin: 0 0 26px;
    font-size: var(--type-title);
    line-height: 1.12;
  }
  .empty-view > p {
    max-width: 480px;
    margin: 0 0 24px;
    color: var(--muted);
  }
</style>
