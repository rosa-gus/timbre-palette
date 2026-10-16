<script lang="ts">
  import { translation as t } from "../i18n/runtime";
  import Dropdown from "./Dropdown.svelte";
</script>

<Dropdown title={$t("limits.title")}>
  <p class="limits-intro">{$t("limits.intro")}</p>
  <p>{$t("limits.method")} </p>
  <p>{$t("limits.incompleteCredits")} </p>
  <p>{$t("limits.excludedTracks")} </p>
  <p>{$t("limits.refresh")} </p>
  <p>{$t("limits.vocabulary")} </p>
  <p>{$t("limits.temperament")} </p>
</Dropdown>

<style>
  .limits-intro {
    color: var(--ink);
  }
</style>
