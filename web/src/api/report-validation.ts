import { REPORT_SCHEMA_VERSION, TEMPERAMENT_RULES } from "./types";
import type { PaletteReport, ProfileAnalysisV3, ProfileSummary } from "./types";
import { boundedText } from "./input-validation";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isCount(
  value: unknown,
  max = Number.MAX_SAFE_INTEGER,
): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0 &&
    value <= max
  );
}

function isUnitFraction(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0 && value <= 1;
}

function isOptionalText(
  value: unknown,
  maxLength = 512,
): value is string | null | undefined {
  return (
    value === undefined ||
    value === null ||
    (typeof value === "string" &&
      value.length <= maxLength &&
      !value.includes("\u0000"))
  );
}

function isProfileSummary(value: unknown): value is ProfileSummary {
  if (!isRecord(value)) return false;
  return (
    boundedText(value.username, 64) !== null &&
    ["overall", "7day", "1month", "3month", "6month", "12month"].includes(
      value.period as string,
    ) &&
    isCount(value.tracks_analyzed, 200) &&
    isCount(value.total_plays) &&
    isOptionalText(value.profile_url, 2_048) &&
    isOptionalText(value.avatar_url, 2_048) &&
    isOptionalText(value.realname, 256) &&
    isOptionalText(value.registered, 64)
  );
}

function isAvailability(value: unknown): boolean {
  return [
    "available",
    "insufficient_coverage",
    "insufficient_diversity",
    "insufficient_nature_evidence",
    "no_candidate",
  ].includes(value as string);
}

function isPaletteReport(value: unknown): value is PaletteReport {
  if (!isRecord(value)) return false;
  const profile = value.profile;
  const analysis = value.analysis;
  const availability = isRecord(analysis)
    ? analysis.section_availability
    : null;
  const vocalPresence = isRecord(analysis) ? analysis.vocal_presence : null;
  const families = value.families;
  const recordings = value.recordings;
  return (
    isProfileSummary(profile) &&
    isRecord(analysis) &&
    !("notice" in analysis) &&
    isOptionalText(analysis.catalog_version) &&
    ["mock", "hybrid", "catalog"].includes(analysis.data_source as string) &&
    ["mock", "lastfm"].includes(analysis.history_source as string) &&
    ["mock", "catalog"].includes(analysis.instrumentation_source as string) &&
    typeof analysis.methodology_version === "string" &&
    typeof analysis.image_catalog_version === "string" &&
    (analysis.status === "partial" ||
      analysis.status === "ready" ||
      analysis.status === "insufficient") &&
    isUnitFraction(analysis.coverage_tracks) &&
    isUnitFraction(analysis.coverage_plays) &&
    isRecord(vocalPresence) &&
    isCount(vocalPresence.documented_tracks) &&
    isCount(vocalPresence.documented_artists) &&
    isCount(vocalPresence.documented_plays) &&
    isUnitFraction(vocalPresence.track_ratio) &&
    isUnitFraction(vocalPresence.play_ratio) &&
    isRecord(availability) &&
    ["families", "sound_balance", "discovery", "temperament"].every((key) =>
      isAvailability(availability[key]),
    ) &&
    Array.isArray(families) &&
    families.length <= 50 &&
    families.every(
      (family) =>
        isRecord(family) &&
        boundedText(family.slug, 80) !== null &&
        boundedText(family.name, 256) !== null &&
        isCount(family.evidence_count) &&
        ["documented", "strongly_associated", "estimated"].includes(
          family.confidence as string,
        ) &&
        isUnitFraction(family.share),
    ) &&
    (value.discovery === null ||
      (isRecord(value.discovery) &&
        boundedText(value.discovery.instrument_slug, 80) !== null &&
        boundedText(value.discovery.instrument_name, 256) !== null &&
        !("title" in value.discovery) &&
        !("summary" in value.discovery))) &&
    (value.temperament === null ||
      (isRecord(value.temperament) &&
        boundedText(value.temperament.primary_family_slug, 80) !== null &&
        TEMPERAMENT_RULES.includes(
          value.temperament.rule as (typeof TEMPERAMENT_RULES)[number],
        ) &&
        ["acoustic", "electric", "electronic", "sampled", "hybrid"].includes(
          value.temperament.primary_nature as string,
        ) &&
        families.some(
          (family) =>
            isRecord(family) &&
            family.slug ===
              (value.temperament as Record<string, unknown>)
                .primary_family_slug,
        ) &&
        !("title" in value.temperament) &&
        !("summary" in value.temperament))) &&
    Array.isArray(recordings) &&
    recordings.length <= 200 &&
    recordings.every(
      (recording) =>
        isRecord(recording) &&
        boundedText(recording.title, 512) !== null &&
        boundedText(recording.artist, 256) !== null &&
        isCount(recording.play_count) &&
        [
          "resolved",
          "unresolved_identity",
          "pending_enrichment",
          "ambiguous",
          "resolved_without_evidence",
          "transient_failure",
          "terminal_failure",
        ].includes(recording.status as string) &&
        !("status_detail" in recording),
    )
  );
}

export function isProfileAnalysisV3(
  value: unknown,
): value is ProfileAnalysisV3 {
  if (!isRecord(value)) return false;
  const snapshot = value.snapshot;
  const hydration = value.hydration;
  const vocabulary = value.artist_vocabulary;
  const reach = isRecord(vocabulary) ? vocabulary.reach : null;
  const vocabularyAvailability = isRecord(vocabulary)
    ? vocabulary.availability
    : null;
  const availableViews = value.available_views;
  const defaultView = value.default_view;
  return (
    value.report_schema_version === REPORT_SCHEMA_VERSION &&
    typeof value.is_example === "boolean" &&
    isOptionalText(value.example_id) &&
    isProfileSummary(value.profile) &&
    isRecord(snapshot) &&
    typeof snapshot.snapshot_version === "string" &&
    typeof snapshot.schema_version === "string" &&
    typeof snapshot.manifest_hash === "string" &&
    typeof snapshot.object_prefix === "string" &&
    typeof snapshot.methodology_version === "string" &&
    isPaletteReport(value.track_palette) &&
    isRecord(vocabulary) &&
    ["available", "pending", "insufficient"].includes(
      vocabulary.status as string,
    ) &&
    !("notice" in vocabulary) &&
    typeof vocabulary.methodology_version === "string" &&
    isRecord(vocabularyAvailability) &&
    typeof vocabularyAvailability.reason === "string" &&
    isRecord(reach) &&
    ["track_reach", "play_reach"].every((key) => isUnitFraction(reach[key])) &&
    [
      "qualified_artists",
      "total_artists",
      "qualified_tracks",
      "total_tracks",
      "qualified_plays",
      "total_plays",
      "unresolved_artists",
      "unresolved_tracks",
    ].every((key) => isCount(reach[key])) &&
    isUnitFraction(vocabulary.concentration) &&
    Array.isArray(vocabulary.families) &&
    vocabulary.families.length <= 50 &&
    vocabulary.families.every(
      (family) =>
        isRecord(family) &&
        typeof family.name === "string" &&
        isUnitFraction(family.share) &&
        isCount(family.supporting_artists) &&
        Array.isArray(family.instruments) &&
        family.instruments.length <= 100 &&
        (family.tone === null ||
          (isRecord(family.tone) &&
            typeof family.tone.shadow === "string" &&
            typeof family.tone.highlight === "string")) &&
        family.instruments.every(
          (instrument) =>
            isRecord(instrument) &&
            typeof instrument.name === "string" &&
            isFiniteNumber(instrument.distinct_recordings) &&
            isRecord(instrument.evidence) &&
            (instrument.evidence.scope === "recording" ||
              instrument.evidence.scope === "track"),
        ),
    ) &&
    Array.isArray(vocabulary.featured_artists) &&
    vocabulary.featured_artists.length <= 3 &&
    vocabulary.featured_artists.every(
      (artist) =>
        isRecord(artist) &&
        typeof artist.mbid === "string" &&
        typeof artist.name === "string" &&
        Array.isArray(artist.families) &&
        artist.families.every(
          (family) =>
            isRecord(family) &&
            typeof family.slug === "string" &&
            typeof family.name === "string" &&
            Array.isArray(family.instruments) &&
            family.instruments.every((name) => typeof name === "string") &&
            (family.tone === null ||
              (isRecord(family.tone) &&
                typeof family.tone.shadow === "string" &&
                typeof family.tone.highlight === "string")),
        ),
    ) &&
    Array.isArray(availableViews) &&
    availableViews.every(
      (view) => view === "track_palette" || view === "artist_vocabulary",
    ) &&
    (defaultView === null ||
      defaultView === "track_palette" ||
      defaultView === "artist_vocabulary") &&
    isRecord(hydration) &&
    (hydration.status === "complete" || hydration.status === "pending") &&
    isCount(hydration.pending_recordings, 50) &&
    isCount(hydration.pending_artists, 200) &&
    isCount(hydration.pending_aliases, 50)
  );
}
