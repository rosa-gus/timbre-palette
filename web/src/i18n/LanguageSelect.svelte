<script lang="ts">
  import { Popover } from "bits-ui";
  import { languageNames } from "../../../shared/i18n/locales.mjs";
  import {
    localeStore,
    setLocale,
    supportedLocales,
    translation as t,
    type Locale,
  } from "./runtime";

  let open = false;
  let busy = false;
  let error = "";
  let trigger: HTMLButtonElement | null = null;

  async function change(language: Locale) {
    busy = true;
    error = "";
    try {
      await setLocale(language);
      open = false;
    } catch {
      error = $t("language.failed");
    } finally {
      busy = false;
    }
  }

  function alignStem(node: HTMLDivElement) {
    const content = node.parentElement!;
    const wrapper = content.parentElement!;
    function update() {
      if (!trigger) return;
      const anchor = trigger.getBoundingClientRect();
      const box = content.getBoundingClientRect();
      content.style.setProperty(
        "--stem-x",
        `${anchor.left + anchor.width / 2 - box.left}px`,
      );
    }
    const observer = new MutationObserver(update);
    observer.observe(wrapper, { attributes: true, attributeFilter: ["style"] });
    const resize = new ResizeObserver(update);
    resize.observe(content);
    if (trigger) resize.observe(trigger);
    update();
    return {
      destroy() {
        observer.disconnect();
        resize.disconnect();
      },
    };
  }
</script>

<Popover.Root bind:open>
  <Popover.Trigger
    bind:ref={trigger}
    class="language-badge"
    aria-label={`${$t("language.label")}: ${$localeStore}`}
  >
    {$localeStore}<span aria-hidden="true">{open ? "▴" : "▾"}</span>
  </Popover.Trigger>
  <Popover.Content
    class="language-panel"
    side="bottom"
    align="start"
    sideOffset={18}
    collisionPadding={20}
    aria-label={$t("language.label")}
    aria-busy={busy}
  >
    <div use:alignStem>
      <div class="language-options">
        {#each supportedLocales as language}
          <button
            class="language-option"
            type="button"
            lang={language}
            aria-pressed={$localeStore === language}
            disabled={busy}
            on:click={() => change(language)}
          >
            <span>{languageNames[language]}</span>
            {#if $localeStore === language}<span
                class="language-active"
                aria-hidden="true"
              ></span>{/if}
          </button>
        {/each}
      </div>
      {#if error}<p class="language-error" role="status">{error}</p>{/if}
    </div>
  </Popover.Content>
</Popover.Root>

<style>
  :global(.language-badge) {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 2px 6px;
    border: 1px solid var(--line-strong);
    border-radius: 0;
    background: transparent;
    color: var(--muted);
    font-family: var(--meta);
    font-size: 11px;
    line-height: 1.5;
    white-space: nowrap;
    cursor: pointer;
  }
  :global(.language-badge:hover),
  :global(.language-badge[data-state="open"]) {
    border-color: var(--accent);
    color: var(--ink);
  }
  :global(.language-panel) {
    position: relative;
    z-index: 5;
    width: 260px;
    max-width: calc(100vw - 40px);
    padding: 16px;
    border: 1px solid var(--line-strong);
    border-radius: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: var(--meta);
    font-size: 12px;
    line-height: 1.5;
  }
  :global(.language-panel::before) {
    position: absolute;
    left: var(--stem-x, 50%);
    width: 1px;
    height: 18px;
    background: var(--line-strong);
    content: "";
    pointer-events: none;
  }
  :global(.language-panel[data-side="bottom"]::before) {
    bottom: 100%;
  }
  :global(.language-panel[data-side="top"]::before) {
    top: 100%;
  }
  .language-options {
    display: grid;
    gap: 4px;
  }
  .language-option {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    width: 100%;
    padding: 8px;
    border: 0;
    border-radius: 2px;
    background: transparent;
    color: var(--muted);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .language-option:hover,
  .language-option:focus-visible,
  .language-option[aria-pressed="true"] {
    background: var(--panel);
    color: var(--ink);
  }
  .language-option:focus-visible {
    outline: 1px solid var(--accent);
    outline-offset: -1px;
  }
  .language-option:disabled {
    cursor: wait;
    opacity: 0.65;
  }
  .language-active {
    width: 7px;
    height: 7px;
    flex: 0 0 7px;
    background: var(--accent);
  }
  .language-error {
    margin: 12px 0 0;
    color: var(--ink);
  }
</style>
