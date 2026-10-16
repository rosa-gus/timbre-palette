import { afterEach, expect, it } from "vitest";
import { analyzeMessage, selectMessage } from "../../shared/i18n/messages.mjs";
import { setLocale, t, messageParts } from "../src/i18n/runtime";
import { renderMessageTypes, validateTranslation } from "../../scripts/generate_locale_types.mjs";

afterEach(async () => { await setLocale("pt-BR", { persist: false, updateUrl: false }); });

it.each(["en-US", "pt-BR"] as const)("renders zero, singular, plural and formatted counts in %s", async (locale) => {
  await setLocale(locale, { persist: false, updateUrl: false });
  const english = locale === "en-US";
  expect(t("report.trackCount", { tracks_analyzed: 0 })).toBe(english ? "0 tracks" : "0 faixas");
  expect(t("report.trackCount", { tracks_analyzed: 1 })).toBe(english ? "1 track" : "1 faixa");
  expect(t("report.trackCount", { tracks_analyzed: 2 })).toBe(english ? "2 tracks" : "2 faixas");
  expect(t("report.trackCount", { tracks_analyzed: 1234 })).toBe(english ? "1,234 tracks" : "1.234 faixas");
  expect(t("report.playCount", { total_plays: 1 })).toBe(english ? "1 play" : "1 reprodução");
  expect(t("vocabulary.recordingCount", { count: 1 })).toBe(english ? "1 distinct recording" : "1 gravação distinta");
  expect(t("history.loadedTracks", { tracks: 1, periodSuffix: " · month" })).toContain(english ? "1 track already loaded" : "1 faixa já carregada");
});

it("handles several independent counts while preserving markup and opaque parameters", async () => {
  await setLocale("en-US", { persist: false, updateUrl: false });
  const external = "{count, plural, one {injected} other {injected}} <value>external</value>";
  const parts = messageParts("report.vocals", { tracks: 1, artists: 2, plays: 1, ratio: external });
  expect(parts.filter((part) => part.wrapper).map((part) => part.text)).toEqual(["1", "2", "1", external]);
  expect(parts.map((part) => part.text).join("")).toContain("1 track, 2 artists, and 1 play");
  expect(t("vocabulary.unresolvedIdentities", { artists: 1, tracks: 0 })).toContain("1 artist and 0 tracks");
});

it("uses English plural rules for a missing Portuguese message while preserving number formatting", async () => {
  const catalog = (await import("../src/i18n/catalog.generated")).default;
  const original = catalog.report.trackCount;
  await setLocale("pt-BR", { persist: false, updateUrl: false });
  try {
    Reflect.deleteProperty(catalog.report, "trackCount");
    expect(t("report.trackCount", { tracks_analyzed: 0 })).toBe("0 tracks");
    expect(t("report.trackCount", { tracks_analyzed: 1234 })).toBe("1.234 tracks");
  } finally { catalog.report.trackCount = original; }
});

it("selects locale-specific categories, exact matches and nested plural branches", () => {
  const message = "{count, plural, one {single} few {few} many {many} other {other}}";
  expect(selectMessage(message, { count: 2 }, "ru").text).toBe("few");
  expect(selectMessage(message, { count: 5 }, "ru").text).toBe("many");
  const nested = "{a, plural, one {{b, plural, one {# item} other {# items}}} other {# groups}}";
  expect(selectMessage(nested, { a: 1, b: 2 }, "en-US").text).toBe("{b} items");
});

it.each([
  "{count, plural, one {# track}}",
  "{count, plural, other {# tracks}",
  "{count, plural, other {# tracks} other {duplicate}}",
  "{count, plural, unknown {bad} other {good}}",
  "{count, select, other {unsupported}}",
])("rejects malformed or unsupported message syntax: %s", (message) => {
  expect(() => analyzeMessage(message)).toThrow();
});

it("validates numeric selectors and matching contracts across every branch", () => {
  const plural = "{count, plural, one {# track} other {# tracks}}";
  expect(() => selectMessage(plural, { count: "1" }, "en-US")).toThrow("finite number");
  expect(() => selectMessage(plural, { count: NaN }, "en-US")).toThrow("finite number");
  expect(() => validateTranslation({ message: plural }, { message: "{count} faixas" })).toThrow();
  expect(() => renderMessageTypes(JSON.stringify({ message: "{count, plural, one {<value>#</value>} other {#}}" }))).toThrow("wrappers");
  expect(() => renderMessageTypes(JSON.stringify({ message: "{count, plural, one {} other {# items}}" }))).toThrow("Empty plural form");
  expect(renderMessageTypes(JSON.stringify({ message: plural }))).toContain('"message": "count";');
});
