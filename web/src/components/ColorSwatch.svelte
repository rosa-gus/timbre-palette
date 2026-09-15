<script lang="ts">
  import { Tooltip } from "bits-ui";

  export let color: string;
  export let label = "Cor da paleta";
  export let className = "";
  export let style = "";
  export let presenceName = "";

  let open = false;
  let copied = false;
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
        if (!document.execCommand("copy")) throw new Error("copy failed");
        textarea.remove();
      }
      copied = true;
      open = true;
      if (copiedTimer) clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => {
        copied = false;
      }, 1800);
    } catch {
      copied = false;
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

<Tooltip.Provider delayDuration={180}>
  <Tooltip.Root bind:open disableCloseOnTriggerClick>
    <Tooltip.Trigger
      bind:ref={trigger}
      class={`color-swatch ${className}`}
      style={`--swatch-color:${color};${style}`}
      aria-label={`${label}: ${hex}. Clique para copiar`}
      onclick={copyColor}
    >
      <span class="visually-hidden">{label}: {hex}</span>
    </Tooltip.Trigger>
    <Tooltip.Portal>
      <Tooltip.Content
        class="color-tooltip"
        side="bottom"
        align="center"
        sideOffset={12}
        collisionPadding={12}
      >
        <div use:alignStem>
          {#if presenceName}
            <span>{presenceName}</span>
          {:else}<span
            class="color-preview"
            style={`background:${color}`}
            aria-hidden="true"
          ></span>{/if}
          <span>{copied ? `Copiado ${hex}` : `${hex} · clique para copiar`}</span>
        </div>
      </Tooltip.Content>
    </Tooltip.Portal>
  </Tooltip.Root>
</Tooltip.Provider>

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
  :global(.color-swatch:focus-visible) {
    outline: 2px solid var(--ink);
    outline-offset: -2px;
  }
  :global(.color-tooltip) {
    position: relative;
    z-index: 40;
    padding: 8px 10px;
    border: 1px solid var(--line-strong);
    border-radius: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: var(--meta);
    font-size: 12px;
    line-height: 1.5;
    white-space: nowrap;
    box-shadow: none;
  }
  :global(.color-tooltip > div) {
    display: grid;
    justify-items: center;
    gap: 6px;
  }
  :global(.color-preview) {
    display: block;
    width: 18px;
    height: 18px;
    border: 1px solid var(--line-strong);
  }
  :global(.color-tooltip::before) {
    position: absolute;
    left: var(--stem-x, 50%);
    width: 1px;
    height: 12px;
    background: var(--line-strong);
    content: "";
    pointer-events: none;
  }
  :global(.color-tooltip[data-side="bottom"]::before) {
    bottom: 100%;
  }
  :global(.color-tooltip[data-side="top"]::before) {
    top: 100%;
  }
</style>
