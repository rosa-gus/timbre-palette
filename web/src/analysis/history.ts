import { STORAGE_KEYS } from "../utils/storage-keys";
import type { ListeningPeriod } from "../api/types";
import { PaletteApiError } from "../api/client";
import { boundedText, safeExternalUrl, safeLastFmAvatarUrl, safeLastFmProfileUrl } from "../api/input-validation";

export interface HistoryTrack {
  title: string;
  artist: string;
  play_count: number;
  mbid: string | null;
  artist_mbid: string | null;
  release_mbid: string | null;
  lastfm_url: string | null;
}
export interface HistoryPage {
  username: string;
  tracks: HistoryTrack[];
  totalPages: number | null;
}
export interface HistoryMetadata {
  username: string;
  profile_url: string | null;
  avatar_url: string | null;
  realname: string | null;
  registered: string | null;
}
interface Checkpoint {
  version: 1;
  id: string;
  baseUrl: string;
  username: string;
  period: ListeningPeriod;
  startedAt: number;
  pageCount: number;
  pages: HistoryPage[];
  metadata: HistoryMetadata | null;
  retryAt: number;
  retryCode: string;
}
export interface HistoryResume {
  username: string;
  period: ListeningPeriod;
  pages: number;
  totalPages: number;
  tracks: number;
  expiresAt: number;
  retryAt: number;
}

export const HISTORY_TTL_MS = 10 * 60_000;
const MAX_STORAGE_LENGTH = 1_000_000;
const PERIODS = new Set(["7day", "1month", "3month", "6month", "12month", "overall"]);
const MBID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let current: Checkpoint | null | undefined;
let active: { id: string; signal: AbortSignal } | null = null;

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const integer = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const identity = (value: string) => value.trim().toLowerCase();
const uuid = (value: unknown) => value === null || (typeof value === "string" && MBID.test(value));

function restore(value: unknown): Checkpoint | null {
  if (!record(value) || value.version !== 1 || !boundedText(value.id, 64) || !boundedText(value.baseUrl, 2048) ||
      !boundedText(value.username, 64) || typeof value.period !== "string" || !PERIODS.has(value.period) ||
      !integer(value.startedAt) || value.startedAt > Date.now() || !integer(value.retryAt) ||
      value.retryAt > Date.now() + 86_400_000 || typeof value.retryCode !== "string" || value.retryCode.length > 64 ||
      !integer(value.pageCount) || value.pageCount < 1 || value.pageCount > 4 || !Array.isArray(value.pages) ||
      value.pages.length > value.pageCount) return null;
  const pages: HistoryPage[] = [];
  for (const page of value.pages) {
    if (!record(page) || !boundedText(page.username, 64) || !Array.isArray(page.tracks) || page.tracks.length > 50 ||
        (page.totalPages !== null && (!integer(page.totalPages) || page.totalPages < 1))) return null;
    const tracks: HistoryTrack[] = [];
    for (const track of page.tracks) {
      if (!record(track) || !boundedText(track.title, 512) || !boundedText(track.artist, 256) ||
          !integer(track.play_count) || !uuid(track.mbid) || !uuid(track.artist_mbid) || !uuid(track.release_mbid)) return null;
      tracks.push({
        title: String(track.title), artist: String(track.artist), play_count: track.play_count,
        mbid: track.mbid as string | null, artist_mbid: track.artist_mbid as string | null,
        release_mbid: track.release_mbid as string | null, lastfm_url: safeExternalUrl(track.lastfm_url),
      });
    }
    pages.push({ username: String(page.username), tracks, totalPages: page.totalPages as number | null });
  }
  let metadata: HistoryMetadata | null = null;
  if (record(value.metadata) && boundedText(value.metadata.username, 64)) {
    const name = String(value.metadata.username);
    metadata = {
      username: name, profile_url: safeLastFmProfileUrl(value.metadata.profile_url, name),
      avatar_url: safeLastFmAvatarUrl(value.metadata.avatar_url), realname: boundedText(value.metadata.realname, 256),
      registered: boundedText(value.metadata.registered, 64),
    };
  }
  return { version: 1, id: String(value.id), baseUrl: String(value.baseUrl), username: String(value.username),
    period: value.period as ListeningPeriod, startedAt: value.startedAt, pageCount: value.pageCount, pages, metadata,
    retryAt: value.retryAt, retryCode: value.retryCode };
}

function persist(): void {
  try {
    if (typeof window === "undefined") return;
    if (!current) window.sessionStorage.removeItem(STORAGE_KEYS.historyProgress);
    else {
      const serialized = JSON.stringify(current);
      if (serialized.length <= MAX_STORAGE_LENGTH) window.sessionStorage.setItem(STORAGE_KEYS.historyProgress, serialized);
      else window.sessionStorage.removeItem(STORAGE_KEYS.historyProgress);
    }
  } catch { /* Storage is optional; the in-memory checkpoint remains usable. */ }
}

function checkpoint(): Checkpoint | null {
  if (current === undefined) {
    current = null;
    try {
      const stored = typeof window === "undefined" ? null : window.sessionStorage.getItem(STORAGE_KEYS.historyProgress);
      if (stored && stored.length <= MAX_STORAGE_LENGTH) current = restore(JSON.parse(stored));
      if (stored && !current) persist();
    } catch { /* Invalid or unavailable storage never blocks a fresh request. */ }
  }
  if (current && active?.id !== current.id && Date.now() >= current.startedAt + HISTORY_TTL_MS) {
    // Expire pages together; retain a server-requested cooldown independently.
    if (current.retryAt > Date.now()) {
      if (!current.pages.length && !current.metadata) return current;
      current.pages = [];
      current.metadata = null;
    } else current = null;
    persist();
  }
  return current;
}

export function getHistoryResume(baseUrl: string): HistoryResume | null {
  const saved = checkpoint();
  if (!saved || saved.baseUrl !== baseUrl) return null;
  return { username: saved.username, period: saved.period, pages: saved.pages.length, totalPages: saved.pageCount,
    tracks: saved.pages.reduce((sum, page) => sum + page.tracks.length, 0),
    expiresAt: saved.startedAt + HISTORY_TTL_MS, retryAt: saved.retryAt };
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); signal.removeEventListener("abort", abort); reject(signal.reason); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}

export async function loadHistory(
  baseUrl: string, username: string, period: ListeningPeriod, signal: AbortSignal,
  fetchPage: (page: number) => Promise<HistoryPage>,
  fetchMetadata: (username: string) => Promise<HistoryMetadata>,
  onProgress: (current: number, total: number) => void,
  resume = false,
): Promise<{ id: string; pages: HistoryPage[]; metadata: HistoryMetadata | null; username: string }> {
  signal.throwIfAborted();
  const saved = checkpoint();
  const matches = saved && saved.baseUrl === baseUrl && identity(saved.username) === identity(username) && saved.period === period;
  if (saved?.baseUrl === baseUrl && saved.retryAt > Date.now()) {
    throw new PaletteApiError("Aguarde antes de retomar a consulta.", 503, saved.retryCode,
      Math.ceil((saved.retryAt - Date.now()) / 1000));
  }
  if (active && !active.signal.aborted) throw new PaletteApiError("Uma consulta já está em andamento.", 409, "analysis_in_progress");
  const state: Checkpoint = resume && matches && saved.pages.length && Date.now() < saved.startedAt + HISTORY_TTL_MS
    ? { ...saved, id: crypto.randomUUID(), pages: [...saved.pages] } : { version: 1, id: crypto.randomUUID(), baseUrl, username, period, startedAt: Date.now(), pageCount: 1,
      pages: [], metadata: null, retryAt: 0, retryCode: "lastfm_busy" };
  current = state;
  const run = { id: state.id, signal };
  active = run;
  state.retryAt = 0;
  persist();
  let metadataPromise: Promise<HistoryMetadata | null> | null = null;
  const startMetadata = () => {
    if (metadataPromise) return;
    metadataPromise = state.metadata ? Promise.resolve(state.metadata)
      : fetchMetadata(state.pages[0].username).then((metadata) => {
          if (!signal.aborted && current?.id === state.id) { state.metadata = metadata; persist(); }
          return metadata;
        }).catch(() => null);
  };
  try {
    if (state.pages.length) { onProgress(state.pages.length, state.pageCount); startMetadata(); }
    for (let page = state.pages.length + 1; page <= state.pageCount; page++) {
      onProgress(page - 1, state.pageCount);
      let result: HistoryPage;
      for (let attempt = 0; ; attempt++) {
        try { result = await fetchPage(page); break; }
        catch (error) {
          if (signal.aborted) throw signal.reason;
          const transient = error instanceof PaletteApiError && !error.retryAfter &&
            (error.code === "network_error" || error.code === "lastfm_unavailable");
          if (!transient || attempt >= 1) throw error;
          await wait(1000, signal); // One bounded retry; overload/cooldowns require manual resumption.
        }
      }
      signal.throwIfAborted();
      if (page === 1) {
        if (!result.tracks.length) throw new PaletteApiError("Não foram encontradas faixas nesse período.", 422, "empty_history");
        state.pageCount = Math.min(4, Math.max(1, result.totalPages ?? (result.tracks.length === 50 ? 4 : 1)));
      }
      // Cache only normalized fields, never upstream extras or derived evidence.
      state.pages.push({ username: result.username, totalPages: result.totalPages, tracks: result.tracks.map((track) => ({
        title: track.title, artist: track.artist, play_count: track.play_count, mbid: track.mbid,
        artist_mbid: track.artist_mbid, release_mbid: track.release_mbid, lastfm_url: track.lastfm_url,
      })) });
      persist();
      startMetadata();
      onProgress(page, state.pageCount);
    }
    const metadata = await metadataPromise;
    signal.throwIfAborted();
    return { id: state.id, pages: state.pages, metadata, username: state.pages[0].username };
  } catch (error) {
    if (error instanceof PaletteApiError && error.retryAfter && !signal.aborted) {
      state.retryAt = Date.now() + Math.min(error.retryAfter, 86_400) * 1000;
      state.retryCode = error.code;
    }
    if (error instanceof PaletteApiError && ["lastfm_profile_not_found", "empty_history", "invalid_username", "invalid_username_or_period"].includes(error.code)) {
      if (current?.id === state.id) current = null;
    }
    persist();
    throw error;
  } finally { if (active === run) active = null; }
}

export function finishHistory(id: string): void {
  if (current?.id === id) { current = null; persist(); }
}

export function recordHistoryFailure(id: string, error: unknown): void {
  if (current?.id === id && error instanceof PaletteApiError && error.retryAfter) {
    current.retryAt = Date.now() + Math.min(error.retryAfter, 86_400) * 1000;
    current.retryCode = error.code;
    persist();
  }
}
