<script lang="ts">
  type Option = {
    value: string;
    label: string;
    disabled?: boolean;
    note?: string;
  };
  export let options: Option[] = [];
  export let value = "";
  export let label = "Escolha uma opção";
  export let onChange: (value: string) => void = () => undefined;
</script>

<div class="segmented-control" role="radiogroup" aria-label={label}>
  {#each options as option}
    <button
      type="button"
      class:active={value === option.value}
      class="segment-button"
      disabled={option.disabled}
      role="radio"
      aria-checked={value === option.value}
      aria-label={option.note
        ? `${option.label}, ${option.note}`
        : option.label}
      on:click={() => onChange(option.value)}>{option.label}</button
    >
  {/each}
</div>

<style>
  .segmented-control {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }
  .segment-button {
    min-height: 30px;
    padding: 0 9px;
    border: 1px solid var(--line);
    border-radius: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--meta);
    font-size: 12px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .segment-button:hover,
  .segment-button.active {
    border-color: var(--accent-soft);
    color: var(--accent-pale);
  }
  .segment-button:disabled {
    cursor: wait;
    opacity: 0.48;
  }
</style>
