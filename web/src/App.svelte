<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import {
    getApiErrorMessage,
    getInstrument,
    getAnalysis,
    normalizeUsername,
    getCatalogSize,
    catalogStorageKey,
    apiBaseUrl,
  } from "./api/client";
  import { getStorageItem, setStorageItem, storageKey } from "./storage";
  import type {
    AnalysisStatus,
    Confidence,
    InstrumentResource,
    ListeningPeriod,
    PaletteReport,
    ProfileAnalysisV2,
    AnalysisView,
    SectionAvailability,
  } from "./api/types";
  import { createShareImage, downloadShareImage } from "./sharing/share";
  import InstrumentDialog from "./components/InstrumentDialog.svelte";
  import ProductVersion from "./components/ProductVersion.svelte";
  import Dropdown from "./components/Dropdown.svelte";
  import { normalizePathname } from "./navigation";
  import CatalogGrowth from "./components/CatalogGrowth.svelte";
  import ResultsView from "./views/ResultsView.svelte";
  import EntryView from "./views/EntryView.svelte";

  type SectionId = "portrait" | "palette" | "discovery" | "share";
  const periods: { value: ListeningPeriod; label: string }[] = [
    { value: "7day", label: "7 dias" },
    { value: "1month", label: "1 mês" },
    { value: "3month", label: "3 meses" },
    { value: "6month", label: "6 meses" },
    { value: "12month", label: "12 meses" },
    { value: "overall", label: "Histórico" },
  ];
  const periodLabels: Record<ListeningPeriod, string> = Object.fromEntries(
    periods.map((item) => [item.value, item.label]),
  ) as Record<ListeningPeriod, string>;
  const sectionLabels: Record<SectionId, string> = {
    portrait: "Retrato",
    palette: "Paleta",
    discovery: "Descoberta",
    share: "Compartilhar",
  };
  const availabilityKeys: Record<
    SectionId,
    keyof PaletteReport["analysis"]["section_availability"]
  > = {
    portrait: "temperament",
    palette: "families",
    discovery: "discovery",
    share: "families",
  };
  const availabilityLabels: Record<SectionAvailability, string> = {
    available: "disponível",
    insufficient_coverage: "cobertura insuficiente",
    insufficient_diversity: "diversidade insuficiente",
    insufficient_nature_evidence: "evidência sonora insuficiente",
    no_candidate: "sem candidato",
  };
  const statusLabels: Record<AnalysisStatus, string> = {
    partial: "parcial",
    ready: "pronta",
    insufficient: "insuficiente",
  };
  const confidenceLabels: Record<Confidence, string> = {
    documented: "Documentada",
    strongly_associated: "Fortemente associada",
    estimated: "Estimada",
  };
  type Theme = "dark" | "light" | "system";
  type ResolvedTheme = Exclude<Theme, "system">;
  const themeStorageKey = storageKey("ui", "theme");
  const themeLabels: Record<Theme, string> = {
    dark: "ESCURO",
    light: "CLARO",
    system: "SISTEMA",
  };
  const homePath = normalizePathname();

  let view: "entry" | "loading" | "report" = "entry";
  let catalogGrowth: { percent: number; added: number } | null = null;

  async function checkCatalog(signal: AbortSignal): Promise<void> {
    try {
      const current = await getCatalogSize(signal);
      const saved = getStorageItem<unknown>(catalogStorageKey);
      if (
        saved &&
        typeof saved === "object" &&
        "schemaVersion" in saved &&
        "apiBaseUrl" in saved &&
        saved.apiBaseUrl === apiBaseUrl() &&
        saved.schemaVersion === 1 &&
        "recordingsWithEvidence" in saved &&
        typeof saved.recordingsWithEvidence === "number" &&
        Number.isSafeInteger(saved.recordingsWithEvidence) &&
        saved.recordingsWithEvidence > 0 &&
        current > saved.recordingsWithEvidence
      ) {
        const added = current - saved.recordingsWithEvidence;
        catalogGrowth = {
          percent: (added / saved.recordingsWithEvidence) * 100,
          added,
        };
      }
      setStorageItem(catalogStorageKey, {
        schemaVersion: 1,
        apiBaseUrl: apiBaseUrl(),
        recordingsWithEvidence: current,
        seenAt: new Date().toISOString(),
      });
    } catch {
      // Optional statistics and browser storage never block the home.
    }
  }
  let theme: Theme = "system";
  let resolvedTheme: ResolvedTheme = "light";
  let systemThemeQuery: MediaQueryList | null = null;
  let username = "";
  let period: ListeningPeriod = "1month";
  let result: ProfileAnalysisV2 | null = null;
  let activeAnalysisView: AnalysisView = "track_palette";
  let formError = "";
  let loadingTitle = "Lendo seu histórico.";
  let loadingDescription = "As primeiras relações estão sendo reunidas.";
  let loadingDetail = "Consultando o Last.fm";
  let periodLoading = false;
  let periodError = "";
  let shareFeedback = "";
  let sharePreviewUrl = "";
  let shareBlob: Blob | null = null;
  let shareBusy = false;
  let dialogOpen = false;
  let instrument: InstrumentResource | null = null;
  let instrumentLoading = false;
  let instrumentError = "";
  let controller: AbortController | null = null;
  let instrumentController: AbortController | null = null;
  const instrumentCache = new Map<string, InstrumentResource>();
  $: sectionOptions = (Object.keys(sectionLabels) as SectionId[]).map(
    (value) => ({
      value,
      label: sectionLabels[value],
      disabled:
        value !== "share" &&
        !!result &&
        result.track_palette.analysis.section_availability[
          availabilityKeys[value]
        ] !== "available",
      note:
        value !== "share" && result
          ? availabilityLabels[
              result.track_palette.analysis.section_availability[
                availabilityKeys[value]
              ]
            ]
          : undefined,
    }),
  );

  function availability(section: SectionId): SectionAvailability {
    return (
      result?.track_palette.analysis.section_availability[
        availabilityKeys[section]
      ] ?? "insufficient_coverage"
    );
  }

  function updateUrl(): void {
    const url = new URL(window.location.href);
    url.searchParams.set("profile", username);
    url.searchParams.set("period", period);
    url.searchParams.set("view", activeAnalysisView);
    window.history.replaceState({}, "", url);
  }

  function selectAnalysisView(next: AnalysisView): void {
    activeAnalysisView = next;
    updateUrl();
  }

  function resolveAnalysisView(
    next: ProfileAnalysisV2,
    requested: AnalysisView | null,
  ): AnalysisView {
    if (requested === "artist_vocabulary") {
      return next.artist_vocabulary.status === "insufficient"
        ? "track_palette"
        : "artist_vocabulary";
    }
    if (requested === "track_palette") return "track_palette";
    if (next.default_view && next.available_views.includes(next.default_view)) {
      return next.default_view;
    }
    if (
      next.available_views.includes("artist_vocabulary") ||
      next.artist_vocabulary.status === "pending"
    ) {
      return "artist_vocabulary";
    }
    return "track_palette";
  }

  async function loadReport(preserveReport = false): Promise<void> {
    controller?.abort();
    const request = new AbortController();
    controller = request;
    const signal = request.signal;
    if (sharePreviewUrl) URL.revokeObjectURL(sharePreviewUrl);
    sharePreviewUrl = "";
    shareBlob = null;
    shareFeedback = "";
    if (preserveReport) {
      periodLoading = true;
      periodError = "";
    } else {
      view = "loading";
      formError = "";
    }
    try {
      const next = await getAnalysis(username, period, signal);
      result = next;
      const requestedView = new URL(window.location.href).searchParams.get(
        "view",
      );
      const requestedAnalysisView =
        requestedView === "artist_vocabulary" ||
        requestedView === "track_palette"
          ? requestedView
          : null;
      activeAnalysisView = resolveAnalysisView(next, requestedAnalysisView);
      view = "report";
      periodLoading = false;
      periodError = "";
      updateUrl();
      return;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (preserveReport) {
        periodLoading = false;
        periodError = getApiErrorMessage(error);
        if (result) period = result.profile.period;
        updateUrl();
      } else {
        view = "entry";
        formError = getApiErrorMessage(error);
      }
    }
  }
  function changePeriod(next: ListeningPeriod): void {
    if (next === period || periodLoading || !result) return;
    period = next;
    void loadReport(true);
  }
  function submit(): void {
    username = normalizeUsername(username);
    if (!username) {
      formError = "Informe um perfil do Last.fm para começar.";
      return;
    }
    if (view === "loading") return;
    void loadReport();
  }
  function openInstrument(): void {
    const slug = result?.track_palette.discovery?.instrument_slug;
    if (slug) void loadInstrument(slug);
  }
  async function loadInstrument(slug: string): Promise<void> {
    instrumentController?.abort();
    const request = new AbortController();
    instrumentController = request;
    dialogOpen = true;
    instrumentError = "";
    instrumentLoading = true;
    instrument = null;
    try {
      const next =
        instrumentCache.get(slug) ??
        (await getInstrument(slug, request.signal));
      if (request.signal.aborted) return;
      instrument = next;
      instrumentCache.set(slug, next);
    } catch (error) {
      if (!request.signal.aborted) instrumentError = getApiErrorMessage(error);
    } finally {
      if (!request.signal.aborted) instrumentLoading = false;
    }
  }
  async function generateShare(): Promise<void> {
    if (!result || shareBusy) return;
    const sourceReport = result.track_palette;
    shareBusy = true;
    shareFeedback = "Preparando sua imagem…";
    try {
      const blob = await createShareImage(sourceReport);
      if (result?.track_palette !== sourceReport || view !== "report") return;
      if (sharePreviewUrl) URL.revokeObjectURL(sharePreviewUrl);
      shareBlob = blob;
      sharePreviewUrl = URL.createObjectURL(blob);
      shareFeedback =
        "Sua imagem está pronta. Confira a prévia antes de baixar.";
    } catch (error) {
      shareFeedback =
        error instanceof Error
          ? error.message
          : "Não foi possível gerar a imagem.";
    } finally {
      shareBusy = false;
    }
  }
  function downloadShare(): void {
    if (!shareBlob || !result) return;
    downloadShareImage(shareBlob, result.profile.username);
    shareFeedback = "Imagem baixada para guardar ou compartilhar.";
  }
  onDestroy(() => {
    controller?.abort();
    instrumentController?.abort();
    if (sharePreviewUrl) URL.revokeObjectURL(sharePreviewUrl);
  });
  function isTheme(value: unknown): value is Theme {
    return value === "dark" || value === "light" || value === "system";
  }
  function applyTheme(): void {
    resolvedTheme =
      theme === "system"
        ? systemThemeQuery?.matches
          ? "light"
          : "dark"
        : theme;
    document.documentElement.dataset.theme = resolvedTheme;
  }
  function watchSystemTheme(): void {
    if (systemThemeQuery) return;
    systemThemeQuery = window.matchMedia("(prefers-color-scheme: light)");
    systemThemeQuery.addEventListener("change", applyTheme);
  }
  function unwatchSystemTheme(): void {
    systemThemeQuery?.removeEventListener("change", applyTheme);
    systemThemeQuery = null;
  }
  function setTheme(next: Theme): void {
    theme = next;
    if (next === "system") watchSystemTheme();
    else unwatchSystemTheme();
    applyTheme();
    setStorageItem(themeStorageKey, next);
  }
  function toggleTheme(): void {
    const next: Record<Theme, Theme> = {
      dark: "light",
      light: "system",
      system: "dark",
    };
    setTheme(next[theme]);
  }
  onMount(() => {
    const catalogController = new AbortController();
    void checkCatalog(catalogController.signal);
    const savedTheme = getStorageItem<unknown>(themeStorageKey);
    setTheme(isTheme(savedTheme) ? savedTheme : "system");
    const params = new URL(window.location.href).searchParams;
    const profile = params.get("profile");
    const requested = params.get("period") as ListeningPeriod | null;
    if (profile) {
      username = normalizeUsername(profile);
      if (requested && periods.some((item) => item.value === requested))
        period = requested;
      void loadReport();
    }
    return () => {
      catalogController.abort();
      unwatchSystemTheme();
    };
  });
</script>

<div class="site-shell" data-view={view} data-theme={resolvedTheme}>
  <header class="site-header">
    <div class="header-identity">
      <a class="wordmark" href={homePath} aria-label="Timbre Palette, início">
        <img src="./favicon-32x32.png" alt="" aria-hidden="true" />
        <span>TIMBRE PALETTE</span>
      </a>
      <ProductVersion />
    </div>
    <div class="header-actions">
      {#if catalogGrowth && view === "entry"}
        <CatalogGrowth {...catalogGrowth} />
      {/if}
      <button
        class="theme-toggle"
        type="button"
        aria-label={`Tema ${themeLabels[theme].toLowerCase()}. Clique para alternar.`}
        title={theme === "system"
          ? `Sistema (${themeLabels[resolvedTheme].toLowerCase()})`
          : themeLabels[theme]}
        on:click={toggleTheme}>{themeLabels[theme]}</button
      >
    </div>
  </header>
  <main id="main-content">
    {#if view === "entry" || view === "loading"}
      <EntryView
        {username}
        {period}
        {periods}
        {formError}
        loading={view === "loading"}
        {loadingTitle}
        {loadingDescription}
        {loadingDetail}
        onUsernameChange={(value) => (username = value)}
        onPeriodChange={(value) => (period = value)}
        onSubmit={submit}
      />
    {:else if view === "report" && result}
      <ResultsView
        {result}
        {period}
        activeView={activeAnalysisView}
        onSelectView={selectAnalysisView}
        {sectionOptions}
        {periodLabels}
        {statusLabels}
        {confidenceLabels}
        {shareFeedback}
        {sharePreviewUrl}
        {shareBusy}
        {periodLoading}
        {periodError}
        {periods}
        onPeriodChange={changePeriod}
        onDownloadShare={downloadShare}
        onOpenInstrument={openInstrument}
        onOpenInstrumentSlug={(slug) => void loadInstrument(slug)}
        onGenerateShare={generateShare}
        getAvailability={availability}
      />
    {/if}
  </main>

  <footer class="site-footer">
    <div class="footer-explainers">
      <div class="footer-explainer">
        <Dropdown title="Limites técnicos">
          <p class="limits-intro">Uma leitura aproximada da sua escuta.</p>
          <p>
            A paleta combina seu histórico público do Last.fm com créditos
            instrumentais publicados. Não analisa o áudio das músicas nem mede o
            volume dos instrumentos.
          </p>
          <p>
            Um instrumento pode estar presente na música sem estar documentado
            nos créditos da gravação no MusicBrainz. Encontrar a gravação nessa
            base não garante encontrar seus instrumentos. Essa documentação
            varia entre repertórios, por isso uma ausência na paleta não
            significa ausência na música.
          </p>
          <p>
            O catálogo ainda está em construção: faixas sem evidência
            instrumental aceita não entram no cálculo da paleta. A consulta usa
            um snapshot offline do MusicBrainz; sua hidratação pode melhorar uma
            visita futura, sem garantir novos créditos. O vocabulário dos
            artistas descreve gravações documentadas desses artistas e não
            comprova instrumentos em cada faixa ouvida.
          </p>
          <p>
            O temperamento da escuta é uma interpretação editorial e lúdica. Não
            é uma avaliação psicológica ou científica da sua personalidade.
          </p>
        </Dropdown>
      </div>
      {#if view === "report" && result}
        <div class="footer-explainer footer-explainer--source">
          <Dropdown title="Fonte dos créditos e versões" align="end">
            <p>
              Os instrumentos vêm de créditos publicados no MusicBrainz. Usamos
              o snapshot {result.snapshot.snapshot_version}, uma cópia desses
              dados. O projeto ainda pode consultar mais gravações dessa cópia;
              por isso, uma próxima visita pode trazer novos créditos.
            </p>
            <p>
              Esta leitura usa as regras da versão {result.track_palette
                .analysis.methodology_version} para a paleta das faixas e {result
                .artist_vocabulary.methodology_version} para o vocabulário dos artistas.
              Se o snapshot ou essas regras mudarem, o resultado também pode mudar.
            </p>
          </Dropdown>
        </div>
      {/if}
    </div>
    <div class="footer-colophon">
      <div class="footer-identity">
        <span class="footer-wordmark">TIMBRE PALETTE</span>
        <p class="footer-byline">
          por <a
            href="https://rosa-gus.github.io/portfolio"
            target="_blank"
            rel="noreferrer noopener">rosa gus</a
          > <span class="separator-indicator" aria-hidden="true">·</span> Código
          <a
            href="https://www.gnu.org/licenses/gpl-3.0.html"
            target="_blank"
            rel="noreferrer noopener">GPL-3.0</a
          >
        </p>
      </div>
      <div class="footer-source">
        <span class="footer-label">HISTÓRICO</span>
        <a href="https://www.last.fm/" target="_blank" rel="noreferrer noopener"
          >Last.fm</a
        >
      </div>
      <div class="footer-source">
        <span class="footer-label">CRÉDITOS</span>
        <a
          href="https://musicbrainz.org/"
          target="_blank"
          rel="noreferrer noopener">MusicBrainz</a
        >
      </div>
    </div>
  </footer>
</div>

<InstrumentDialog
  resource={instrument}
  bind:open={dialogOpen}
  loading={instrumentLoading}
  error={instrumentError}
  onOpenRelated={(slug) => void loadInstrument(slug)}
  onClose={() => instrumentController?.abort()}
/>

<style>
  .limits-intro {
    color: var(--ink);
  }
</style>
