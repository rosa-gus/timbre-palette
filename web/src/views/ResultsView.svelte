<script lang="ts">
  import { Tabs } from "bits-ui";
  import { tick } from "svelte";
  import { normalizePathname } from "../navigation";
  import { getAsciiLines, hasAsciiDrawing } from "../sharing/ascii";
  import { HERCULES_BEETLE_ASCII } from "../sharing/beetle";
  import Arrow from "../components/Arrow.svelte";
  import Badge from "../components/Badge.svelte";
  import Dropdown from "../components/Dropdown.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import Tooltip from "../components/Tooltip.svelte";
  import type {
    AnalysisStatus,
    AnalysisView,
    Confidence,
    ListeningPeriod,
    ProfileAnalysisV2,
    SectionAvailability,
    VocabularyFeaturedArtist,
  } from "../api/types";
  import ReportView from "./ReportView.svelte";

  type SectionId = "portrait" | "palette" | "discovery" | "share";
  type SectionOption = {
    value: string;
    label: string;
    disabled?: boolean;
    note?: string;
  };
  export let result: ProfileAnalysisV2;
  export let period: ListeningPeriod = "1month";
  export let periods: { value: ListeningPeriod; label: string }[] = [];
  export let periodLoading = false;
  export let periodError = "";
  export let onPeriodChange: (value: ListeningPeriod) => void = () => undefined;
  export let activeView: AnalysisView;
  export let onSelectView: (view: AnalysisView) => void;
  export let sectionOptions: SectionOption[] = [];
  export let periodLabels: Record<string, string>;
  export let statusLabels: Record<AnalysisStatus, string>;
  export let confidenceLabels: Record<Confidence, string>;
  export let shareFeedback = "";
  export let sharePreviewUrl = "";
  export let shareBusy = false;
  export let canShareImage = false;
  export let onDownloadShare: () => void;
  export let onOpenInstrument: () => void;
  export let onOpenInstrumentSlug: (slug: string) => void;
  export let onGenerateShare: () => void;
  export let onShareImage: () => void;
  export let getAvailability: (section: SectionId) => SectionAvailability;

  let selectedPeriodButton: HTMLButtonElement | null = null;
  let dismissedLowCoveragePeriod: ListeningPeriod | null = null;
  const homePath = normalizePathname();
  const registeredMonthLabels = [
    "jan.",
    "fev.",
    "mar.",
    "abr.",
    "mai.",
    "jun.",
    "jul.",
    "ago.",
    "set.",
    "out.",
    "nov.",
    "dez.",
  ];
  const bayer4 = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
  ];
  const artistArtScale = 2;
  const artistArtWidth = 96 * artistArtScale;
  const artistArtHeight = 60 * artistArtScale;
  $: palette = result.track_palette;
  $: vocabulary = result.artist_vocabulary;
  $: vocabularyAvailable =
    vocabulary.status === "available" &&
    result.available_views.includes("artist_vocabulary");
  $: vocabularyPending =
    vocabulary.status === "pending" ||
    (vocabulary.status === "available" && !vocabularyAvailable);
  $: vocabularyStatusLabel = vocabularyAvailable
    ? "disponível"
    : vocabularyPending
      ? "em preparação"
      : "insuficiente";
  $: predominantFamily = vocabulary.families.reduce<
    (typeof vocabulary.families)[number] | null
  >(
    (highest, family) =>
      !highest || family.score > highest.score ? family : highest,
    null,
  );
  $: predominantDrawing =
    vocabularyAvailable &&
    predominantFamily &&
    hasAsciiDrawing(predominantFamily.slug)
      ? getAsciiLines(predominantFamily.slug).join("\n")
      : null;
  $: directAvailable =
    palette.analysis.status !== "insufficient" &&
    palette.analysis.section_availability.families === "available";
  $: lastFmUrl =
    result.profile.profile_url ??
    `https://www.last.fm/user/${encodeURIComponent(result.profile.username)}`;
  $: periodOptions = periods.map((option) => ({
    ...option,
    disabled: periodLoading,
  }));
  $: registeredLabel = formatRegisteredDate(result.profile.registered);
  $: showLowCoverageNotice =
    !periodLoading &&
    !periodError &&
    result.profile.period === period &&
    palette.profile.period === period &&
    palette.analysis.coverage_tracks <= 0.01 &&
    selectedPeriodButton !== null &&
    dismissedLowCoveragePeriod !== period;

  function percent(value: number): string {
    return `${Math.round(value * 100)}%`;
  }
  function coveragePercent(value: number): string {
    return `${Number((value * 100).toFixed(1)).toLocaleString("pt-BR")}%`;
  }
  function count(value: number): string {
    return value.toLocaleString("pt-BR");
  }
  function artistArtStyle(artist: VocabularyFeaturedArtist): string {
    const primary = artistArtColors(artist)[0];
    return `--art-primary:${primary}`;
  }
  function artistSeed(artist: VocabularyFeaturedArtist): number {
    let seed = 2166136261;
    for (const character of artist.mbid) {
      seed = Math.imul(seed ^ character.charCodeAt(0), 16777619) >>> 0;
    }
    return seed;
  }
  function nextSeed(seed: number): number {
    seed ^= seed << 13;
    seed ^= seed >>> 17;
    seed ^= seed << 5;
    return seed >>> 0;
  }
  function lighterArtistTone(color: string): string {
    const hex = /^#([0-9a-f]{6})$/i.exec(color)?.[1];
    if (!hex) return "#FFB8B8";
    const channels = [0, 2, 4].map((offset) =>
      Math.round(parseInt(hex.slice(offset, offset + 2), 16) * 0.5 + 127.5)
        .toString(16)
        .padStart(2, "0"),
    );
    return `#${channels.join("")}`;
  }
  function artistArtColors(artist: VocabularyFeaturedArtist): string[] {
    const highlights = [
      ...new Set(
        artist.families
          .map((family) => family.tone?.highlight)
          .filter((color): color is string => Boolean(color)),
      ),
    ];
    const primary = highlights[0] ?? "#F29191";
    const secondary =
      highlights.find((color) => color !== primary) ??
      lighterArtistTone(primary);
    const accent = highlights.find(
      (color) => color !== primary && color !== secondary,
    );
    return accent ? [primary, secondary, accent] : [primary, secondary];
  }
  function artistDitherArt(
    artist: VocabularyFeaturedArtist,
    variant: number,
  ): { color: string; path: string }[] {
    const colors = artistArtColors(artist);
    let seed = artistSeed(artist);
    seed = nextSeed(seed);
    const slope = [0.27, -0.24, 0.15][variant % 3] +
      ((seed & 255) / 255 - 0.5) * 0.1;
    seed = nextSeed(seed);
    const centerOffset = ((seed & 255) / 255 - 0.5) * 0.1;
    seed = nextSeed(seed);
    const phase = (seed & 255) / 255;
    const columns = Array.from({ length: artistArtWidth }, (_, x) => {
      const u = (x + 0.5) / artistArtWidth;
      const wave = Math.sin((u + phase) * Math.PI * 2);
      return 0.5 + centerOffset + slope * (u - 0.5) + 0.045 * wave;
    });
    const pixels: number[][] = [];
    for (let y = 0; y < artistArtHeight; y += 1) {
      const row: number[] = [];
      const v = (y + 0.5) / artistArtHeight;
      for (let x = 0; x < artistArtWidth; x += 1) {
        const mix = Math.max(0, Math.min(1, 0.5 + (v - columns[x]) / 0.8));
        const position = mix * (colors.length - 1);
        const lower = Math.min(colors.length - 2, Math.floor(position));
        const threshold = (bayer4[y % 4][x % 4] + 0.5) / 16;
        row.push(position - lower > threshold ? lower + 1 : lower);
      }
      pixels.push(row);
    }

    return colors.map((color, index) => {
      const path: string[] = [];
      for (let y = 0; y < artistArtHeight; y += 1) {
        for (let x = 0; x < artistArtWidth; ) {
          if (pixels[y][x] !== index) {
            x += 1;
            continue;
          }
          const start = x;
          while (x < artistArtWidth && pixels[y][x] === index) x += 1;
          path.push(`M${start} ${y}h${x - start}v1h-${x - start}z`);
        }
      }
      return { color, path: path.join("") };
    });
  }
  function artistInstruments(
    artist: VocabularyFeaturedArtist,
  ): { name: string; slug: string | null }[] {
    const seen = new Set<string>();
    return artist.families
      .flatMap((family) => {
        const listed = vocabulary.families.find(
          (item) => item.slug === family.slug,
        )?.instruments;
        return family.instruments.map((name) => ({
          name,
          slug: listed?.find((item) => item.name === name)?.slug ?? null,
        }));
      })
      .filter((instrument) => {
        if (seen.has(instrument.name)) return false;
        seen.add(instrument.name);
        return true;
      })
      .slice(0, 3);
  }
  function formatRegisteredDate(
    value: string | null | undefined,
  ): string | null {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return `${registeredMonthLabels[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
  }
  function lastFmAvatarFallbackUrl(source: string): string | null {
    try {
      const url = new URL(source);
      if (url.hostname !== "lastfm-img.freetls.fastly.net") return null;
      if (!/\/i\/u\//.test(url.pathname) || !/\.png$/i.test(url.pathname))
        return null;
      url.hostname = "lastfm.freetls.fastly.net";
      url.pathname = url.pathname.replace(/\.png$/i, ".gif");
      return url.toString();
    } catch {
      return null;
    }
  }
  function handleAvatarError(event: Event): void {
    const image = event.currentTarget as HTMLImageElement;
    const fallback = lastFmAvatarFallbackUrl(image.src);
    if (fallback && image.src !== fallback) image.src = fallback;
  }
  function reasonText(reason: string): string {
    const reasons: Record<string, string> = {
      no_mapped_evidence:
        "Ainda não há instrumentos recorrentes documentados para esta leitura.",
      insufficient_track_reach:
        "Os artistas qualificados ainda representam poucas faixas deste histórico.",
      insufficient_play_reach:
        "Os artistas qualificados ainda representam poucas reproduções deste histórico.",
      insufficient_artist_diversity:
        "Ainda há poucos artistas qualificados para uma leitura diversa.",
      excessive_artist_concentration:
        "A evidência está concentrada demais em um único artista.",
    };
    return (
      reasons[reason] ??
      "Ainda não há evidência suficiente para apresentar esta leitura."
    );
  }
  function handleTabChange(value: string): void {
    if (value === "track_palette") {
      onSelectView(value);
    } else if (
      value === "artist_vocabulary" &&
      vocabulary.status !== "insufficient"
    ) {
      onSelectView(value);
    }
  }

  function handlePeriodChange(value: ListeningPeriod): void {
    if (value !== period) dismissedLowCoveragePeriod = null;
    onPeriodChange(value);
  }

  function dismissLowCoverageNotice(): void {
    dismissedLowCoveragePeriod = period;
  }

  async function showShareSection(event: MouseEvent): Promise<void> {
    event.preventDefault();
    if (activeView !== "track_palette") onSelectView("track_palette");
    await tick();
    const section = document.getElementById("share");
    if (!section) return;
    if (window.location.hash !== "#share") {
      window.history.pushState({}, "", "#share");
    }
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }
</script>

<div class="results-view">
  <a class="back-link" href={homePath}><Arrow direction="left" />VOLTAR</a>
  <section
    class="profile-card"
    aria-labelledby="profile-title"
  >
    <div class="profile-avatar">
      {#if result.is_example}
        <pre class="profile-avatar-drawing" role="img" aria-label="ascii de um besouro">{HERCULES_BEETLE_ASCII}</pre>
      {:else if result.profile.avatar_url}
        <img
          src={result.profile.avatar_url}
          alt={`Foto de perfil de @${result.profile.username}`}
          on:error={handleAvatarError}
        />
      {:else}
        <span aria-hidden="true">[ ? ? ? ]</span>
      {/if}
    </div>
    <div class="profile-copy">
      <div class="profile-identity">
        <div class="profile-label">
          {#if !result.is_example}
          <p class="eyebrow">
            PERFIL LAST.FM
          </p>
          {/if}
          {#if result.is_example}<Badge tone="accent">EXEMPLO</Badge>{/if}
        </div>
        <h1 id="profile-title">
          {result.is_example
            ? result.profile.realname || "Besouro Hércules"
            : result.profile.realname || `@${result.profile.username}`}
        </h1>
        {#if result.is_example}<p class="profile-username">
            {result.profile.username}
          </p>{:else if result.profile.realname}<p class="profile-username">
            @{result.profile.username}
          </p>{/if}
      </div>
      <div class="profile-footer">
        <div class="profile-meta">
          {#if registeredLabel}<span>SCROBBLANDO DESDE {registeredLabel}</span
            >{/if}
          {#if result.is_example}<span>ESCUTA FICTÍCIA COM GRAVAÇÕES DO CATÁLOGO</span>{/if}
          {#if palette.analysis.data_source !== "catalog"}
            <span
              >{palette.analysis.data_source === "mock"
                ? "dados demonstrativos"
                : "dados híbridos"}</span
            >
          {/if}
        </div>
        <div class="profile-actions">
          {#if directAvailable && !periodLoading}<a
             class="profile-link"
             href="#share"
             on:click={showShareSection}
              >{result.is_example ? "VER IMAGEM DO EXEMPLO" : "VER MINHA IMAGEM"}
              <Arrow direction="right" /></a
            >{/if}
          {#if !result.is_example}<a
            class="profile-link"
            href={lastFmUrl}
            target="_blank"
            rel="noreferrer"
          >
            VER NO LAST.FM <Arrow direction="up-right" />
          </a>{/if}
        </div>
      </div>
    </div>
    <div class="period-controls" aria-busy={periodLoading}>
      <span class="period-label">PERÍODO DE ANÁLISE</span>
      <SegmentedControl
        label="Período de análise"
        options={periodOptions}
        value={period}
        bind:selectedButton={selectedPeriodButton}
        onChange={(value) => handlePeriodChange(value as ListeningPeriod)}
      />
      {#if periodLoading}
        <p class="period-loading" role="status" aria-live="polite">
          <span class="loading-indicator" aria-hidden="true"></span>
          <span>Atualizando análise de {periodLabels[period]}…</span>
        </p>
      {:else if periodError}
        <p class="period-error" role="alert">{periodError}</p>
      {/if}
      {#if showLowCoverageNotice}
        <Tooltip
          frozen
          anchor={selectedPeriodButton}
          align="center"
          onClose={dismissLowCoverageNotice}
        >
          <p aria-live="polite">
            No período selecionado ({periodLabels[period]}), a cobertura de
            faixas foi de apenas {coveragePercent(
              palette.analysis.coverage_tracks,
            )}. Escolha outro período para tentar encontrar uma cobertura maior.
          </p>
        </Tooltip>
      {/if}
    </div>
  </section>

  <Tabs.Root
    value={activeView}
    onValueChange={handleTabChange}
    activationMode="manual"
    orientation="horizontal"
    loop
    class="view-tabs"
  >
    <Tabs.List
      class={`view-switch${vocabulary.status === "insufficient" ? " view-switch-single" : ""}`}
      aria-label="Leituras da escuta"
    >
      <Tabs.Trigger value="track_palette" class="view-tab view-tab-palette">
        <span>01 / PALETA DAS FAIXAS</span>
        <small>{statusLabels[palette.analysis.status]}</small>
      </Tabs.Trigger>
      {#if vocabulary.status !== "insufficient"}
        <Tabs.Trigger
          value="artist_vocabulary"
          class="view-tab view-tab-vocabulary"
        >
          <span>02 / VOCABULÁRIO DOS ARTISTAS</span>
          <small>{vocabularyStatusLabel}</small>
        </Tabs.Trigger>
      {/if}
    </Tabs.List>

    <Tabs.Content value="track_palette" class="view-panel">
      {#if directAvailable}
        <ReportView
          report={palette}
          isExample={result.is_example}
          embedded
          {sectionOptions}
          {periodLabels}
          {statusLabels}
          {confidenceLabels}
          {shareFeedback}
          {sharePreviewUrl}
          {shareBusy}
          {canShareImage}
          {onDownloadShare}
          {onShareImage}
          {onOpenInstrument}
          {onOpenInstrumentSlug}
          {onGenerateShare}
          {getAvailability}
          hydrationPending={result.hydration.status === "pending"}
        />
      {:else}
        <section class="unavailable-reading" aria-labelledby="direct-title">
          <p class="eyebrow">
            01 / PALETA DAS FAIXAS <span
              class="separator-indicator"
              aria-hidden="true">·</span
            > INSUFICIENTE
          </p>
          <h2 id="direct-title">Ainda não há um retrato das suas faixas.</h2>
          <p>
            Não encontramos créditos instrumentais diretos aceitos em uma
            amostra suficiente deste histórico. Isso não significa que esses
            instrumentos estejam ausentes das músicas.
          </p>
          <p class="reading-measure">
            {percent(palette.analysis.coverage_tracks)} das faixas
            <span class="separator-indicator" aria-hidden="true">·</span>
            {percent(palette.analysis.coverage_plays)} das reproduções cobertas
          </p>
          {#if vocabularyAvailable}<button
              type="button"
              on:click={() => onSelectView("artist_vocabulary")}
              >VER VOCABULÁRIO DOS ARTISTAS →</button
            >{/if}
        </section>
      {/if}
    </Tabs.Content>
    {#if vocabulary.status !== "insufficient"}
      <Tabs.Content value="artist_vocabulary" class="view-panel">
        <section class="vocabulary-reading" aria-labelledby="vocabulary-title">
          <div class="vocabulary-lead">
            <div>
              <p class="eyebrow">
                02 / VOCABULÁRIO DOS ARTISTAS <span
                  class="separator-indicator"
                  aria-hidden="true">·</span
                >
                {vocabularyStatusLabel.toUpperCase()}
              </p>
              <h2 id="vocabulary-title">
                Os sons documentados ao redor dos artistas.
              </h2>
              <p class="lead-copy">
                Instrumentos que recorrem em gravações documentadas dos artistas
                presentes na sua escuta.
              </p>
              <p class="scope-note">{vocabulary.notice}</p>
            </div>
            {#if predominantDrawing && predominantFamily}
              <figure
                class="type-art"
                aria-label={`Desenho ASCII da família ${predominantFamily.name}, predominante no vocabulário`}
              >
                <pre aria-hidden="true">{predominantDrawing}</pre>
                <figcaption>
                  {predominantFamily.name} / família predominante
                </figcaption>
              </figure>
            {/if}
          </div>

          {#if vocabularyAvailable}
            <div
              class="vocabulary-color-strip"
              role="img"
              aria-label={`Cores das famílias no vocabulário: ${vocabulary.families.map((family) => `${family.name} ${percent(family.share)}`).join(", ")}`}
            >
              {#each vocabulary.families as family (family.slug)}
                <span
                  style={`flex:${family.share} 1 0;background:${family.tone?.highlight ?? "#F29191"}`}
                  title={`${family.name}: ${percent(family.share)}`}
                ></span>
              {/each}
            </div>
            {#if vocabulary.featured_artists.length > 0}
              <section
                class="featured-artists"
                aria-labelledby="featured-artists-title"
              >
                <div class="featured-heading">
                  <h3 id="featured-artists-title">Artistas em destaque</h3>
                  <p>São os que mais contribuem para este vocabulário.</p>
                </div>
                <div class="artist-cards">
                  {#each vocabulary.featured_artists as artist, index (artist.mbid)}
                    {@const art = artistDitherArt(artist, index)}
                    <article class="artist-card" style={artistArtStyle(artist)}>
                      <div class="artist-art" aria-hidden="true">
                        <svg
                          viewBox={`0 0 ${artistArtWidth} ${artistArtHeight}`}
                          preserveAspectRatio="none"
                          focusable="false"
                        >
                          {#each art as mass}
                            <path d={mass.path} fill={mass.color}></path>
                          {/each}
                        </svg>
                      </div>
                      <div class="artist-card-copy">
                        <span class="artist-card-index"
                          >{String(index + 1).padStart(2, "0")} / ARTISTA</span
                        >
                        <h4>{artist.name}</h4>
                        <p class="artist-families">
                          {artist.families
                            .map((family) => family.name)
                            .join(" · ")}
                        </p>
                        <p class="artist-instruments">
                          {#each artistInstruments(artist) as instrument, instrumentIndex (instrument.name)}
                            <span class="artist-instrument-entry">
                              {#if instrumentIndex > 0}<span
                                  class="separator-indicator"
                                  aria-hidden="true">·</span
                                >{/if}
                              {#if instrument.slug}<button
                                  type="button"
                                  class="instrument-link"
                                  on:click={() =>
                                    instrument.slug &&
                                    onOpenInstrumentSlug(instrument.slug)}
                                  >{instrument.name}</button
                                >{:else}{instrument.name}{/if}
                            </span>
                          {/each}
                        </p>
                        <p class="artist-card-note">
                          Instrumentos recorrentes em gravações documentadas
                          deste artista.
                        </p>
                      </div>
                    </article>
                  {/each}
                </div>
              </section>
            {/if}
            <div class="reach-grid" aria-label="Alcance do vocabulário">
              <div>
                <span>FAIXAS LIGADAS A ARTISTAS QUALIFICADOS</span><strong
                  >{count(vocabulary.reach.qualified_tracks)} / {count(
                    vocabulary.reach.total_tracks,
                  )}</strong
                ><small
                  >{percent(vocabulary.reach.track_reach)} das faixas</small
                >
              </div>
              <div>
                <span>REPRODUÇÕES</span><strong
                  >{percent(vocabulary.reach.play_reach)}</strong
                ><small
                  >{count(vocabulary.reach.qualified_plays)} / {count(
                    vocabulary.reach.total_plays,
                  )} reproduções</small
                >
              </div>
              <div>
                <span>ARTISTAS QUALIFICADOS</span><strong
                  >{count(vocabulary.reach.qualified_artists)} / {count(
                    vocabulary.reach.total_artists,
                  )}</strong
                ><small>com instrumentos recorrentes</small>
              </div>
            </div>
            <div class="family-heading">
              <span>FAMÍLIAS NO VOCABULÁRIO</span>
            </div>
            <div class="vocabulary-families">
              {#each vocabulary.families as family, index}
                <article
                  class="vocabulary-family"
                  style={`--family-accent:${family.tone?.highlight ?? "#F29191"}`}
                >
                  <div class="family-top">
                    <span class="family-index"
                      >{String(index + 1).padStart(2, "0")}</span
                    >
                    <h3>
                      <button
                        type="button"
                        class="family-link"
                        aria-label={`Abrir ficha de ${family.name}`}
                        on:click={() => onOpenInstrumentSlug(family.slug)}
                        >{family.name}</button
                      >
                    </h3>
                    <strong>{percent(family.share)}</strong>
                  </div>
                  <div
                    class="vocabulary-bar"
                    role="img"
                    aria-label={`${family.name}: ${percent(family.share)} de participação no modelo`}
                  >
                    <span style={`width:${family.share * 100}%`}></span>
                  </div>
                  <p>
                    {count(family.supporting_artists)}
                    {family.supporting_artists === 1
                      ? "artista com suporte"
                      : "artistas com suporte"}
                  </p>
                  <div class="family-evidence">
                    <Dropdown title="Critérios e evidências">
                      <p>
                        Os instrumentos abaixo recorrem em pelo menos três
                        gravações distintas documentadas de um artista. Eles não
                        são créditos atribuídos às faixas deste histórico.
                      </p>
                      <ul>
                        {#each family.instruments as instrument}<li>
                            <button
                              type="button"
                              class="instrument-link"
                              on:click={() =>
                                onOpenInstrumentSlug(instrument.slug)}
                              >{instrument.name}</button
                            ><span
                              >{count(instrument.distinct_recordings)} gravações
                              distintas
                              <span
                                class="separator-indicator"
                                aria-hidden="true">·</span
                              >
                              crédito de {instrument.evidence.scope === "track"
                                ? "faixa"
                                : "gravação"}</span
                            >
                          </li>{/each}
                      </ul>
                    </Dropdown>
                  </div>
                </article>
              {/each}
            </div>
          {:else}
            <div class="vocabulary-state" role="status">
              {#if vocabularyPending}<span
                  class="loading-indicator"
                  aria-hidden="true"
                ></span>{/if}
              <h3>
                {vocabularyPending
                  ? "Esta leitura ainda está em preparação."
                  : "Ainda não há um vocabulário para mostrar."}
              </h3>
              <p>
                {vocabularyPending
                  ? "Estamos reunindo informações sobre artistas deste histórico. Isso pode levar horas; volte mais tarde para consultar novamente."
                  : reasonText(vocabulary.availability.reason)}
              </p>
            </div>
          {/if}

          {#if vocabularyAvailable}
            <div class="vocabulary-method">
              <Dropdown title="O que estes números significam">
                <p>
                  O alcance mostra a parte do histórico ligada a artistas com
                  instrumentos recorrentes documentados. Ele não é a cobertura
                  da paleta das faixas.
                </p>
                <p>
                  A participação mostra o peso relativo calculado entre as
                  famílias deste vocabulário. Não mede volume, duração ou
                  presença do instrumento nas faixas ouvidas.
                </p>
                <p>
                  Maior contribuição de um único artista para a pontuação: {percent(
                    vocabulary.concentration,
                  )}.
                </p>
                <p>
                  {count(vocabulary.reach.unresolved_artists)} artistas e {count(
                    vocabulary.reach.unresolved_tracks,
                  )} faixas sem identidade MusicBrainz não entram na consulta pendente.
                </p>
                <p>
                  Snapshot MusicBrainz {result.snapshot.snapshot_version}
                  <span class="separator-indicator" aria-hidden="true">·</span>
                  Método do vocabulário {vocabulary.methodology_version}
                </p>
              </Dropdown>
            </div>
          {/if}
        </section>
      </Tabs.Content>
    {/if}
  </Tabs.Root>
</div>

<style>
  .results-view {
    width: 100%;
    max-width: 1320px;
    margin: 0 auto;
    padding: 54px 0 32px;
  }
  .back-link {
    display: inline-block;
    margin-bottom: 28px;
    color: var(--accent-soft);
    font: 13px var(--meta);
    letter-spacing: 0.06em;
    text-decoration: none;
  }
  .back-link:hover {
    color: var(--ink);
  }
  .eyebrow {
    font: 12px var(--meta);
    letter-spacing: 0.07em;
    line-height: 1.6;
  }
  .eyebrow {
    color: var(--muted);
  }
  .profile-card {
    display: grid;
    grid-template-columns: 192px minmax(0, 1fr);
    align-items: stretch;
    gap: 24px;
    padding: 0 0 24px;
    margin-bottom: 38px;
    border-bottom: 1px solid var(--line-strong);
  }
  .profile-label {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .profile-avatar {
    display: grid;
    width: 192px;
    aspect-ratio: 1;
    align-self: center;
    overflow: hidden;
    place-items: center;
    background: var(--panel);
    border: 1px solid var(--line-strong);
    color: var(--accent-soft);
    font: 13px var(--meta);
  }
  .profile-avatar img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .profile-avatar-drawing {
    margin: 0;
    color: var(--accent-soft);
    font: 9px/1.1 var(--meta);
    white-space: pre;
    transform: scaleX(1.3);
  }
  .profile-copy {
    display: flex;
    min-width: 0;
    flex-direction: column;
    justify-content: space-between;
    gap: 24px;
  }
  .profile-identity .eyebrow {
    margin: 0;
  }
  .profile-identity h1 {
    margin: 6px 0 0;
    color: var(--ink);
    font-size: clamp(1.8rem, 2.6vw, 2.6rem);
    line-height: 1.1;
    overflow-wrap: anywhere;
  }
  .profile-username {
    margin: 6px 0 0;
    color: var(--muted);
    font: 14px var(--meta);
    overflow-wrap: anywhere;
  }
  .profile-footer {
    display: flex;
    align-items: end;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 16px 24px;
  }
  .profile-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 18px;
    color: var(--quiet);
    font: 12px var(--meta);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .profile-actions {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  .profile-actions .profile-link {
    justify-content: space-between;
  }
  .profile-link {
    display: inline-flex;
    align-items: center;
    min-height: 40px;
    padding: 8px 12px;
    border: 1px solid var(--line-strong);
    color: var(--muted);
    font: 12px var(--meta);
    letter-spacing: 0.04em;
    text-decoration: none;
    white-space: nowrap;
  }
  .profile-link:hover,
  .profile-link:focus-visible {
    border-color: var(--accent-soft);
    color: var(--accent-soft);
  }
  .period-controls {
    grid-column: 1 / -1;
    display: grid;
    gap: 9px;
    padding-top: 20px;
    border-top: 1px solid var(--line);
  }
  .period-label {
    color: var(--muted);
    font: 12px var(--meta);
    letter-spacing: 0.05em;
  }
  .period-loading,
  .period-error {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    color: var(--muted);
    font: 11px var(--meta);
    line-height: 1.5;
  }
  .period-loading .loading-indicator {
    flex-basis: 4.4em;
  }
  .period-error {
    color: var(--accent-soft);
  }
  :global(.view-tabs) {
    width: 100%;
  }
  :global(.view-switch) {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    border: 1px solid var(--line-strong);
  }
  :global(.view-switch-single) {
    grid-template-columns: 1fr;
  }
  :global(.view-tab) {
    position: relative;
    z-index: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    min-height: 76px;
    padding: 20px 24px;
    border: 0;
    border-bottom: 3px solid transparent;
    border-radius: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    text-align: left;
    font: 13px var(--meta);
    letter-spacing: 0.04em;
    transition:
      background-color 150ms ease,
      border-color 150ms ease,
      color 150ms ease;
  }
  :global(.view-tab + .view-tab) {
    border-left: 1px solid var(--line-strong);
  }
  :global(.view-tab:hover),
  :global(.view-tab:focus-visible) {
    color: var(--ink);
  }
  :global(.view-tab[data-state="active"]) {
    z-index: 1;
    border-top: 0;
    border-bottom: 3px solid var(--accent);
    background: var(--panel);
    color: var(--ink);
  }
  :global(.view-tab small) {
    color: var(--accent-soft);
    font: 12px var(--meta);
    white-space: nowrap;
  }
  .unavailable-reading button {
    margin-left: auto;
    padding: 10px 12px;
    border: 1px solid var(--line-strong);
    border-radius: 0;
    background: transparent;
    color: var(--ink);
    cursor: pointer;
    font: 12px var(--meta);
    white-space: nowrap;
  }
  button:hover:not(:disabled) {
    border-color: var(--accent-soft);
    color: var(--accent-soft);
  }
  button:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .unavailable-reading {
    max-width: 760px;
    padding: 68px 0 100px;
  }
  .unavailable-reading h2,
  .vocabulary-lead h2 {
    margin: 12px 0 18px;
    font-size: clamp(2rem, 3.8vw, 3.6rem);
    line-height: 1.08;
  }
  .unavailable-reading > p:not(.eyebrow),
  .lead-copy {
    color: var(--muted);
    font-size: clamp(1rem, 1.3vw, 1.18rem);
  }
  .reading-measure {
    margin: 26px 0;
    font-family: var(--meta);
    font-size: 13px !important;
  }
  .unavailable-reading button {
    margin: 12px 0 0;
  }
  .vocabulary-reading {
    padding-top: 52px;
  }
  .vocabulary-lead {
    display: flex;
    justify-content: space-between;
    gap: 36px;
    padding-bottom: 44px;
  }
  .vocabulary-lead > div {
    max-width: 790px;
  }
  .lead-copy {
    margin: 0 0 12px;
  }
  .scope-note {
    max-width: 630px;
    color: var(--quiet);
    font-size: 13px;
  }
  .type-art {
    display: grid;
    align-self: center;
    justify-items: center;
    width: max-content;
    max-width: 100%;
    margin: 0 3vw 0 0;
    color: var(--accent-soft);
  }
  .type-art pre {
    max-width: 100%;
    margin: 0;
    font: clamp(11px, 1vw, 15px) / 1.05 var(--meta);
    white-space: pre;
  }
  .type-art figcaption {
    width: 100%;
    margin-top: 16px;
    color: var(--muted);
    font: 11px var(--meta);
    letter-spacing: 0.04em;
    text-align: center;
    text-transform: uppercase;
  }
  .vocabulary-color-strip {
    display: flex;
    width: 100%;
    height: 28px;
    gap: 4px;
    margin: 0 0 42px;
    overflow: hidden;
  }
  .vocabulary-color-strip span {
    display: block;
    min-width: 3px;
  }
  .featured-artists {
    margin: 4px 0 52px;
  }
  .featured-heading {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px 24px;
    margin-bottom: 15px;
  }
  .featured-heading h3 {
    margin: 0;
    font: 12px var(--meta);
    letter-spacing: 0.07em;
    text-transform: uppercase;
  }
  .featured-heading p {
    margin: 0;
    color: var(--muted);
    font: 12px var(--meta);
  }
  .artist-cards {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px;
  }
  .artist-card {
    min-width: 0;
    border: 1px solid var(--line-strong);
    background: var(--panel);
  }
  .artist-art {
    aspect-ratio: 1.55;
    overflow: hidden;
    background: var(--art-primary);
  }
  .artist-art svg {
    display: block;
    width: 100%;
    height: 100%;
    shape-rendering: crispEdges;
  }
  .artist-card-copy {
    min-height: 202px;
    padding: 20px 22px 22px;
    border-top: 4px solid var(--art-primary);
  }
  .artist-card-index {
    color: var(--muted);
    font: 11px var(--meta);
    letter-spacing: 0.06em;
  }
  .artist-card h4 {
    margin: 12px 0 8px;
    font-size: clamp(1.5rem, 2vw, 2rem);
    font-weight: 500;
    line-height: 1.1;
    overflow-wrap: anywhere;
  }
  .artist-families {
    margin: 0;
    color: var(--ink);
    font-size: 14px;
  }
  .artist-instruments {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    margin: 16px 0 4px;
    font: 12px var(--meta);
    line-height: 1.5;
  }
  .artist-instrument-entry {
    display: inline-flex;
    align-items: center;
    white-space: nowrap;
  }
  .artist-card-note {
    margin: 0;
    color: var(--muted);
    font-size: 12px;
    line-height: 1.45;
  }
  .reach-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    border: 1px solid var(--line-strong);
  }
  .reach-grid > div {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
    padding: 22px 24px;
  }
  .reach-grid > div + div {
    border-left: 1px solid var(--line);
  }
  .reach-grid span,
  .reach-grid small,
  .family-heading,
  .family-index {
    color: var(--muted);
    font: 12px var(--meta);
    letter-spacing: 0.05em;
  }
  .reach-grid strong {
    font-size: clamp(1.55rem, 2.8vw, 2.8rem);
    font-weight: 500;
    line-height: 1.1;
  }
  .family-heading {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    margin: 54px 0 8px;
  }
  .vocabulary-family {
    padding: 24px 0 26px;
    border-top: 1px solid var(--line);
  }
  .family-top {
    display: grid;
    grid-template-columns: 40px 1fr auto;
    align-items: baseline;
    gap: 18px;
  }
  .family-top h3 {
    margin: 0;
    font-size: clamp(1.5rem, 2.3vw, 2.4rem);
  }
  .family-top .family-link {
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
  .family-top .family-link:hover,
  .family-top .family-link:focus-visible {
    color: var(--accent-soft);
    text-decoration-color: currentColor;
  }
  .family-top strong {
    font: 20px var(--meta);
    color: var(--accent-soft);
  }
  .vocabulary-bar {
    height: 11px;
    margin: 20px 0 14px 58px;
    background: var(--panel);
  }
  .vocabulary-bar span {
    display: block;
    height: 100%;
    background: var(--family-accent);
  }
  .vocabulary-family > p {
    margin: 0 0 0 58px;
    color: var(--muted);
    font-size: 14px;
  }
  .family-evidence {
    margin: 16px 0 0 58px;
  }
  .family-evidence p {
    max-width: 650px;
  }
  .vocabulary-family ul {
    max-width: 760px;
    margin: 14px 0 0;
    padding: 0;
    list-style: none;
  }
  .vocabulary-family li {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    padding: 8px 0;
    border-top: 1px solid var(--line);
  }
  .vocabulary-family li:first-child {
    border-top: 0;
  }
  .vocabulary-family li span:first-child {
    color: var(--ink);
  }
  .instrument-link {
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--ink);
    cursor: pointer;
    font: inherit;
    text-align: left;
    text-decoration: underline;
    text-decoration-color: transparent;
    text-underline-offset: 4px;
    transition:
      color 150ms ease,
      text-decoration-color 150ms ease;
  }
  .instrument-link:hover,
  .instrument-link:focus-visible {
    color: var(--accent-soft);
    text-decoration-color: currentColor;
  }
  .vocabulary-state {
    max-width: 700px;
    padding: 45px 0 55px;
    border-top: 1px solid var(--line);
  }
  .vocabulary-state > span {
    color: var(--accent-soft);
    font: 13px var(--meta);
  }
  .vocabulary-state h3 {
    margin: 14px 0;
    font-size: clamp(1.5rem, 2.5vw, 2.3rem);
  }
  .vocabulary-state p {
    color: var(--muted);
  }
  .vocabulary-method {
    max-width: 850px;
    margin: 50px 0 40px;
  }
  .vocabulary-method p {
    max-width: 700px;
  }
  @media (max-width: 800px) {
    .results-view {
      padding-top: 32px;
    }
    .profile-card {
      grid-template-columns: minmax(0, 1fr);
      gap: 16px;
      padding-bottom: 20px;
    }
    .profile-avatar {
      width: 100%;
    }
    .profile-avatar-drawing {
      font-size: 5px;
    }
    .profile-identity h1 {
      font-size: clamp(1.6rem, 6vw, 2.2rem);
    }
    .profile-copy {
      gap: 18px;
    }
    .period-controls {
      padding-top: 16px;
    }
    :global(.view-switch) {
      grid-template-columns: 1fr;
    }
    :global(.view-tab) {
      min-height: 60px;
      padding: 14px 10px;
    }
    :global(.view-tab + .view-tab) {
      border-top: 1px solid var(--line-strong);
      border-left: 0;
    }
    .vocabulary-reading {
      padding-top: 34px;
    }
    .vocabulary-lead {
      flex-direction: column;
      padding-bottom: 28px;
    }
    .type-art {
      align-self: center;
      margin: 12px 0 0;
    }
    .type-art pre {
      font-size: clamp(9px, 2.8vw, 13px);
    }
    .featured-heading {
      display: block;
    }
    .featured-heading p {
      margin-top: 6px;
    }
    .artist-cards {
      grid-template-columns: 1fr;
    }
    .artist-art {
      aspect-ratio: 1.8;
    }
    .artist-card-copy {
      min-height: 0;
    }
    .reach-grid {
      grid-template-columns: 1fr;
    }
    .reach-grid > div,
    .reach-grid > div:first-child {
      align-items: center;
      padding: 14px 0;
      text-align: center;
    }
    .reach-grid > div + div {
      border-left: 0;
      border-top: 1px solid var(--line);
    }
    .family-heading {
      margin-top: 40px;
    }
    .family-heading span:last-child {
      width: 100%;
      max-width: none;
      text-align: left;
    }
    .vocabulary-bar,
    .vocabulary-family > p,
    .family-evidence {
      margin-left: 0;
    }
    .family-top {
      grid-template-columns: 26px 1fr auto;
      gap: 10px;
    }
    .vocabulary-family li {
      display: grid;
      gap: 2px;
    }
  }
</style>
