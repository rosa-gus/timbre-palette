<script lang="ts">
  import { Popover } from "bits-ui";
  export let percent: number;
  export let added: number;
  let trigger: HTMLButtonElement | null = null;
  $: percentage =
    percent < 0.1
      ? "<0,1"
      : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(
          percent,
        );
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
  function preventAutoFocus(event: Event) {
    event.preventDefault();
  }
</script>

<Popover.Root>
  <Popover.Trigger
    bind:ref={trigger}
    openOnHover
    openDelay={200}
    closeDelay={0}
    class="catalog-growth"
    aria-label={`Crescimento do catálogo: +${percentage}% desde sua última visita neste navegador`}
    >+{percentage}%</Popover.Trigger
  >
  <Popover.Content
    class="catalog-tooltip"
    side="bottom"
    align="end"
    sideOffset={18}
    collisionPadding={16}
    trapFocus={false}
    onOpenAutoFocus={preventAutoFocus}
    onCloseAutoFocus={preventAutoFocus}
    aria-label="Crescimento do catálogo"
  >
    <div use:alignStem>
      <p class="catalog-title">Nosso catálogo cresceu {percentage}%.</p>
      <p>
        Mais {added.toLocaleString("pt-BR")} gravações com instrumentos documentados
        desde sua última visita neste navegador.
      </p>
      <p>
        Ao consultar um perfil, faixas e artistas ainda não materializados podem
        ser consultados em segundo plano no snapshot MusicBrainz publicado.
        Novas evidências podem aparecer em uma visita futura.
      </p>
    </div>
  </Popover.Content>
</Popover.Root>

<style>
  :global(.catalog-growth) {
    padding: 5px 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: var(--accent-soft);
    font-family: var(--meta);
    font-size: 13px;
    font-weight: 400;
    line-height: 1.5;
    letter-spacing: 0.065em;
    white-space: nowrap;
    cursor: help;
  }
  :global(.catalog-growth:hover) {
    color: var(--ink);
  }
  :global(.catalog-growth:focus-visible) {
    outline: 1px solid var(--accent);
    outline-offset: 2px;
  }
  :global(.catalog-tooltip) {
    position: relative;
    z-index: 30;
    width: min(320px, calc(100vw - 32px));
    padding: 16px;
    border: 1px solid var(--line-strong);
    border-radius: 0;
    background: var(--paper);
    color: var(--muted);
    font-family: var(--display);
    font-size: 13px;
    line-height: 1.6;
  }
  :global(.catalog-tooltip::before) {
    position: absolute;
    left: var(--stem-x, 50%);
    width: 1px;
    height: 18px;
    background: var(--line-strong);
    content: "";
    pointer-events: none;
  }
  :global(.catalog-tooltip[data-side="bottom"]::before) {
    bottom: 100%;
  }
  :global(.catalog-tooltip[data-side="top"]::before) {
    top: 100%;
  }
  p {
    margin: 0;
  }
  p + p {
    margin-top: 12px;
  }
  .catalog-title {
    color: var(--ink);
  }
</style>
