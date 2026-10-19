<script lang="ts">
  import { formatNumber, formatPercent, formatRegisteredDate } from "../i18n/formatters";
  import { translation as t, localeStore } from "../i18n/runtime";
  import { Tabs } from "bits-ui";
  import { normalizePathname } from "../navigation";
  import { getAsciiLines, getFamilyTexture, hasAsciiDrawing } from "../sharing/ascii";
  import { fitFamilyTexture } from "../sharing/texture";
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
    ProfileAnalysisV3,
    SectionAvailability,
    VocabularyFeaturedArtist,
  } from "../api/types";
  import HistoryResumeNotice from "../components/HistoryResume.svelte";
  import type { HistoryResume } from "../analysis/history";
  import ReportView from "./ReportView.svelte";

  type SectionId = "portrait" | "palette" | "discovery" | "share";
  export let result: ProfileAnalysisV3;
  export let revealReady = true;
  export let localizationIncomplete = false;
  export let localizationPending = false;
  export let onRetryLocalization: () => void = () => undefined;
  export let period: ListeningPeriod = "1month";
  export let periods: { value: ListeningPeriod; label: string }[] = [];
  export let periodLoading = false;
  export let periodError = "";
  export let resumeProgress: HistoryResume | null = null;
  export let waitSeconds = 0;
  export let onResume: () => void = () => undefined;
  export let periodRevealKey = 0;
  export let onPeriodChange: (value: ListeningPeriod) => void = () => undefined;
  export let activeView: AnalysisView;
  export let onSelectView: (view: AnalysisView) => void;
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
    ? $t("availability.available")
    : vocabularyPending
      ? $t("vocabulary.pending")
      : $t("status.insufficient");
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
  $: registeredLabel = formatRegisteredDate(result.profile.registered, $localeStore);
  $: showLowCoverageNotice =
    revealReady &&
    !periodLoading &&
    !periodError &&
    result.profile.period === period &&
    palette.profile.period === period &&
    palette.analysis.coverage_tracks <= 0.01 &&
    selectedPeriodButton !== null &&
    dismissedLowCoveragePeriod !== period;

  $: percent = (value: number): string => formatPercent(value, 0, $localeStore);
  $: coveragePercent = (value: number): string => formatPercent(value, 1, $localeStore);
  $: count = (value: number): string => formatNumber(value, undefined, $localeStore);
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
  ): { name: string; locale?: string; slug: string | null; tone: string }[] {
    const seen = new Set<string>();
    return artist.families
      .flatMap((family) => {
        const listed = vocabulary.families.find(
          (item) => item.slug === family.slug,
        );
        return family.instruments.map((name) => ({
          name,
          locale: listed?.instruments.find((item) => item.name === name)?.locale,
          slug: listed?.instruments.find((item) => item.name === name)?.slug ?? null,
          tone: listed?.tone?.highlight ?? "#F29191",
        }));
      })
      .filter((instrument) => {
        if (seen.has(instrument.name)) return false;
        seen.add(instrument.name);
        return true;
      })
      .slice(0, 3);
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
        $t("vocabulary.noRecurringInstruments"),
      insufficient_track_reach:
        $t("vocabulary.lowTrackReach"),
      insufficient_play_reach:
        $t("vocabulary.lowPlayReach"),
      insufficient_artist_diversity:
        $t("vocabulary.lowArtistDiversity"),
      excessive_artist_concentration:
        $t("vocabulary.highConcentration"),
    };
    return (
      reasons[reason] ??
      $t("vocabulary.insufficientEvidence")
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
</script>

<div class="results-view">
  <div class="results-opening">
  <a class="back-link" href={homePath}><Arrow direction="left" />{$t("navigation.backUpper")}</a>
  <section
    class="profile-card"
    aria-labelledby="profile-title"
  >
    <div class="profile-avatar">
      {#if result.is_example}
        <pre class="profile-avatar-drawing" role="img" aria-label={$t("example.avatarAlt")}>{HERCULES_BEETLE_ASCII}</pre>
      {:else if result.profile.avatar_url}
        <img
          src={result.profile.avatar_url}
          alt={$t("profile.avatarAlt", { username: result.profile.username })}
          on:error={handleAvatarError}
        />
      {:else}
        <span aria-hidden="true">[ ? ? ? ]</span>
      {/if}
    </div>
    <div class="profile-copy">
      <div class="profile-identity">
        <div class="profile-label">
          {#if result.is_example}<Badge tone="accent">{$t("example.badge")}</Badge>{/if}
        </div>
        <h1 id="profile-title">
          {result.is_example
            ? result.profile.realname || $t("example.displayName")
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
          {#if registeredLabel}<span>{$t("profile.registered", { registeredLabel: registeredLabel })}</span
            >{/if}
          {#if result.is_example}<span>{$t("profile.exampleNotice")}</span>{/if}
          {#if palette.analysis.data_source !== "catalog"}
            <span
              >{palette.analysis.data_source === "mock"
                ? $t("profile.demoData")
                : $t("profile.hybridData")}</span
            >
          {/if}
        </div>
        <div class="profile-actions">
          {#if !result.is_example}<a
            class="profile-link"
            href={lastFmUrl}
            target="_blank"
            rel="noreferrer"
          >{$t("profile.openLastFm")} <Arrow direction="up-right" />
          </a>{/if}
        </div>
      </div>
    </div>
    <div class="period-controls" aria-busy={periodLoading}>
      <span class="period-label">{$t("periods.analysisHeading")}</span>
      <SegmentedControl
        label={$t("periods.analysisLabel")}
        options={periodOptions}
        value={period}
        bind:selectedButton={selectedPeriodButton}
        onChange={(value) => handlePeriodChange(value as ListeningPeriod)}
      />
      {#if periodLoading}
        <p class="period-loading" role="status" aria-live="polite">
          <span class="loading-indicator" aria-hidden="true"></span>
          <span>{$t("periods.updating", { period: periodLabels[period] })}</span>
        </p>
      {:else if periodError}
        <p class="period-error" role="alert">{periodError}</p>
      {/if}
      {#if resumeProgress && !periodLoading}
        <HistoryResumeNotice progress={resumeProgress} {waitSeconds} periodLabel={periodLabels[resumeProgress.period]} {onResume} />
      {/if}
      {#if periodRevealKey > 0 && !periodLoading && !periodError}
        <p class="visually-hidden" role="status">{$t("periods.updated", { period: periodLabels[period] })} </p>
      {/if}
      {#if showLowCoverageNotice}
        <Tooltip
          frozen
          anchor={selectedPeriodButton}
          align="center"
          onClose={dismissLowCoverageNotice}
        >
          <p aria-live="polite">{$t("periods.lowCoverage", { period: periodLabels[period], coverage: coveragePercent(
              palette.analysis.coverage_tracks,
            ) })} </p>
        </Tooltip>
      {/if}
    </div>
  </section>
  </div>

  {#key periodRevealKey}
  <div class:period-reveal={periodRevealKey > 0} class="reading-content">
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
      aria-label={$t("results.viewsLabel")}
    >
      <Tabs.Trigger value="track_palette" class="view-tab view-tab-palette">
        <span>{$t("results.trackPaletteTab")}</span>
        <small>{statusLabels[palette.analysis.status]}</small>
      </Tabs.Trigger>
      {#if vocabulary.status !== "insufficient"}
        <Tabs.Trigger
          value="artist_vocabulary"
          class="view-tab view-tab-vocabulary"
        >
          <span>{$t("results.artistVocabularyTab")}</span>
          <small>{vocabularyStatusLabel}</small>
        </Tabs.Trigger>
      {/if}
    </Tabs.List>

    <p class="view-description">
      <span aria-hidden="true">^ </span>
      {activeView === "track_palette"
        ? $t("results.trackPaletteDescription")
        : $t("results.artistVocabularyDescription")}
    </p>

      {#if localizationIncomplete}
        <div class="localization-notice">
          <span class="localization-info" aria-hidden="true">[i]</span>
          <p role="status">{localizationPending ? $t("localization.retrying") : $t("localization.partial")}</p>
          <button
            type="button"
            disabled={localizationPending}
            on:click={onRetryLocalization}
          >{localizationPending ? $t("localization.pending") : $t("localization.retry")}
            <span class="retry-arrow" aria-hidden="true">&#x21BB;&#xFE0E;</span>
          </button>
        </div>
      {/if}

    <Tabs.Content value="track_palette" class="view-panel">
      {#if directAvailable}
        <ReportView
          report={palette}
          isExample={result.is_example}
          {periodLabels}
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
          <p class="eyebrow">{$t("results.trackPaletteHeading")} <span
              class="separator-indicator"
              aria-hidden="true">·</span
            > {$t("results.insufficientBadge")} </p>
          <h2 id="direct-title">{$t("results.noPortraitTitle")}</h2>
          <p>{$t("results.noPortraitDescription")} </p>
          <p class="reading-measure">{$t("results.trackCoverage", { coverage: percent(palette.analysis.coverage_tracks) })} <span class="separator-indicator" aria-hidden="true">·</span>{$t("results.playCoverage", { coverage: percent(palette.analysis.coverage_plays) })} </p>
          {#if vocabularyAvailable}<button
              type="button"
              on:click={() => onSelectView("artist_vocabulary")}
              >{$t("results.openVocabulary")}</button
            >{/if}
        </section>
      {/if}
    </Tabs.Content>
    {#if vocabulary.status !== "insufficient"}
      <Tabs.Content value="artist_vocabulary" class="view-panel">
        <section class="vocabulary-reading" aria-labelledby="vocabulary-title">
          <div class="vocabulary-lead">
            <div>
              <p class="eyebrow">{$t("vocabulary.heading")} <span
                  class="separator-indicator"
                  aria-hidden="true">·</span
                >
                {vocabularyStatusLabel.toUpperCase()}
              </p>
              <h2 id="vocabulary-title">{$t("vocabulary.title")} </h2>
              <p class="lead-copy">{$t("vocabulary.description")} </p>
              <p class="scope-note">{$t("narrative.vocabulary.notice")}</p>
            </div>
            {#if predominantDrawing && predominantFamily}
              <figure
                class="type-art"
                aria-label={$t("vocabulary.drawingAlt", { name: predominantFamily.name })}
              >
                <pre aria-hidden="true">{predominantDrawing}</pre>
                <figcaption>{$t("vocabulary.predominantFamily", { name: predominantFamily.name })} </figcaption>
              </figure>
            {/if}
          </div>

          {#if vocabularyAvailable}
            <div
              class="vocabulary-color-strip"
              role="img"
              aria-label={$t("vocabulary.colorsLabel", { families: vocabulary.families.map((family) => `${family.name} ${percent(family.share)}`).join(", ") })}
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
                  <h3 id="featured-artists-title">{$t("vocabulary.featuredArtists")}</h3>
                  <p>{$t("vocabulary.featuredArtistsDescription")}</p>
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
                          >{$t("vocabulary.artistIndex", { index: String(index + 1).padStart(2, "0") })}</span
                        >
                        <h4>{artist.name}</h4>
                        <p class="artist-families">
                          {#each artist.families as family, index}
                            {#if index > 0} · {/if}<span lang={family.locale}>{family.name}</span>
                          {/each}
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
                                  style={`--family-accent:${instrument.tone}`}
                                  on:click={() =>
                                    instrument.slug &&
                                    onOpenInstrumentSlug(instrument.slug)}
                                  lang={instrument.locale}
                                  >{instrument.name}</button
                                >{:else}<span lang={instrument.locale}>{instrument.name}</span>{/if}
                            </span>
                          {/each}
                        </p>
                        <p class="artist-card-note">{$t("vocabulary.artistDescription")} </p>
                      </div>
                    </article>
                  {/each}
                </div>
              </section>
            {/if}
            <div class="reach-grid" aria-label={$t("vocabulary.reachLabel")}>
              <div>
                <span>{$t("vocabulary.qualifiedTracksHeading")}</span><strong
                  >{count(vocabulary.reach.qualified_tracks)} / {count(
                    vocabulary.reach.total_tracks,
                  )}</strong
                ><small
                  >{$t("vocabulary.trackReach", { coverage: percent(vocabulary.reach.track_reach) })}</small
                >
              </div>
              <div>
                <span>{$t("vocabulary.playsHeading")}</span><strong
                  >{percent(vocabulary.reach.play_reach)}</strong
                ><small
                  >{$t("vocabulary.playReach", { qualified: count(vocabulary.reach.qualified_plays), total: vocabulary.reach.total_plays })}</small
                >
              </div>
              <div>
                <span>{$t("vocabulary.qualifiedArtistsHeading")}</span><strong
                  >{count(vocabulary.reach.qualified_artists)} / {count(
                    vocabulary.reach.total_artists,
                  )}</strong
                ><small>{$t("vocabulary.recurringInstruments")}</small>
              </div>
            </div>
            <div class="family-heading">
              <span>{$t("vocabulary.familiesHeading")}</span>
            </div>
            <div class="vocabulary-families">
              {#each vocabulary.families as family, index}
                <article
                  class="vocabulary-family"
                  style={`--family-accent:${family.tone?.highlight ?? "#F29191"}`}
                >
                  <div class="family-meta">
                    <span class="family-index"
                      >{String(index + 1).padStart(2, "0")}</span
                    >
                    <span class="family-index" aria-hidden="true">/</span>
                    <button
                      type="button"
                      class="family-ficha"
                      aria-label={$t("actions.openInstrument", { name: family.name })}
                      on:click={() => onOpenInstrumentSlug(family.slug)}
                    >{$t("actions.open")}</button>
                  </div>
                  <div class="family-top">
                    <h3 lang={family.locale}>{family.name}</h3>
                    <strong>{percent(family.share)}</strong>
                  </div>
                  <div
                    class="vocabulary-bar"
                    role="img"
                    aria-label={$t("vocabulary.familyShareLabel", { name: family.name, share: percent(family.share) })}
                  >
                    <span
                      class="vocabulary-texture"
                      style={`width:${family.share * 100}%`}
                      aria-hidden="true"
                      use:fitFamilyTexture={getFamilyTexture(family.slug)}
                    ></span>
                  </div>
                  <p>
                    {$t("vocabulary.supportingArtistsCount", {
                      count: family.supporting_artists,
                    })}
                  </p>
                  <div class="family-evidence">
                    <Dropdown title={$t("vocabulary.evidenceTitle")}>
                      <p>{$t("vocabulary.evidenceDescription")} </p>
                      <ul>
                        {#each family.instruments as instrument}<li>
                            <button
                              type="button"
                              class="instrument-link"
                              on:click={() =>
                                onOpenInstrumentSlug(instrument.slug)}
                              lang={instrument.locale}
                              >{instrument.name}</button
                            ><span
                              >{$t("vocabulary.recordingCount", { count: instrument.distinct_recordings })} <span
                                class="separator-indicator"
                                aria-hidden="true">·</span
                              >{$t("vocabulary.creditScope", { scope: instrument.evidence.scope === "track"
                                ? $t("vocabulary.trackScope")
                                : $t("vocabulary.recordingScope") })}</span
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
                  ? $t("vocabulary.pendingTitle")
                  : $t("vocabulary.unavailableTitle")}
              </h3>
              <p>
                {vocabularyPending
                  ? $t("vocabulary.pendingDescription")
                  : reasonText(vocabulary.availability.reason)}
              </p>
            </div>
          {/if}

          {#if vocabularyAvailable}
            <div class="vocabulary-method">
              <Dropdown title={$t("vocabulary.metricsTitle")}>
                <p>{$t("vocabulary.reachDescription")} </p>
                <p>{$t("vocabulary.shareDescription")} </p>
                <p>{$t("vocabulary.concentration", { share: percent(
                    vocabulary.concentration,
                  ) })} </p>
                <p>{$t("vocabulary.unresolvedIdentities", { artists: vocabulary.reach.unresolved_artists, tracks: vocabulary.reach.unresolved_tracks })} </p>
                <p>{$t("vocabulary.snapshot", { snapshot_version: result.snapshot.snapshot_version })} <span class="separator-indicator" aria-hidden="true">·</span>{$t("vocabulary.methodology", { methodology_version: vocabulary.methodology_version })} </p>
              </Dropdown>
            </div>
          {/if}
        </section>
      </Tabs.Content>
    {/if}
  </Tabs.Root>
  </div>
  {/key}
</div>

<style>
  .localization-notice {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 0 12px;
    padding-top: 8px;
    color: var(--muted);
    font-size: 13px;
    line-height: 1.5;
  }
  .localization-info { font-family: var(--meta); }
  .localization-notice p { margin: 0; }
  .localization-notice button {
    display: inline-flex;
    align-items: center;
    justify-content: start;
    gap: 8px;
    min-height: 44px;
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: 12px/1.5 var(--meta);
  }
  .localization-notice button:is(:hover, :focus-visible):not(:disabled) {
    color: var(--accent-soft);
    text-decoration: underline;
    text-underline-offset: 4px;
  }
  .localization-notice button:disabled { cursor: wait; }
  .retry-arrow {
    font-family: var(--meta);
    font-weight: 400;
    font-size: 1.1em;
    line-height: 1;
  }
  @media (max-width: 800px) {
    .localization-notice { grid-template-columns: auto minmax(0, 1fr); align-items: baseline; }
    .localization-notice button { grid-column: 2; justify-self: start; }
  }

  .results-view {
    position: relative;
    isolation: isolate;
    --dither-large: 128px 128px;
    --dither-medium: 64px 64px;
    --dither-small: 32px 32px;
    --dither-fine: 16px 16px;
    width: 100%;
    max-width: 1320px;
    margin: 0 auto;
    padding: 54px 0 32px;
  }
  .period-reveal::after {
    position: absolute;
    z-index: 2;
    inset: 0;
    background: var(--panel);
    content: "";
    pointer-events: none;
    mask-repeat: repeat;
  }
  .results-opening {
    position: relative;
    /* Keep the coverage popover above the following reading-content layer. */
    z-index: 1;
    isolation: isolate;
  }
  .back-link {
    display: inline-block;
    margin-bottom: 20px;
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
    grid-template-columns: 64px minmax(0, 1fr);
    align-items: center;
    gap: 16px 20px;
    padding: 0 0 24px;
    margin-bottom: 24px;
    border-bottom: 1px solid var(--line-strong);
  }
  .profile-label {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .profile-avatar {
    display: grid;
    width: 64px;
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
    font: 3px/1.1 var(--meta);
    white-space: pre;
    transform: scaleX(1.3);
  }
  .profile-copy {
    display: grid;
    min-width: 0;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 6px 24px;
  }
  .profile-identity h1 {
    margin: 0;
    color: var(--ink);
    font-size: clamp(1.35rem, 2vw, 1.75rem);
    line-height: 1.1;
    overflow-wrap: anywhere;
  }
  .profile-username {
    display: inline;
    margin: 0;
    color: var(--muted);
    font: 14px var(--meta);
    overflow-wrap: anywhere;
  }
  .profile-identity {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px 12px;
    min-width: 0;
  }
  .profile-label:empty { display: none; }
  .profile-footer { display: contents; }
  .profile-meta {
    grid-column: 1;
    grid-row: 2;
    display: flex;
    flex-wrap: wrap;
    gap: 8px 18px;
    color: var(--muted);
    font: 12px/1.5 var(--meta);
  }
  .profile-actions {
    grid-column: 2;
    grid-row: 1 / 3;
    display: flex;
    align-items: center;
  }
  .profile-actions .profile-link {
    justify-content: space-between;
  }
  .profile-link {
    display: inline-flex;
    align-items: center;
    min-height: 40px;
    padding: 4px 0;
    color: var(--muted);
    font: 12px var(--meta);
    letter-spacing: 0.04em;
    text-decoration: none;
    white-space: nowrap;
  }
  .profile-link:hover,
  .profile-link:focus-visible {
    color: var(--accent-soft);
    text-decoration: underline;
    text-underline-offset: 4px;
  }
  .period-controls {
    grid-column: 1 / -1;
    display: grid;
    gap: 9px;
    padding-top: 0;
  }
  .period-label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
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
  .reading-content {
    position: relative;
    isolation: isolate;
  }
  .period-reveal {
    --dither-large: 96px 96px;
    --dither-medium: 48px 48px;
    --dither-small: 24px 24px;
    --dither-fine: 12px 12px;
  }
  .period-reveal::after {
    animation: dither-resolve 340ms steps(1, end) forwards;
  }
  @keyframes dither-resolve {
    0%, 4% {
      mask-image: none;
    }
    5%, 36% {
      mask-image: url("../assets/bayer-mask-75.svg");
      mask-size: var(--dither-large);
    }
    37%, 68% {
      mask-image: url("../assets/bayer-mask-50.svg");
      mask-size: var(--dither-medium);
    }
    69%, 85% {
      mask-image: url("../assets/bayer-mask-25.svg");
      mask-size: var(--dither-small);
    }
    86%, 99% {
      mask-image: url("../assets/bayer-mask-25.svg");
      mask-size: var(--dither-fine);
    }
    100% {
      visibility: hidden;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .period-reveal::after {
      display: none;
    }
  }
  :global(.view-tabs) {
    width: 100%;
  }
  .view-description {
    margin: 12px 0 0;
    color: var(--muted);
    font-size: 14px;
    line-height: 1.5;
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
    min-height: 56px;
    padding: 14px 20px;
    border: 0;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    text-align: left;
    font: 13px var(--meta);
    letter-spacing: 0.04em;
    transition:
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
    border-bottom-color: var(--accent-soft);
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
  .family-meta {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 12px;
  }
  .family-top {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: baseline;
    gap: 18px;
  }
  .family-top h3 {
    margin: 0;
    font-size: clamp(1.5rem, 2.3vw, 2.4rem);
  }
  .family-ficha {
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font: 12px/1.5 var(--meta);
    text-align: left;
    text-decoration: none;
    transition: color 150ms ease;
  }
  .vocabulary-family .family-ficha:hover,
  .vocabulary-family .family-ficha:focus-visible {
    color: color-mix(in srgb, var(--family-accent) 40%, black);
    text-decoration-color: currentColor;
  }
  .family-top strong {
    font: 20px var(--meta);
    color: var(--accent-soft);
  }
  .vocabulary-bar {
    min-width: 0;
    height: 28px;
    margin: 20px 0 14px;
    border-bottom: 1px solid var(--line);
  }
  .vocabulary-texture {
    display: block;
    height: 100%;
    border-bottom: 3px solid var(--family-accent);
    color: color-mix(in srgb, var(--family-accent) 40%, black);
    font: 14px/22px var(--meta);
    letter-spacing: 0;
    white-space: nowrap;
    pointer-events: none;
  }
  :global(:root[data-theme="dark"]) .vocabulary-texture {
    color: var(--family-accent);
  }
  .vocabulary-family > p {
    margin: 0;
    color: var(--muted);
    font-size: 14px;
  }
  .family-evidence {
    margin: 16px 0 0;
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
    text-decoration-color: var(--line-strong);
    text-decoration-thickness: 1px;
    text-underline-offset: 4px;
    transition:
      color 150ms ease,
      text-decoration-color 150ms ease;
  }
  .instrument-link:hover,
  .instrument-link:focus-visible {
    color: color-mix(in srgb, var(--family-accent) 40%, black);
    text-decoration-color: currentColor;
  }
  :global(:root[data-theme="dark"]) .family-ficha:is(:hover, :focus-visible),
  :global(:root[data-theme="dark"]) .instrument-link:is(:hover, :focus-visible) {
    color: var(--family-accent);
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
      grid-template-columns: 48px minmax(0, 1fr);
      gap: 12px;
      padding-bottom: 20px;
      margin-bottom: 20px;
    }
    .profile-avatar {
      width: 48px;
      align-self: start;
    }
    .profile-avatar-drawing { font-size: 2.3px; }
    .profile-identity h1 { font-size: 1.35rem; }
    .profile-copy {
      grid-template-columns: minmax(0, 1fr);
      gap: 4px;
    }
    .profile-username { font-size: 12px; }
    .profile-meta { font-size: 11px; }
    .profile-actions {
      grid-column: 1;
      grid-row: 3;
    }
    .profile-link { min-height: 32px; font-size: 11px; }
    .period-controls { padding-top: 0; }
    :global(.view-tab) {
      flex-direction: column;
      align-items: flex-start;
      justify-content: center;
      gap: 4px;
      min-height: 60px;
      padding: 12px 10px;
      font-size: 12px;
      line-height: 1.5;
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
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
    }
    .vocabulary-family li {
      display: grid;
      gap: 2px;
    }
  }
</style>
