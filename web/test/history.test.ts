import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
let PaletteApiError: typeof import("../src/api/client").PaletteApiError;
import { STORAGE_KEYS } from "../src/utils/storage-keys";
import type { HistoryPage } from "../src/analysis/history";

class MemoryStorage {
  private items = new Map<string, string>();
  get length() { return this.items.size; }
  key(index: number) { return [...this.items.keys()][index] ?? null; }
  getItem(key: string) { return this.items.get(key) ?? null; }
  setItem(key: string, value: string) { this.items.set(key, value); }
  removeItem(key: string) { this.items.delete(key); }
}
const base = "https://api.test";
const page = (number: number): HistoryPage => ({ username: "Alice", totalPages: 4,
  tracks: Array.from({ length: 50 }, (_, index) => ({ title: `Track ${number}-${index}`, artist: "Artist",
    play_count: 1, mbid: null, artist_mbid: null, release_mbid: null, lastfm_url: null })) });
const metadata = { username: "Alice", profile_url: null, avatar_url: null, realname: null, registered: null };
let storage: MemoryStorage;
beforeEach(async () => {
  vi.resetModules();
  ({ PaletteApiError } = await import("../src/api/client"));
  storage = new MemoryStorage();
  vi.stubGlobal("window", { sessionStorage: storage, localStorage: new MemoryStorage() });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("local history resumption", () => {
  it("survives reload, reuses metadata and requests only missing pages", async () => {
    let history = await import("../src/analysis/history");
    const fetchPage = vi.fn(async (number: number) => {
      if (number === 3) throw new PaletteApiError("busy", 503, "lastfm_busy");
      return page(number);
    });
    const fetchMetadata = vi.fn(async () => metadata);
    await expect(history.loadHistory(base, "alice", "1month", new AbortController().signal,
      fetchPage, fetchMetadata, vi.fn())).rejects.toMatchObject({ code: "lastfm_busy" });
    expect(fetchPage.mock.calls.map(([number]) => number)).toEqual([1, 2, 3]);
    expect(history.getHistoryResume(base)).toMatchObject({ pages: 2, tracks: 100, totalPages: 4 });
    vi.resetModules(); // Same sessionStorage, new module instance, as after reloading the tab.
    history = await import("../src/analysis/history");
    const remaining = vi.fn(async (number: number) => page(number));
    const result = await history.loadHistory(base, "ALICE", "1month", new AbortController().signal,
      remaining, fetchMetadata, vi.fn(), true);
    expect(remaining.mock.calls.map(([number]) => number)).toEqual([3, 4]);
    expect(fetchMetadata).toHaveBeenCalledTimes(1);
    expect(result.pages.flatMap((value) => value.tracks)).toHaveLength(200);
    history.finishHistory(result.id);
    expect(storage.getItem(STORAGE_KEYS.historyProgress)).toBeNull();
  });

  it("honors cooldown across reload and profile/period changes, including restart", async () => {
    vi.useFakeTimers();
    let history = await import("../src/analysis/history");
    const busy = vi.fn(async (number: number) => {
      if (number === 2) throw new PaletteApiError("busy", 503, "lastfm_busy", 60);
      return page(number);
    });
    await expect(history.loadHistory(base, "alice", "1month", new AbortController().signal,
      busy, async () => metadata, vi.fn())).rejects.toMatchObject({ retryAfter: 60 });
    vi.resetModules();
    history = await import("../src/analysis/history");
    const fetchPage = vi.fn(async (number: number) => page(number));
    for (const resume of [false, true]) {
      await expect(history.loadHistory(base, "bob", "7day", new AbortController().signal,
        fetchPage, async () => metadata, vi.fn(), resume)).rejects.toMatchObject({ retryAfter: 60 });
    }
    expect(fetchPage).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(60_000);
    await history.loadHistory(base, "alice", "1month", new AbortController().signal,
      fetchPage, async () => metadata, vi.fn(), true);
    expect(fetchPage.mock.calls.map(([number]) => number)).toEqual([2, 3, 4]);
  });

  it("retries a transient page once and leaves its checkpoint after exhaustion", async () => {
    vi.useFakeTimers();
    const history = await import("../src/analysis/history");
    const fetchPage = vi.fn(async (number: number) => {
      if (number === 2) throw new PaletteApiError("unavailable", 502, "lastfm_unavailable");
      return page(number);
    });
    const attempt = history.loadHistory(base, "alice", "1month", new AbortController().signal,
      fetchPage, async () => metadata, vi.fn());
    const failed = expect(attempt).rejects.toMatchObject({ code: "lastfm_unavailable" });
    await vi.advanceTimersByTimeAsync(1000);
    await failed;
    expect(fetchPage.mock.calls.map(([number]) => number)).toEqual([1, 2, 2]);
    expect(history.getHistoryResume(base)?.pages).toBe(1);
  });

  it.each(["restart", "expired", "other user", "other period", "other API"])("starts fresh for %s", async (reason) => {
    vi.useFakeTimers();
    const history = await import("../src/analysis/history");
    await expect(history.loadHistory(base, "alice", "1month", new AbortController().signal,
      async (number) => { if (number === 2) throw new PaletteApiError("busy", 503, "lastfm_busy"); return page(number); },
      async () => metadata, vi.fn())).rejects.toThrow();
    if (reason === "expired") await vi.advanceTimersByTimeAsync(history.HISTORY_TTL_MS);
    const fresh = vi.fn(async (number: number) => page(number));
    await history.loadHistory(reason === "other API" ? `${base}/other` : base,
      reason === "other user" ? "bob" : "alice", reason === "other period" ? "7day" : "1month",
      new AbortController().signal, fresh, async () => metadata, vi.fn(), reason !== "restart");
    expect(fresh.mock.calls.map(([number]) => number)).toEqual([1, 2, 3, 4]);
  });

  it("expires cached pages without bypassing a longer cooldown", async () => {
    vi.useFakeTimers();
    const history = await import("../src/analysis/history");
    await expect(history.loadHistory(base, "alice", "1month", new AbortController().signal,
      async (number) => { if (number === 2) throw new PaletteApiError("busy", 503, "lastfm_busy", 3600); return page(number); },
      async () => metadata, vi.fn())).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(history.HISTORY_TTL_MS);
    expect(history.getHistoryResume(base)).toMatchObject({ pages: 0, tracks: 0 });
    const fetchPage = vi.fn();
    await expect(history.loadHistory(base, "alice", "1month", new AbortController().signal,
      fetchPage, async () => metadata, vi.fn(), true)).rejects.toMatchObject({ retryAfter: 3000 });
    expect(fetchPage).not.toHaveBeenCalled();
  });

  it("retains all pages when evidence fails and clears only the completed attempt", async () => {
    vi.useFakeTimers();
    const history = await import("../src/analysis/history");
    const first = await history.loadHistory(base, "alice", "1month", new AbortController().signal,
      async (number) => page(number), async () => metadata, vi.fn());
    history.recordHistoryFailure(first.id, new PaletteApiError("busy", 503, "d1_busy", 5));
    expect(history.getHistoryResume(base)).toMatchObject({ pages: 4, tracks: 200 });
    const fetchPage = vi.fn();
    await expect(history.loadHistory(base, "alice", "1month", new AbortController().signal,
      fetchPage, async () => metadata, vi.fn(), true)).rejects.toMatchObject({ code: "d1_busy", retryAfter: 5 });
    expect(fetchPage).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(5000);
    const second = await history.loadHistory(base, "alice", "1month", new AbortController().signal,
      fetchPage, async () => metadata, vi.fn(), true);
    expect(fetchPage).not.toHaveBeenCalled();
    history.finishHistory(first.id);
    expect(history.getHistoryResume(base)?.pages).toBe(4);
    history.finishHistory(second.id);
    expect(history.getHistoryResume(base)).toBeNull();
  });

  it("keeps the memory checkpoint when sessionStorage is unavailable", async () => {
    vi.stubGlobal("window", { get sessionStorage() { throw new Error("blocked"); } });
    const history = await import("../src/analysis/history");
    await expect(history.loadHistory(base, "alice", "1month", new AbortController().signal,
      async (number) => { if (number === 2) throw new PaletteApiError("busy", 503, "lastfm_busy"); return page(number); },
      async () => metadata, vi.fn())).rejects.toThrow();
    expect(history.getHistoryResume(base)?.tracks).toBe(50);
  });

  it("ignores malformed persisted data", async () => {
    storage.setItem(STORAGE_KEYS.historyProgress, JSON.stringify({ version: 1, pages: [{ tracks: "invalid" }] }));
    const history = await import("../src/analysis/history");
    expect(history.getHistoryResume(base)).toBeNull();
    expect(storage.getItem(STORAGE_KEYS.historyProgress)).toBeNull();
  });

  it("preserves completed pages on cancellation and allows a new attempt before the old one settles", async () => {
    const history = await import("../src/analysis/history");
    const controller = new AbortController();
    let release!: (value: HistoryPage) => void;
    let reached!: () => void;
    const pending = new Promise<void>((resolve) => { reached = resolve; });
    const old = history.loadHistory(base, "alice", "1month", controller.signal,
      async (number) => {
        if (number !== 2) return page(number);
        reached();
        return new Promise<HistoryPage>((resolve) => { release = resolve; });
      }, async () => metadata, vi.fn());
    const cancelled = expect(old).rejects.toMatchObject({ name: "AbortError" });
    await pending;
    controller.abort();
    expect(history.getHistoryResume(base)?.pages).toBe(1);
    const remaining = vi.fn(async (number: number) => page(number));
    const resumed = await history.loadHistory(base, "alice", "1month", new AbortController().signal,
      remaining, async () => metadata, vi.fn(), true);
    release(page(2));
    await cancelled;
    expect(remaining.mock.calls.map(([number]) => number)).toEqual([2, 3, 4]);
    expect(history.getHistoryResume(base)?.pages).toBe(4);
    history.finishHistory(resumed.id);
    expect(history.getHistoryResume(base)).toBeNull();
  });
});
