<script lang="ts">
  import Arrow from "./Arrow.svelte";

  export let variant: "primary" | "secondary" | "text" | "icon" = "text";
  export let type: "button" | "submit" = "button";
  export let disabled = false;
  export let terminalHover = false;
  export let ariaLabel: string | undefined = undefined;
</script>

<button
  class={`ui-button ui-button--${variant}`}
  class:ui-button--terminal={terminalHover}
  {type}
  {disabled}
  aria-label={ariaLabel}
  on:click
>
  <slot />
  {#if terminalHover}
    <span class="terminal-symbol" aria-hidden="true">
      <span class="terminal-arrow"><Arrow direction="right" /></span>
    </span>
  {/if}
</button>

<style>
  .ui-button {
    border: 1px solid transparent;
    border-radius: 0;
    background: transparent;
    cursor: pointer;
    letter-spacing: 0.04em;
    transition:
      border-color 150ms ease,
      background-color 150ms ease,
      color 150ms ease;
  }
  .ui-button:disabled {
    cursor: wait;
    opacity: 0.48;
  }
  .ui-button--primary {
    min-height: 44px;
    padding: 0 18px;
    border-color: var(--accent);
    background: var(--accent);
    color: #000;
    font-family: var(--meta);
    font-size: 13px;
    text-transform: uppercase;
  }
  .ui-button--primary:hover,
  .ui-button--primary:focus-visible {
    border-color: var(--accent-soft);
    background: var(--accent-soft);
    color: var(--on-accent-soft);
  }
  .ui-button--terminal,
  .ui-button--terminal:hover,
  .ui-button--terminal:focus-visible {
    border-color: var(--accent);
    background: var(--accent);
    color: #000;
  }
  .terminal-symbol {
    display: inline-grid;
    width: 1em;
    margin-left: 0.55em;
    line-height: 1;
    vertical-align: -0.08em;
    place-items: center;
  }
  .terminal-arrow,
  .terminal-symbol::after {
    grid-area: 1 / 1;
  }
  .terminal-arrow :global(.icon-arrow) { margin: 0; }
  .terminal-symbol::after { content: ""; }
  .ui-button--terminal:is(:hover, :focus-visible):not(:disabled) .terminal-arrow {
    animation: terminal-arrow 800ms step-end infinite;
  }
  .ui-button--terminal:is(:hover, :focus-visible):not(:disabled) .terminal-symbol::after {
    animation: terminal-characters 800ms step-end infinite;
  }
  @keyframes terminal-arrow {
    0%, 49.99% { opacity: 1; }
    50%, 100% { opacity: 0; }
  }
  @keyframes terminal-characters {
    0%, 49.99% { content: ""; }
    50%, 100% { content: "*"; }
  }
  @media (prefers-reduced-motion: reduce) {
    .ui-button--terminal:is(:hover, :focus-visible):not(:disabled) .terminal-arrow,
    .ui-button--terminal:is(:hover, :focus-visible):not(:disabled) .terminal-symbol::after {
      animation: none;
    }
  }
  .ui-button--secondary {
    min-height: 40px;
    padding: 0 14px;
    border-color: var(--line-strong);
    color: var(--muted);
    font-family: var(--meta);
    font-size: 13px;
    text-transform: uppercase;
  }
  .ui-button--secondary:hover,
  .ui-button--secondary:focus-visible {
    border-color: var(--accent-soft);
    color: var(--accent-pale);
  }
  .ui-button--text {
    padding: 0 0 8px;
    color: var(--accent-soft);
    font-family: var(--meta);
    font-size: 13px;
    text-transform: uppercase;
  }
  .ui-button--text:hover {
    color: var(--accent-pale);
  }
  .ui-button--icon {
    width: 34px;
    height: 34px;
    border-color: var(--line);
    color: var(--muted);
    font-size: 20px;
    line-height: 1;
  }
  .ui-button--icon:hover {
    border-color: var(--accent-soft);
    background: var(--accent-soft);
    color: var(--on-accent-soft);
  }
</style>
