import type {
  InstrumentResource,
  ListeningPeriod,
  PaletteReport,
} from "./types";
import { storageKey } from "../storage";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8787"
).replace(/\/$/, "");

export const catalogStorageKey = storageKey("catalog", "last-seen");

export async function getCatalogSize(signal: AbortSignal): Promise<number> {
  const response = await fetch(`${API_BASE_URL}/v1/catalog/stats`, { signal });
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
    isRecord(profile) &&
    typeof profile.username === "string" &&
    typeof profile.period === "string" &&
    isFiniteNumber(profile.tracks_analyzed) &&
    isFiniteNumber(profile.total_plays) &&
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

export async function getPalette(
  username: string,
  period: ListeningPeriod,
  signal: AbortSignal,
): Promise<PaletteReport> {
  const encodedUsername = encodeURIComponent(username);
  const result = await getJson<unknown>(
    `/v1/profiles/${encodedUsername}/palette?period=${encodeURIComponent(period)}`,
    signal,
  );
  if (!isPaletteReport(result.data)) {
    throw new PaletteApiError(
      "A API devolveu uma paleta incompatível com o contrato.",
      result.response.status,
      "invalid_report",
    );
  }
  return result.data;
}

export async function getInstrument(
  slug: string,
  signal: AbortSignal,
): Promise<InstrumentResource> {
  const result = await getJson<InstrumentResource>(
    `/v1/instruments/${encodeURIComponent(slug)}`,
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
