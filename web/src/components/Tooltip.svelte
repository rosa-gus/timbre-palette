<script lang="ts">
  import { Tooltip as BitsTooltip } from "bits-ui";

  export let frozen = false;
  export let anchor: HTMLElement | null = null;
  export let triggerLabel = "[?]";
  export let ariaLabel = "Abrir explicação";
  export let closeLabel = "Fechar aviso";
  export let side: "top" | "right" | "bottom" | "left" = "bottom";
  export let align: "start" | "center" | "end" = "end";
  export let sideOffset = 18;
  export let collisionPadding = 16;
  export let onClose: () => void = () => undefined;

  let open = false;
  let trigger: HTMLElement | null = null;
  let dismissed = false;

  $: if (frozen && !dismissed) open = true;

  function alignStem(node: HTMLDivElement) {
    const content = node.parentElement!;
    const wrapper = content.parentElement!;
    function update() {
      const target = anchor ?? trigger;
      if (!target) return;
      const targetBox = target.getBoundingClientRect();
      const box = content.getBoundingClientRect();
      const stemTarget =
        anchor && align === "end"
          ? targetBox.right
          : anchor && align === "start"
            ? targetBox.left
            : targetBox.left + targetBox.width / 2;
      const stemX = Math.max(
        16,
        Math.min(box.width - 16, stemTarget - box.left),
      );
      content.style.setProperty("--stem-x", `${stemX}px`);
    }

    // Floating positioning can shift the panel at the viewport edges.
    const observer = new MutationObserver(update);
    observer.observe(wrapper, { attributes: true, attributeFilter: ["style"] });
    const resize = new ResizeObserver(update);
    resize.observe(content);
    const target = anchor ?? trigger;
    if (target) resize.observe(target);
    update();
    return {
      destroy() {
        observer.disconnect();
        resize.disconnect();
      },
    };
  }

  function onPointerDown(event: PointerEvent) {
    if (event.pointerType !== "touch") return;
    event.preventDefault();
    open = !open;
  }

  function close() {
    dismissed = true;
    open = false;
    onClose();
  }

  function handleInteractOutside(event: PointerEvent) {
    if (frozen) event.preventDefault();
  }

  function handleEscapeKeydown(event: KeyboardEvent) {
    if (!frozen) return;
    event.preventDefault();
    close();
  }
</script>

<BitsTooltip.Provider delayDuration={200}>
  <BitsTooltip.Root bind:open disableCloseOnTriggerClick>
    {#if frozen && !anchor}
      <span
        bind:this={trigger}
        class="tooltip-anchor"
        aria-hidden="true"
      ></span>
    {:else if !frozen}
      <BitsTooltip.Trigger
        bind:ref={trigger}
        class="tooltip-trigger"
        aria-label={ariaLabel}
        onpointerdown={onPointerDown}>{triggerLabel}</BitsTooltip.Trigger
      >
    {/if}
    <BitsTooltip.Content
      class={frozen ? "app-tooltip app-tooltip-frozen" : "app-tooltip"}
      {side}
      {align}
      {sideOffset}
      {collisionPadding}
      customAnchor={frozen ? anchor ?? trigger : undefined}
      onInteractOutside={handleInteractOutside}
      onEscapeKeydown={handleEscapeKeydown}
    >
      <div use:alignStem>
        <slot />
        {#if frozen}
          <button
            class="tooltip-close"
            type="button"
            aria-label={closeLabel}
            on:click={close}>×</button
          >
        {/if}
      </div>
    </BitsTooltip.Content>
  </BitsTooltip.Root>
</BitsTooltip.Provider>

<style>
  :global(.tooltip-trigger) {
    padding: 2px 3px;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: var(--muted);
    font-family: var(--meta);
    font-size: 12px;
    line-height: 1.5;
    cursor: help;
    vertical-align: baseline;
  }
  :global(.tooltip-trigger:hover),
  :global(.tooltip-trigger[data-state="delayed-open"]),
  :global(.tooltip-trigger[data-state="instant-open"]) {
    color: var(--ink);
  }
  :global(.app-tooltip) {
    position: relative;
    z-index: 20;
    width: min(320px, calc(100vw - 32px));
    padding: 16px;
    border: 1px solid var(--line-strong);
    border-radius: 0;
    background: var(--paper);
    color: var(--muted);
    font-family: var(--display);
    font-size: 13px;
    line-height: 1.6;
    box-shadow: none;
  }
  :global(.app-tooltip-frozen) {
    padding-top: 36px;
  }
  :global(.app-tooltip::before) {
    position: absolute;
    left: var(--stem-x, 50%);
    width: 1px;
    height: 18px;
    background: var(--line-strong);
    content: "";
    pointer-events: none;
  }
  :global(.app-tooltip[data-side="bottom"]::before) {
    bottom: 100%;
  }
  :global(.app-tooltip[data-side="top"]::before) {
    top: 100%;
  }
  :global(.tooltip-close) {
    position: absolute;
    top: 5px;
    right: 7px;
    display: grid;
    width: 24px;
    height: 24px;
    padding: 0;
    place-items: center;
    border: 1px solid transparent;
    border-radius: 0;
    background: transparent;
    color: var(--muted);
    font: 20px/1 var(--meta);
    cursor: pointer;
  }
  :global(.tooltip-close:hover),
  :global(.tooltip-close:focus-visible) {
    border-color: var(--line-strong);
    color: var(--ink);
  }
  :global(.tooltip-anchor) {
    display: inline-block;
    width: 1px;
    height: 1px;
  }
  :global(.app-tooltip p) {
    margin: 0;
  }
  :global(.app-tooltip p + p) {
    margin-top: 12px;
  }
  :global(.app-tooltip .tooltip-note) {
    display: flex;
    align-items: baseline;
    gap: 8px;
    color: var(--ink);
    font-family: var(--meta);
    font-size: 12px;
  }
</style>
