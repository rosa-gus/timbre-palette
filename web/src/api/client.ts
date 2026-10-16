import { PaletteApiError } from "./errors";
import { isProfileAnalysisV3 } from "./report-validation";
export { PaletteApiError } from "./errors";
export { isProfileAnalysisV3 } from "./report-validation";
import { t } from "../i18n/runtime";
import type {
  InstrumentResource,
  ListeningPeriod,
  ProfileAnalysisV3,
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


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
    t("errors.analysisUnavailable"),
    status,
    "api_error",
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
      t("errors.network"),
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
      t("errors.invalidJson"),
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
): Promise<ProfileAnalysisV3> {
  const encodedUsername = encodeURIComponent(username);
  const result = await getJson<unknown>(
    `/v3/profiles/${encodedUsername}/analysis?period=${encodeURIComponent(period)}`,
    signal,
    analysisApiBaseUrl(),
  );
  if (!isProfileAnalysisV3(result.data)) {
    throw new PaletteApiError(
      t("errors.invalidReport"),
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
): Promise<ProfileAnalysisV3> {
  const params = new URLSearchParams({ period });
  if (sampleId) params.set("sample_id", sampleId);
  const result = await getJson<unknown>(
    `/v3/examples/analysis?${params.toString()}`,
    signal,
    analysisApiBaseUrl(),
  );
  if (!isProfileAnalysisV3(result.data) || !result.data.is_example) {
    throw new PaletteApiError(
      t("errors.invalidExampleReport"),
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
      t("errors.invalidInstrument"),
      result.response.status,
      "invalid_instrument",
    );
  }
  return sanitizeInstrumentResource(result.data);
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof PaletteApiError) {
    const localized: Record<string, string> = {
      network_error: t("errors.network"),
      invalid_json: t("errors.invalidJson"),
      invalid_report: t("errors.invalidReport"),
      invalid_example_report: t("errors.invalidExampleReport"),
      invalid_instrument: t("errors.invalidInstrument"),
      invalid_evidence: t("errors.invalidEvidence"),
      snapshot_changed: t("errors.snapshotChanged"),
      invalid_example_id: t("errors.invalidExampleId"),
      analysis_in_progress: t("errors.analysisInProgress"),
      lastfm_not_configured: t("errors.lastfmKeyMissing"),
      empty_listening_history: t("errors.emptyHistory"),
      invalid_request: t("errors.invalidUsernameOrPeriod"),
      invalid_browser_report: t("errors.invalidBrowserReport"),
      hydration_unavailable: t("errors.hydrationUnavailable"),
      invalid_snapshot_version: t("errors.invalidSnapshotVersion"),
      invalid_mbid_list: t("errors.invalidMbidList"),
      request_too_large: t("errors.requestTooLarge"),
      invalid_lastfm_response: t("errors.invalidLastfmResponse"),
      empty_history: t("errors.emptyHistory"),
      invalid_username: t("errors.invalidUsername"),
      invalid_username_or_period: t("errors.invalidUsernameOrPeriod"),
      invalid_page_or_limit: t("errors.invalidPageOrLimit"),
      lastfm_key_missing: t("errors.lastfmKeyMissing"),
      lastfm_unavailable: t("errors.lastfmUnavailable"),
      lastfm_profile_not_found: t("errors.lastfmProfileNotFound"),
      rate_limited: t("errors.rateLimited"),
      lastfm_busy: t("errors.lastfmBusy"),
      hydration_busy: t("errors.hydrationBusy"),
      hydration_daily_budget: t("errors.hydrationDailyBudget"),
      d1_busy: t("errors.d1Busy"),
      d1_daily_budget: t("errors.d1DailyBudget"),
      protection_unavailable: t("errors.protectionUnavailable"),
      lastfm_rate_limited: t("errors.lastfmRateLimited"),
      snapshot_unavailable: t("errors.snapshotUnavailable"),
      unsupported_snapshot_schema: t("errors.unsupportedSnapshotSchema"),
      database_unavailable: t("errors.databaseUnavailable"),
      example_data_unavailable: t("errors.exampleDataUnavailable"),
      catalog_unavailable: t("errors.catalogUnavailable"),
      instrument_not_found: t("errors.instrumentNotFound"),
      invalid_slug: t("errors.invalidSlug"),
    };
    return localized[error.code] ?? t("errors.analysisFailed");
  }
  if (error instanceof DOMException && error.name === "AbortError") return "";
  if (isRecord(error) && typeof error.message === "string") {
    return t("errors.analysisFailed");
  }
  return t("errors.analysisFailed");
}
