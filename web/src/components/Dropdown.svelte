<script lang="ts">
  export let title: string;
  export let align: "start" | "end" = "start";
</script>

<details class={`ui-dropdown ui-dropdown--${align}`}>
  <summary>{title}</summary>
  <div class="dropdown-content"><slot /></div>
</details>

<style>
  .ui-dropdown {
    color: var(--muted);
  }
  summary {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 44px;
    width: fit-content;
    padding: 10px 0;
    font-family: var(--meta);
    font-size: 12px;
    line-height: 1.5;
    list-style: none;
    cursor: pointer;
  }
  summary::-webkit-details-marker {
    display: none;
  }
  summary::before {
    content: "▸";
    font-size: 18px;
  }
  .ui-dropdown[open] > summary::before {
    content: "▾";
    font-size: 18px;
  }
  .ui-dropdown--end > summary {
    margin-left: auto;
    text-align: end;
  }
  summary:hover {
    color: var(--ink);
  }
  summary:focus-visible {
    outline: 2px solid var(--accent-soft);
    outline-offset: 4px;
  }
  .dropdown-content {
    max-width: 680px;
    border-left: 1px solid var(--line-strong);
    padding: 4px 0 16px 20px;
    font-size: 13px;
    line-height: 1.7;
  }
  .ui-dropdown--end > .dropdown-content {
    margin-left: auto;
    padding: 4px 20px 16px 0;
    border-left: 0;
    border-right: 1px solid var(--line-strong);
    text-align: end;
  }
  .dropdown-content :global(p) {
    margin: 0 0 12px;
  }
  .dropdown-content :global(p:last-child) {
    margin-bottom: 0;
  }
</style>
