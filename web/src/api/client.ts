import type {
  InstrumentResource,
  ListeningPeriod,
  PaletteReport,
  ProfileSummary,
  ProfileAnalysisV2,
} from "./types";
import { storageKey } from "../storage";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8787"
).replace(/\/$/, "");

// v2 stats count the active snapshot projection; do not compare them with
// values cached under the former catalog semantics.
export const catalogStorageKey = storageKey("catalog", "last-seen", "v2");

export async function getCatalogSize(signal: AbortSignal): Promise<number> {
  const response = await fetch(`${API_BASE_URL}/v2/catalog/stats`, { signal });
  if (!response.ok) throw new Error("Catalog statistics unavailable");
  const value: unknown = await response.json();
  if (!isRecord(value) || !Number.isSafeInteger(value.recordings_with_evidence) ||
      typeof value.recordings_with_evidence !== "number" || value.recordings_with_evidence < 0) {
    throw new Error("Invalid catalog statistics");
  }
  return value.recordings_with_evidence;
}

export class PaletteApiError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(
    message: string,
    status: number,
    code: string,
  ) {
    super(message);
    this.name = "PaletteApiError";
    this.code = code;
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isOptionalText(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === "string";
}

function isProfileSummary(value: unknown): value is ProfileSummary {
  if (!isRecord(value)) return false;
  return (
    typeof value.username === "string" &&
    typeof value.period === "string" &&
    isFiniteNumber(value.tracks_analyzed) &&
    isFiniteNumber(value.total_plays) &&
    isOptionalText(value.profile_url) &&
    isOptionalText(value.avatar_url) &&
    isOptionalText(value.realname) &&
    isOptionalText(value.registered)
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

function parseApiError(value: unknown, status: number): PaletteApiError {
  if (isRecord(value) && typeof value.message === "string") {
    return new PaletteApiError(
      value.message,
      status,
      typeof value.code === "string" ? value.code : "api_error",
    );
  }
  return new PaletteApiError(
    "Não foi possível obter a análise.",
    status,
    "api_error",
  );
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
    (analysis.status === "partial" ||
      analysis.status === "ready" ||
      analysis.status === "insufficient") &&
    isFiniteNumber(analysis.coverage_tracks) &&
    isFiniteNumber(analysis.coverage_plays) &&
    isRecord(vocalPresence) &&
    isFiniteNumber(vocalPresence.documented_tracks) &&
    isFiniteNumber(vocalPresence.documented_artists) &&
    isFiniteNumber(vocalPresence.documented_plays) &&
    isFiniteNumber(vocalPresence.track_ratio) &&
    isFiniteNumber(vocalPresence.play_ratio) &&
    isRecord(availability) &&
    [
      "families",
      "sound_balance",
      "discovery",
      "temperament",
    ].every((key) => isAvailability(availability[key])) &&
    Array.isArray(families) &&
    families.every(
      (family) =>
        isRecord(family) &&
        typeof family.name === "string" &&
        isFiniteNumber(family.share),
    ) &&
    Array.isArray(recordings) &&
    recordings.every(
      (recording) =>
        isRecord(recording) &&
        typeof recording.title === "string" &&
        typeof recording.artist === "string",
    )
  );
}

function isProfileAnalysisV2(value: unknown): value is ProfileAnalysisV2 {
  if (!isRecord(value)) return false;
  const snapshot = value.snapshot;
  const hydration = value.hydration;
  const vocabulary = value.artist_vocabulary;
  const reach = isRecord(vocabulary) ? vocabulary.reach : null;
  const vocabularyAvailability = isRecord(vocabulary) ? vocabulary.availability : null;
  const availableViews = value.available_views;
  const defaultView = value.default_view;
  return (
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
    ["available", "pending", "insufficient"].includes(vocabulary.status as string) &&
    typeof vocabulary.notice === "string" &&
    typeof vocabulary.methodology_version === "string" &&
    isRecord(vocabularyAvailability) &&
    typeof vocabularyAvailability.reason === "string" &&
    isRecord(reach) &&
    ["track_reach", "play_reach", "qualified_artists", "total_artists",
      "qualified_tracks", "total_tracks", "qualified_plays", "total_plays",
      "unresolved_artists", "unresolved_tracks"].every((key) => isFiniteNumber(reach[key])) &&
    Array.isArray(vocabulary.families) &&
    vocabulary.families.every((family) => isRecord(family) &&
      typeof family.name === "string" && isFiniteNumber(family.share) &&
      isFiniteNumber(family.supporting_artists) && Array.isArray(family.instruments) &&
      (family.tone === null || (isRecord(family.tone) &&
        typeof family.tone.shadow === "string" &&
        typeof family.tone.highlight === "string")) &&
      family.instruments.every((instrument) => isRecord(instrument) &&
        typeof instrument.name === "string" &&
        isFiniteNumber(instrument.distinct_recordings) &&
        isRecord(instrument.evidence) &&
        (instrument.evidence.scope === "recording" || instrument.evidence.scope === "track"))) &&
    Array.isArray(vocabulary.featured_artists) &&
    vocabulary.featured_artists.length <= 3 &&
    vocabulary.featured_artists.every((artist) => isRecord(artist) &&
      typeof artist.mbid === "string" && typeof artist.name === "string" &&
      Array.isArray(artist.families) && artist.families.every((family) =>
        isRecord(family) && typeof family.slug === "string" &&
        typeof family.name === "string" && Array.isArray(family.instruments) &&
        family.instruments.every((name) => typeof name === "string") &&
        (family.tone === null || (isRecord(family.tone) &&
          typeof family.tone.shadow === "string" &&
          typeof family.tone.highlight === "string")))) &&
    Array.isArray(availableViews) &&
    availableViews.every((view) =>
      view === "track_palette" || view === "artist_vocabulary",
    ) &&
    (defaultView === null ||
      defaultView === "track_palette" ||
      defaultView === "artist_vocabulary") &&
    isRecord(hydration) &&
    (hydration.status === "complete" || hydration.status === "pending") &&
    [
      "pending_recordings",
      "pending_artists",
      "pending_aliases",
    ].every((key) => isFiniteNumber(hydration[key]))
  );
}

function isInstrumentResource(value: unknown): value is InstrumentResource {
  return (
    isRecord(value) &&
    typeof value.slug === "string" &&
    typeof value.name === "string" &&
    typeof value.description === "string" &&
    typeof value.sound_production === "string" &&
    Array.isArray(value.common_roles) &&
    Array.isArray(value.related_slugs) &&
    Array.isArray(value.sections) &&
    Array.isArray(value.sources)
  );
}

async function getJson<T>(
  path: string,
  signal: AbortSignal,
): Promise<{ data: T; response: Response }> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new PaletteApiError(
      "Não foi possível conectar à API da paleta.",
      0,
      "network_error",
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new PaletteApiError(
      "A API devolveu uma resposta inválida.",
      response.status,
      "invalid_json",
    );
  }

  if (!response.ok) {
    const problem = parseApiError(payload, response.status);
    throw new PaletteApiError(
      problem.message,
      problem.status,
      problem.code,
    );
  }

  return { data: payload as T, response };
}

export function normalizeUsername(value: string): string {
  const input = value.trim();
  try {
    const url = new URL(input);
    const parts = url.pathname.split("/").filter(Boolean);
    const userIndex = parts.findIndex((part) => part.toLowerCase() === "user");
    if (userIndex >= 0 && parts[userIndex + 1])
      return decodeURIComponent(parts[userIndex + 1]);
  } catch {
    // The input is a username rather than a URL.
  }
  return input.replace(/^@+/, "").replace(/\s+/g, "");
}

export async function getAnalysis(
  username: string,
  period: ListeningPeriod,
  signal: AbortSignal,
): Promise<ProfileAnalysisV2> {
  const encodedUsername = encodeURIComponent(username);
  const result = await getJson<unknown>(
    `/v2/profiles/${encodedUsername}/analysis?period=${encodeURIComponent(period)}`,
    signal,
  );
  if (!isProfileAnalysisV2(result.data)) {
    throw new PaletteApiError(
      "A API devolveu uma análise incompatível com o contrato.",
      result.response.status,
      "invalid_report",
    );
  }
  return result.data;
}

export async function getExampleAnalysis(
  period: ListeningPeriod,
  signal: AbortSignal,
  sampleId?: string,
): Promise<ProfileAnalysisV2> {
  const params = new URLSearchParams({ period });
  if (sampleId) params.set("sample_id", sampleId);
  const result = await getJson<unknown>(
    `/v2/examples/analysis?${params.toString()}`,
    signal,
  );
  if (!isProfileAnalysisV2(result.data) || !result.data.is_example) {
    throw new PaletteApiError(
      "A API devolveu uma análise de exemplo incompatível com o contrato.",
      result.response.status,
      "invalid_example_report",
    );
  }
  return result.data;
}

export async function getInstrument(
  slug: string,
  signal: AbortSignal,
): Promise<InstrumentResource> {
  const result = await getJson<InstrumentResource>(
    `/v2/instruments/${encodeURIComponent(slug)}`,
    signal,
  );
  if (!isInstrumentResource(result.data)) {
    throw new PaletteApiError(
      "A API devolveu uma ficha incompatível com o contrato.",
      result.response.status,
      "invalid_instrument",
    );
  }
  return result.data;
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof PaletteApiError) return error.message;
  if (error instanceof DOMException && error.name === "AbortError") return "";
  if (isRecord(error) && typeof error.message === "string") {
    return error.message;
  }
  return "Não foi possível concluir a análise.";
}

export function apiBaseUrl(): string {
  return API_BASE_URL;
}
