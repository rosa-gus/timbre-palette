<script lang="ts">
  export let direction: "left" | "right" | "up-right" = "right";
</script>

<span class={`icon-arrow icon-arrow--${direction}`} aria-hidden="true">↑</span>

<style>
  .icon-arrow {
    display: inline-block;
    margin-left: 0.55em;
    color: currentColor;
    font-family: var(--meta);
    font-size: 1.1em;
    line-height: 1;
    transform-origin: center;
    vertical-align: -0.08em;
  }
  .icon-arrow--right {
    transform: rotate(90deg);
  }
  .icon-arrow--left {
    margin-left: 0;
    margin-right: 0.55em;
    transform: rotate(-90deg);
  }
  .icon-arrow--up-right {
    transform: rotate(45deg);
  }
</style>
