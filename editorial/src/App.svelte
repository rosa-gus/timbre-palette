<script lang="ts">
  import LanguageSelect from "./i18n/LanguageSelect.svelte";
  import { translation as t } from "./i18n/runtime";
  import { onMount } from "svelte";
  import TranslationEditor from "./TranslationEditor.svelte";
  import { initialSnapshot, sourceSheets, snapshotFromSheets, sourceRevision, legacySourceRevision, type Sheet, type Translations, type Snapshot } from "./content";
  import type { EditorialSection } from "../../web/src/api/types";
  import { getStorageItem, isStorageAvailable, setStorageItem } from "../../web/src/storage";

  import { STORAGE_KEYS } from "../../web/src/utils/storage-keys";
  import { cleanupStorageVersions } from "../../web/src/utils/storage-cleanup";

  const seed = sourceSheets(initialSnapshot);
  let translations: Translations = structuredClone(Object.fromEntries(Object.entries(initialSnapshot.locales).filter(([locale]) => locale !== "pt-BR")));
  let sheets: Sheet[] = structuredClone(seed) as Sheet[];
  let selectedSlug = sheets[0].resource.slug;
  let search = "";
  let feedback = "";
  let storageReady = false;
  let storageAvailable = true;
  $: selected = sheets.find((sheet) => sheet.resource.slug === selectedSlug) ?? sheets[0];
  $: visible = sheets.filter(({ resource }) => `${resource.name} ${resource.slug}`.toLowerCase().includes(search.toLowerCase()));
  $: if (storageReady && storageAvailable) persist(sheets, selected, translations);

  onMount(() => {
    cleanupStorageVersions();
    try {
      if (!isStorageAvailable()) throw new Error("Armazenamento indisponível");
      const saved = getStorageItem<unknown>(STORAGE_KEYS.editorialInstruments);
      if (saved && typeof saved === "object") {
        const parsed = saved as Record<string, unknown>;
        const savedInstruments = parsed.schema_version === 2 ? sourceSheets(parsed as unknown as Snapshot)
          : Array.isArray(parsed.instruments) ? parsed.instruments as Sheet[] : [];
        const seedSlugs = new Set(seed.map((item) => item.resource.slug));
        const savedSlugs = savedInstruments.map((sheet) => sheet.resource?.slug);
        if (![1, 2].includes(Number(parsed.schema_version)) || !savedInstruments.length ||
            new Set(savedSlugs).size !== savedSlugs.length ||
            savedInstruments.some((sheet) => !seedSlugs.has(sheet.resource?.slug) ||
              !Array.isArray(sheet.resource?.sources) || Array.isArray(sheet.resource?.sections) === false ||
              !Array.isArray(sheet.resource?.further_reading) || !sheet.review || !sheet.text_citations)) {
          throw new Error("Formato incompatível");
        }
        const savedBySlug = new Map(savedInstruments.map((sheet) => [sheet.resource.slug, sheet]));
        sheets = seed.map((item) => savedBySlug.get(item.resource.slug) ?? structuredClone(item)) as Sheet[];
        if (parsed.schema_version === 2) translations = Object.fromEntries(Object.entries((parsed as unknown as Snapshot).locales).filter(([locale]) => locale !== "pt-BR"));
      }
    } catch {
      storageAvailable = false;
      feedback = $t("errors.loadRevisions");
    }
    storageReady = true;
  });

  function persist(instruments: Sheet[], _selected: Sheet, translated: Translations) {
    if (!setStorageItem(STORAGE_KEYS.editorialInstruments, snapshotFromSheets(instruments, translated))) {
      storageAvailable = false;
      feedback = $t("errors.storageUnavailable");
    }
  }
  function invalidate() {
    selected.review.claim_support_verified = false;
    selected.review.reviewed_at = null;
    selected.review.reviewer = null;
    sheets = [...sheets];
  }
  function addCuriosity() {
    selected.resource.sections = [{
      id: `${selected.resource.slug}-curiosity`, kind: "curiosity", text: "", content_type: "editorial_summary", status: "draft",
      review: { source_metadata_verified: false, claim_support_verified: false, reviewed_at: null, reviewer: null, editorial_note: null },
      citations: [],
    }];
    invalidate();
  }
  function removeCuriosity() { selected.resource.sections = []; invalidate(); }
  function updateCitation(section: EditorialSection, sourceId: string, checked: boolean) {
    section.citations = checked ? [...section.citations, { source_id: sourceId, locator: null, note: null }] : section.citations.filter((citation) => citation.source_id !== sourceId);
    section.review.claim_support_verified = false;
    section.review.reviewed_at = null;
    sheets = [...sheets];
  }
  function addSource() {
    selected.resource.sources = [...selected.resource.sources, {
      id: crypto.randomUUID(), title: "", contributors: [], publisher: null, publication_date: null, url: null,
      accessed_at: new Date().toISOString().slice(0, 10), verified_at: null, locator: null,
      source_type: "article", language: "pt-BR", license: null, note: null, metadata_verified: false,
    }];
    invalidate();
  }
  function removeSource(id: string) {
    selected.resource.sources = selected.resource.sources.filter((source) => source.id !== id);
    for (const field of ["description", "sound_production"] as const)
      selected.text_citations[field] = selected.text_citations[field].filter((sourceId) => sourceId !== id);
    for (const section of selected.resource.sections) {
      section.citations = section.citations.filter((citation) => citation.source_id !== id);
      section.review.claim_support_verified = false;
    }
    invalidate();
  }
  function addReading() {
    selected.resource.further_reading = [...selected.resource.further_reading, { title: "", url: "", publisher: null, status: "draft", reviewer: null, reviewed_at: null }];
  }
  function addImage() {
    selected.resource.image = { asset_id: "", resolution: "exact", depicted_instrument_slug: selected.resource.slug, alt: "", caption: "", variants: [{ name: "detail", url: "", width: 1200, height: 675 }], tone: selected.resource.tone ?? { shadow: "#000000", highlight: "#F29191" }, credit: { photographer: null, provider: null, photo_url: null, photographer_url: null, license: null, license_url: null } };
    invalidate();
  }
  function httpUrl(value: string | null | undefined): boolean {
    try { return ["http:", "https:"].includes(new URL(value ?? "").protocol); } catch { return false; }
  }
  function validate(instruments: Sheet[]): string[] {
    const errors: string[] = [];
    for (const sheet of instruments) {
      const { resource, review } = sheet;
      const label = resource.name || resource.slug;
      if (!resource.name.trim() || !resource.description.trim() || !resource.sound_production.trim())
        errors.push($t("validation.requiredText", { label: label }));
      const sourceIds = new Set(resource.sources.map((source) => source.id));
      for (const source of resource.sources) {
        if (!source.title.trim() || (source.url && !httpUrl(source.url))) errors.push($t("validation.source", { label: label }));
      }
      for (const field of ["description", "sound_production"] as const) {
        if (sheet.text_citations[field].some((id) => !sourceIds.has(id))) errors.push($t("validation.missingReference", { label: label, field: field }));
      }
      if (review.claim_support_verified && (!review.reviewer?.trim() || !review.reviewed_at))
        errors.push($t("validation.review", { label: label }));
      for (const section of resource.sections) {
        if (!section.text.trim()) errors.push(`${label}: remova a curiosidade vazia ou escreva o texto.`);
        if (section.citations.some((citation) => !sourceIds.has(citation.source_id))) errors.push($t("validation.curiosityReference", { label: label }));
        if (section.status !== "draft" && !section.citations.length) errors.push($t("validation.curiosityCitation", { label: label }));
        if (["reviewed", "published"].includes(section.status) && (!section.review.claim_support_verified || !section.review.reviewer?.trim() || !section.review.reviewed_at))
          errors.push($t("validation.curiosityReview", { label: label }));
      }
      for (const link of resource.further_reading) {
        if (!link.title.trim() || !httpUrl(link.url)) errors.push($t("validation.readingLink", { label: label }));
        if (link.status !== "draft" && (!link.reviewer?.trim() || !link.reviewed_at))
          errors.push($t("validation.readingReview", { label: label }));
      }
      if (resource.image && (!resource.image.asset_id.trim() || !resource.image.alt.trim() || !resource.image.variants.length || !httpUrl(resource.image.variants[0].url)))
        errors.push($t("validation.image", { label: label }));
    }
    return errors;
  }
  async function exportRevision() {
    const snapshot = structuredClone(sheets);
    for (const sheet of snapshot) {
      const verified = (ids: string[]) => ids.length > 0 && ids.every((id) => sheet.resource.sources.find((source) => source.id === id)?.metadata_verified);
      sheet.review.source_metadata_verified = verified([...sheet.text_citations.description, ...sheet.text_citations.sound_production]);
      for (const section of sheet.resource.sections) section.review.source_metadata_verified = verified(section.citations.map((citation) => citation.source_id));
    }
    const errors = validate(snapshot);
    if (errors.length) { feedback = errors.join("\n"); return; }
    const output = snapshotFromSheets(snapshot, structuredClone(translations));
    for (const [locale, texts] of Object.entries(output.locales)) {
      if (locale === "pt-BR") continue;
      for (const text of texts) {
        const original = snapshot.find((item) => item.resource.slug === text.slug)!;
        const revision = await sourceRevision(original);
        if (text.source_revision === await legacySourceRevision(original)) text.source_revision = revision;
        if (text.status !== "deprecated" && text.source_revision !== revision) text.status = "stale";
        if (["reviewed", "published"].includes(text.status) &&
            (!text.name.trim() || !text.description.trim() || !text.sound_production.trim() ||
             !text.review.claim_support_verified || !text.review.reviewer?.trim() || !text.review.reviewed_at ||
             text.sections.some((block) => ["reviewed", "published"].includes(block.status) &&
               (!block.review.claim_support_verified || !block.review.reviewer?.trim() || !block.review.reviewed_at)))) {
          feedback = $t("translations.incomplete", { label: text.name, locale }); return;
        }
      }
    }
    const blob = new Blob([JSON.stringify(output, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "timbre-instrument-review.json"; anchor.click();
    URL.revokeObjectURL(url);
    feedback = $t("export.success");
  }
</script>

<div class="app-shell">
  <header class="topbar"><a href="./" class="brand">timbre palette <span>{$t("navigation.editorial")}</span></a><LanguageSelect /><span class="eyebrow">{$t("navigation.instrumentSheets")}</span></header>
  <div class="page-heading"><div><p class="eyebrow">{$t("catalog.heading")}</p><h1>{$t("catalog.titleStart")}<br />{$t("catalog.titleEnd")}</h1><p class="intro">{$t("catalog.description")}</p></div><button class="primary-action" on:click={exportRevision}>{$t("export.action")}</button></div>
  <div class="editor-layout">
    <aside class="catalog-sidebar" aria-label={$t("catalog.sidebarLabel")}>
      <label for="search">{$t("catalog.search")}</label><input id="search" type="search" bind:value={search} placeholder={$t("catalog.searchPlaceholder")} />
      <nav aria-label={$t("catalog.listLabel")}><ul class="sheet-list">{#each visible as sheet}<li><button class:selected={sheet.resource.slug === selectedSlug} on:click={() => selectedSlug = sheet.resource.slug}><strong lang="pt-BR">{sheet.resource.name}</strong><span>{sheet.resource.kind === "family" ? $t("catalog.family") : $t("catalog.instrument")} · {sheet.review.claim_support_verified ? $t("review.reviewed") : $t("review.pending")}</span></button></li>{/each}</ul></nav>
      {#if !visible.length}<p>{$t("catalog.empty")}</p>{/if}
    </aside>
    <main aria-label={$t("sheet.editLabel")}>
      {#key selected.resource.slug}
        <div class="sheet-heading"><h2 lang="pt-BR">{selected.resource.name}</h2><span class="eyebrow">{selected.resource.slug}</span></div>
        <section aria-labelledby="text-title"><h3 id="text-title">{$t("sheet.briefTitle")}</h3>
          <div class="form-grid"><label>{$t("sheet.name")}<input lang="pt-BR" bind:value={selected.resource.name} on:input={invalidate} /></label><label>{$t("sheet.family")}<select bind:value={selected.resource.family_slug} disabled={selected.resource.kind === "family"} on:change={invalidate}><option value={null}>{$t("sheet.selfFamily")}</option>{#each sheets.filter((sheet) => sheet.resource.kind === "family") as family}<option value={family.resource.slug}>{family.resource.name}</option>{/each}</select></label></div>
          <label>{$t("sheet.description")}<textarea rows="3" maxlength="600" lang="pt-BR" bind:value={selected.resource.description} on:input={invalidate}></textarea></label>
          <label>{$t("sheet.soundProduction")}<textarea rows="2" maxlength="400" lang="pt-BR" bind:value={selected.resource.sound_production} on:input={invalidate}></textarea></label>
          <p class="hint">{$t("sheet.writingHint")}</p>
          <fieldset><legend>{$t("sources.descriptionTitle")}</legend>{#each selected.resource.sources as source}<label class="check"><input type="checkbox" value={source.id} bind:group={selected.text_citations.description} on:change={invalidate} />{source.title || $t("sources.untitled")}</label>{/each}</fieldset>
          <fieldset><legend>{$t("sources.soundProductionTitle")}</legend>{#each selected.resource.sources as source}<label class="check"><input type="checkbox" value={source.id} bind:group={selected.text_citations.sound_production} on:change={invalidate} />{source.title || $t("sources.untitled")}</label>{/each}</fieldset>
        </section>
        <section aria-labelledby="curiosity-title"><h3 id="curiosity-title">{$t("curiosity.title")} <span class="hint">{$t("curiosity.optional")}</span></h3>
          {#if !selected.resource.sections.length}<p class="hint">{$t("curiosity.optionalHint")}</p><button on:click={addCuriosity}>{$t("curiosity.add")}</button>{/if}
          {#each selected.resource.sections as section}
            <label>{$t("curiosity.text")}<textarea rows="3" maxlength="600" lang="pt-BR" bind:value={section.text} on:input={() => { section.review.claim_support_verified = false; section.review.reviewed_at = null; }}></textarea></label>
            <label>{$t("review.status")}<select bind:value={section.status}><option value="draft">{$t("review.draft")}</option><option value="sourced">{$t("review.sourced")}</option><option value="reviewed">{$t("review.reviewed")}</option><option value="published">{$t("review.published")}</option><option value="deprecated">{$t("review.deprecated")}</option></select></label>
            <fieldset><legend>{$t("curiosity.sourcesTitle")}</legend>{#each selected.resource.sources as source}<label class="check"><input type="checkbox" checked={section.citations.some((citation) => citation.source_id === source.id)} on:change={(event) => updateCitation(section, source.id, event.currentTarget.checked)} />{source.title || $t("sources.untitled")}</label>{/each}</fieldset>
            {#each section.citations as citation}<label>{$t("sources.locatorWithTitle", { title: selected.resource.sources.find((source) => source.id === citation.source_id)?.title ?? "" })}<input bind:value={citation.locator} placeholder={$t("sources.locatorPlaceholder")} /></label>{/each}
            <label class="check"><input type="checkbox" bind:checked={section.review.claim_support_verified} />{$t("curiosity.supportReviewed")}</label>
            <div class="form-grid"><label>{$t("review.reviewer")}<input bind:value={section.review.reviewer} /></label><label>{$t("review.date")}<input type="date" bind:value={section.review.reviewed_at} /></label></div>
            <button class="danger-action" on:click={removeCuriosity}>{$t("curiosity.remove")}</button>
          {/each}
        </section>
        <section aria-labelledby="reading-title"><h3 id="reading-title">{$t("reading.title")}</h3><p class="hint">{$t("reading.hint")}</p>
          {#each selected.resource.further_reading as link, index}<div class="item-card"><label>{$t("sources.title")}<input bind:value={link.title} on:input={() => link.status = "draft"} /></label><div class="form-grid"><label>{$t("sources.url")}<input type="url" bind:value={link.url} on:input={() => link.status = "draft"} /></label><label>{$t("reading.publisher")}<input bind:value={link.publisher} on:input={() => link.status = "draft"} /></label></div><div class="form-grid"><label>{$t("review.linkReviewer")}<input bind:value={link.reviewer} /></label><label>{$t("review.date")}<input type="date" bind:value={link.reviewed_at} /></label></div><label>{$t("review.status")}<select bind:value={link.status}><option value="draft">{$t("review.draft")}</option><option value="reviewed">{$t("review.reviewed")}</option><option value="published">{$t("review.published")}</option></select></label><button on:click={() => selected.resource.further_reading = selected.resource.further_reading.filter((_, i) => i !== index)}>{$t("reading.remove")}</button></div>{/each}
          <button on:click={addReading}>{$t("reading.add")}</button>
        </section>
        <section aria-labelledby="sources-title"><h3 id="sources-title">{$t("sources.heading")}</h3>
          {#each selected.resource.sources as source}<div class="item-card"><label>{$t("sources.title")}<input bind:value={source.title} on:input={() => { source.metadata_verified = false; invalidate(); }} /></label><div class="form-grid"><label>{$t("sources.url")}<input type="url" bind:value={source.url} on:input={() => { source.metadata_verified = false; invalidate(); }} /></label><label>{$t("sources.publisher")}<input bind:value={source.publisher} on:input={() => { source.metadata_verified = false; invalidate(); }} /></label></div><label>{$t("sources.locator")}<input bind:value={source.locator} on:input={invalidate} /></label><label>{$t("sources.notes")}<textarea rows="2" bind:value={source.note}></textarea></label><div class="form-grid"><label>{$t("sources.accessed")}<input type="date" bind:value={source.accessed_at} /></label><label>{$t("sources.verifiedAt")}<input type="date" bind:value={source.verified_at} /></label></div><label class="check"><input type="checkbox" bind:checked={source.metadata_verified} />{$t("sources.verified")}</label><button on:click={() => removeSource(source.id)}>{$t("sources.remove")}</button></div>{/each}
          <button on:click={addSource}>{$t("sources.add")}</button>
        </section>
        <section aria-labelledby="image-title"><h3 id="image-title">{$t("images.heading")}</h3>
          {#if selected.resource.image}<div class="form-grid"><label>{$t("images.asset")}<input bind:value={selected.resource.image.asset_id} on:input={invalidate} /></label><label>{$t("images.depictedInstrument")}<input bind:value={selected.resource.image.depicted_instrument_slug} on:input={invalidate} /></label></div><label>{$t("images.resolution")}<select bind:value={selected.resource.image.resolution} on:change={invalidate}><option value="exact">{$t("images.exact")}</option><option value="related">{$t("images.related")}</option><option value="family">{$t("sheet.family")}</option></select></label>
            {#each selected.resource.image.variants as variant}<label>{$t("images.url")}<input type="url" bind:value={variant.url} on:input={invalidate} /></label>{/each}
            <label>{$t("images.alt")}<input lang="pt-BR" bind:value={selected.resource.image.alt} on:input={invalidate} /></label><label>{$t("images.caption")}<input lang="pt-BR" bind:value={selected.resource.image.caption} on:input={invalidate} /></label>
            <div class="form-grid"><label>{$t("images.photographer")}<input bind:value={selected.resource.image.credit.photographer} on:input={invalidate} /></label><label>{$t("images.photographerUrl")}<input type="url" bind:value={selected.resource.image.credit.photographer_url} on:input={invalidate} /></label><label>{$t("images.provider")}<input bind:value={selected.resource.image.credit.provider} on:input={invalidate} /></label><label>{$t("images.originalUrl")}<input type="url" bind:value={selected.resource.image.credit.photo_url} on:input={invalidate} /></label><label>{$t("images.license")}<input bind:value={selected.resource.image.credit.license} on:input={invalidate} /></label><label>{$t("images.licenseUrl")}<input type="url" bind:value={selected.resource.image.credit.license_url} on:input={invalidate} /></label></div>
            <button on:click={() => { selected.resource.image = null; invalidate(); }}>{$t("images.remove")}</button>
          {:else}<p class="hint">{$t("images.unavailable")}</p><button on:click={addImage}>{$t("images.add")}</button>{/if}
        </section>
        <TranslationEditor sheet={selected} {translations} changed={() => translations = { ...translations }} />
        <section aria-labelledby="review-title"><h3 id="review-title">{$t("review.title")}</h3><label class="check"><input type="checkbox" bind:checked={selected.review.claim_support_verified} />{$t("review.textVerified")}</label><div class="form-grid"><label>{$t("review.reviewer")}<input bind:value={selected.review.reviewer} /></label><label>{$t("review.date")}<input type="date" bind:value={selected.review.reviewed_at} /></label></div><label>{$t("review.note")}<textarea rows="2" bind:value={selected.review.editorial_note}></textarea></label></section>
      {/key}
    </main>
  </div>
  <p class="feedback" role="status">{feedback}</p>
  <footer><span>{$t("storage.notice")}</span><span>timbre palette / editorial</span></footer>
</div>
