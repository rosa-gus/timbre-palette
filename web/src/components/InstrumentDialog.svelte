<script lang="ts">
  import { onDestroy } from "svelte";
  import { Dialog } from "bits-ui";
  import { getInstrument } from "../api/client";
  import type { InstrumentResource } from "../api/types";
  import ScrollArea from "./ScrollArea.svelte";
  import Arrow from "./Arrow.svelte";
  import ColorSwatch from "./ColorSwatch.svelte";
  import Dropdown from "./Dropdown.svelte";

  export let resource: InstrumentResource | null = null;
  export let open = false;
  export let loading = false;
  export let error = "";
  export let onClose: () => void = () => undefined;
  export let onOpenRelated: (slug: string) => void = () => undefined;

  let familyName = "";
  let related: InstrumentResource[] = [];
  let relationsLoading = false;
  let relationsError = "";
  let contextResource: InstrumentResource | null = null;
  let relationsController: AbortController | null = null;
  const cache = new Map<string, InstrumentResource>();
  const statusLabels: Record<string, string> = {
    sourced: "Fonte vinculada",
    reviewed: "Revisado",
    published: "Publicado",
  };
  const sourceTypeLabels: Record<string, string> = {
    book: "Livro",
    article: "Artigo",
    website: "Site",
    web: "Site",
    journal: "Periódico",
    encyclopedia: "Enciclopédia",
    institution: "Instituição",
  };

  $: sections =
    resource?.sections.filter(
      (section) =>
        section.status !== "draft" && section.status !== "deprecated",
    ) ?? [];
  $: if (open && !loading && resource && resource !== contextResource)
    void loadRelations(resource);
  $: if (!open) {
    relationsController?.abort();
    contextResource = null;
  }

  function date(value: string | null): string {
    if (!value) return "";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
      ? value
      : parsed.toLocaleDateString("pt-BR", { timeZone: "UTC" });
  }
  function language(value: string): string {
    return (
      new Intl.DisplayNames(["pt-BR"], { type: "language" }).of(value) ?? value
    );
  }
  function sourceId(id: string): string {
    return `instrument-source-${encodeURIComponent(resource?.slug ?? "")}-${encodeURIComponent(id)}`;
  }
  function sourceNumber(id: string): number {
    return (
      (resource?.sources.findIndex((source) => source.id === id) ?? -1) + 1
    );
  }
  function sourceMetaParts(
    source: InstrumentResource["sources"][number],
  ): string[] {
    return [
      source.contributors.join(", "),
      source.publisher,
      source.publication_date,
    ].filter((part): part is string => Boolean(part));
  }
  type Rgb = [number, number, number];
  function parseHex(value: string): Rgb {
    const normalized = value.replace(/^#/, "");
    return [
      Number.parseInt(normalized.slice(0, 2), 16),
      Number.parseInt(normalized.slice(2, 4), 16),
      Number.parseInt(normalized.slice(4, 6), 16),
    ];
  }
  function mix(first: Rgb, second: Rgb, amount: number): Rgb {
    return first.map((value, index) =>
      Math.round(value + (second[index] - value) * amount),
    ) as Rgb;
  }
  function hex(rgb: Rgb): string {
    return `#${rgb
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase()}`;
  }
  function toneSwatches(value: string): string[] {
    const base = parseHex(value);
    return [
      hex(mix(base, [0, 0, 0], 0.15)),
      hex(base),
      hex(mix(base, [255, 255, 255], 0.1)),
      hex(mix(base, [255, 255, 255], 0.2)),
    ];
  }
  function toneText(value: string): string {
    return hex(mix(parseHex(value), [0, 0, 0], 0.6));
  }
  async function loadRelations(current: InstrumentResource): Promise<void> {
    relationsController?.abort();
    const controller = new AbortController();
    relationsController = controller;
    contextResource = current;
    familyName = "";
    related = [];
    relationsError = "";
    const slugs = [
      ...new Set(
        [current.family_slug, ...current.related_slugs].filter(
          (slug): slug is string => !!slug && slug !== current.slug,
        ),
      ),
    ];
    relationsLoading = slugs.length > 0;
    const results = await Promise.allSettled(
      slugs.map(async (slug) => {
        const item =
          cache.get(slug) ?? (await getInstrument(slug, controller.signal));
        cache.set(slug, item);
        return item;
      }),
    );
    if (controller.signal.aborted) return;
    const items = results.flatMap((result) =>
      result.status === "fulfilled" ? [result.value] : [],
    );
    familyName =
      items.find((item) => item.slug === current.family_slug)?.name ?? "";
    related = items.filter((item) => current.related_slugs.includes(item.slug));
    relationsError = results.some(
      (result, index) =>
        result.status === "rejected" &&
        current.related_slugs.includes(slugs[index]),
    )
      ? "Algumas fichas relacionadas não estão disponíveis agora."
      : "";
    relationsLoading = false;
  }
  onDestroy(() => relationsController?.abort());
</script>

<Dialog.Root
  {open}
  onOpenChange={(value) => {
    open = value;
    if (!value) onClose();
  }}
>
  <Dialog.Portal>
    <Dialog.Overlay class="ui-dialog-overlay" />
    <Dialog.Content
      class="ui-dialog-content"
      style={`--instrument-tone:${resource?.tone?.highlight ?? "#F29191"};--instrument-tone-text:${toneText(resource?.tone?.highlight ?? "#F29191")};--instrument-shadow:${resource?.tone?.shadow ?? "#100e0e"}`}
    >
      <div class="ui-dialog-header">
        <div>
          <p class="eyebrow">
            {!loading && resource?.kind === "family"
              ? "FAMÍLIA SONORA"
              : "FICHA INSTRUMENTAL"}
          </p>
          <Dialog.Title class="ui-dialog-title"
            >{loading || error
              ? "Ficha instrumental"
              : (resource?.name ?? "Ficha instrumental")}</Dialog.Title
          >
          {#if !loading && !error && familyName}<p class="instrument-family">
              {familyName}
            </p>{/if}
        </div>
        <Dialog.Close class="ui-dialog-close" aria-label="Fechar ficha"
          >×</Dialog.Close
        >
      </div>
      <Dialog.Description class="visually-hidden"
        >Imagem, produção do som, funções musicais, conteúdo editorial e
        referências do instrumento.</Dialog.Description
      >
      {#key resource?.slug}
        <ScrollArea>
          {#if loading}
            <p class="instrument-message instrument-loading" role="status">
              <span class="loading-indicator" aria-hidden="true"></span>
              <span>Carregando ficha…</span>
            </p>
          {:else if error}
            <p class="instrument-message" role="alert">{error}</p>
          {:else if resource}
            <div class="instrument-sheet" data-instrument={resource.slug}>
              <aside
                class="instrument-visual"
                aria-label="Imagem do instrumento"
              >
                {#if resource.image?.variants.length}
                  <figure class="instrument-photo">
                    <img
                      src={resource.image.variants[0].url}
                      alt={resource.image.alt}
                      width={resource.image.variants[0].width}
                      height={resource.image.variants[0].height}
                    />
                    <figcaption class="instrument-photo-credit">
                      {#if resource.image.resolution === "exact"}<span
                          >{resource.image.caption}</span
                        >{/if}
                      {#if resource.image.credit.photographer_url}<a
                          href={resource.image.credit.photographer_url}
                          target="_blank"
                          rel="noreferrer"
                          >Foto: {resource.image.credit.photographer ??
                            "Ver crédito"}</a
                        >{:else if resource.image.credit.photographer}<span
                          >Foto: {resource.image.credit.photographer}</span
                        >{/if}
                      {#if resource.image.credit.license_url}<a
                          href={resource.image.credit.license_url}
                          target="_blank"
                          rel="noreferrer"
                          >{resource.image.credit.license ??
                            "Licença da imagem"}</a
                        >{/if}
                    </figcaption>
                  </figure>
                {:else}<div class="instrument-image-empty">
                    <span>{resource.name}</span><small
                      >Imagem ainda não disponível.</small
                    >
                  </div>{/if}
                <div
                  class="instrument-tones"
                  aria-label={`Variações do tom de ${resource.name}`}
                >
                  {#each toneSwatches(resource.tone?.highlight ?? "#F29191") as swatch}<ColorSwatch
                      color={swatch}
                      label={`Variação de tom de ${resource.name}`}
                    />{/each}
                </div>
                {#if resource.image && resource.image.resolution !== "exact"}<p
                    class="instrument-image-note"
                  >
                    {resource.image.caption}
                  </p>{/if}
              </aside>
              <div class="instrument-reading">
                <p class="instrument-description">{resource.description}</p>
                <section class="instrument-block" aria-label="Como produz som">
                  <h3 class="eyebrow">COMO PRODUZ SOM</h3>
                  <p>{resource.sound_production}</p>
                </section>
                {#if resource.common_roles.length}<section
                    class="instrument-block"
                    aria-label="Funções musicais"
                  >
                    <h3 class="eyebrow">FUNÇÕES MUSICAIS</h3>
                    <ul class="instrument-roles">
                      {#each resource.common_roles as role}<li>
                          {role}
                        </li>{/each}
                    </ul>
                  </section>{/if}
                {#each sections as section}
                  <section
                    class="instrument-block"
                    aria-label="Uma curiosidade"
                  >
                    <h3 class="eyebrow">
                      UMA CURIOSIDADE
                    </h3>
                    <p>
                      {section.text}
                      {#each section.citations as citation}{#if sourceNumber(citation.source_id)}<a
                            class="instrument-citation"
                            href={`#${sourceId(citation.source_id)}`}
                            aria-label={`Referência ${sourceNumber(citation.source_id)}`}
                            >[{sourceNumber(citation.source_id)}]</a
                          >{:else}<span class="instrument-review-note"
                            >Referência indisponível.</span
                          >{/if}{/each}
                    </p>
                    {#if !section.review.claim_support_verified}<p
                        class="instrument-review-note"
                      >
                        Revisão do suporte à afirmação pendente.
                      </p>{/if}
                    <Dropdown title="Sobre este trecho">
                      <div class="instrument-details">
                      <dl>
                        <div>
                          <dt>Conteúdo</dt>
                          <dd>
                            {section.content_type === "fact"
                              ? "Informação factual"
                              : "Síntese editorial"}
                          </dd>
                        </div>
                        <div>
                          <dt>Estado editorial</dt>
                          <dd>
                            {statusLabels[section.status] ?? section.status}
                          </dd>
                        </div>
                        <div>
                          <dt>Dados bibliográficos</dt>
                          <dd>
                            {section.review.source_metadata_verified
                              ? "Verificados"
                              : "Verificação pendente"}
                          </dd>
                        </div>
                        <div>
                          <dt>Suporte à afirmação</dt>
                          <dd>
                            {section.review.claim_support_verified
                              ? "Revisado"
                              : "Revisão pendente"}
                          </dd>
                        </div>
                        {#if section.review.reviewed_at}<div>
                            <dt>Revisão</dt>
                            <dd>
                              {date(
                                section.review.reviewed_at,
                              )}{#if section.review.reviewer}<span
                                  class="separator-indicator"
                                  aria-hidden="true">·</span
                                >{section.review.reviewer}{/if}
                            </dd>
                          </div>{/if}
                      </dl>
                      {#if section.review.editorial_note}<p>
                          {section.review.editorial_note}
                        </p>{/if}{#each section.citations as citation}{#if citation.locator || citation.note}<p
                          >
                            <strong
                              >Referência {sourceNumber(citation.source_id) ||
                                "indisponível"}:</strong
                            >
                            {citation.locator ?? ""}{#if citation.note}<span
                                class="separator-indicator"
                                aria-hidden="true">·</span
                              >{citation.note}{/if}
                          </p>{/if}{/each}
                      </div>
                    </Dropdown>
                  </section>
                {/each}
                {#if resource.related_slugs.length}<section
                    class="instrument-block"
                    aria-label="Instrumentos relacionados"
                  >
                    <h3 class="eyebrow">INSTRUMENTOS RELACIONADOS</h3>
                    <div class="instrument-related">
                      {#each related as item}<button
                          type="button"
                          on:click={() => onOpenRelated(item.slug)}
                          >{item.name} <Arrow direction="up-right" /></button
                        >{/each}
                    </div>
                    {#if relationsLoading}<p
                        class="instrument-review-note instrument-loading-note"
                        role="status"
                      >
                        <span class="loading-indicator" aria-hidden="true"></span>
                        <span>Carregando fichas relacionadas…</span>
                      </p>{/if}{#if relationsError}<p
                        class="instrument-review-note"
                        role="status"
                      >
                        {relationsError}
                      </p>{/if}
                  </section>{/if}
                {#if resource.further_reading?.length}
                  <section class="instrument-block" aria-label="Saiba mais">
                    <h3 class="eyebrow">SAIBA MAIS</h3>
                    <ul>
                      {#each resource.further_reading as article}
                        <li><a href={article.url} target="_blank" rel="noopener noreferrer">{article.title} <Arrow direction="up-right" /></a>{#if article.publisher}<p>{article.publisher}</p>{/if}</li>
                      {/each}
                    </ul>
                  </section>
                {/if}
                {#if resource.sources.length}<section
                    class="instrument-block"
                    aria-label="Referências"
                  >
                    <h3 class="eyebrow">REFERÊNCIAS</h3>
                    <ol class="instrument-sources">
                      {#each resource.sources as source, index}<li
                          id={sourceId(source.id)}
                        >
                          <span class="instrument-source-number"
                            >[{index + 1}]</span
                          >
                          <div>
                            {#if source.url}<a
                                class="instrument-source-title"
                                href={source.url}
                                target="_blank"
                                rel="noreferrer"
                                >{source.title}
                                <Arrow direction="up-right" /></a
                              >{:else}<span class="instrument-source-title"
                                >{source.title}</span
                              >{/if}
                            <p class="instrument-source-meta">
                              {#each sourceMetaParts(source) as part, index}{#if index > 0}<span
                                  class="separator-indicator"
                                  aria-hidden="true">·</span
                                >{/if}{part}{/each}
                            </p>
                            <Dropdown title="Ver detalhes da fonte">
                              <div class="instrument-details">
                              <dl>
                                <div>
                                  <dt>Tipo</dt>
                                  <dd>
                                    {sourceTypeLabels[source.source_type] ??
                                      source.source_type}
                                  </dd>
                                </div>
                                <div>
                                  <dt>Idioma</dt>
                                  <dd>{language(source.language)}</dd>
                                </div>
                                <div>
                                  <dt>Metadados</dt>
                                  <dd>
                                    {source.metadata_verified
                                      ? "Verificados"
                                      : "Verificação pendente"}
                                  </dd>
                                </div>
                                {#if source.locator}<div>
                                    <dt>Localizador</dt>
                                    <dd>{source.locator}</dd>
                                  </div>{/if}{#if source.license}<div>
                                    <dt>Licença</dt>
                                    <dd>{source.license}</dd>
                                  </div>{/if}{#if source.accessed_at}<div>
                                    <dt>Consultada em</dt>
                                    <dd>{date(source.accessed_at)}</dd>
                                  </div>{/if}{#if source.verified_at}<div>
                                    <dt>Verificada em</dt>
                                    <dd>{date(source.verified_at)}</dd>
                                  </div>{/if}
                              </dl>
                              {#if source.note}<p>{source.note}</p>{/if}
                              </div>
                            </Dropdown>
                          </div>
                        </li>{/each}
                    </ol>
                  </section>{/if}
                <Dropdown title="Sobre esta ficha">
                  <div class="instrument-details instrument-about">
                  <dl>
                    <div>
                      <dt>Procedência</dt>
                      <dd>
                        {resource.data_source === "mock"
                          ? "Dados demonstrativos"
                          : "Catálogo instrumental"}
                      </dd>
                    </div>
                    <div>
                      <dt>Catálogo</dt>
                      <dd>{resource.catalog_version}</dd>
                    </div>
                    <div>
                      <dt>Catálogo de imagens</dt>
                      <dd>{resource.image_catalog_version}</dd>
                    </div>
                  </dl>
                  </div>
                </Dropdown>
              </div>
            </div>
          {/if}
        </ScrollArea>
      {/key}
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
