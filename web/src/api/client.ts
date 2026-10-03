import type {
  InstrumentResource,
  ListeningPeriod,
  PaletteReport,
  ProfileSummary,
  ProfileAnalysisV2,
} from "./types";
import { retryAfterSeconds } from "./retry-after";
import {
  boundedText,
  readBoundedJson,
  sanitizeInstrumentResource,
  sanitizeProfileAnalysis,
} from "./input-validation";
import {
  analysisApiBaseUrl as configuredAnalysisApiBaseUrl,
  apiBaseUrl as configuredApiBaseUrl,
  loadRuntimeConfig,
} from "./runtime-config";

export { loadRuntimeConfig };

export function apiBaseUrl(): string { return configuredApiBaseUrl(); }
function analysisApiBaseUrl(): string { return configuredAnalysisApiBaseUrl(); }

export async function getCatalogSize(signal: AbortSignal): Promise<number> {
  const response = await fetch(`${apiBaseUrl()}/v2/catalog/stats`, { signal });
  if (!response.ok) throw new Error("Catalog statistics unavailable");
  const value: unknown = await readBoundedJson(response);
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
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = "PaletteApiError";
    this.code = code;
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isCount(value: unknown, max = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= max;
}

function isUnitFraction(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0 && value <= 1;
}

function isOptionalText(value: unknown, maxLength = 512): value is string | null | undefined {
  return value === undefined || value === null ||
    (typeof value === "string" && value.length <= maxLength && !value.includes("\u0000"));
}

function isProfileSummary(value: unknown): value is ProfileSummary {
  if (!isRecord(value)) return false;
  return (
    boundedText(value.username, 64) !== null &&
    ["overall", "7day", "1month", "3month", "6month", "12month"].includes(value.period as string) &&
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

function parseApiError(value: unknown, status: number): PaletteApiError {
  if (isRecord(value) && typeof value.message === "string") {
    return new PaletteApiError(
      value.message,
      status,
      typeof value.code === "string" ? value.code
        : typeof value.error === "string" ? value.error : "api_error",
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
    isUnitFraction(analysis.coverage_tracks) &&
    isUnitFraction(analysis.coverage_plays) &&
    isRecord(vocalPresence) &&
    isFiniteNumber(vocalPresence.documented_tracks) &&
    isFiniteNumber(vocalPresence.documented_artists) &&
    isFiniteNumber(vocalPresence.documented_plays) &&
    isUnitFraction(vocalPresence.track_ratio) &&
    isUnitFraction(vocalPresence.play_ratio) &&
    isRecord(availability) &&
    [
      "families",
      "sound_balance",
      "discovery",
      "temperament",
    ].every((key) => isAvailability(availability[key])) &&
    Array.isArray(families) && families.length <= 50 &&
    families.every(
      (family) =>
        isRecord(family) &&
        boundedText(family.name, 256) !== null &&
        isUnitFraction(family.share),
    ) &&
    Array.isArray(recordings) && recordings.length <= 200 &&
    recordings.every(
      (recording) =>
        isRecord(recording) &&
        boundedText(recording.title, 512) !== null &&
        boundedText(recording.artist, 256) !== null,
    )
  );
}

export function isProfileAnalysisV2(value: unknown): value is ProfileAnalysisV2 {
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
    ["track_reach", "play_reach"].every((key) => isUnitFraction(reach[key])) &&
    ["qualified_artists", "total_artists", "qualified_tracks", "total_tracks",
      "qualified_plays", "total_plays", "unresolved_artists", "unresolved_tracks"]
      .every((key) => isCount(reach[key])) &&
    isUnitFraction(vocabulary.concentration) &&
    Array.isArray(vocabulary.families) && vocabulary.families.length <= 50 &&
    vocabulary.families.every((family) => isRecord(family) &&
      typeof family.name === "string" && isUnitFraction(family.share) &&
      isCount(family.supporting_artists) && Array.isArray(family.instruments) &&
      family.instruments.length <= 100 &&
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
    isCount(hydration.pending_recordings, 50) &&
    isCount(hydration.pending_artists, 200) &&
    isCount(hydration.pending_aliases, 50)
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
    value.common_roles.every((role) => typeof role === "string") &&
    Array.isArray(value.related_slugs) &&
    value.related_slugs.every((slug) => typeof slug === "string") &&
    Array.isArray(value.sections) &&
    value.sections.every((section) => isRecord(section) &&
      typeof section.text === "string" && typeof section.status === "string" &&
      isRecord(section.review) &&
      typeof section.review.claim_support_verified === "boolean" &&
      typeof section.review.source_metadata_verified === "boolean" &&
      Array.isArray(section.citations) &&
      section.citations.every((citation) => isRecord(citation) &&
        typeof citation.source_id === "string")) &&
    Array.isArray(value.sources) &&
    value.sources.every((source) => isRecord(source) &&
      typeof source.id === "string" && typeof source.title === "string" &&
      typeof source.source_type === "string" &&
      typeof source.language === "string" &&
      /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(source.language) &&
      Array.isArray(source.contributors) &&
      source.contributors.every((contributor) => typeof contributor === "string")) &&
    (value.further_reading === undefined || (Array.isArray(value.further_reading) &&
      value.further_reading.every((article) => isRecord(article) &&
        typeof article.title === "string" && typeof article.url === "string")))
  );
}

async function getJson<T>(
  path: string,
  signal: AbortSignal,
  baseUrl = apiBaseUrl(),
): Promise<{ data: T; response: Response }> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
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
    payload = await readBoundedJson(response);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
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
      retryAfterSeconds(response),
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
    analysisApiBaseUrl(),
  );
  if (!isProfileAnalysisV2(result.data)) {
    throw new PaletteApiError(
      "A API devolveu uma análise incompatível com o contrato.",
      result.response.status,
      "invalid_report",
    );
  }
  return sanitizeProfileAnalysis(result.data);
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
    analysisApiBaseUrl(),
  );
  if (!isProfileAnalysisV2(result.data) || !result.data.is_example) {
    throw new PaletteApiError(
      "A API devolveu uma análise de exemplo incompatível com o contrato.",
      result.response.status,
      "invalid_example_report",
    );
  }
  return sanitizeProfileAnalysis(result.data);
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
  return sanitizeInstrumentResource(result.data);
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof PaletteApiError) {
    const localized: Record<string, string> = {
      invalid_username: "Informe um perfil válido do Last.fm.",
      invalid_username_or_period: "O perfil ou período informado é inválido.",
      invalid_page_or_limit: "A página solicitada é inválida.",
      lastfm_key_missing: "A consulta do histórico não está configurada.",
      lastfm_unavailable: "Não foi possível consultar o Last.fm agora.",
      lastfm_profile_not_found: "Esse perfil não foi encontrado no Last.fm.",
      rate_limited: "Você fez muitas consultas. Aguarde um minuto antes de tentar novamente.",
      lastfm_busy: "As consultas de histórico estão no limite agora. Aguarde um pouco e tente novamente.",
      hydration_busy: "O registro de novas evidências está pausado temporariamente.",
      hydration_daily_budget: "O limite diário de novas evidências foi atingido.",
      d1_daily_budget: "O limite diário de consultas ao catálogo foi atingido. Tente novamente mais tarde.",
      protection_unavailable: "O serviço de análise está temporariamente indisponível. Tente novamente em instantes.",
      lastfm_rate_limited: "O Last.fm está recebendo muitas consultas. Tente novamente em instantes.",
      snapshot_unavailable: "O catálogo de créditos está indisponível agora.",
      unsupported_snapshot_schema: "A versão do catálogo não é compatível com esta análise.",
      database_unavailable: "O catálogo de evidências está indisponível.",
      example_data_unavailable: "O exemplo do catálogo não está disponível.",
      catalog_unavailable: "O catálogo está indisponível no momento.",
      instrument_not_found: "Esse instrumento não foi encontrado no catálogo.",
      invalid_slug: "O identificador do instrumento é inválido.",
    };
    return localized[error.code] ?? error.message;
  }
  if (error instanceof DOMException && error.name === "AbortError") return "";
  if (isRecord(error) && typeof error.message === "string") {
    return error.message;
  }
  return "Não foi possível concluir a análise.";
}
