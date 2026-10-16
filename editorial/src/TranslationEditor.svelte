<script lang="ts">
  import { t } from "./i18n/runtime";
  import { emptyReview, localizedText, sourceRevision, type Sheet, type Translation, type Translations } from "./content";
  export let sheet: Sheet;
  export let translations: Translations;
  export let changed: () => void;
  let locale = "en";
  let feedback = "";
  let revision = "";
  let generation = 0;
  $: translation = translations[locale]?.find((item) => item.slug === sheet.resource.slug);
  $: refresh(sheet);
  async function refresh(source: Sheet) {
    const current = ++generation;
    const digest = await sourceRevision(source);
    if (current === generation) revision = digest;
  }
  async function start() {
    try {
      const canonical = Intl.getCanonicalLocales(locale)[0];
      if (!canonical || canonical === "pt-BR" || !/^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?$/.test(canonical)) throw new Error();
      locale = canonical;
      if (translations[locale]?.some((item) => item.slug === sheet.resource.slug)) return;
      const draft = structuredClone(localizedText(sheet));
      draft.source_revision = await sourceRevision(sheet);
      resetReview(draft);
      translations[locale] = [...(translations[locale] ?? []), draft];
      changed();
      feedback = "";
    } catch { feedback = t("translations.invalidLocale"); }
  }
  function resetReview(item: Translation) {
    item.status = "draft";
    item.review = emptyReview();
    item.sections.forEach((block) => { block.status = "draft"; block.review = emptyReview(); });
  }
  function invalidate() {
    if (translation) resetReview(translation);
    changed();
  }
  async function rebase() {
    if (!translation) return;
    translation.sections = sheet.resource.sections.map((block) => ({
      id: block.id, text: translation!.sections.find((item) => item.id === block.id)?.text ?? block.text,
      status: "draft", review: emptyReview(),
    }));
    if (sheet.resource.image?.asset_id !== translation.image?.asset_id) {
      translation.image = localizedText(sheet).image;
    }
    translation.source_revision = await sourceRevision(sheet);
    resetReview(translation);
    changed();
  }
</script>

<section aria-labelledby="translations-title">
  <h3 id="translations-title">{t("translations.title")}</h3>
  <p class="hint">{t("translations.hint")}</p>
  <label>{t("translations.locale")}<input bind:value={locale} list="content-locales" placeholder="en" /></label>
  <datalist id="content-locales">{#each Object.keys(translations) as language}<option value={language}></option>{/each}</datalist>
  {#if translation}
    {#if translation.source_revision !== revision}<p role="status">{t("translations.stale")}</p>{/if}
    <button on:click={rebase}>{t("translations.rebase")}</button>
    <label>{t("sheet.name")}<input bind:value={translation.name} on:input={invalidate} /></label>
    <label>{t("sheet.description")}<textarea rows="3" bind:value={translation.description} on:input={invalidate}></textarea></label>
    <label>{t("sheet.soundProduction")}<textarea rows="3" bind:value={translation.sound_production} on:input={invalidate}></textarea></label>
    <label>{t("translations.roles")}<textarea rows="3" value={translation.common_roles.join("\n")} on:input={(event) => { translation!.common_roles = event.currentTarget.value.split("\n").filter(Boolean); invalidate(); }}></textarea></label>
    {#each translation.sections as block}
      <label>{t("curiosity.text")}<textarea rows="3" bind:value={block.text} on:input={invalidate}></textarea></label>
      <label class="check"><input type="checkbox" bind:checked={block.review.claim_support_verified} on:change={() => { block.status = block.review.claim_support_verified ? "reviewed" : "draft"; changed(); }} />{t("curiosity.supportReviewed")}</label>
      <div class="form-grid"><label>{t("review.reviewer")}<input bind:value={block.review.reviewer} on:input={changed} /></label><label>{t("review.date")}<input type="date" bind:value={block.review.reviewed_at} on:input={changed} /></label></div>
    {/each}
    {#if translation.image}
      <label>{t("images.alt")}<input bind:value={translation.image.alt} on:input={invalidate} /></label>
      <label>{t("images.caption")}<input bind:value={translation.image.caption} on:input={invalidate} /></label>
    {/if}
    <label class="check"><input type="checkbox" bind:checked={translation.review.claim_support_verified} on:change={changed} />{t("translations.verified")}</label>
    <div class="form-grid"><label>{t("review.reviewer")}<input bind:value={translation.review.reviewer} on:input={changed} /></label><label>{t("review.date")}<input type="date" bind:value={translation.review.reviewed_at} on:input={changed} /></label></div>
    <label>{t("review.status")}<select bind:value={translation.status} on:change={changed}><option value="draft">{t("review.draft")}</option><option value="reviewed">{t("review.reviewed")}</option><option value="published">{t("review.published")}</option><option value="deprecated">{t("review.deprecated")}</option><option value="stale" disabled>{t("translations.staleStatus")}</option></select></label>
  {:else}
    <button on:click={start}>{t("translations.start")}</button>
  {/if}
  {#if feedback}<p role="status">{feedback}</p>{/if}
</section>
