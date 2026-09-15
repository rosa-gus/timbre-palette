<script lang="ts">
  import { LinkPreview } from "bits-ui";

  export let href: string;
  export let label: string;
  export let description: string;
  export let ariaLabel: string = label;
  let trigger: HTMLAnchorElement | null = null;

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

<LinkPreview.Root openDelay={400}>
  <LinkPreview.Trigger
    bind:ref={trigger}
    {href}
    target="_blank"
    rel="noreferrer noopener"
    aria-label={ariaLabel}
  >
    {label}
  </LinkPreview.Trigger>
  <LinkPreview.Content
    class="footer-link-preview"
    side="top"
    align="end"
    sideOffset={18}
    collisionPadding={16}
  >
    <div use:alignStem>
      <p class="preview-title">{label}</p>
      <p>{description}</p>
    </div>
  </LinkPreview.Content>
</LinkPreview.Root>

<style>
  :global(.footer-link-preview) {
    position: relative;
    z-index: 30;
    width: min(280px, calc(100vw - 32px));
    padding: 16px;
    border: 1px solid var(--line-strong);
    border-radius: 0;
    background: var(--paper);
    color: var(--muted);
    font-family: var(--display);
    font-size: 13px;
    font-weight: 400;
    line-height: 1.6;
    letter-spacing: normal;
    text-transform: none;
    text-align: left;
    white-space: normal;
    overflow-wrap: anywhere;
  }
  :global(.footer-link-preview::before) {
    position: absolute;
    left: var(--stem-x, 50%);
    width: 1px;
    height: 18px;
    background: var(--line-strong);
    content: "";
    pointer-events: none;
  }
  :global(.footer-link-preview[data-side="top"]::before) {
    top: 100%;
  }
  :global(.footer-link-preview[data-side="bottom"]::before) {
    bottom: 100%;
  }
  p {
    margin: 0;
  }
  .preview-title {
    margin-bottom: 6px;
    color: var(--ink);
    font-weight: 500;
  }
</style>
