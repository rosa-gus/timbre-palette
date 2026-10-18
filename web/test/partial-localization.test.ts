import { afterEach, expect, it, vi } from "vitest";
import { getInstrument } from "../src/api/client";
import { localizeAnalysis, LOCALIZATION_DEADLINE_MS } from "../src/i18n/resources";
import type { InstrumentResource, ProfileAnalysisV3 } from "../src/api/types";

vi.mock("../src/api/client", () => ({ getInstrument: vi.fn() }));
const lookup = vi.mocked(getInstrument);
const resource = (slug: string, locale = "en-US") => ({ slug, name: `Translated ${slug}`, locale, image: null }) as InstrumentResource;
function report(slugs: string[]): ProfileAnalysisV3 {
  return { profile: {}, track_palette: { families: slugs.map((slug) => ({ slug, name: `Original ${slug}`, share: 0.5, image: null })), discovery: null },
    artist_vocabulary: { families: [], featured_artists: [] } } as unknown as ProfileAnalysisV3;
}
afterEach(() => { vi.useRealTimers(); lookup.mockReset(); });

it("consolidates completed resources at one deadline even when a request ignores abort", async () => {
  vi.useFakeTimers();
  let complete!: (value: InstrumentResource) => void;
  const late = new Promise<InstrumentResource>((resolve) => { complete = resolve; });
  lookup.mockImplementation((slug) => slug === "deadline-ready" ? Promise.resolve(resource(slug)) : late);
  const source = report(["deadline-ready", "deadline-late", "deadline-queued-1", "deadline-queued-2", "deadline-queued-3"]);
  const original = JSON.stringify(source);
  const pending = localizeAnalysis(source, "en-US", new AbortController().signal);
  await vi.advanceTimersByTimeAsync(LOCALIZATION_DEADLINE_MS);
  const display = await pending;
  expect(display.track_palette.families[0].name).toBe("Translated deadline-ready");
  expect(display.track_palette.families[1].name).toBe("Original deadline-late");
  expect(display.localization.incomplete).toBe(true);
  expect(lookup.mock.calls.filter(([slug]) => slug !== "deadline-ready").every(([, signal]) => signal.aborted)).toBe(true);
  const settled = JSON.stringify(display);
  complete(resource("deadline-late"));
  await Promise.resolve(); await Promise.resolve();
  expect(JSON.stringify(display)).toBe(settled);
  expect(JSON.stringify(source)).toBe(original);
});

it("cancels a superseded presentation without waiting for the deadline", async () => {
  lookup.mockImplementation(() => new Promise(() => {}));
  const controller = new AbortController();
  const pending = localizeAnalysis(report(["cancelled"]), "en-US", controller.signal);
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
});

it("includes the discovery image subject and records the effective fallback locale", async () => {
  const source = report([]);
  source.track_palette.discovery = { instrument_slug: "image-sampler", instrument_name: "Sampler",
    image: { asset_id: "pads", depicted_instrument_slug: "image-pads", depicted_name: "Controlador", family_name: "Eletrônicos" } as never };
  lookup.mockImplementation(async (slug) => resource(slug, slug === "image-pads" ? "pt-BR" : "en-US"));
  const display = await localizeAnalysis(source, "en-US", new AbortController().signal);
  expect(lookup.mock.calls.map(([slug]) => slug)).toContain("image-pads");
  expect(display.track_palette.discovery?.image).toMatchObject({ depicted_name: "Translated image-pads", locale: "pt-BR" });
  expect(display.localization.localeBySlug["image-pads"]).toBe("pt-BR");
  expect(display.localization.incomplete).toBe(true);
});

it("retries localization without reusing a cached fallback or collecting history", async () => {
  lookup.mockResolvedValue(resource("retry", "pt-BR"));
  await localizeAnalysis(report(["retry"]), "en-US", new AbortController().signal);
  lookup.mockResolvedValue(resource("retry"));
  const display = await localizeAnalysis(report(["retry"]), "en-US", new AbortController().signal, true);
  expect(display.localization.incomplete).toBe(false);
  expect(lookup).toHaveBeenCalledTimes(2);
});
