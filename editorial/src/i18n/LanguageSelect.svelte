<script lang="ts">
  import { localeStore, setLocale, translation as t, type Locale } from "./runtime";
  let busy = false;
  let error = "";
  async function change(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    busy = true; error = "";
    try { await setLocale(select.value as Locale); }
    catch { error = $t("language.failed"); select.value = $localeStore; }
    finally { busy = false; }
  }
</script>
<label class="language-select">
  <span class="label">{$t("language.label")}</span>
  <select value={$localeStore} on:change={change} disabled={busy}>
    <option value="pt-BR" lang="pt-BR">Português (Brasil)</option>
    <option value="en-US" lang="en-US">English (US)</option>
  </select>
</label>
{#if error}<span role="status">{error}</span>{/if}
<style>
  .language-select { display: inline-flex; align-items: center; gap: .5rem; font-size: .75rem; }
  .label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  select { color: inherit; background: transparent; border: 1px solid currentColor; padding: .4rem; font: inherit; max-width: 11rem; }
  option { color: #111; background: #fff; }
</style>
