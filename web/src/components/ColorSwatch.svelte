<script lang="ts">
  import { Popover } from "bits-ui";

  export let color: string;
  export let label = "Cor da paleta";
  export let className = "";
  export let style = "";
  export let presenceName = "";

  let copied = false;
  let copyFailed = false;
  let trigger: HTMLButtonElement | null = null;
  let copiedTimer: ReturnType<typeof setTimeout> | undefined;

  $: hex = normalizeHex(color);

  function normalizeHex(value: string): string {
    const normalized = value.trim().replace(/^#/, "");
    if (/^[0-9a-f]{3}$/i.test(normalized)) {
      return `#${normalized
        .split("")
        .map((part) => part + part)
        .join("")
        .toUpperCase()}`;
    }
    return /^[0-9a-f]{6}$/i.test(normalized)
      ? `#${normalized.toUpperCase()}`
      : value;
  }

  async function copyColor(): Promise<void> {
    copyFailed = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(hex);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = hex;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        try {
          if (!document.execCommand("copy")) throw new Error("copy failed");
        } finally {
          textarea.remove();
        }
      }
      copied = true;
      if (copiedTimer) clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => {
        copied = false;
      }, 1800);
    } catch {
      copied = false;
      copyFailed = true;
      if (copiedTimer) clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => {
        copyFailed = false;
      }, 2400);
    }
  }

  function alignStem(node: HTMLDivElement) {
    const content = node.parentElement!;
    const wrapper = content.parentElement!;
    if (!trigger) return;
    const triggerElement = trigger as HTMLButtonElement;
    function update() {
      const anchor = triggerElement.getBoundingClientRect();
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
    resize.observe(triggerElement);
    update();
    return {
      destroy() {
        observer.disconnect();
        resize.disconnect();
        if (copiedTimer) clearTimeout(copiedTimer);
      },
    };
  }
</script>

<Popover.Root>
  <Popover.Trigger
    bind:ref={trigger}
    class={`color-swatch ${className}`}
    style={`--swatch-color:${color};${style}`}
    aria-label={`${label}: ${hex}. Abrir detalhes da cor`}
  >
    <span class="visually-hidden">{label}: {hex}</span>
  </Popover.Trigger>
  <Popover.Portal>
    <Popover.Content
      class="color-popover"
      side="bottom"
      align="center"
      sideOffset={12}
      collisionPadding={12}
      aria-label={`Detalhes de ${label}`}
    >
      <div use:alignStem>
        {#if presenceName}
          <span class="color-popover-name">{presenceName}</span>
        {:else}<span
            class="color-preview"
            style={`background:${color}`}
            aria-hidden="true"
          ></span>{/if}
        <span class="color-popover-hex">{hex}</span>
        <button
          type="button"
          class="color-copy"
          aria-label={`Copiar código ${hex}`}
          onclick={copyColor}
          >{copied
            ? "Código copiado"
            : copyFailed
              ? "Falha ao copiar"
              : "Copiar código"}</button
        >
      </div>
    </Popover.Content>
  </Popover.Portal>
</Popover.Root>

<style>
  :global(.color-swatch) {
    display: block;
    width: 100%;
    height: 100%;
    min-height: 24px;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: var(--swatch-color);
    cursor: copy;
  }
  :global(.composition-swatch) {
    flex-basis: 0;
    min-width: 0;
  }
  :global(.share-swatch) {
    min-height: 0;
  }
  :global(.color-swatch:hover),
  :global(.color-swatch:focus-visible),
  :global(.color-swatch[data-state="open"]) {
    outline: 2px solid var(--ink);
    outline-offset: -2px;
  }
  :global(.color-popover) {
    position: relative;
    z-index: 40;
    min-width: 132px;
    max-width: calc(100vw - 24px);
    padding: 12px;
    border: 1px solid var(--line-strong);
    border-radius: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: var(--meta);
    font-size: 12px;
    line-height: 1.5;
    box-shadow: none;
  }
  :global(.color-popover > div) {
    display: grid;
    justify-items: center;
    gap: 8px;
  }
  :global(.color-popover-name) {
    font-size: 13px;
  }
  :global(.color-preview) {
    display: block;
    width: 18px;
    height: 18px;
    border: 1px solid var(--line-strong);
  }
  :global(.color-popover-hex) {
    color: var(--muted);
  }
  :global(.color-copy) {
    width: 100%;
    padding: 5px 8px;
    border: 1px solid var(--line-strong);
    border-radius: 2px;
    background: transparent;
    color: var(--ink);
    font: 11px var(--meta);
    cursor: pointer;
  }
  :global(.color-copy:hover),
  :global(.color-copy:focus-visible) {
    border-color: var(--accent-soft);
    color: var(--accent-soft);
  }
  :global(.color-popover::before) {
    position: absolute;
    left: var(--stem-x, 50%);
    width: 1px;
    height: 12px;
    background: var(--line-strong);
    content: "";
    pointer-events: none;
  }
  :global(.color-popover[data-side="bottom"]::before) {
    bottom: 100%;
  }
  :global(.color-popover[data-side="top"]::before) {
    top: 100%;
  }
</style>
