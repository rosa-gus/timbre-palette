<script lang="ts">
  import Button from "./Button.svelte";
  import type { HistoryResume } from "../analysis/history";

  export let progress: HistoryResume;
  export let waitSeconds = 0;
  export let periodLabel = "";
  export let showResume = true;
  export let onResume: () => void = () => undefined;
  $: waitLabel =
    waitSeconds >= 60
      ? `${Math.ceil(waitSeconds / 60)} min`
      : `${waitSeconds} s`;
</script>

<div class="history-resume">
  {#if progress.pages > 0}
    <p>
      {progress.tracks} faixas já carregadas{periodLabel
        ? ` · ${periodLabel}`
        : ""}. Retome para concluir a análise.
    </p>
  {/if}
  {#if waitSeconds > 0}
    <p>Aguarde {waitLabel} para tentar novamente.</p>
  {/if}
  {#if progress.pages > 0 && showResume}
    <Button variant="secondary" disabled={waitSeconds > 0} on:click={onResume}
      >Retomar consulta</Button
    >
  {/if}
</div>

<style>
  .history-resume {
    display: grid;
    gap: 12px;
    margin-top: 16px;
  }
  p {
    margin: 0;
    color: var(--muted);
    font-size: 13px;
    line-height: 1.5;
  }
</style>
