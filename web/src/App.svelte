<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import {
    getApiErrorMessage,
    getInstrument,
    getAnalysis,
    getExampleAnalysis,
    normalizeUsername,
    getCatalogSize,
    apiBaseUrl,
  } from "./api/client";
  import { getStorageItem, setStorageItem } from "./storage";
  import { cleanupStorageVersions } from "./utils/storage-cleanup";
  import { STORAGE_KEYS } from "./utils/storage-keys";
  import { getHistoryResume, type HistoryResume } from "./analysis/history";
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
  import AnalysisLimits from "./components/AnalysisLimits.svelte";
  import { normalizePathname } from "./navigation";
  import CatalogGrowth from "./components/CatalogGrowth.svelte";
  import ResultsView from "./views/ResultsView.svelte";
  import EntryView from "./views/EntryView.svelte";
  import { getBrowserAnalysis, getBrowserExampleAnalysis } from "./analysis/browser";
  import { loadRuntimeConfig, profileAnalysisMode } from "./api/runtime-config";

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
  const themeLabels: Record<Theme, string> = {
    dark: "ESCURO",
    light: "CLARO",
    system: "SISTEMA",
  };
  const headerMarks: Record<ResolvedTheme, { src: string; srcset: string }> = {
    dark: {
      src: "./timbre-mark-header-dark-1x.png",
      srcset:
        "./timbre-mark-header-dark-1x.png 1x, ./timbre-mark-header-dark-2x.png 2x",
    },
    light: {
      src: "./timbre-mark-header-light-1x.png",
      srcset:
        "./timbre-mark-header-light-1x.png 1x, ./timbre-mark-header-light-2x.png 2x",
    },
  };
  const homePath = normalizePathname();
  let view: "entry" | "loading" | "report" = "entry";
  let catalogGrowth: { percent: number; added: number } | null = null;

  async function checkCatalog(signal: AbortSignal): Promise<void> {
    try {
      const current = await getCatalogSize(signal);
      // Only consume the saved comparison when the indicator can be shown.
      if (signal.aborted || view !== "entry") return;
      const saved = getStorageItem<unknown>(STORAGE_KEYS.catalogLastSeen);
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
      setStorageItem(STORAGE_KEYS.catalogLastSeen, {
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
  let isExample = false;
  let exampleId = "";
  let result: ProfileAnalysisV2 | null = null;
  let activeAnalysisView: AnalysisView = "track_palette";
  let formError = "";
  let loadingTitle = "Lendo seu histórico.";
  let loadingDescription = "As primeiras relações estão sendo reunidas.";
  let loadingDetail = "Consultando o Last.fm";
  let periodLoading = false;
  let periodError = "";
  let savedHistory: HistoryResume | null = null;
  let now = Date.now();
  $: matchingHistory = !isExample && savedHistory &&
    savedHistory.username.toLowerCase() === normalizeUsername(username).toLowerCase() ? savedHistory : null;
  $: entryHistory = matchingHistory?.period === period ? matchingHistory : null;
  $: waitSeconds = savedHistory ? Math.max(0, Math.ceil((savedHistory.retryAt - now) / 1000)) : 0;

  function refreshHistory(): void {
    now = Date.now();
    savedHistory = profileAnalysisMode() === "browser" ? getHistoryResume(apiBaseUrl()) : null;
  }
  function resumeReport(): void {
    refreshHistory();
    const saved = savedHistory;
    if (!saved || saved.username.toLowerCase() !== normalizeUsername(username).toLowerCase() ||
        saved.retryAt > Date.now() || view === "loading" || periodLoading || isExample) return;
    period = saved.period;
    void loadReport(view === "report", true);
  }
  let periodRevealKey = 0;
  let shareFeedback = "";
  let sharePreviewUrl = "";
  let shareBlob: Blob | null = null;
  let shareBusy = false;
  let canShareImage = false;
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
    if (isExample) {
      url.searchParams.delete("profile");
      url.searchParams.set("example", "1");
      url.searchParams.set("sample", exampleId);
    } else {
      url.searchParams.delete("example");
      url.searchParams.delete("sample");
      url.searchParams.set("profile", username);
    }
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
    if (next.track_palette.analysis.status !== "insufficient") {
      return "track_palette";
    }
    if (
      next.artist_vocabulary.status !== "insufficient" &&
      (next.available_views.includes("artist_vocabulary") ||
        next.artist_vocabulary.status === "pending")
    ) {
      return "artist_vocabulary";
    }
    if (next.default_view && next.available_views.includes(next.default_view)) {
      return next.default_view;
    }
    if (next.available_views.includes("artist_vocabulary")) {
      return "artist_vocabulary";
    }
    return "track_palette";
  }

  async function loadReport(preserveReport = false, resume = false): Promise<void> {
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
      periodRevealKey = 0;
      view = "loading";
      formError = "";
    }
    try {
      await loadRuntimeConfig();
      signal.throwIfAborted();
      const useBrowserAssembly = profileAnalysisMode() === "browser";
      const next = isExample
        ? useBrowserAssembly
          ? await getBrowserExampleAnalysis(period, signal, exampleId || undefined)
          : await getExampleAnalysis(period, signal, exampleId || undefined)
        : useBrowserAssembly
          ? await getBrowserAnalysis(username, period, signal, (phase, current, total) => {
              if (signal.aborted) return;
              loadingDetail = phase === "tracks"
                ? `Carregando faixas (${current}/${total})`
                : phase === "profile"
                  ? "Carregando perfil (1/1)"
                  : phase === "evidence"
                    ? `Consultando evidências (${current}/${total})`
                    : "Montando resultado...";
            }, resume)
          : await getAnalysis(username, period, signal);
      signal.throwIfAborted();
      if (controller !== request) return;
      result = next;
      if (preserveReport) periodRevealKey += 1;
      isExample = next.is_example;
      exampleId = next.example_id ?? "";
      username = next.profile.username;
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
      if (signal.aborted || controller !== request) return;
      if (preserveReport) {
        periodLoading = false;
        periodError = getApiErrorMessage(error);
        if (result) period = result.profile.period;
        updateUrl();
      } else {
        view = "entry";
        formError = getApiErrorMessage(error);
      }
    } finally {
      if (controller === request) refreshHistory();
    }
  }
  function changePeriod(next: ListeningPeriod): void {
    if (next === period || periodLoading || !result) return;
    period = next;
    void loadReport(true);
  }
  function submit(): void {
    isExample = false;
    exampleId = "";
    loadingTitle = "Lendo seu histórico.";
    loadingDescription = "As primeiras relações estão sendo reunidas.";
    loadingDetail = "Consultando o Last.fm";
    username = normalizeUsername(username);
    if (!username) {
      formError = "Informe um perfil do Last.fm para começar.";
      return;
    }
    if (view === "loading") return;
    void loadReport();
  }
  function createExampleId(): string {
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
      "",
    );
  }
  function openExample(): void {
    if (view === "loading") return;
    isExample = true;
    exampleId = createExampleId();
    username = "";
    loadingTitle = "Preparando o exemplo.";
    loadingDescription = "Selecionando gravações e créditos do catálogo.";
    loadingDetail = "Consultando o catálogo";
    formError = "";
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
      const blob = await createShareImage(sourceReport, undefined, {
        isExample: result.is_example,
        displayName: result.profile.realname || "Besouro Hércules",
      });
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
    downloadShareImage(
      shareBlob,
      result.is_example ? "besouro-hercules" : result.profile.username,
    );
    shareFeedback = "Imagem baixada para guardar ou compartilhar.";
  }
  async function shareImage(): Promise<void> {
    if (!shareBlob || !result || !canShareImage) return;
    const usernameSlug = (
      result.is_example ? "besouro-hercules" : result.profile.username
    )
      .toLowerCase()
      .replace(/[^a-z0-9]+/gi, "-");
    const file = new File(
      [shareBlob],
      `paleta-${usernameSlug || "escuta"}.png`,
      { type: "image/png" },
    );
    try {
      await navigator.share({
        files: [file],
        title: result.is_example
          ? "Escuta de exemplo do Besouro Hércules"
          : "Minha escuta em cores",
        text: result.is_example
          ? "Uma escuta fictícia montada com gravações e créditos reais do catálogo."
          : "Os instrumentos encontrados nas músicas que ouvi formaram esta paleta.",
      });
      shareFeedback = "Compartilhamento concluído.";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        shareFeedback = "Compartilhamento cancelado.";
        return;
      }
      shareFeedback =
        "Não foi possível compartilhar agora. Você ainda pode baixar a imagem.";
    }
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
    setStorageItem(STORAGE_KEYS.theme, next);
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
    cleanupStorageVersions();
    const catalogController = new AbortController();
    try {
      if (
        typeof navigator.share === "function" &&
        typeof navigator.canShare === "function"
      ) {
        const probeFile = new File([], "paleta.png", { type: "image/png" });
        canShareImage = navigator.canShare({ files: [probeFile] });
      }
    } catch {
      canShareImage = false;
    }
    const historyTimer = window.setInterval(refreshHistory, 1000);
    void loadRuntimeConfig().then(() => {
      if (catalogController.signal.aborted) return;
      refreshHistory();
      if (view === "entry" && !username && !isExample && savedHistory) {
        username = savedHistory.username;
        period = savedHistory.period;
      }
      if (profile && !isExample && view === "entry") {
        const matches = savedHistory && savedHistory.username.toLowerCase() === username.toLowerCase() && savedHistory.period === period;
        if (!matches) void loadReport();
      }
      void checkCatalog(catalogController.signal);
    });
    const savedTheme = getStorageItem<unknown>(STORAGE_KEYS.theme);
    setTheme(isTheme(savedTheme) ? savedTheme : "system");
    const params = new URL(window.location.href).searchParams;
    const profile = params.get("profile");
    const requested = params.get("period") as ListeningPeriod | null;
    if (requested && periods.some((item) => item.value === requested))
      period = requested;
    if (params.get("example") === "1") {
      isExample = true;
      exampleId = params.get("sample") || createExampleId();
      void loadReport();
    } else if (profile) {
      username = normalizeUsername(profile);
    }
    return () => {
      window.clearInterval(historyTimer);
      catalogController.abort();
      unwatchSystemTheme();
    };
  });
</script>

<div class="site-shell" data-view={view} data-theme={resolvedTheme}>
  <header class="site-header">
    <div class="header-identity">
      <a class="wordmark" href={homePath} aria-label="Timbre Palette, início">
        <img
          src={headerMarks[resolvedTheme].src}
          srcset={headerMarks[resolvedTheme].srcset}
          width="111"
          height="44"
          alt=""
          aria-hidden="true"
        />
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
        resumeProgress={entryHistory}
        {waitSeconds}
        onResume={() => resumeReport()}
        loading={view === "loading"}
        {loadingTitle}
        {loadingDescription}
        {loadingDetail}
        onUsernameChange={(value) => {
          username = value;
          isExample = false;
          exampleId = "";
        }}
        onPeriodChange={(value) => (period = value)}
        onSubmit={submit}
        onExample={openExample}
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
        {canShareImage}
        {periodLoading}
        {periodError}
        resumeProgress={matchingHistory}
        {waitSeconds}
        onResume={() => resumeReport()}
        {periodRevealKey}
        {periods}
        onPeriodChange={changePeriod}
        onDownloadShare={downloadShare}
        onShareImage={shareImage}
        onOpenInstrument={openInstrument}
        onOpenInstrumentSlug={(slug) => void loadInstrument(slug)}
        onGenerateShare={generateShare}
        getAvailability={availability}
      />
    {/if}
  </main>

  <footer class="site-footer">
    {#if view === "report"}
      <div class="footer-explainers">
        <div class="footer-explainer">
          <AnalysisLimits />
        </div>
        {#if result}
          <div class="footer-explainer footer-explainer--source">
            <Dropdown
              title="Fonte dos créditos e versões"
              align="end"
              mobileStart
            >
              <p>
                Os instrumentos vêm de créditos publicados no MusicBrainz. Usamos
                o snapshot <code class="source-value">{result.snapshot.snapshot_version}</code>, uma cópia desses
                dados. O projeto ainda pode consultar mais gravações dessa cópia;
                por isso, uma próxima visita pode trazer novos créditos.
              </p>
              <p>
                Esta leitura usa as regras da versão <code class="source-value">{result.track_palette
                  .analysis.methodology_version}</code> para a paleta das faixas e <code class="source-value">{result
                  .artist_vocabulary.methodology_version}</code> para o vocabulário dos artistas.
                Se o snapshot ou essas regras mudarem, o resultado também pode mudar.
              </p>
            </Dropdown>
          </div>
        {/if}
      </div>
    {/if}
    <div class="footer-colophon">
      <div class="footer-identity">
        <div class="footer-brand">
          <span class="footer-wordmark">TIMBRE PALETTE</span>
          <span class="footer-signature" aria-hidden="true"># + : *</span>
        </div>
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
  .source-value {
    padding: 2px 5px;
    background: var(--panel);
    color: var(--ink);
    font: 0.95em/1.6 var(--meta);
    overflow-wrap: anywhere;
    -webkit-box-decoration-break: clone;
    box-decoration-break: clone;
  }
</style>
