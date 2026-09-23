<script lang="ts">
  import { RadioGroup } from "bits-ui";

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
  export let selectedButton: HTMLButtonElement | null = null;

  function exposeSelectedButton(node: HTMLButtonElement, selected: boolean) {
    function updateSelection(isSelected: boolean) {
      if (isSelected) selectedButton = node;
      else if (selectedButton === node) selectedButton = null;
    }

    updateSelection(selected);
    return {
      update: updateSelection,
      destroy() {
        if (selectedButton === node) selectedButton = null;
      },
    };
  }
</script>

<RadioGroup.Root
  class="segmented-control"
  aria-label={label}
  orientation="horizontal"
  {value}
  onValueChange={onChange}
>
  {#each options as option}
    <RadioGroup.Item
      value={option.value}
      disabled={option.disabled}
    >
      {#snippet child({ props })}
        <button
          {...props}
          class="segment-button"
          aria-label={option.note
            ? `${option.label}, ${option.note}`
            : option.label}
          use:exposeSelectedButton={value === option.value}
        >{option.label}</button>
      {/snippet}
    </RadioGroup.Item>
  {/each}
</RadioGroup.Root>

<style>
  :global(.segmented-control) {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
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
  .segment-button[data-state="checked"] {
    border-color: var(--accent-soft);
    color: var(--accent-pale);
  }
  .segment-button:disabled {
    cursor: wait;
    opacity: 0.48;
  }
</style>
