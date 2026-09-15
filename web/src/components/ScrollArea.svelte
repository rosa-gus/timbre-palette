<script lang="ts">
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex (A região rolável precisa receber foco para permitir rolagem pelo teclado.) -->
<div
  class="ui-scroll-area"
  role="region"
  aria-label="Conteúdo da ficha instrumental"
  tabindex="0"
>
  <slot />
</div>

<style>
  .ui-scroll-area {
    position: relative;
    min-height: 0;
    height: 100%;
    overflow: auto;
    padding-right: 18px;
    scrollbar-gutter: stable;
  }
  .ui-scroll-area:focus-visible {
    outline: 2px solid var(--accent-soft);
    outline-offset: 4px;
  }
</style>
