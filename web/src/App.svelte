<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import {
    getApiErrorMessage,
    getInstrument,
    getPalette,
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
    SectionAvailability,
  } from "./api/types";
  import { createShareImage, downloadShareImage } from "./sharing/share";
  import InstrumentDialog from "./components/InstrumentDialog.svelte";
  import ProductVersion from "./components/ProductVersion.svelte";
  import FooterLinkPreview from "./components/FooterLinkPreview.svelte";
  import TechnicalLimits from "./components/TechnicalLimits.svelte";
  import CatalogGrowth from "./components/CatalogGrowth.svelte";
  import EmptyView from "./views/EmptyView.svelte";
  import EntryView from "./views/EntryView.svelte";
  import ReportView from "./views/ReportView.svelte";

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

  let view: "entry" | "loading" | "report" | "empty" = "entry";
  let catalogGrowth: { percent: number; added: number } | null = null;

  async function checkCatalog(signal: AbortSignal): Promise<void> {
    try {
      const current = await getCatalogSize(signal);
      const saved = getStorageItem<unknown>(catalogStorageKey);
      if (saved && typeof saved === "object" && "schemaVersion" in saved &&
          "apiBaseUrl" in saved && saved.apiBaseUrl === apiBaseUrl() &&
          saved.schemaVersion === 1 && "recordingsWithEvidence" in saved &&
          typeof saved.recordingsWithEvidence === "number" &&
          Number.isSafeInteger(saved.recordingsWithEvidence) && saved.recordingsWithEvidence > 0 &&
          current > saved.recordingsWithEvidence) {
        const added = current - saved.recordingsWithEvidence;
        catalogGrowth = { percent: added / saved.recordingsWithEvidence * 100, added };
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
  let resolvedTheme: ResolvedTheme = "dark";
  let systemThemeQuery: MediaQueryList | null = null;
  let username = "";
  let period: ListeningPeriod = "7day";
  let report: PaletteReport | null = null;
  let formError = "";
  let loadingTitle = "Lendo seu histórico.";
  let loadingDescription = "As primeiras relações estão sendo reunidas.";
  let loadingDetail = "Consultando o Last.fm";
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
        !!report &&
        report.analysis.section_availability[availabilityKeys[value]] !==
          "available",
      note:
        value !== "share" && report
          ? availabilityLabels[
              report.analysis.section_availability[availabilityKeys[value]]
            ]
          : undefined,
    }),
  );

  function availability(section: SectionId): SectionAvailability {
    return (
      report?.analysis.section_availability[availabilityKeys[section]] ??
      "insufficient_coverage"
    );
  }

  function updateUrl(): void {
    const url = new URL(window.location.href);
    url.searchParams.set("profile", username);
    url.searchParams.set("period", period);
    window.history.replaceState({}, "", url);
  }

  async function loadReport(): Promise<void> {
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    if (sharePreviewUrl) URL.revokeObjectURL(sharePreviewUrl);
    sharePreviewUrl = "";
    shareBlob = null;
    shareFeedback = "";
    formError = "";
    view = "loading";
    try {
      report = await getPalette(username, period, signal);
      if (report.analysis.status === "insufficient") view = "empty";
      else view = "report";
      updateUrl();
      return;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      view = "entry";
      formError = getApiErrorMessage(error);
    }
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
    const slug = report?.discovery?.instrument_slug;
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
    if (!report || shareBusy) return;
    const sourceReport = report;
    shareBusy = true;
    shareFeedback = "Preparando sua imagem…";
    try {
      const blob = await createShareImage(sourceReport);
      if (report !== sourceReport || view !== "report") return;
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
    if (!shareBlob || !report) return;
    downloadShareImage(shareBlob, report.profile.username);
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
    resolvedTheme = theme === "system"
      ? systemThemeQuery?.matches ? "light" : "dark"
      : theme;
    document.documentElement.dataset.theme = resolvedTheme;
  }
  function setTheme(next: Theme): void {
    theme = next;
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
    systemThemeQuery = window.matchMedia("(prefers-color-scheme: light)");
    const updateSystemTheme = () => {
      if (theme === "system") applyTheme();
    };
    systemThemeQuery.addEventListener("change", updateSystemTheme);
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
      systemThemeQuery?.removeEventListener("change", updateSystemTheme);
      systemThemeQuery = null;
    };
  });
</script>

<div class="site-shell" data-view={view} data-theme={resolvedTheme}>
  <header class="site-header">
    <div class="header-identity">
      <a class="wordmark" href="./" aria-label="Timbre Palette, início">
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
        title={theme === "system" ? `Sistema (${themeLabels[resolvedTheme].toLowerCase()})` : themeLabels[theme]}
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
    {:else if view === "empty" && report}
      <EmptyView notice={report.analysis.notice} />
    {:else if view === "report" && report}
      <ReportView
        {report}
        {sectionOptions}
        {periodLabels}
        {statusLabels}
        {confidenceLabels}
        {shareFeedback}
        {sharePreviewUrl}
        {shareBusy}
        onDownloadShare={downloadShare}
        onOpenInstrument={openInstrument}
        onGenerateShare={generateShare}
        getAvailability={availability}
      />
    {/if}
  </main>

  <TechnicalLimits />

  <footer class="site-footer">
    <small class="footer-credit"
      ><FooterLinkPreview
        href="https://rosa-gus.github.io/portfolio"
        label="rosa gus"
        description="Desenvolvimento e concepção do Timbre Palette. Esse link leva ao seu portfólio."
      /><span class="footer-separator" aria-hidden="true">/</span><FooterLinkPreview
        href="https://www.gnu.org/licenses/gpl-3.0.html"
        label="GPL-3.0"
        ariaLabel="Licença GPL-3.0"
        description="Licença do código do projeto. Consulte os termos da GPL-3.0."
      /></small
    >
    <small class="footer-powered"
      ><FooterLinkPreview href="https://www.last.fm/"
        label="Last.fm"
        description="Fonte do histórico público de escuta usado para criar sua paleta."
      /><span class="footer-separator" aria-hidden="true">/</span><FooterLinkPreview
        href="https://musicbrainz.org/"
        label="MusicBrainz"
        description="Fonte de créditos instrumentais usados no enriquecimento do catálogo."
      /></small
    >
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
