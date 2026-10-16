import { readFileSync } from "node:fs";
import { afterEach, expect, it, vi } from "vitest";
import { isProfileAnalysisV3 } from "../src/api/report-validation";

vi.mock("../src/i18n/runtime", () => { throw new Error("Analysis must not load UI dictionaries"); });
vi.mock("../src/api/runtime-config", () => ({ apiBaseUrl: () => "https://api.test" }));

afterEach(() => vi.unstubAllGlobals());

it("assembles reproducible structured reports without loading locales or contacting the API", async () => {
  const fixture = JSON.parse(readFileSync(new URL("../../reference/server-assembly/src/palette_api/_curated_example_history.json", import.meta.url), "utf8"));
  vi.stubGlobal("window", { location: { href: "https://web.test/" } });
  const fetch = vi.fn(async (input: string | URL) => {
    const path = new URL(String(input)).pathname;
    if (path.endsWith("profile-analysis-example.json")) return Response.json(fixture);
    if (path.endsWith("profile-analysis-catalog.json")) return Response.json({ catalog_version: "test" });
    throw new Error(`Unexpected collection request: ${input}`);
  });
  vi.stubGlobal("fetch", fetch);
  const { getBrowserExampleAnalysis } = await import("../src/analysis/browser");
  const signal = new AbortController().signal;
  const report = await getBrowserExampleAnalysis("1month", signal, "localization");
  expect(await getBrowserExampleAnalysis("1month", signal, "localization")).toEqual(report);
  expect(report.report_schema_version).toBe("profile-analysis-v3");
  expect(isProfileAnalysisV3(report)).toBe(true);
  expect(report.track_palette.analysis).not.toHaveProperty("notice");
  expect(report.artist_vocabulary).not.toHaveProperty("notice");
  expect(report.track_palette.temperament).toMatchObject({ rule: expect.any(String), primary_family_slug: expect.any(String) });
  expect(report.track_palette.temperament).not.toHaveProperty("summary");
  expect(report.track_palette.recordings.every((recording) => !("status_detail" in recording))).toBe(true);
  expect(fetch.mock.calls.every(([url]) => String(url).startsWith("https://web.test/"))).toBe(true);

  // Cached v2 prose and future or malformed selections cannot be consumed as v3 facts.
  expect(isProfileAnalysisV3({ ...report, report_schema_version: undefined })).toBe(false);
  expect(isProfileAnalysisV3({ ...report, report_schema_version: "profile-analysis-v4" })).toBe(false);
  for (const temperament of [
    { ...report.track_palette.temperament, rule: "unknown-rule" },
    { ...report.track_palette.temperament, primary_family_slug: "missing-family" },
    { title: "Legacy prose", summary: "Legacy prose", disclaimer: "Legacy prose" },
  ]) {
    expect(isProfileAnalysisV3({ ...report, track_palette: { ...report.track_palette, temperament } })).toBe(false);
  }
});
