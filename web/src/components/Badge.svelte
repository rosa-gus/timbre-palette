<script lang="ts">
  export let tone: "neutral" | "accent" | "quiet" = "neutral";
</script>

<span class={`ui-badge ui-badge--${tone}`}><slot /></span>

<style>
  .ui-badge {
    display: inline-flex;
    align-items: center;
    min-height: 18px;
    padding: 2px 6px;
    border: 1px solid var(--line-strong);
    color: var(--muted);
    font-family: var(--meta);
    font-size: 12px;
    font-weight: 400;
    letter-spacing: 0.04em;
    line-height: 1.2;
    text-transform: none;
    vertical-align: middle;
  }
  .ui-badge--accent {
    border-color: var(--accent-soft);
    color: var(--accent-soft);
  }
  .ui-badge--quiet {
    border-color: var(--line);
    color: var(--quiet);
  }
</style>
