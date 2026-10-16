<script lang="ts">
  import { formatWaitDuration } from "../i18n/formatters";
  import { t } from "../i18n/runtime";
  import Button from "./Button.svelte";
  import type { HistoryResume } from "../analysis/history";

  export let progress: HistoryResume;
  export let waitSeconds = 0;
  export let periodLabel = "";
  export let showResume = true;
  export let onResume: () => void = () => undefined;
  $: waitLabel = formatWaitDuration(waitSeconds);
</script>

<div class="history-resume">
  {#if progress.pages > 0}
    <p>{t("history.loadedTracks", { tracks: progress.tracks, periodSuffix: periodLabel
        ? ` · ${periodLabel}`
        : "" })} </p>
  {/if}
  {#if waitSeconds > 0}
    <p>{t("history.waitWithLabel", { waitLabel: waitLabel })}</p>
  {/if}
  {#if progress.pages > 0 && showResume}
    <Button variant="secondary" disabled={waitSeconds > 0} on:click={onResume}
      >{t("actions.resume")}</Button
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
