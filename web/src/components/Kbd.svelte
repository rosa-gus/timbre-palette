<script lang="ts">
  export let hideOnMobile = false;
</script>

<kbd class="ui-kbd" class:ui-kbd--hide-on-mobile={hideOnMobile}><slot /></kbd>

<style>
  .ui-kbd {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 22px;
    padding: 2px 6px;
    border: 0;
    border-bottom: 1px solid currentColor;
    border-radius: 0;
    background: transparent;
    color: inherit;
    font-family: var(--meta);
    font-size: 11px;
    font-weight: 400;
    letter-spacing: 0;
    line-height: 1.2;
    text-transform: none;
    white-space: nowrap;
  }

  .ui-kbd::before,
  .ui-kbd::after {
    content: "";
    position: absolute;
    bottom: 0;
    width: 1px;
    height: 5px;
    background: currentColor;
  }
  .ui-kbd::before { left: 0; }
  .ui-kbd::after { right: 0; }

  @media (hover: none) and (pointer: coarse) {
    .ui-kbd--hide-on-mobile { display: none; }
  }
</style>
