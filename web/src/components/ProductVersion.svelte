<script lang="ts">
  import { Popover } from "bits-ui";

  const metadata = __PRODUCT_METADATA__;
  const statusLabels = {
    prototype: "Protótipo",
    development: "Em desenvolvimento",
    beta: "Beta",
    stable: "Estável",
  } as const;
  let open = false;
  let trigger: HTMLButtonElement | null = null;

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
    class="version-badge"
    aria-label={`Informações do Timbre Palette, ${statusLabels[metadata.status]}, produto ${metadata.product}`}
  >
    v{metadata.product}<span aria-hidden="true">{open ? "▴" : "▾"}</span>
  </Popover.Trigger>
  <Popover.Content
    class="version-panel"
    side="bottom"
    align="start"
    sideOffset={18}
    collisionPadding={20}
    aria-label="Informações do projeto"
  >
    <div use:alignStem>
      <dl>
        <div>
          <dt>Status</dt>
          <dd>{statusLabels[metadata.status]}</dd>
        </div>
        <div>
          <dt>Edição</dt>
          <dd>v{metadata.product}</dd>
        </div>
        <div>
          <dt>Método</dt>
          <dd>{metadata.method}</dd>
        </div>
        <div>
          <dt>API</dt>
          <dd>{metadata.api}</dd>
        </div>
      </dl>
    </div>
  </Popover.Content>
</Popover.Root>

<style>
  :global(.version-badge) {
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
  :global(.version-badge:hover),
  :global(.version-badge[data-state="open"]) {
    border-color: var(--accent);
    color: var(--ink);
  }
  :global(.version-panel) {
    position: relative;
    z-index: 5;
    width: 220px;
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
  :global(.version-panel::before) {
    position: absolute;
    left: var(--stem-x, 50%);
    width: 1px;
    height: 18px;
    background: var(--line-strong);
    content: "";
    pointer-events: none;
  }
  :global(.version-panel[data-side="bottom"]::before) {
    bottom: 100%;
  }
  :global(.version-panel[data-side="top"]::before) {
    top: 100%;
  }
  dl {
    display: grid;
    gap: 12px;
    margin: 0;
  }
  dl > div {
    display: flex;
    justify-content: space-between;
    gap: 24px;
  }
  dt {
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.065em;
  }
  dd {
    margin: 0;
  }
  @media (max-width: 800px) {
    :global(.version-badge) {
      display: none;
    }
  }
</style>
