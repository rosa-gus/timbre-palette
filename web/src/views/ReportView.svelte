<script lang="ts">
  import Arrow from "../components/Arrow.svelte";
  import Badge from "../components/Badge.svelte";
  import Button from "../components/Button.svelte";
  import ColorSwatch from "../components/ColorSwatch.svelte";
  import Dropdown from "../components/Dropdown.svelte";
  import Tooltip from "../components/Tooltip.svelte";
  import { normalizePathname } from "../navigation";
  import { getPortraitCopy } from "../portrait";
  import { createAsciiArtwork } from "../sharing/ascii";
  import type {
    AnalysisStatus,
    Confidence,
    PaletteReport,
    SectionAvailability,
  } from "../api/types";
  import type { FamilyPresence } from "../api/types";

  type SectionId = "portrait" | "palette" | "discovery" | "share";
  type SectionOption = {
    value: string;
    label: string;
    disabled?: boolean;
    note?: string;
  };
  export let report: PaletteReport;
  export let isExample = false;
  export let embedded = false;
  export let hydrationPending = false;
  $: portrait = getPortraitCopy(report);
  $: asciiArtwork = createAsciiArtwork(report.families);
  $: discoveryAvailable =
    !!report.discovery && getAvailability("discovery") === "available";
  export let sectionOptions: SectionOption[] = [];
  export let periodLabels: Record<string, string>;
  export let statusLabels: Record<AnalysisStatus, string>;
  export let confidenceLabels: Record<Confidence, string>;
  export let shareFeedback = "";
  export let onOpenInstrument: () => void = () => undefined;
  export let onOpenInstrumentSlug: (slug: string) => void = () => undefined;
  export let onGenerateShare: () => void = () => undefined;
  export let getAvailability: (
    section: SectionId,
  ) => SectionAvailability = () => "insufficient_coverage";
  const homePath = normalizePathname();

  function percent(value: number): string {
    return `${Math.round(value * 100)}%`;
  }

  type Rgb = [number, number, number];
  const fallbackTone = "#F29191";

  function parseHex(value: string): Rgb | null {
    const normalized = value.trim().replace(/^#/, "");
    if (!/^[0-9a-f]{6}$/i.test(normalized)) return null;
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

  function toneText(value: string): string {
    const base = parseHex(value) ?? parseHex(fallbackTone)!;
    return hex(mix(base, [0, 0, 0], 0.6));
  }

  function toneSwatches(family: FamilyPresence): string[] {
    const base =
      parseHex(family.tone?.highlight ?? fallbackTone) ??
      parseHex(fallbackTone)!;
    const black: Rgb = [0, 0, 0];
    const white: Rgb = [255, 255, 255];
    return [
      hex(mix(base, black, 0.15)),
      hex(base),
      hex(mix(base, white, 0.1)),
      hex(mix(base, white, 0.2)),
    ];
  }

  export let sharePreviewUrl = "";
  export let shareBusy = false;
  export let canShareImage = false;
  export let onDownloadShare: () => void = () => undefined;
  export let onShareImage: () => void = () => undefined;
  const natureLabels: Record<string, string> = {
    acoustic: "Acústica",
    electric: "Elétrica",
    electronic: "Eletrônica",
    sampled: "Sampleada",
    hybrid: "Híbrida",
    unknown: "Ainda não identificada",
  };
</script>

<section
  class="report-view"
  class:embedded
  aria-labelledby="report-title"
  style={`--report-tone:${report.families[0]?.tone?.highlight ?? fallbackTone};--report-tone-text:${toneText(report.families[0]?.tone?.highlight ?? fallbackTone)}`}
>
  {#if !embedded}<div class="report-back">
      <a class="back-link" href={homePath}><Arrow direction="left" />Voltar</a>
    </div>{/if}
  {#if !embedded}<div class="archive-header">
      <p class="eyebrow">
        ESCUTA DE {isExample
          ? report.profile.realname || "Besouro Hércules"
          : `@${report.profile.username}`}
        {#if isExample}<Badge tone="accent">EXEMPLO</Badge>{/if}
      </p>
      <div class="archive-period">
        <span
          >{periodLabels[report.profile.period]}<span
            class="separator-indicator"
            aria-hidden="true">·</span
          >Análise {statusLabels[report.analysis.status]}</span
        >{#if report.analysis.data_source !== "catalog"}<span
            >Dados {report.analysis.data_source === "mock"
              ? "demonstrativos"
              : "híbridos"}</span
          >{/if}
      </div>
      <a class="image-link" href="#share"
        >{isExample ? "Visualizar imagem do exemplo" : "Visualizar minha imagem"}
        <Arrow direction="up-right" /></a
      >
    </div>{/if}
  <nav class="report-index" aria-label="Índice do retrato">
    {#each sectionOptions as option, index}
      <a
        href={`#${option.value}`}
        data-unavailable={option.disabled || undefined}
        title={option.note}
        >{String(index + 1).padStart(2, "0")} / {option.label}</a
      >
    {/each}
  </nav>
  <section id="portrait" class="portrait" aria-labelledby="report-title">
    <div class="portrait-copy">
      <p class="eyebrow">01 / SEU RETRATO INSTRUMENTAL</p>
      {#if embedded}<h2 class="portrait-title" id="report-title">
          {portrait.title}
        </h2>
      {:else}<h1 id="report-title">{portrait.title}</h1>{/if}
      <p class="large-copy">
        {portrait.summary}
      </p>
      {#if portrait.disclaimer}<p class="disclaimer">
          {portrait.disclaimer}
        </p>{/if}
    </div>
    <div class="portrait-caption">
      <span>{report.profile.tracks_analyzed} faixas</span><span
        >{report.profile.total_plays} reproduções</span
      ><span
        >{percent(report.analysis.coverage_tracks)} das faixas cobertas
          <Tooltip ariaLabel="O que significa a cobertura?" triggerLabel="[?]">
            <p>
              Cobertura é a proporção das faixas analisadas com evidências
              instrumentais suficientes para contribuir para sua paleta.
            </p>
            <p>Faixas sem essas evidências ficam fora do cálculo.</p>
            {#if hydrationPending}<p class="tooltip-note">
                <span class="loading-indicator" aria-hidden="true"></span>
                <span>Mais dados podem chegar depois.</span>
              </p>{/if}
          </Tooltip>
        </span
      >
    </div>
    <div class="composition" aria-label="Composição da paleta instrumental">
      {#each report.families as family}<ColorSwatch
          color={family.tone?.highlight ?? fallbackTone}
          label={`${family.name} (${percent(family.share)})`}
          presenceName={family.name}
          className="composition-swatch"
          style={`flex-grow:${family.share};`}
        />{/each}
    </div>
    <p class="color-hint">
      Selecione uma cor para ver o código e copiá-lo.
    </p>
    <div class="instrument-grid">
      {#each report.families.slice(0, 3) as family, index}
        <figure
          class="instrument-card"
          style={`--family-tone:${family.tone?.highlight ?? fallbackTone};--family-tone-text:${toneText(family.tone?.highlight ?? fallbackTone)}`}
        >
          <figcaption>
            <span class="eyebrow"
              >{String(index + 1).padStart(2, "0")} / PRESENÇA DOMINANTE</span
            >
            <div class="instrument-name">
              <h2>
                <button
                  type="button"
                  class="family-card-link"
                  aria-label={`Abrir ficha de ${family.name}`}
                  on:click={() => onOpenInstrumentSlug(family.slug)}
                  >{family.name}</button
                >
              </h2>
              <strong>{percent(family.share)}</strong>
            </div>
          </figcaption>
          {#if family.image?.variants.length}<div class="credited-image">
              <img
                src={family.image.variants[0].url}
                alt={family.image.alt}
                width={family.image.variants[0].width}
                height={family.image.variants[0].height}
              />
              <p class="photo-caption">
                <span class="photo-caption-text">{family.image.caption}</span>
                {#if family.image.credit.photographer_url}<a
                    href={family.image.credit.photographer_url}
                    target="_blank"
                    rel="noreferrer">Foto: {family.image.credit.photographer}</a
                  >{:else if family.image.credit.photographer}<span
                    >Foto: {family.image.credit.photographer}</span
                  >{/if}
              </p>
            </div>{:else}<div class="image-placeholder">{family.name}</div>{/if}
          <div
            class="tone-strip"
            aria-label={`Variações do tom de ${family.name}`}
          >
            {#each toneSwatches(family) as swatch}<ColorSwatch
                color={swatch}
                label={`Variação de tom de ${family.name}`}
              />{/each}
          </div>
        </figure>
      {/each}
    </div>
  </section>
  <section id="palette" class="archive-section" aria-labelledby="palette-title">
    <div class="section-heading">
      <p class="eyebrow">02 / PALETA</p>
      <h2 id="palette-title">As presenças da sua escuta.</h2>
      <p class="palette-scope">Entre as fontes identificadas</p>
    </div>
    <div class="palette-layout">
      <div class="family-list" aria-label="Famílias instrumentais">
        {#each report.families as family}<div class="family-row">
            <div class="family-label">
              <button
                type="button"
                class="family-link"
                aria-label={`Abrir ficha de ${family.name}`}
                on:click={() => onOpenInstrumentSlug(family.slug)}
                >{family.name}</button
              ><Badge tone="neutral"
                >{confidenceLabels[family.confidence]}</Badge
              >
            </div>
            <div
              class="share-bar"
              aria-label={`${family.name}: ${percent(family.share)}`}
            >
              <ColorSwatch
                color={family.tone?.highlight ?? fallbackTone}
                label={`${family.name} (${percent(family.share)})`}
                className="share-swatch"
                style={`width:${family.share * 100}%;`}
              />
            </div>
            <strong>{percent(family.share)}</strong>
          </div>{/each}
      </div>
      <aside>
        <p class="eyebrow">NATUREZA SONORA</p>
        {#if report.sound_balance}<ul class="compact-list">
            {#each Object.entries(report.sound_balance)
              .filter(([, value]) => Math.round(value * 100) > 0)
              .sort(([, a], [, b]) => b - a) as [nature, value]}<li>
                <span>{natureLabels[nature] ?? nature}</span><strong
                  >{percent(value)}</strong
                >
              </li>{/each}
          </ul>{:else}<p>A natureza sonora ainda está sendo apurada.</p>{/if}
      </aside>
    </div>
    <div class="analysis-details">
      <Dropdown title="Sobre os dados desta leitura">
        <p>{report.analysis.notice}</p>
        <p>
          Cobertura: {percent(report.analysis.coverage_tracks)} das faixas / {percent(
            report.analysis.coverage_plays,
          )} das reproduções.
        </p>
        <p>
          Voz documentada: {report.analysis.vocal_presence.documented_tracks} faixas,
          {report.analysis.vocal_presence.documented_artists} artistas e
          {report.analysis.vocal_presence.documented_plays} reproduções ({percent(
            report.analysis.vocal_presence.play_ratio,
          )} das reproduções).
        </p>
        <p>
          Catálogo {report.analysis.catalog_version ?? "não publicado"}
          <span class="separator-indicator" aria-hidden="true">·</span>
          Método {report.analysis.methodology_version}
        </p>
      </Dropdown>
    </div>
  </section>
  <section
    id="discovery"
    class="archive-section"
    class:unavailable-section={!discoveryAvailable}
    aria-labelledby="discovery-title"
  >
    {#if discoveryAvailable && report.discovery}
      <div class="section-heading">
        <p class="eyebrow">03 / DESCOBERTA</p>
        <h2 id="discovery-title">Uma presença inesperada.</h2>
      </div>
      <div class="discovery-layout">
        {#if report.discovery.image?.variants.length}<figure
            class="credited-image"
          >
            <img
              src={report.discovery.image.variants[0].url}
              alt={report.discovery.image.alt}
              width={report.discovery.image.variants[0].width}
              height={report.discovery.image.variants[0].height}
              loading="lazy"
            />
            <figcaption class="photo-caption">
              <span class="photo-caption-text"
                >{report.discovery.image.caption}</span
              >{#if report.discovery.image.credit.photographer_url}
                <a
                  href={report.discovery.image.credit.photographer_url}
                  target="_blank"
                  rel="noreferrer"
                  >Foto: {report.discovery.image.credit.photographer}</a
                >{/if}
            </figcaption>
          </figure>{/if}
        <div>
          <h3>{report.discovery.title}</h3>
          <p class="large-copy">{report.discovery.summary}</p>
          <Button variant="secondary" on:click={onOpenInstrument}
            >Explorar instrumento <Arrow direction="right" /></Button
          >
        </div>
      </div>
    {:else}
      <p class="eyebrow">03 / DESCOBERTA</p>
      <p id="discovery-title">
        Nenhuma descoberta para destacar neste período.
      </p>
    {/if}
  </section>
  <section
    id="share"
    class="archive-section share-section"
    aria-labelledby="share-title"
  >
    <div class="share-copy">
      <p class="eyebrow">04 / {isExample ? "RETRATO DE EXEMPLO" : "SEU RETRATO PARA COMPARTILHAR"}</p>
      <h2 id="share-title">
        {isExample ? "Leve esta paleta" : "Leve sua paleta"}<br />com você.
      </h2>
      <p class="large-copy">
        {isExample
          ? "As cores, os instrumentos e o retrato da escuta do Besouro Hércules em uma imagem para guardar ou compartilhar."
          : "As cores, os instrumentos e o retrato da sua escuta em uma imagem para guardar ou compartilhar."}
      </p>
      <Button variant="primary" disabled={shareBusy} on:click={onGenerateShare}
        >{sharePreviewUrl
          ? "Atualizar imagem"
          : isExample
            ? "Preparar imagem do exemplo"
            : "Preparar minha imagem"}
        <Arrow direction="right" /></Button
      >{#if sharePreviewUrl}{#if canShareImage}<Button
          variant="secondary"
          on:click={onShareImage}>Compartilhar</Button
        >{/if}<Button
          variant="secondary"
          on:click={onDownloadShare}>Baixar imagem</Button
        >{/if}
      <p class="share-feedback" aria-live="polite">{shareFeedback}</p>
    </div>
    <div class="share-preview">
      {#if sharePreviewUrl}<img
          src={sharePreviewUrl}
          alt={`Imagem pronta para compartilhar: paleta de ${isExample ? report.profile.realname || "Besouro Hércules" : report.profile.username}`}
        />{:else}<div class="share-card-preview">
          <span class="eyebrow"
            >TIMBRE PALETTE / {isExample
              ? report.profile.realname || "Besouro Hércules"
              : `@${report.profile.username}`}
            <span class="separator-indicator" aria-hidden="true">·</span>
            {#if isExample}EXEMPLO <span class="separator-indicator" aria-hidden="true">·</span> {/if}
            {periodLabels[report.profile.period]}</span
          ><strong>{portrait.title}</strong>
          <p class="preview-summary">{portrait.summary}</p>
          <div
            class="preview-specimens"
            style={`--specimen-count:${Math.max(1, asciiArtwork.length)}`}
          >
            {#each asciiArtwork as item, index}<div
                class="preview-specimen"
                style={`--specimen-tone:${item.color}`}
              >
                <div class="preview-ascii-drawing" aria-hidden="true">
                  <pre
                    style={`font-size:${Math.min(9, 100 / (item.columns * 0.6), 88 / (item.lines.length * 0.95))}cqw`}>{item.lines.join(
                      "\n",
                    )}</pre>
                </div>
                <span class="preview-index"
                  >{String(index + 1).padStart(2, "0")}</span
                >
                <span class="preview-family">{item.family.name}</span>
                <span class="preview-share">{percent(item.family.share)}</span>
              </div>{/each}
          </div>
          <span class="preview-note"
            >Interpretação musical <span
              class="separator-indicator"
              aria-hidden="true">·</span
            > TIMBRE PALETTE</span
          >
        </div>{/if}
    </div>
  </section>
</section>

<style>
  .report-view {
    width: 100%;
    max-width: 1320px;
    margin: 0 auto;
    padding: 54px 0 32px;
  }
  .report-view.embedded {
    padding-top: 0;
  }
  .report-back {
    margin-bottom: 20px;
  }
  .back-link {
    display: inline-block;
    padding-bottom: 8px;
    color: var(--accent-soft);
    font-family: var(--meta);
    font-size: 13px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    text-decoration: none;
  }
  .back-link:hover {
    color: var(--accent-pale);
  }
  .archive-header {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 20px;
    padding-bottom: 24px;
    border-bottom: 1px solid var(--line);
  }
  .archive-header .eyebrow {
    margin: 0;
    color: var(--ink);
  }
  .archive-period {
    display: flex;
    flex-wrap: wrap;
    gap: 12px 24px;
    color: var(--muted);
    font-family: var(--meta);
    font-size: 13px;
  }
  .image-link {
    margin-left: auto;
    padding: 12px 18px;
    background: var(--report-tone);
    color: #000;
    text-decoration: none;
    font-size: 14px;
    font-weight: 600;
  }
  .report-index {
    display: flex;
    flex-wrap: wrap;
    gap: 12px 30px;
    padding: 20px 0;
  }
  .report-index a {
    color: var(--muted);
    font-family: var(--meta);
    font-size: 12px;
    text-decoration: none;
  }
  .report-index a:hover {
    color: var(--ink);
    text-decoration: underline;
    text-underline-offset: 5px;
  }
  .report-index a[data-unavailable="true"] {
    color: var(--quiet);
  }
  .portrait {
    padding-top: 40px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 220px;
    gap: 32px;
  }
  h1,
  .portrait-title {
    max-width: 950px;
    margin: 12px 0 24px;
    font-size: clamp(2.5rem, 4vw, 4rem);
    line-height: 1.05;
  }
  h2 {
    font-size: clamp(1.6rem, 2.6vw, 2.5rem);
    line-height: 1.15;
    margin: 0;
  }
  h3 {
    font-size: 1.8rem;
    line-height: 1.2;
  }
  .large-copy {
    max-width: 760px;
    color: var(--muted);
    font-size: clamp(1rem, 1.4vw, 1.2rem);
    line-height: 1.65;
    margin: 0 0 24px;
  }
  .disclaimer {
    max-width: 760px;
    font-size: 13px;
    color: var(--muted);
    margin: 0;
  }
  .portrait-caption {
    display: grid;
    align-content: end;
    gap: 8px;
    padding-bottom: 4px;
    color: var(--muted);
    font-family: var(--meta);
    font-size: 13px;
  }
  .portrait-caption span:last-child {
    margin-top: 12px;
    font-family: var(--display);
  }
  .composition {
    grid-column: 1/-1;
    display: flex;
    height: 42px;
    gap: 4px;
    margin-top: 8px;
  }
  .color-hint {
    grid-column: 1/-1;
    margin: -2px 0 16px;
    color: var(--muted);
    font: 12px var(--meta);
  }
  .instrument-grid {
    grid-column: 1/-1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 24px;
  }
  figure {
    margin: 0;
    min-width: 0;
  }
  .instrument-card figcaption {
    padding: 4px 0 18px;
  }
  .instrument-card .eyebrow {
    font-size: 11px;
    color: var(--muted);
  }
  .instrument-name {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin-top: 12px;
  }
  .instrument-name h2 {
    font-size: clamp(1.2rem, 1.8vw, 1.75rem);
  }
  .family-card-link,
  .family-link {
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    text-align: left;
    text-decoration: underline;
    text-decoration-color: transparent;
    text-underline-offset: 5px;
    transition:
      color 150ms ease,
      text-decoration-color 150ms ease;
  }
  .family-card-link:hover,
  .family-card-link:focus-visible,
  .family-link:hover,
  .family-link:focus-visible {
    color: var(--accent-soft);
    text-decoration-color: currentColor;
  }
  .instrument-name strong {
    font-family: var(--meta);
    font-size: 18px;
    font-weight: 400;
    color: var(--family-tone-text);
  }
  .instrument-card .credited-image > img,
  .image-placeholder {
    width: 100%;
    height: 230px;
    object-fit: cover;
    display: block;
    background: var(--panel);
  }
  .image-placeholder {
    display: grid;
    place-items: center;
    color: var(--family-tone-text);
  }
  .tone-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 3px;
    height: 24px;
    margin-top: 4px;
  }
  .credited-image {
    position: relative;
  }
  .photo-caption {
    position: absolute;
    bottom: 0;
    right: 0;
    max-width: 100%;
    display: grid;
    gap: 4px;
    padding: 12px 16px;
    margin: 0;
    background: rgb(0 0 0 / 0.82);
    color: var(--on-dark);
    font-size: 12px;
    line-height: 1.5;
    opacity: 0;
    transition: opacity 150ms ease;
  }
  .credited-image:hover .photo-caption,
  .credited-image:focus-within .photo-caption {
    opacity: 1;
  }
  .photo-caption a {
    justify-self: start;
    text-underline-offset: 3px;
  }
  @media (hover: none) {
    .photo-caption {
      opacity: 1;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .photo-caption {
      transition: none;
    }
  }
  .archive-section {
    margin-top: 64px;
    padding-top: 32px;
    scroll-margin-top: 24px;
  }
  .section-heading {
    margin-bottom: 36px;
  }
  .section-heading .eyebrow {
    margin: 0 0 12px;
  }
  .palette-scope {
    margin: 14px 0 0;
    color: var(--muted);
    font: 12px var(--meta);
  }
  .palette-layout,
  .discovery-layout {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr);
    gap: 64px;
  }
  .family-list {
    display: grid;
    gap: 24px;
  }
  .family-row {
    display: grid;
    grid-template-columns: minmax(170px, 1fr) minmax(80px, 1.5fr) 48px;
    gap: 20px;
    align-items: center;
  }
  .family-label {
    display: grid;
    justify-items: start;
    gap: 6px;
  }
  .family-label .family-link {
    font-size: 17px;
  }
  .share-bar {
    height: 16px;
    background: var(--panel);
  }
  .family-row > strong {
    font-family: var(--meta);
    font-size: 14px;
    font-weight: 400;
    text-align: right;
  }
  .compact-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .compact-list li {
    display: flex;
    justify-content: space-between;
    border-bottom: 1px solid var(--line);
    padding: 12px 0;
    font-size: 15px;
    color: var(--muted);
  }
  .compact-list strong {
    font-weight: 400;
    color: var(--ink);
  }
  .compact-list li:last-child {
    border-bottom: 0;
  }
  .analysis-details {
    margin-top: 36px;
  }
  .discovery-layout {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    align-items: center;
  }
  .discovery-layout img {
    display: block;
    width: 100%;
    height: 300px;
    object-fit: cover;
  }
  .share-section {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 64px;
    align-items: center;
  }
  .share-copy h2 {
    font-size: clamp(2rem, 3.4vw, 3.5rem);
    margin: 16px 0 24px;
  }
  .share-copy :global(.ui-button) {
    margin: 0 10px 10px 0;
  }
  .share-feedback {
    color: var(--muted);
    min-height: 24px;
    font-size: 14px;
  }
  .share-preview > img {
    display: block;
    width: 100%;
    height: auto;
    border: 1px solid var(--line-strong);
  }
  .share-card-preview {
    padding: 28px;
    background: #000;
    color: var(--on-dark);
    border-top: 8px solid var(--report-tone);
    display: grid;
    gap: 28px;
  }
  .share-card-preview > strong {
    font-size: clamp(1.8rem, 2.8vw, 2.8rem);
    line-height: 1.1;
    font-weight: 500;
    letter-spacing: -0.035em;
  }
  .preview-summary {
    margin: 0;
    color: #b5adaa;
    font-size: 14px;
    line-height: 1.5;
  }
  .preview-specimens {
    display: grid;
    grid-template-columns: repeat(var(--specimen-count), minmax(0, 1fr));
    gap: 16px;
  }
  .preview-specimen {
    display: grid;
    grid-template-rows: auto auto 1fr auto;
    min-width: 0;
    gap: 10px;
  }
  .preview-ascii-drawing {
    display: grid;
    place-items: center;
    container-type: inline-size;
    aspect-ratio: 1;
    overflow: hidden;
    border-bottom: 2px solid var(--specimen-tone);
  }
  .preview-ascii-drawing pre {
    margin: 0;
    color: var(--specimen-tone);
    font-family: var(--meta);
    line-height: 0.95;
    font-weight: 500;
  }
  .preview-index,
  .preview-share {
    color: var(--specimen-tone);
    font-family: var(--meta);
  }
  .preview-index {
    font-size: 10px;
  }
  .preview-family {
    font-size: 14px;
    line-height: 1.25;
  }
  .preview-share {
    font-size: 22px;
  }
  .share-card-preview .eyebrow,
  .share-card-preview .preview-note {
    color: #b5adaa;
  }
  .preview-note {
    color: var(--muted);
    font-size: 12px;
  }
  .archive-section.unavailable-section {
    display: flex;
    align-items: baseline;
    gap: 24px;
    margin-top: 28px;
    padding: 12px 0;
    border-block: 1px solid var(--line);
  }
  .archive-section.unavailable-section > p {
    margin: 0;
  }
  .archive-section.unavailable-section > p:last-child {
    color: var(--muted);
    font-size: 14px;
  }
  @media (max-width: 800px) {
    .report-view {
      padding-top: 32px;
    }
    .archive-header {
      gap: 16px;
    }
    .archive-period {
      font-size: 12px;
      gap: 16px;
    }
    .image-link {
      margin-left: 0;
    }
    .report-index {
      gap: 14px 20px;
    }
    .portrait {
      grid-template-columns: 1fr;
      padding-top: 24px;
      gap: 24px;
    }
    .portrait-caption {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }
    .portrait-caption span:last-child {
      margin: 0;
    }
    .instrument-grid {
      grid-template-columns: 1fr;
      gap: 32px;
    }
    .instrument-card .credited-image > img {
      height: 260px;
    }
    .palette-layout,
    .discovery-layout,
    .share-section {
      grid-template-columns: 1fr;
      gap: 32px;
    }
    .family-row {
      grid-template-columns: 1fr 48px;
      gap: 10px;
    }
    .family-row > strong {
      grid-column: 2;
      grid-row: 1;
    }
    .share-bar {
      grid-column: 1/-1;
    }
    .archive-section {
      margin-top: 44px;
    }
    .share-card-preview {
      padding: 20px;
    }
    .archive-section.unavailable-section {
      flex-wrap: wrap;
      gap: 4px 12px;
    }
    .share-preview {
      width: calc(100% + 40px);
      margin-inline: -20px;
    }
    .photo-caption-text {
      display: none;
    }
  }
</style>
