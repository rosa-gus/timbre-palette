<script lang="ts">
  import {
    localizeAnalysis,
    localizedInstrument as getInstrument,
  } from "./i18n/resources";
  import LanguageSelect from "./i18n/LanguageSelect.svelte";
  import Message from "./i18n/Message.svelte";
  import { translation as t, localeStore } from "./i18n/runtime";
  import { onMount, onDestroy, tick } from "svelte";
  import bayer75 from "./assets/bayer-mask-75.svg";
  import bayer50 from "./assets/bayer-mask-50.svg";
  import bayer25 from "./assets/bayer-mask-25.svg";
  import {
    getApiErrorMessage,
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
    ProfileAnalysisV3,
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
  import {
    getBrowserAnalysis,
    getBrowserExampleAnalysis,
  } from "./analysis/browser";
  import { loadRuntimeConfig, profileAnalysisMode } from "./api/runtime-config";

  type SectionId = "portrait" | "palette" | "discovery" | "share";
  $: periods = [
    { value: "7day", label: $t("periods.week") },
    { value: "1month", label: $t("periods.month") },
    { value: "3month", label: $t("periods.threeMonths") },
    { value: "6month", label: $t("periods.sixMonths") },
    { value: "12month", label: $t("periods.year") },
    { value: "overall", label: $t("periods.overall") },
  ] satisfies { value: ListeningPeriod; label: string }[];
  $: periodLabels = Object.fromEntries(
    periods.map((item) => [item.value, item.label]),
  ) as Record<ListeningPeriod, string>;
  $: sectionLabels = {
    portrait: $t("sections.portrait"),
    palette: $t("sections.palette"),
    discovery: $t("sections.discovery"),
    share: $t("actions.share"),
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
  $: availabilityLabels = {
    available: $t("availability.available"),
    insufficient_coverage: $t("availability.insufficientCoverage"),
    insufficient_diversity: $t("availability.insufficientDiversity"),
    insufficient_nature_evidence: $t("availability.insufficientNature"),
    no_candidate: $t("availability.noCandidate"),
  };
  $: statusLabels = {
    partial: $t("status.partial"),
    ready: $t("status.ready"),
    insufficient: $t("status.insufficient"),
  };
  $: confidenceLabels = {
    documented: $t("confidence.documented"),
    strongly_associated: $t("confidence.associated"),
    estimated: $t("confidence.estimated"),
  };
  type Theme = "dark" | "light" | "system";
  type ResolvedTheme = Exclude<Theme, "system">;
  $: themeLabels = {
    dark: $t("theme.dark"),
    light: $t("theme.light"),
    system: $t("theme.system"),
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
  let preparingReport = false;
  let revealAssets: Promise<unknown> | null = null;

  async function prepareReport(signal: AbortSignal): Promise<void> {
    // Decode the reveal masks before starting the animation on cold visits.
    revealAssets ??= Promise.all(
      [bayer75, bayer50, bayer25].map((src) => {
        const image = new Image();
        image.src = src;
        return image.decode().catch(() => undefined);
      }),
    );
    await tick();
    await Promise.all([revealAssets, document.fonts.ready]);
    signal.throwIfAborted();
    // Keep the loading composition visible while the mounted report settles.
    await new Promise<void>((resolve) => window.setTimeout(resolve, 180));
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    });
    signal.throwIfAborted();
  }
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
  let result: ProfileAnalysisV3 | null = null;
  let displayResult: ProfileAnalysisV3 | null = null;
  let localizationPending = false;
  let localizationController: AbortController | null = null;
  $: void updatePresentation(result, $localeStore);
  async function updatePresentation(
    source: ProfileAnalysisV3 | null,
    language: typeof $localeStore,
  ) {
    localizationController?.abort();
    const request = new AbortController();
    localizationController = request;
    displayResult = source;
    localizationPending = Boolean(source && language !== "pt-BR");
    if (!source) return;
    try {
      const translated = await localizeAnalysis(
        source,
        language,
        request.signal,
      );
      if (!request.signal.aborted) displayResult = translated;
    } catch {
      /* Keep the existing report if localized resources are unavailable. */
    } finally {
      if (!request.signal.aborted) localizationPending = false;
    }
  }
  let previousLocale = $localeStore;
  $: if ($localeStore !== previousLocale) {
    previousLocale = $localeStore;
    if (sharePreviewUrl) URL.revokeObjectURL(sharePreviewUrl);
    sharePreviewUrl = "";
    shareBlob = null;
    shareFeedback = "";
    if (dialogOpen && requestedInstrumentSlug)
      void loadInstrument(requestedInstrumentSlug);
    loadingTitle = $t(
      isExample ? "loading.exampleTitle" : "loading.historyTitle",
    );
    loadingDescription = $t(
      isExample ? "loading.exampleDescription" : "loading.historyDescription",
    );
    loadingDetail = $t(isExample ? "loading.catalog" : "loading.historyDetail");
  }
  let activeAnalysisView: AnalysisView = "track_palette";
  let formErrorSource: unknown = null;
  $: formError =
    formErrorSource === "usernameRequired"
      ? $t("errors.usernameRequired")
      : formErrorSource
        ? $localeStore && getApiErrorMessage(formErrorSource)
        : "";
  let loadingTitle = $t("loading.historyTitle");
  let loadingDescription = $t("loading.historyDescription");
  let loadingDetail = $t("loading.historyDetail");
  let periodLoading = false;
  let periodErrorSource: unknown = null;
  $: periodError = periodErrorSource
    ? $localeStore && getApiErrorMessage(periodErrorSource)
    : "";
  let savedHistory: HistoryResume | null = null;
  let now = Date.now();
  $: matchingHistory =
    !isExample &&
    savedHistory &&
    savedHistory.username.toLowerCase() ===
      normalizeUsername(username).toLowerCase()
      ? savedHistory
      : null;
  $: entryHistory = matchingHistory?.period === period ? matchingHistory : null;
  $: waitSeconds = savedHistory
    ? Math.max(0, Math.ceil((savedHistory.retryAt - now) / 1000))
    : 0;

  function refreshHistory(): void {
    now = Date.now();
    savedHistory =
      profileAnalysisMode() === "browser"
        ? getHistoryResume(apiBaseUrl())
        : null;
  }
  function resumeReport(): void {
    refreshHistory();
    const saved = savedHistory;
    if (
      !saved ||
      saved.username.toLowerCase() !==
        normalizeUsername(username).toLowerCase() ||
      saved.retryAt > Date.now() ||
      view === "loading" ||
      periodLoading ||
      isExample
    )
      return;
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
  let requestedInstrumentSlug = "";
  let instrumentLoading = false;
  let instrumentError = "";
  let controller: AbortController | null = null;
  let instrumentController: AbortController | null = null;
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
    next: ProfileAnalysisV3,
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

  async function loadReport(
    preserveReport = false,
    resume = false,
  ): Promise<void> {
    controller?.abort();
    const request = new AbortController();
    controller = request;
    preparingReport = false;
    const signal = request.signal;
    if (sharePreviewUrl) URL.revokeObjectURL(sharePreviewUrl);
    sharePreviewUrl = "";
    shareBlob = null;
    shareFeedback = "";
    if (preserveReport) {
      periodLoading = true;
      periodErrorSource = null;
    } else {
      periodRevealKey = 0;
      view = "loading";
      formErrorSource = null;
    }
    try {
      await loadRuntimeConfig();
      signal.throwIfAborted();
      const useBrowserAssembly = profileAnalysisMode() === "browser";
      const next = isExample
        ? useBrowserAssembly
          ? await getBrowserExampleAnalysis(
              period,
              signal,
              exampleId || undefined,
            )
          : await getExampleAnalysis(period, signal, exampleId || undefined)
        : useBrowserAssembly
          ? await getBrowserAnalysis(
              username,
              period,
              signal,
              (phase, current, total) => {
                if (signal.aborted) return;
                loadingDetail =
                  phase === "tracks"
                    ? $t("loading.tracksProgress", {
                        current: current,
                        total: total,
                      })
                    : phase === "profile"
                      ? $t("loading.profileProgress")
                      : phase === "evidence"
                        ? $t("loading.evidenceProgress", {
                            current: current,
                            total: total,
                          })
                        : $t("loading.assembly");
              },
              resume,
            )
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
      if (!preserveReport) {
        preparingReport = true;
        loadingDetail = $t("loading.palette");
        await prepareReport(signal);
        if (controller !== request) return;
      }
      view = "report";
      preparingReport = false;
      periodLoading = false;
      periodErrorSource = null;
      updateUrl();
      return;
    } catch (error) {
      if (signal.aborted || controller !== request) return;
      preparingReport = false;
      if (preserveReport) {
        periodLoading = false;
        periodErrorSource = error;
        if (result) period = result.profile.period;
        updateUrl();
      } else {
        view = "entry";
        formErrorSource = error;
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
    loadingTitle = $t("loading.historyTitle");
    loadingDescription = $t("loading.historyDescription");
    loadingDetail = $t("loading.historyDetail");
    username = normalizeUsername(username);
    if (!username) {
      formErrorSource = "usernameRequired";
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
    loadingTitle = $t("loading.exampleTitle");
    loadingDescription = $t("loading.exampleDescription");
    loadingDetail = $t("loading.catalog");
    formErrorSource = null;
    void loadReport();
  }
  function openInstrument(): void {
    const slug = result?.track_palette.discovery?.instrument_slug;
    if (slug) void loadInstrument(slug);
  }
  async function loadInstrument(slug: string): Promise<void> {
    requestedInstrumentSlug = slug;
    const language = $localeStore;
    instrumentController?.abort();
    const request = new AbortController();
    instrumentController = request;
    dialogOpen = true;
    instrumentError = "";
    instrumentLoading = true;
    instrument = null;
    try {
      const next = await getInstrument(slug, request.signal, language);
      if (request.signal.aborted) return;
      instrument = next;
    } catch (error) {
      if (!request.signal.aborted) instrumentError = getApiErrorMessage(error);
    } finally {
      if (!request.signal.aborted) instrumentLoading = false;
    }
  }
  async function generateShare(): Promise<void> {
    if (!result || shareBusy || localizationPending) return;
    const sourceReport = displayResult?.track_palette ?? result.track_palette;
    const shareLocale = $localeStore;
    shareBusy = true;
    shareFeedback = $t("sharing.preparing");
    try {
      const blob = await createShareImage(sourceReport, undefined, {
        isExample: result.is_example,
        displayName:
          displayResult?.profile.realname ||
          result.profile.realname ||
          $t("example.displayName"),
      });
      if (
        (displayResult?.track_palette ?? result?.track_palette) !==
          sourceReport ||
        $localeStore !== shareLocale ||
        view !== "report"
      )
        return;
      if (sharePreviewUrl) URL.revokeObjectURL(sharePreviewUrl);
      shareBlob = blob;
      sharePreviewUrl = URL.createObjectURL(blob);
      shareFeedback = $t("sharing.ready");
    } catch (error) {
      shareFeedback =
        error instanceof Error ? error.message : $t("sharing.failed");
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
    shareFeedback = $t("sharing.downloaded");
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
          ? $t("sharing.exampleTitle")
          : $t("sharing.title"),
        text: result.is_example
          ? $t("sharing.exampleDescription")
          : $t("sharing.description"),
      });
      shareFeedback = $t("sharing.completed");
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        shareFeedback = $t("sharing.cancelled");
        return;
      }
      shareFeedback = $t("sharing.unavailable");
    }
  }
  onDestroy(() => {
    controller?.abort();
    instrumentController?.abort();
    localizationController?.abort();
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
        const matches =
          savedHistory &&
          savedHistory.username.toLowerCase() === username.toLowerCase() &&
          savedHistory.period === period;
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

{#snippet sourceCode(text: string)}<code class="source-value">{text}</code
  >{/snippet}

<div class="site-shell" data-view={view} data-theme={resolvedTheme}>
  <header class="site-header">
    <div class="header-identity">
      <a class="wordmark" href={homePath} aria-label={$t("navigation.home")}>
        <img
          src={headerMarks[resolvedTheme].src}
          srcset={headerMarks[resolvedTheme].srcset}
          width="111"
          height="44"
          alt=""
          aria-hidden="true"
        />
      </a>
      <LanguageSelect />
    </div>
    <div class="header-actions">
      {#if catalogGrowth && view === "entry"}
        <CatalogGrowth {...catalogGrowth} />
      {/if}
      <button
        class="theme-toggle"
        type="button"
        aria-label={$t("theme.toggleLabel", {
          theme: themeLabels[theme].toLowerCase(),
        })}
        title={theme === "system"
          ? $t("theme.systemLabel", {
              theme: themeLabels[resolvedTheme].toLowerCase(),
            })
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
    {/if}
    {#if (view === "report" || preparingReport) && result}
      <div
        class="report-stage"
        class:preparing={preparingReport}
        inert={preparingReport}
        aria-hidden={preparingReport}
      >
        <ResultsView
          revealReady={view === "report"}
          result={displayResult ?? result}
          {period}
          activeView={activeAnalysisView}
          onSelectView={selectAnalysisView}
          {sectionOptions}
          {periodLabels}
          {statusLabels}
          {confidenceLabels}
          {shareFeedback}
          {sharePreviewUrl}
          shareBusy={shareBusy || localizationPending}
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
      </div>
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
              title={$t("sources.versionsTitle")}
              align="end"
              mobileStart
            >
              <p>
                <Message
                  message="sources.snapshot"
                  values={{ snapshot: result.snapshot.snapshot_version }}
                  wrappers={{ version: sourceCode }}
                />
              </p>
              <p>
                <Message
                  message="sources.method"
                  values={{
                    tracks: result.track_palette.analysis.methodology_version,
                    artists: result.artist_vocabulary.methodology_version,
                  }}
                  wrappers={{ version: sourceCode }}
                />
              </p>
            </Dropdown>
          </div>
        {/if}
      </div>
    {/if}
    <div class="footer-colophon">
      <span class="footer-signature" aria-hidden="true"># + : *</span>
      <div class="footer-identity">
        <div class="footer-brand">
          <span class="footer-wordmark">TIMBRE PALETTE</span>
          <ProductVersion />
        </div>
        <p class="footer-byline">
          {$t("footer.by")}
          <a
            href="https://rosa-gus.github.io/portfolio"
            target="_blank"
            rel="noreferrer noopener">rosa gus</a
          > <span class="separator-indicator" aria-hidden="true">·</span>
          {$t("footer.code")}
          <a
            href="https://www.gnu.org/licenses/gpl-3.0.html"
            target="_blank"
            rel="noreferrer noopener">GPL-3.0</a
          >
        </p>
      </div>
      <div class="footer-source">
        <span class="footer-label">{$t("footer.history")}</span>
        <a href="https://www.last.fm/" target="_blank" rel="noreferrer noopener"
          >Last.fm</a
        >
      </div>
      <div class="footer-source">
        <span class="footer-label">{$t("footer.credits")}</span>
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
  main {
    position: relative;
  }
  .report-stage {
    min-width: 0;
  }
  .report-stage.preparing {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    overflow: clip;
    visibility: hidden;
    pointer-events: none;
  }
</style>
