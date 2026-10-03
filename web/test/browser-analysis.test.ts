import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../src/api/runtime-config", () => ({
  apiBaseUrl: () => "https://api.test",
  analysisApiBaseUrl: () => "https://api.test",
  loadRuntimeConfig: async () => undefined,
}));

const mbid = (number: number) => `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`;
const snapshot = (version: string) => ({ snapshot_version: version,
  index_schema_version: "musicbrainz-instrument-credits-serving-v2", manifest_hash: "a".repeat(64) });
const evidence = (version: string) => Response.json({ snapshot: snapshot(version), aliases: [],
  recording_statuses: [], recording_claims: [], artist_statuses: [], artist_vocabulary: [] });
let historyCalls: number[];
let metadataCalls: number;
let evidenceBodies: { snapshot_version?: string }[];
let hydrationCalls: number;

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  historyCalls = [];
  metadataCalls = 0;
  evidenceBodies = [];
  hydrationCalls = 0;
  const items = new Map<string, string>();
  vi.stubGlobal("window", { location: { href: "https://web.test/" }, sessionStorage: {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => items.set(key, value), removeItem: (key: string) => items.delete(key),
  } });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

function mockApi(options: { failPage?: boolean; failEvidence?: boolean }) {
  vi.stubGlobal("fetch", vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    if (url.pathname.endsWith("/tracks")) {
      const page = Number(url.searchParams.get("page"));
      historyCalls.push(page);
      if (options.failPage && page === 3 && historyCalls.filter((value) => value === 3).length === 1) {
        return Response.json({ error: "lastfm_busy" }, { status: 503, headers: { "Retry-After": "10" } });
      }
      return Response.json({ toptracks: { "@attr": { user: "alice", totalPages: "4" },
        track: Array.from({ length: 50 }, (_, index) => ({ name: `Track ${page}-${index}`,
          artist: { name: "Artist", mbid: mbid(page + 10) }, playcount: "2", mbid: index === 0 ? mbid(page) : "" })) } });
    }
    if (url.pathname.endsWith("/metadata")) {
      metadataCalls++;
      return Response.json({ username: "alice", profile: { realname: "Alice" } });
    }
    if (url.pathname === "/v3/evidence") {
      evidenceBodies.push(JSON.parse(String(init?.body)));
      if (options.failEvidence && evidenceBodies.length === 2) {
        return Response.json({ error: "d1_daily_budget_exhausted" }, { status: 503, headers: { "Retry-After": "60" } });
      }
      return evidence(options.failEvidence && evidenceBodies.length > 2 ? "new-snapshot" : "old-snapshot");
    }
    if (url.pathname === "/v3/hydration") {
      hydrationCalls++;
      return Response.json({ accepted: 8 }, { status: 202 });
    }
    if (url.pathname.endsWith("profile-analysis-catalog.json")) return Response.json({ catalog_version: "test" });
    throw new Error(`Unexpected request: ${url.pathname}`);
  }));
}

it("completes a 200-track report after resumption without repeating successful Last.fm calls", async () => {
  mockApi({ failPage: true });
  const { getBrowserAnalysis } = await import("../src/analysis/browser");
  const signal = new AbortController().signal;
  await expect(getBrowserAnalysis("alice", "1month", signal, vi.fn())).rejects.toMatchObject({ code: "lastfm_busy", retryAfter: 10 });
  expect(evidenceBodies).toHaveLength(0);
  await vi.advanceTimersByTimeAsync(10_000);
  const report = await getBrowserAnalysis("alice", "1month", signal, vi.fn(), true);
  expect(report.profile.tracks_analyzed).toBe(200);
  expect(report.profile.realname).toBe("Alice");
  expect(historyCalls).toEqual([1, 2, 3, 3, 4]);
  expect(metadataCalls).toBe(1);
  expect(evidenceBodies.map((body) => body.snapshot_version)).toEqual([undefined, "old-snapshot", "old-snapshot", "old-snapshot"]);
  expect(hydrationCalls).toBe(1);
  const { getHistoryResume } = await import("../src/analysis/history");
  expect(getHistoryResume("https://api.test")).toBeNull();
});

it("refreshes all evidence against one snapshot while reusing completed history after a D1 refusal", async () => {
  mockApi({ failEvidence: true });
  const { getBrowserAnalysis } = await import("../src/analysis/browser");
  const signal = new AbortController().signal;
  await expect(getBrowserAnalysis("alice", "1month", signal, vi.fn())).rejects.toMatchObject({ code: "d1_daily_budget_exhausted" });
  expect(hydrationCalls).toBe(0);
  await vi.advanceTimersByTimeAsync(60_000);
  const report = await getBrowserAnalysis("alice", "1month", signal, vi.fn(), true);
  expect(report.profile.tracks_analyzed).toBe(200);
  expect(report.snapshot.snapshot_version).toBe("new-snapshot");
  expect(historyCalls).toEqual([1, 2, 3, 4]);
  expect(metadataCalls).toBe(1);
  expect(evidenceBodies.slice(2).map((body) => body.snapshot_version)).toEqual([undefined, "new-snapshot", "new-snapshot", "new-snapshot"]);
  expect(hydrationCalls).toBe(1);
});
