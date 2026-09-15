<script lang="ts">
  import { onMount } from "svelte";
  import seedManifest from "./instruments.json";
  import type { InstrumentResource, EditorialReview, EditorialSection, FurtherReading } from "../../web/src/api/types";
  import { getStorageItem, isStorageAvailable, setStorageItem, storageKey } from "../../web/src/storage";

  type Reading = FurtherReading & { status: "draft" | "reviewed" | "published"; reviewer: string | null; reviewed_at: string | null };
  type Sheet = { resource: Omit<InstrumentResource, "further_reading"> & { further_reading: Reading[] }; review: EditorialReview; text_citations: { description: string[]; sound_production: string[] } };
  const seed = (Array.isArray(seedManifest) ? seedManifest : (seedManifest as { instruments: unknown[] }).instruments) as Sheet[];
  const editorialStorageKey = storageKey("editorial", "instruments");
  let sheets: Sheet[] = structuredClone(seed) as Sheet[];
  let selectedSlug = sheets[0].resource.slug;
  let search = "";
  let feedback = "";
  let storageReady = false;
  let storageAvailable = true;
  $: selected = sheets.find((sheet) => sheet.resource.slug === selectedSlug) ?? sheets[0];
  $: visible = sheets.filter(({ resource }) => `${resource.name} ${resource.slug}`.toLowerCase().includes(search.toLowerCase()));
  $: if (storageReady && storageAvailable) persist(sheets, selected);

  onMount(() => {
    try {
      if (!isStorageAvailable()) throw new Error("Armazenamento indisponível");
      const saved = getStorageItem<unknown>(editorialStorageKey);
      if (saved && typeof saved === "object") {
        const parsed = saved as Record<string, unknown>;
        const savedInstruments = Array.isArray(parsed.instruments) ? parsed.instruments as Sheet[] : [];
        const seedSlugs = new Set(seed.map((item) => item.resource.slug));
        const savedSlugs = savedInstruments.map((sheet) => sheet.resource?.slug);
        if (parsed.schema_version !== 1 || !Array.isArray(parsed.instruments) ||
            new Set(savedSlugs).size !== savedSlugs.length ||
            savedInstruments.some((sheet) => !seedSlugs.has(sheet.resource?.slug) ||
              !Array.isArray(sheet.resource?.sources) || Array.isArray(sheet.resource?.sections) === false ||
              !Array.isArray(sheet.resource?.further_reading) || !sheet.review || !sheet.text_citations)) {
          throw new Error("Formato incompatível");
        }
        const savedBySlug = new Map(savedInstruments.map((sheet) => [sheet.resource.slug, sheet]));
        sheets = seed.map((item) => savedBySlug.get(item.resource.slug) ?? structuredClone(item)) as Sheet[];
      }
    } catch {
      storageAvailable = false;
      feedback = "Não foi possível carregar as revisões locais. Os dados iniciais estão visíveis; exporte suas alterações para preservá-las.";
    }
    storageReady = true;
  });

  function persist(instruments: Sheet[], _selected: Sheet) {
    if (!setStorageItem(editorialStorageKey, { schema_version: 1, instruments })) {
      storageAvailable = false;
      feedback = "Armazenamento local indisponível. Exporte a revisão para preservar as alterações.";
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
        errors.push(`${label}: preencha nome, descrição e produção do som.`);
      const sourceIds = new Set(resource.sources.map((source) => source.id));
      for (const source of resource.sources) {
        if (!source.title.trim() || (source.url && !httpUrl(source.url))) errors.push(`${label}: confira título e URL da fonte.`);
      }
      for (const field of ["description", "sound_production"] as const) {
        if (sheet.text_citations[field].some((id) => !sourceIds.has(id))) errors.push(`${label}: referência inexistente em ${field}.`);
      }
      if (review.claim_support_verified && (!review.reviewer?.trim() || !review.reviewed_at))
        errors.push(`${label}: informe responsável e data da revisão.`);
      for (const section of resource.sections) {
        if (!section.text.trim()) errors.push(`${label}: remova a curiosidade vazia ou escreva o texto.`);
        if (section.citations.some((citation) => !sourceIds.has(citation.source_id))) errors.push(`${label}: referência inexistente na curiosidade.`);
        if (section.status !== "draft" && !section.citations.length) errors.push(`${label}: curiosidade com fonte vinculada precisa de uma citação.`);
        if (["reviewed", "published"].includes(section.status) && (!section.review.claim_support_verified || !section.review.reviewer?.trim() || !section.review.reviewed_at))
          errors.push(`${label}: conclua a revisão da curiosidade antes de promovê-la.`);
      }
      for (const link of resource.further_reading) {
        if (!link.title.trim() || !httpUrl(link.url)) errors.push(`${label}: confira título e URL de Saiba mais.`);
        if (link.status !== "draft" && (!link.reviewer?.trim() || !link.reviewed_at))
          errors.push(`${label}: informe a revisão do link de Saiba mais.`);
      }
      if (resource.image && (!resource.image.asset_id.trim() || !resource.image.alt.trim() || !resource.image.variants.length || !httpUrl(resource.image.variants[0].url)))
        errors.push(`${label}: confira identificador, descrição e URL da imagem.`);
    }
    return errors;
  }
  function exportRevision() {
    const snapshot = structuredClone(sheets);
    for (const sheet of snapshot) {
      const verified = (ids: string[]) => ids.length > 0 && ids.every((id) => sheet.resource.sources.find((source) => source.id === id)?.metadata_verified);
      sheet.review.source_metadata_verified = verified([...sheet.text_citations.description, ...sheet.text_citations.sound_production]);
      for (const section of sheet.resource.sections) section.review.source_metadata_verified = verified(section.citations.map((citation) => citation.source_id));
    }
    const errors = validate(snapshot);
    if (errors.length) { feedback = errors.join("\n"); return; }
    const blob = new Blob([JSON.stringify({ schema_version: 1, exported_at: new Date().toISOString(), instruments: snapshot }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "timbre-instrument-review.json"; anchor.click();
    URL.revokeObjectURL(url);
    feedback = "Revisão exportada. A exportação não publica alterações na API.";
  }
</script>

<div class="app-shell">
  <header class="topbar"><a href="./" class="brand">timbre palette <span>editorial</span></a><span class="eyebrow">FICHAS DE INSTRUMENTOS</span></header>
  <div class="page-heading"><div><p class="eyebrow">01 / CATÁLOGO EDITORIAL</p><h1>Instrumentos,<br />em poucas palavras.</h1><p class="intro">Textos breves, imagens, referências e caminhos para saber mais.</p></div><button class="primary-action" on:click={exportRevision}>Exportar revisão JSON ↗</button></div>
  <div class="editor-layout">
    <aside class="catalog-sidebar" aria-label="Instrumentos e famílias">
      <label for="search">Buscar ficha</label><input id="search" type="search" bind:value={search} placeholder="Nome ou slug" />
      <nav aria-label="Fichas"><ul class="sheet-list">{#each visible as sheet}<li><button class:selected={sheet.resource.slug === selectedSlug} on:click={() => selectedSlug = sheet.resource.slug}><strong>{sheet.resource.name}</strong><span>{sheet.resource.kind === "family" ? "Família sonora" : "Instrumento"} · {sheet.review.claim_support_verified ? "Revisado" : "Em revisão"}</span></button></li>{/each}</ul></nav>
      {#if !visible.length}<p>Nenhuma ficha encontrada.</p>{/if}
    </aside>
    <main aria-label="Editar ficha">
      {#key selected.resource.slug}
        <div class="sheet-heading"><h2>{selected.resource.name}</h2><span class="eyebrow">{selected.resource.slug}</span></div>
        <section aria-labelledby="text-title"><h3 id="text-title">Ficha breve</h3>
          <div class="form-grid"><label>Nome<input bind:value={selected.resource.name} on:input={invalidate} /></label><label>Família<select bind:value={selected.resource.family_slug} disabled={selected.resource.kind === "family"} on:change={invalidate}><option value={null}>A própria família</option>{#each sheets.filter((sheet) => sheet.resource.kind === "family") as family}<option value={family.resource.slug}>{family.resource.name}</option>{/each}</select></label></div>
          <label>Descrição<textarea rows="3" maxlength="600" bind:value={selected.resource.description} on:input={invalidate}></textarea></label>
          <label>Como produz som<textarea rows="2" maxlength="400" bind:value={selected.resource.sound_production} on:input={invalidate}></textarea></label>
          <p class="hint">Prefira duas ou três frases. História e origem não fazem parte da ficha.</p>
          <fieldset><legend>Fontes da descrição</legend>{#each selected.resource.sources as source}<label class="check"><input type="checkbox" value={source.id} bind:group={selected.text_citations.description} on:change={invalidate} />{source.title || "Fonte sem título"}</label>{/each}</fieldset>
          <fieldset><legend>Fontes da produção do som</legend>{#each selected.resource.sources as source}<label class="check"><input type="checkbox" value={source.id} bind:group={selected.text_citations.sound_production} on:change={invalidate} />{source.title || "Fonte sem título"}</label>{/each}</fieldset>
        </section>
        <section aria-labelledby="curiosity-title"><h3 id="curiosity-title">Curiosidade <span class="hint">opcional</span></h3>
          {#if !selected.resource.sections.length}<p class="hint">A ficha pode ser publicada sem curiosidade.</p><button on:click={addCuriosity}>Adicionar curiosidade</button>{/if}
          {#each selected.resource.sections as section}
            <label>Texto breve<textarea rows="3" maxlength="600" bind:value={section.text} on:input={() => { section.review.claim_support_verified = false; section.review.reviewed_at = null; }}></textarea></label>
            <label>Estado<select bind:value={section.status}><option value="draft">Rascunho</option><option value="sourced">Fonte vinculada</option><option value="reviewed">Revisado</option><option value="published">Publicado</option><option value="deprecated">Retirado</option></select></label>
            <fieldset><legend>Fontes da curiosidade</legend>{#each selected.resource.sources as source}<label class="check"><input type="checkbox" checked={section.citations.some((citation) => citation.source_id === source.id)} on:change={(event) => updateCitation(section, source.id, event.currentTarget.checked)} />{source.title || "Fonte sem título"}</label>{/each}</fieldset>
            {#each section.citations as citation}<label>Localizador — {selected.resource.sources.find((source) => source.id === citation.source_id)?.title}<input bind:value={citation.locator} placeholder="Página, seção ou verbete" /></label>{/each}
            <label class="check"><input type="checkbox" bind:checked={section.review.claim_support_verified} />Suporte da curiosidade revisado</label>
            <div class="form-grid"><label>Responsável<input bind:value={section.review.reviewer} /></label><label>Data da revisão<input type="date" bind:value={section.review.reviewed_at} /></label></div>
            <button class="danger-action" on:click={removeCuriosity}>Remover curiosidade</button>
          {/each}
        </section>
        <section aria-labelledby="reading-title"><h3 id="reading-title">Saiba mais</h3><p class="hint">Artigos para aprofundamento. Estes links não substituem as fontes dos textos.</p>
          {#each selected.resource.further_reading as link, index}<div class="item-card"><label>Título<input bind:value={link.title} on:input={() => link.status = "draft"} /></label><div class="form-grid"><label>URL<input type="url" bind:value={link.url} on:input={() => link.status = "draft"} /></label><label>Instituição ou autor<input bind:value={link.publisher} on:input={() => link.status = "draft"} /></label></div><div class="form-grid"><label>Responsável pela revisão<input bind:value={link.reviewer} /></label><label>Data da revisão<input type="date" bind:value={link.reviewed_at} /></label></div><label>Estado<select bind:value={link.status}><option value="draft">Rascunho</option><option value="reviewed">Revisado</option><option value="published">Publicado</option></select></label><button on:click={() => selected.resource.further_reading = selected.resource.further_reading.filter((_, i) => i !== index)}>Remover link</button></div>{/each}
          <button on:click={addReading}>Adicionar artigo</button>
        </section>
        <section aria-labelledby="sources-title"><h3 id="sources-title">Fontes dos textos</h3>
          {#each selected.resource.sources as source}<div class="item-card"><label>Título<input bind:value={source.title} on:input={() => { source.metadata_verified = false; invalidate(); }} /></label><div class="form-grid"><label>URL<input type="url" bind:value={source.url} on:input={() => { source.metadata_verified = false; invalidate(); }} /></label><label>Instituição ou editora<input bind:value={source.publisher} on:input={() => { source.metadata_verified = false; invalidate(); }} /></label></div><label>Localizador<input bind:value={source.locator} on:input={invalidate} /></label><label>Observações<textarea rows="2" bind:value={source.note}></textarea></label><div class="form-grid"><label>Consultada em<input type="date" bind:value={source.accessed_at} /></label><label>Metadados verificados em<input type="date" bind:value={source.verified_at} /></label></div><label class="check"><input type="checkbox" bind:checked={source.metadata_verified} />Metadados bibliográficos verificados</label><button on:click={() => removeSource(source.id)}>Remover fonte</button></div>{/each}
          <button on:click={addSource}>Adicionar fonte</button>
        </section>
        <section aria-labelledby="image-title"><h3 id="image-title">Imagem e créditos</h3>
          {#if selected.resource.image}<div class="form-grid"><label>Asset<input bind:value={selected.resource.image.asset_id} on:input={invalidate} /></label><label>Instrumento fotografado<input bind:value={selected.resource.image.depicted_instrument_slug} on:input={invalidate} /></label></div><label>Correspondência<select bind:value={selected.resource.image.resolution} on:change={invalidate}><option value="exact">Instrumento exato</option><option value="related">Instrumento relacionado</option><option value="family">Família</option></select></label>
            {#each selected.resource.image.variants as variant}<label>URL da imagem<input type="url" bind:value={variant.url} on:input={invalidate} /></label>{/each}
            <label>Descrição acessível<input bind:value={selected.resource.image.alt} on:input={invalidate} /></label><label>Legenda<input bind:value={selected.resource.image.caption} on:input={invalidate} /></label>
            <div class="form-grid"><label>Fotógrafo<input bind:value={selected.resource.image.credit.photographer} on:input={invalidate} /></label><label>URL do fotógrafo<input type="url" bind:value={selected.resource.image.credit.photographer_url} on:input={invalidate} /></label><label>Provedor<input bind:value={selected.resource.image.credit.provider} on:input={invalidate} /></label><label>URL da fotografia original<input type="url" bind:value={selected.resource.image.credit.photo_url} on:input={invalidate} /></label><label>Licença<input bind:value={selected.resource.image.credit.license} on:input={invalidate} /></label><label>URL da licença<input type="url" bind:value={selected.resource.image.credit.license_url} on:input={invalidate} /></label></div>
            <button on:click={() => { selected.resource.image = null; invalidate(); }}>Remover imagem da ficha</button>
          {:else}<p class="hint">Sem imagem associada.</p><button on:click={addImage}>Associar imagem</button>{/if}
        </section>
        <section aria-labelledby="review-title"><h3 id="review-title">Revisão da ficha</h3><label class="check"><input type="checkbox" bind:checked={selected.review.claim_support_verified} />Descrição e produção do som revisadas</label><div class="form-grid"><label>Responsável<input bind:value={selected.review.reviewer} /></label><label>Data da revisão<input type="date" bind:value={selected.review.reviewed_at} /></label></div><label>Nota editorial<textarea rows="2" bind:value={selected.review.editorial_note}></textarea></label></section>
      {/key}
    </main>
  </div>
  <p class="feedback" role="status">{feedback}</p>
  <footer><span>Revisões salvas neste navegador · exportação manual</span><span>timbre palette / editorial</span></footer>
</div>
