<script lang="ts">
  import { Tooltip } from "bits-ui";

  let open = false;
  let trigger: HTMLButtonElement | null = null;
  export let hydrationPending = false;

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
    // Floating positioning can shift the panel at the viewport edges.
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

  function onPointerDown(event: PointerEvent) {
    if (event.pointerType !== "touch") return;
    event.preventDefault();
    open = !open;
  }
</script>

<Tooltip.Provider delayDuration={200}>
  <Tooltip.Root bind:open disableCloseOnTriggerClick>
    <Tooltip.Trigger
      bind:ref={trigger}
      class="coverage-help"
      aria-label="O que significa a cobertura?"
      onpointerdown={onPointerDown}>[?]</Tooltip.Trigger
    >
    <Tooltip.Content
      class="coverage-tooltip"
      side="bottom"
      align="end"
      sideOffset={18}
      collisionPadding={16}
    >
      <div use:alignStem>
        <p>
          Cobertura é a proporção das faixas analisadas com evidências
          instrumentais suficientes para contribuir para sua paleta.
        </p>
        <p>Faixas sem essas evidências ficam fora do cálculo.</p>
        {#if hydrationPending}<p class="coverage-pending">
          <span class="loading-indicator" aria-hidden="true"></span>
          <span>Mais dados podem chegar depois.</span>
        </p>{/if}
      </div>
    </Tooltip.Content>
  </Tooltip.Root>
</Tooltip.Provider>

<style>
  :global(.coverage-help) {
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
  :global(.coverage-help:hover),
  :global(.coverage-help[data-state="delayed-open"]),
  :global(.coverage-help[data-state="instant-open"]) {
    color: var(--ink);
  }
  :global(.coverage-tooltip) {
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
  :global(.coverage-tooltip::before) {
    position: absolute;
    left: var(--stem-x, 50%);
    width: 1px;
    height: 18px;
    background: var(--line-strong);
    content: "";
    pointer-events: none;
  }
  :global(.coverage-tooltip[data-side="bottom"]::before) {
    bottom: 100%;
  }
  :global(.coverage-tooltip[data-side="top"]::before) {
    top: 100%;
  }
  p {
    margin: 0;
  }
  p + p {
    margin-top: 12px;
  }
  .coverage-pending {
    display: flex;
    align-items: baseline;
    gap: 8px;
    color: var(--ink);
    font-family: var(--meta);
    font-size: 12px;
  }
</style>
