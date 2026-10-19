import { afterEach, expect, it, vi } from "vitest";
import { getInstrumentResources } from "../src/api/client";
import { localizeAnalysis } from "../src/i18n/resources";
import type { InstrumentResource, ProfileAnalysisV3 } from "../src/api/types";

vi.mock("../src/api/client", () => ({ getInstrumentResources: vi.fn() }));
const lookup = vi.mocked(getInstrumentResources);
const resource = (slug: string, locale = "en-US") => ({ slug, name: `Translated ${slug}`, locale, image: null }) as InstrumentResource;
function report(slugs: string[]): ProfileAnalysisV3 {
  return { profile: {}, track_palette: { analysis: { section_availability: { discovery: "available" } }, families: slugs.map((slug) => ({ slug, name: `Original ${slug}`, share: 0.5, image: null })), discovery: null },
    artist_vocabulary: { families: [], featured_artists: [] } } as unknown as ProfileAnalysisV3;
}
afterEach(() => { vi.useRealTimers(); lookup.mockReset(); });

it("consolidates all resources from one bounded request", async () => {
  lookup.mockResolvedValue({
    requested_locale: "en-US",
    resources: [resource("deadline-ready")],
    missing: ["deadline-late", "deadline-queued-1", "deadline-queued-2", "deadline-queued-3"],
  });
  const source = report(["deadline-ready", "deadline-late", "deadline-queued-1", "deadline-queued-2", "deadline-queued-3"]);
  const original = JSON.stringify(source);
  const pending = localizeAnalysis(source, "en-US", new AbortController().signal);
  const display = await pending;
  expect(display.track_palette.families[0].name).toBe("Translated deadline-ready");
  expect(display.track_palette.families[1].name).toBe("Original deadline-late");
  expect(display.localization.incomplete).toBe(true);
  expect(lookup).toHaveBeenCalledWith(expect.arrayContaining(["deadline-ready", "deadline-late"]), expect.anything(), "en-US");
  expect(JSON.stringify(source)).toBe(original);
});

it("cancels a superseded presentation without waiting for the deadline", async () => {
  lookup.mockImplementation((_slugs, signal) => new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }));
  const controller = new AbortController();
  const pending = localizeAnalysis(report(["cancelled"]), "en-US", controller.signal);
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
});

it("keeps image subjects outside the editorial resource request", async () => {
  const source = report([]);
  source.track_palette.discovery = { instrument_slug: "image-sampler", instrument_name: "Sampler",
    image: { asset_id: "pads", depicted_instrument_slug: "image-pads", depicted_name: "Controlador", family_name: "Eletrônicos",
      variants: [{ url: "/pads.webp" }] } as never };
  lookup.mockResolvedValue({
    requested_locale: "en-US",
    resources: [resource("image-sampler")],
    missing: [],
  });
  const display = await localizeAnalysis(source, "en-US", new AbortController().signal);
  expect(lookup.mock.calls[0][0]).not.toContain("image-pads");
  expect(display.track_palette.discovery?.image).toMatchObject({
    depicted_name: "Controlador",
    asset_id: "pads",
  });
  expect(display.localization.localeBySlug["image-pads"]).toBeUndefined();
  expect(display.localization.incomplete).toBe(false);
});

it("does not mark an unavailable discovery section as partially localized", async () => {
  const source = report(["palette"]);
  source.track_palette.discovery = {
    instrument_slug: "hidden-discovery",
    instrument_name: "Hidden discovery",
    image: null,
  };
  source.track_palette.analysis = {
    section_availability: {
      discovery: "insufficient_coverage",
    },
  } as never;
  lookup.mockResolvedValue({
    requested_locale: "en-US",
    resources: [resource("palette")],
    missing: ["hidden-discovery"],
  });
  const display = await localizeAnalysis(
    source,
    "en-US",
    new AbortController().signal,
  );
  expect(lookup.mock.calls[0][0]).toContain("hidden-discovery");
  expect(display.localization.incomplete).toBe(false);
});

it("retries localization without reusing a cached fallback or collecting history", async () => {
  lookup.mockResolvedValue({ requested_locale: "en-US", resources: [resource("retry", "pt-BR")], missing: [] });
  await localizeAnalysis(report(["retry"]), "en-US", new AbortController().signal);
  lookup.mockResolvedValue({ requested_locale: "en-US", resources: [resource("retry")], missing: [] });
  const display = await localizeAnalysis(report(["retry"]), "en-US", new AbortController().signal, true);
  expect(display.localization.incomplete).toBe(false);
  expect(lookup).toHaveBeenCalledTimes(2);
});
