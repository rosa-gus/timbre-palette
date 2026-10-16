<script lang="ts">
  import type { Snippet } from "svelte";
  import { messageParts, type MessageKey } from "./runtime";

  let { message, values = {}, wrappers = {} }: {
    message: MessageKey;
    values?: Record<string, string | number>;
    wrappers?: Record<string, Snippet<[string]>>;
  } = $props();
</script>

{#each messageParts(message, values) as part}
  {#if part.wrapper}
    {@render wrappers[part.wrapper](part.text)}
  {:else}
    {part.text}
  {/if}
{/each}
