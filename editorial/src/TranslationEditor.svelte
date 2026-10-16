<script lang="ts">
  import { translation as t } from "./i18n/runtime";
  import { onDestroy } from "svelte";
  import { sourceRevision, legacySourceRevision, type Sheet, type Translations } from "./content";
  import { startTranslation, rebaseTranslation, resetTranslationReview } from "./translation-operations";
  export let sheet: Sheet;
  export let translations: Translations;
  export let changed: () => void;
  let locale = "en-US";
  let feedback = "";
  let revision = "";
  let legacyRevision = "";
  let generation = 0;
  let operation = 0;
  let disposed = false;
  $: cancelPending(sheet, locale);
  onDestroy(() => { disposed = true; generation++; operation++; });
  function cancelPending(_sheet: Sheet, _locale: string) {
    operation++;
    feedback = "";
  }
  function task() {
    const current = ++operation;
    const selectedLocale = locale;
    const context = { sheet, locale, translations };
    return { context, isCurrent: () => !disposed && current === operation &&
      sheet === context.sheet && locale === selectedLocale && translations === context.translations };
  }
  $: translation = translations[locale]?.find((item) => item.slug === sheet.resource.slug);
  $: refresh(sheet);
  async function refresh(source: Sheet) {
    const current = ++generation;
    revision = "";
    legacyRevision = "";
    const snapshot = structuredClone(source);
    const [digest, legacy] = await Promise.all([sourceRevision(snapshot), legacySourceRevision(snapshot)]);
    if (!disposed && current === generation) { revision = digest; legacyRevision = legacy; }
  }
  async function start() {
    const { context, isCurrent } = task();
    try {
      const canonical = Intl.getCanonicalLocales(context.locale)[0];
      if (!canonical || canonical === "pt-BR" || !/^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?$/.test(canonical)) throw new Error();
      context.locale = canonical;
      const created = await startTranslation(context, isCurrent);
      if (!isCurrent()) return;
      locale = canonical;
      feedback = "";
      if (created) changed();
    } catch {
      if (isCurrent()) feedback = $t("translations.invalidLocale");
    }
  }
  function invalidate() {
    operation++;
    if (translation) resetTranslationReview(translation);
    changed();
  }
  async function rebase() {
    const { context, isCurrent } = task();
    if (await rebaseTranslation(context, isCurrent) && isCurrent()) changed();
  }
</script>

<section aria-labelledby="translations-title">
  <h3 id="translations-title">{$t("translations.title")}</h3>
  <p class="hint">{$t("translations.hint")}</p>
  <label>{$t("translations.locale")}<input bind:value={locale} list="content-locales" placeholder="en-US" /></label>
  <datalist id="content-locales">{#each Object.keys(translations) as language}<option value={language}></option>{/each}</datalist>
  {#if translation}
    {#if translation.source_revision !== revision && translation.source_revision !== legacyRevision}<p role="status">{$t("translations.stale")}</p>{/if}
    <button on:click={rebase}>{$t("translations.rebase")}</button>
    <label>{$t("sheet.name")}<input lang={locale} bind:value={translation.name} on:input={invalidate} /></label>
    <label>{$t("sheet.description")}<textarea rows="3" lang={locale} bind:value={translation.description} on:input={invalidate}></textarea></label>
    <label>{$t("sheet.soundProduction")}<textarea rows="3" lang={locale} bind:value={translation.sound_production} on:input={invalidate}></textarea></label>
    <label>{$t("translations.roles")}<textarea rows="3" value={translation.common_roles.join("\n")} on:input={(event) => { translation!.common_roles = event.currentTarget.value.split("\n").filter(Boolean); invalidate(); }}></textarea></label>
    {#each translation.sections as block}
      <label>{$t("curiosity.text")}<textarea rows="3" lang={locale} bind:value={block.text} on:input={invalidate}></textarea></label>
      <label class="check"><input type="checkbox" bind:checked={block.review.claim_support_verified} on:change={() => { block.status = block.review.claim_support_verified ? "reviewed" : "draft"; changed(); }} />{$t("curiosity.supportReviewed")}</label>
      <div class="form-grid"><label>{$t("review.reviewer")}<input bind:value={block.review.reviewer} on:input={changed} /></label><label>{$t("review.date")}<input type="date" bind:value={block.review.reviewed_at} on:input={changed} /></label></div>
    {/each}
    {#if translation.image}
      <label>{$t("images.alt")}<input lang={locale} bind:value={translation.image.alt} on:input={invalidate} /></label>
      <label>{$t("images.caption")}<input lang={locale} bind:value={translation.image.caption} on:input={invalidate} /></label>
    {/if}
    <label class="check"><input type="checkbox" bind:checked={translation.review.claim_support_verified} on:change={changed} />{$t("translations.verified")}</label>
    <div class="form-grid"><label>{$t("review.reviewer")}<input bind:value={translation.review.reviewer} on:input={changed} /></label><label>{$t("review.date")}<input type="date" bind:value={translation.review.reviewed_at} on:input={changed} /></label></div>
    <label>{$t("review.status")}<select bind:value={translation.status} on:change={changed}><option value="draft">{$t("review.draft")}</option><option value="reviewed">{$t("review.reviewed")}</option><option value="published">{$t("review.published")}</option><option value="deprecated">{$t("review.deprecated")}</option><option value="stale" disabled>{$t("translations.staleStatus")}</option></select></label>
  {:else}
    <button on:click={start}>{$t("translations.start")}</button>
  {/if}
  {#if feedback}<p role="status">{feedback}</p>{/if}
</section>
