import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { setLocale, resolveLocale, matchLocale, t, translation, messageParts, initializeLocale } from "../src/i18n/runtime";
import { setLocale as setEditorialLocale, t as editorialText, resolveLocale as resolveEditorialLocale, initializeLocale as initializeEditorialLocale } from "../../editorial/src/i18n/runtime";
import { formatNumber, formatDate, formatPercent, formatShareDate, formatRegisteredDate } from "../src/i18n/formatters";
import { getPortraitCopy } from "../src/analysis/presentation";
import { createShareImage } from "../src/sharing/share";
import { localizeAnalysis } from "../src/i18n/resources";

beforeEach(async () => {
  await setLocale("pt-BR", { persist: false, updateUrl: false });
  await setEditorialLocale("pt-BR", { persist: false, updateUrl: false });
});

afterEach(async () => {
  await setLocale("pt-BR", { persist: false, updateUrl: false });
  await setEditorialLocale("pt-BR", { persist: false, updateUrl: false });
  vi.unstubAllGlobals(); vi.restoreAllMocks();
});

it("resolves URL, saved preference, browser fallback and unsupported languages", () => {
  expect(resolveLocale("en", "pt-BR", ["pt-BR"])).toBe("en-US");
  expect(resolveLocale(null, "en-US", ["pt-BR"])).toBe("en-US");
  expect(resolveLocale("de", null, ["de", "en-GB"])).toBe("en-US");
  expect(resolveLocale("broken_tag", "bad", ["ja"])).toBe("en-US");
  expect(resolveLocale(null, null, [])).toBe("en-US");
  expect(resolveLocale(null, null, ["pt-BR", "en-US"])).toBe("pt-BR");
  expect(resolveLocale(null, null, ["ja", "pt-PT"])).toBe("pt-BR");
  expect(resolveEditorialLocale(null, null, ["ja"])).toBe("en-US");
  expect(resolveEditorialLocale(null, null, ["pt-BR"])).toBe("pt-BR");
  expect(matchLocale("PT-pt")).toBe("pt-BR");
});

it("switches independent UI catalogs, reactive text, semantic wrappers and formatting", async () => {
  await setLocale("en-US", { persist: false, updateUrl: false });
  expect(t("entry.profileLabel")).toBe("Your Last.fm profile");
  expect(get(translation)("profile.registered", { registeredLabel: "Jan. 2020" })).toBe("SCROBBLING SINCE Jan. 2020");
  expect(messageParts("entry.title").find((part) => part.wrapper)?.wrapper).toBe("emphasis");
  expect(formatNumber(1234.5)).toBe("1,234.5");
  expect(formatPercent(0.126, 1)).toBe("12.6%");
  expect(formatDate(new Date("2026-10-16T00:00:00Z"))).toBe("10/16/2026");
  expect(formatRegisteredDate("2026-01-01T00:00:00Z")).toBe("Jan. 2026");
  expect(formatShareDate(new Date(2026, 9, 16, 12))).toBe("OCT. 16, 2026");
  expect(editorialText("sheet.editLabel")).toBe("Editar ficha");
  await setEditorialLocale("en-US", { persist: false, updateUrl: false });
  expect(editorialText("sheet.editLabel")).toBe("Edit profile");
});

it("updates document language and metadata while keeping preference failures optional", async () => {
  const metadata = new Map<string, string>();
  vi.stubGlobal("document", { documentElement: { lang: "", dir: "" }, title: "",
    querySelector: (selector: string) => ({ setAttribute: (_name: string, value: string) => metadata.set(selector, value) }) });
  vi.stubGlobal("navigator", { languages: ["en-US"] });
  vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); } });
  await initializeLocale();
  expect(document.documentElement.lang).toBe("en-US");
  expect(document.title).toContain("Discover what your listening is made of");
  expect(metadata.get('meta[property="og:locale"]')).toBe("en_US");
});

it("localizes report display through catalog resources without fetching listening history or mutating facts", async () => {
  const source = { is_example: true, profile: { username: "example", period: "1month" },
    track_palette: { families: [{ slug: "percussion", name: "Percussão", share: 0.6, image: null }], discovery: null },
    artist_vocabulary: { families: [], featured_artists: [] } } as unknown as import("../src/api/types").ProfileAnalysisV3;
  const before = JSON.stringify(source);
  const fetch = vi.fn(async (url: string) => {
    expect(url).toContain("/v2/catalog/resources?locale=en-US");
    return Response.json({ requested_locale: "en-US", resources: [{ slug: "percussion", name: "Percussion", description: "Description", sound_production: "Sound", common_roles: [],
        related_slugs: [], sections: [], sources: [], further_reading: [], image: null, tone: null, locale: "en-US" }],
      missing: [] });
  });
  vi.stubGlobal("fetch", fetch);
  await setLocale("en-US", { persist: false, updateUrl: false });
  const display = await localizeAnalysis(source, "en-US", new AbortController().signal);
  expect(display.track_palette.families[0]).toMatchObject({ name: "Percussion", share: 0.6 });
  expect(display.profile.realname).toBe("Hercules Beetle");
  expect(JSON.stringify(source)).toBe(before);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("writes English narratives, coverage and disclosure into the exported image", async () => {
  await setLocale("en-US", { persist: false, updateUrl: false });
  const drawn: string[] = [];
  const context = { fillText: (value: string) => drawn.push(value), measureText: (value: string) => ({ width: value.length * 10 }),
    fillRect: vi.fn(), save: vi.fn(), restore: vi.fn(), drawImage: vi.fn(), fillStyle: "", font: "", globalAlpha: 1 };
  vi.stubGlobal("document", { documentElement: { lang: "en-US", dir: "ltr" }, fonts: { ready: Promise.resolve() },
    createElement: () => ({ getContext: () => context, toBlob: (callback: (blob: Blob) => void) => callback(new Blob(["png"])) }) });
  vi.stubGlobal("Image", class { src = ""; decode = async () => undefined; });
  vi.stubGlobal("window", { location: { href: "https://palette.test/?lang=en-US" } });
  const report = { profile: { username: "listener", period: "1month" }, analysis: { coverage_tracks: 0.5, data_source: "catalog" },
    families: [], temperament: null } as unknown as import("../src/api/types").PaletteReport;
  expect(getPortraitCopy(report).title).toBe("Your listening does not have a palette yet.");
  await createShareImage(report);
  const output = drawn.join(" ");
  expect(output).toContain("/ INSTRUMENTAL PALETTE");
  expect(output).toContain("Instrument information available for 50% of analyzed tracks.");
  expect(output).toContain("not a personality test");
  expect(output).not.toMatch(/<upper>|Interpretação|Informação/);
});

it("persists a manual selection and preserves report URL parameters", async () => {
  const replaceState = vi.fn();
  const setItem = vi.fn();
  vi.stubGlobal("window", { location: { href: "https://palette.test/?profile=listener&period=1month" }, history: { state: { report: true }, replaceState } });
  vi.stubGlobal("localStorage", { setItem });
  await setLocale("en-US");
  const url = replaceState.mock.calls[0][2] as URL;
  expect(url.searchParams.get("lang")).toBe("en-US");
  expect(url.searchParams.get("profile")).toBe("listener");
  expect(url.searchParams.get("period")).toBe("1month");
  expect(setItem).toHaveBeenCalledWith("app:v1:web:locale", "en-US");
});

it("initializes both interfaces in English when browser languages are unavailable or unsupported", async () => {
  vi.stubGlobal("navigator", { languages: ["ja-JP"] });
  vi.stubGlobal("localStorage", { getItem: () => null });
  await initializeLocale();
  await initializeEditorialLocale();
  expect(t("entry.profileLabel")).toBe("Your Last.fm profile");
  expect(editorialText("sheet.editLabel")).toBe("Edit profile");
});


it("falls back per key without changing the selected locale or losing other translations", async () => {
  const publicCatalog = (await import("../src/i18n/catalog.generated")).default;
  const editorCatalog = (await import("../../editorial/src/i18n/catalog.generated")).default;
  const publicLabel = publicCatalog.entry.profileLabel;
  const editorLabel = editorCatalog.sheet.editLabel;
  try {
    Reflect.deleteProperty(publicCatalog.entry, "profileLabel");
    editorCatalog.sheet.editLabel = "   ";
    expect(t("entry.profileLabel")).toBe("Your Last.fm profile");
    expect(editorialText("sheet.editLabel")).toBe("Edit profile");
    expect(t("example.displayName")).toBe("Besouro Hércules");
    expect((await import("../src/i18n/runtime")).locale).toBe("pt-BR");
    expect(messageParts("entry.profileLabel").map((part) => part.text).join("")).toBe("Your Last.fm profile");
  } finally {
    publicCatalog.entry.profileLabel = publicLabel;
    editorCatalog.sheet.editLabel = editorLabel;
  }
});


it.each([
  [{ language: "pt-BR" }, "pt-BR"],
  [{ languages: [], language: "pt-PT" }, "pt-BR"],
  [{ languages: undefined, language: "en-GB" }, "en-US"],
  [{}, "en-US"],
  [{ language: "ja-JP" }, "en-US"],
  [undefined, "en-US"],
  [{ languages: ["en-US"], language: "pt-BR" }, "en-US"],
] as const)("initializes both interfaces with incomplete browser preferences: %j", async (browser, expected) => {
  vi.stubGlobal("navigator", browser);
  vi.stubGlobal("localStorage", { getItem: () => null });
  await initializeLocale();
  await initializeEditorialLocale();
  expect((await import("../src/i18n/runtime")).locale).toBe(expected);
  expect((await import("../../editorial/src/i18n/runtime")).locale).toBe(expected);
});
